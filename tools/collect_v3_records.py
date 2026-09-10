"""Collect explicit official run paths after independent read-only verification."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_mve.io import read_json, write_json, digest
from policy_v3.runtime import select_run
from policy_v3.verify import verify_run
from policy_v3.spec import SPEC_VERSION
from policy_v3.design import record_version


def collect(design, paths, root=ROOT):
    records, seen = [], set()
    for value in paths:
        path = Path(value).resolve()
        frozen = read_json(path / "run_config.json") if (path / "run_config.json").is_file() else {}
        record = frozen.get("record") or read_json(path / "record.json")
        rid = record["run_id"]
        if rid in seen:
            raise ValueError("Duplicate run_id: select one attempt explicitly before collection: " + rid)
        seen.add(rid)
        expected = select_run(design, rid)
        if any(record.get(k) != expected.get(k) for k in
               ("stage", "scenario_id", "scenario", "seed", "replicate", "horizon")):
            raise ValueError("Frozen run identity differs from selected design: " + rid)
        verification = verify_run(path, root)
        metrics = read_json(path / "metrics.json") if (path / "metrics.json").is_file() else {}
        declared = [frozen.get("version"), record.get("spec_version"), record.get("version"),
                    verification.get("spec_version"), verification.get("version"), metrics.get("spec_version")]
        if any(record_version({"spec_version": version}) != SPEC_VERSION for version in declared if version is not None):
            raise ValueError("Run implementation version differs from current frozen study: " + rid)
        controllers = [read_json(p) for p in sorted(path.glob("controller-*.json"))]
        complete = verification["passed"] and verification.get("full_horizon") is True
        source = frozen.get("code_manifest")
        mode = frozen.get("mode", controllers[-1].get("mode", "unknown") if controllers else "unknown")
        records.append({**deepcopy(expected), "spec_version": SPEC_VERSION,
                        "mode": mode, "status": "complete" if complete else "excluded_incomplete_or_invalid",
                        "metrics": metrics, "verification": verification,
                        "source_manifest": source,
                        "source_manifest_sha256": digest(source) if source is not None else None,
                        "requests": sum(r.get("requests", 0) for r in controllers),
                        "elapsed_seconds": sum(r.get("elapsed_seconds", 0) for r in controllers),
                        "controller_invocations": len(controllers), "path": str(path)})
    return {"schema_version": "policy-v3-collected-records-1.0", "runs": records,
            "complete_verified_runs": sum(r["status"] == "complete" for r in records),
            "real_model_runs": sum(r["status"] == "complete" and r["mode"] == "llm" for r in records),
            "selection": "Explicit paths; duplicate attempts rejected; failed or partial runs retained as excluded."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT, help="Exact archived source root; simulation dependencies must match current replay")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; choose a new evidence path")
    result = collect(read_json(args.design), args.run_dir, args.source_root)
    write_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}))
    return 0 if result["complete_verified_runs"] == len(result["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
