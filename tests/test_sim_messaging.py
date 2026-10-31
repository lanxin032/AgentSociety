"""Offline tests of the installed official transport; no model or Ray execution."""
import os
os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "offline")
os.environ.setdefault("AGENTSOCIETY_CODER_LLM_API_KEY", "offline")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from policy_sim.core import PolicyWorld
from policy_sim.io import digest, read_json, write_json
from policy_sim.verify import audit_information_flow, replay_actions

try:
    from policy_sim.messaging import PolicyMailbox
except ModuleNotFoundError as exc:
    if exc.name and exc.name.split('.')[0] != 'agentsociety2':
        raise
    PolicyMailbox = None


@unittest.skipIf(PolicyMailbox is None, 'official agentsociety2 is not installed')
class OfficialMailboxTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.world = PolicyWorld('000')
        self.t = datetime(2026, 9, 14)
        self.mailbox = PolicyMailbox(self.world)
        await self.mailbox.init(self.t)

    def enqueue_and_advance(self):
        target = next(iter(self.world.tickets))
        self.world._message(1, 2, target, 'status_reply', {})
        for actor in (1, 2, 3, 4):
            self.world.submit(actor, next(a for a in self.world.observe(actor)['available_actions']
                                         if a['kind'] == 'wait'))
        self.world.advance()
        return target

    async def test_native_round_barrier_and_checkpoint_no_duplicate(self):
        target = self.enqueue_and_advance()
        self.assertFalse(self.world._access(2, target))
        await self.mailbox.deliver(self.world, self.t + timedelta(seconds=1))
        self.assertTrue(self.world._access(2, target))
        count = len(self.mailbox.receipts)
        self.assertGreater(count, 0)
        self.assertNotIn('message_id', self.mailbox.receipts[0]['receive'])
        snapshot = self.world.export_state()
        with tempfile.TemporaryDirectory() as temp:
            await self.mailbox.to_workspace(temp)
            native = read_json(Path(temp) / 'native/state/ENV_STATE.json')
            self.assertEqual(native['total_messages_sent'], count)
            self.assertFalse(any(native['mailboxes'].values()))
            restored_world = PolicyWorld.from_state(snapshot)
            restored = PolicyMailbox(restored_world)
            self.assertTrue(await restored.restore(temp))
            await restored.deliver(restored_world, self.t + timedelta(seconds=2))
            self.assertEqual(restored_world.export_state(), snapshot)
            self.assertEqual(len(restored.receipts), count)

    async def test_unknown_native_message_fails_before_domain_delivery(self):
        target = self.enqueue_and_advance()
        await self.mailbox.native.send_message(1, 2, '{"message_id":"unknown"}')
        with self.assertRaisesRegex(ValueError, 'Unknown or duplicate'):
            await self.mailbox.deliver(self.world, self.t)
        self.assertFalse(self.world._access(2, target))
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(RuntimeError):
            await self.mailbox.to_workspace(temp)

    async def test_mutated_domain_sender_is_rejected_before_native_send(self):
        self.enqueue_and_advance()
        message = next(iter(self.world.messages.values()))
        message['sender'] = 3
        with self.assertRaisesRegex(ValueError, 'creation evidence'):
            await self.mailbox.deliver(self.world, self.t)
        self.assertEqual(self.mailbox.native._total_messages_sent, 0)

    async def test_forged_native_sender_is_rejected_before_domain_delivery(self):
        target = self.enqueue_and_advance()
        original = self.mailbox.native.receive_messages

        async def forged(actor):
            result = await original(actor)
            if result.messages:
                result.messages[0]['sender_id'] = 3
            return result

        self.mailbox.native.receive_messages = forged
        with self.assertRaisesRegex(ValueError, 'identity or content'):
            await self.mailbox.deliver(self.world, self.t)
        self.assertFalse(self.world._access(2, target))

    async def test_restore_rejects_tampered_native_even_with_updated_hash(self):
        self.enqueue_and_advance()
        await self.mailbox.deliver(self.world, self.t)
        with tempfile.TemporaryDirectory() as temp:
            await self.mailbox.to_workspace(temp)
            path = Path(temp)
            state = read_json(path / 'native/state/ENV_STATE.json')
            state['agent_names']['2'] = 'impostor'
            write_json(path / 'native/state/ENV_STATE.json', state)
            metadata = read_json(path / 'TRANSPORT.json')
            metadata['native_sha256'] = digest(state)
            write_json(path / 'TRANSPORT.json', metadata)
            with self.assertRaisesRegex(ValueError, 'completed policy delivery barrier'):
                await PolicyMailbox(self.world).restore(path)

    async def test_pending_business_envelope_survives_native_restore(self):
        self.enqueue_and_advance()
        for m in self.world.messages.values():
            self.assertEqual(m['deliver_round'], self.world.round)
        with tempfile.TemporaryDirectory() as temp:
            await self.mailbox.to_workspace(temp)
            world = PolicyWorld.from_state(self.world.export_state())
            mailbox = PolicyMailbox(world)
            self.assertTrue(await mailbox.restore(temp))
            await mailbox.deliver(world, self.t)
            self.assertEqual(len(mailbox.receipts), len(world.messages))

    async def test_free_envelope_waits_for_official_barrier(self):
        target = next(iter(self.world.tickets))
        mid = self.world._message(1, 2, target, 'status_reply', {}, free=True)
        self.assertIsNone(self.world.messages[mid]['delivered_round'])
        await self.mailbox.deliver(self.world, self.t)
        self.assertEqual(self.world.messages[mid]['delivered_round'], 0)

    async def test_zero_friction_handoff_waits_for_official_receive(self):
        world = PolicyWorld('000', seed=3001, config={'zero_communication_friction': True})
        mailbox = PolicyMailbox(world)
        await mailbox.init(self.t)
        self.assertIn('整轮结算后', world.observe(2)['public_rules']['communication'])
        ticket = 'T:F1-1:0'

        def submit(actions):
            for actor in (1, 2, 3, 4):
                obs = world.observe(actor)
                kind, target, params = actions.get(actor, ('wait', None, {}))
                choice = next(a for a in obs['available_actions'] if a['kind'] == kind
                              and a['target'] == target
                              and all(a['params'].get(k) == v for k, v in params.items()))
                choice = {k: choice[k] for k in ('kind', 'target', 'params', 'reason')}
                self.assertEqual(world.submit(actor, choice)['status'], 'queued')

        async def settle(actions):
            submit(actions)
            world.advance()
            await mailbox.deliver(world, self.t + timedelta(seconds=world.round))

        await settle({1: ('route', ticket, {'department': 2})})
        await settle({2: ('inspect', ticket, {})})
        task2, task3 = (f'K:{ticket}:{actor}' for actor in (2, 3))
        self.assertEqual(world.knowledge['2']['tasks'][task3]['state'], 'pending')
        # Settle actor 3 first: the dependent actor 2 must still wait for receive.
        while (world.round + int(world._random('settlement_start') * 3)) % 3 != 1:
            await settle({})
        submit({2: ('work', task2, {}), 3: ('work', task3, {})})
        original_record = world._record
        at_creation = []

        def record(*args):
            result = original_record(*args)
            if result['kind'] == 'task_completed':
                at_creation.append((result['id'] in world.knowledge['3']['records'],
                                    result['id'] in world.knowledge['2']['records']))
            return result

        with patch.object(world, '_record', side_effect=record):
            world.advance()
        self.assertEqual(at_creation, [(True, False)])
        self.assertEqual(world.observe(2)['last_receipt']['code'], 'prerequisites_or_received_handoff_missing')
        receipt = next(r for r in world.records.values() if r['kind'] == 'task_completed'
                       and r['data']['task']['id'] == task3)
        self.assertNotIn(receipt['id'], world.knowledge['2']['records'])
        handoffs = [m for m in world.messages.values() if receipt in m['payload'].get('records', [])]
        self.assertEqual([m['recipient'] for m in handoffs], [2])
        self.assertTrue(handoffs[0]['free_service'])

        original_receive = mailbox.native.receive_messages

        async def receive(actor):
            result = await original_receive(actor)
            self.assertNotIn(receipt['id'], world.knowledge['2']['records'])
            return result

        with patch.object(mailbox.native, 'receive_messages', side_effect=receive):
            await mailbox.deliver(world, self.t + timedelta(seconds=world.round))
        self.assertTrue(any(r['message_id'] == handoffs[0]['id'] for r in mailbox.receipts))
        self.assertIn(receipt['id'], world.knowledge['2']['records'])
        self.assertEqual(world.knowledge['2']['tasks'][task3]['state'], 'completed')
        self.assertEqual(world.material_sources(2)['record:' + receipt['id']]['received_round'], world.round)
        self.assertEqual(world.material_sources(3)['record:' + receipt['id']]['received_round'], receipt['created_round'])
        state = world.export_state()
        self.assertEqual(audit_information_flow(state), [])
        self.assertEqual(replay_actions(state)[1], [])
        forged = deepcopy(state)
        forged['events'].append({'kind': 'zero_friction_shared', 'round': world.round,
                                 'record': receipt['id'], 'recipients': [1]})
        forged['knowledge']['1']['records'][receipt['id']] = deepcopy(receipt)
        self.assertIn('Record sharing requires a received business message', audit_information_flow(forged))
        early = deepcopy(state)
        delivery = next(e for e in early['events'] if e['kind'] == 'message_delivered'
                        and e['message'] == handoffs[0]['id'])
        delivery['round'] = delivery['delivery_round'] = handoffs[0]['deliver_round'] - 1
        self.assertIn('Message arrived outside its recorded delivery time or recipient', audit_information_flow(early))

    async def test_future_message_does_not_arrive_early(self):
        target = next(iter(self.world.tickets))
        mid = self.world._message(1, 2, target, 'status_reply', {})
        with self.assertRaisesRegex(ValueError, 'not due'):
            self.world.accept_delivery(mid)
        await self.mailbox.deliver(self.world, self.t)
        self.assertFalse(self.world._access(2, target))
        self.assertEqual(self.mailbox.receipts, [])

    async def test_restore_rejects_modified_receipt(self):
        self.enqueue_and_advance()
        await self.mailbox.deliver(self.world, self.t)
        with tempfile.TemporaryDirectory() as temp:
            await self.mailbox.to_workspace(temp)
            path = Path(temp) / 'TRANSPORT.json'
            data = read_json(path)
            data['receipts'][0]['receive']['sender_id'] = 3
            write_json(path, data)
            with self.assertRaisesRegex(ValueError, 'receipt differs'):
                await PolicyMailbox(self.world).restore(temp)
