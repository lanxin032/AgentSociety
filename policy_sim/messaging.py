"""Trusted adapter for official SimpleSocialSpace transport and checkpointing.

Business envelopes remain in the domain; the official environment owns the only
transport mailbox. Checkpoints are permitted only at completed delivery barriers.
"""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json

from agentsociety2.contrib.env.simple_social_space import SimpleSocialSpace

from .io import canonical, digest, read_json, write_json
from .spec import ACTORS


class PolicyMailbox:
    def __init__(self, world):
        self.world = world
        self.native = SimpleSocialSpace(list(ACTORS.items()))
        self.receipts = []
        self.t = None
        self._failed = False

    async def init(self, t):
        await self.native.init(t)
        self.t = t
        await self.deliver(self.world, t)

    def _envelope(self, mid):
        message = self.world.messages[mid]
        if (message['id'] != mid or type(message['sender']) is not int
                or type(message['recipient']) is not int
                or message['sender'] not in ACTORS or message['recipient'] not in ACTORS):
            raise ValueError('Invalid business message identity')
        # Creation evidence is immutable; delivery/reply flags are business state.
        envelope = {k: deepcopy(v) for k, v in message.items()
                    if k not in ('delivered_round', 'replied')}
        creations = [e['message'] for e in self.world.events
                     if e['kind'] == 'message_created' and e['message']['id'] == mid]
        if len(creations) != 1 or envelope != {
                k: v for k, v in creations[0].items() if k not in ('delivered_round', 'replied')}:
            raise ValueError('Business envelope differs from creation evidence')
        return {'message_id': mid, 'envelope': envelope}

    def _check_receipts(self, receipts):
        seen = set()
        for receipt in receipts:
            mid = receipt['message_id']
            if mid in seen or mid not in self.world.messages:
                raise ValueError('Unknown or duplicate transport receipt')
            seen.add(mid)
            message = self.world.messages[mid]
            content = canonical(self._envelope(mid))
            expected_send = {'sender_id': message['sender'],
                             'receiver_id': message['recipient'], 'content': content}
            expected_receive = {'type': 'personal', 'sender_id': message['sender'],
                                'sender_name': ACTORS[message['sender']], 'content': content,
                                'timestamp': receipt['timestamp']}
            if (receipt['send'] != expected_send or receipt['receive'] != expected_receive
                    or receipt['content_sha256'] != digest(self._envelope(mid))
                    or receipt['round'] != message['delivered_round']
                    or receipt['round'] < message['deliver_round']):
                raise ValueError('Transport receipt differs from business delivery')
        if seen != {mid for mid, m in self.world.messages.items() if m['delivered_round'] is not None}:
            raise ValueError('Delivered business messages lack official receipts')

    async def deliver(self, world, t):
        if self._failed:
            raise RuntimeError('Mailbox failed; restore a completed checkpoint')
        if world is not self.world:
            raise ValueError('Mailbox is bound to a different world')
        try:
            self._check_receipts(self.receipts)
            self.t = t
            await self.native.init(t)
            due = world.pending_message_ids()
            # Validate every outbound envelope before any native send.
            contents = {mid: canonical(self._envelope(mid)) for mid in due}
            sent = {}
            for mid in due:
                m = world.messages[mid]
                result = await self.native.send_message(m['sender'], m['recipient'], contents[mid])
                sent[mid] = result.model_dump(mode='json')
                if sent[mid] != {'sender_id': m['sender'], 'receiver_id': m['recipient'],
                                 'content': contents[mid]}:
                    raise ValueError('Unexpected native send receipt')
            received = {}
            for actor in ACTORS:
                result = await self.native.receive_messages(actor)
                if result.agent_id != actor:
                    raise ValueError('Unexpected native recipient')
                for row in result.messages:
                    # The native receive API deliberately omits native message_id.
                    mid = json.loads(row['content'])['message_id']
                    if mid not in sent or mid in received:
                        raise ValueError('Unknown or duplicate native envelope')
                    m = world.messages[mid]
                    expected = {'type': 'personal', 'sender_id': m['sender'],
                                'sender_name': ACTORS[m['sender']], 'content': contents[mid],
                                'timestamp': t.isoformat()}
                    if m['recipient'] != actor or row != expected:
                        raise ValueError('Native envelope identity or content mismatch')
                    received[mid] = deepcopy(row)
            if set(received) != set(due):
                raise ValueError('Native delivery is incomplete')
            # Preserve business creation order, independent of recipient grouping.
            for mid in due:
                world.accept_delivery(mid)
                self.receipts.append({'message_id': mid, 'round': world.round,
                                      'timestamp': t.isoformat(),
                                      'content_sha256': digest(self._envelope(mid)),
                                      'send': sent[mid], 'receive': received[mid]})
        except BaseException:
            self._failed = True
            raise

    async def to_workspace(self, path):
        if self._failed or self.t is None:
            raise RuntimeError('Mailbox has no completed delivery barrier')
        self._check_receipts(self.receipts)
        for mid in self.world.messages:
            self._envelope(mid)
        path = Path(path)
        await self.native.to_workspace(path / 'native')
        native_state = read_json(path / 'native/state/ENV_STATE.json')
        self._check_native_checkpoint(native_state, len(self.receipts))
        write_json(path / 'TRANSPORT.json', {
            'schema': 'policy-mailbox-1', 'world_sha256': digest(self.world.export_state()),
            'native_sha256': digest(native_state), 'timestamp': self.t.isoformat(),
            'receipts': self.receipts})

    @staticmethod
    def _check_native_checkpoint(state, count):
        if (not set(state['mailboxes']) <= {str(k) for k in ACTORS}
                or any(state['mailboxes'].values()) or state['groups']
                or state['agent_names'] != {str(k): v for k, v in ACTORS.items()}
                or state['total_messages_sent'] != count
                or state['next_message_id'] != count + 1
                or state['next_group_id'] != 1 or state['step_counter'] != 0):
            raise ValueError('Native checkpoint is not a completed policy delivery barrier')

    async def restore(self, path):
        path = Path(path)
        metadata = path / 'TRANSPORT.json'
        native_path = path / 'native/state/ENV_STATE.json'
        if not metadata.exists() and not native_path.exists():
            return False
        data = read_json(metadata)
        state = read_json(native_path)
        if (data['schema'] != 'policy-mailbox-1'
                or data['world_sha256'] != digest(self.world.export_state())
                or data['native_sha256'] != digest(state)):
            raise ValueError('Mailbox checkpoint does not match world/native state')
        for mid in self.world.messages:
            self._envelope(mid)
        self._check_receipts(data['receipts'])
        self._check_native_checkpoint(state, len(data['receipts']))
        if not await self.native.restore(path / 'native'):
            raise ValueError('Missing official mailbox checkpoint')
        self.receipts = deepcopy(data['receipts'])
        self.t = datetime.fromisoformat(data['timestamp'])
        await self.native.init(self.t)
        self._failed = False
        return True
