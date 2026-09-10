"""Analyze saved V3 records only; emit JSON and Markdown at explicit paths."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_v3.analysis import analyze, render_markdown


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--test-only", action="store_true", help="Accept verified scripted data only as an explicitly labeled analysis test")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.json_output.resolve() == args.markdown_output.resolve():
        parser.error("JSON and Markdown output paths must differ")
    if {args.json_output.resolve(), args.markdown_output.resolve()} & {args.design.resolve(), args.records.resolve()}:
        parser.error("analysis outputs must not overwrite the design or input evidence")
    for output in (args.json_output, args.markdown_output):
        if output.exists() and not args.overwrite:
            parser.error("output already exists; use a new path or explicitly pass --overwrite")
    design = json.loads(args.design.read_text(encoding="utf-8"))
    payload = json.loads(args.records.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload["runs"]
    report = analyze(records, design, allow_offline=args.test_only)
    for output in (args.json_output, args.markdown_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(args.json_output.resolve()), "markdown": str(args.markdown_output.resolve()), "formal_inference": report["formal_inference"], "accepted": report["accepted_formal_records"], "excluded": len(report["excluded_records"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
