"""Plot input semantics without requiring matplotlib installation."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.plot_v3 import OFFLINE_TITLE, analysis_label, contrast_data, dose_data, render


class PlotSemanticsTests(unittest.TestCase):
    def test_offline_title_overrides_inconsistent_formal_flag(self):
        self.assertEqual(analysis_label({"analysis_mode": "offline_test_only", "formal_inference": True}), OFFLINE_TITLE)
        self.assertEqual(analysis_label({"test_only": True, "formal_inference": True}), OFFLINE_TITLE)
        self.assertIn("NO FORMAL INFERENCE", analysis_label({"formal_inference": False}))
        self.assertIn("FORMAL ANALYSIS", analysis_label({"formal_inference": True}))

    def test_raw_legacy_field_is_never_presented_as_original_burden(self):
        rows = [{"id": "x", "raw_difference": 0.2, "n_complete_blocks": 4}]
        self.assertIsNone(contrast_data(rows, "burden")[0]["value"])
        row = {"id": "x", "burden_difference": -72, "normalized_difference": -0.1,
               "ci95_burden_difference": [-144, 0], "normalized_ci95": [-0.2, 0], "n_complete_blocks": 4}
        self.assertEqual(contrast_data([row], "burden")[0]["ci"], [-144, 0])
        self.assertEqual(contrast_data([row], "normalized")[0]["value"], -0.1)

    def test_missing_nonfinite_values_and_bad_intervals_are_not_invented(self):
        rows = [{"burden_difference": None, "n_complete_blocks": 3},
                {"burden_difference": float("nan"), "n_complete_blocks": 3},
                {"burden_difference": 5, "n_complete_blocks": 0},
                {"burden_difference": 5, "ci95_burden_difference": [0, 10], "n_complete_blocks": 1},
                {"burden_difference": 5, "ci95_burden_difference": [8, 3], "n_complete_blocks": 3}]
        values = contrast_data(rows, "burden")
        self.assertEqual([r["value"] for r in values], [None, None, None, 5, 5])
        self.assertTrue(all(r["ci"] is None for r in values))

    def test_dose_missing_point_remains_gap_and_counts_are_respected(self):
        curves = [{"axis": "A", "fixed_other_q": {"B": 0, "C": 0}, "points": [
            {"q": 1, "mean_normalized_burden": 0.5, "n_available_blocks": 3},
            {"q": 0.5, "mean_normalized_burden": None, "n_available_blocks": 0},
            {"q": 0, "mean_normalized_burden": 0, "n_available_blocks": 0}]}]
        points = dose_data(curves, "A")[0]["points"]
        self.assertEqual([p["q"] for p in points], [0, 0.5, 1])
        self.assertEqual([p["mean"] for p in points], [None, None, 0.5])
        self.assertEqual(dose_data(curves, "B"), [])

    def test_wrong_schema_fails_before_import_or_output(self):
        with self.assertRaises(ValueError):
            render({}, "unused")


if __name__ == "__main__":
    unittest.main()
