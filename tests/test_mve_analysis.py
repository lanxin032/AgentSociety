from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_mve.analyze import POLICIES, summarize


def records(seeds=(1, 2, 3)):
    result = []
    for seed in seeds:
        for policy in POLICIES:
            a, b, c = map(int, policy)
            # Benefit interactions AB=4+7*C, AC=5+7*B, BC=6+7*A.
            benefit = a + 2*b + 3*c + 4*a*b + 5*a*c + 6*b*c + 7*a*b*c
            result.append({"seed": seed, "policy": policy, "status": "offline_scripted_pass", "horizon": 30,
                           "metrics": {"seed": seed, "policy": policy, "round": 30, "horizon": 30,
                                       "cumulative_issue_burden": 100 + seed - benefit,
                                       "initial_resolution_rate": .5 + .01 * benefit,
                                       "labor_spent": 20 + 2*a*b,
                                       "capital_spent": 10 + c}})
    return result


class AnalysisTests(unittest.TestCase):
    def test_known_six_interactions_and_primary_sign(self):
        report = summarize({"mode": "offline_scripted", "runs": records()})
        interactions = report["results"]["cumulative_issue_burden"]["conditional_interactions"]
        expected = {"AB|C0": 4, "AB|C1": 11, "AC|B0": 5, "AC|B1": 12, "BC|A0": 6, "BC|A1": 13}
        for name, value in expected.items():
            self.assertEqual(interactions[name]["benefit_direction"]["mean"], value)
            self.assertEqual(interactions[name]["original_units"]["mean"], -value)
            self.assertEqual(len(interactions[name]["original_units"]["values"]), 3)
        self.assertEqual(report["complete_seeds"], [1, 2, 3])
        self.assertFalse(report["is_llm_experiment"])

    def test_original_values_ranges_and_cost_direction(self):
        report = summarize(records())
        level = report["results"]["cumulative_issue_burden"]["policy_levels"]["000"]["original_units"]
        self.assertEqual(level["mean"], 102)
        self.assertEqual(level["range"], {"min": 101, "max": 103})
        labor = report["results"]["labor_spent"]["conditional_interactions"]["AB|C0"]
        self.assertEqual(labor["original_units"]["mean"], 2)
        self.assertEqual(labor["benefit_direction"]["mean"], -2)
        diff = report["results"]["cumulative_issue_burden"]["paired_differences_from_000"]["100"]
        self.assertEqual(diff["original_units"]["mean"], -1)
        self.assertEqual(diff["benefit_direction"]["mean"], 1)

    def test_missing_and_failed_blocks_are_explicit_and_not_partially_pooled(self):
        rows = records()
        rows = [r for r in rows if (r["seed"], r["policy"]) != (2, "111")]
        next(r for r in rows if (r["seed"], r["policy"]) == (3, "000"))["status"] = "offline_scripted_fail"
        report = summarize({"mode": "offline_scripted", "expected_seeds": [1, 2, 3, 4], "runs": rows})
        self.assertEqual(report["complete_seeds"], [1])
        self.assertEqual(len(report["record_audit"]), 23)
        excluded = {b["seed"]: b for b in report["incomplete_blocks"]}
        self.assertEqual(excluded[2]["missing_policies"], ["111"])
        self.assertEqual(excluded[3]["failed_records"][0]["policy"], "000")
        self.assertEqual(excluded[4]["missing_policies"], list(POLICIES))

    def test_duplicate_invalid_metric_and_unfinished_horizon(self):
        rows = records()
        rows.append(deepcopy(rows[0]))
        rows[8]["metrics"]["labor_spent"] = None
        rows[16]["metrics"]["round"] = 2
        report = summarize(rows)
        self.assertEqual(report["complete_block_count"], 0)
        self.assertEqual(len(report["incomplete_blocks"]), 3)
        self.assertEqual(report["incomplete_blocks"][0]["duplicate_policies"]["000"], [0, 24])
        self.assertIsNone(report["results"]["labor_spent"]["policy_levels"]["000"]["original_units"]["mean"])

    def test_mixed_modes_and_input_are_not_silently_changed(self):
        rows = records((1,))
        rows[0]["mode"] = "llm"
        data = {"mode": "offline_scripted", "runs": rows}
        original = deepcopy(data)
        report = summarize(data)
        self.assertEqual(data, original)
        self.assertEqual(report["mode"], "mixed")
        self.assertEqual(report["complete_block_count"], 0)
        self.assertTrue(report["incomplete_blocks"][0]["mixed_execution_modes"])


if __name__ == "__main__":
    unittest.main()
