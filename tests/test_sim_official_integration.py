"""The native mailbox must carry real business handoffs, not just exist unused."""
import unittest
import json
from unittest.mock import patch
try:
    from tests import test_sim_framework as framework
except ImportError:
    import test_sim_framework as framework
from agentsociety2.contrib.env.simple_social_space import SimpleSocialSpace


class NativeHandoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_business_assignment_uses_official_send_and_receive(self):
        fixture = framework.FrameworkTests("test_official_lifecycle_four_finished_barrier_and_restore")
        await fixture.asyncSetUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.addCleanup(fixture.no_network.stop)
        sent, received = [], []
        original_send = SimpleSocialSpace.send_message
        original_receive = SimpleSocialSpace.receive_messages
        async def send(space, *args, **kwargs):
            result = await original_send(space, *args, **kwargs)
            row = result.model_dump(mode="json")
            envelope = json.loads(row["content"])["envelope"]
            if envelope["kind"] == "ticket_assignment":
                self.assertFalse(fixture.router.world._access(envelope["recipient"], envelope["object"]),
                                 "Initial assignment granted knowledge before official receive")
            sent.append(row)
            return result
        async def receive(space, *args, **kwargs):
            result = await original_receive(space, *args, **kwargs)
            received.extend(result.messages)
            return result
        with patch.object(SimpleSocialSpace, "send_message", send), patch.object(SimpleSocialSpace, "receive_messages", receive):
            for actor in fixture.actors:
                await actor.step(1, fixture.now)
            await fixture.accept_results()
            await fixture.router.step(1, fixture.now)
            self.assertTrue(sent, "Business assignment bypassed the official mailbox")
            self.assertTrue(received, "Business knowledge was granted without an official receive")
            assignment = next(json.loads(row["content"]) for row in sent
                              if json.loads(row["content"])["envelope"]["kind"] == "ticket_assignment")
            message = fixture.router.world.messages[assignment["message_id"]]
            self.assertEqual(message["delivered_round"], 1)
            self.assertTrue(fixture.router.world._access(message["recipient"], message["object"]))
