"""Offline behavioral contracts for the shared officer and router modules."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from tests.fixtures import WorkspaceTemporaryDirectory
from policy_mve.io import read_json, write_json
from policy_runtime.officer import OfficerRuntime
from policy_runtime.router import PolicyRouter


class OfficerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.observation = {"actor_id": 2, "round": 3, "available_actions": [
            {"kind": "work", "target": "t1", "params": {}}]}
        self.action = {**self.observation["available_actions"][0], "reason": "visible"}
        self.choose = AsyncMock(return_value=self.action)
        self.scripted = lambda observation: {**self.action, "reason": "scripted"}

    def runtime(self, mode="llm"):
        return OfficerRuntime(2, self.path, decision_mode=mode, scripted_action=self.scripted,
                              choose_action=self.choose)

    def environment(self, status="queued"):
        return SimpleNamespace(ask=AsyncMock(side_effect=[
            ({"observation": deepcopy(self.observation)}, ""), ({"receipt": {"status": status}}, "")]))

    async def test_decision_receipt_and_history_are_one_turn(self):
        write_json(self.path / "state/business.json", {"history": [{"round": 2, "receipt": {"status": "rejected"}}]})
        runtime, environment = self.runtime(), self.environment()
        client = object()
        result = json.loads(await runtime.step(environment, client))
        self.assertEqual(result, {"actor_id": 2, "round": 3, "action": self.action, "receipt": {"status": "queued"}})
        calls = environment.ask.call_args_list
        self.assertEqual(calls[0].args, ({"actor_id": 2}, "observe"))
        self.assertTrue(calls[0].kwargs["readonly"])
        self.assertEqual(calls[1].args, ({"actor_id": 2, "action": self.action}, "submit"))
        self.assertFalse(calls[1].kwargs["readonly"])
        self.assertEqual(self.choose.call_args.args[:2], (client, self.observation))
        self.assertEqual(runtime.history[-1]["receipt"], {"status": "queued"})
        runtime.save(self.path)
        restored = self.runtime()
        self.assertEqual(restored.describe(), runtime.describe())
        self.assertEqual(restored.history[0]["receipt"]["status"], "rejected")

    async def test_wait_only_never_calls_model_and_preserves_reason(self):
        self.observation["available_actions"] = [{"kind": "wait"}]
        runtime = self.runtime()
        result = json.loads(await runtime.step(self.environment(), object()))
        self.assertEqual(result["action"], {"kind": "wait", "target": None, "params": {}, "reason": "无可执行任务"})
        self.choose.assert_not_called()
        rows = [json.loads(line) for line in (self.path / "decisions.jsonl").read_text().splitlines()]
        self.assertEqual(rows, [{"round": 3, "actor_id": 2, "idle": True}])

    async def test_scripted_decisions_keep_priority_even_with_wait_only_observation(self):
        self.observation["available_actions"] = [{"kind": "wait"}]
        runtime = self.runtime(mode="scripted")
        result = json.loads(await runtime.step(self.environment(), object()))
        self.assertEqual(result["action"]["reason"], "scripted")
        self.choose.assert_not_called()

    async def test_all_structured_receipts_are_recorded_without_retry(self):
        for status in ("queued", "duplicate", "rejected", "business_rejected"):
            runtime, environment = self.runtime(), self.environment(status)
            await runtime.step(environment, object())
            self.assertEqual(runtime.history[-1]["receipt"]["status"], status)
            self.assertEqual(environment.ask.await_count, 2)

    async def test_invalid_receipt_or_decision_error_never_commits_history(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, "structured action receipt"):
            await runtime.step(self.environment("missing"), object())
        self.assertEqual(runtime.history, [])
        self.choose.side_effect = RuntimeError("transport failed")
        environment = self.environment()
        with self.assertRaisesRegex(RuntimeError, "transport failed"):
            await runtime.step(environment, object())
        self.assertEqual(environment.ask.await_count, 1)
        self.assertEqual(runtime.history, [])

    async def test_saved_and_reported_history_retains_only_last_three_turns(self):
        runtime = self.runtime()
        for turn in range(5):
            self.observation["round"] = turn
            await runtime.step(self.environment(), object())
        runtime.save(self.path)
        expected = [2, 3, 4]
        self.assertEqual([row["round"] for row in read_json(self.path / "state/business.json")["history"]], expected)
        self.assertEqual([row["round"] for row in json.loads(runtime.describe())["recent_actions"]], expected)


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.round = 0
        self.bindings = []
        self.snapshot = lambda: {"round": self.round}
        async def step(tick, t):
            self.round += 1
        self.env = SimpleNamespace(
            _bind_workspace=self.bindings.append,
            observe=lambda actor: {"actor_id": actor, "round": self.round, "policy": "legacy",
                                   "available_actions": [{"kind": "wait"}]},
            submit=lambda actor, action: {"status": "queued"},
            step=step, init=AsyncMock(), to_workspace=AsyncMock(), restore=AsyncMock(return_value=True),
            close=AsyncMock(), world=SimpleNamespace(export_state=self.snapshot, metrics=lambda: {"count": self.round}))
        # Access round through a property so the router sees the advanced world.
        owner = self
        class World:
            @property
            def round(self):
                return owner.round
            def export_state(self):
                return owner.snapshot()
            def metrics(self):
                return {"count": owner.round}
        self.env.world = World()

    def router(self, transform=None):
        return PolicyRouter(self.env, self.path, "PolicyV3Env", "scripted", None,
                            finalize_observation=transform)

    async def test_four_actor_round_and_checkpoint_cache_restore(self):
        router = self.router()
        self.assertEqual(self.bindings, [self.path / "env/PolicyV3Env"])
        await router.init("start")
        for actor in (1, 2, 3, 4):
            await router.ask({"actor_id": actor, "action": {"kind": "wait"}}, "submit")
            if actor < 4:
                with self.assertRaisesRegex(RuntimeError, "partially submitted"):
                    await router.to_workspaces()
        await router.step(60, "start")
        router.advice_cache["prior"] = {"candidates": [2]}
        await router.to_workspaces()
        self.assertEqual(read_json(self.path / "world.json"), {"round": 1})
        self.assertEqual(router.owner_partial()["submitted"], [])
        restored = self.router()
        self.assertTrue(await restored.from_workspaces())
        self.assertEqual(restored.advice_cache, router.advice_cache)
        await restored.close()
        self.env.close.assert_awaited_once()

    async def test_partial_round_cannot_advance_and_wrong_actor_is_rejected(self):
        router = self.router()
        with self.assertRaisesRegex(RuntimeError, "Incomplete actor phase"):
            await router.step(60, "start")
        for actor in (True, "1", 5, None):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                await router.ask({"actor_id": actor}, "observe", readonly=True)
        self.assertEqual(self.round, 0)

    async def test_checkpoint_round_mismatch_stops_restore(self):
        router = self.router()
        await router.to_workspaces()
        self.round += 1
        with self.assertRaisesRegex(RuntimeError, "checkpoint mismatch"):
            await self.router().from_workspaces()

    async def test_observation_transform_sees_only_final_public_facts(self):
        def transform(observation):
            self.assertNotIn("policy", observation)
            return {**observation, "finalized": True}
        result, _ = await self.router(transform).ask({"actor_id": 1}, "observe", readonly=True)
        self.assertTrue(result["observation"]["finalized"])
        self.assertNotIn("finalized", self.env.observe(1))


if __name__ == "__main__":
    unittest.main()
