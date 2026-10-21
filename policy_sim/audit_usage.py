"""Bind every paid request to its UUID, frozen payload and executed purpose."""
import hashlib
import json
from pathlib import Path
import uuid
from .io import digest
from .profiles import PURPOSES, profile_digest, settings_for_purpose, validate_profile
from .usage import summarize_native_usage


def audit_run_usage(run_dir, frozen, decisions=(), services=(), memories=(), ledger_receipts=None, environment_decisions=()):
    from .audit import _require, _read, _controller_receipts, hydrate_traces
    from .evidence import load_model_events
    root = Path(run_dir).resolve()
    profile = validate_profile(frozen['runtime_profile'])
    rows = load_model_events(root)
    paths = {str(root)}
    lineage_path = root / 'recovery_lineage.json'
    if lineage_path.exists():
        from .recovery import audit_recovery
        lineage = audit_recovery(root)
        paths.update(str(Path(entry['failed_output']).resolve()) for entry in lineage)

    receipts = list(ledger_receipts or [])
    if ledger_receipts is None:
        for path in sorted(root.glob('controller-*.json')):
            controller = _read(path)
            _require(controller.get('run_id') == frozen['record']['run_id'] and controller.get('mode') == frozen['mode'] and controller.get('runtime_profile') == profile, 'Controller identity differs')
            receipts.extend(_controller_receipts(controller))
    if frozen['mode'] == 'scripted':
        _require(not rows and not receipts and not services and all(not r.get('request_id') for r in [*decisions, *memories, *environment_decisions]), 'Scripted run contains actual model requests')
        usage, errors = summarize_native_usage(root, receipts, [])
        _require(not errors, 'Scripted consumption evidence malformed')
        return usage
    if len(paths) > 1:
        # Committed-prefix requests retain parent attempt identity and receipts;
        # discarded requests remain in whole-system usage, never actor success.
        for origin in sorted(paths - {str(root)}):
            for path in Path(origin).glob('controller-*.json'):
                controller = _read(path)
                _require(controller.get('run_id') == frozen['record']['run_id'] and controller.get('runtime_profile') == profile, 'Parent controller identity differs')
                receipts.extend(_controller_receipts(controller))
    _require(rows and receipts, 'Live run lacks model/ledger evidence')
    starts, ends, ledger = {}, {}, {}
    for row in rows:
        _require(row.get('schema_version') == 'business-request-audit-1', 'Unsupported request evidence schema')
        rid = row.get('request_id')
        _require(isinstance(rid, str) and str(uuid.UUID(rid)) == rid, 'Request lacks canonical UUID')
        _require(row.get('purpose') in PURPOSES and row.get('run_id') == frozen['record']['run_id'] and row.get('attempt_id') in paths, 'Request identity/purpose differs')
        _require(type(row.get('round')) is int and row['round'] >= 0 and type(row.get('actor_id')) is int and row['actor_id'] in (1, 2, 3, 4), 'Request actor/round invalid')
        _require(row.get('runtime_profile_sha256') == profile_digest(profile) and row.get('request_settings') == settings_for_purpose(profile, row['purpose']) and row.get('model') == profile['model'], 'Request differs from frozen settings')
        _require(row.get('input_sha256') == digest(row['messages']), 'Request input hash differs')
        options = row.get('request_options')
        _require(isinstance(options, dict) and set(options) <= {'tools', 'tool_choice'} and (row['purpose'] in ('agent_decision', 'environment_routing', 'memory') or not options), 'Unexpected request tool options')
        event = row.get('event')
        _require(event in ('request_started', 'request_finished', 'request_failed'), 'Unknown request event')
        dest = starts if event == 'request_started' else ends
        _require(rid not in dest or dest[rid] == row, 'Conflicting duplicate request event')
        dest[rid] = row
    _require(set(starts) == set(ends), 'Missing request start/terminal event')
    for rid, end in ends.items():
        start = starts[rid]
        _require(end['event'] == 'request_finished', 'Failed request in successful run')
        _require(all(end.get(k) == start.get(k) for k in ('purpose', 'round', 'actor_id', 'messages', 'request_options', 'request_settings')), 'Changed request binding')
        _require(end['unix'] >= start['unix'], 'Terminal event predates request')
        raw = end['raw_response']
        _require(end.get('usage_source') == 'provider_response' and end.get('usage') == raw.get('usage'), 'Raw response usage differs')
        choices = raw.get('choices', [])
        rejected = next((d for d in [*decisions, *environment_decisions] if d.get('request_id') == rid and d.get('response_error')), None)
        _require(rejected is not None or len(choices) == 1 and choices[0].get('finish_reason') in ('stop', 'tool_calls'), 'Incomplete paid response lacks rejected actor trace')
    for receipt in receipts:
        rid = receipt.get('client_request_id')
        if rid not in ends and len(paths) > 1:
            continue
        _require(rid in ends and (rid not in ledger or ledger[rid] == receipt), 'Extra/conflicting paid receipt')
        ledger[rid] = receipt
        request = ends[rid]
        payload = {**request['request_settings'], **request['request_options'], 'messages': request['messages'], 'stream': False, 'n': 1}
        wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        _require(receipt.get('status') == 200 and receipt.get('request_sha256') == hashlib.sha256(wire).hexdigest() and receipt.get('request_bytes') == len(wire), 'Paid receipt payload/status differs')
    _require(set(ledger) == set(ends), 'Missing paid receipt')
    used = set()
    traces = [(r, 'environment_routing') for r in environment_decisions] + [(r, 'agent_decision') for r in decisions] + [(r, 'policy_' + r['service']) for r in services] + [(r, 'memory') for r in hydrate_traces(root, memories)]
    for trace, purpose in traces:
        rid = trace.get('request_id')
        _require(rid in ends and rid not in used, 'Missing/reused transcript UUID')
        used.add(rid)
        end = ends[rid]
        _require((end['purpose'], end['round'], end['actor_id']) == (purpose, trace['round'], trace['actor_id']), 'Transcript request attribution differs')
        if purpose == 'memory':
            prior = [ends[r['request_id']] for r in decisions if (r['round'], r['actor_id']) == (trace['round'], trace['actor_id'])]
            _require(prior and trace.get('offline') is False and starts[rid]['unix'] >= max(r['unix'] for r in prior), 'Memory request precedes or lacks completed actor turn')
    _require(used == set(ends), 'Request lacks execution trace')
    usage, errors = summarize_native_usage(root, receipts, [r['request_id'] for r in decisions])
    _require(not errors, 'Consumption conflicts: ' + '; '.join(errors))
    usage['model_behavior_verified'] = True
    return usage
