"""Collector contract tests with mocked verification and synthetic fixtures.

No fixture here is a real model run or formal research evidence. No verifier,
framework, cloud service or model is executed by these tests.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import uuid

from policy_mve.io import digest, write_json
from tools.collect_v3_records import collect
from policy_v3.spec import SPEC_VERSION


class CollectRecordTests(unittest.TestCase):
    def setUp(self):
        self.workspace = Path(__file__).resolve().parents[1]
        # Default mkdir permissions avoid tempfile's Windows mode=0700 ACL issue.
        self.folder = self.workspace / (".test-v3-collect-" + uuid.uuid4().hex)
        self.folder.mkdir()
        self.source = [{"path": "policy_v3/core.py", "sha256": "a" * 64},
                       {"path": "policy_v3/spec.py", "sha256": "b" * 64}]
        scenario = {"id": "synthetic_collector_fixture", "family": "static", "horizon": 60,
                    "q": {"A": 0.0, "B": 0.0, "C": 0.0},
                    "schedule": [{"start": 0, "end": 60, "q": {"A": 0.0, "B": 0.0, "C": 0.0}}],
                    "environment": "baseline"}
        self.records = [{"run_id": f"synthetic_collector_fixture_{index}", "stage": "static",
                         "scenario_id": scenario["id"], "seed": 3001 + index, "replicate": 0,
                         "horizon": 60, "scenario": deepcopy(scenario), "status": "awaiting_pilot_freeze",
                         "metrics": None, "verification": None, "path": None,
                         "record_origin": "synthetic_unit_test_fixture_not_a_real_run"}
                        for index in range(2)]
        self.design = {"runs": deepcopy(self.records)}

    def tearDown(self):
        # Recursive cleanup is constrained to this test's verified UUID child.
        resolved = self.folder.resolve()
        self.assertEqual(resolved.parent, self.workspace.resolve())
        self.assertTrue(resolved.name.startswith(".test-v3-collect-"))
        if resolved.exists():
            shutil.rmtree(resolved)

    def save_fixture(self, index=0, mode="llm", mutate=None, completed_round=60, name=None):
        path = self.folder / (name or f"run-{index}")
        path.mkdir()
        record = deepcopy(self.records[index])
        if mutate:
            mutate(record)
        write_json(path / "run_config.json", {"record": record, "mode": mode,
                   "code_manifest": self.source, "fixture_origin": "synthetic_unit_test_only"})
        write_json(path / "metrics.json", {"round": completed_round, "horizon": 60,
                   "cumulative_issue_burden": 120, "fixture_origin": "synthetic_unit_test_only"})
        return path

    def verification(self, passed=True, full_horizon=True, mode="llm"):
        return {"passed": passed, "full_horizon": full_horizon, "mode": mode,
                "spec_version": SPEC_VERSION, "source_manifest_sha256": digest(self.source),
                "errors": [] if passed else ["synthetic verifier failure for unit test"],
                "fixture_origin": "mocked_verifier_not_actual_verification"}

    def test_duplicate_run_id_requires_explicit_attempt_selection(self):
        first = self.save_fixture(name="first-attempt")
        second = self.save_fixture(name="second-attempt")
        with patch("tools.collect_v3_records.verify_run", return_value=self.verification()) as verifier:
            with self.assertRaisesRegex(ValueError, "Duplicate run_id"):
                collect(self.design, [first, second], root=self.workspace)
            self.assertEqual(verifier.call_count, 1)

    def test_legacy_verification_cannot_be_relabeled_current(self):
        path = self.save_fixture()
        for version in ("3", "3.0", "policy-v3-3.0"):
            report = self.verification()
            report["spec_version"] = version
            with self.subTest(version=version), patch("tools.collect_v3_records.verify_run", return_value=report):
                with self.assertRaisesRegex(ValueError, "implementation version"):
                    collect(self.design, [path], root=self.workspace)

    def test_identity_fields_must_match_selected_design_before_verification(self):
        mismatches = {"stage": "order", "scenario_id": "another-scenario", "seed": 9999,
                      "replicate": 1, "horizon": 90}
        for field, value in mismatches.items():
            with self.subTest(field=field):
                path = self.save_fixture(name="bad-" + field,
                                         mutate=lambda r, f=field, v=value: r.update({f: v}))
                with patch("tools.collect_v3_records.verify_run") as verifier:
                    with self.assertRaisesRegex(ValueError, "Frozen run identity differs"):
                        collect(self.design, [path], root=self.workspace)
                    verifier.assert_not_called()

    def test_scenario_content_mismatch_is_rejected_even_when_id_is_same(self):
        def alter(record):
            record["scenario"]["schedule"][0]["q"]["C"] = 1.0
        path = self.save_fixture(mutate=alter)
        with patch("tools.collect_v3_records.verify_run") as verifier:
            with self.assertRaisesRegex(ValueError, "Frozen run identity differs"):
                collect(self.design, [path], root=self.workspace)
            verifier.assert_not_called()

    def test_unknown_run_id_is_not_silently_added_to_design(self):
        path = self.save_fixture(mutate=lambda r: r.update(run_id="not_in_design"))
        with patch("tools.collect_v3_records.verify_run") as verifier:
            with self.assertRaisesRegex(ValueError, "exactly one frozen run"):
                collect(self.design, [path], root=self.workspace)
            verifier.assert_not_called()

    def test_failed_verification_is_retained_but_not_complete(self):
        path = self.save_fixture()
        with patch("tools.collect_v3_records.verify_run", return_value=self.verification(passed=False)):
            result = collect(self.design, [path], root=self.workspace)
        self.assertEqual(result["complete_verified_runs"], 0)
        self.assertEqual(result["real_model_runs"], 0)
        self.assertEqual(len(result["runs"]), 1)
        row = result["runs"][0]
        self.assertEqual(row["status"], "excluded_incomplete_or_invalid")
        self.assertFalse(row["verification"]["passed"])
        self.assertEqual(row["verification"]["errors"], ["synthetic verifier failure for unit test"])

    def test_initialization_failure_keeps_record_without_inventing_source(self):
        for has_controller in (True, False):
            with self.subTest(has_controller=has_controller):
                path = self.folder / ("initialization-failure-" + str(has_controller))
                path.mkdir()
                write_json(path / "record.json", deepcopy(self.records[0]))
                if has_controller:
                    write_json(path / "controller-20260909T100000.000000Z.json",
                               {"mode": "llm", "requests": 2, "elapsed_seconds": 1.5,
                                "fixture_origin": "synthetic_unit_test_only"})
                report = self.verification(passed=False, full_horizon=False)
                report.pop("source_manifest_sha256")
                with patch("tools.collect_v3_records.verify_run", return_value=report) as verifier:
                    result = collect(self.design, [path], root=self.workspace)
                verifier.assert_called_once_with(path.resolve(), self.workspace)
                self.assertEqual(result["complete_verified_runs"], 0)
                self.assertEqual(result["real_model_runs"], 0)
                self.assertEqual(len(result["runs"]), 1)
                row = result["runs"][0]
                self.assertEqual(row["status"], "excluded_incomplete_or_invalid")
                self.assertFalse(row["verification"]["passed"])
                self.assertEqual(row["metrics"], {})
                self.assertIsNone(row["source_manifest"])
                self.assertIsNone(row["source_manifest_sha256"])
                self.assertEqual(row["mode"], "llm" if has_controller else "unknown")
                self.assertEqual(row["requests"], 2 if has_controller else 0)
                self.assertEqual(row["elapsed_seconds"], 1.5 if has_controller else 0)
                self.assertEqual(row["record_origin"], "synthetic_unit_test_fixture_not_a_real_run")

    def test_valid_checkpoint_short_of_horizon_is_not_complete(self):
        path = self.save_fixture(completed_round=18)
        with patch("tools.collect_v3_records.verify_run", return_value=self.verification(full_horizon=False)):
            result = collect(self.design, [path], root=self.workspace)
        self.assertEqual(result["complete_verified_runs"], 0)
        self.assertEqual(result["real_model_runs"], 0)
        self.assertEqual(result["runs"][0]["metrics"]["round"], 18)
        self.assertEqual(result["runs"][0]["status"], "excluded_incomplete_or_invalid")
        self.assertTrue(result["runs"][0]["verification"]["passed"])

    def test_full_horizon_must_be_explicitly_true(self):
        path = self.save_fixture()
        report = self.verification()
        del report["full_horizon"]
        with patch("tools.collect_v3_records.verify_run", return_value=report):
            result = collect(self.design, [path], root=self.workspace)
        self.assertEqual(result["complete_verified_runs"], 0)

    def test_verified_scripted_and_llm_counts_are_distinct(self):
        llm = self.save_fixture(index=0, mode="llm")
        scripted = self.save_fixture(index=1, mode="scripted")
        before = deepcopy(self.design)
        with patch("tools.collect_v3_records.verify_run", side_effect=[self.verification(mode="llm"), self.verification(mode="scripted")]) as verifier:
            result = collect(self.design, [llm, scripted], root=self.workspace)
        self.assertEqual(result["complete_verified_runs"], 2)
        self.assertEqual(result["real_model_runs"], 1)
        self.assertEqual([r["mode"] for r in result["runs"]], ["llm", "scripted"])
        self.assertEqual(sum(r["status"] == "complete" and r["mode"] == "scripted" for r in result["runs"]), 1)
        self.assertEqual(self.design, before)
        self.assertEqual(verifier.call_args_list[0].args, (llm.resolve(), self.workspace))
        self.assertTrue(all(r["record_origin"] == "synthetic_unit_test_fixture_not_a_real_run" for r in result["runs"]))

    def test_source_digest_and_evidence_are_preserved(self):
        path = self.save_fixture()
        report = self.verification()
        with patch("tools.collect_v3_records.verify_run", return_value=report):
            result = collect(self.design, [path], root=self.workspace)
        row = result["runs"][0]
        self.assertEqual(row["source_manifest"], self.source)
        self.assertEqual(row["source_manifest_sha256"], digest(self.source))
        self.assertEqual(row["source_manifest_sha256"], row["verification"]["source_manifest_sha256"])
        self.assertEqual(row["path"], str(path.resolve()))
        self.assertEqual(row["spec_version"], SPEC_VERSION)

    def test_controller_invocations_accumulate_without_latest_alias(self):
        path = self.save_fixture()
        first = {"requests": 5, "elapsed_seconds": 1.25, "fixture_origin": "synthetic_unit_test_only"}
        resumed = {"requests": 7, "elapsed_seconds": 2.75, "fixture_origin": "synthetic_unit_test_only"}
        write_json(path / "controller-20260909T100000.000000Z.json", first)
        write_json(path / "controller-20260909T100100.000000Z.json", resumed)
        # The runtime's latest alias repeats the final invocation and must not count twice.
        write_json(path / "controller_receipt.json", resumed)
        write_json(path / "driver_latest.json", {"requests": 999, "elapsed_seconds": 999})
        with patch("tools.collect_v3_records.verify_run", return_value=self.verification()):
            row = collect(self.design, [path], root=self.workspace)["runs"][0]
        self.assertEqual(row["controller_invocations"], 2)
        self.assertEqual(row["requests"], 12)
        self.assertEqual(row["elapsed_seconds"], 4.0)


if __name__ == "__main__":
    unittest.main()
