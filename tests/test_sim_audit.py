"""Known-answer completion, information-boundary and payment regressions."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import uuid
from policy_sim.core import PolicyWorld
from policy_sim.verify import verify_state, recompute_completion, valid_native_chunk
from policy_sim.audit_materials import audit_projection, _material_for_observation
from policy_sim.usage import summarize_native_usage
from policy_sim.audit import compare_system_tokens
from policy_sim.evidence import append_model_event


class PhysicalAuditTests(unittest.TestCase):
    def test_all_unfiled_round_replays_without_fabricated_submissions(self):
        world = PolicyWorld('000')
        observations = [{'round': 0, 'actor_id': actor, 'observation': world.observe(actor)}
                        for actor in (1, 2, 3, 4)]
        world.advance()
        result = verify_state(world.export_state(), world.metrics(), observations)
        self.assertTrue(result['passed'], result['errors'])
        self.assertFalse(any(e['kind'] == 'action_submitted' for e in world.events))

    def test_unfinished_physics_does_not_certify_workload(self):
        world = PolicyWorld('000')
        result = verify_state(world.export_state(), world.metrics())
        self.assertTrue(result['passed'], result['errors'])
        self.assertFalse(result['workload_complete'])
        self.assertEqual(len(result['completion_status']['remaining_local_cases']), 12)

    def test_local_closure_does_not_replace_roots_or_acceptance(self):
        state = PolicyWorld('000').export_state()
        for iid in state['issues']:
            tid = next(t for t, value in state['tickets'].items() if value['issue'] == iid)
            state['tickets'][tid]['closed'] = True
            state['events'] += [{'kind': 'issue_resolved', 'issue': iid},
                                {'kind': 'record_created', 'record': {'kind': 'issue_closed', 'object': tid}}]
        for tid, task in state['tasks'].items():
            task['state'] = 'completed'
            state['events'].append({'kind': 'task_completed', 'task': tid})
        result, errors = recompute_completion(state)
        self.assertFalse(errors)
        self.assertFalse(result['complete'])
        self.assertTrue(result['required_shared_root_repairs'])
        self.assertTrue(result['required_administrative_acceptance'])

    def test_forged_resource_and_completion_events_fail(self):
        state = PolicyWorld('000').export_state()
        state['events'].append({'event_index': len(state['events']), 'round': 0, 'kind': 'resource_spent', 'actor_id': 1, 'labor': 0, 'capital': 0, 'crew': 0})
        self.assertFalse(verify_state(state, replay=False)['passed'])
        state = PolicyWorld('000').export_state()
        state['tickets'][next(iter(state['tickets']))]['closed'] = True
        self.assertFalse(verify_state(state)['passed'])

    def test_actor_phase_barrier_and_projection_tampering(self):
        world = PolicyWorld('000')
        obs = world.observe(1)
        altered = deepcopy(obs)
        altered['hidden_true_cause'] = 'privileged'
        self.assertTrue(audit_projection(obs, altered))
        action = next(a for a in obs['available_actions'] if a['kind'] == 'wait')
        world.submit(1, action)
        state = world.export_state()
        self.assertFalse(verify_state(state)['passed'])

    def test_blocked_candidates_annotate_and_rejections_carry_unmet_detail(self):
        # attempt-0062 regression: a prerequisite-blocked work candidate must
        # say so in-band, and its settlement rejection must name the unmet
        # handoff — the actor's lawful view, never the world's hidden state.
        world = PolicyWorld('000')
        route = next(a for a in world.observe(1)['available_actions']
                     if a['kind'] == 'route' and a['target'] == 'T:F1-1:0' and a['params']['department'] == 2)
        ticket = route['target']
        world.submit(1, {**route, 'reason': '派单'})
        for actor in (2, 3, 4):
            world.submit(actor, next(a for a in world.observe(actor)['available_actions'] if a['kind'] == 'wait'))
        world.advance()
        for mid, message in world.messages.items():
            if message['delivered_round'] is None and message['deliver_round'] <= world.round:
                world.accept_delivery(mid)
        lead = world.tickets[ticket]['lead']
        world.submit(lead, next(a for a in world.observe(lead)['available_actions'] if a['kind'] == 'inspect' and a['target'] == ticket))
        for actor in ({1, 2, 3, 4} - {lead}):
            world.submit(actor, next(a for a in world.observe(actor)['available_actions'] if a['kind'] == 'wait'))
        world.advance()
        obs = world.observe(lead)
        blocked = [a for a in obs['available_actions']
                   if a['kind'] in ('work', 'implement_project') and 'blocked_by' in a]
        self.assertTrue(blocked, 'routed ticket must expose its prerequisite-blocked task')
        entry = blocked[0]
        self.assertTrue(entry['blocked_by'] and all(b['received_completion'] is False for b in entry['blocked_by']))
        self.assertNotIn('state', json.dumps(entry['blocked_by']))
        from policy_sim.interface import decorate_observation
        option = next(o for o in decorate_observation(obs)['candidate_options'] if o.get('blocked_by'))
        self.assertEqual({k for k in option}, {'candidate_id', 'kind', 'target', 'params', 'blocked_by'})
        world.submit(lead, {k: entry[k] for k in ('kind', 'target', 'params')} | {'reason': '尝试施工'})
        for actor in ({1, 2, 3, 4} - {lead}):
            world.submit(actor, next(a for a in world.observe(actor)['available_actions'] if a['kind'] == 'wait'))
        world.advance()
        receipt = world._latest_receipt(lead)
        self.assertEqual(receipt['status'], 'business_rejected')
        self.assertEqual(receipt['code'], 'prerequisites_or_received_handoff_missing')
        self.assertTrue(receipt['detail']['unmet'])
        self.assertTrue(all(b['received_completion'] is False for b in receipt['detail']['unmet']))

    def test_policy_services_reconstruct_lawful_inputs(self):
        world = PolicyWorld('111')
        for actor in (1, 4):
            obs = world.observe(actor)
            for material in world.material_service_inputs(actor):
                _material_for_observation(material, obs)
                forged = deepcopy(material)
                forged['sources'][0]['data']['hidden_truth'] = True
                with self.assertRaises(ValueError):
                    _material_for_observation(forged, obs)

    def test_until_complete_controller_requires_independent_final_completion(self):
        self.assertTrue(valid_native_chunk(135, None, workload_complete=True, last_chunk=True))
        self.assertFalse(valid_native_chunk(135, None, workload_complete=False, last_chunk=True))
        self.assertFalse(valid_native_chunk(135, None, workload_complete=True, last_chunk=False))
        self.assertFalse(valid_native_chunk(0, None, workload_complete=True, last_chunk=True))
        self.assertFalse(valid_native_chunk(True, None, workload_complete=True, last_chunk=True))
        self.assertFalse(valid_native_chunk(1, True, workload_complete=True, last_chunk=True))

    def test_short_chunk_only_at_real_completion(self):
        self.assertTrue(valid_native_chunk(3, 5, workload_complete=True, last_chunk=True))
        self.assertFalse(valid_native_chunk(3, 5, workload_complete=False, last_chunk=True))
        self.assertFalse(valid_native_chunk(0, 5))
        self.assertFalse(compare_system_tokens({'passed': True, 'workload_complete': False, 'T_system': 0}, {'T_system': 50})['eligible'])


class PaymentAuditTests(unittest.TestCase):
    def test_uuid_dedup_all_purposes_and_proxy_settled_failure(self):
        with TemporaryDirectory() as directory:
            root, receipts = Path(directory), []
            for purpose in ('agent_decision', 'memory', 'policy_A', 'policy_C', 'environment_routing'):
                rid = str(uuid.uuid4())
                start = {'request_id': rid, 'event': 'request_started', 'purpose': purpose,
                         'messages': [], 'request_settings': {}, 'request_options': {}}
                end = {'request_id': rid, 'event': 'request_failed' if purpose == 'memory' else 'request_finished',
                       'purpose': purpose, 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
                for row in (start, end, end):
                    append_model_event(root / 'model_requests.jsonl', row)
                receipts.append({'client_request_id': rid, 'status': 200, 'prompt_tokens': 10, 'completion_tokens': 5})
            usage, errors = summarize_native_usage(root, receipts + deepcopy(receipts))
            self.assertFalse(errors, errors)
            self.assertEqual(usage['all_requests']['total_tokens'], 75)
            self.assertEqual(usage['all_requests']['request_count'], 5)
            self.assertEqual(usage['memory']['failed_requests'], 1)

    def test_proxy_receipt_without_worker_terminal_still_counts(self):
        with TemporaryDirectory() as directory:
            root, rid = Path(directory), str(uuid.uuid4())
            append_model_event(root / 'model_requests.jsonl', {'request_id': rid, 'event': 'request_started', 'purpose': 'memory'})
            usage, errors = summarize_native_usage(root, [{'client_request_id': rid, 'status': 200, 'prompt_tokens': 7, 'completion_tokens': 4}])
            self.assertFalse(errors)
            self.assertEqual(usage['all_requests']['total_tokens'], 11)
            self.assertEqual(usage['all_requests']['unfinished_requests'], 0)
            self.assertFalse(usage['model_behavior_verified'])

    def test_failed_attempt_lineage_is_counted_once_with_copied_prefix(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / 'current'
            failed = Path(directory) / 'failed'
            root.mkdir(); failed.mkdir()
            shared, abandoned = str(uuid.uuid4()), str(uuid.uuid4())
            prefix = {'request_id': shared, 'event': 'request_finished', 'purpose': 'agent_decision',
                      'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
            for location in (root, failed):
                append_model_event(location / 'model_requests.jsonl', prefix)
            append_model_event(failed / 'model_requests.jsonl', {'request_id': abandoned,
                'event': 'request_failed', 'purpose': 'memory', 'usage': {'prompt_tokens': 7, 'completion_tokens': 3}})
            shared_receipt = {'client_request_id': shared, 'status': 200, 'prompt_tokens': 10, 'completion_tokens': 5}
            other_receipt = {'client_request_id': abandoned, 'status': 200, 'prompt_tokens': 7, 'completion_tokens': 3}
            (failed / 'controller-failed.json').write_text(json.dumps({'mode': 'llm', 'requests': 2,
                'request_receipts': [shared_receipt, other_receipt]}))
            (root / 'recovery_lineage.json').write_text(json.dumps([{'failed_output': str(failed)}]))
            usage, errors = summarize_native_usage(root, [shared_receipt])
            self.assertFalse(errors, errors)
            self.assertEqual(usage['all_requests']['request_count'], 2)
            self.assertEqual(usage['all_requests']['total_tokens'], 25)
            self.assertEqual(usage['memory']['failed_requests'], 1)

    def test_unknown_usage_is_not_zero_and_conflicts_fail(self):
        with TemporaryDirectory() as directory:
            root, rid = Path(directory), str(uuid.uuid4())
            row = {'request_id': rid, 'event': 'request_failed', 'purpose': 'agent_decision',
                   'official_token_snapshot': {'input_tokens': 0, 'output_tokens': 0}}
            append_model_event(root / 'model_requests.jsonl', row)
            usage, _ = summarize_native_usage(root, [])
            self.assertIsNone(usage['all_requests']['total_tokens'])
            self.assertFalse(usage['complete_token_comparison'])
            append_model_event(root / 'model_requests.jsonl', {**row, 'usage': {'prompt_tokens': 9, 'completion_tokens': 3}})
            usage, errors = summarize_native_usage(root, [{'client_request_id': rid, 'status': 200, 'prompt_tokens': 10, 'completion_tokens': 3}])
            self.assertTrue(errors)
            self.assertIsNone(usage['all_requests']['total_tokens'])



class OfficialTurnAuditTests(unittest.TestCase):
    def test_unmodified_official_finish_and_independent_validation(self):
        from policy_sim.audit import _finish
        from jsonschema import ValidationError
        for count in (1, 8):
            _finish({'memories': [{'text': 'Subjective observation', 'type': 'observation', 'importance': .2,
                                  'source': 'step_result', 'refs': ['temporary-ref']} for _ in range(count)]})
        for count in (0, 9):
            with self.assertRaises(ValidationError):
                _finish({'memories': [{'text': 'Memory', 'type': 'observation', 'importance': .2}] * count})


class InstalledLoopEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_audit_binds_world_policy_to_frozen_record(self):
        import shutil
        from tests.test_sim_framework import FrameworkTests
        from policy_sim.checkpoints import commit_round
        from policy_sim.io import read_json, write_json
        from policy_sim.profiles import settings_for_purpose
        from policy_sim.runtime import code_manifest, runtime_environment
        from policy_sim.spec import SPEC_VERSION
        from policy_sim.verify import verify_run
        repo = Path(__file__).resolve().parents[1]
        harness = FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await harness.asyncSetUp()
        try:
            frozen = read_json(harness.root / 'run_config.json')
            world = harness.router.world.export_state()
            frozen.update(version=SPEC_VERSION, mode='scripted', horizon=None, seed=world['seed'],
                          scenario=world['scenario'], code_manifest=code_manifest(repo),
                          request_settings=settings_for_purpose(frozen['runtime_profile']),
                          runtime_environment=runtime_environment())
            frozen['record'].update(policy='000', runtime_profile=frozen['runtime_profile'])
            write_json(harness.root / 'run_config.json', frozen)
            write_json(harness.root / 'SOCIETY_STEP.json', {'step_count': 0})
            await harness.router.to_workspaces()
            commit_round(harness.root, 0, harness.router.world.export_state(), [])
            for officer in harness.actors:
                await officer.step(1, harness.now)
                await officer.to_workspace(officer.workspace_root_path())
            await harness.accept_results()
            await harness.router.step(1, harness.now)
            await harness.router.to_workspaces()
            write_json(harness.root / 'SOCIETY_STEP.json', {'step_count': 1})
            commit_round(harness.root, 1, harness.router.world.export_state(), [])
            profile = frozen['runtime_profile']
            write_json(harness.root / 'driver_latest.json', {'ok': True, 'ray_shutdown': True,
                'completed_steps': 1, 'routing': 'official_PersonAgent_ReActRouter',
                'framework_version': profile['framework_version'], 'source_manifest': frozen['code_manifest'],
                'runtime_profile': profile, 'runtime_environment': frozen['runtime_environment']})
            write_json(harness.root / 'controller-fixture.json', {'invocation_id': 'fixture',
                'mode': 'scripted', 'requests': 0, 'request_receipts': [], 'requested_steps': 1,
                'measured_rounds': 1, 'committed_steps': 1, 'status': 'checkpoint',
                'clean_commit': True, 'ray_shutdown': True, 'run_id': 'test',
                'runtime_profile': profile, 'source_manifest': frozen['code_manifest']})
            result = verify_run(harness.root, repo)
            self.assertTrue(result['passed'], result['errors'])
            self.assertEqual(result['policy'], '000')
            driver = read_json(harness.root / 'driver_latest.json')
            write_json(harness.root / 'driver_latest.json', {**driver, 'runtime_environment': {}})
            result = verify_run(harness.root, repo)
            self.assertFalse(result['passed'], result['errors'])
            self.assertIn('Official driver evidence incomplete or different', result['errors'])
            write_json(harness.root / 'driver_latest.json', driver)
            for policy in ('111', None):
                if policy is None:
                    frozen['record'].pop('policy')
                else:
                    frozen['record']['policy'] = policy
                for location in (harness.root, *(harness.root.parent / (harness.root.name + '-commits')).glob('round-*')):
                    write_json(location / 'run_config.json', frozen)
                result = verify_run(harness.root, repo)
                self.assertFalse(result['passed'], result['errors'])
                self.assertIn('World policy differs from frozen record', result['errors'])
        finally:
            harness.no_network.stop()
            harness.tmp.cleanup()
            shutil.rmtree(harness.root.parent / (harness.root.name + '-commits'), ignore_errors=True)

    async def test_native_audit_accepts_finished_unfiled_and_fallback_filed_turns(self):
        from tests.test_sim_framework import FrameworkTests
        from policy_sim.agent import tool_response
        from policy_sim.audit import audit_native
        from policy_sim.checkpoints import commit_round
        from policy_sim.io import read_json, write_json
        from policy_sim.profiles import settings_for_purpose
        for outcome in ('finished', 'unfiled', 'filed_fallback'):
            with self.subTest(outcome=outcome):
                harness = FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
                await harness.asyncSetUp()
                try:
                    frozen = read_json(harness.root / 'run_config.json')
                    frozen.update(mode='scripted', horizon=None,
                                  request_settings=settings_for_purpose(frozen['runtime_profile']))
                    write_json(harness.root / 'run_config.json', frozen)
                    write_json(harness.root / 'SOCIETY_STEP.json', {'step_count': 0})
                    await harness.router.to_workspaces()
                    commit_round(harness.root, 0, harness.router.world.export_state(), [])
                    actor = harness.actors[0]
                    original = actor._client.call
                    async def reply(**kwargs):
                        if kwargs.get('tools') and outcome != 'finished':
                            if outcome == 'unfiled':
                                return tool_response('finish', {'memories': [
                                    {'type': 'observation', 'importance': .2, 'text': '未办理'}]})
                            if actor._submission is not None:
                                return tool_response('finish', {'memories': []})
                        return await original(**kwargs)
                    actor._client.call = reply
                    for officer in harness.actors:
                        await officer.step(1, harness.now)
                        await officer.to_workspace(officer.workspace_root_path())
                    await harness.accept_results()
                    await harness.router.step(1, harness.now)
                    await harness.router.to_workspaces()
                    result = audit_native(harness.root)
                    self.assertTrue(result['passed'], result['errors'])
                    self.assertEqual(result['checks']['actor_rounds'], 4)
                    path = actor.workspace_root_path() / 'memory/episodes.jsonl'
                    episodes = [json.loads(line) for line in path.read_text().splitlines()]
                    episodes[0]['text'] = 'forged memory'
                    path.write_text(''.join(json.dumps(row) + '\n' for row in episodes))
                    self.assertFalse(audit_native(harness.root)['passed'])
                finally:
                    harness.no_network.stop()
                    harness.tmp.cleanup()

    async def test_mailbox_audit_rejects_deleted_and_forged_delivery_receipts(self):
        from datetime import datetime, timedelta
        from tests.test_sim_framework import FrameworkTests  # installed offline configuration
        from policy_sim.messaging import PolicyMailbox
        from policy_sim.audit import audit_mailbox
        from policy_sim.io import digest
        world = PolicyWorld('000')
        mailbox = PolicyMailbox(world)
        now = datetime(2026, 9, 14)
        await mailbox.init(now)
        world._message(1, 2, next(iter(world.tickets)), 'status_reply', {})
        for actor in (1, 2, 3, 4):
            world.submit(actor, next(a for a in world.observe(actor)['available_actions'] if a['kind'] == 'wait'))
        world.advance()
        await mailbox.deliver(world, now + timedelta(seconds=1))
        with TemporaryDirectory() as folder:
            root = Path(folder)
            await mailbox.to_workspace(root / 'env/PolicyEnv/mailbox')
            self.assertEqual(audit_mailbox(root, world.export_state()), 1)
            path = root / 'env/PolicyEnv/mailbox/TRANSPORT.json'
            original = json.loads(path.read_text())
            for damage in ('delete', 'sender', 'content', 'recipient', 'counter'):
                value = deepcopy(original)
                if damage == 'delete':
                    value['receipts'] = []
                elif damage == 'sender':
                    value['receipts'][0]['receive']['sender_id'] = 3
                elif damage == 'content':
                    value['receipts'][0]['receive']['content'] = '{}'
                elif damage == 'recipient':
                    value['receipts'][0]['send']['receiver_id'] = 3
                else:
                    native_path = path.parent / 'native/state/ENV_STATE.json'
                    native = json.loads(native_path.read_text())
                    native['total_messages_sent'] += 1
                    native_path.write_text(json.dumps(native))
                    value['native_sha256'] = digest(native)
                path.write_text(json.dumps(value))
                with self.subTest(damage=damage), self.assertRaises(ValueError):
                    audit_mailbox(root, world.export_state())

    async def test_saved_official_turns_including_repaired_truncation_audit(self):
        import importlib.util
        if importlib.util.find_spec('agentsociety2') is None:
            self.skipTest('Official framework environment required')
        from tests.test_sim_framework import FrameworkTests
        from policy_sim.audit import audit_turns, audit_finish_memories, _rows
        harness = FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await harness.asyncSetUp()
        try:
            actor = harness.actors[0]
            original, calls = actor._client.call, []
            async def reply(**kwargs):
                calls.append(kwargs)
                response = await original(**kwargs)
                if len(calls) == 1:
                    response.choices[0].finish_reason = 'length'
                return response
            actor._client.call = reply
            # A raw official file read and denied research path are both recorded.
            from policy_sim.agent import tool_response
            reader = harness.actors[3]
            original_reader, read_calls = reader._client.call, []
            async def page_reply(**kwargs):
                if len(read_calls) < 2:
                    path = 'world.json' if not read_calls else 'business/current.json'
                    read_calls.append(path)
                    return tool_response('read', {'path': path})
                return await original_reader(**kwargs)
            reader._client.call = page_reply
            for actor in harness.actors:
                await actor.step(1, harness.now)
            self.assertEqual(harness.router.world.round, 0)
            self.assertGreater(len(read_calls), 1)
            await harness.accept_results()
            await harness.router.step(1, harness.now)
            await harness.router.to_workspaces()
            from policy_sim.audit import audit_mailbox
            self.assertEqual(audit_mailbox(harness.root, harness.router.world.export_state()), len(harness.router.mailbox.receipts))
            transport_path = harness.root / 'env/PolicyEnv/mailbox/TRANSPORT.json'
            transport = json.loads(transport_path.read_text())
            bad_transport = deepcopy(transport)
            bad_transport['receipts'] = bad_transport['receipts'][1:]
            if transport['receipts']:
                transport_path.write_text(json.dumps(bad_transport))
                with self.assertRaisesRegex(ValueError, 'Native receipt sequence'):
                    audit_mailbox(harness.root, harness.router.world.export_state())
                transport_path.write_text(json.dumps(transport))
            rows = [r for p in (harness.root / 'agents').rglob('native_decisions.jsonl') for r in _rows(p)]
            receipts = [r for p in (harness.root / 'agents').rglob('native_tool_receipts.jsonl') for r in _rows(p)]
            summaries, routes = audit_turns(rows, _rows(harness.root / 'observations.jsonl'),
                _rows(harness.root / 'actions.jsonl'), _rows(harness.root / 'material_reads.jsonl'),
                harness.router.world.export_state(), tool_receipts=receipts,
                environment_routes=_rows(harness.root / 'native_routes.jsonl'),
                environment_decisions=_rows(harness.root / 'native_router_decisions.jsonl'))
            self.assertEqual(len(summaries), 4)
            self.assertEqual(len(routes), 4)
            self.assertEqual(routes, _rows(harness.root / 'native_routes.jsonl'))
            self.assertTrue((harness.root / 'native_router_decisions.jsonl').exists())
            forged = deepcopy(receipts)
            forged[0]['args']['instruction'] = 'Changed actor request'
            with self.assertRaises(ValueError):
                audit_turns(rows, _rows(harness.root / 'observations.jsonl'),
                    _rows(harness.root / 'actions.jsonl'), _rows(harness.root / 'material_reads.jsonl'),
                    harness.router.world.export_state(), tool_receipts=forged,
                    environment_routes=_rows(harness.root / 'native_routes.jsonl'),
                environment_decisions=_rows(harness.root / 'native_router_decisions.jsonl'))
            router_rows = _rows(harness.root / 'native_routes.jsonl')
            for damage in ('route_operation', 'route_payload', 'prompt_memory', 'prompt_candidate_count', 'tool_authority', 'extra_receipt'):
                altered_rows, altered_routes, altered_receipts = deepcopy(rows), deepcopy(router_rows), deepcopy(receipts)
                if damage == 'route_operation':
                    altered_routes[0]['operation'] = 'observe'
                elif damage == 'route_payload':
                    altered_routes[0]['payload'] = {**altered_routes[0]['payload'], 'reason': 'forged justification'}
                elif damage == 'prompt_memory':
                    altered_rows[-1]['messages'][1]['content'] = altered_rows[-1]['messages'][1]['content'].replace('<memory_context>', '<memory_context>Hidden world state')
                elif damage == 'prompt_candidate_count':
                    content = altered_rows[0]['messages'][1]['content']
                    self.assertIn('"candidate_count":', content)
                    altered_rows[0]['messages'][1]['content'] = content.replace('"candidate_count":', '"forged_candidate_count":', 1)
                elif damage == 'tool_authority':
                    altered_rows[0]['request_options']['tools'][0]['function']['parameters'] = {}
                else:
                    altered_receipts.append(deepcopy(receipts[0]))
                with self.subTest(damage=damage), self.assertRaises((ValueError, KeyError)):
                    audit_turns(altered_rows, _rows(harness.root / 'observations.jsonl'),
                        _rows(harness.root / 'actions.jsonl'), _rows(harness.root / 'material_reads.jsonl'),
                        harness.router.world.export_state(), tool_receipts=altered_receipts,
                        environment_routes=altered_routes,
                        environment_decisions=_rows(harness.root / 'native_router_decisions.jsonl'))
            count = audit_finish_memories(harness.root, rows, _rows(harness.root / 'actions.jsonl'))
            self.assertGreaterEqual(count, 4)
            path = next((harness.root / 'agents').rglob('episodes.jsonl'))
            episodes = _rows(path)
            episodes[0]['text'] = 'Forged durable memory'
            path.write_text(''.join(json.dumps(e) + '\n' for e in episodes))
            with self.assertRaisesRegex(ValueError, 'Saved official memories differ'):
                audit_finish_memories(harness.root, rows, _rows(harness.root / 'actions.jsonl'))
        finally:
            # This harness was not run by unittest and has no asyncio runner.
            # Its IsolatedAsyncioTestCase.doCleanups would silently record an
            # internal runner error and leave the global socket patch active.
            harness.no_network.stop()
            harness.tmp.cleanup()


if __name__ == '__main__':
    unittest.main()
