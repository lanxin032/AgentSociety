"""Current finite authorization and fail-closed attempt accounting. No API imports."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from policy_sim.spec import SPEC_VERSION

MAX_ATTEMPTS = 850
MAX_RETRIES = 8


class ExecutionError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hash(root):
    from policy_sim.runtime import code_digest
    return code_digest(root)


def validate_runtime_profile(profile):
    from .profiles import validate_profile
    return validate_profile(profile)


def validate_manifest(obj, stage='finite_baseline', require_frozen=False):
    from .protocol import validate_manifest as validate_current
    return validate_current(obj, stage, require_frozen)


def load_manifest(path, stage, require_frozen=False):
    obj = json.loads(Path(path).read_text(encoding='utf-8'))
    return obj, validate_manifest(obj, stage, require_frozen)


def authorization_paths(auth, root):
    """Keep an explicitly authorized local budget separate from cloud history."""
    root = Path(root).resolve()
    scope = auth.get('ledger_scope')
    if scope != 'independent_local':
        raise ExecutionError('Unknown budget ledger scope')
    reference = auth.get('independent_ledger_user_evidence_reference')
    if (auth.get('independent_ledger_explicitly_approved') is not True
            or not isinstance(reference, str) or not reference.strip()
            or auth.get('historical_usage_status') != 'not_migrated'
            or auth.get('execution_environment') != 'local'):
        raise ExecutionError('Independent local accounting requires explicit exception approval and historical boundary')
    from .providers import authorization_route, secret_filename
    route = authorization_route(auth)
    return {'ledger': root / 'runs/api-local-budget.json',
            'control': root / 'runs/v3_local_control', 'secret': root / secret_filename(route)}


def validate_authorization(auth, manifest_path, stage, root):
    """Require one current profile, original local ledger, and record-only execution."""
    manifest, runs = load_manifest(manifest_path, stage, require_frozen=True)
    profile = validate_runtime_profile(manifest['runtime_profile'])
    current_source = source_hash(root)
    if manifest['source_binding']['source_manifest_sha256'] != current_source:
        raise ExecutionError('Frozen design source differs from current source')
    expected = {'manifest_sha256': file_hash(manifest_path), 'stage': stage,
                'model': profile['model'], 'source_sha256': current_source,
                'explicit_stage_authorization': True}
    if any(auth.get(k) != v for k, v in expected.items()):
        raise ExecutionError('Authorization does not bind stage, manifest, model, and source')
    if auth.get('request_profiles') != [profile]:
        raise ExecutionError('Authorization does not bind the exact current request profile')
    if (auth.get('automatic_technical_retries') is not False
            or type(auth.get('max_recoveries_total')) is not int or auth['max_recoveries_total'] != 0
            or type(auth.get('max_recoveries_per_run')) is not int or auth['max_recoveries_per_run'] != 0):
        raise ExecutionError('Current execution permits no automatic retries or recoveries')
    for field in ('authorization_id', 'user_evidence_reference', 'approval_reference', 'price_version',
                  'api_ledger_path', 'baseline_prefix_sha256', 'cost_control_user_evidence_reference'):
        if not isinstance(auth.get(field), str) or not auth[field].strip():
            raise ExecutionError('Missing authorization field: ' + field)
    if auth.get('approved') is not True or auth.get('manual_resume_allowed') is not True:
        raise ExecutionError('Authorization must explicitly approve execution and manual continuation')
    if auth.get('provider_route') != profile['provider_route']:
        raise ExecutionError('Authorized provider differs from the frozen runtime profile')
    paths = authorization_paths(auth, root)
    if Path(auth['api_ledger_path']).resolve() != paths['ledger'].resolve():
        raise ExecutionError('API ledger path differs from the authorized accounting scope')
    if paths['ledger'].is_symlink() or paths['control'].is_symlink():
        raise ExecutionError('Accounting must not alias another ledger or attempt registry')
    if type(auth.get('baseline_requests')) is not int or auth['baseline_requests'] < 0:
        raise ExecutionError('Missing existing ledger request baseline')
    if (auth.get('cost_control_mode') != 'record_only'
            or 'incremental_request_cap' not in auth or auth['incremental_request_cap'] is not None
            or 'incremental_rmb_cap' not in auth or auth['incremental_rmb_cap'] is not None
            or auth.get('local_stop_at_utc')):
        raise ExecutionError('Current execution requires record-only accounting without cost/request/deadline stops')
    if type(auth.get('max_attempts')) is not int or auth['max_attempts'] != len(runs):
        raise ExecutionError('Authorization must cover exactly one initial attempt per frozen run')
    for field in ('input_rmb_per_million', 'output_rmb_per_million', 'baseline_accounted_rmb'):
        if (isinstance(auth.get(field), bool) or not isinstance(auth.get(field), (int, float))
                or not math.isfinite(auth[field]) or auth[field] < 0):
            raise ExecutionError('Missing finite nonnegative accounting value: ' + field)
    if 0 in (auth['input_rmb_per_million'], auth['output_rmb_per_million']) and not auth.get('zero_price_user_evidence_reference'):
        raise ExecutionError('Zero price requires explicit user evidence')
    body_limit = auth.get('max_body_bytes')
    if type(body_limit) is not int or not 1 <= body_limit <= 1024 * 1024:
        raise ExecutionError('Request body capacity must be an integer from 1 to 1 MiB')
    return auth


def check_deadline(stop_at, reserve_seconds=60):
    if not stop_at:
        raise ExecutionError('Execution requires verified cloud stop-at UTC')
    deadline = datetime.fromisoformat(stop_at.replace('Z', '+00:00'))
    if deadline.tzinfo is None or deadline.utcoffset().total_seconds() != 0:
        raise ExecutionError('stop-at must specify UTC')
    if (deadline - datetime.now(timezone.utc)).total_seconds() <= reserve_seconds:
        raise ExecutionError('Cloud stop deadline too close')


@contextmanager
def controller_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ExecutionError('Controller lock exists; inspect owner, never auto-remove') from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
        path.unlink()


class AttemptRegistry:
    """Append-only attempt chain; caller owns the lock. Never an API ledger.

    Historical event scopes and their original limits remain interpreted when
    validating the existing registry. They do not enable historical execution.
    """
    def __init__(self, path):
        self.path = Path(path)
        self.head_path = self.path.with_suffix(self.path.suffix + '.head.json')
        self.events = []
        if self.head_path.exists() and not self.path.exists():
            raise ExecutionError('Registry removed while durable head remains')
        if self.path.exists():
            raw = self.path.read_bytes()
            if raw and not raw.endswith(b'\n'):
                raise ExecutionError('Torn registry; evidence must be investigated')
            try:
                for line in raw.splitlines():
                    event = json.loads(line)
                    checksum = event.pop('sha256')
                    if event['previous'] != (self.events[-1]['sha256'] if self.events else '0' * 64) or digest(event) != checksum:
                        raise ExecutionError('Registry hash chain mismatch')
                    event['sha256'] = checksum
                    self.events.append(event)
                self._validate()
                head = json.loads(self.head_path.read_text(encoding='utf-8'))
                expected = {'events': len(self.events), 'sha256': self.events[-1]['sha256'] if self.events else '0' * 64}
                if head != expected:
                    raise ExecutionError('Durable registry head mismatch; truncation or interrupted append')
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ExecutionError('Invalid registry') from exc

    def _validate(self):
        known = {}
        retries = 0
        legacy_attempts = 0
        for event in self.events:
            aid = event['attempt_id']
            if event['kind'] == 'start':
                if aid in known:
                    raise ExecutionError('Duplicate attempt')
                scope = event.get('attempt_scope')
                if scope not in (None, 'authorization'):
                    raise ExecutionError('Unknown attempt scope')
                if event.get('manual_continuation'):
                    parent = known.get(event.get('recovery_of'), {})
                    if (parent.get('kind') != 'technical_failure' or parent.get('run_id') != event['run_id']
                            or parent.get('authorization_id') != event['authorization_id']
                            or not event.get('checkpoint_sha256')
                            or any(e.get('recovery_of') == event.get('recovery_of') for e in known.values())):
                        raise ExecutionError('Broken manual continuation chain')
                prior = [x for x in known.values() if x['run_id'] == event['run_id'] and
                         (x.get('authorization_id') == event['authorization_id'] if scope == 'authorization'
                          else x.get('attempt_scope') is None)]
                if scope is None:
                    legacy_attempts += 1
                if prior:
                    if prior[-1]['kind'] != 'technical_failure':
                        raise ExecutionError('Retry requires recorded technical failure')
                    if scope is None:
                        retries += 1
                known[aid] = event
            else:
                if aid not in known or known[aid]['kind'] in ('complete', 'technical_failure'):
                    raise ExecutionError('Invalid transition')
                if event['kind'] not in ('running', 'checkpoint', 'complete', 'technical_failure'):
                    raise ExecutionError('Unknown transition')
                if event['kind'] == 'checkpoint' and event.get('clean_commit') is not True:
                    raise ExecutionError('Uncommitted checkpoint')
                known[aid] = {**known[aid], **event}
        if legacy_attempts > MAX_ATTEMPTS or retries > MAX_RETRIES:
            raise ExecutionError('850-attempt or 8-technical-retry cap exceeded')

    def append(self, kind, attempt_id, **fields):
        event = {**fields, 'kind': kind, 'attempt_id': attempt_id,
                 'previous': self.events[-1]['sha256'] if self.events else '0' * 64}
        event['sha256'] = digest(event)
        self.events.append(event)
        try:
            self._validate()
        except Exception:
            self.events.pop()
            raise
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('ab') as stream:
            stream.write((json.dumps(event, sort_keys=True) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        temporary = self.head_path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump({'events': len(self.events), 'sha256': event['sha256']}, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.head_path)
        return event

    def latest(self, attempt_id):
        found = {}
        for event in self.events:
            if event['attempt_id'] == attempt_id:
                found.update(event)
        return found

    def for_run(self, run_id):
        starts = [e for e in self.events if e['kind'] == 'start' and e['run_id'] == run_id]
        return self.latest(starts[-1]['attempt_id']) if starts else None

    def start(self, run_id, authorization_id, cap=MAX_ATTEMPTS, **bindings):
        # Manual continuations do not consume another run's initial attempt.
        used = sum(e['kind'] == 'start' and e.get('authorization_id') == authorization_id
                   and e.get('manual_continuation') is not True for e in self.events)
        if used >= cap:
            raise ExecutionError('Stage authorization attempt cap exhausted')
        aid = f'attempt-{sum(e["kind"] == "start" for e in self.events) + 1:04d}'
        self.append('start', aid, run_id=run_id, authorization_id=authorization_id, **bindings)
        return aid



    def start_continuation(self, run_id, authorization_id, parent_attempt_id, checkpoint_sha256, **bindings):
        parent = self.latest(parent_attempt_id)
        if (parent.get('kind') != 'technical_failure' or parent.get('run_id') != run_id
                or parent.get('authorization_id') != authorization_id
                or any(e['kind'] == 'start' and e.get('recovery_of') == parent_attempt_id for e in self.events)
                or not isinstance(checkpoint_sha256, str) or len(checkpoint_sha256) != 64):
            raise ExecutionError('Invalid explicit continuation lineage')
        aid = f'attempt-{sum(e["kind"] == "start" for e in self.events) + 1:04d}'
        self.append('start', aid, run_id=run_id, authorization_id=authorization_id,
                    attempt_scope='authorization', recovery_of=parent_attempt_id,
                    manual_continuation=True, checkpoint_sha256=checkpoint_sha256, **bindings)
        return aid


def execute_stage(root, manifest_path, authorization_path, output, *, resume=False, runner=None):
    """Run one controller at a time; incomplete turns require explicit resume."""
    import shutil
    import subprocess
    from .io import read_json, write_json
    from .protocol import require_baseline
    from .runtime import code_manifest
    from .checkpoints import validate_commit, copy_checkpoint, restore_payload_links
    from .recovery import tree_hashes
    root, output = Path(root).resolve(), Path(output).resolve()
    manifest_path, authorization_path = Path(manifest_path).resolve(), Path(authorization_path).resolve()
    manifest_header = read_json(manifest_path)
    manifest, runs = load_manifest(manifest_path, manifest_header['stage'], True)
    auth = validate_authorization(read_json(authorization_path), manifest_path, manifest['stage'], root)
    require_baseline(manifest, root)
    if not output.is_relative_to(root / 'runs'):
        raise ExecutionError('Output must be under project runs')
    binding = {'source_sha256': source_hash(root), 'manifest_sha256': file_hash(manifest_path),
               'authorization_sha256': file_hash(authorization_path), 'stage': manifest['stage']}
    control = authorization_paths(auth, root)['control']
    runner = runner or subprocess.run
    with controller_lock(control / 'policy-sim-stage.lock'):
        registry = AttemptRegistry(control / 'attempts.jsonl')
        if resume:
            from .proxy import ControllerLock
            with ControllerLock(root / 'runs' / 'v3-framework-runtime'):
                pass
            state = read_json(output / 'batch_status.json')
            if any(state.get(k) != v for k, v in binding.items()):
                raise ExecutionError('Resume source, manifest or authorization changed')
        else:
            if output.exists():
                raise ExecutionError('Output exists; evidence cannot be overwritten')
        from .budget import open_stage_ledger
        open_stage_ledger(root, authorization_path, manifest_path, manifest['stage'])
        if not resume:
            output.mkdir(parents=True)
            state = {**binding, 'status': 'prepared', 'runs': {r['run_id']: {'status': 'prepared'} for r in runs}}
            write_json(output / 'stage_review.json', {**binding, 'source_manifest': code_manifest(root),
                'manifest': str(manifest_path), 'authorization': str(authorization_path), 'automatic_retries': False})
        for record in runs:
            row = state['runs'][record['run_id']]
            if row['status'] == 'complete':
                validate_commit(Path(row['output_path']))
                continue
            if resume and row['status'] != 'prepared':
                previous_output = Path(row['output_path'])
                latest = read_json(previous_output.parent / (previous_output.name + '-commits') / 'latest.json')
                snapshot = Path(latest['path'])
                committed = validate_commit(snapshot)
                frozen = read_json(snapshot / 'run_config.json')
                if frozen['record'] != record or frozen['code_manifest'] != code_manifest(root):
                    raise ExecutionError('Old source or run definition cannot be resumed')
                if latest['committed_sha256'] != file_hash(snapshot / 'committed.json'):
                    raise ExecutionError('Latest checkpoint binding differs')
                old_attempt = row['attempt_id']
                old = registry.latest(old_attempt)
                if old['kind'] != 'technical_failure':
                    registry.append('technical_failure', old_attempt, reason='Explicit resume after interrupted controller')
                # Resume authorization is explicit and separate from automatic retries.
                if auth.get('manual_resume_allowed') is not True:
                    raise ExecutionError('Manual continuation is not authorized')
                if any(e['kind'] == 'start' and e.get('recovery_of') == old_attempt for e in registry.events):
                    raise ExecutionError('An attempt already has a continuation')
                destination = output / (record['run_id'] + '-resume-' + str(len(registry.events)))
                aid = registry.start_continuation(record['run_id'], auth['authorization_id'], old_attempt,
                    file_hash(snapshot / 'committed.json'), output_path=str(destination), stage=record['stage'],
                    manifest_sha256=binding['manifest_sha256'])
                before = tree_hashes(snapshot)
                shutil.copytree(snapshot, destination)
                if tree_hashes(destination) != before or tree_hashes(snapshot) != before:
                    raise ExecutionError('Snapshot changed during restore')
                prior_lineage = read_json(destination / 'recovery_lineage.json') if (destination / 'recovery_lineage.json').exists() else []
                write_json(destination / 'recovery_lineage.json', prior_lineage + [{'run_id': record['run_id'],
                    **binding, 'authorization_id': auth['authorization_id'], 'attempt_id': aid,
                    'parent_attempt_id': old_attempt, 'snapshot_path': str(snapshot),
                    'snapshot_sha256': file_hash(snapshot / 'committed.json'),
                    'restored_steps': committed['round'], 'failed_output': str(previous_output),
                    'failed_evidence_sha256': digest(tree_hashes(previous_output))}])
                # A continuation can itself fail before its first new round.
                # Preserve its inherited clean boundary as a new immutable copy.
                parent = destination.parent / (destination.name + '-commits')
                parent.mkdir()
                inherited = parent / f"round-{committed['round']:06d}"
                copy_checkpoint(destination, inherited)
                validate_commit(inherited)
                write_json(parent / 'latest.json', {'round': committed['round'],
                    'path': str(inherited), 'committed_sha256': file_hash(inherited / 'committed.json')})
                restore_payload_links(snapshot, destination)
                previous = committed['round']
                restoring = True
            else:
                destination = output / record['run_id']
                aid = registry.start(record['run_id'], auth['authorization_id'], auth['max_attempts'],
                    attempt_scope='authorization', output_path=str(destination), stage=record['stage'],
                    manifest_sha256=binding['manifest_sha256'])
                previous, restoring = 0, False
            row.update(output_path=str(destination), attempt_id=aid, committed_steps=previous, status='running')
            state['status'] = 'running'
            write_json(output / 'batch_status.json', state)
            # One long-lived official framework process per attempt.
            # The driver commits initial state and every settled round in-process.
            command = [sys.executable, '-B', '-m', 'policy_sim.controller', '--manifest', str(manifest_path),
                '--run-id', record['run_id'], '--output', str(destination),
                '--authorization', str(authorization_path), '--attempt-id', aid]
            if restoring:
                command.append('--resume')
            registry.append('running', aid, committed_steps=previous)
            result = runner(command, cwd=root, check=False)
            receipt = read_json(destination / 'controller_receipt.json') if (destination / 'controller_receipt.json').exists() else {}
            if result.returncode or receipt.get('clean_commit') is not True or receipt.get('ray_shutdown') is not True or receipt.get('pending_requests', 0):
                failure = receipt.get('failure') or {'error_type': 'technical_failure', 'retryable': False}
                registry.append('technical_failure', aid, failure=failure)
                actual = receipt.get('latest_committed_round', receipt.get('committed_steps', previous))
                if type(actual) is not int or actual < previous:
                    actual = previous
                row.update(status='paused', failure=failure, committed_steps=actual)
                state['status'] = 'paused'
                write_json(output / 'batch_status.json', state)
                return False
            commit = validate_commit(destination)
            if commit['round'] != receipt.get('committed_steps') or commit['round'] < previous:
                raise ExecutionError('Controller did not commit requested round')
            previous = commit['round']
            complete = receipt.get('completion_status', {}).get('complete') is True
            if not complete:
                raise ExecutionError('Long-lived attempt returned before workload completion')
            if complete:
                from .verify import verify_run
                verification = verify_run(destination, root)
                write_json(destination / 'verification.json', verification)
                if not verification.get('passed') or not verification.get('workload_complete'):
                    registry.append('technical_failure', aid, reason='Independent audit failed')
                    row.update(status='paused', failure='independent_audit_failed')
                    state['status'] = 'paused'
                    write_json(output / 'batch_status.json', state)
                    return False
            registry.append('complete' if complete else 'checkpoint', aid,
                clean_commit=True, committed_steps=previous)
            row.update(status='complete' if complete else 'checkpoint', committed_steps=previous)
            write_json(output / 'batch_status.json', state)
        state['status'] = 'complete'
        write_json(output / 'batch_status.json', state)
        return True
