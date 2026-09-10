"""Run the complete offline unit suite and optional installed SciPy cross-check."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_v3.runtime import code_manifest
from policy_mve.io import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    if target.exists():
        parser.error("Output exists; preserve prior checks")
    target.mkdir(parents=True)
    os.chdir(ROOT)
    before = code_manifest(ROOT)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / "tests")))
    numerical = {"status": "not_available"}
    try:
        from scipy.stats import t, chi2
        from policy_v3.analysis import student_t_quantile, chi_square_df3_quantile
        errors = [abs(student_t_quantile(.975, df)-t.ppf(.975, df)) for df in (3, 7, 9, 11)]
        errors.append(abs(chi_square_df3_quantile(.1)-chi2.ppf(.1, 3)))
        numerical = {"status": "passed" if max(errors) < 1e-8 else "failed", "maximum_absolute_quantile_error": max(errors), "reference": "installed scipy.stats"}
    except ImportError:
        pass
    unchanged = before == code_manifest(ROOT)
    report = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "passed": result.wasSuccessful() and unchanged and numerical["status"] != "failed",
              "source_unchanged": unchanged, "source_manifest": before, "numerical_distribution_check": numerical,
              "api_requests": 0, "mode": "offline_unit_tests"}
    (target / "unit-tests.log").write_text(stream.getvalue(), encoding="utf-8")
    report["unit_log_sha256"] = hashlib.sha256((target / "unit-tests.log").read_bytes()).hexdigest()
    write_json(target / "unit-tests.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "source_manifest"}))
    if not result.wasSuccessful():
        print("\n".join(stream.getvalue().splitlines()[-80:]))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
