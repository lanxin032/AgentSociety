"""Offline V3 planning and fail-closed attempt accounting. No API imports."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from policy_v3.spec import SPEC_VERSION

MODEL = 'deepseek-v4-flash'
MAX_ATTEMPTS = 850
MAX_RETRIES = 8


class ExecutionError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hash(root):
    from policy_v3.runtime import code_digest
    return code_digest(root)


def load_manifest(path, stage):
    obj = json.loads(Path(path).read_text(encoding='utf-8'))
    runs = obj.get('runs', [])
    if not runs or len({r['run_id'] for r in runs}) != len(runs):
        raise ExecutionError('Empty manifest or duplicate run_id')
    selected = [r for r in runs if r['stage'] == stage]
    if not selected or any(not isinstance(r['horizon'], int) or r['horizon'] <= 0 for r in selected):
        raise ExecutionError('Stage absent or invalid horizon')
    if any(Path(r['run_id']).name != r['run_id'] or '/' in r['run_id'] or '\\' in r['run_id'] or r['run_id'] in ('.', '..') for r in selected):
        raise ExecutionError('Unsafe run identifier')
    return obj, selected


def validate_authorization(auth, manifest_path, stage, root):
    expected = {'manifest_sha256': file_hash(manifest_path), 'stage': stage,
                'model': MODEL, 'source_sha256': source_hash(root), 'explicit_stage_authorization': True}
    if any(auth.get(k) != v for k, v in expected.items()):
        raise ExecutionError('Authorization does not bind stage, manifest, model, and source')
    for field in ('authorization_id', 'user_evidence_reference', 'approval_reference', 'price_version', 'api_ledger_path', 'baseline_prefix_sha256'):
        if not isinstance(auth.get(field), str) or not auth[field].strip():
            raise ExecutionError('Missing authorization field: ' + field)
    if auth.get('approved') is not True:
        raise ExecutionError('Authorization must record explicit approval')
    if Path(auth['api_ledger_path']).resolve() != (Path(root) / 'runs/api-smoke-budget-20260909.json').resolve():
        raise ExecutionError('Must retain the original API ledger path')
    if type(auth.get('baseline_requests')) is not int or auth['baseline_requests'] < 0:
        raise ExecutionError('Missing existing ledger request baseline')
    for field in ('incremental_request_cap', 'max_attempts'):
        if type(auth.get(field)) is not int or auth[field] <= 0:
            raise ExecutionError('Missing positive integer cap: ' + field)
    if auth['max_attempts'] > MAX_ATTEMPTS:
        raise ExecutionError('Attempt cap exceeds 850')
    for field in ('input_rmb_per_million', 'output_rmb_per_million', 'incremental_rmb_cap', 'baseline_accounted_rmb'):
        if isinstance(auth.get(field), bool) or not isinstance(auth.get(field), (int, float)) or not math.isfinite(auth[field]) or auth[field] < 0:
            raise ExecutionError('Missing finite nonnegative rate/cap: ' + field)
    if 0 in (auth['input_rmb_per_million'], auth['output_rmb_per_million']) and not auth.get('zero_price_user_evidence_reference'):
        raise ExecutionError('Zero price needs explicit user evidence; it never removes request caps')
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
    """Append-only hash chain; lock must be held by caller. Never an API ledger."""
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
        for event in self.events:
            aid = event['attempt_id']
            if event['kind'] == 'start':
                if aid in known:
                    raise ExecutionError('Duplicate attempt')
                prior = [x for x in known.values() if x['run_id'] == event['run_id']]
                if prior:
                    if prior[-1]['kind'] != 'technical_failure':
                        raise ExecutionError('Retry requires recorded technical failure')
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
        if len(known) > MAX_ATTEMPTS or retries > MAX_RETRIES:
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
        used = sum(e['kind'] == 'start' and e.get('authorization_id') == authorization_id for e in self.events)
        if used >= cap:
            raise ExecutionError('Stage authorization attempt cap exhausted')
        aid = f'attempt-{sum(e["kind"] == "start" for e in self.events) + 1:04d}'
        self.append('start', aid, run_id=run_id, authorization_id=authorization_id, **bindings)
        return aid


def quote(runs, receipts=()):
    measured = []
    legacy = 0
    for receipt in receipts:
        if receipt.get('version') != SPEC_VERSION:
            legacy += 1
            continue
        if receipt.get('mode') != 'llm' or receipt.get('stage') not in ('diagnostic', 'pilot', 'diagnostics'):
            continue
        steps = receipt.get('measured_rounds', 0)
        requests = receipt.get('requests')
        elapsed = receipt.get('elapsed_seconds')
        if steps > 0 and isinstance(requests, (int, float)) and requests >= 0 and isinstance(elapsed, (int, float)) and elapsed > 0:
            measured.append((requests / steps, elapsed / steps))
    rounds = sum(r['horizon'] for r in runs)
    advice_bound = 0
    for run in runs:
        scenario = run.get('scenario', {})
        schedule = scenario.get('schedule', [])
        a_possible = scenario.get('q', {}).get('A', 0) > 0 or any(p.get('q', {}).get('A', 0) > 0 for p in schedule)
        if a_possible:
            # Twelve facilities; one unresolved episode per facility; two format attempts.
            advice_bound += run['horizon'] * 12 * 2
    result = {'version': SPEC_VERSION, 'runs': len(runs), 'rounds': rounds, 'status': 'measured' if measured else 'no_measurement',
              'legacy_receipts_excluded': legacy, 'measurement_count': len(measured), 'authorizes_execution': False,
              'request_bound_formula': '8 actor requests per round + up to 24 advice requests per round if A can be offered; API authorization cap remains binding',
              'actor_request_bound': rounds * 8, 'advice_request_bound': advice_bound,
              'worst_case_request_cap': rounds * 8 + advice_bound,
              'estimated_requests_with_25pct': None, 'estimated_seconds_with_25pct': None,
              'bound_assumptions': ['4 actors, at most 2 formatting attempts each per round',
                                    '12 facilities, at most one unresolved episode each',
                                    'At most one new recommendation input per facility per round, 2 formatting attempts']}
    if measured:
        result.update(requests_per_round_max=max(v[0] for v in measured), seconds_per_round_max=max(v[1] for v in measured),
                      estimated_requests_with_25pct=math.ceil(rounds * max(v[0] for v in measured) * 1.25),
                      estimated_seconds_with_25pct=math.ceil(rounds * max(v[1] for v in measured) * 1.25))
    return result


def chunk_commands(root, manifest, run, mode, output, chunk_steps=5, authorization=None, stop_at=None, start_step=0, attempt_id=None):
    if chunk_steps <= 0:
        raise ExecutionError('chunk_steps must be positive')
    commands = []
    if not 0 <= start_step <= run['horizon']:
        raise ExecutionError('Invalid committed step')
    for offset in range(start_step, run['horizon'], chunk_steps):
        command = [sys.executable, '-B', str(Path(root) / 'tools/run_v3.py'), '--manifest', str(manifest), '--run-id', run['run_id'],
                   '--mode', mode, '--output', str(output), '--steps', str(min(chunk_steps, run['horizon'] - offset))]
        if offset:
            command.append('--resume')
        if authorization:
            command.extend(['--authorization', str(authorization)])
        if stop_at:
            command.extend(['--stop-at', stop_at])
        if attempt_id:
            command.extend(['--attempt-id', attempt_id])
        commands.append(command)
    return commands
