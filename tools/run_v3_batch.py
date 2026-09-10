"""Stage-bounded V3 controller. Defaults to an offline command review."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_v3.execution import (AttemptRegistry, ExecutionError, check_deadline, chunk_commands,
                                 controller_lock, file_hash, load_manifest, quote, source_hash, validate_authorization)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--stage', required=True)
    p.add_argument('--mode', choices=('scripted', 'llm'), default='scripted')
    p.add_argument('--authorization')
    p.add_argument('--output', required=True)
    p.add_argument('--chunk-steps', type=int, default=5)
    p.add_argument('--stop-at')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--resume-batch', action='store_true')
    args = p.parse_args()
    if args.execute and args.dry_run:
        raise ExecutionError('Choose execute or dry-run')
    _, runs = load_manifest(args.manifest, args.stage)
    auth = None
    if args.mode == 'llm' and args.execute:
        if any(r.get('status') == 'awaiting_pilot_freeze' for r in runs):
            raise ExecutionError('Formal design remains awaiting independent pilot freeze')
        if not args.authorization:
            raise ExecutionError('LLM execution requires a distinct explicit stage authorization file')
        auth = validate_authorization(json.loads(Path(args.authorization).read_text(encoding='utf-8')),
                                      args.manifest, args.stage, ROOT)
        if len(runs) > auth['max_attempts']:
            raise ExecutionError('Stage exceeds authorized attempt cap')
        check_deadline(args.stop_at)
    output = Path(args.output).resolve()
    binding = {'stage': args.stage, 'mode': args.mode, 'manifest_sha256': file_hash(args.manifest),
               'source_sha256': source_hash(ROOT), 'chunk_steps': args.chunk_steps,
               'authorization_sha256': file_hash(args.authorization) if args.authorization else None}
    if output.exists() and not args.resume_batch:
        raise ExecutionError('Output must be a new directory; existing evidence cannot be overwritten')
    if args.resume_batch:
        if not args.execute:
            raise ExecutionError('resume-batch requires execute')
        prior_review = json.loads((output / 'stage_review.json').read_text(encoding='utf-8'))
        if any(prior_review.get(k) != v for k, v in binding.items()) or prior_review.get('execute_requested') is not True:
            raise ExecutionError('Resume requires same source, manifest, mode, stage and authorization')
    plans = [{'run_id': run['run_id'], 'commands': chunk_commands(ROOT, Path(args.manifest).resolve(), run,
              args.mode, output / run['run_id'], args.chunk_steps, args.authorization, args.stop_at)} for run in runs]
    review = {**binding, 'execute_requested': args.execute,
              'quote': quote(runs), 'runs': plans, 'production_api_ledger_owner': 'tools/run_v3.py',
              'automatic_technical_retries': False}
    if not args.resume_batch:
        output.mkdir(parents=True)
        with (output / 'stage_review.json').open('x', encoding='utf-8') as stream:
            json.dump(review, stream, ensure_ascii=False, indent=2)
    if not args.execute:
        print(str(output / 'stage_review.json'))
        return
    # Scripted validation is entirely segregated from real attempt and API records.
    control = ROOT / 'runs/v3_control' if args.mode == 'llm' else output / 'scripted_control'
    with controller_lock(control / 'v3-batch.lock'):
        registry = AttemptRegistry(control / 'attempts.jsonl')
        for run, plan in zip(runs, plans):
            if args.mode == 'llm':
                check_deadline(args.stop_at)
            previous_steps = 0
            run_output = output / plan['run_id']
            attempt_binding = {'output_path': str(run_output), 'manifest_sha256': binding['manifest_sha256'], 'stage': args.stage}
            prior = registry.for_run(plan['run_id'])
            if args.resume_batch and prior:
                if any(prior.get(k) != v for k, v in attempt_binding.items()):
                    raise ExecutionError('Attempt is bound to a different output/manifest/stage')
                if prior['kind'] == 'complete':
                    continue
                if prior['kind'] != 'checkpoint' or prior.get('clean_commit') is not True:
                    raise ExecutionError('Only known clean checkpoints may resume; inspect failed or interrupted evidence')
                aid = prior['attempt_id']
                previous_steps = prior['committed_steps']
            else:
                aid = registry.start(plan['run_id'], auth['authorization_id'] if auth else 'scripted',
                                     auth['max_attempts'] if auth else 850, **attempt_binding)
            commands = chunk_commands(ROOT, Path(args.manifest).resolve(), run, args.mode, run_output,
                                      args.chunk_steps, args.authorization, args.stop_at, previous_steps,
                                      aid if args.mode == 'llm' else None)
            for command in commands:
                if args.mode == 'llm':
                    check_deadline(args.stop_at)
                expected_steps = previous_steps + int(command[command.index('--steps') + 1])
                registry.append('running', aid, committed_steps=previous_steps, requested_end_step=expected_steps)
                result = subprocess.run(command, cwd=ROOT, shell=False, check=False)
                receipt_path = output / plan['run_id'] / 'controller_receipt.json'
                try:
                    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                except (OSError, ValueError) as exc:
                    registry.append('technical_failure', aid, reason='Missing or invalid runtime receipt')
                    raise ExecutionError('Missing runtime receipt; failed evidence retained') from exc
                if result.returncode or receipt.get('status') == 'technical_failure':
                    registry.append('technical_failure', aid, reason='Runtime technical failure', receipt=str(receipt_path))
                    raise ExecutionError('Technical failure; no automatic retry')
                if receipt.get('run_id') != plan['run_id'] or receipt.get('clean_commit') is not True or receipt.get('committed_steps', 0) != expected_steps:
                    raise ExecutionError('Cannot resume without a matching advancing clean commit')
                previous_steps = receipt['committed_steps']
                status = receipt.get('status')
                if status not in ('complete', 'checkpoint'):
                    raise ExecutionError('Unknown runtime status; business outcomes are not technical failures')
                if (status == 'complete') != (previous_steps == run['horizon']):
                    raise ExecutionError('Completion status disagrees with planned horizon')
                registry.append(status, aid, clean_commit=True, committed_steps=previous_steps, receipt=str(receipt_path))
                if status == 'complete':
                    break
    print(str(output / 'stage_review.json'))


if __name__ == '__main__':
    main()
