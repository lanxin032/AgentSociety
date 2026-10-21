"""Offline tests of the installed official transport; no model or Ray execution."""
import os
os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "offline")
os.environ.setdefault("AGENTSOCIETY_CODER_LLM_API_KEY", "offline")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from policy_sim.core import PolicyWorld
from policy_sim.io import digest, read_json, write_json

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
