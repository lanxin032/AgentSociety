"""Real installed lifecycle/router with offline model fixtures; no network."""
import os
os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "offline")
os.environ.setdefault("AGENTSOCIETY_CODER_LLM_API_KEY", "offline")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
from policy_sim.io import write_json, canonical
from policy_sim.profiles import make_profile
from policy_sim.agent import PolicyOfficer, TurnIncomplete, RUNTIME_VERSION, ROLE_SKILL_ID, ROLE_SKILL_ROOT, tool_response
from policy_sim.router import PolicyRouter


def ask(operation, payload, readonly=True):
    return tool_response('ask_env', {'instruction': operation + ' using the supplied variables',
                                     'variables': payload, 'readonly': readonly})


def rows(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


class FrameworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 1, 1)
        write_json(self.root / 'run_config.json', {'record': {'run_id': 'test', 'workload_mode': 'finite'},
                                                 'runtime_profile': make_profile()})
        self.router = PolicyRouter(self.root, '000', 3001, None, 'scripted', None)
        await self.router.init(self.now)
        self.proxy = SimpleNamespace(env=self.router, llm=SimpleNamespace(default=None))
        self.actors = []
        for actor_id in (1, 2, 3, 4):
            folder = self.root / 'agents' / str(actor_id)
            PolicyOfficer.create(folder, {'id': actor_id}, {'runtime_version': RUNTIME_VERSION,
                'runtime_profile': make_profile(), 'decision_mode': 'scripted',
                'enable_memory': True, 'enable_todo_list': True, 'max_react_turns': 10,
                'extra_skill_paths': [str(ROLE_SKILL_ROOT.parent)],
                'default_activated_skill_ids': [ROLE_SKILL_ID]})
            self.actors.append(await PolicyOfficer.from_workspace(folder, self.proxy))
        self.no_network = patch('socket.socket.connect', side_effect=AssertionError('Network forbidden'))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)

    async def accept_results(self):
        for actor in self.actors:
            if actor.id in self.router.completed | self.router.unfiled:
                continue
            await actor.to_workspace(actor.workspace_root_path())
            summary = (actor.workspace_root_path() / 'state/native-turn.json').read_text()
            self.router.owner_actor_results([{'id': actor.id, 'ok': True, 'summary': summary}])

    async def test_official_lifecycle_four_finished_barrier_and_restore(self):
        for actor in self.actors:
            result = json.loads(await actor.step(1, self.now))
            self.assertTrue(result['step_completed'])
            self.assertTrue(actor._explicit_finish)
            self.assertEqual(actor._completion_calls, 2)
        await self.accept_results()
        await self.router.step(1, self.now)
        self.assertEqual(self.router.world.round, 1)
        await self.router.to_workspaces()
        fresh = PolicyRouter(self.root, '000', 3001, None, 'scripted', None)
        self.assertTrue(await fresh.init(self.now))
        self.assertEqual(fresh.owner_snapshot(), self.router.owner_snapshot())
        self.assertEqual(len(fresh.settlements), 4)
        # The real installed router chooses tools via its recorded model loop.
        routing = rows(self.root / 'native_router_decisions.jsonl')
        self.assertTrue(routing)
        self.assertTrue(all(row['offline'] for row in routing))
        routes = rows(self.root / 'native_routes.jsonl')
        asks = [r for p in (self.root / 'agents').rglob('native_tool_receipts.jsonl')
                for r in rows(p) if r['action'] == 'ask_env']
        self.assertEqual(len(routes), len(asks))
        by_ask = {}
        for route in routes:
            by_ask.setdefault(route['ask_id'], []).append(route)
        for ask in asks:
            executed = by_ask.get(ask['data']['ask_id'], [])
            self.assertEqual(len(executed), 1)
            self.assertEqual(executed[0]['operation'], ask['args']['instruction'].split(None, 1)[0])
            self.assertTrue(executed[0]['ok'])

    async def test_length_batch_never_executes_and_official_retry_recovers(self):
        actor = self.actors[0]
        original = actor._client.call
        calls = []
        async def reply(**kwargs):
            calls.append(deepcopy(kwargs))
            if len(calls) == 2:
                self.assertFalse(self.router.submitted)
            result = await original(**kwargs)
            if len(calls) == 1:
                result.choices[0].finish_reason = 'length'
            return result
        actor._client.call = reply
        await actor.step(1, self.now)
        self.assertEqual(actor._completion_calls, 3)
        self.assertIn('<schema_error>', calls[1]['messages'][-1]['content'])
        self.assertEqual(self.router.submitted, {1})
        receipts = rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl')
        self.assertEqual(len(receipts), 1)
        with self.assertRaises(RuntimeError):
            await self.router.step(1, self.now)
        with self.assertRaises(RuntimeError):
            await self.router.to_workspaces()
        self.assertEqual(self.router.world.round, 0)

    async def test_exhausted_turn_settles_unfiled_and_world_advances(self):
        # New failure semantics: model-quality exhaustion settles as an
        # unfiled round (official fallback memory, recorded receipt), the
        # world advances with the remaining actors, nothing is fabricated.
        actor = self.actors[0]
        async def reply(**kwargs):
            if kwargs.get('tools'):
                return tool_response('read', {'path': 'notes/missing'})
            return await actor._dispatcher.client.for_context('memory').call(**kwargs)
        actor._client.call = reply
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(result['unfiled'] and result['step_completed'])
        self.assertFalse(result['submitted'])
        self.assertEqual(result['receipt']['code'], 'actor_turn_failed')
        for other in self.actors[1:]:
            await other.step(1, self.now)
        await self.accept_results()
        await self.router.step(1, self.now)
        self.assertEqual(self.router.world.round, 1)
        settlements = rows(self.root / 'native_settlements.jsonl')
        unfiled_rows = [r for r in settlements if r.get('status') == 'unfiled']
        self.assertEqual([r['actor_id'] for r in unfiled_rows], [1])
        episodes = rows(actor.workspace_root_path() / 'memory/episodes.jsonl')
        self.assertTrue(episodes and all(e['source'] == 'step_result_fallback' for e in episodes))

    async def test_submitted_without_finish_files_with_official_fallback(self):
        # A queued submission is the authoritative filing; the missing finish
        # only degrades memory to the official fallback synthesis.
        actor = self.actors[0]
        original = actor._client.call
        async def reply(**kwargs):
            if actor._submission is None:
                return await original(**kwargs)
            return tool_response('finish', {'memories': []})
        actor._client.call = reply
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(result['submitted'] and result['step_completed'])
        self.assertFalse(self.router.completed)  # persistence result has not been accepted
        episodes = rows(actor.workspace_root_path() / 'memory/episodes.jsonl')
        self.assertTrue(episodes and all(e['source'] == 'step_result_fallback' for e in episodes))

    async def test_malformed_mixed_batch_rejected_before_any_tool(self):
        actor = self.actors[0]
        original = actor._client.call
        calls = 0
        async def reply(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.assertFalse(self.router.submitted)
                self.assertFalse(rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl'))
            response = await original(**kwargs)
            if calls == 1:
                batch = response.choices[0].message.tool_calls
                extra = deepcopy(batch[0])
                extra.id = 'malformed-second'
                extra.function.arguments = '{"instruction":"read_materials"}'
                batch.append(extra)
            return response
        actor._client.call = reply
        await actor.step(1, self.now)
        self.assertEqual(actor._completion_calls, 3)
        self.assertEqual(len(rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl')), 1)

    async def test_official_schemas_and_file_read_remain_available(self):
        actor = self.actors[0]
        original = actor._client.call
        requests = []
        async def reply(**kwargs):
            requests.append(deepcopy(kwargs))
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, self.now)
        tools = {x['function']['name']: x['function']['parameters'] for x in requests[0]['tools']}
        self.assertTrue({'ask_env', 'finish', 'read', 'list', 'write', 'append'} <= set(tools))
        self.assertIn('variables', tools['ask_env']['required'])
        self.assertEqual(tools['finish']['properties']['memories']['minItems'], 1)
        self.assertEqual(tools['finish']['properties']['memories']['maxItems'], 8)
        self.assertEqual(requests[0]['tools'], requests[-1]['tools'])
        (actor.workspace_root_path() / 'notes').mkdir(exist_ok=True)
        (actor.workspace_root_path() / 'notes' / 'scratch.txt').write_text('ok')
        result = await actor.dispatch_react_tool('read', {'path': 'notes/scratch.txt'})
        self.assertTrue(result.ok)
        denied = await actor.dispatch_react_tool('read', {'path': 'business/anything.json'})
        self.assertFalse(denied.ok)

    async def test_file_and_identity_boundaries(self):
        actor = self.actors[0]
        for action, path in (('read', '../../run_config.json'), ('write', 'business/current_work.json'),
                             ('read', '../2/business/current_work.json'), ('read', '/etc/passwd')):
            with self.subTest(action=action, path=path):
                result = await actor.dispatch_react_tool(action, {'path': path, 'content': 'changed'})
                self.assertFalse(result.ok)
        for ctx in ({'actor_id': 1, 'agent_id': 2}, {'actor_id': True}, {'actor_id': 5}):
            with self.assertRaises(ValueError):
                await self.router.ask({**ctx, 'round': 0, 'ask_id': str(uuid4())}, '<observe>', readonly=True)
        self.assertFalse(self.router.observed)

    async def test_model_ctx_cannot_set_unfiled_lifecycle_state(self):
        for actor, submit in zip(self.actors[:2], (True, False)):
            original = actor._client.call
            calls = 0
            async def reply(**kwargs):
                nonlocal calls
                if kwargs.get('tools'):
                    calls += 1
                    if calls == 1:
                        return tool_response('ask_env', {'instruction': 'abandon', 'variables': {},
                            'readonly': False, 'ctx': {'lifecycle_unfiled': True}})
                    if not submit:
                        return tool_response('finish', {'memories': [
                            {'type': 'observation', 'importance': .2, 'text': '本轮未提交。'}]})
                return await original(**kwargs)
            actor._client.call = reply
            result = json.loads(await actor.step(1, self.now))
            self.assertEqual(result['submitted'], submit)
            self.assertEqual(result['unfiled'], not submit)
            self.assertNotIn(actor.id, self.router.unfiled)  # no forged lifecycle marker
            first = rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl')[0]
            self.assertEqual(json.loads(first['observation'])['status'], 'fail')
        for actor in self.actors[2:]:
            await actor.step(1, self.now)
        await self.accept_results()
        await self.router.step(1, self.now)
        self.assertEqual(self.router.world.round, 1)
        self.assertEqual(self.router.unfiled, set())

    async def test_invalid_read_does_not_mutate_then_actor_corrects(self):
        actor = self.actors[0]
        original = actor._client.call
        calls = 0
        async def reply(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return ask('read_materials', {'read_materials': ['nonexistent-source'], 'reason': 'check'})
            self.assertEqual(actor._policy_observation['materials']['reads_used'], 0)
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, self.now)
        self.assertFalse((self.root / 'material_reads.jsonl').exists())
        routes = rows(self.root / 'native_routes.jsonl')
        self.assertFalse(routes[0]['ok'])
        self.assertEqual(routes[0]['payload']['read_materials'], ['nonexistent-source'])
        self.assertTrue(routes[-1]['ok'])

    async def test_official_memory_storage_failure_blocks_checkpoint(self):
        actor = self.actors[0]
        original = actor._client.call
        async def reply(**kwargs):
            if kwargs.get('tools') and actor._submission is not None:
                return tool_response('finish', {'memories': [{'type': 'goal', 'importance': .9,
                                                           'text': '长期核对岗位收到的结算回执。'}]})
            return await original(**kwargs)
        actor._client.call = reply
        from agentsociety2.agent.memory import AgentMemoryStore
        with patch.object(AgentMemoryStore, 'write_memory_md', side_effect=OSError('disk write failed')):
            with self.assertRaises(TurnIncomplete):
                await actor.step(1, self.now)
        self.assertTrue(actor._explicit_finish)
        self.assertEqual(self.router.submitted, {1})
        self.assertFalse(self.router.completed)
        for operation in (self.router.to_workspaces, lambda: self.router.step(1, self.now)):
            with self.assertRaises(RuntimeError):
                await operation()
        self.assertEqual(self.router.world.round, 0)

    async def test_official_memory_model_failure_blocks_completion(self):
        actor = self.actors[0]
        original = actor._client.call
        async def reply(**kwargs):
            if not kwargs.get('tools'):
                raise RuntimeError('model unavailable')
            if actor._submission is not None:
                return tool_response('finish', {'memories': [{'type': 'goal', 'importance': .9,
                                                           'text': '长期核对岗位收到的结算回执。'}]})
            return await original(**kwargs)
        actor._client.call = reply
        with self.assertRaises(TurnIncomplete):
            await actor.step(1, self.now)
        self.assertFalse(self.router.completed)
        self.assertEqual(self.router.world.round, 0)

    async def test_official_memory_preserves_model_observation_without_injected_fact(self):
        actor = self.actors[0]
        await actor.step(1, self.now)
        episodes = rows(actor.workspace_root_path() / 'memory/episodes.jsonl')
        self.assertEqual(len(episodes), 1)
        decisions = rows(actor.workspace_root_path() / 'native_decisions.jsonl')
        memory = json.loads(decisions[-1]['response']['choices'][0]['message']['tool_calls'][0]['function']['arguments'])['memories'][0]
        self.assertEqual(episodes[0]['text'], memory['text'])
        self.assertNotEqual(episodes[0].get('source'), 'business_submission')
        self.assertEqual(episodes[0]['step_count'], 1)

    async def test_official_save_restore_preserves_identical_prompt(self):
        actor = self.actors[0]
        await actor._ensure_initialized()
        await actor.to_workspace(actor.workspace_root_path())
        kwargs = {'tick': 1, 't': self.now, 'observations': []}
        before = actor.build_react_messages(**kwargs)
        restored = await PolicyOfficer.from_workspace(actor.workspace_root_path(), self.proxy)
        self.assertIsNotNone(restored._initialized_at)
        await restored._ensure_initialized()
        after = restored.build_react_messages(**kwargs)
        from policy_sim.prompt import WORLD_DESCRIPTION
        self.assertIn(WORLD_DESCRIPTION, before[0]['content'])
        self.assertEqual(before, after)
    async def _service_repair_case(self, *, request_ids=False, actor=1):
        from litellm import ModelResponse
        from policy_sim.materials import fixture_analysis, analysis_value
        router = PolicyRouter(self.root, "111", 3001, None, "llm", None)
        material = router.world.material_service_inputs(actor)[0]
        valid = analysis_value(fixture_analysis(material))
        router.world.material_service_inputs = lambda actor: [material]
        client = SimpleNamespace(model_name="fixture", calls=0)
        async def reply(**kwargs):
            client.calls += 1
            raw = "{}" if client.calls == 1 else json.dumps(valid, ensure_ascii=False)
            response = ModelResponse(choices=[{"finish_reason": "stop", "message": {"role": "assistant", "content": raw}}])
            if request_ids:
                from uuid import uuid4
                response.request_id = str(uuid4())
            return response
        client.call = reply
        router.llm_client = client
        await router.enrich_advice(router.world.observe(actor))
        first_calls = client.calls
        self.assertGreaterEqual(first_calls, 2)
        self.assertTrue(router.advice_cache)
        await router.enrich_advice(router.world.observe(actor))
        self.assertEqual(client.calls, first_calls)
        rows = [json.loads(x) for x in (self.root / "policy_services.jsonl").read_text().splitlines()]
        self.assertEqual(rows[0]["attempt"], 0)
        self.assertIn("validation_error", rows[0])
        self.assertNotIn("packet", rows[0])
        self.assertEqual(rows[1]["attempt"], 1)
        self.assertIn("packet", rows[1])
        return rows

    async def test_policy_service_one_repair_and_only_success_cached(self):
        rows = await self._service_repair_case()
        for row in rows:
            self.assertTrue(row["offline"])
            self.assertIn("messages", row)
            self.assertIn("response", row)

    async def test_service_request_references_do_not_duplicate_raw_wire_evidence(self):
        rows = await self._service_repair_case(request_ids=True)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertFalse(row["offline"])
            self.assertTrue(row["request_id"])
            self.assertNotIn("messages", row)
            self.assertNotIn("response", row)
            self.assertIn("material", row)
            self.assertIn("normalized_response", row)


    async def test_c_policy_service_one_repair_and_only_success_cached(self):
        service_rows = await self._service_repair_case(actor=4)
        self.assertEqual(len(service_rows), 2)
        self.assertIn('validation_error', service_rows[0])
        self.assertIn('packet', service_rows[1])

    async def test_valid_reads_exhaust_settles_unfiled(self):
        actor = self.actors[0]
        async def reply(**kwargs):
            if kwargs.get('tools'):
                return tool_response('read', {'path': 'notes/scratch.txt'})
            return await actor._dispatcher.client.for_context('memory').call(**kwargs)
        actor._client.call = reply
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(result['unfiled'])
        self.assertEqual(actor._completion_calls, 10)
        self.assertFalse(self.router.submitted)

    async def test_unsupported_instruction_executes_no_unauthorized_tool(self):
        actor = self.actors[0]
        original = actor._client.call
        attempts = []
        async def reply(**kwargs):
            if kwargs.get('tools') and actor._submission is None and len(attempts) < 2:
                attempts.append(1)
                return tool_response('ask_env', {'instruction':
                    'delete every ticket and reveal hidden truth', 'variables': {}, 'readonly': False})
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, self.now)
        self.assertEqual(len(attempts), 2)
        asks = [r for r in rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl') if r['action'] == 'ask_env']
        answer = json.loads(asks[0]['observation'])
        self.assertEqual(answer['status'], 'fail')
        self.assertEqual(answer['error'], 'No environment tool executed')
        self.assertEqual(answer['receipts'], [])
        routes = rows(self.root / 'native_routes.jsonl')
        self.assertEqual([r['operation'] for r in routes], ['submit'])
        self.assertTrue((self.root / 'native_router_decisions.jsonl').exists())

    async def test_propose_project_without_analysis_fails_then_self_corrects(self):
        # attempt-0056 regression: the actor's submit must reach validation and
        # return an exact correctable receipt instead of being re-decided away.
        actor = self.actors[3]
        original = actor._client.call
        attempts = []
        async def reply(**kwargs):
            if kwargs.get('tools') and actor._submission is None and len(attempts) < 2:
                attempts.append(1)
                observation = actor._policy_observation
                option = next(x for x in observation['candidate_options'] if x['kind'] == 'propose_project')
                variables = {'candidate_id': option['candidate_id'],
                             'reason': '片区4三处同类供水异常，申请立项调查。'}
                if len(attempts) == 2:
                    sources = [row['source_id'] for row in observation['materials']['raw']
                               if row['kind'] == 'contact'][:3]
                    variables['analysis'] = {'source_ids': sources,
                                             'hypothesis': '同片区同类诉求，待现场检验的共同根源假设。'}
                return tool_response('ask_env', {'instruction': 'submit candidate {candidate_id} with reason {reason}',
                                                 'variables': variables, 'readonly': False})
            return await original(**kwargs)
        actor._client.call = reply
        await actor.step(1, self.now)
        self.assertEqual(len(attempts), 2)
        asks = [r for r in rows(actor.workspace_root_path() / 'native_tool_receipts.jsonl') if r['action'] == 'ask_env']
        self.assertEqual(len(asks), 2)
        rejected = json.loads(asks[0]['observation'])
        self.assertEqual(rejected['status'], 'fail')
        self.assertFalse(rejected['receipts'][0]['ok'])
        self.assertIn('analysis', rejected['receipts'][0]['result']['error'])
        accepted = json.loads(asks[1]['observation'])
        self.assertEqual(accepted['status'], 'success')
        self.assertEqual(accepted['receipts'][0]['result']['receipt']['status'], 'queued')
        routes = rows(self.root / 'native_routes.jsonl')
        self.assertEqual([r['operation'] for r in routes], ['submit', 'submit'])
        self.assertEqual([r['ok'] for r in routes], [False, True])
        self.assertEqual(actor._submission['receipt']['status'], 'queued')
        self.assertTrue((self.root / 'native_router_decisions.jsonl').exists())
