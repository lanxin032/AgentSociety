"""Independent native evidence audit. Never imports the native runtime guards.

Business physics is replayed by verify_state; subjective memory is never used
as proof of a business result. Scripted evidence cannot certify model behavior.
"""
from collections import defaultdict
from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path
import uuid
from policy_sim.io import digest
from .profiles import MODEL, PURPOSES, profile_digest, settings_for_purpose, validate_profile

def _strict(raw):

    def pairs(items):
        out = {}
        for (key, value) in items:
            if key in out:
                raise ValueError('Duplicate JSON field: ' + key)
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))

def _read(path):
    return _strict(path.read_text(encoding='utf-8'))

def _rows(path):
    return [_strict(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.is_file() else []

def _require(ok, message):
    if not ok:
        raise ValueError(message)

def _controller_receipts(controller):
    """A scripted zero-request controller need not manufacture an API ledger."""
    count = controller.get('requests')
    _require(type(count) is int and count >= 0, 'Controller request count must be a nonnegative integer')
    if controller.get('mode') == 'scripted':
        _require(count == 0 and controller.get('request_receipts', []) == [] and (controller.get('budget_before') is None) and (controller.get('budget_after') is None) and (controller.get('pending_requests') in (None, 0)), 'Scripted controller must have zero API consumption')
        return []
    values = controller.get('request_receipts')
    _require(isinstance(values, list), 'Paid controller requires explicit request receipts')
    _require(len(values) == count, 'Controller request total differs from receipts')
    return values

def summarize_native_usage(run_dir, ledger_receipts=None, finalized_request_ids=None):
    """Account for observed consumption even when execution/trace audit fails.

    UUIDs identify paid requests, never repeated HTTP delivery or copied log rows.
    This does not certify successful behavior or authorize outcome comparison.
    The ``agent`` partition reports agent_decision-only consumption;
    consolidation, router and policy service consumption remain explicit parts.
    """
    (root, errors, requests, receipts) = (Path(run_dir), [], {}, {})
    unlinked = 0

    def lines(path):
        nonlocal unlinked
        if not path.is_file():
            return []
        result = []
        try:
            content = path.read_text(encoding='utf-8')
        except OSError as exc:
            errors.append('Unreadable consumption evidence: ' + str(exc))
            return []
        for line in content.splitlines():
            if not line.strip():
                continue
            try:
                value = _strict(line)
                _require(isinstance(value, dict), 'Request row must be an object')
                result.append(value)
            except (ValueError, TypeError) as exc:
                unlinked += 1
                errors.append('Malformed consumption row: ' + str(exc))
        return result

    def identity(row, field):
        nonlocal unlinked
        rid = row.get(field)
        try:
            _require(isinstance(rid, str) and str(uuid.UUID(rid)) == rid, 'Noncanonical request identity')
            return rid
        except (ValueError, AttributeError, TypeError):
            unlinked += 1
            errors.append('Consumption lacks canonical UUID')
            return None

    def counter(record, data, key, rid):
        if not isinstance(data, dict) or data.get(key) is None:
            return
        value = data[key]
        if type(value) is not int or value < 0:
            record['uncertain'] = True
            errors.append('Invalid consumption counter: ' + rid)
            return
        if key in record['usage'] and record['usage'][key] != value:
            record['usage'][key] = min(value, record['usage'][key])
            record['uncertain'] = True
            errors.append('Conflicting consumption counter: ' + rid)
        else:
            record['usage'][key] = value
    from .evidence import load_model_events
    paths = {root.resolve()}
    lineage_path = root / 'recovery_lineage.json'
    if lineage_path.exists():
        try:
            paths.update(Path(entry['failed_output']).resolve() for entry in _read(lineage_path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append('Invalid consumption lineage: ' + str(exc))
    model_rows = []
    for evidence_path in sorted(paths):
        try:
            model_rows.extend(load_model_events(evidence_path))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append('Canonical model payload evidence: ' + str(exc))
            model_rows.extend(lines(evidence_path / 'model_requests.jsonl'))
    for row in model_rows:
        rid = identity(row, 'request_id')
        if rid is None:
            continue
        rec = requests.setdefault(rid, {'usage': {}, 'events': {}, 'uncertain': False})
        for key in ('purpose', 'actor_id', 'round', 'run_id', 'attempt_id', 'input_sha256', 'runtime_profile_sha256'):
            if key in row:
                if key in rec and rec[key] != row[key]:
                    rec['uncertain'] = True
                    errors.append('Conflicting consumption provenance: ' + rid)
                else:
                    rec[key] = row[key]
        event = row.get('event')
        if event not in ('request_started', 'request_finished', 'request_failed'):
            rec['uncertain'] = True
            errors.append('Unknown consumption request event: ' + rid)
        if event in rec['events'] and rec['events'][event] != row:
            rec['uncertain'] = True
            errors.append('Conflicting duplicate consumption event: ' + rid)
        rec['events'][event] = row
        raw = row.get('raw_response')
        for source in (row.get('usage'), raw.get('usage') if isinstance(raw, dict) else None):
            for key in ('prompt_tokens', 'completion_tokens'):
                counter(rec, source, key, rid)
            if isinstance(source, dict) and all((type(source.get(k)) is int for k in ('prompt_tokens', 'completion_tokens', 'total_tokens'))) and (source['total_tokens'] != source['prompt_tokens'] + source['completion_tokens']):
                rec['uncertain'] = True
                errors.append('Consumption total differs from component counters: ' + rid)
    ledger_rows = list(ledger_receipts or [])
    controller_paths = [p for origin in paths if ledger_receipts is None or origin != root.resolve() for p in origin.glob('controller-*.json')]
    if controller_paths:
        for path in sorted(controller_paths):
            try:
                value = _read(path)
                rows = value.get('request_receipts', [])
                if isinstance(rows, list):
                    ledger_rows.extend(rows)
                _controller_receipts(value)
                if value.get('mode') == 'scripted' and requests:
                    errors.append('Scripted controller has actual model request evidence')
            except (OSError, ValueError, TypeError, KeyError) as exc:
                errors.append('Unreadable controller consumption: ' + str(exc))
    for row in ledger_rows:
        if not isinstance(row, dict):
            unlinked += 1
            errors.append('Malformed consumption receipt')
            continue
        rid = identity(row, 'client_request_id')
        if rid is None:
            continue
        if rid in receipts and receipts[rid] != row:
            errors.append('Conflicting duplicate paid receipt: ' + rid)
            requests.setdefault(rid, {'usage': {}, 'events': {}, 'uncertain': False})['uncertain'] = True
        receipts[rid] = row
    logged_ids = set(requests)
    for (rid, receipt) in receipts.items():
        rec = requests.setdefault(rid, {'usage': {}, 'events': {}, 'uncertain': False})
        for key in ('prompt_tokens', 'completion_tokens'):
            counter(rec, receipt, key, rid)
        if receipt.get('status') == 200 and 'request_failed' in rec['events']:
            pass
        elif 'request_finished' in rec['events'] and receipt.get('status') != 200:
            rec['uncertain'] = True
            errors.append('Successful SDK response has conflicting paid status: ' + rid)

    def empty():
        return {'request_count': 0, 'known_prompt_tokens': 0, 'known_completion_tokens': 0, 'known_total_tokens': 0, 'unknown_usage_requests': 0, 'total_tokens': 0, 'failed_requests': 0, 'unfinished_requests': 0}
    by_purpose = {p: empty() for p in (*PURPOSES, 'unknown')}
    parts = {p: empty() for p in ('agent', 'finalized', 'discarded', 'unclassified', 'policy_service', 'all_requests')}
    (by_actor, by_round) = ({}, {})
    final = None if finalized_request_ids is None else set(finalized_request_ids)
    (missing, unmatched) = (len(logged_ids - set(receipts)), len(set(receipts) - logged_ids))
    unknown_purpose = 0
    for (rid, rec) in requests.items():
        purpose = rec.get('purpose')
        if purpose not in PURPOSES:
            purpose = 'unknown'
            unknown_purpose += 1
        outputs = [parts['all_requests'], by_purpose[purpose]]
        if purpose == 'agent_decision':
            outputs += [parts['agent'], parts['unclassified' if final is None else 'finalized' if rid in final else 'discarded']]
            if type(rec.get('actor_id')) is int:
                outputs.append(by_actor.setdefault(str(rec['actor_id']), empty()))
            if type(rec.get('round')) is int:
                outputs.append(by_round.setdefault(str(rec['round']), empty()))
        if purpose in ('policy_A', 'policy_C'):
            outputs.append(parts['policy_service'])
        failed = 'request_failed' in rec['events'] or receipts.get(rid, {}).get('status') not in (None, 200, 'reserved')
        unfinished = not any((k in rec['events'] for k in ('request_finished', 'request_failed'))) and receipts.get(rid, {}).get('status') in (None, 'reserved')
        for out in outputs:
            out['request_count'] += 1
            for key in ('prompt_tokens', 'completion_tokens'):
                out['known_' + key] += rec['usage'].get(key, 0)
            out['unknown_usage_requests'] += rec['uncertain'] or len(rec['usage']) < 2
            out['failed_requests'] += failed
            out['unfinished_requests'] += unfinished
    (cumulative, cumulative_by_round) = (empty(), {})
    for key in sorted(by_round, key=int):
        for field in cumulative:
            if field not in ('total_tokens', 'known_total_tokens'):
                cumulative[field] += by_round[key][field]
        cumulative_by_round[key] = dict(cumulative)
    for out in [*parts.values(), *by_purpose.values(), *by_actor.values(), *by_round.values(), *cumulative_by_round.values()]:
        out['known_total_tokens'] = out['known_prompt_tokens'] + out['known_completion_tokens']
        out['total_tokens'] = None if out['unknown_usage_requests'] else out['known_total_tokens']
    usage = {'schema_version': 'agent-usage-1', 'native_schema_version': 'native-usage-1', 'agent_definition': 'agent_decision only; memory is reported separately', **parts, 'memory': by_purpose['memory'], 'by_purpose': by_purpose, 'by_actor': by_actor, 'by_round': by_round, 'cumulative_by_round': cumulative_by_round, 'usage_source': 'provider_response_and_paid_receipts', 'system_definition': 'T_system = prompt_tokens + completion_tokens for every actual request; reasoning tokens are already included in completion_tokens', 'request_count': len(requests), 'unlinked_rows': unlinked, 'unknown_purpose_requests': unknown_purpose, 'missing_receipt_requests': missing, 'unmatched_receipt_requests': unmatched, 'complete_token_comparison': not errors and (not (unlinked or unknown_purpose or missing or unmatched or parts['all_requests']['unknown_usage_requests'])), 'model_behavior_verified': False, 'accounting_errors': list(dict.fromkeys(errors))}
    return (usage, usage['accounting_errors'])
