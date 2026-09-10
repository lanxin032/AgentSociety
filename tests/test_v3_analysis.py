from copy import deepcopy
from policy_v3.spec import SPEC_VERSION
import math
import unittest

from policy_v3.design import build_design, endpoint_id
from policy_v3.analysis import analyze, summarize_differences, paired_summary, holm_adjust, student_t_quantile, student_t_two_sided, chi_square_df3_quantile, render_markdown


def completed(record, value, mode="llm"):
    result = deepcopy(record)
    result.update(mode=mode, status="complete", spec_version=SPEC_VERSION, verification={"passed": True}, record_origin="synthetic_unit_test_fixture_not_a_real_run")
    result["metrics"] = {"round": result["horizon"], "horizon": result["horizon"], "cumulative_issue_burden": value * 12 * result["horizon"], "labor_spent": 100 * value, "capital_spent": 10 * value}
    return result


class StatisticalTests(unittest.TestCase):
    def test_distribution_reference_values(self):
        # Standard t(.975,df) and chi-square(.10,3) numerical reference values.
        for df, expected in ((1, 12.7062047361747), (2, 4.30265272969614), (7, 2.36462425159278), (9, 2.2621571627982), (11, 2.20098516008295)):
            self.assertAlmostEqual(student_t_quantile(.975, df), expected, places=9)
            self.assertAlmostEqual(student_t_two_sided(expected, df), .05, places=10)
        self.assertAlmostEqual(chi_square_df3_quantile(.1), .584374374155183, places=12)

    def test_manual_paired_mean_sd_mcse_and_direction(self):
        report = summarize_differences([.1, .2, .3])
        self.assertAlmostEqual(report["raw_difference"], .2)
        self.assertAlmostEqual(report["benefit_difference"], -.2)
        self.assertAlmostEqual(report["sample_sd"], .1)
        self.assertAlmostEqual(report["mcse"], .1 / math.sqrt(3))
        self.assertAlmostEqual(report["half_width"], 4.30265272969614 * .1 / math.sqrt(3))

    def test_zero_sd_and_singleton_do_not_divide_by_zero(self):
        report = summarize_differences([.2] * 8)
        self.assertEqual(report["mcse"], 0)
        self.assertEqual(report["ci95_raw"], [.2, .2])
        self.assertIsNone(report["pvalue_two_sided"])
        self.assertIsNone(summarize_differences([.1])["mcse"])
        self.assertIsNone(summarize_differences([])["raw_difference"])
        self.assertIsNone(summarize_differences([.2 - .1, .3 - .2, .4 - .3])["pvalue_two_sided"])

    def test_missing_bounds_hand_calculation(self):
        outcomes = {("t", 1): .3, ("c", 1): .5, ("c", 2): .4}
        report = paired_summary([("t", 1), ("c", -1)], [1, 2], outcomes)
        self.assertEqual(report["n_complete_blocks"], 1)
        self.assertAlmostEqual(report["raw_difference"], -.2)
        self.assertAlmostEqual(report["full_planned_mean_raw_bounds"][0], -.3)
        self.assertAlmostEqual(report["full_planned_mean_raw_bounds"][1], .2)
        self.assertEqual(report["missing_blocks"], [{"seed": 2, "missing_cells": ["t"]}])

    def test_holm_prespecified_family_including_missing(self):
        rows = [{"family": "a", "pvalue_two_sided": p, "pvalue_holm": None} for p in (.01, .04, .03)]
        holm_adjust(rows)
        self.assertEqual([round(r["pvalue_holm"], 3) for r in rows], [.03, .06, .06])
        rows[-1]["pvalue_two_sided"] = None
        rows[-1]["pvalue_holm"] = None
        holm_adjust(rows)
        self.assertAlmostEqual(rows[0]["pvalue_holm"], .03)

    def test_formal_data_rejects_offline_and_mixed_versions(self):
        design = build_design(8)
        original = next(r for r in design["runs"] if r["stage"] == "static")
        record = completed(original, .3, mode="scripted")
        report = analyze([record], design)
        self.assertFalse(report["formal_inference"])
        self.assertEqual(report["accepted_formal_records"], 0)
        report = analyze([record], design, allow_offline=True)
        self.assertEqual(report["accepted_formal_records"], 1)
        self.assertFalse(report["formal_inference"])
        two = [completed(r, .3) for r in design["runs"] if r["stage"] == "static"][:2]
        two[0]["spec_version"] = "old"
        with self.assertRaises(ValueError):
            analyze(two, design)
        for version in ("3", "3.0", "policy-v3-3.0"):
            legacy = completed(original, .3)
            legacy["spec_version"] = version
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "version"):
                analyze([legacy], design)

    def test_static_factorial_and_no_order_seed_mixing(self):
        design = build_design(8)
        records = []
        for r in design["runs"]:
            if r["stage"] == "static":
                a, b = r["scenario"]["q"]["A"], r["scenario"]["q"]["B"]
                records.append(completed(r, .1 + .2 * a + .05 * b + .1 * a * b))
        report = analyze(records, design)
        contrasts = {r["id"]: r for r in report["contrasts"]}
        self.assertAlmostEqual(contrasts["RQ1_factorial_A"]["raw_difference"], .25)
        self.assertAlmostEqual(contrasts["RQ1_factorial_AB"]["raw_difference"], .1)
        self.assertAlmostEqual(contrasts["RQ1_conditional_AB_given_C0"]["raw_difference"], .1)
        self.assertAlmostEqual(contrasts["RQ1_conditional_AB_given_C1"]["raw_difference"], .1)
        self.assertEqual(sum(c["family"] == "RQ1_primary" for c in contrasts.values()), 13)
        self.assertEqual(sum(c["family"] == "RQ1_exploratory_factorial" for c in contrasts.values()), 7)
        self.assertEqual(contrasts["RQ1_conditional_AB_given_C1"]["holm_family_size"], 13)
        self.assertAlmostEqual(contrasts["RQ1_factorial_AB"]["burden_difference"], .1 * 720)
        self.assertEqual(contrasts["RQ1_factorial_AB"]["units"]["burden_difference"], "unresolved_Issue_rounds")
        self.assertEqual(contrasts["RQ1_111_minus_000"]["n_complete_blocks"], 8)
        self.assertEqual(contrasts["RQ2b_order_equal_ABC"]["n_complete_blocks"], 0)
        self.assertEqual(len(report["dose_curves"]), 27)
        self.assertEqual(len(report["nondominated"]["common_seeds"]), 8)
        self.assertTrue(any(p["nondominated"] for p in report["nondominated"]["points"]))
        self.assertIn("Holm", render_markdown(report))

    def test_order_common_window_is_separate_and_scaled_to_30_rounds(self):
        design = build_design(8)
        records = []
        for row in design["runs"]:
            if row["stage"] == "order":
                is_reference = row["scenario_id"].endswith("simultaneous")
                record = completed(row, .5 if is_reference else .4)
                record["metrics"]["common_window_burden"] = 90 if is_reference else 54
                record["metrics"]["common_window_horizon"] = 30
                records.append(record)
        report = analyze(records, design)
        contrasts = {r["id"]: r for r in report["contrasts"]}
        full = contrasts["RQ2b_order_equal_ABC"]
        common = contrasts["RQ2b_order_equal_ABC_common_window"]
        self.assertAlmostEqual(full["burden_difference"], -108)
        self.assertAlmostEqual(common["burden_difference"], -36)
        self.assertAlmostEqual(common["normalized_difference"], -.1)
        self.assertEqual(common["units"]["window_horizon"], 30)
        self.assertEqual(full["units"]["window_horizon"], 90)
        self.assertEqual(common["holm_family_size"], 12)
        self.assertEqual(report["common_window_unavailable"], [])
        del records[0]["metrics"]["common_window_burden"]
        self.assertEqual(len(analyze(records, design)["common_window_unavailable"]), 1)

    def test_model_repeats_are_paired_not_doubled(self):
        design = build_design(8)
        records = [completed(r, .3 if r["stage"] == "static" else .32) for r in design["runs"] if r["scenario_id"] == endpoint_id("000") and r["stage"] in ("static", "model_replicate")]
        report = analyze(records, design)
        row = next(r for r in report["model_replicates"] if r["scenario_id"] == endpoint_id("000"))
        self.assertEqual(row["n_exogenous_blocks"], 8)
        self.assertEqual(row["independent_sample_size_is_not"], 16)
        self.assertAlmostEqual(row["within_exogenous_model_variance_estimate"], .02 ** 2 / 2)

    def test_sensitivity_baseline_pairs_use_only_first_six_static_seeds(self):
        design = build_design(8)
        records = []
        for r in design["runs"]:
            if r["stage"] == "static":
                records.append(completed(r, .3))
            elif r["stage"] == "sensitivity":
                records.append(completed(r, .4))
        report = analyze(records, design)
        row = next(r for r in report["contrasts"] if r["id"] == "sensitivity_environment_tight_resources_111")
        self.assertEqual(row["n_complete_blocks"], 6)
        self.assertEqual([r["seed"] for r in row["complete_blocks"]], list(range(3001, 3007)))
        self.assertAlmostEqual(row["raw_difference"], .1)

    def test_missing_counterpart_not_pooled_and_duplicate_id_rejected(self):
        design = build_design(8)
        target = next(r for r in design["runs"] if r["stage"] == "static" and r["seed"] == 3001 and r["scenario_id"] == endpoint_id("111"))
        baseline = next(r for r in design["runs"] if r["stage"] == "static" and r["seed"] == 3002 and r["scenario_id"] == endpoint_id("000"))
        records = [completed(target, .2), completed(baseline, .3)]
        report = analyze(records, design)
        row = next(r for r in report["contrasts"] if r["id"] == "RQ1_111_minus_000")
        self.assertEqual(row["n_complete_blocks"], 0)
        self.assertIsNone(row["raw_difference"])
        with self.assertRaises(ValueError):
            analyze(records + [records[0]], design)


if __name__ == "__main__":
    unittest.main()
