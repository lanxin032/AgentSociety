import json
import unittest
from copy import deepcopy

from policy_v3 import PolicyWorld, scripted_action
from policy_v3.spec import COMMUNICATION_KINDS


def play(world, rounds=None):
    for _ in range(world.horizon - world.round if rounds is None else rounds):
        choices = {actor: scripted_action(world.observe(actor)) for actor in (1, 2, 3, 4)}
        for actor, action in choices.items():
            world.submit(actor, action)
        world.advance()
    return world


class V3CoreContracts(unittest.TestCase):
    def test_fixture_reports_mixed_capacity_and_completion_records(self):
        wait = {'kind': 'wait', 'target': None, 'params': {}, 'reason': 'test'}
        reports = [{'kind': 'report_status', 'target': 'P:test', 'params': {'recipient': a}, 'reason': 'test'} for a in (2, 4)]
        obstacle = {'id': 'obstacle', 'author': 3, 'kind': 'capacity_obstacle', 'data': {'task': 'predecessor'}}
        completion = {'id': 'done', 'author': 3, 'kind': 'task_completed', 'data': {'task': {'id': 'predecessor'}}}
        project = {'id': 'P:test', 'received_records': [obstacle], 'tasks': [
            {'id': 'dependent', 'actor': 2, 'kind': 'implement_project', 'state': 'pending', 'prerequisites': ['predecessor']}]}
        obs = {'actor_id': 3, 'available_actions': [wait] + reports, 'projects': [project], 'visible_tickets': []}
        # A string-valued obstacle is reportable, but is not a completion handoff.
        self.assertEqual(scripted_action(obs)['params']['recipient'], 4)
        project['received_records'].append(completion)
        self.assertEqual(scripted_action(obs)['params']['recipient'], 2)

    def test_balanced_world_and_fewer_roots(self):
        w = PolicyWorld(seed=13)
        self.assertEqual(len(w.initial_ids), 12)
        self.assertEqual([sum(f['archetype'] == a for f in w.facilities.values()) for a in range(4)], [3] * 4)
        self.assertEqual(sum(f['clear_text'] for f in w.facilities.values()), 6)
        self.assertEqual(sum(f['dependent'] for f in w.facilities.values()), 3)
        less = PolicyWorld(seed=13, scenario={'environment': 'fewer_shared_roots'})
        self.assertEqual(sum(f['shared_root'] for f in less.facilities.values()), 3)
        self.assertEqual(sum(len(f['case_actors']) == 2 for f in less.facilities.values()), 6)

    def test_observation_pure_and_hides_physical_roots(self):
        w = PolicyWorld()
        before = w.export_state()
        for actor in (1, 2, 3, 4):
            obs = w.observe(actor)
            self.assertEqual(obs, w.observe(actor))
            text = json.dumps(obs)
            self.assertNotIn('shared_root', text)
            self.assertNotIn('root_repaired', text)
            self.assertNotIn('archetype', text)
        self.assertEqual(before, w.export_state())

    def test_completion_receipt_supersedes_later_assignment_template(self):
        w = PolicyWorld()
        task = next(iter(w.tasks.values()))
        w.round = 8
        w._assign(2, task['object'], [w._task_definition(task)])
        view = {**w._task_definition(task), 'state': 'completed', 'completed_round': 4, 'opinion': None, 'as_of_round': 4}
        w._learn(2, {'id': 'test-receipt', 'object': task['object'], 'author': 3, 'kind': 'task_completed', 'created_round': 4, 'data': {'task': view}})
        self.assertEqual(w.knowledge['2']['tasks'][task['id']]['state'], 'completed')

    def test_undelivered_closure_does_not_change_observation(self):
        w = PolicyWorld()
        ticket = next(iter(w.tickets.values()))
        w._grant(2, ticket['id'])
        before = w.observe(2)
        ticket['closed'] = True
        self.assertEqual(before, w.observe(2))
        w._record(ticket['id'], 3, 'issue_closed', {'resolved_round': 1})
        self.assertEqual(before, w.observe(2))
        record = next(iter(w.records.values()))
        w._learn(2, record)
        self.assertTrue(w.observe(2)['visible_tickets'][0]['closed'])

    def test_zero_friction_removes_manual_communication_actions(self):
        for policy in ('000', '111'):
            w = play(PolicyWorld(policy, horizon=18, scenario={'environment': 'zero_communication_friction'}))
            for actor in (1, 2, 3, 4):
                self.assertFalse(COMMUNICATION_KINDS & {a['kind'] for a in w.observe(actor)['available_actions']})
            self.assertEqual(w.metrics()['communication_labor'], 0)

    def test_ordinary_and_structured_complete_real_projects(self):
        for policy in ('000', '111'):
            w = play(PolicyWorld(policy, seed=0, horizon=42))
            self.assertGreaterEqual(w.metrics()['projects_completed'], 1)
            self.assertGreaterEqual(w.metrics()['source_repaired_facilities'], 3)
            for project in w.projects.values():
                if project['state'] == 'completed':
                    tasks = [t for t in w.tasks.values() if t['object'] == project['id'] and t['kind'] == 'implement_project']
                    self.assertEqual({t['actor'] for t in tasks}, {2, 3})
                    self.assertTrue(all(t['state'] == 'completed' for t in tasks))

    def test_snapshot_resume_exact(self):
        w = play(PolicyWorld(seed=2, horizon=12), 6)
        copy = PolicyWorld.from_state(json.loads(json.dumps(w.export_state())))
        play(w)
        play(copy)
        self.assertEqual(w.export_state(), copy.export_state())
        bad = deepcopy(w.export_state())
        bad['schema_version'] = 'policy-mve-1.2'
        with self.assertRaises(ValueError):
            PolicyWorld.from_state(bad)

    def test_resources_never_negative_and_crew_resets(self):
        w = play(PolicyWorld(seed=4, horizon=24, scenario={'environment': 'tight_resources'}))
        self.assertGreaterEqual(w.capital, 0)
        self.assertTrue(all(v >= 0 for v in w.labor.values()))
        for r in range(w.round):
            self.assertLessEqual(sum(e.get('crew', 0) for e in w.events if e['round'] == r and e['kind'] == 'resource_spent'), 1)

    def test_phase_uniform_draw_stable(self):
        q = {tool: 0 for tool in 'ABC'}
        w = PolicyWorld(scenario={'horizon': 3, 'q': q, 'schedule': [{'start': 1, 'end': 3, 'q': {tool: 1 for tool in 'ABC'}}]})
        before = deepcopy(w.opportunities)
        w.advance()
        for key, entry in before.items():
            self.assertEqual(entry['u'], w.opportunities[key]['u'])
        self.assertEqual(w._q('A'), 1)


if __name__ == '__main__':
    unittest.main()
