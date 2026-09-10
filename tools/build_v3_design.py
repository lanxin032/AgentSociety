"""Generate versioned V3 manifests only; never launch an experiment."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_v3.design import build_design, protocol_specification, freeze_sample_size, freeze_design


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", choices=("all", "8", "10", "12"), default="all")
    parser.add_argument("--output-dir", type=Path, help="Directory for candidate designs")
    parser.add_argument("--pilot-records", type=Path, help="Decision report only: does not unlock or freeze the candidate manifests")
    parser.add_argument("--freeze-from-pilot", type=Path, help="Explicitly create only the chosen-N frozen manifest from 32 verified source-bound pilot records")
    parser.add_argument("--frozen-output", type=Path, help="New file path for --freeze-from-pilot; always refuses overwrite")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.freeze_from_pilot:
        if not args.frozen_output or args.pilot_records or args.output_dir:
            parser.error("--freeze-from-pilot requires only --frozen-output; do not combine with candidate/decision-report output")
        if args.frozen_output.exists():
            parser.error("frozen output must be a new path; existing manifests are immutable")
        payload = json.loads(args.freeze_from_pilot.read_text(encoding="utf-8"))
        frozen = freeze_design(payload if isinstance(payload, list) else payload["runs"])
        args.frozen_output.parent.mkdir(parents=True, exist_ok=True)
        args.frozen_output.write_text(json.dumps(frozen, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"frozen_output": str(args.frozen_output.resolve()), "n": frozen["n"], "status": frozen["status"], "executed_runs": 0, "execution_authorized": False}, ensure_ascii=False))
        return 0
    if not args.output_dir or args.frozen_output:
        parser.error("candidate generation requires --output-dir; --frozen-output requires --freeze-from-pilot")
    choices = (8, 10, 12) if args.n == "all" else (int(args.n),)
    outputs = {f"design-{n}.json": build_design(n) for n in choices}
    protocol = protocol_specification()
    if args.pilot_records:
        payload = json.loads(args.pilot_records.read_text(encoding="utf-8"))
        protocol["pilot_precision_decision"] = freeze_sample_size(payload if isinstance(payload, list) else payload["runs"])
    outputs["design_protocol.json"] = protocol
    for name in outputs:
        if (args.output_dir / name).exists() and not args.overwrite:
            parser.error("output exists; preserve previous design or explicitly pass --overwrite: " + name)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"generated": [str((args.output_dir / name).resolve()) for name in outputs], "counts": {str(n): outputs[f'design-{n}.json']["counts"]["total"] for n in choices}, "executed_runs": 0, "formal_status": "awaiting_pilot_freeze"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
