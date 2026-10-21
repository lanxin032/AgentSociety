"""Regression at the official actor/router seams implicated by real attempt 0055."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from tests import test_sim_framework as framework
from policy_sim.agent import tool_response
from policy_sim.core import PolicyWorld
from policy_sim.interface import decorate_observation
from policy_sim.work import WorkContext, WORK_SECTIONS, SECTION_BYTES, _size, read_work_section
from policy_sim.audit import _prompt_blocks
from policy_sim.official_adapter import PROMPT_CORRECTIONS, adapt_official_messages


class InformationContractTests(unittest.TestCase):
    def test_delivered_policy_analysis_remains_accessible_without_actor_files(self):
        obs = decorate_observation(PolicyWorld('111', seed=3001).observe(1))
        payload = {'summary': '已合法送达的建议' * 100}
        obs['materials']['analyses'] = [{'service': 'A', 'target': 'ticket-1', 'payload': payload}]
        overview = WorkContext(obs).current_work
        self.assertEqual(overview['analyses']['read_work']['section'], 'analyses')
        self.assertEqual(read_work_section(obs, 'analyses')['value'][0]['payload'], payload)

    def test_every_query_reference_is_executable_and_pages_preserve_records(self):
        for policy in (f'{i:03b}' for i in range(8)):
            world = PolicyWorld(policy, seed=3001)
            for actor in (1, 2, 3, 4):
                obs = decorate_observation(world.observe(actor))
                overview = WorkContext(obs).current_work
                self.assertNotIn('business/', json.dumps(overview))
                for value in overview.values():
                    if isinstance(value, dict) and 'read_work' in value:
                        query = value['read_work']
                        self.assertIn(query['section'], WORK_SECTIONS)
                        self.assertIn('value', read_work_section(obs, **query))
        obs['candidate_options'] *= 100
        collected, offset = [], 0
        while True:
            page = read_work_section(obs, 'candidate_options', offset)
            self.assertLessEqual(_size(page), SECTION_BYTES)
            collected.extend(page['value'])
            if page['complete']:
                break
            self.assertGreater(page['next_offset'], offset)
            offset = page['next_offset']
        self.assertEqual(collected, obs['candidate_options'])
        for section in ('business/role-0001.txt', 'issues', 'hidden_true_cause'):
            with self.assertRaises(ValueError):
                read_work_section(obs, section)


class OfficialInformationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pacing_counts_react_turns_instead_of_schema_repair_requests(self):
        fixture = framework.FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await fixture.asyncSetUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.addCleanup(fixture.no_network.stop)
        actor = fixture.actors[0]
        original, calls = actor._client.call, []
        async def reply(**kwargs):
            if kwargs.get('tools'):
                calls.append(1)
                if len(calls) <= 12:
                    if len(calls) % 2:
                        return tool_response('unavailable_tool', {})
                    return tool_response('ask_env', {'instruction': 'read_work section {section} offset {offset}',
                        'variables': {'section': 'inbox', 'offset': 0}, 'readonly': True})
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, fixture.now)
        reads = [r for r in framework.rows(fixture.root / 'native_routes.jsonl') if r['operation'] == 'read_work']
        self.assertEqual(len(reads), 6)
        self.assertTrue(all('pace_note' not in r['result'] for r in reads[:5]))
        self.assertIn('第6次ReAct迭代', reads[5]['result']['pace_note'])

    async def test_evicted_page_is_served_again_after_a_batch_of_eight_tool_results(self):
        for operation in ('read_work', 'read_materials'):
            with self.subTest(operation=operation):
                await self._check_evicted_page(operation)

    async def _check_evicted_page(self, operation):
        fixture = framework.FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await fixture.asyncSetUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.addCleanup(fixture.no_network.stop)
        actor = fixture.actors[0]
        original, turns = actor._client.call, []
        def read(section):
            if operation == 'read_materials' and section == 'public_rules':
                sid = actor._policy_observation['materials']['source_index'][0]['source_id']
                return tool_response('ask_env', {'instruction': 'read_materials source_ids {source_ids} reason {reason}',
                    'variables': {'source_ids': [sid], 'reason': '读取已获授权的正文'}, 'readonly': True})
            return tool_response('ask_env', {'instruction': 'read_work section {section} offset {offset}',
                'variables': {'section': section, 'offset': 0}, 'readonly': True})
        async def reply(**kwargs):
            if not kwargs.get('tools'):
                return await original(**kwargs)
            turns.append(1)
            if len(turns) in (1, 3):
                return read('public_rules')
            if len(turns) == 2:
                batch = read('inbox')
                for section in ('projects', 'topics', 'sent_messages', 'visible_tickets',
                                'candidate_options', 'source_catalog', 'analyses'):
                    call = read(section).choices[0].message.tool_calls[0]
                    call.id = section
                    batch.choices[0].message.tool_calls.append(call)
                return batch
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, fixture.now)
        routes = [r for r in framework.rows(fixture.root / 'native_routes.jsonl')
                  if r['operation'] == operation and
                  (operation != 'read_work' or r['payload']['section'] == 'public_rules')]
        self.assertEqual(len(routes), 2)
        field = 'sources' if operation == 'read_materials' else 'value'
        self.assertIn(field, routes[1]['result'])
        self.assertEqual(routes[0]['result'][field], routes[1]['result'][field])
        for other in fixture.actors[1:]:
            await other.step(1, fixture.now)
        await fixture.router.step(1, fixture.now)
        from policy_sim.audit import audit_turns
        decisions = [r for p in (fixture.root / 'agents').rglob('native_decisions.jsonl') for r in framework.rows(p)]
        receipts = [r for p in (fixture.root / 'agents').rglob('native_tool_receipts.jsonl') for r in framework.rows(p)]
        summaries, _ = audit_turns(decisions, framework.rows(fixture.root / 'observations.jsonl'),
            framework.rows(fixture.root / 'actions.jsonl'), framework.rows(fixture.root / 'material_reads.jsonl'),
            fixture.router.world.export_state(), tool_receipts=receipts,
            environment_routes=framework.rows(fixture.root / 'native_routes.jsonl'))
        self.assertEqual(len(summaries), 4)

    async def test_first_official_prompt_already_contains_executable_candidates(self):
        fixture = framework.FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await fixture.asyncSetUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.addCleanup(fixture.no_network.stop)
        actor = fixture.actors[0]
        original = actor._client.call
        async def reply(**kwargs):
            if kwargs.get('tools') and actor._submission is None:
                blocks = _prompt_blocks(kwargs['messages'])
                overview = json.loads(blocks['recent_observations'][0]['observation'])
                self.assertIsInstance(overview.get('candidate_options'), list)
                option = next(x for x in overview['candidate_options'] if x['kind'] == 'wait')
                return tool_response('ask_env', {'instruction': 'submit candidate {candidate_id} with reason {reason}',
                    'variables': {'candidate_id': option['candidate_id'], 'reason': '按初始观察等待'}, 'readonly': False})
            return await original(**kwargs)
        actor._client.call = reply
        result = json.loads(await actor.step(1, fixture.now))
        self.assertTrue(result['submitted'])
        self.assertEqual(actor._completion_calls, 2)
        self.assertEqual([r['operation'] for r in framework.rows(fixture.root / 'native_routes.jsonl')], ['submit'])

    async def test_repeated_read_serves_stub_and_audit_replays_it(self):
        # attempt-0067 regression class: an identical in-round re-read must
        # return the unchanged stub through the official loop, and the
        # independent audit must replay the same stub from route history.
        fixture = framework.FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await fixture.asyncSetUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.addCleanup(fixture.no_network.stop)
        router, actor = fixture.router, fixture.actors[0]
        original, reads = actor._client.call, []
        async def reply(**kwargs):
            if not kwargs.get('tools'):
                return await original(**kwargs)
            if actor._submission is None:
                if len(reads) < 2:
                    reads.append(1)
                    return tool_response('ask_env', {'instruction': 'read_work section {section} offset {offset}',
                        'variables': {'section': 'inbox', 'offset': 0}, 'readonly': True})
                option = next(x for x in actor._policy_observation['candidate_options'] if x['kind'] == 'wait')
                return tool_response('ask_env', {'instruction': 'submit candidate {candidate_id} with reason {reason}',
                    'variables': {'candidate_id': option['candidate_id'], 'reason': '已有信息未变，等待。'}, 'readonly': False})
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, fixture.now)
        asks = [r for r in framework.rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl') if r['action'] == 'ask_env']
        self.assertEqual(len(asks), 3)
        first = json.loads(asks[0]['observation'])['receipts'][0]['result']
        second = json.loads(asks[1]['observation'])['receipts'][0]['result']
        self.assertNotIn('unchanged_since_last_read', first)
        self.assertEqual(second.get('unchanged_since_last_read'), True)
        self.assertEqual(second.get('read_count_this_turn'), 2)
        for other in fixture.actors[1:]:
            await other.step(1, fixture.now)
        await router.step(1, fixture.now)
        from policy_sim.audit import audit_turns
        all_decisions = [r for p in (fixture.root / 'agents').rglob('native_decisions.jsonl') for r in framework.rows(p)]
        receipts = [r for p in (fixture.root / 'agents').rglob('native_tool_receipts.jsonl') for r in framework.rows(p)]
        summaries, routes = audit_turns(all_decisions, framework.rows(fixture.root / 'observations.jsonl'),
            framework.rows(fixture.root / 'actions.jsonl'), framework.rows(fixture.root / 'material_reads.jsonl'),
            router.world.export_state(), tool_receipts=receipts,
            environment_routes=framework.rows(fixture.root / 'native_routes.jsonl'))
        self.assertEqual(len(summaries), 4)
        stubbed = [r for r in routes if r['operation'] == 'read_work' and r['actor_id'] == 1]
        self.assertEqual(len(stubbed), 2)
        self.assertIn('unchanged_since_last_read', json.dumps(stubbed[1]['result']))

    async def test_actor_asks_dispatch_deterministically_without_actor_files(self):
        fixture = framework.FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await fixture.asyncSetUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.addCleanup(fixture.no_network.stop)
        router, actor = fixture.router, fixture.actors[0]
        router.decision_mode = 'llm'
        # Any model invocation from the environment side is a hard failure:
        # business asks dispatch from their recorded template alone.
        async def forbidden(**kwargs):
            raise AssertionError('Environment routing must not call a model')
        router.llm_client = SimpleNamespace(for_context=lambda *a, **k: SimpleNamespace(call=forbidden))
        original, calls = actor._client.call, []
        async def reply(**kwargs):
            calls.append(kwargs.get('tools') is not None)
            if not kwargs.get('tools'):
                return await original(**kwargs)
            observation = actor._policy_observation
            if actor._submission is None:
                if len(calls) == 1:
                    return tool_response('ask_env', {'instruction': 'read_work section {section} offset {offset}',
                        'variables': {'section': 'candidate_options', 'offset': 0}, 'readonly': True})
                option = next(x for x in observation['candidate_options'] if x['kind'] == 'wait')
                return tool_response('ask_env', {'instruction': 'submit candidate {candidate_id} with reason {reason}',
                    'variables': {'candidate_id': option['candidate_id'], 'reason': '无待办判断，等待派单。'}, 'readonly': False})
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, fixture.now)
        self.assertFalse((fixture.root / 'native_router_decisions.jsonl').exists())
        routes = framework.rows(fixture.root / 'native_routes.jsonl')
        self.assertEqual([r['operation'] for r in routes], ['read_work', 'submit'])
        self.assertTrue(all(r['ok'] for r in routes))
        self.assertEqual(router.completed, {1})
        decisions = framework.rows(actor.workspace_root_path() / 'native_decisions.jsonl')
        first, last = (_prompt_blocks(row['messages']) for row in (decisions[0], decisions[-1]))
        self.assertEqual(first['agent']['current_work']['phase'], 'choose')
        self.assertEqual(last['agent']['current_work']['phase'], 'finish')
        self.assertEqual(last['agent']['current_work']['queued_receipt']['status'], 'queued')
        history = [{'turn': n, 'action': 'read', 'ok': True, 'observation': f'old-record-{n}'}
                   for n in range(1, 13)]
        messages = actor.build_react_messages(tick=1, t=fixture.now, observations=history)
        blocks = _prompt_blocks(messages)
        self.assertEqual(blocks['recent_observations'], history[-8:])
        self.assertEqual(blocks['agent']['current_work'], last['agent']['current_work'])
        for original_text, replacement in PROMPT_CORRECTIONS:
            self.assertNotIn(original_text, messages[0]['content'])
            self.assertEqual(messages[0]['content'].count(replacement), 1)
        with self.assertRaises(RuntimeError):
            adapt_official_messages(messages)  # version drift/double application
        for other in fixture.actors[1:]:
            await other.step(1, fixture.now)
        await router.step(1, fixture.now)
        from policy_sim.audit import audit_turns
        all_decisions = [r for p in (fixture.root / 'agents').rglob('native_decisions.jsonl')
                         for r in framework.rows(p)]
        receipts = [r for p in (fixture.root / 'agents').rglob('native_tool_receipts.jsonl')
                    for r in framework.rows(p)]
        def audit(routes):
            return audit_turns(all_decisions, framework.rows(fixture.root / 'observations.jsonl'),
                framework.rows(fixture.root / 'actions.jsonl'), framework.rows(fixture.root / 'material_reads.jsonl'),
                router.world.export_state(), tool_receipts=receipts, environment_routes=routes)
        routes = framework.rows(fixture.root / 'native_routes.jsonl')
        self.assertEqual(len(audit(routes)[0]), 4)
        routes[1]['result'] = {'value': 'fabricated candidates'}
        with self.assertRaises(ValueError):
            audit(routes)
