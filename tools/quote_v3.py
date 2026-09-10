"""Produce a reviewable stage quote; never authorizes or calls a model."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_v3.execution import load_manifest, quote, source_hash, file_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--stage', required=True)
    p.add_argument('--receipts', nargs='*', default=[])
    p.add_argument('--output', required=True)
    args = p.parse_args()
    _, runs = load_manifest(args.manifest, args.stage)
    receipts = [json.loads(Path(path).read_text(encoding='utf-8')) for path in args.receipts]
    result = quote(runs, receipts)
    result.update(stage=args.stage, manifest_sha256=file_hash(args.manifest), source_sha256=source_hash(ROOT))
    with Path(args.output).open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
