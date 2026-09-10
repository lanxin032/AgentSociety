from copy import deepcopy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid
import asyncio
from types import SimpleNamespace

from policy_v3.verify import VERSION, _hash, audit_decision_traces, audit_information_flow, audit_observation, recompute_events, verify_run, verify_state


def fixture_state():
    """Hand-calculated two-round episode history, independent of the simulator."""
    state = {'spec_version': VERSION, 'seed': 7, 'scenario': {'id': 'fixture'}, 'horizon': 2, 'round': 2,
             'config': {'labor_per_actor': 100, 'capital': 24, 'shared_crew_capacity': 2},
             'labor': {'1': 100., '2': 98.9, '3': 99.4, '4': 100.}, 'capital': 23.5,
             'pending': {}, 'burden': 22, 'issues': {}, 'events': []}
    def event(kind, r, **data):
        state['events'].append({'event_index': len(state['events']), 'round': r, 'kind': kind, **data})
    for i in range(12):
        iid, fid = f'I{i}', f'F{i}'
        state['issues'][iid] = {'id': iid, 'facility': fid, 'created': 0, 'resolved': None, 'initial': True}
        event('issue_created', 0, issue=iid, facility=fid, ticket=f'T{i}', initial=True)
    event('resource_spent', 0, actor_id=2, labor=1.1, capital=.5, crew=1)
    state['issues']['I0']['resolved'] = 1
    event('issue_resolved', 0, issue='I0', resolved_round=1)
    event('round_completed', 1, completed_round=1, settlement_unresolved=11, burden=11)
    for i in range(12):
        event('external_shock', 1, facility=f'F{i}', at_risk=(i == 0), draw=.01 if i == 0 else .99, probability=.1, root_repaired=False)
    state['issues']['I12'] = {'id': 'I12', 'facility': 'F0', 'created': 1, 'resolved': None, 'initial': False}
    event('issue_created', 1, issue='I12', facility='F0', ticket='T12', initial=False)
    event('resource_spent', 1, actor_id=3, labor=.6, capital=0, crew=1)
    state['issues']['I1']['resolved'] = 2
    event('issue_resolved', 1, issue='I1', resolved_round=2)
    event('round_completed', 2, completed_round=2, settlement_unresolved=11, burden=22)
    return state


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.tmp = self.root / ('test-v3-verify-' + uuid.uuid4().hex)
        self.tmp.mkdir()

    def tearDown(self):
        assert self.tmp.resolve().parent == self.root
        assert self.tmp.name.startswith('test-v3-verify-')
        shutil.rmtree(self.tmp)

    def test_independent_cohort_burden_resource_and_recurrence(self):
        result = verify_state(fixture_state(), replay=False)
        self.assertTrue(result['passed'], result['errors'])
        values = result['independently_recomputed']
        self.assertEqual(values['cumulative_issue_burden'], 22)
        self.assertEqual(values['initial_resolved'], 2)
        self.assertAlmostEqual(values['initial_censored_mean_time'], 23 / 12)
        self.assertEqual(values['new_issues'], 1)
        self.assertEqual(values['recurrent_episodes'], 1)
        self.assertEqual(values['shared_crew_units_spent'], 2)
        self.assertAlmostEqual(values['labor_spent'], 1.7)
        self.assertIsNone(values['tool_opportunities']['B']['offer_rate'])

    def test_self_consistent_reported_burden_tamper_still_fails_events(self):
        state = fixture_state()
        state['burden'] = 21
        state['events'][-1]['burden'] = 21
        result = verify_state(state, replay=False)
        self.assertFalse(result['passed'])
        self.assertEqual(result['independently_recomputed']['cumulative_issue_burden'], 22)

    def test_resource_event_tamper_cannot_hide_behind_remaining_balance(self):
        state = fixture_state()
        event = next(e for e in state['events'] if e['kind'] == 'resource_spent')
        event['labor'] = 2.1
        result = verify_state(state, replay=False)
        self.assertFalse(result['passed'])
        self.assertTrue(any('remaining labor' in e for e in result['errors']))

    def test_resource_round_capacity_not_just_total(self):
        state = fixture_state()
        event = next(e for e in state['events'] if e['kind'] == 'resource_spent')
        event['crew'] = 3
        self.assertTrue(any('capacity' in e for e in recompute_events(state)[1]))

    def test_duplicate_unresolved_facility_is_invalid(self):
        state = fixture_state()
        next(e for e in state['events'] if e['kind'] == 'issue_created' and e['issue'] == 'I12')['facility'] = 'F2'
        self.assertTrue(any('Multiple unresolved' in e for e in recompute_events(state)[1]))

    def test_partial_phase_and_missing_settlement_are_invalid(self):
        state = fixture_state()
        state['pending'] = {'1': {'kind': 'wait'}}
        state['events'].pop()
        errors = recompute_events(state)[1]
        self.assertTrue(any('Partial actor phase' in e for e in errors))
        self.assertTrue(any('completion' in e for e in errors))

    def test_whitelist_allows_lawful_root_findings_and_rejects_hidden_injection(self):
        legal = {'actor_id': 4, 'round': 2, 'visible_tickets': [], 'available_actions': [],
                 'received_findings': {'root': 'paid-investigation-result'}}
        self.assertEqual(audit_observation(legal, legal), [])
        leaked = {**legal, 'truth_required_departments': [2, 3]}
        self.assertTrue(audit_observation(legal, leaked))
        changed = deepcopy(legal)
        changed['received_findings']['root'] = 'not-the-received-result'
        self.assertTrue(audit_observation(legal, changed))

    def test_confirmation_record_does_not_authorize_early_delivery(self):
        record = {'id': 'r1', 'object': 'T1', 'author': 2, 'kind': 'joint_confirmation', 'created_round': 0, 'data': {'accepted': True}}
        message = {'id': 'm1', 'object': 'T1', 'sender': 2, 'recipient': 3, 'kind': 'ordinary_contact',
                   'created_round': 0, 'deliver_round': 1, 'delivered_round': None, 'free_service': False,
                   'payload': {'records': [record]}}
        state = {'config': {}, 'round': 1, 'events': [
            {'kind': 'record_created', 'round': 0, 'record': record},
            {'kind': 'message_created', 'round': 0, 'message': message},
            {'kind': 'message_delivered', 'round': 0, 'message': 'm1', 'delivery_round': 0, 'recipient': 3}]}
        self.assertTrue(any('delivery time' in e for e in audit_information_flow(state)))
        state['events'][-1].update(round=1, delivery_round=1)
        self.assertEqual(audit_information_flow(state), [])

    def test_public_llm_advice_may_disagree_with_fixture_without_privileged_input(self):
        ticket = {'id': 'T1', 'a_offered': True, 'lead': None, 'facility': 'F1', 'district': 'd1', 'text': 'ambiguous issue',
                  'category': 'water', 'recommendation': {'provenance': 'rule_fixture', 'candidates': [2, 3]}}
        expected = {'actor_id': 1, 'round': 0, 'visible_tickets': [ticket],
                    'public_rules': {'directory': {'2': 'water', '3': 'infrastructure'}},
                    'available_actions': [{'kind': 'route', 'target': 'T1', 'params': {'use_recommendation': True, 'department': 2}, 'reason': 'fixture'}]}
        actual = deepcopy(expected)
        material = {'ticket': {k: ticket[k] for k in ('text', 'category', 'district', 'facility')},
                    'directory': expected['public_rules']['directory']}
        actual['visible_tickets'][0]['recommendation'] = {'provenance': 'real_llm_visible_material_only',
            'model': 'deepseek-v4-flash', 'candidates': [3, 2], 'uncertain': True,
            'basis': 'Public text leaves uncertainty', 'input_sha256': _hash(material)}
        actual['available_actions'][0]['params']['department'] = 3
        self.assertEqual(audit_observation(expected, actual), [])
        actual['visible_tickets'][0]['recommendation']['input_sha256'] = 'wrong-public-input'
        self.assertTrue(audit_observation(expected, actual))

    def test_duplicate_sync_fee_and_failure_fee_are_invalid(self):
        payment = {'kind': 'resource_spent', 'round': 3, 'actor_id': 4, 'object_id': 'P1',
                   'reason': 'shared_record_maintenance', 'labor': .1, 'capital': 0, 'crew': 0}
        state = {'config': {'maintenance_cost': .1}, 'round': 4, 'events': [payment, deepcopy(payment),
                 {'kind': 'shared_update_failed', 'round': 3, 'object': 'P1'}]}
        errors = audit_information_flow(state)
        self.assertTrue(any('once per object' in e for e in errors))
        self.assertTrue(any('Failed sharing charged' in e for e in errors))

    def make_run(self, mode='scripted'):
        from policy_v3.runtime import code_manifest, MODEL_SETTINGS
        from tools.v3_driver import checkpoint_files
        state = fixture_state()
        run = self.tmp / 'run'
        run.mkdir()
        write = lambda p, value: p.write_text(json.dumps(value), encoding='utf-8')
        write(run / 'world.json', state)
        write(run / 'metrics.json', recompute_events(state)[0])
        frozen = {'version': VERSION, 'mode': mode, 'record': {'run_id': 'fixture'},
                  'seed': 7, 'horizon': 2, 'scenario': state['scenario'],
                  'code_manifest': code_manifest(self.root), 'request_settings': MODEL_SETTINGS}
        write(run / 'run_config.json', frozen)
        write(run / 'SOCIETY.json', {})
        write(run / 'SOCIETY_STEP.json', {'step_count': 2})
        (run / 'observations.jsonl').write_text('', encoding='utf-8')
        for actor in range(1, 5):
            actor_dir = run / 'agents' / str(actor)
            (actor_dir / 'state').mkdir(parents=True)
            write(actor_dir / 'AGENT.json', {'agent_id': actor, 'step_count': 2})
            write(actor_dir / 'state/business.json', {'history': [{'round': 1}]})
        write(run / 'committed.json', {'round': 2, 'world_sha256': _hash(state), 'files': checkpoint_files(run)})
        write(run / 'driver_latest.json', {'version': VERSION, 'mode': mode, 'source_manifest': frozen['code_manifest'],
              'ok': True, 'ray_shutdown': True, 'completed_steps': 2})
        receipt = {'version': VERSION, 'mode': mode, 'source_manifest': frozen['code_manifest'], 'model_settings': MODEL_SETTINGS,
                   'run_id': 'fixture', 'invocation_id': '001', 'status': 'complete', 'clean_commit': True,
                   'ray_shutdown': True, 'measured_rounds': 2, 'requested_steps': 2, 'committed_steps': 2, 'requests': 0}
        if mode == 'llm':
            receipt.update(budget_before={'requests': 16}, budget_after={'requests': 16})
        write(run / 'controller-001.json', receipt)
        return run

    def test_committed_hash_tamper_fails_before_replay(self):
        run = self.make_run()
        (run / 'metrics.json').write_text('{}')
        with patch('policy_v3.verify.replay_actions', side_effect=AssertionError('Must reject corrupt commit first')):
            result = verify_run(run)
        self.assertFalse(result['passed'])
        self.assertTrue(any('Checkpoint set changed' in e for e in result['errors']))

    def test_source_change_is_not_same_frozen_experiment(self):
        run = self.make_run()
        # Isolate source identity from the separately tested replay mechanism.
        with patch('policy_v3.verify.replay_actions', return_value=('mock-replay-hash', [])), \
             patch('policy_v3.runtime.code_manifest', return_value=[{'path': 'changed.py', 'sha256': 'different'}]):
            result = verify_run(run)
        self.assertFalse(result['passed'])
        self.assertTrue(any('Current source differs' in e for e in result['errors']))

    def test_llm_label_alone_cannot_be_verified_real_model_evidence(self):
        run = self.make_run(mode='llm')
        with patch('policy_v3.verify.replay_actions', return_value=('mock-replay-hash', [])):
            result = verify_run(run)
        self.assertFalse(result['passed'])
        self.assertTrue(any('no recorded real model responses' in e for e in result['errors']))

    def test_ninety_round_common_window_is_last_thirty(self):
        from policy_v3.core import PolicyWorld
        world = PolicyWorld(policy='000', seed=1001, horizon=90)
        for _ in range(90):
            for actor in (1, 2, 3, 4):
                world.submit(actor, {'kind': 'wait', 'target': None, 'params': {}, 'reason': 'fixture'})
            world.advance()
        values, errors = recompute_events(world.export_state())
        self.assertEqual(errors, [])
        self.assertEqual(values['cumulative_issue_burden'], 1080)
        self.assertEqual(values['common_window_burden'], 360)
        self.assertEqual(values['common_window_rounds'], 30)
        self.assertEqual(values['at_risk_facility_rounds'], 0)

    def test_actual_world_replay_preserves_asynchronous_submit_order(self):
        from policy_v3.core import PolicyWorld
        from policy_v3.scripted import scripted_action
        scenario = {'id': 'phase-test', 'horizon': 5, 'q': {'A': 0, 'B': 0, 'C': 0},
                    'schedule': [{'start': 0, 'end': 2, 'q': {'A': 0, 'B': 0, 'C': 0}},
                                 {'start': 2, 'end': 5, 'q': {'A': 1, 'B': 1, 'C': 1}}]}
        world = PolicyWorld(seed=1001, horizon=5, scenario=scenario)
        observations = []
        for r in range(5):
            for actor in (3, 1, 4, 2):
                obs = world.observe(actor)
                observations.append({'round': r, 'actor_id': actor, 'observation': obs})
                world.submit(actor, scripted_action(obs))
            world.advance()
        result = verify_state(world.export_state(), world.metrics(), observations)
        self.assertTrue(result['passed'], result['errors'])
        self.assertEqual(result['replay_hash'], result['state_sha256'])
        tampered = world.export_state()
        next(e for e in tampered['events'] if e['kind'] == 'action_result')['code'] = 'manufactured_success'
        self.assertFalse(verify_state(tampered)['passed'])

    def physical_world(self, shared=True):
        from test_v3_physical import PhysicalContracts
        helper = PhysicalContracts()
        world, pid, _ = helper.build(shared=shared)
        helper.commission(world, pid, expect='executed' if shared else 'business_rejected')
        return helper, world, pid

    def test_physical_effect_is_counted_before_administrative_acceptance(self):
        helper, world, pid = self.physical_world()
        result = verify_state(world.export_state(), world.metrics(), replay=False)
        self.assertTrue(result['passed'], result['errors'])
        m = result['independently_recomputed']
        self.assertEqual(m['source_repaired_facilities'], 3)
        self.assertEqual(m['projects_physically_effective'], 1)
        self.assertEqual(m['projects_completed'], 0)
        helper.act(world, 2, 'report_status', pid, recipient=4)
        helper.act(world, 4, 'accept_project', pid)
        result = verify_state(world.export_state(), world.metrics(), replay=False)
        self.assertTrue(result['passed'], result['errors'])
        self.assertEqual(result['independently_recomputed']['projects_administratively_accepted'], 1)
        self.assertEqual(result['independently_recomputed']['source_repaired_facilities'], 3)

    def test_physical_state_metric_and_activation_tampering_are_rejected(self):
        _, world, pid = self.physical_world()
        metrics = world.metrics()
        for metric in ('source_repaired_facilities', 'projects_physically_effective', 'projects_built', 'projects_commissioned', 'commissioning_labor'):
            with self.subTest(metric=metric):
                changed = deepcopy(metrics); changed[metric] += 1
                self.assertFalse(verify_state(world.export_state(), changed, replay=False)['passed'])
        for field, value in (('effective_at', 0), ('physical', 'not_commissioned'), ('administrative', 'accepted')):
            changed = world.export_state(); changed['projects'][pid][field] = value
            self.assertFalse(verify_state(changed, replay=False)['passed'])
        changed = world.export_state()
        next(e for e in changed['events'] if e['kind'] == 'physical_effect_activated')['kind'] = 'invented_notice'
        result = verify_state(changed, replay=False)
        self.assertFalse(result['passed'])
        self.assertTrue(any('activation' in e or 'risk' in e for e in result['errors']))

    def test_failed_and_cancelled_projects_are_competing_events_not_censored(self):
        helper, world, pid = self.physical_world(shared=False)
        result = verify_state(world.export_state(), world.metrics(), replay=False)
        self.assertTrue(result['passed'], result['errors'])
        delay = result['independently_recomputed']['project_stage_delays'][0]
        self.assertFalse(delay['built_to_effective_censored'])
        self.assertEqual(delay['built_to_effective_competing_event'], 'commissioning_failed')
        helper.act(world, 4, 'cancel_project', pid, reason_code='evidence_does_not_support')
        result = verify_state(world.export_state(), world.metrics(), replay=False)
        self.assertTrue(result['passed'], result['errors'])
        delay = result['independently_recomputed']['project_stage_delays'][0]
        self.assertFalse(delay['built_to_effective_censored'])
        self.assertEqual(delay['built_to_effective_competing_event'], 'cancelled')
        altered = deepcopy(world.metrics())
        altered['project_stage_delays'][0]['built_to_effective_censored'] = True
        self.assertFalse(verify_state(world.export_state(), altered, replay=False)['passed'])

    def decision_evidence(self, repair=False, idle=False):
        from policy_v3.core import PolicyWorld
        from policy_v3.llm import choose_action
        world = PolicyWorld('000', seed=3, horizon=2)
        observations, actions, histories, rows = [], [], {a: [] for a in range(1, 5)}, []
        class Client:
            def __init__(self, values): self.values = iter(values)
            async def call(self, *args, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(self.values)), finish_reason='stop')], usage={'prompt_tokens': 1, 'completion_tokens': 1})
        for r in range(2):
            for actor in range(1, 5):
                obs = world.observe(actor)
                observations.append({'round': r, 'actor_id': actor, 'observation': obs})
                option = next(x for x in obs['candidate_options'] if x['kind'] == 'wait')
                raw = json.dumps({'candidate_id': option['candidate_id'], 'reason': 'offline fixture'})
                values = ['not JSON', raw] if repair and (r, actor) == (0, 1) else [raw]
                trace = self.tmp / f'decision-{r}-{actor}.jsonl'
                automatic_idle = idle and not any(a['kind'] != 'wait' for a in obs['available_actions'])
                if automatic_idle:
                    action = {'kind': 'wait', 'target': None, 'params': {}, 'reason': '无可执行任务'}
                    rows.append({'round': r, 'actor_id': actor, 'idle': True})
                else:
                    action = asyncio.run(choose_action(Client(values), obs, histories[actor], trace))
                receipt = world.submit(actor, action)
                actions.append({'round': r, 'actor_id': actor, 'action': action, 'receipt': receipt})
                histories[actor].append({'round': r, 'action': action, 'receipt': receipt})
                if not automatic_idle:
                    rows.extend(json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines())
            world.advance()
        submissions = [e for e in world.events if e['kind'] == 'action_submitted']
        return rows, observations, actions, submissions

    def test_candidate_trace_decode_history_and_one_repair_are_auditable(self):
        rows, obs, actions, submissions = self.decision_evidence(repair=True)
        report, errors = audit_decision_traces(rows, obs, actions, 2, submissions)
        self.assertEqual(errors, [])
        self.assertEqual(report['decoded_action_pairs'], 8)
        self.assertEqual(report['decision_model_responses'], 9)
        self.assertIn('validation_error', rows[0])

    def test_trace_rejects_changed_decoded_action_stale_id_or_system(self):
        rows, obs, actions, submissions = self.decision_evidence()
        variants = []
        altered = deepcopy(rows); altered[0]['decoded_action']['reason'] = 'changed'; variants.append(altered)
        altered = deepcopy(rows); altered[4]['response'] = rows[0]['response']; variants.append(altered)
        altered = deepcopy(rows); altered[0]['messages'][0]['content'] = 'different system'; variants.append(altered)
        altered = deepcopy(rows); altered[0]['candidate_options'][0]['target'] = 'poison'; variants.append(altered)
        for altered in variants:
            self.assertTrue(audit_decision_traces(altered, obs, actions, 2, submissions)[1])
        changed_actions = deepcopy(actions); changed_actions[0]['action']['reason'] = 'not submitted'
        self.assertTrue(audit_decision_traces(rows, obs, changed_actions, 2, submissions)[1])

    def test_idle_trace_counts_no_model_response_and_binds_fixed_wait(self):
        rows, obs, actions, submissions = self.decision_evidence(idle=True)
        report, errors = audit_decision_traces(rows, obs, actions, 2, submissions)
        self.assertEqual(errors, [])
        idle_count = sum(row.get('idle') is True for row in rows)
        self.assertGreater(idle_count, 0)
        self.assertEqual(report['idle_action_pairs'], idle_count)
        self.assertEqual(report['decoded_action_pairs'], 8 - idle_count)
        self.assertEqual(report['decision_model_responses'], 8 - idle_count)
        changed = deepcopy(actions)
        idle_key = next((row['round'], row['actor_id']) for row in rows if row.get('idle'))
        next(row for row in changed if (row['round'], row['actor_id']) == idle_key)['action']['reason'] = 'altered'
        self.assertTrue(audit_decision_traces(rows, obs, changed, 2, submissions)[1])
        altered = deepcopy(rows)
        next(row for row in altered if row.get('idle'))['response'] = 'invented'
        self.assertTrue(audit_decision_traces(altered, obs, actions, 2, submissions)[1])

    def test_fake_idle_cannot_hide_executable_candidate(self):
        rows, obs, actions, submissions = self.decision_evidence(idle=True)
        item = next(x for x in obs if any(a['kind'] != 'wait' for a in x['observation']['available_actions']))
        key = (item['round'], item['actor_id'])
        altered = [row for row in rows if (row['round'], row['actor_id']) != key]
        altered.append({'round': key[0], 'actor_id': key[1], 'idle': True})
        errors = audit_decision_traces(altered, obs, actions, 2, submissions)[1]
        self.assertTrue(any('non-wait' in error for error in errors), errors)

    def test_trace_rejects_missing_failed_attempt_extra_retry_and_repair_feedback(self):
        rows, obs, actions, submissions = self.decision_evidence(repair=True)
        self.assertTrue(audit_decision_traces(rows[1:], obs, actions, 2, submissions)[1])
        altered = deepcopy(rows); altered[1]['messages'][-1]['content'] = 'pick the correct candidate for a better outcome'
        self.assertTrue(audit_decision_traces(altered, obs, actions, 2, submissions)[1])
        altered = deepcopy(rows); extra = deepcopy(altered[1]); extra['attempt'] = 2; altered.insert(2, extra)
        self.assertTrue(audit_decision_traces(altered, obs, actions, 2, submissions)[1])


if __name__ == '__main__':
    unittest.main()
