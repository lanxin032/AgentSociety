"""Offline legal witness: existence of a path, not evidence of model performance."""
from copy import deepcopy
import json
import unittest

from policy_sim.core import PolicyWorld
from policy_sim.scripted import scripted_action
from policy_sim.interface import decode_material_read
from policy_sim.materials import apply_read


def finite_witness_action(observation):
    """Uses only the actor's supplied permissioned observation, never world truth."""
    obs = deepcopy(observation)
    if obs['actor_id'] == 4:
        for p in obs['projects']:
            if p.get('state') in ('planned', 'under_review') and p.get('received_reviews') == {2: 'approve', 3: 'approve'}:
                return next(a for a in obs['available_actions'] if a['kind'] == 'request_budget' and a['target'] == p['id'])
        # Remember concluded investigations: no reason to repeat the same proposal.
        done = {p['topic'] for p in obs['projects'] if p.get('state') in ('cancelled', 'completed', 'failed')}
        obs['materials']['raw'] = [r for r in obs['materials']['raw'] if r['kind'] != 'contact' or r['data']['district'] + '|' + r['data']['category'] not in done]
    return scripted_action(obs)


def deliver_pending(world):
    """Pure-domain witness fixture; production delivery belongs to PolicyMailbox."""
    for mid, message in world.messages.items():
        if message["delivered_round"] is None and message["deliver_round"] <= world.round:
            world.accept_delivery(mid)


def run_witness(world, max_steps=250, actor4_delay=0):
    deliver_pending(world)
    physical_before_acceptance = False
    for _ in range(max_steps):
        for actor in (1, 2, 3, 4):
            obs = world.observe(actor)
            action = (next(a for a in obs['available_actions'] if a['kind'] == 'wait')
                      if actor == 4 and world.round < actor4_delay else finite_witness_action(obs))
            assert world.submit(actor, action)['status'] == 'queued'
        world.advance()
        deliver_pending(world)
        status = world.completion_status()
        if not status["required_shared_root_repairs"] and status["required_administrative_acceptance"]:
            physical_before_acceptance = True
            assert not status["complete"]
        if status['complete']:
            assert physical_before_acceptance, "witness must observe physical completion before administrative acceptance"
            assert not any(e["kind"] == "action_result" and e["status"] != "executed" for e in world.events), "witness must use executable business actions"
            return world.round
    raise AssertionError(world.completion_status())


class FiniteWorldTests(unittest.TestCase):
    def test_project_revision_follows_delivery_and_stale_task_still_queues(self):
        world = self.make_world()

        def pick(obs, kind, target=None, **params):
            return deepcopy(next(a for a in obs['available_actions'] if a['kind'] == kind
                                 and (target is None or a['target'] == target)
                                 and all(a['params'].get(k) == v for k, v in params.items())))

        def settle(actor=4, kind='wait', target=None, **params):
            for current in (1, 2, 3, 4):
                obs = world.observe(current)
                action = pick(obs, kind, target, **params) if current == actor else pick(obs, 'wait')
                self.assertEqual(world.submit(current, action)['status'], 'queued')
            world.advance()
            deliver_pending(world)

        proposal = finite_witness_action(world.observe(4))
        self.assertEqual(proposal['kind'], 'propose_project')
        self.assertEqual(world.submit(4, proposal)['status'], 'queued')
        for actor in (1, 2, 3):
            world.submit(actor, pick(world.observe(actor), 'wait'))
        world.advance()
        deliver_pending(world)
        pid = 'P:1'
        for kind in ('confirm_project_lead', 'diagnose_project', 'draft_plan'):
            settle(kind=kind, target=pid)
        settle(kind='request_review', target=pid, department=2)
        old_task = 'J:P:1:1:review_project:2'
        before = world.observe(2)['projects'][0]
        self.assertEqual(before['revision'], 1)
        settle(kind='draft_plan', target=pid)
        snapshot = world.export_state()
        after = world.observe(2)['projects'][0]
        self.assertEqual(after, before)
        self.assertEqual(world.observe(4)['projects'][0]['revision'], 2)
        self.assertEqual(world.export_state(), snapshot, 'observation must not mutate world events or state')
        self.assertEqual(world.tasks[old_task]['state'], 'cancelled')
        settle(actor=2, kind='review_project', target=old_task, opinion='approve')
        self.assertEqual(world.observe(2)['last_receipt']['code'], 'task_not_pending')
        settle(kind='request_review', target=pid, department=2)
        delivered = world.observe(2)['projects'][0]
        self.assertEqual(delivered['revision'], 2)
        self.assertEqual([r['data']['revision'] for r in delivered['received_records']
                          if r['kind'] == 'proposed_plan'], [1, 2])
        self.assertTrue(any(t['revision'] == 2 for t in delivered['tasks']))

    def test_completed_review_is_delivered_to_project_lead(self):
        # attempt-0064/0065 regression: a review opinion exists in the world but
        # only its author learns the record, so the lead waits forever for an
        # already-completed review. The opinion must travel the official
        # delivery channel and reach the lead's lawful view after receive.
        world = self.make_world()

        def pick(obs, kind, target=None, **params):
            return deepcopy(next(a for a in obs['available_actions'] if a['kind'] == kind
                                 and (target is None or a['target'] == target)
                                 and all(a['params'].get(k) == v for k, v in params.items())))

        def settle(actor=4, kind='wait', target=None, **params):
            for current in (1, 2, 3, 4):
                obs = world.observe(current)
                action = pick(obs, kind, target, **params) if current == actor else pick(obs, 'wait')
                self.assertEqual(world.submit(current, action)['status'], 'queued')
            world.advance()
            deliver_pending(world)

        proposal = finite_witness_action(world.observe(4))
        self.assertEqual(proposal['kind'], 'propose_project')
        world.submit(4, proposal)
        for actor in (1, 2, 3):
            world.submit(actor, pick(world.observe(actor), 'wait'))
        world.advance()
        deliver_pending(world)
        pid = 'P:1'
        for kind in ('confirm_project_lead', 'diagnose_project', 'draft_plan'):
            settle(kind=kind, target=pid)
        # attempt-0066 regression: after a redraft the lead must not see the
        # undispatched template review tasks as pending while none requested.
        lead_view = world.observe(4)['projects'][0]
        self.assertEqual(lead_view['requested']['review_project'], [])
        self.assertFalse([t for t in lead_view['tasks']
                          if t['kind'] == 'review_project' and t['state'] == 'pending'],
                        'undispatched template review tasks must stay invisible to the lead')
        self.assertEqual(world._received_reviews(4, world.projects[pid]), {})
        settle(kind='request_review', target=pid, department=2)
        lead_view = world.observe(4)['projects'][0]
        visible_owners = [t['actor'] for t in lead_view['tasks']
                          if t['kind'] == 'review_project' and t['state'] == 'pending']
        self.assertEqual(visible_owners, [2], 'dispatched review becomes visible; undispatched stays hidden')
        task = 'J:P:1:1:review_project:2'
        self.assertEqual(world._received_reviews(4, world.projects[pid]), {})
        settle(actor=2, kind='review_project', target=task, opinion='approve')
        self.assertEqual(world.observe(2)['last_receipt']['status'], 'executed')
        self.assertEqual(world._received_reviews(4, world.projects[pid]), {2: 'approve'},
                         'review opinion must reach the lead through delivery')
        lead_inbox = world.observe(4)['inbox']
        self.assertTrue(any(m['payload'].get('records') and any(
            r['kind'] == 'review_completed' for r in m['payload']['records']) for m in lead_inbox))

    def test_project_summaries_use_received_revision_without_hidden_filtering(self):
        world = self.make_world()
        # Known-answer fixture: one delivered v1 package, a private owner v2.
        project = {'id': 'P:fixture', 'revision': 2, 'topic': 'fixture', 'mode': 'conventional',
                   'b_required': False, 'b_registered': False}
        world.projects[project['id']] = project
        knowledge = world.knowledge['2']
        for actor in (2, 3):
            knowledge['tasks'][f'review-{actor}'] = {
                'object': project['id'], 'kind': 'review_project', 'revision': 1,
                'actor': actor, 'state': 'completed', 'opinion': 'approve'}
            knowledge['tasks'][f'build-{actor}'] = {
                'object': project['id'], 'kind': 'implement_project', 'revision': 1,
                'actor': actor, 'state': 'completed', 'completed_round': 0}
        knowledge['records']['commission'] = {
            'object': project['id'], 'kind': 'commissioning_result',
            'data': {'revision': 1, 'success': True, 'effective_at': 0}}
        view = world._visible_project(2, project)
        self.assertEqual(view['revision'], 1)
        self.assertEqual(world._received_reviews(2, project), {2: 'approve', 3: 'approve'})
        self.assertEqual((view['construction'], view['built_at']), ('built', 0))
        self.assertEqual((view['physical'], view['effective_at']), ('effective', 0))
        knowledge['records']['plan-v2'] = {
            'object': project['id'], 'kind': 'proposed_plan', 'data': {'revision': 2}}
        view = world._visible_project(2, project)
        self.assertEqual(view['revision'], 2)
        self.assertEqual(world._received_reviews(2, project), {})
        self.assertEqual((view['construction'], view['physical']), ('unknown', 'unknown'))
        self.assertEqual(len(view['tasks']), 4, 'old delivered tasks remain visible')

    def test_missing_submissions_settle_unfiled_without_fabrication(self):
        world = self.make_world()
        world.submit(1, next(a for a in world.observe(1)['available_actions'] if a['kind'] == 'wait'))
        world.submit(2, next(a for a in world.observe(2)['available_actions'] if a['kind'] == 'wait'))
        world.submit(3, next(a for a in world.observe(3)['available_actions'] if a['kind'] == 'wait'))
        world.advance()  # actor 4 never submitted
        self.assertEqual(world.round, 1)
        receipts = [e for e in world.events if e['kind'] == 'action_result']
        unfiled = [e for e in receipts if e.get('status') == 'unfiled']
        self.assertEqual([e['actor_id'] for e in unfiled], [4])
        self.assertEqual(unfiled[0]['receipt']['code'], 'actor_turn_failed')
        # No fabricated wait: the unfiled actor has no executed or rejected action.
        self.assertFalse(any(e['actor_id'] == 4 and e.get('action') for e in receipts))

    def make_world(self, **kwargs):
        return PolicyWorld('000', seed=3001, workload_mode='finite', horizon=None, **kwargs)

    def test_wait_after_sixty_and_persistent_sources(self):
        world = self.make_world(config={'labor_per_actor': 0, 'capital': 0})
        initial = world.material_sources(4)
        for _ in range(65):
            for actor in (1, 2, 3, 4):
                obs = world.observe(actor)
                self.assertEqual(world.submit(actor, next(a for a in obs['available_actions'] if a['kind'] == 'wait'))['status'], 'queued')
            world.advance()
            deliver_pending(world)
        self.assertEqual(world.round, 65)
        self.assertEqual(len(world.issues), 12)
        self.assertEqual(len(world.contacts), 12)
        self.assertTrue(set(initial) <= world.material_sources(4).keys())
        self.assertEqual(world.observe(4)['materials']['window_start'], 0)
        self.assertTrue(any(a['kind'] == 'propose_project' for a in world.observe(4)['available_actions']))
        self.assertFalse(any(e['kind'] in ('external_shock', 'repeat_contact', 'resource_spent') for e in world.events))
        run_witness(world)
        self.assertTrue(world.completion_status()['complete'])

    def test_baseline_legal_witness_requires_roots_and_acceptance(self):
        world = self.make_world(config={'labor_per_actor': 0, 'capital': 0})
        # Local closure does not imply shared-root repair or administrative success.
        for _ in range(90):
            for actor in (1, 2, 3):
                world.submit(actor, finite_witness_action(world.observe(actor)))
            world.submit(4, next(a for a in world.observe(4)['available_actions'] if a['kind'] == 'wait'))
            world.advance()
            deliver_pending(world)
        status = world.completion_status()
        self.assertEqual(status['remaining_local_cases'], [])
        self.assertFalse(status['complete'])
        self.assertEqual(len(status['required_shared_root_repairs']), 2)
        self.assertEqual(len(status['required_administrative_acceptance']), 2)
        run_witness(world)
        self.assertTrue(world.completion_status()['complete'])
        self.assertEqual(len(world.issues), 12)
        self.assertTrue(all(world.tickets['T' + iid[1:]]['closed'] for iid in world.initial_ids))
        for actor in (1, 2, 3, 4):
            obs = world.observe(actor)
            self.assertNotIn('complete', obs)
            self.assertNotIn('root_repaired', json.dumps(obs))
            self.assertNotIn('workload_mode', obs)
            self.assertNotIn('costs', obs['public_rules'])
            self.assertEqual(obs['resources'], {'availability': '当前作业所需资源可用'})
        self.assertIsNone(world.metrics()['normalized_burden'])

    def test_unlimited_reads_retain_source_permissions(self):
        world = self.make_world()
        obs = world.observe(4)
        sid = obs['materials']['source_index'][0]['source_id']
        for _ in range(5):
            ids = decode_material_read({'read_materials': [sid], 'reason': '核查原文'}, obs)
            obs = apply_read(obs, world.read_materials(4, ids))
        self.assertEqual(obs['materials']['reads_used'], 5)
        with self.assertRaises(ValueError):
            decode_material_read({'read_materials': [sid], 'reason': '核查'}, world.observe(2))
    def test_c_analysis_and_cancelled_topic_remain_available(self):
        world = PolicyWorld('001', seed=3001, workload_mode='finite', horizon=None)
        def settle():
            for actor in (1, 2, 3, 4):
                if str(actor) not in world.pending:
                    world.submit(actor, next(a for a in world.observe(actor)['available_actions'] if a['kind'] == 'wait'))
            world.advance()
            deliver_pending(world)
        for _ in range(65):
            settle()
        inputs = world.material_service_inputs(4)
        self.assertEqual(len([s for s in inputs[0]['sources'] if s['kind'] == 'contact']), 12)
        obs = world.observe(4)
        proposal = scripted_action(obs)
        self.assertEqual(proposal['kind'], 'propose_project')
        world.submit(4, proposal); settle()
        project_id = next(iter(world.projects))
        for kind in ('confirm_project_lead', 'diagnose_project'):
            obs = world.observe(4)
            world.submit(4, next(a for a in obs['available_actions'] if a['kind'] == kind)); settle()
        obs = world.observe(4)
        world.submit(4, next(a for a in obs['available_actions'] if a['kind'] == 'cancel_project' and a['params']['reason_code'] == 'evidence_does_not_support'))
        settle()
        self.assertEqual(world.projects[project_id]['state'], 'cancelled')
        world.submit(4, proposal); settle()
        self.assertEqual(len(world.projects), 2)

    def test_only_finite_checkpoints_and_no_horizon(self):
        world = self.make_world()
        state = world.export_state()
        restored = PolicyWorld.from_state(json.loads(json.dumps(state)), workload_mode='finite')
        self.assertEqual(restored.export_state(), state)
        for kwargs in ({'workload_mode': 'historical'}, {'horizon': 60}):
            with self.assertRaises(ValueError):
                PolicyWorld(**kwargs)
        state.pop('workload_mode')
        with self.assertRaises(ValueError):
            PolicyWorld.from_state(state)

    def test_static_scenario_none_horizon(self):
        world = self.make_world(scenario={'horizon': None, 'q': {'A':0,'B':0,'C':0}})
        self.assertTrue(world.finite_workload)
        with self.assertRaises(ValueError):
            self.make_world(scenario={'horizon': None, 'schedule': [{'start':0, 'end':60,'q':{'A':0,'B':0,'C':0}}]})

from policy_sim.interface import decode_candidate_choice, decorate_observation
from policy_sim.materials import analysis_value, fixture_analysis, validate_analysis
from policy_sim.normalization import normalize_decision, normalize_service, verify_normalization

class NormalizationTests(unittest.TestCase):
    def test_repeated_legal_reads_keep_candidates_and_full_context_evidence(self):
        world = PolicyWorld('000', seed=3001)
        obs = world.observe(4)
        ids = [obs['materials']['source_index'][0]['source_id']]
        original_options = obs['candidate_options']
        wait = next(o for o in original_options if o['kind'] == 'wait')
        for _ in range(4):
            before_hash = obs['context_sha256']
            allowed = decode_material_read({'read_materials': ids, 'reason': '复核全文'}, obs)
            result = world.read_materials(4, allowed)
            obs = apply_read(obs, result)
            self.assertEqual(obs['candidate_options'], original_options)
            self.assertNotEqual(obs['context_sha256'], before_hash)
            self.assertIn(result['sources'][0], obs['materials']['raw'])
            self.assertEqual(decode_candidate_choice(
                {'candidate_id': wait['candidate_id'], 'reason': '等待结算'}, obs)['kind'], 'wait')
        with self.assertRaises(ValueError):
            decode_material_read({'read_materials': ids, 'reason': '越权'}, world.observe(2))

    def test_inline_delivery_copy_is_stable_but_new_delivery_is_not(self):
        world = PolicyWorld('000', seed=3001)
        route = next(a for a in world.observe(1)['available_actions']
                     if a['kind'] == 'route' and a['params']['department'] == 2)
        world.submit(1, route)
        for actor in (2, 3, 4):
            world.submit(actor, next(a for a in world.observe(actor)['available_actions'] if a['kind'] == 'wait'))
        world.advance()
        deliver_pending(world)
        obs = world.observe(2)
        sid = 'ticket:' + route['target']
        self.assertIn(sid, obs['materials']['delivered_raw_ids'])
        self.assertFalse(any(r['source_id'] == sid for r in obs['materials']['raw']))
        after = apply_read(obs, world.read_materials(2, [sid]))
        self.assertEqual(after['candidate_options'], obs['candidate_options'])
        self.assertNotEqual(after['context_sha256'], obs['context_sha256'])
        self.assertTrue(any(r['source_id'] == sid for r in after['materials']['raw']))

        world = PolicyWorld('100', seed=3001)
        obs = world.observe(1)
        sid = obs['materials']['source_index'][0]['source_id']
        self.assertNotIn(sid, obs['materials']['delivered_raw_ids'])
        after = apply_read(obs, world.read_materials(1, [sid]))
        self.assertNotEqual(after['candidate_options'], obs['candidate_options'])
        self.assertEqual(apply_read(after, world.read_materials(1, [sid]))['candidate_options'],
                         after['candidate_options'])

    def test_candidate_ids_reject_changed_actor_round_actions_and_business_state(self):
        obs = PolicyWorld('000', seed=3001).observe(1)
        option = next(o for o in obs['candidate_options'] if o['kind'] == 'route')
        choice = {'candidate_id': option['candidate_id'], 'reason': '派单'}
        mutations = [
            lambda o: o.update(actor_id=2),
            lambda o: o.update(round=o['round'] + 1),
            lambda o: o['available_actions'].pop(),
            lambda o: o['visible_tickets'][0].update(closed=True),
            lambda o: o['materials']['source_index'][0].update(version='changed'),
        ]
        for mutate in mutations:
            changed = deepcopy(obs)
            mutate(changed)
            with self.subTest(mutation=mutations.index(mutate)), self.assertRaises(ValueError):
                decode_candidate_choice(choice, changed)
        # Audit binding still covers the exact body, not only source versions.
        changed = deepcopy(obs)
        changed['materials']['raw'][0]['data']['text'] = 'tampered body'
        self.assertNotEqual(decorate_observation(changed)['context_sha256'], obs['context_sha256'])

    def test_wrapper_and_redundant_fields_keep_exact_action(self):
        obs = PolicyWorld('000', seed=3001).observe(1)
        option = next(o for o in obs['candidate_options'] if o['kind'] == 'route')
        value = {**option, 'reason': '依据本人收到的职责和工单'}
        normalized, steps = normalize_decision(json.dumps({'action': value}), obs)
        expected = {'candidate_id': option['candidate_id'], 'reason': value['reason']}
        self.assertEqual(normalized, expected)
        self.assertEqual(decode_candidate_choice(normalized, obs)['params'], option['params'])
        trace = {'response': json.dumps({'action': value}), 'normalized_response': normalized,
                 'normalization': steps}
        self.assertEqual(verify_normalization(trace, obs), expected)
        bad = deepcopy(trace)
        bad['normalization'] = []
        with self.assertRaises(ValueError):
            verify_normalization(bad, obs)

    def test_conflicts_duplicate_keys_and_hash_typos_are_never_guessed(self):
        obs = PolicyWorld('000', seed=3001).observe(1)
        option = next(o for o in obs['candidate_options'] if o['kind'] == 'route')
        choice = {'candidate_id': option['candidate_id'], 'reason': '有依据'}
        bad = [json.dumps({**choice, 'kind': 'wait'}),
               json.dumps({**choice, 'params': {'department': True}}),
               json.dumps({'action': choice, 'reason': 'ambiguous'}),
               json.dumps({'action': {'action': choice}}),
               json.dumps({**choice, 'extra': 'unknown'}),
               json.dumps({**choice, 'candidate_id': option['candidate_id'][:-1]}),
               '{"candidate_id":"x","candidate_id":"y","reason":"duplicate"}']
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                value, _ = normalize_decision(raw, obs)
                decode_candidate_choice(value, obs)

    def test_topic_aliases_do_not_merge_or_rewrite_hypotheses(self):
        world = PolicyWorld('001', seed=3001)
        obs = world.observe(4)
        option = next(o for o in obs['candidate_options'] if o['kind'] == 'propose_project')
        material = world.material_service_inputs(4)[0]
        canonical = analysis_value(fixture_analysis(material))
        topic = canonical['topics'][0]
        params = {'source_ids': [i.split(':', 1)[1] for i in topic['source_ids']],
                  'hypothesis': topic['hypothesis']}
        raw = json.dumps({**option, 'params': params, 'reason': '先提出假设后调查'})
        value, _ = normalize_decision(raw, obs)
        self.assertEqual(value['analysis']['source_ids'], topic['source_ids'])
        self.assertEqual(value['analysis']['hypothesis'], topic['hypothesis'])
        conflicting = json.loads(raw)
        conflicting['analysis'] = {**params, 'hypothesis': '另一个假设'}
        with self.assertRaises(ValueError):
            normalize_decision(json.dumps(conflicting), obs)
        aliased = deepcopy(canonical)
        for t in aliased['topics']:
            t['source_ids'] = [i.split(':', 1)[1] for i in t['source_ids']]
        normalized, _ = normalize_service(json.dumps(aliased), material)
        self.assertEqual(normalized, canonical)
        duplicate = deepcopy(canonical)
        duplicate['topics'].append(deepcopy(duplicate['topics'][0]))
        normalized, _ = normalize_service(json.dumps(duplicate), material)
        with self.assertRaisesRegex(ValueError, 'Duplicate C topic'):
            validate_analysis(normalized, material, provenance='test')

    def test_alias_collisions_and_unavailable_sources_are_rejected(self):
        obs = PolicyWorld('000', seed=3001).observe(4)
        index = obs['materials']['source_index']
        index.extend([{'source_id': 'ticket:same'}, {'source_id': 'record:same'}])
        with self.assertRaises(ValueError):
            normalize_decision('{"read_materials":["same"],"reason":"ambiguous"}', obs)
        value, _ = normalize_decision('{"read_materials":["not-supplied"],"reason":"missing"}', obs)
        from policy_sim.interface import decode_material_read
        with self.assertRaises(ValueError):
            decode_material_read(value, obs)
