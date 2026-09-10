import asyncio
import ast
import copy
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import unittest

from policy_v3.interface import decorate_observation, decode_candidate_choice, raw_observation
from policy_v3.llm import choose_action, REPAIR_PROMPT
from policy_mve.io import digest


class InterfaceTests(unittest.TestCase):
    def raw(self):
        return {"actor_id": 2, "round": 4, "available_actions": [
            {"kind": "wait", "target": None, "params": {}, "reason": "visible"},
            {"kind": "work", "target": "task-1", "params": {"amount": 1}, "reason": "visible"}],
            "visible_tickets": [], "projects": [], "inbox": [], "sent_messages": []}

    def test_pure_idempotent_and_preserves_candidates(self):
        raw = self.raw()
        before = deepcopy(raw)
        obs = decorate_observation(raw)
        self.assertEqual(raw, before)
        self.assertEqual(raw_observation(obs), raw)
        self.assertEqual(decorate_observation(obs), obs)
        obs["available_actions"][1]["params"]["amount"] = 99
        self.assertEqual(raw, before)

    def test_context_bound_ids_and_strict_choice(self):
        raw = self.raw()
        obs = decorate_observation(raw)
        choice = {"candidate_id": obs["candidate_options"][1]["candidate_id"], "reason": "visible"}
        self.assertEqual(decode_candidate_choice(choice, obs), raw["available_actions"][1])
        for key, value in (("actor_id", 3), ("round", 5), ("new_visible_fact", "updated")):
            modified = deepcopy(raw)
            modified[key] = value
            with self.assertRaises(ValueError):
                decode_candidate_choice(choice, modified)
        for bad in ({}, {**choice, "target": "hidden"}, {**choice, "candidate_id": 1},
                    {**choice, "reason": None}, {**choice, "reason": "x" * 1001},
                    {**choice, "candidate_id": "missing"}, {"candidate_id": choice["candidate_id"]}):
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(ValueError):
                decode_candidate_choice(bad, obs)
        tampered = deepcopy(obs)
        tampered["candidate_options"][1]["target"] = "hidden"
        self.assertEqual(decode_candidate_choice(choice, tampered)["target"], "task-1")

    def test_parameter_json_types_change_id(self):
        obs = decorate_observation(self.raw())
        raw = self.raw()
        raw["available_actions"][1]["params"]["amount"] = True
        self.assertNotEqual(obs["candidate_options"], decorate_observation(raw)["candidate_options"])

    def test_six_frozen_observations_no_extra_facts(self):
        base = Path(__file__).resolve().parents[1] / "research/v3_20260910_revision/benchmark/observations"
        for path in sorted(base.glob("C*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            obs = decorate_observation(raw)
            self.assertEqual(raw_observation(obs), raw)
            self.assertEqual(len(obs["candidate_options"]), len(raw["available_actions"]))
            self.assertEqual(decorate_observation(obs), obs)
            for item in obs["candidate_options"]:
                action = decode_candidate_choice({"candidate_id": item["candidate_id"], "reason": "visible"}, obs)
                self.assertIn({k: action[k] for k in ("kind", "target", "params")},
                    [{k: a[k] for k in ("kind", "target", "params")} for a in raw["available_actions"]])
            for obj in obs["evidence_index"]["objects"]:
                for task in obj["tasks"]:
                    self.assertEqual(task["current_other_actor_actual_state"], "unknown")
        self.assertEqual(len(list(base.glob("C*.json"))), 6)

    def test_mode_never_infers_dispatch_or_confirmation(self):
        raw = self.raw()
        raw["projects"] = [{"id": "P:1", "tasks": [{"id": "t", "actor": 3, "state": "pending"}]}]
        for mode in ("ordinary", "structured", "zero"):
            raw["projects"][0]["mode"] = mode
            raw["zero_communication_friction"] = mode == "zero"
            obj = decorate_observation(raw)["evidence_index"]["objects"][0]
            self.assertEqual(obj["own_confirmation"]["value"], "unknown")
            self.assertEqual(obj["visible_confirmation_records"], [])
            self.assertEqual(obj["tasks"][0]["dispatch_sent_evidence"], [])

    def test_only_assignment_payload_is_dispatch_evidence(self):
        raw = self.raw()
        raw["projects"] = [{"id": "P:1", "own_confirmed": False,
            "received_records": [{"author": 3, "kind": "project_confirmation", "data": {"accepted": True}}],
            "tasks": [{"id": "t", "actor": 3, "state": "pending"}]}]
        assignment = {"id": "m", "object": "P:1", "kind": "construction_assignment", "payload": {"tasks": [{"id": "t"}]}}
        query = {**assignment, "kind": "status_query"}
        raw["sent_messages"] = [query, assignment]
        raw["inbox"] = [assignment]
        obj = decorate_observation(raw)["evidence_index"]["objects"][0]
        self.assertEqual(obj["own_confirmation"]["value"], False)
        self.assertEqual(obj["visible_confirmation_records"][0]["author"], 3)
        task = obj["tasks"][0]
        self.assertEqual(task["dispatch_sent_evidence"], ["/sent_messages/1/payload/tasks/0"])
        self.assertEqual(task["received_assignment_evidence"], ["/inbox/0/payload/tasks/0"])
        self.assertEqual(task["current_other_actor_actual_state"], "unknown")

    def test_mock_choice_repair_and_trace(self):
        obs = decorate_observation(self.raw())
        valid = json.dumps({"candidate_id": obs["candidate_options"][1]["candidate_id"], "reason": "visible"})
        class Client:
            def __init__(self, values):
                self.values, self.calls = list(values), []
            async def call(self, model, messages):
                self.calls.append(deepcopy(messages))
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.values.pop(0)), finish_reason="stop")], usage={})
        records = []
        with patch("policy_v3.llm.append_jsonl", side_effect=lambda path, row: records.append(deepcopy(row))):
            path = Path("unused_mock_trace.jsonl")
            client = Client(['{"candidate_id":"invalid","reason":"x"}', valid])
            action = asyncio.run(choose_action(client, obs, [], path))
            self.assertEqual(action["target"], "task-1")
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(client.calls[1][-1]["content"], REPAIR_PROMPT)
            self.assertIn("validation_error", records[0])
            self.assertEqual(records[1]["decoded_action"], action)
            self.assertEqual(records[1]["candidate_options"], obs["candidate_options"])
            client = Client(['{}', '{}'])
            with self.assertRaises(RuntimeError):
                asyncio.run(choose_action(client, obs, [], path))
            self.assertEqual(len(client.calls), 2)

    def test_joint_invitation_and_string_task_record(self):
        raw = self.raw()
        raw["visible_tickets"] = [{"id": "T:1", "joint_invitation": {"own_confirmed": False},
            "tasks": [{"id": "t", "actor": 3, "state": "pending"}],
            "received_records": [{"kind": "capacity_obstacle", "data": {"task": "t"}}]}]
        raw["sent_messages"] = [{"kind": "joint_invitation", "object": "T:1", "payload": {"tasks": [{"id": "t"}]}}]
        obj = decorate_observation(raw)["evidence_index"]["objects"][0]
        self.assertEqual(obj["own_confirmation"], {"value": False, "source": "/visible_tickets/0/joint_invitation/own_confirmed"})
        task = obj["tasks"][0]
        self.assertEqual(task["dispatch_sent_evidence"], ["/sent_messages/0/payload/tasks/0"])
        self.assertEqual(task["received_record_evidence"], ["/visible_tickets/0/received_records/0"])
        self.assertEqual(task["current_other_actor_actual_state"], "unknown")

    def test_actual_router_advice_then_choice_rebinds_ids(self):
        # Execute the actual method ASTs without importing the optional cloud registry.
        root = Path(__file__).resolve().parents[1]
        namespace = {"copy": copy, "json": json, "digest": digest,
                     "decorate_observation": decorate_observation, "append_jsonl": lambda *args: None}
        for relative, name, methods in (("policy_mve/router.py", "PolicyRouterActor", {"ask", "enrich_advice"}),
                                       ("policy_v3/router.py", "PolicyV3RouterActor", {"enrich_advice"})):
            tree = ast.parse((root / relative).read_text(encoding="utf-8"))
            cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
            cls.body = [node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name in methods]
            module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
            exec(compile(module, str(root / relative), "exec"), namespace)
        raw = self.raw()
        raw.update(actor_id=1, policy="legacy")
        raw["visible_tickets"] = [{"id": "T:1", "a_offered": True, "lead": None, "closed": False,
                                  "text": "visible text", "category": "water", "district": "d", "facility": "f"}]
        raw["available_actions"] = [{"kind": "route", "target": "T:1", "params": {"department": 2, "use_recommendation": True}, "reason": "visible"}]
        original = decorate_observation(raw)
        router = namespace["PolicyV3RouterActor"]()
        router.env = SimpleNamespace(observe=lambda actor: deepcopy(original))
        router.run_dir = Path("mock")
        router.decision_mode = "llm"
        router.advice_cache = {}
        class Client:
            async def call(self, model, messages):
                if "candidate_options" in messages[-1]["content"]:
                    payload = json.loads(messages[-1]["content"])
                    self.payload = payload
                    content = json.dumps({"candidate_id": payload["observation"]["candidate_options"][0]["candidate_id"], "reason": "visible"})
                else:
                    content = '{"candidates":[3],"uncertain":true,"basis":"visible directory"}'
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")], usage={})
        client = router.llm_client = Client()
        payload, _ = asyncio.run(router.ask({"actor_id": 1}, "observe", readonly=True))
        obs = payload["observation"]
        self.assertNotIn("policy", obs)
        self.assertEqual(obs["available_actions"][0]["params"]["department"], 3)
        self.assertNotEqual(original["context_sha256"], obs["context_sha256"])
        self.assertEqual(decorate_observation(obs), obs)
        with self.assertRaises(ValueError):
            decode_candidate_choice({"candidate_id": original["candidate_options"][0]["candidate_id"], "reason": "visible"}, obs)
        history = [{"receipt": "visible history"}]
        with patch("policy_v3.llm.append_jsonl"):
            action = asyncio.run(choose_action(client, obs, history, Path("mock")))
        self.assertEqual(action["params"]["department"], 3)
        self.assertEqual(client.payload["observation"], obs)
        self.assertEqual(client.payload["recent_history"], history)
        self.assertEqual(original, decorate_observation(raw))


if __name__ == "__main__":
    unittest.main()
