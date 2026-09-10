"""V3 guardrails using ordinary-ACL UUID fixtures and mocked model calls."""
import copy
from contextlib import redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_v3.runtime import code_manifest, code_digest, select_run, MODEL_SETTINGS
from policy_v3.llm import choose_action, validate_action
from policy_v3.interface import decorate_observation
from policy_mve.llm import parse_object
from policy_v3.budget import open_stage_ledger, prefix_digest
from policy_v3.execution import ExecutionError, file_hash, source_hash
from tools.smoke_budget import BudgetError


class OrdinaryFixture:
    def make_fixture(self):
        base = (ROOT / "tests").resolve()
        self.fixture = base / ("_v3_runtime_" + uuid.uuid4().hex)
        self.fixture.mkdir()

        def cleanup():
            target = self.fixture.resolve()
            if target.parent != base or not target.name.startswith("_v3_runtime_"):
                raise RuntimeError("Refusing to clean a path outside this test fixture")
            shutil.rmtree(target)

        self.addCleanup(cleanup)

    def write(self, relative, value):
        path = self.fixture / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path


def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")], usage={})


def observation():
    return {"round": 2, "actor_id": 1, "available_actions": [
        {"kind": "route", "target": "T1", "params": {"department": 2, "use_recommendation": False}},
        {"kind": "wait", "target": None, "params": {}},
    ]}


class V3ActionTests(unittest.TestCase):
    def test_copies_only_visible_candidate_and_preserves_parameter_types(self):
        obs = observation()
        action = {**copy.deepcopy(obs["available_actions"][0]), "reason": "visible facts"}
        self.assertEqual(validate_action(action, obs), action)
        mutations = [
            {"target": "hidden-target"}, {"actor_id": 2}, {"kind": "execute_code"},
            {"params": {"department": 2, "use_recommendation": 0}},
            {"params": {"department": 2.0, "use_recommendation": False}},
            {"params": {"department": "2", "use_recommendation": False}},
            {"params": {"department": 2, "use_recommendation": False, "capital": 100}},
        ]
        for change in mutations:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_action({**action, **change}, obs)

    def test_nonfinite_and_nonobject_actions_rejected(self):
        for token in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(token=token), self.assertRaises(ValueError):
                parse_object('{"kind":"wait","params":{"value":' + token + '}}')
        for value in ([], None, {"kind": "wait", "params": {"value": float("inf")}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_action(value, observation())


class V3DecisionTests(OrdinaryFixture, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.make_fixture()

    async def test_exactly_one_schema_repair_then_success(self):
        choice = {"candidate_id": decorate_observation(observation())["candidate_options"][1]["candidate_id"], "reason": "visible wait"}
        client = SimpleNamespace(call=AsyncMock(side_effect=[reply('{"actor_id":4}'), reply(json.dumps(choice))]))
        action = await choose_action(client, observation(), [], self.fixture / "trace.jsonl")
        self.assertEqual(action["kind"], "wait")
        self.assertEqual(client.call.await_count, 2)
        rows = [json.loads(line) for line in (self.fixture / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["attempt"] for r in rows], [0, 1])
        self.assertTrue(all(r["actor_id"] == 1 for r in rows))

    async def test_second_invalid_response_stops_and_transport_is_not_repaired(self):
        client = SimpleNamespace(call=AsyncMock(return_value=reply('[]')))
        with self.assertRaisesRegex(RuntimeError, "one budgeted repair"):
            await choose_action(client, observation(), [], self.fixture / "schema.jsonl")
        self.assertEqual(client.call.await_count, 2)
        client = SimpleNamespace(call=AsyncMock(side_effect=RuntimeError("HTTP 400")))
        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            await choose_action(client, observation(), [], self.fixture / "transport.jsonl")
        self.assertEqual(client.call.await_count, 1)
        self.assertFalse((self.fixture / "transport.jsonl").exists())


class V3ManifestTests(OrdinaryFixture, unittest.TestCase):
    def setUp(self):
        self.make_fixture()

    def test_manifest_covers_python_dependencies_and_excludes_secrets_reports(self):
        included = ["policy_v3/runtime.py", "policy_mve/llm.py", "policy_runtime/checkpoints.py", "custom/agents/officer.py", "tools/driver.py"]
        excluded = [".env.smoke", "policy_v3/settings.json", "tools/notes.md", "runs/budget.json", "custom/__pycache__/old.py"]
        for relative in included + excluded:
            path = self.fixture / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("dummy fixture text", encoding="utf-8")
        manifest = code_manifest(self.fixture)
        self.assertEqual([row["path"] for row in manifest], sorted(included))
        for row in manifest:
            self.assertEqual(row["sha256"], hashlib.sha256((self.fixture / row["path"]).read_bytes()).hexdigest())
        original = code_digest(self.fixture)
        (self.fixture / ".env.smoke").write_text("changed dummy secret")
        self.assertEqual(code_digest(self.fixture), original)
        (self.fixture / "policy_mve/llm.py").write_text("changed dependency")
        self.assertNotEqual(code_digest(self.fixture), original)

    def test_run_selection_rejects_missing_duplicate_and_horizon_mismatch(self):
        row = {"run_id": "r1", "seed": 0, "horizon": 3, "scenario": {"horizon": 3}}
        self.assertEqual(select_run({"runs": [row]}, "r1"), row)
        for manifest in ({"runs": []}, {"runs": [row, row]},
                         {"runs": [{**row, "scenario": {"horizon": 4}}]},
                         {"runs": [{**row, "seed": True}]}, {"runs": [{**row, "horizon": True}]}):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                select_run(manifest, "r1")

    def test_referenced_scenario_must_not_be_ambiguous(self):
        manifest = {"runs": [{"run_id": "r1", "seed": 0, "horizon": 3, "scenario_id": "s1"}],
                    "scenarios": [{"id": "s1", "horizon": 3}, {"id": "s1", "horizon": 3}]}
        with self.assertRaises(ValueError):
            select_run(manifest, "r1")


class CanonicalSyncTests(OrdinaryFixture, unittest.TestCase):
    def setUp(self):
        self.make_fixture()

    def test_guarded_sync_refuses_unknown_bytes_and_updates_without_version_copies(self):
        from tools import sync_mve, sync_v3
        for module, package in ((sync_mve, "policy_mve"), (sync_v3, "policy_v3")):
            with self.subTest(module=module.__name__):
                source = self.fixture / module.__name__.split(".")[-1]
                target = source / "cloud"
                for directory in ("tools", "tests", "custom", "policy_runtime", package):
                    (source / directory).mkdir(parents=True)
                relative = package + "/fixture.py"
                (source / relative).write_text("new source", encoding="utf-8")
                shared_sources = {"policy_runtime/checkpoints.py": "shared checkpoint code",
                                  "tools/mve_driver.py": "MVE caller", "tools/v3_driver.py": "V3 caller"}
                if module is sync_v3:
                    (source / "policy_mve").mkdir(exist_ok=True)
                    shared_sources["policy_mve/io.py"] = "existing shared I/O"
                    (source / "tests/data").mkdir()
                    shared_sources["tests/data/project_lifecycle_v3_1.json"] = "{}"
                for name, contents in shared_sources.items():
                    (source / name).write_text(contents, encoding="utf-8")
                (target / package).mkdir(parents=True)
                (target / relative).write_text("unreviewed source", encoding="utf-8")
                expected = source / "expected.json"
                expected.write_text(json.dumps({relative: hashlib.sha256(b"reviewed source").hexdigest()}))
                output = io.StringIO()
                with patch.object(module, "__file__", str(source / "tools/sync.py")), patch.object(sys, "argv", ["sync", "--expected", str(expected)]), redirect_stdout(output):
                    module.main()
                script = output.getvalue().replace("root=Path('/home/coder/policy-mix').resolve()", "root=Path(" + repr(str(target)) + ").resolve()")
                with self.assertRaisesRegex(RuntimeError, "Unreviewed"):
                    exec(compile(script, "guarded-sync-fixture", "exec"), {})
                self.assertEqual((target / relative).read_text(), "unreviewed source")
                (target / relative).write_text("reviewed source", encoding="utf-8")
                with redirect_stdout(io.StringIO()):
                    exec(compile(script, "guarded-sync-fixture", "exec"), {})
                self.assertEqual((target / relative).read_text(), "new source")
                self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()},
                                 {relative, *shared_sources})
                for name, contents in shared_sources.items():
                    self.assertEqual((target / name).read_text(), contents)


class V3StageBudgetTests(OrdinaryFixture, unittest.TestCase):
    def setUp(self):
        self.make_fixture()
        self.history = [{"request": 1, "status": 200, "reserved_rmb": 0.02, "estimated_rmb": 0.01},
                        {"request": 2, "status": 502, "reserved_rmb": 0.03}]
        self.ledger_path = self.write("runs/api-smoke-budget-20260909.json", self.history)
        self.manifest_path = self.write("manifest.json", {"runs": [{"run_id": "test", "stage": "pilot", "horizon": 3}]})
        self.auth = {
            "authorization_id": "test-only-v3-stage", "stage": "pilot", "model": MODEL_SETTINGS["model"],
            "manifest_sha256": file_hash(self.manifest_path), "source_sha256": source_hash(self.fixture),
            "explicit_stage_authorization": True, "approved": True,
            "user_evidence_reference": "TEST FIXTURE ONLY", "approval_reference": "TEST FIXTURE ONLY",
            "zero_price_user_evidence_reference": "TEST FIXTURE ZERO PRICE", "price_version": "test-zero",
            "api_ledger_path": str(self.ledger_path), "baseline_requests": 2,
            "baseline_prefix_sha256": prefix_digest(self.history), "baseline_accounted_rmb": 0.04,
            "incremental_request_cap": 1, "max_attempts": 1, "incremental_rmb_cap": 0,
            "input_rmb_per_million": 0, "output_rmb_per_million": 0,
        }
        self.auth_path = self.write("test-authorization.json", self.auth)

    def open(self):
        return open_stage_ledger(self.fixture, self.auth_path, self.manifest_path, "pilot")

    def payload(self):
        return {**copy.deepcopy(MODEL_SETTINGS), "messages": [{"role": "user", "content": "test-only"}], "stream": False}

    def test_history_and_unknown_usage_preserved_with_zero_price_request_cap(self):
        original = self.ledger_path.read_bytes()
        ledger = self.open()
        self.assertEqual(self.ledger_path.read_bytes(), original)
        index, _ = ledger.reserve(self.payload())
        ledger.finish(index, 502)
        self.assertEqual(ledger.records[:2], self.history)
        self.assertEqual(ledger.records[2]["authorization_id"], self.auth["authorization_id"])
        self.assertEqual(ledger.records[2]["reserved_rmb"], 0)
        self.assertNotIn("estimated_rmb", ledger.records[2])
        self.assertAlmostEqual(ledger.summary()["accounted_rmb"], 0.04)
        self.assertEqual(ledger.summary()["unknown_usage_requests"], 2)
        with self.assertRaises(BudgetError):
            self.open().reserve(self.payload())

    def test_changed_authorization_or_original_prefix_rejected(self):
        ledger = self.open()
        self.write("test-authorization.json", {**self.auth, "incremental_request_cap": 2})
        with self.assertRaises(BudgetError):
            ledger.reserve(self.payload())
        self.write("test-authorization.json", self.auth)
        altered = copy.deepcopy(self.history)
        altered[0]["estimated_rmb"] = 0
        self.write("runs/api-smoke-budget-20260909.json", altered)
        with self.assertRaises(BudgetError):
            self.open()

    def test_missing_original_ledger_wrong_settings_and_missing_zero_evidence_rejected(self):
        ledger = self.open()
        with self.assertRaises(BudgetError):
            ledger.reserve({**self.payload(), "temperature": 1})
        without_evidence = dict(self.auth)
        without_evidence.pop("zero_price_user_evidence_reference")
        self.write("test-authorization.json", without_evidence)
        with self.assertRaises(ExecutionError):
            self.open()
        self.write("test-authorization.json", self.auth)
        self.ledger_path.unlink()
        with self.assertRaises(BudgetError):
            self.open()
        self.assertFalse(self.ledger_path.exists())

    def test_nonobject_payload_raises_budget_error_for_proxy_fatal_guard(self):
        ledger = self.open()
        for value in ([], None, 1):
            with self.subTest(value=value), self.assertRaises(BudgetError):
                ledger.reserve(value)
        self.assertEqual(ledger.records, self.history)


if __name__ == "__main__":
    unittest.main()
