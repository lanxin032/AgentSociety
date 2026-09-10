"""Validate saved V3 scenarios with deterministic scripts; zero model/API calls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_mve.io import write_json
from policy_v3.core import PolicyWorld
from policy_v3.scripted import scripted_action
from policy_v3.verify import verify_state
from policy_v3.runtime import code_manifest
from policy_v3.spec import SPEC_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--coverage", action="store_true", help="One record for every stage/scenario, explicitly not a full repeated matrix")
    parser.add_argument("--stage")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Output exists; preserve old validation evidence")
    design = json.loads(args.design.read_text(encoding="utf-8"))
    selected = [r for r in design["runs"] if not args.stage or r["stage"] == args.stage]
    if args.coverage:
        seen, records = set(), []
        for row in selected:
            key = (row["stage"], row["scenario_id"])
            if key not in seen:
                records.append(row)
                seen.add(key)
        selected = records
    if not selected:
        raise SystemExit("No scenarios selected")
    args.output.mkdir(parents=True)
    outputs = []
    started = time.monotonic()
    frozen_source = code_manifest(ROOT)
    for index, row in enumerate(selected, 1):
        world = PolicyWorld(seed=row["seed"], horizon=row["horizon"], scenario=row["scenario"])
        failure = None
        try:
            for _ in range(row["horizon"]):
                for actor in (1, 2, 3, 4):
                    observation = world.observe(actor)
                    receipt = world.submit(actor, scripted_action(observation))
                    if receipt.get("status") != "queued":
                        raise RuntimeError("Scripted decision was not accepted for settlement")
                world.advance()
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
        state, metrics = world.export_state(), world.metrics()
        verification = verify_state(state, metrics) if failure is None else {"passed": False, "errors": [failure], "spec_version": SPEC_VERSION}
        folder = args.output / row["run_id"]
        write_json(folder / "world.json", state)
        write_json(folder / "metrics.json", metrics)
        write_json(folder / "verification.json", verification)
        outputs.append({**deepcopy(row), "spec_version": SPEC_VERSION, "mode": "offline_scripted",
                        "status": "complete" if verification["passed"] else "technical_failure",
                        "metrics": metrics, "verification": verification, "path": str(folder.resolve())})
        print(json.dumps({"checked": index, "total": len(selected), "run_id": row["run_id"],
                          "passed": verification["passed"], "errors": verification["errors"][:3]}), flush=True)
        if not verification["passed"]:
            break
    complete = len(outputs) == len(selected) and all(r["verification"]["passed"] for r in outputs)
    source_unchanged = code_manifest(ROOT) == frozen_source
    result = {"mode": "offline_scripted", "real_model_runs": 0, "api_requests": 0,
              "coverage_only": args.coverage, "source_manifest": frozen_source,
              "source_unchanged": source_unchanged, "passed": complete and source_unchanged,
              "selected_runs": len(selected), "runs": outputs,
              "elapsed_seconds": round(time.monotonic() - started, 3)}
    write_json(args.output / "validation.json", result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
