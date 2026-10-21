"""Known-answer visibility corruptions, independent of builder equality replay."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from policy_sim.audit_visibility import audit_visibility
from policy_sim.core import PolicyWorld
from tests.test_sim_domain import finite_witness_action, deliver_pending


class VisibilityAuditTests(unittest.TestCase):
    def setUp(self):
        self.world = PolicyWorld('000', seed=3001)

    def settle(self, actor=4, kind='wait', target=None, **params):
        for current in (1, 2, 3, 4):
            observation = self.world.observe(current)
            action = next(a for a in observation['available_actions']
                          if a['kind'] == (kind if current == actor else 'wait')
                          and (current != actor or target is None or a['target'] == target)
                          and (current != actor or all(a['params'].get(k) == v for k, v in params.items())))
            self.world.submit(current, action)
        self.world.advance()
        deliver_pending(self.world)

    def private_new_revision(self):
        proposal = finite_witness_action(self.world.observe(4))
        for actor in (1, 2, 3, 4):
            action = proposal if actor == 4 else next(a for a in self.world.observe(actor)['available_actions'] if a['kind'] == 'wait')
            self.world.submit(actor, action)
        self.world.advance()
        deliver_pending(self.world)
        for kind in ('confirm_project_lead', 'diagnose_project', 'draft_plan'):
            self.settle(kind=kind, target='P:1')
        self.settle(kind='request_review', target='P:1', department=2)
        self.settle(kind='draft_plan', target='P:1')
        return self.world.observe(2), self.world.export_state()

    def test_private_revision_and_stale_pending_task_are_lawful(self):
        observation, state = self.private_new_revision()
        self.assertEqual(observation['projects'][0]['revision'], 1)
        self.assertEqual(state['projects']['P:1']['revision'], 2)
        task = observation['projects'][0]['tasks'][0]
        self.assertEqual(task['state'], 'pending')
        self.assertEqual(state['tasks'][task['id']]['state'], 'cancelled')
        before = deepcopy((observation, state))
        with patch.object(PolicyWorld, 'observe', side_effect=AssertionError('must not call builder')), patch.object(PolicyWorld, '_visible_project', side_effect=AssertionError('must not call builder')):
            audit_visibility(observation, state)
        self.assertEqual((observation, state), before)
        audit_visibility(json.loads(json.dumps(observation)), json.loads(json.dumps(state)))
        for actor in (1, 3, 4):
            audit_visibility(self.world.observe(actor), state)

    def test_summaries_follow_received_version_even_when_owner_has_newer_plan(self):
        self.private_new_revision()
        knowledge = self.world.knowledge['2']
        for actor in (2, 3):
            task = deepcopy(next(iter(knowledge['tasks'].values())))
            task.update(id=f'known-build-{actor}', kind='implement_project', actor=actor,
                        state='completed', completed_round=1)
            knowledge['tasks'][task['id']] = task
        record = {'id': 'known-commission', 'object': 'P:1', 'author': 2,
                  'kind': 'commissioning_result', 'created_round': 1,
                  'data': {'revision': 1, 'success': True, 'effective_at': 2}}
        knowledge['records'][record['id']] = deepcopy(record)
        self.world.records[record['id']] = deepcopy(record)
        observation, state = self.world.observe(2), self.world.export_state()
        self.assertEqual(observation['projects'][0]['revision'], 1)
        self.assertEqual(observation['projects'][0]['construction'], 'built')
        self.assertEqual(observation['projects'][0]['physical'], 'effective')
        audit_visibility(observation, state)
        observation['projects'][0]['construction'] = 'unknown'
        with self.assertRaisesRegex(ValueError, 'construction'):
            audit_visibility(observation, state)

    def test_hidden_revision_is_rejected(self):
        observation, state = self.private_new_revision()
        observation['projects'][0]['revision'] = 2
        with self.assertRaisesRegex(ValueError, 'revision'):
            audit_visibility(observation, state)

    def test_unreceived_record_is_rejected(self):
        observation, state = self.private_new_revision()
        hidden = next(r for r in state['records'].values() if r['object'] == 'P:1' and r['kind'] == 'proposed_plan' and r['data']['revision'] == 2)
        observation['projects'][0]['received_records'].append(deepcopy(hidden))
        with self.assertRaisesRegex(ValueError, 'provenance'):
            audit_visibility(observation, state)

    def test_global_task_status_is_not_a_received_update(self):
        observation, state = self.private_new_revision()
        observation['projects'][0]['tasks'][0]['state'] = 'cancelled'
        with self.assertRaisesRegex(ValueError, 'tasks provenance'):
            audit_visibility(observation, state)

    def test_owner_field_injection_is_rejected(self):
        observation, state = self.private_new_revision()
        observation['projects'][0]['plan'] = state['projects']['P:1']['plan']
        with self.assertRaisesRegex(ValueError, 'field boundary'):
            audit_visibility(observation, state)

    def test_unknown_summaries_and_owner_fact_corruption(self):
        observation, state = self.private_new_revision()
        self.assertEqual(observation['projects'][0]['physical'], 'unknown')
        observation['projects'][0]['physical'] = 'effective'
        with self.assertRaisesRegex(ValueError, 'physical'):
            audit_visibility(observation, state)
        owner = self.world.observe(4)
        owner['projects'][0]['plan'] = 'fabricated'
        with self.assertRaisesRegex(ValueError, 'plan'):
            audit_visibility(owner, state)


if __name__ == '__main__':
    unittest.main()
