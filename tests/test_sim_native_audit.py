"""Independent native-router provenance and lawful early-finish regressions."""
import os
os.environ.setdefault('AGENTSOCIETY_LLM_API_KEY', 'offline')
os.environ.setdefault('AGENTSOCIETY_CODER_LLM_API_KEY', 'offline')
os.environ.setdefault('LITELLM_LOCAL_MODEL_COST_MAP', 'True')
from copy import deepcopy
import json
import hashlib
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from policy_sim.audit import _rows, audit_native, audit_turns
from policy_sim.agent import tool_response
from policy_sim.checkpoints import commit_round
from policy_sim.io import read_json, write_json
from policy_sim.profiles import settings_for_purpose


class NativeAuditTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tests.test_sim_framework import FrameworkTests
        self.fixture = FrameworkTests('test_official_lifecycle_four_finished_barrier_and_restore')
        await self.fixture.asyncSetUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.addCleanup(self.fixture.no_network.stop)
        self.addCleanup(shutil.rmtree, self.fixture.root.parent / (self.fixture.root.name + '-commits'), True)

    async def settle(self):
        for actor in self.fixture.actors:
            await actor.step(1, self.fixture.now)
        await self.fixture.accept_results()
        await self.fixture.router.step(1, self.fixture.now)
        await self.fixture.router.to_workspaces()

    async def freeze_start(self):
        root = self.fixture.root
        frozen = read_json(root / 'run_config.json')
        frozen.update(mode='scripted', horizon=None, request_settings=settings_for_purpose(frozen['runtime_profile']))
        write_json(root / 'run_config.json', frozen)
        write_json(root / 'SOCIETY_STEP.json', {'step_count': 0})
        await self.fixture.router.to_workspaces()
        commit_round(root, 0, self.fixture.router.world.export_state(), [])

    def evidence(self):
        root = self.fixture.root
        return {
            'decisions': [r for p in (root / 'agents').rglob('native_decisions.jsonl') for r in _rows(p)],
            'observations': _rows(root / 'observations.jsonl'), 'actions': _rows(root / 'actions.jsonl'),
            'reads': _rows(root / 'material_reads.jsonl'), 'state': self.fixture.router.world.export_state(),
            'tool_receipts': [r for p in (root / 'agents').rglob('native_tool_receipts.jsonl') for r in _rows(p)],
            'environment_routes': _rows(root / 'native_routes.jsonl'),
            'environment_decisions': _rows(root / 'native_router_decisions.jsonl'),
        }

    async def test_early_finish_records_real_memories_without_submission(self):
        root = self.fixture.root
        await self.freeze_start()
        for actor in self.fixture.actors:
            async def finish(**kwargs):
                return tool_response('finish', {'memories': [
                    {'type': 'observation', 'importance': .2, 'text': '本轮未提交办理。'}]})
            actor._client.call = finish
        await self.settle()
        result = audit_native(root)
        self.assertTrue(result['passed'], result['errors'])
        self.assertEqual(result['checks']['finish_episodes'], 4)
        self.assertFalse(_rows(root / 'actions.jsonl'))
        self.assertFalse(_rows(root / 'native_router_decisions.jsonl'))
        episode_path = self.fixture.actors[0].workspace_root_path() / 'memory/episodes.jsonl'
        episodes = _rows(episode_path)
        self.assertEqual(episodes[0]['text'], '本轮未提交办理。')
        episodes[0]['text'] = '伪造已办理'
        episode_path.write_text(''.join(json.dumps(r) + '\n' for r in episodes))
        self.assertFalse(audit_native(root)['passed'])

    async def test_todo_and_dynamic_skill_prompt_match_saved_personal_workspace(self):
        await self.freeze_start()
        actor = self.fixture.actors[0]
        original = actor._client.call
        calls = iter([('todo_add', {'title': '核实本轮事项', 'due': '09:00'}),
                      ('deactivate_skill', {'skill_name': 'policy-role'}),
                      ('read_skill_file', {'skill_name': 'policy-role', 'path': 'SKILL.md'}),
                      ('activate_skill', {'skill_name': 'policy-role'})])

        async def response(**kwargs):
            if kwargs.get('tools'):
                action = next(calls, None)
                if action:
                    return tool_response(*action)
            return await original(**kwargs)

        actor._client.call = response
        await self.settle()
        result = audit_native(self.fixture.root)
        self.assertTrue(result['passed'], result['errors'])
        todo_path = actor.workspace_root_path() / 'TODO.json'
        saved = read_json(todo_path)
        saved['todos'][0]['title'] = '伪造的个人任务'
        write_json(todo_path, saved)
        self.assertFalse(audit_native(self.fixture.root)['passed'])

    async def test_raw_router_models_and_order_cannot_be_replaced_by_normalized_receipts(self):
        await self.settle()
        evidence = self.evidence()
        self.assertEqual(len(audit_turns(**evidence)[0]), 4)
        for damage in ('response_args', 'route_args', 'model_role', 'hidden_context', 'missing_call', 'extra_call', 'legacy_route'):
            forged = deepcopy(evidence)
            decision = forged['environment_decisions'][0]
            route = forged['environment_routes'][0]
            if damage == 'response_args':
                decision['response']['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{}'
            elif damage == 'route_args':
                route['payload']['reason'] = 'changed after the model responded'
            elif damage == 'model_role':
                decision['model_role'] = 'summary'
            elif damage == 'hidden_context':
                decision['messages'][1]['content'] += '\nHidden world facts'
            elif damage == 'missing_call':
                forged['environment_decisions'].pop(0)
            elif damage == 'extra_call':
                forged['environment_decisions'].insert(1, deepcopy(decision))
            else:
                route['routing'] = 'deterministic_template_dispatch'
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                audit_turns(**forged)

    async def test_router_summary_success_without_tools_stays_unfiled_and_traceable(self):
        from litellm import ModelResponse
        router = self.fixture.router
        original_router = router._scripted_response
        actor = self.fixture.actors[0]
        original_actor = actor._client.call
        actor_calls = 0

        def router_response(model, messages, **kwargs):
            from policy_sim.router import _TRUSTED
            if _TRUSTED.get()['actor'] == 1:
                return ModelResponse(choices=[{'finish_reason': 'stop', 'message': {
                    'role': 'assistant', 'content': '{"status":"success","summary":"Submitted successfully"}'}}])
            return original_router(model, messages, **kwargs)

        async def actor_response(**kwargs):
            nonlocal actor_calls
            if kwargs.get('tools'):
                actor_calls += 1
                if actor_calls > 1:
                    return tool_response('finish', {'memories': [
                        {'type': 'observation', 'importance': .2, 'text': '环境未执行提交。'}]})
            return await original_actor(**kwargs)

        router._scripted_response, actor._client.call = router_response, actor_response
        await self.settle()
        evidence = self.evidence()
        self.assertTrue(audit_turns(**evidence)[0][0, 1]['unfiled'])
        receipt = next(r for r in evidence['tool_receipts'] if r['actor_id'] == 1)
        self.assertEqual(json.loads(receipt['observation']),
                         {'status': 'fail', 'receipts': [], 'error': 'No environment tool executed'})
        evidence['environment_decisions'] = [r for r in evidence['environment_decisions'] if r['actor_id'] != 1]
        with self.assertRaises(ValueError):
            audit_turns(**evidence)

    async def test_router_failed_arguments_then_multiple_tools_are_audited_in_order(self):
        from litellm import ModelResponse
        router = self.fixture.router
        original = router._scripted_response
        queued = {}

        def response(model, messages, **kwargs):
            if model == 'coder' and kwargs.get('tools'):
                submit = original(model, messages, **kwargs)
                raw = submit.choices[0].message.tool_calls[0].function.arguments
                payload = json.loads(raw)
                # The raw router context, rather than a second business oracle,
                # carries the actor's candidate choice for this scripted response.
                from policy_sim.router import _TRUSTED
                ask_id = _TRUSTED.get()['ask_id']
                queued[ask_id] = payload
                calls = []
                for name, args in [('submit', {}), ('observe', {}), ('read_work', {'section': 'candidate_options', 'offset': 0})]:
                    calls.extend(tool_response(name, args).choices[0].message.tool_calls)
                calls[-1].function.arguments = "{section:'candidate_options',offset:0,}"
                return ModelResponse(choices=[{'finish_reason': 'tool_calls', 'message': {
                    'role': 'assistant', 'content': None, 'tool_calls': [c.model_dump(mode='json') for c in calls]}}])
            if model == 'coder' and messages[-1].get('role') == 'tool':
                from policy_sim.router import _TRUSTED
                ask_id = _TRUSTED.get()['ask_id']
                if ask_id in queued:
                    return tool_response('submit', queued.pop(ask_id))
            return original(model, messages, **kwargs)

        router._scripted_response = response
        await self.settle()
        evidence = self.evidence()
        self.assertEqual(len(audit_turns(**evidence)[0]), 4)
        first = evidence['environment_routes'][:4]
        self.assertEqual([r['operation'] for r in first], ['submit', 'observe', 'read_work', 'submit'])
        self.assertEqual([r['ok'] for r in first], [False, True, True, True])
        self.assertEqual([r['router_call_index'] for r in first], [0, 0, 0, 1])
        forged = deepcopy(evidence)
        forged['environment_routes'][0]['ok'] = True
        with self.assertRaises(ValueError):
            audit_turns(**forged)


class NativeRequestUsageTests(unittest.TestCase):
    def test_coder_and_summary_requests_bind_paid_uuid_to_ask_and_call(self):
        from policy_sim.audit_usage import audit_run_usage
        from policy_sim.evidence import append_model_event
        from policy_sim.io import digest
        from policy_sim.profiles import make_profile, profile_digest
        from policy_sim.interface import RUNTIME_VERSION
        with TemporaryDirectory() as directory:
            root, profile = Path(directory).resolve(), make_profile()
            frozen = {'mode': 'llm', 'runtime_profile': profile, 'record': {'run_id': 'usage-test'}}
            traces, receipts, ask_id = [], [], str(uuid4())
            for index, role in enumerate(('coder', 'summary')):
                rid, messages = str(uuid4()), [{'role': 'user', 'content': role}]
                settings = settings_for_purpose(profile, 'environment_routing')
                row = {'schema_version': 'business-request-audit-1', 'request_id': rid,
                       'purpose': 'environment_routing', 'run_id': 'usage-test', 'attempt_id': str(root),
                       'round': 0, 'actor_id': 1, 'ask_id': ask_id, 'substep': index,
                       'runtime_profile_sha256': profile_digest(profile), 'model': profile['model'],
                       'request_settings': settings, 'request_options': {}, 'messages': messages,
                       'input_sha256': digest(messages)}
                raw = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}],
                       'usage': {'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}}
                append_model_event(root / 'model_requests.jsonl', {**row, 'event': 'request_started', 'unix': index * 2})
                append_model_event(root / 'model_requests.jsonl', {**row, 'event': 'request_finished',
                    'unix': index * 2 + 1, 'raw_response': raw, 'usage': raw['usage'], 'usage_source': 'provider_response'})
                wire = json.dumps({**settings, 'messages': messages, 'stream': False, 'n': 1},
                                  ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
                receipts.append({'client_request_id': rid, 'status': 200, 'request_sha256': hashlib.sha256(wire).hexdigest(),
                                 'request_bytes': len(wire), 'prompt_tokens': 2, 'completion_tokens': 3})
                traces.append({'runtime_version': RUNTIME_VERSION, 'round': 0, 'actor_id': 1, 'ask_id': ask_id,
                               'router_call_index': index, 'model_role': role, 'offline': False, 'request_id': rid})
            usage = audit_run_usage(root, frozen, ledger_receipts=receipts, environment_decisions=traces)
            self.assertEqual(usage['by_purpose']['environment_routing']['total_tokens'], 10)
            self.assertEqual(usage['all_requests']['request_count'], 2)
            for damage in ('ask', 'call', 'missing_summary', 'offline', 'response'):
                forged = deepcopy(traces)
                if damage == 'ask':
                    forged[0]['ask_id'] = str(uuid4())
                elif damage == 'call':
                    forged[0]['router_call_index'] = 1
                elif damage == 'missing_summary':
                    forged.pop()
                elif damage == 'offline':
                    forged[0]['offline'] = True
                else:
                    forged[0]['response'] = {}
                with self.subTest(damage=damage), self.assertRaises(ValueError):
                    audit_run_usage(root, frozen, ledger_receipts=receipts, environment_decisions=forged)


if __name__ == '__main__':
    unittest.main()
