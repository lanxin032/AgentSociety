"""Known-answer checks for rebuilt domain indices and delivery order."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from policy_sim.core import PolicyWorld


class DomainIndexTests(unittest.TestCase):
    def test_candidate_and_settlement_order_match_full_scan(self):
        from tests.test_sim_domain import finite_witness_action

        for zero in (False, True):
            with self.subTest(zero_friction=zero):
                world = PolicyWorld('000', seed=3001, config={'zero_communication_friction': zero})
                reference = PolicyWorld('000', seed=3001, config={'zero_communication_friction': zero})

                indexed_views = PolicyWorld._views_for

                def views(instance, actor, kind, oid):
                    if instance is reference:
                        return [row for row in instance.knowledge[str(actor)][kind].values()
                                if row['object'] == oid]
                    return indexed_views(instance, actor, kind, oid)

                with patch.object(PolicyWorld, '_views_for', new=views):
                    for _ in range(8):
                        due = [mid for mid, message in reference.messages.items()
                               if message['delivered_round'] is None and message['deliver_round'] <= reference.round]
                        self.assertEqual(world.pending_message_ids(), due)
                        for mid in due:
                            world.accept_delivery(mid)
                            reference.accept_delivery(mid)
                        for actor in (1, 2, 3, 4):
                            observation = world.observe(actor)
                            self.assertEqual(observation, reference.observe(actor))
                            action = finite_witness_action(observation)
                            self.assertEqual(world.submit(actor, action), reference.submit(actor, action))
                        world.advance()
                        reference.advance()
                        self.assertEqual(world.export_state(), reference.export_state())

    def test_pending_delivery_records_and_restore(self):
        world = PolicyWorld('000', seed=3001)
        first, second = list(world.tickets)[:2]
        r1 = world._record(first, 2, 'field_note', {'note': 'first'})
        r2 = world._record(second, 2, 'field_note', {'note': 'second'})
        r3 = world._record(first, 2, 'field_note', {'note': 'third'})

        later = world._message(2, 3, first, 'status_reply', {'records': [r1]})
        free = world._message(2, 3, first, 'status_reply', {'records': [r3, r1]}, free=True)
        other = world._message(2, 3, second, 'status_reply', {'records': [r2]})
        empty = world._message(2, 3, first, 'status_reply', {}, free=True)
        self.assertEqual(world.pending_message_ids(), [free, empty])
        self.assertEqual(world._legal_records(3, first), [])
        for mid in world.pending_message_ids():
            world.accept_delivery(mid)
        self.assertEqual([r['id'] for r in world._legal_records(3, first)], [r3['id'], r1['id']])
        self.assertEqual(world.knowledge['3']['inbox'], [free, empty])
        self.assertEqual(world.material_sources(3)['record:' + r1['id']]['received_round'], 0)
        self.assertEqual(world.material_sources(3)['ticket:' + first]['received_round'], 0)
        self.assertNotIn('record:' + r2['id'], world.material_sources(3))
        self.assertEqual(world.pending_message_ids(), [])

        def scan(actor, kind, oid):
            return [row for row in world.knowledge[str(actor)][kind].values() if row['object'] == oid]

        for actor in (1, 2, 3, 4):
            indexed = world.observe(actor)
            with patch.object(world, '_views_for', side_effect=scan):
                self.assertEqual(indexed, world.observe(actor))

        state = world.export_state()
        self.assertNotIn('_indices', state)
        injected = deepcopy(state)
        injected['_indices'] = {'records': 'forged'}
        restored = PolicyWorld.from_state(injected)
        self.assertEqual(restored.export_state(), state)
        for actor in (1, 2, 3, 4):
            self.assertEqual(restored.observe(actor), world.observe(actor))

        for instance in (world, restored):
            instance.advance()
            self.assertEqual(instance.pending_message_ids(), [later, other])
            for mid in instance.pending_message_ids():
                instance.accept_delivery(mid)
            self.assertEqual(instance.pending_message_ids(), [])
            self.assertEqual(instance.knowledge['3']['inbox'], [free, empty, later, other])
            self.assertEqual([r['id'] for r in instance._legal_records(3, first)], [r3['id'], r1['id']])
            sources = instance.material_sources(3)
            self.assertEqual(sources['record:' + r1['id']]['received_round'], 0)
            self.assertEqual(sources['record:' + r2['id']]['received_round'], 1)
            self.assertEqual(sources['ticket:' + second]['received_round'], 1)
        self.assertEqual(restored.export_state(), world.export_state())

    def test_task_snapshots_and_observation_match_full_scan(self):
        world = PolicyWorld('000', seed=3001)
        ticket = next(iter(world.tickets))
        definitions = world._case_definitions(ticket)
        world._send_assignment(1, 2, ticket, 'case_assignment', definitions, free=True)
        world.accept_delivery(world.pending_message_ids()[0])
        task_id = definitions[0]['id']
        known = deepcopy(world.knowledge['2']['tasks'][task_id])
        world.tasks[task_id]['state'] = 'completed'
        self.assertEqual(world.knowledge['2']['tasks'][task_id], known)
        self.assertEqual(known['state'], 'pending')

        def scan(actor, kind, oid):
            return [row for row in world.knowledge[str(actor)][kind].values() if row['object'] == oid]

        for actor in (1, 2, 3, 4):
            indexed = world.observe(actor)
            with patch.object(world, '_views_for', side_effect=scan):
                scanned = world.observe(actor)
            self.assertEqual(indexed, scanned)
        restored = PolicyWorld.from_state(world.export_state())
        self.assertEqual(restored.observe(2), world.observe(2))


if __name__ == '__main__':
    unittest.main()
