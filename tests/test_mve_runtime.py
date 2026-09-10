"""Offline runtime boundaries: mocked model calls and synthetic checkpoints only."""
import asyncio
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fixtures import WorkspaceTemporaryDirectory
from policy_mve.io import append_jsonl, digest, write_json
from policy_mve.llm import BoundedClient, MODEL, choose_action, parse_object, validate_action
from mve_driver import checkpoint_files, validate_commit, validate_round_state


def response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")], usage={})


class ActionBoundaryTests(unittest.TestCase):
    def test_action_cannot_supply_identity_policy_or_resources(self):
        for field in ("actor_id", "role", "state", "policy", "resources", "capital"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_action({"kind": "wait", field: "override"})

    def test_parser_requires_one_finite_json_object(self):
        for raw in ('[]', 'null', 'true', '{"kind":"wait"} {"kind":"work"}',
                    '{"params":{"amount":NaN}}', '{"params":{"amount":Infinity}}',
                    '{"params":{"amount":-Infinity}}', '{"params":{"amount":1e999}}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_object(raw)

    def test_valid_fenced_object_and_incomplete_fence(self):
        self.assertEqual(parse_object('```json\n{"kind":"wait"}\n```'), {"kind": "wait"})
        with self.assertRaises(ValueError):
            parse_object('```')

    def test_invalid_action_schema_rejected(self):
        for value in ({}, {"kind": 1}, {"kind": "wait", "params": []},
                      {"kind": "wait", "reason": 5}, {"kind": "wait", "reason": "x" * 1001}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_action(value)


class DecisionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.trace = Path(self.directory.name) / "decisions.jsonl"
        self.observation = {"round": 0, "actor_id": 2, "available_actions": [{"kind": "wait"}]}

    async def test_bad_schema_receives_exactly_one_repair(self):
        calls = []

        async def call(model, messages):
            calls.append(copy.deepcopy(messages))
            return response('{"actor_id":1,"kind":"wait"}' if len(calls) == 1 else '{"kind":"wait"}')

        client = SimpleNamespace(call=call)
        action = await choose_action(client, self.observation, [], self.trace)
        self.assertEqual(action["kind"], "wait")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[0]), 2)
        self.assertEqual(len(calls[1]), 4)
        entries = [json.loads(line) for line in self.trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["attempt"] for row in entries], [0, 1])
        self.assertTrue(all(row["actor_id"] == 2 for row in entries))

    async def test_second_schema_failure_stops(self):
        client = SimpleNamespace(call=AsyncMock(return_value=response('[]')))
        with self.assertRaisesRegex(RuntimeError, "after one repair"):
            await choose_action(client, self.observation, [], self.trace)
        self.assertEqual(client.call.await_count, 2)

    async def test_extra_business_parameter_receives_one_schema_repair(self):
        client = SimpleNamespace(call=AsyncMock(side_effect=[
            response('{"kind":"inspect","target":"T00007","params":{"facility":"F3-1"}}'),
            response('{"kind":"propose_project","target":"片区3|供水波动","params":{"mode":"structured"}}')]))
        action = await choose_action(client, self.observation, [], self.trace)
        self.assertEqual(action["kind"], "propose_project")
        self.assertEqual(client.call.await_count, 2)

    async def test_incomplete_fence_is_repaired(self):
        client = SimpleNamespace(call=AsyncMock(side_effect=[response('```'), response('{"kind":"wait"}')]))
        action = await choose_action(client, self.observation, [], self.trace)
        self.assertEqual(action["kind"], "wait")
        self.assertEqual(client.call.await_count, 2)

    async def test_http_failure_is_never_retried_or_repaired(self):
        for status in (400, 401, 429, 500):
            with self.subTest(status=status):
                client = BoundedClient("http://127.0.0.1:12345/v1")
                error = HTTPError("http://127.0.0.1", status, "synthetic failure", {}, None)
                with patch("policy_mve.llm.urlopen", side_effect=error) as upstream:
                    with self.assertRaisesRegex(RuntimeError, f"HTTP {status}"):
                        await choose_action(client, self.observation, [], self.trace)
                    self.assertEqual(upstream.call_count, 1)
                self.assertEqual(client.calls, 0)
        self.assertFalse(self.trace.exists())

    async def test_non_loopback_endpoint_rejected_before_network(self):
        for base in ("https://example.invalid/v1", "http://192.0.2.1/v1", "https://127.0.0.1/v1"):
            with self.subTest(base=base), patch("policy_mve.llm.urlopen") as upstream:
                with self.assertRaises(ValueError):
                    await BoundedClient(base).call(MODEL, [])
                upstream.assert_not_called()


class CommitTests(unittest.TestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run_dir = Path(self.directory.name)
        self.world = {"round": 1, "cases": [{"id": "case-1", "resolved": False}]}
        for name, value in {
            "SOCIETY.json": {"agent_ids": [1, 2, 3, 4]},
            "SOCIETY_STEP.json": {"step_count": 1}, "world.json": self.world,
            "metrics.json": {"resolved": 0}, "run_config.json": {"mode": "scripted"},
            "env/PolicyCaseEnv/state/ENV_STATE.json": self.world,
            "env/PolicyCaseEnv/router.json": {"round": 1},
        }.items():
            write_json(self.run_dir / name, value)
        for identifier in (1, 2, 3, 4):
            folder = self.run_dir / "agents" / f"agent_{identifier:04d}"
            write_json(folder / "AGENT.json", {"id": identifier, "step_count": 1})
            write_json(folder / "config.json", {"decision_mode": "scripted"})
            write_json(folder / "state/business.json", {"history": [{"round": 0}]})
            append_jsonl(folder / "decisions.jsonl", {"round": 0, "kind": "wait"})
        append_jsonl(self.run_dir / "actions.jsonl", {"round": 0, "actor_id": 1})
        self.committed = {"round": 1, "world_sha256": digest(self.world), "files": checkpoint_files(self.run_dir)}
        write_json(self.run_dir / "committed.json", self.committed)

    def test_intact_checkpoint_validates(self):
        self.assertEqual(validate_commit(self.run_dir), self.committed)
        validate_round_state(self.run_dir, 1)

    def test_round_validation_rejects_stale_society(self):
        write_json(self.run_dir / "SOCIETY_STEP.json", {"step_count": 0})
        with self.assertRaises(RuntimeError):
            validate_round_state(self.run_dir, 1)

    def test_round_validation_rejects_duplicate_identity_and_stale_actor(self):
        path = self.run_dir / "agents/agent_0004/AGENT.json"
        for state in ({"id": 1, "step_count": 1}, {"id": 4, "step_count": 0}):
            write_json(path, state)
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                validate_round_state(self.run_dir, 1)

    def test_round_validation_rejects_missing_actor(self):
        (self.run_dir / "agents/agent_0004/AGENT.json").unlink()
        with self.assertRaises(RuntimeError):
            validate_round_state(self.run_dir, 1)

    def test_round_validation_rejects_stale_business_history(self):
        for history in ([], [{"round": -1}]):
            write_json(self.run_dir / "agents/agent_0004/state/business.json", {"history": history})
            with self.subTest(history=history), self.assertRaises(RuntimeError):
                validate_round_state(self.run_dir, 1)

    def test_world_tampering_rejected(self):
        write_json(self.run_dir / "world.json", {"round": 2})
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_each_actor_checkpoint_tampering_rejected(self):
        for identifier in (1, 2, 3, 4):
            path = self.run_dir / "agents" / f"agent_{identifier:04d}" / "AGENT.json"
            original = path.read_bytes()
            try:
                write_json(path, {"id": identifier, "step_count": 0})
                with self.subTest(identifier=identifier), self.assertRaises(RuntimeError):
                    validate_commit(self.run_dir)
            finally:
                path.write_bytes(original)

    def test_event_tail_append_rejected(self):
        append_jsonl(self.run_dir / "actions.jsonl", {"round": 1, "actor_id": 1})
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_agent_decision_tail_append_rejected(self):
        append_jsonl(self.run_dir / "agents/agent_0002/decisions.jsonl", {"round": 1})
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_missing_checkpoint_rejected(self):
        (self.run_dir / "agents/agent_0004/AGENT.json").unlink()
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)


if __name__ == "__main__":
    unittest.main()
