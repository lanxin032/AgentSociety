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
from policy_mve.llm import BoundedClient, MODEL, choose_action, parse_object, validate_action


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


if __name__ == "__main__":
    unittest.main()
