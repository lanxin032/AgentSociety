"""Read-only V3 event/replay/checkpoint verification; no API calls."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_v3.verify import verify_run, verify_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--run-dir')
    source.add_argument('--state')
    parser.add_argument('--output', help='New JSON result path; existing files are never overwritten')
    parser.add_argument('--source-root', help='Exact archived source root for historical runs; replay dependencies must match')
    args = parser.parse_args()
    result = verify_run(args.run_dir, root=args.source_root) if args.run_dir else verify_state(json.loads(Path(args.state).read_text(encoding='utf-8')))
    if args.state:
        result['mode'] = 'offline'
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        with Path(args.output).open('x', encoding='utf-8') as stream:
            stream.write(text + '\n')
    print(text)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
