"""Current finite experiment: python -m policy_sim prepare/run/resume/audit."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='Freeze an offline baseline proposal on the existing ledger')
    prepare.add_argument('--output', type=Path, required=True)
    for name in ('run', 'resume'):
        sub = commands.add_parser(name)
        sub.add_argument('--manifest', type=Path, required=True)
        sub.add_argument('--authorization', type=Path, required=True)
        sub.add_argument('--output', type=Path, required=True)
    audit = commands.add_parser('audit')
    audit.add_argument('run_dir', type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    if args.command == 'prepare':
        from .protocol import prepare as freeze
        result = freeze(root, args.output)
    elif args.command == 'audit':
        from .verify import verify_run
        result = verify_run(args.run_dir, root)
    else:
        from .execution import execute_stage
        return 0 if execute_stage(root, args.manifest, args.authorization, args.output,
                                   resume=args.command == 'resume') else 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.command != 'audit' or result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
