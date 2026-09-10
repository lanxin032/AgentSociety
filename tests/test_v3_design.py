from copy import deepcopy
import math
import unittest

from policy_v3.design import build_design, integrated_dose, endpoint_id, freeze_sample_size, freeze_design, validate_scenario
from policy_v3.design import record_version
from policy_v3.spec import SPEC_VERSION


def pilot_fixture(scale=0.01):
    rows = [deepcopy(r) for r in build_design(8)["runs"] if r["stage"] == "pilot"]
    for row in rows:
        change = [-3, -1, 1, 3][row["seed"] - 2001] * scale if row["scenario_id"] == endpoint_id("111") else 0
        row.update(mode="llm", status="complete", spec_version=SPEC_VERSION, verification={"passed": True},
                   record_origin="synthetic_unit_test_fixture_not_a_real_run", source_manifest_sha256="f" * 64)
        row["metrics"] = {"round": 60, "horizon": 60, "cumulative_issue_burden": (0.5 + change) * 720}
    return rows


class DesignTests(unittest.TestCase):
    def test_current_version_and_legacy_aliases_stay_separate(self):
        self.assertEqual(build_design(8)["metadata"]["implementation_version"], SPEC_VERSION)
        self.assertEqual(record_version({"spec_version": "3.1"}), SPEC_VERSION)
        for version in ("3", "3.0", "policy-v3-3.0"):
            self.assertEqual(record_version({"spec_version": version}), "policy-v3-3.0")
            rows = pilot_fixture()
            for row in rows:
                row["spec_version"] = version
            with self.assertRaisesRegex(ValueError, "implementation version"):
                freeze_sample_size(rows)

    def test_counts_and_850_cap(self):
        for n, total in ((8, 638), (10, 740), (12, 842)):
            design = build_design(n)
            self.assertEqual(design["counts"], {"diagnostic": 6, "pilot": 32, "static": 33 * n, "order": 14 * n, "model_replicate": 4 * n, "sensitivity": 192, "total": total})
            self.assertEqual(len({r["run_id"] for r in design["runs"]}), total)
            self.assertLessEqual(total + design["limits"]["technical_redo_reserve"], 850)
        self.assertEqual(build_design(12)["limits"]["planned_plus_reserve"], 850)

    def test_only_accepted_n(self):
        for n in (3, 9, 48, True, "12"):
            with self.assertRaises(ValueError):
                build_design(n)

    def test_grid_full_three_levels_plus_six_axis_points(self):
        design = build_design(8)
        scenarios = [s for s in design["scenarios"] if s["family"] == "static" and s["environment"] == "baseline"]
        self.assertEqual(len(scenarios), 33)
        extra = [s for s in scenarios if any(v in (0.25, 0.75) for v in s["q"].values())]
        self.assertEqual(len(extra), 6)
        self.assertTrue(all(sum(v != 0 for v in s["q"].values()) == 1 for s in extra))

    def test_phase_integrals_and_common_final_period(self):
        order = [s for s in build_design(8)["scenarios"] if s["family"].startswith("order_")]
        self.assertEqual(len(order), 14)
        for scenario in order:
            self.assertTrue(validate_scenario(scenario))
            dose = integrated_dose(scenario)
            self.assertEqual(scenario["schedule"][-1], {"start": 60, "end": 90, "q": {"A": 1.0, "B": 1.0, "C": 1.0}})
            if scenario["family"] == "order_equal":
                self.assertEqual(dose, {"A": 50.0, "B": 50.0, "C": 50.0})
            else:
                self.assertEqual(sum(dose.values()), 210)
                self.assertEqual(sorted(dose.values()), [70, 70, 70] if scenario["id"].endswith("simultaneous") else [50, 70, 90])

    def test_seed_pools_reuse_only_explicit_pairs(self):
        design = build_design(10)
        pools = design["seed_pools"]
        for left in ("diagnostic", "pilot", "static", "order"):
            for right in ("diagnostic", "pilot", "static", "order"):
                if left != right:
                    self.assertFalse(set(pools[left]) & set(pools[right]))
        self.assertEqual(pools["sensitivity_reuses_static"], pools["static"][:6])
        self.assertEqual(pools["model_replicate_reuses_static"], pools["static"])
        for r in design["runs"]:
            if r["stage"] == "model_replicate":
                self.assertEqual(r["replicate"], 1)
            elif r["stage"] not in ("diagnostic", "pilot"):
                self.assertEqual(r["status"], "awaiting_pilot_freeze")

    def test_run_order_deterministic_and_not_lexicographic(self):
        a, b = build_design(8), build_design(8)
        self.assertEqual(a, b)
        group = [r["scenario_id"] for r in a["runs"] if r["stage"] == "static" and r["seed"] == 3001]
        self.assertNotEqual(group, sorted(group))
        self.assertEqual([r["run_order"] for r in a["runs"]], list(range(1, 639)))

    def test_precision_freeze_candidates_and_cap(self):
        for scale, n, status in ((0.005, 8, "precision_target_planned"), (0.021, 10, "precision_target_planned"), (0.025, 12, "precision_target_planned"), (0.04, 12, "precision_limited_at_cap")):
            result = freeze_sample_size(pilot_fixture(scale))
            self.assertEqual(result["n"], n)
            self.assertEqual(result["status"], status)
            self.assertFalse(result["execution_authorized"])
            expected_sd = math.sqrt(20 / 3) * scale
            self.assertAlmostEqual(result["contrasts"][-1]["sample_sd"], expected_sd)

    def test_precision_zero_sd_is_not_probability_claim(self):
        result = freeze_sample_size(pilot_fixture(0))
        self.assertEqual(result["n"], 8)
        self.assertEqual(result["planned_half_width"], 0)
        self.assertTrue(any("zero" in note for note in result["limitations"]))

    def test_precision_rejects_missing_failed_scripted_and_mixed(self):
        with self.assertRaises(ValueError):
            freeze_sample_size(pilot_fixture()[:-1])
        for field, value in (("status", "technical_failure"), ("mode", "scripted"), ("spec_version", "old")):
            rows = pilot_fixture()
            rows[0][field] = value
            with self.assertRaises(ValueError):
                freeze_sample_size(rows)
        rows = pilot_fixture()
        rows[0]["scenario"]["q"]["A"] = 0.123
        with self.assertRaises(ValueError):
            freeze_sample_size(rows)

    def test_freeze_chosen_manifest_source_bound_without_stage_authorization(self):
        rows = pilot_fixture(.021)
        frozen = freeze_design(rows)
        self.assertEqual(frozen["n"], 10)
        self.assertEqual(frozen["status"], "frozen_pending_stage_authorization")
        self.assertFalse(frozen["execution_authorized"])
        self.assertEqual(frozen["pilot_binding"]["source_manifest_sha256"], "f" * 64)
        self.assertEqual(frozen["counts"]["total"], 740)
        self.assertTrue(all(r["status"] == "frozen_pending_stage_authorization" for r in frozen["runs"] if r["stage"] not in ("pilot", "diagnostic")))
        self.assertEqual(frozen["pilot_binding"]["canonical_record_sha256"], freeze_design(list(reversed(rows)))["pilot_binding"]["canonical_record_sha256"])
        self.assertTrue(all(r["record_origin"] == "synthetic_unit_test_fixture_not_a_real_run" for r in frozen["runs"] if r["stage"] == "pilot"))

    def test_freeze_rejects_missing_or_mixed_source_manifest(self):
        rows = pilot_fixture()
        del rows[0]["source_manifest_sha256"]
        with self.assertRaises(ValueError):
            freeze_design(rows)
        rows = pilot_fixture()
        rows[0]["source_manifest_sha256"] = "a" * 64
        with self.assertRaises(ValueError):
            freeze_design(rows)
        rows = pilot_fixture()
        rows[0]["metrics"]["round"] = 59
        with self.assertRaises(ValueError):
            freeze_sample_size(rows)


if __name__ == "__main__":
    unittest.main()
