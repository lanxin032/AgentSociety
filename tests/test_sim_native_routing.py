"""Actual installed environment loop with offline responses and fault injection."""
import json
import shutil
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import uuid4

try:
    from tests import test_sim_framework as framework
except ImportError:
    import test_sim_framework as framework

from litellm import ModelResponse
from policy_sim.agent import tool_response
from policy_sim.agent import PolicyOfficer
from policy_sim.router import PolicyRouter


class NativeRoutingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = framework.FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await self.fixture.asyncSetUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.addCleanup(self.fixture.no_network.stop)
        self.router = self.fixture.router
        self.ctx = {'actor_id': 1, 'round': 0, 'ask_id': str(uuid4())}
        await self.router.ask(self.ctx, '<observe>', readonly=True)
        self.option = next(row for row in self.router.observed[1].observation['candidate_options']
                           if row['kind'] == 'wait')

    async def test_native_loop_runs_multiple_tools_and_records_only_actual_submission(self):
        responses = [tool_response('read_work', {'section': 'candidate_options', 'offset': 0}),
                     tool_response('submit', {'candidate_id': self.option['candidate_id'], 'reason': '等待交接'})]
        original = self.router._scripted_response
        prompts = []
        def reply(model, messages, **kwargs):
            prompts.append(deepcopy(messages))
            if model == 'coder' and responses:
                return responses.pop(0)
            return original(model, messages, **kwargs)
        self.router._scripted_response = reply
        ctx = {**self.ctx, 'ask_id': str(uuid4()), 'hidden_extra_context': 'must not reach model'}
        result, answer = await self.router.ask(ctx, '查看合法候选并提交等待', readonly=False)
        self.assertEqual([row['operation'] for row in result['receipts']], ['read_work', 'submit'])
        self.assertEqual(json.loads(answer)['receipts'], result['receipts'])
        self.assertEqual(self.router.submitted, {1})
        self.assertNotIn('hidden_extra_context', json.dumps(prompts))
        traces = framework.rows(self.fixture.root / 'native_router_decisions.jsonl')
        self.assertEqual([row['router_call_index'] for row in traces], list(range(4)))
        self.assertEqual([row['model_role'] for row in traces], ['coder', 'coder', 'coder', 'summary'])
        routes = framework.rows(self.fixture.root / 'native_routes.jsonl')
        self.assertEqual([row['router_call_index'] for row in routes], [0, 1])
        self.assertTrue(all(row['routing'] == 'official_react' for row in routes))

    async def test_model_success_without_tool_does_not_create_submission(self):
        original = self.router._scripted_response
        def reply(model, messages, **kwargs):
            if model == 'coder':
                return ModelResponse(choices=[{'finish_reason': 'stop', 'message': {
                    'role': 'assistant', 'content': 'Everything succeeded.'}}])
            return original(model, messages, **kwargs)
        self.router._scripted_response = reply
        _, answer = await self.router.ask({**self.ctx, 'ask_id': str(uuid4())}, '完成提交', readonly=False)
        self.assertEqual(json.loads(answer), {'status': 'fail', 'receipts': [],
                                             'error': 'No environment tool executed'})
        self.assertFalse(self.router.submitted)
        self.assertFalse(framework.rows(self.fixture.root / 'actions.jsonl'))

    async def test_routing_requests_use_the_existing_metered_client_for_both_roles(self):
        original = self.router._scripted_response
        calls = []
        async def call(**kwargs):
            calls.append(deepcopy(kwargs))
            role = 'coder' if len(calls) <= 2 else 'summary'
            return original(role, kwargs['messages'], **{k: v for k, v in kwargs.items()
                            if k not in {'messages', 'model', 'audit_context'}})
        self.router.decision_mode = 'llm'
        self.router.llm_client = SimpleNamespace(model_name='fixture', call=call)
        payload = {'candidate_id': self.option['candidate_id'], 'reason': '等待'}
        await self.router.ask({**self.ctx, 'ask_id': str(uuid4()), 'variables': payload},
                              'submit supplied candidate', readonly=False)
        self.assertEqual(len(calls), 3)
        for index, request in enumerate(calls):
            self.assertEqual(request['model'], 'fixture')
            self.assertEqual(request['audit_context']['purpose'], 'environment_routing')
            self.assertEqual(request['audit_context']['substep'], index)
            self.assertEqual(request['audit_context']['actor_id'], 1)
        self.assertNotIn('tools', calls[-1])

    async def test_routing_failure_and_truncation_never_execute_tools(self):
        response = tool_response('submit', {'candidate_id': self.option['candidate_id'], 'reason': '等待'})
        response.choices[0].finish_reason = 'length'
        self.router._scripted_response = lambda *args, **kwargs: response
        with self.assertRaises(RuntimeError):
            await self.router.ask({**self.ctx, 'ask_id': str(uuid4()), 'variables': {}},
                                  'submit current candidate', readonly=False)
        self.assertFalse(self.router.submitted)
        self.assertFalse(framework.rows(self.fixture.root / 'native_routes.jsonl'))
        with self.assertRaises(RuntimeError):
            await self.router.to_workspaces()

    async def test_saved_actor_result_is_required_and_cannot_be_forged(self):
        for actor in self.fixture.actors:
            await actor.step(1, self.fixture.now)
        with self.assertRaises(RuntimeError):
            await self.router.step(1, self.fixture.now)
        actor = self.fixture.actors[0]
        summary = json.loads((actor.workspace_root_path() / 'state/native-turn.json').read_text())
        forged = {**summary, 'action': {**summary['action'], 'reason': 'forged'}}
        with self.assertRaises(RuntimeError):
            self.router.owner_actor_results([{'id': 1, 'ok': True, 'summary': json.dumps(forged)}])
        self.assertFalse(self.router.completed)
        await self.fixture.accept_results()
        with self.assertRaises(RuntimeError):
            self.router.owner_actor_results([{'id': 1, 'ok': True, 'summary': json.dumps(summary)}])
        await self.router.step(1, self.fixture.now)
        self.assertEqual(self.router.world.round, 1)
        await self.router.to_workspaces()
        self.assertEqual(self.router.owner_checkpoint_status(), {'round': 1})

    async def test_environment_save_failure_remains_visible_to_society(self):
        for actor in self.fixture.actors:
            await actor.step(1, self.fixture.now)
        await self.fixture.accept_results()
        await self.router.step(1, self.fixture.now)
        with patch('policy_sim.router.write_json', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                await self.router.to_workspaces()
        with self.assertRaises(RuntimeError):
            self.router.owner_checkpoint_status()

    async def test_route_evidence_failure_stops_before_next_model_call(self):
        from policy_sim import router as implementation
        original = implementation.append_jsonl
        failed = []
        def append(path, value):
            if Path(path).name == 'native_routes.jsonl' and not failed:
                failed.append(True)
                raise OSError('route evidence write failed')
            return original(path, value)
        candidate = {'candidate_id': self.option['candidate_id'], 'reason': '等待'}
        responses = [tool_response('read_work', {'section': 'inbox'}), tool_response('submit', candidate)]
        original_response = self.router._scripted_response
        def reply(model, messages, **kwargs):
            if model == 'coder' and responses:
                return responses.pop(0)
            return original_response(model, messages, **kwargs)
        self.router._scripted_response = reply
        with patch.object(implementation, 'append_jsonl', append), self.assertRaises(RuntimeError):
            await self.router.ask({**self.ctx, 'ask_id': str(uuid4())}, '查看后提交等待', readonly=False)
        self.assertTrue(failed)
        self.assertIsNotNone(self.router.fatal_error)
        self.assertFalse(self.router.submitted)
        decisions = framework.rows(self.fixture.root / 'native_router_decisions.jsonl')
        self.assertEqual([row['model_role'] for row in decisions], ['coder'])
        with self.assertRaises(RuntimeError):
            await self.router.to_workspaces()

    async def test_action_evidence_failure_blocks_settlement_and_further_requests(self):
        from policy_sim import router as implementation
        original = implementation.append_jsonl
        def append(path, value):
            if Path(path).name == 'actions.jsonl':
                raise OSError('action evidence write failed')
            return original(path, value)
        payload = {'candidate_id': self.option['candidate_id'], 'reason': '等待'}
        with patch.object(implementation, 'append_jsonl', append), self.assertRaises(RuntimeError):
            await self.router.ask({**self.ctx, 'ask_id': str(uuid4()), 'variables': payload},
                                  'submit supplied candidate', readonly=False)
        self.assertIsNotNone(self.router.fatal_error)
        self.assertEqual(len(framework.rows(self.fixture.root / 'native_router_decisions.jsonl')), 1)
        with self.assertRaises(RuntimeError):
            await self.router.step(1, self.fixture.now)
        self.assertEqual(self.router.world.round, 0)

    async def test_initial_observation_evidence_failure_locks_shared_environment(self):
        from policy_sim import router as implementation
        original = implementation.append_jsonl
        def append(path, value):
            if Path(path).name == 'observations.jsonl':
                raise OSError('observation evidence write failed')
            return original(path, value)
        ctx = {'actor_id': 2, 'round': 0, 'ask_id': str(uuid4())}
        with patch.object(implementation, 'append_jsonl', append), self.assertRaises(OSError):
            await self.router.ask(ctx, '<observe>', readonly=True)
        self.assertIsNotNone(self.router.fatal_error)
        with self.assertRaises(RuntimeError):
            await self.router.ask({**ctx, 'actor_id': 3, 'ask_id': str(uuid4())}, '<observe>', readonly=True)
        self.assertNotIn(3, self.router.observed)

    async def test_restored_native_round_matches_uninterrupted_round(self):
        for actor in self.fixture.actors:
            await actor.step(1, self.fixture.now)
        await self.fixture.accept_results()
        await self.router.step(1, self.fixture.now)
        await self.router.to_workspaces()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        resumed_path = Path(temporary.name) / 'resumed'
        shutil.copytree(self.fixture.root, resumed_path)
        resumed = PolicyRouter(resumed_path, '000', 3001, None, 'scripted', None)
        self.assertTrue(await resumed.init(self.fixture.now))
        now = self.fixture.now + timedelta(seconds=1)
        for router, run_dir in ((self.router, self.fixture.root), (resumed, resumed_path)):
            router.set_current_time(now)
            proxy = SimpleNamespace(env=router, llm=SimpleNamespace(default=None))
            for identifier in (1, 2, 3, 4):
                actor = await PolicyOfficer.from_workspace(run_dir / 'agents' / str(identifier), proxy)
                summary = await actor.step(1, now)
                await actor.to_workspace(actor.workspace_root_path())
                router.owner_actor_results([{'id': identifier, 'ok': True, 'summary': summary}])
            await router.step(1, now)
            await router.to_workspaces()
            self.assertEqual(router.owner_checkpoint_status(), {'round': 2})
        self.assertEqual(resumed.world.export_state(), self.router.world.export_state())
        self.assertEqual(resumed.mailbox.receipts, self.router.mailbox.receipts)
