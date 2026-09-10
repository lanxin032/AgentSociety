"""Summarize an existing MVE manifest without modifying its evidence files."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_mve.analyze import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New JSON path; existing files are never overwritten")
    args = parser.parse_args()
    payload = args.manifest.read_bytes()
    report = summarize(json.loads(payload.decode("utf-8-sig")))
    report["input_manifest"] = str(args.manifest.resolve())
    report["input_sha256"] = hashlib.sha256(payload).hexdigest()
    serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
    print(json.dumps({"output": str(args.output.resolve()), "mode": report["mode"],
                      "complete_blocks": report["complete_block_count"],
                      "incomplete_blocks": len(report["incomplete_blocks"]),
                      "invalid_records": len(report["invalid_records"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
