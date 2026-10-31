"""PolicyOfficer on the installed PersonAgent lifecycle, without network or Ray."""
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "offline")
os.environ.setdefault("AGENTSOCIETY_CODER_LLM_API_KEY", "offline")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from agentsociety2.agent.memory_runtime import PersonMemoryRuntime
from agentsociety2.agent.base.skill_registry import reset_skill_registry
from policy_sim.agent import PolicyOfficer, ROLE_SKILL_ID, ROLE_SKILL_ROOT, RUNTIME_VERSION, TurnIncomplete, tool_response
from policy_sim.io import canonical, write_json
from policy_sim.profiles import make_profile


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def finish():
    return tool_response("finish", {"memories": [{"type": "observation", "text": "核对本轮材料。", "importance": .2}]})


def ask(instruction, variables, readonly):
    return tool_response("ask_env", {"instruction": instruction, "variables": variables, "readonly": readonly})


class FixtureEnv:
    env_modules = []

    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.calls = []
        self.submission = None
        self.fail_observe = False
        self.invalid_observe = False

    async def get_world_description(self):
        from policy_sim.prompt import WORLD_DESCRIPTION
        return WORLD_DESCRIPTION

    async def ask(self, ctx, instruction, readonly=False, **kwargs):
        self.calls.append((deepcopy(ctx), instruction, readonly))
        observation = {"actor_id": 1, "round": 0, "role": "受理派单员",
                       "candidate_options": [{"candidate_id": "c1"}], "context_sha256": "context"}
        if instruction == "<observe>":
            if self.fail_observe:
                raise RuntimeError("observe unavailable")
            if self.invalid_observe:
                return {}, "{}"
            return {"observation": observation}, canonical(observation)
        if instruction.startswith("read_work"):
            receipt = {"operation": "read_work", "ok": True, "result": {"section": "inbox", "value": []}}
        elif instruction.startswith("submit"):
            if readonly or self.submission is not None:
                receipt = {"operation": "submit", "ok": False, "result": {"error": "submission rejected"}}
            else:
                self.submission = {"action": {"kind": "wait"}, "receipt": {"status": "queued", "submission_id": "s1"}}
                receipt = {"operation": "submit", "ok": True, "result": deepcopy(self.submission)}
        else:
            raise AssertionError("Unexpected request: " + instruction)
        return {"observation": observation, "receipts": [receipt]}, canonical({"receipts": [receipt]})


class Recorder:
    model_name = "offline-policy-fixture"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def for_context(self, purpose, audit_context=None):
        return self

    def raise_if_failed(self):
        pass

    async def call(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self.responses.pop(0)


class AgentSkillTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.no_network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
        self.no_network.start()
        self.addCleanup(self.no_network.stop)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 1, 1)
        self.profile = make_profile()
        write_json(self.root / "run_config.json", {"record": {"run_id": "test", "workload_mode": "finite"},
                                                  "runtime_profile": self.profile})
        self.env = FixtureEnv(self.root)
        self.proxy = SimpleNamespace(env=self.env, llm=SimpleNamespace(default=None))

    async def actor(self, responses, **config):
        folder = self.root / "agents/1"
        PolicyOfficer.create(folder, {"id": 1, "name": "Officer", "bio": "受理派单员"}, {
            "runtime_version": RUNTIME_VERSION, "runtime_profile": self.profile, "decision_mode": "scripted",
            "enable_memory": True, "enable_todo_list": True, "max_react_turns": 10,
            "extra_skill_paths": [str(ROLE_SKILL_ROOT.parent)], "default_activated_skill_ids": [ROLE_SKILL_ID],
            **config})
        actor = await PolicyOfficer.from_workspace(folder, self.proxy)
        client = Recorder(responses)
        actor._client = actor._dispatcher.client = client
        return actor, client

    async def test_static_role_and_todo_survive_official_step_and_restore(self):
        actor, client = await self.actor([
            ask("read_work section {section} offset {offset}", {"section": "inbox", "offset": 0}, True),
            tool_response("todo_add", {"title": "核对下一轮回执"}),
            ask("submit candidate {candidate_id} with reason {reason}", {"candidate_id": "c1", "reason": "等待交接"}, False),
            finish(),
        ])
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(result["submitted"] and result["step_completed"])
        self.assertEqual(result["receipt"]["submission_id"], "s1")
        self.assertEqual([call[1].split()[0] for call in self.env.calls], ["<observe>", "read_work", "submit"])
        for ctx, _, _ in self.env.calls:
            self.assertEqual(ctx["actor_id"], 1)
            UUID(ctx["ask_id"])
        self.assertEqual(actor.skill_runtime.visible_skill_ids(), {ROLE_SKILL_ID})
        self.assertEqual(actor.skill_runtime.activated_skill_ids(), {ROLE_SKILL_ID})
        first = client.calls[0]
        names = {item["function"]["name"] for item in first["tools"]}
        self.assertIn("activate_skill", names)
        self.assertTrue(any(name.startswith("todo_") for name in names))
        self.assertIn("岗位办理指南", first["messages"][0]["content"])
        self.assertIn("每名主体每轮最多提交一次", first["messages"][0]["content"])
        self.assertTrue(rows(actor.workspace_root_path() / "memory/episodes.jsonl"))
        self.assertEqual(len(rows(actor.workspace_root_path() / "native_decisions.jsonl")), 4)
        self.assertEqual(len(rows(actor.workspace_root_path() / "native_tool_receipts.jsonl")), 3)
        self.assertIn("核对下一轮回执", (actor.workspace_root_path() / "TODO.json").read_text())
        await actor.to_workspace(actor.workspace_root_path())
        reset_skill_registry()
        restored = await PolicyOfficer.from_workspace(actor.workspace_root_path(), self.proxy)
        restored_prompt = restored.build_react_messages(tick=1, t=self.now, observations=[])
        self.assertEqual(first["messages"][0]["content"], restored_prompt[0]["content"])
        self.assertEqual(restored.skill_runtime.activated_skill_ids(), {ROLE_SKILL_ID})
        self.assertIn("核对下一轮回执", (await restored.dispatch_react_tool("todo_list", {})).observation)

    async def test_no_submission_and_submitted_exhaustion_use_official_fallback(self):
        no_submission, _ = await self.actor([tool_response("read", {"path": "notes/missing"}) for _ in range(10)])
        result = json.loads(await no_submission.step(1, self.now))
        self.assertTrue(result["unfiled"] and not result["submitted"])
        self.assertTrue(rows(no_submission.workspace_root_path() / "memory/episodes.jsonl"))
        self.assertFalse(no_submission._explicit_finish)

        actor, _ = await self.actor([
            ask("submit candidate {candidate_id} with reason {reason}", {"candidate_id": "c1", "reason": "等待"}, False),
            *[tool_response("read", {"path": "notes/missing"}) for _ in range(9)],
        ])
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(result["submitted"] and not result["unfiled"])
        self.assertFalse(actor._explicit_finish)
        self.assertEqual(result["receipt"]["submission_id"], "s1")

    async def test_native_finish_without_submit_is_unfiled(self):
        actor, _ = await self.actor([finish()])
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(actor._explicit_finish)
        self.assertTrue(result["unfiled"] and not result["submitted"])

    async def test_empty_finish_memories_uses_official_retry(self):
        actor, client = await self.actor([tool_response("finish", {"memories": []}), finish()])
        result = json.loads(await actor.step(1, self.now))
        self.assertTrue(result["unfiled"])
        self.assertEqual(result["schema_repairs"], 1)
        self.assertIn("<schema_error>", client.calls[1]["messages"][-1]["content"])
        decisions = rows(actor.workspace_root_path() / "native_decisions.jsonl")
        self.assertTrue(decisions[0]["response_error"])
        self.assertIsNone(decisions[1]["response_error"])

    async def test_files_and_scripted_builtin_are_outside_the_model_boundary(self):
        actor, _ = await self.actor([finish()])
        identity = (actor.workspace_root_path() / "AGENT.json").read_text()
        for action, args in [
            ("read", {"path": "../2/AGENT.json"}),
            ("write", {"path": "AGENT.json", "content": "corrupt"}),
            ("execute_skill_script", {"skill_name": "daily-guidance", "script_path": "scripts/daily_guidance.py"}),
            ("read_skill_file", {"skill_name": "policy-role", "path": ".env"}),
        ]:
            self.assertFalse((await actor.dispatch_react_tool(action, args)).ok)
        self.assertTrue((await actor.dispatch_react_tool("read_skill_file", {"skill_name": "policy-role", "path": "SKILL.md"})).ok)
        self.assertTrue((await actor.dispatch_react_tool("write", {"path": "notes/a.txt", "content": "note"})).ok)
        self.assertEqual((actor.workspace_root_path() / "AGENT.json").read_text(), identity)

    async def test_observe_and_post_submission_memory_failure_are_fatal(self):
        actor, client = await self.actor([finish()])
        self.env.fail_observe = True
        with self.assertRaises(TurnIncomplete):
            await actor.step(1, self.now)
        self.assertFalse(client.calls)
        self.assertFalse((actor.workspace_root_path() / "state/native-turn.json").exists())

        self.env.fail_observe = False
        self.env.invalid_observe = True
        actor, client = await self.actor([finish()])
        with self.assertRaises(TurnIncomplete):
            await actor.step(1, self.now)
        self.assertFalse(client.calls)
        self.env.invalid_observe = False
        actor, _ = await self.actor([
            ask("submit candidate {candidate_id} with reason {reason}", {"candidate_id": "c1", "reason": "等待"}, False),
            tool_response("finish", {"memories": [{"type": "observation", "text": "重要约束已确认。", "importance": .9}]}),
        ], memory_consolidation_pending_threshold=1, memory_consolidation_interval_steps=1)
        with patch.object(PersonMemoryRuntime, "_consolidate_memory_md", side_effect=RuntimeError("memory unavailable")):
            with self.assertRaises(TurnIncomplete):
                await actor.step(1, self.now)
        self.assertIsNotNone(self.env.submission)
        self.assertFalse((actor.workspace_root_path() / "state/native-turn.json").exists())
        self.assertTrue(rows(actor.workspace_root_path() / "native_failures.jsonl"))

    async def test_missing_default_role_configuration_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "default policy role skill"):
            await self.actor([], default_activated_skill_ids=[])
        with self.assertRaisesRegex(ValueError, "default policy role skill"):
            await self.actor([], extra_skill_paths=[])
