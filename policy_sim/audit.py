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
from .interface import decode_candidate_choice, decode_material_read
from .llm import validate_action
from .work import WorkContext, paced
from .usage import summarize_native_usage
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

def _key(row):
    return (row['round'], row['actor_id'])

def _unique(rows):
    result = {}
    for row in rows:
        key = _key(row)
        _require(key not in result, 'Duplicate actor/round evidence')
        result[key] = row
    return result

def _calls(raw):
    choices = raw['choices']
    _require(len(choices) == 1 and choices[0]['finish_reason'] in ('stop', 'tool_calls'), 'Incomplete/ambiguous native response')
    calls = choices[0]['message'].get('tool_calls')
    _require(isinstance(calls, list) and calls, 'Native tool calls required')
    result = []
    for call in calls:
        _require(call.get('type') == 'function', 'Nonfunction native tool')
        args = _strict(call['function']['arguments'])
        _require(isinstance(args, dict), 'Tool arguments must be an object')
        result.append((call['function']['name'], args))
    return result

def _finish(args):
    """Validate the unmodified official finish contract independently."""
    from jsonschema import validate
    from agentsociety2.agent.person_tools import finish_step_tool_schema
    validate(args, finish_step_tool_schema()['function']['parameters'])
    for item in args['memories']:
        _require(type(item['importance']) in (int, float) and math.isfinite(item['importance']), 'Nonfinite memory importance')


def audit_finish_memories(run_dir, decisions, actions):
    """Match saved official episodes to raw finish and independently checked actions."""
    from .interface import canonical
    submitted = _unique(actions)
    expected = {}
    for row in decisions:
        if row.get('response_error'):
            continue
        for name, args in _calls(row['response']):
            if name != 'finish':
                continue
            key = _key(row)
            _require(key not in expected, 'Duplicate finish memory source')
            _finish(args)
            memories = []
            for raw in args['memories']:
                if not raw['text'].strip():
                    continue
                memories.append({'type': raw['type'], 'importance': raw['importance'],
                    'source': raw.get('source', 'step_result').strip() or 'step_result', 'text': ' '.join(raw['text'].strip().split()),
                    'keywords': list(dict.fromkeys(s.strip() for s in raw.get('keywords', []) if s.strip())),
                    'refs': list(dict.fromkeys(s.strip() for s in raw.get('refs', []) if s.strip()))})
            expected[key] = memories
    _require(set(expected) <= set(submitted), 'Finish lacks a business submission')
    groups = defaultdict(list)
    for row in decisions:
        groups[_key(row)].append(row)
    receipts = [row for path in Path(run_dir).glob('agents/*/native_tool_receipts.jsonl') for row in _rows(path)]
    for key in set(groups) - set(expected):
        rows = groups[key]
        identity = _prompt_blocks(rows[0]['messages'])['agent']
        history = list(_prompt_blocks(rows[0]['messages'])['recent_observations'])
        for index, row in enumerate(rows):
            if index + 1 < len(rows) and rows[index + 1]['official_turn'] == row['official_turn']:
                continue
            if row.get('response_error'):
                history.append({'action': '(invalid)', 'observation': row['response_error']})
            else:
                history.extend(r for r in receipts if _key(r) == key and r['call_index'] == row['call_index'])
        parts = []
        for observation in history:
            action = str(observation.get('action') or '').strip()
            text = str(observation.get('observation') or '').strip()
            if text:
                parts.append((f'{action}: ' if action and action != '(invalid)' else '') + text[:200])
        summary = ' | '.join(parts[:5]) if parts else 'no notable events recorded'
        text = f"Step {key[0] + 1} ({identity['current_time']}): {summary}"[:1000]
        expected[key] = [{'type': 'observation', 'importance': .4, 'source': 'step_result_fallback',
                          'text': ' '.join(text.strip().split()), 'keywords': [], 'refs': []}]
    actual = defaultdict(list)
    ids = set()
    for path in Path(run_dir).glob('agents/*/memory/episodes.jsonl'):
        actor = _read(path.parent.parent / 'AGENT.json')['agent_id']
        for episode in _rows(path):
            _require(episode.get('agent_id') == actor and episode.get('step_index') == episode.get('step_count'), 'Memory episode identity differs')
            ident = (actor, episode.get('id'))
            _require(ident not in ids, 'Duplicate memory episode')
            ids.add(ident)
            actual[episode['step_count'] - 1, actor].append({k: episode[k] for k in
                ('type', 'importance', 'source', 'text', 'keywords', 'refs')})
    _require(dict(actual) == {k: v for k, v in expected.items() if v},
             'Saved official memories differ from raw finish memories')
    return sum(map(len, expected.values()))

def hydrate_traces(run_dir, traces):
    """Join UUID references to the sole canonical transport payloads."""
    from .evidence import load_model_events
    ends = {r['request_id']: r for r in load_model_events(run_dir) if r['event'] == 'request_finished'}
    result = []
    for trace in traces:
        row = deepcopy(trace)
        if row.get('request_id'):
            event = ends[row['request_id']]
            for key in ('messages', 'request_options'):
                if key in row:
                    _require(row[key] == event[key], 'Trace changed canonical request ' + key)
                row[key] = event[key]
            response = event['raw_response']
            if 'service' in row:
                response = response['choices'][0]['message']['content']
            if 'response' in row:
                actual = deepcopy(row['response'])
                if isinstance(actual, dict):
                    actual.pop('request_id', None)
                _require(actual == response, 'Trace changed canonical response')
            row['response'] = response
        result.append(row)
    return result


def audit_requests(run_dir, frozen, decisions, routes, services, ledger_receipts=None):
    from .audit_usage import audit_run_usage
    memories = []
    for path in sorted((run_dir / 'agents').rglob('native_memory.jsonl')):
        identity = _read(path.parent / 'AGENT.json')
        for row in _rows(path):
            _require(identity.get('agent_id') == row.get('actor_id'), 'Memory workspace identity differs')
            memories.append(row)
    return audit_run_usage(run_dir, frozen, decisions, services, memories, ledger_receipts, hydrate_traces(run_dir, _rows(run_dir / "native_router_decisions.jsonl")))


def audit_mailbox(run_dir, state):
    """Recompute native transport provenance from immutable business events."""
    from datetime import datetime
    from .spec import ACTORS
    from .io import canonical
    folder = Path(run_dir) / 'env/PolicyEnv/mailbox'
    transport = _read(folder / 'TRANSPORT.json')
    native = _read(folder / 'native/state/ENV_STATE.json')
    _require(transport.get('schema') == 'policy-mailbox-1' and transport.get('world_sha256') == digest(state) and transport.get('native_sha256') == digest(native), 'Mailbox snapshot does not bind current world/native state')
    creations, deliveries = {}, {}
    delivery_order = []
    for event in state['events']:
        if event.get('kind') == 'message_created':
            message = event['message']
            _require(message['id'] not in creations, 'Duplicate message creation evidence')
            creations[message['id']] = message
        if event.get('kind') == 'message_delivered':
            mid = event['message']
            _require(mid in creations and mid not in deliveries, 'Delivery lacks unique preceding creation')
            message = creations[mid]
            _require(event['sender'] == message['sender'] and event['recipient'] == message['recipient'] and event['object'] == message['object'] and event['delivery_round'] == event['round'] and event['round'] >= message['deliver_round'], 'Business delivery identity/timing differs from creation')
            deliveries[mid] = event
            delivery_order.append(mid)
    _require(set(creations) == set(state['messages']), 'Stored messages differ from creation events')
    receipts = transport.get('receipts')
    _require(isinstance(receipts, list) and [r.get('message_id') for r in receipts] == delivery_order, 'Native receipt sequence differs from business deliveries')
    timestamps = {}
    for receipt in receipts:
        mid = receipt['message_id']
        message = state['messages'][mid]
        envelope = {k: v for k, v in creations[mid].items() if k not in ('delivered_round', 'replied')}
        _require(envelope == {k: v for k, v in message.items() if k not in ('delivered_round', 'replied')}, 'Stored envelope changed after creation')
        content_object = {'message_id': mid, 'envelope': envelope}
        content = canonical(content_object)
        timestamp = receipt['timestamp']
        stamp = datetime.fromisoformat(timestamp)
        r = deliveries[mid]['round']
        _require(r not in timestamps or timestamps[r] == stamp, 'One delivery barrier has inconsistent timestamps')
        timestamps[r] = stamp
        _require(receipt['round'] == message['delivered_round'] == r and receipt['content_sha256'] == digest(content_object), 'Native receipt differs from granted business delivery')
        _require(receipt['send'] == {'sender_id': message['sender'], 'receiver_id': message['recipient'], 'content': content}, 'Native send differs from authorized envelope')
        _require(receipt['receive'] == {'type': 'personal', 'sender_id': message['sender'], 'sender_name': ACTORS[message['sender']], 'content': content, 'timestamp': timestamp}, 'Native receive differs from authorized sender/content')
    _require(set(deliveries) == {mid for mid, m in state['messages'].items() if m['delivered_round'] is not None}, 'Business visibility was granted without native delivery evidence')
    previous = None
    for r in sorted(timestamps):
        _require(previous is None or timestamps[r] >= previous, 'Native delivery timestamps moved backwards')
        previous = timestamps[r]
    checkpoint_time = datetime.fromisoformat(transport['timestamp'])
    _require(previous is None or checkpoint_time >= previous, 'Native checkpoint predates delivery')
    _require(isinstance(native.get('mailboxes'), dict) and set(native['mailboxes']) <= {str(a) for a in ACTORS} and not any(native['mailboxes'].values()) and native.get('groups') == {} and native.get('agent_names') == {str(a): name for a, name in ACTORS.items()}, 'Native mailbox checkpoint contains unconsumed or unauthorized messages')
    count = len(receipts)
    _require(type(native.get('total_messages_sent')) is int and native['total_messages_sent'] == count and native.get('next_message_id') == count + 1 and native.get('next_group_id') == 1 and native.get('step_counter') == 0, 'Native mailbox counters differ from independent delivery count')
    return count


def audit_native(run_dir, ledger_receipts=None):
    """Return fail-closed independent checks without modifying saved evidence."""
    from .verify import verify_state
    from .audit_materials import audit_services
    (root, errors, checks) = (Path(run_dir), [], {})
    result = {'passed': False, 'errors': errors, 'checks': checks, 'verification_scope': 'native_evidence_and_physical_replay', 'real_world_inference': False}
    try:
        (frozen, state) = (_read(root / 'run_config.json'), _read(root / 'world.json'))
        result['mode'] = frozen['mode']
        profile = validate_profile(frozen['runtime_profile'])
        _require(frozen.get('request_settings') == settings_for_purpose(profile), 'Frozen native request settings mismatch')
        _require(state.get('workload_mode') == 'finite' and state.get('horizon') is None and (frozen.get('horizon') is None), 'Current profile requires finite workload without horizon')
        (observations, actions, reads) = (_rows(root / name) for name in ('observations.jsonl', 'actions.jsonl', 'material_reads.jsonl'))
        physical = verify_state(state, _read(root / 'metrics.json'), observations, material_reads=reads)
        errors.extend(physical['errors'])
        checks['physical_replay'] = physical['passed']
        checks['native_message_deliveries'] = audit_mailbox(root, state)
        result.update({k: physical[k] for k in ('independently_recomputed', 'replay_hash', 'state_sha256', 'spec_version')})
        result['policy'] = state.get('policy')
        result.update(workload_complete=physical.get('workload_complete', False), completion_status=physical.get('completion_status'), committed_round=state['round'], full_horizon=state['round'] == state['horizon'], run_id=frozen['record']['run_id'], execution_mode=frozen['mode'])
        decisions = []
        for path in sorted((root / 'agents').rglob('native_decisions.jsonl')):
            for row in _rows(path):
                identity = _read(path.parent / 'AGENT.json')
                _require(identity.get('agent_id') == row['actor_id'] and (not row.get('fallback')), 'Actor trace workspace identity/fallback mismatch')
                decisions.append(row)
        tool_receipts = [r for p in (root / 'agents').rglob('native_tool_receipts.jsonl') for r in _rows(p)]
        decisions = hydrate_traces(root, decisions)
        routes = _rows(root / 'native_routes.jsonl')
        (summaries, selected_routes) = audit_turns(decisions, observations, actions, reads, state, profile, tool_receipts, audit_personal_contexts(root, state, frozen), routes)
        checks['actor_rounds'] = len(summaries)
        checks['finish_episodes'] = audit_finish_memories(root, decisions, actions)
        for path in (root / 'agents').rglob('native_failures.jsonl'):
            _require(not _rows(path), 'Native actor failure evidence present')
        if state['round']:
            from .interface import RUNTIME_VERSION
            turns = [_read(p) for p in (root / 'agents').rglob('state/native-turn.json')]
            _require(len(turns) == 4 and {_key(t) for t in turns} == {(state['round'] - 1, a) for a in (1, 2, 3, 4)}, 'Missing native actor checkpoint evidence')
            for turn in turns:
                _require(turn.get('runtime_version') == RUNTIME_VERSION and all((turn.get(k) == v for (k, v) in summaries[_key(turn)].items())), 'Native checkpoint differs from reconstructed turn')
                _require(turn.get('step_completed') is True and (turn.get('submitted') is True or turn.get('unfiled') is True),
                         'Official step lacks completed filing or recorded unfiled outcome')
        settlements = _unique(_rows(root / 'native_settlements.jsonl'))
        expected_phases = {(r, a) for r in range(state['round']) for a in (1, 2, 3, 4)}
        _require(set(settlements) == set(summaries) == expected_phases, 'Settlements must cover every committed actor phase')
        world_results = _unique([e for e in state['events'] if e.get('kind') == 'action_result'])
        for (key, summary) in summaries.items():
            event = world_results[key]
            if event['status'] == 'unfiled':
                _require(settlements[key] == {'round': key[0], 'actor_id': key[1], 'submission_id': None,
                    'status': 'unfiled', 'code': 'actor_turn_failed', 'action_kind': None, 'target': None},
                    'Unfiled settlement differs from authoritative world events')
                continue
            sid = digest([frozen['record']['run_id'], *key])
            _require(summary['receipt'].get('submission_id') == sid and settlements[key].get('submission_id') == sid, 'Unstable submission/settlement identity')
            expected = {'round': key[0], 'actor_id': key[1], 'submission_id': sid, 'status': event['status'], 'code': event['code'], 'action_kind': event['action']['kind'], 'target': event['action']['target'], 'resources_paid': {n: round(sum((e[n] for e in state['events'] if e.get('kind') == 'resource_spent' and _key(e) == key)), 8) for n in ('labor', 'capital', 'crew')}}
            expected.pop('resources_paid')
            _require(settlements[key] == expected, 'Settlement differs from authoritative world events')
        services = hydrate_traces(root, _rows(root / 'policy_services.jsonl'))
        if frozen['mode'] == 'llm':
            errors.extend(audit_services(services, observations))
        usage = audit_requests(root, frozen, decisions, routes, services, ledger_receipts)
        result['agent_usage'] = usage
        checks['model_behavior_verified'] = usage['model_behavior_verified']
        _require(not (root / 'partial_failure.json').exists(), 'Partial failure evidence present')
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, RuntimeError, ImportError) as exc:
        errors.append('Native audit: ' + str(exc))
    if 'agent_usage' not in result:
        (usage, usage_errors) = summarize_native_usage(root, ledger_receipts)
        result['agent_usage'] = usage
        errors.extend(usage_errors)
    result['system_usage'] = result['agent_usage']['all_requests']
    result['T_system'] = result['system_usage']['total_tokens']
    if 'frozen' in locals() and 'state' in locals():
        result['comparison_identity'] = {'workload_mode': state.get('workload_mode'), 'seed': state.get('seed'), 'initial_workload': [{k: i.get(k) for k in ('id', 'facility', 'created', 'initial')} for i in state.get('issues', {}).values() if i.get('initial')], 'source_manifest': frozen.get('code_manifest'), 'runtime_profile': frozen.get('runtime_profile'), 'prompt_version': frozen.get('runtime_profile', {}).get('prompt_version', frozen.get('prompt_version', frozen.get('record', {}).get('prompt_version'))), 'scenario_conditions': {k: v for (k, v) in state.get('scenario', {}).items() if k not in ('id', 'q')}, 'config': state.get('config')}
    result['passed'] = not errors
    result['status'] = 'passed' if result['passed'] else 'failed'
    result['audit_complete'] = result['passed']
    return result

def compare_system_tokens(policy, baseline):
    """A shorter failed/incomplete trajectory can never win a token comparison."""
    reasons = []
    for (label, run) in (('policy', policy), ('baseline', baseline)):
        if not (run.get('passed') is True and run.get('workload_complete') is True and (run.get('mode') == 'llm') and (run.get('agent_usage', {}).get('complete_token_comparison') is True) and (run.get('agent_usage', {}).get('model_behavior_verified') is True)):
            reasons.append(label + ' is not a completed verified workload with complete actual usage')
    if baseline.get('policy') != '000':
        reasons.append('Baseline must be policy 000')
    identity = policy.get('comparison_identity')
    if not identity or identity != baseline.get('comparison_identity') or identity.get('workload_mode') != 'finite' or (not identity.get('source_manifest')):
        reasons.append('Incompatible or missing finite workload/source/profile/prompt identity')
    (p, b) = (policy.get('T_system'), baseline.get('T_system'))
    if type(p) is not int or type(b) is not int or p < 0 or (b <= 0):
        reasons.append('System token totals are unknown or baseline denominator is zero')
    if reasons:
        return {'eligible': False, 'errors': reasons, 'delta_tokens': None, 'savings_fraction': None, 'by_purpose': None}
    purposes = {}
    for purpose in PURPOSES:
        pv = policy['agent_usage']['by_purpose'][purpose]['total_tokens']
        bv = baseline['agent_usage']['by_purpose'][purpose]['total_tokens']
        purposes[purpose] = {'policy_tokens': pv, 'baseline_tokens': bv, 'delta_tokens': pv - bv, 'savings_fraction': 1 - pv / bv if bv else None}
    return {'eligible': True, 'errors': [], 'T_system_policy': p, 'T_system_000': b, 'delta_tokens': p - b, 'savings_fraction': 1 - p / b, 'by_purpose': purposes}


def _prompt_blocks(messages):
    """Decode the official formatter's dynamic blocks, rejecting extra context."""
    import re
    _require(isinstance(messages, list) and len(messages) >= 2 and messages[0].get('role') == 'system' and messages[1].get('role') == 'user', 'Missing official prompt')
    content = messages[1]['content']
    matches = list(re.finditer(r'<(recent_observations|memory_context|agent)>\n(.*?)\n</\1>', content, re.S))
    _require(''.join(content[m.start():m.end()] for m in matches).replace('\n', '') == content.replace('\n', ''), 'Unexpected dynamic prompt block')
    blocks = {m[1]: _strict(m[2]) for m in matches}
    _require(len(blocks) == len(matches) and {'agent', 'recent_observations'} <= blocks.keys(), 'Missing/duplicate prompt blocks')
    return blocks


def audit_environment(routes, tool_receipts):
    """Verify every actor ask executed exactly its deterministic template dispatch."""
    from .interface import dispatch_plan
    asks = {}
    for row in tool_receipts:
        if row.get('action') != 'ask_env':
            continue
        ask_id = row.get('data', {}).get('ask_id')
        _require(isinstance(ask_id, str) and str(uuid.UUID(ask_id)) == ask_id and ask_id not in asks, 'Missing/reused environment ask identity')
        asks[ask_id] = row
    actual = defaultdict(list)
    for index, route in enumerate(routes):
        _require(route.get('ordinal') == index and route.get('routing') == 'deterministic_template_dispatch' and not route.get('fallback'), 'Environment route order/runtime differs')
        actual[route.get('ask_id')].append(route)
    _require(set(actual) <= set(asks), 'Environment calls lack actor ask provenance')
    for ask_id, ask in asks.items():
        _require(len(actual[ask_id]) <= 1, 'One actor ask must execute at most one deterministic tool call')
        variables = ask['args'].get('variables')
        try:
            tool_name, expected_args = dispatch_plan(ask['args'].get('instruction'), variables if isinstance(variables, dict) else None)
        except ValueError:
            _require(not actual[ask_id], 'Environment executed a tool for an undispatchable instruction')
            continue
        _require(len(actual[ask_id]) == 1, 'A dispatchable instruction must execute exactly one tool call')
        route = actual[ask_id][0]
        _require(_key(route) == _key(ask) and route.get('actor_call_index') == ask['call_index']
                 and route.get('operation') == tool_name and route.get('payload') == expected_args,
                 'Executed environment tool differs from the deterministic dispatch')
    return asks

def _audit_memory_result(name, args, receipt, episodes):
    if not receipt['ok']:
        return
    from datetime import datetime
    limit = max(1, int(args.get('limit') or {'memory_recent': 8, 'memory_search': 20}.get(name, 50)))
    if name == 'memory_recent':
        expected = episodes[-limit:]
    elif name == 'memory_read':
        wanted = {s.strip() for s in args.get('ids', []) if s.strip()}
        expected = [e for e in episodes if e['id'] in wanted]
    elif name == 'memory_search':
        query = args.get('query', '').strip().lower()
        expected = [e for e in reversed(episodes) if query and query in json.dumps(e, ensure_ascii=False).lower()][:limit]
    else:
        expected = []
        for episode in episodes:
            include = True
            for field, value in [('step', episode.get('step_index', episode.get('step_count'))), ('tick', episode.get('tick_duration_sec', episode.get('tick'))), ('time', episode.get('time'))]:
                if field == 'time':
                    try:
                        value = datetime.fromisoformat(value)
                    except (TypeError, ValueError):
                        value = None
                for prefix in ('start_', 'end_'):
                    bound = args.get(prefix + field)
                    if bound is None:
                        continue
                    if field == 'time':
                        try:
                            bound = datetime.fromisoformat(bound)
                        except (TypeError, ValueError):
                            continue
                    if value is None or (value < bound if prefix == 'start_' else value > bound):
                        include = False
            if include:
                expected.append(episode)
            if len(expected) >= limit:
                break
    _require(receipt['data'] == {'episodes': expected} and _strict(receipt['observation']) == receipt['data'], 'Native memory tool differs from immutable personal episodes')


def _audit_workspace_result(name, args, receipt, current, notes, workspace_root=None):
    """Check filesystem authority and reconstruct business file bytes."""
    if not receipt['ok']:
        return
    from pathlib import PurePosixPath
    path = args.get('path', '.')
    parsed = PurePosixPath(path)
    if parsed.is_absolute() and workspace_root:
        try:
            parsed = parsed.relative_to(PurePosixPath(workspace_root))
        except ValueError:
            raise ValueError('Successful file tool escaped authorized workspace')
    _require(not parsed.is_absolute() and '..' not in parsed.parts and parsed.parts and parsed.parts[0] in {'business', 'notes'}, 'Successful file tool escaped authorized workspace')
    _require(name not in {'write', 'append'} or parsed.parts[0] == 'notes', 'Successful mutation touched runtime business files')
    from .work import lawful_work
    documents = {}
    for field, value in lawful_work(current).items():
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        parts, part, size = [], '', 0
        for char in text:
            width = len(char.encode('utf-8'))
            if size + width > 6000:
                parts.append(part)
                part, size = '', 0
            part += char
            size += width
        parts.append(part)
        for index, value in enumerate(parts, 1):
            documents[f'business/{field}-{index:04d}.txt'] = value
    documents['business/current.json'] = json.dumps(WorkContext(current).current_work, ensure_ascii=False, indent=2)
    documents.update(notes)
    normalized = str(parsed)
    if name == 'read':
        _require(normalized in documents, 'Native file read names unknown workspace file')
        equal = _strict(receipt['observation']) == _strict(documents[normalized]) if normalized == 'business/current.json' else receipt['observation'] == documents[normalized]
        _require(equal and receipt['data'] == {'path': normalized}, 'Native file read differs from lawful workspace bytes')
    elif name in {'write', 'append'}:
        content = args.get('content', '')
        notes[normalized] = (notes.get(normalized, '') if name == 'append' else '') + content
    elif name == 'list':
        files = receipt.get('data', {}).get('files')
        expected = sorted(k for k in documents if k == normalized or k.startswith(normalized.rstrip('/') + '/'))
        _require(isinstance(files, list) and sorted(files) == expected and _strict(receipt['observation']) == files, 'Native workspace list differs from authorized files')
    elif name == 'grep':
        import re
        matches = receipt.get('data', {}).get('matches')
        _require(isinstance(matches, list) and len(matches) <= (args.get('limit') or 100) and _strict(receipt['observation']) == receipt['data'], 'Native grep result shape differs')
        for match in matches:
            filename = match.get('path')
            _require(filename in documents and (filename == normalized or filename.startswith(normalized.rstrip('/') + '/')), 'Native grep exposed unauthorized file')
            lines = documents[filename].splitlines()
            number = match.get('line')
            _require(type(number) is int and 1 <= number <= len(lines) and match.get('text') == lines[number-1], 'Native grep line differs from lawful file bytes')
            _require(re.search(args['pattern'], match['text']) is not None, 'Native grep match differs from pattern')


def audit_turns(decisions, observations, actions, reads, state, profile=None, tool_receipts=None, personal_contexts=None, environment_routes=None):
    """Replay lawful domain state while checking unmodified official transcripts."""
    from jsonschema import validate, ValidationError
    from agentsociety2.agent.base.tool_schema import react_tool_schemas
    from agentsociety2.agent.person_tools import finish_step_tool_schema
    from .work import business_material_result
    from .io import canonical
    expected = {(r, a) for r in range(state['round']) for a in (1, 2, 3, 4)}
    obs, logged = _unique(observations), _unique(actions)
    submitted = _unique([e for e in state['events'] if e.get('kind') == 'action_submitted'])
    unfiled = _unique([e for e in state['events']
                       if e.get('kind') == 'action_result' and e.get('status') == 'unfiled'])
    groups, read_groups = defaultdict(list), defaultdict(list)
    for row in decisions:
        groups[_key(row)].append(row)
    for row in reads:
        read_groups[_key(row)].append(row)
    _require(set(obs) == expected and set(logged) == set(submitted) == expected - set(unfiled),
             'Official turns must cover every committed filed actor phase')
    _require(set(submitted) | set(unfiled) == expected and not (set(submitted) & set(unfiled)),
             'Every committed actor phase is either filed or recorded unfiled')
    _require(set(groups) == expected, 'Decision evidence must cover every committed phase')
    _require(set(read_groups) <= expected, 'Material query outside committed turn')
    receipts_all = list(tool_receipts or [])
    _require(all(_key(r) in expected and type(r.get('call_index')) is int and 0 <= r['call_index'] < len(groups[_key(r)]) for r in receipts_all), 'Tool execution outside committed call')
    env_routes = list(environment_routes or [])
    audit_environment(env_routes, receipts_all)
    route_groups = defaultdict(list)
    for route in env_routes:
        route_groups[route['ask_id']].append(route)
    official_tools = react_tool_schemas(enable_todo_list=False, enable_memory=True, disable_skills=True,
        overrides={'finish': finish_step_tool_schema()})
    summaries, selected_routes = {}, []
    for key in sorted(expected):
        current, selected, used, finished = deepcopy(obs[key]['observation']), None, 0, False
        read_ledger, read_counts = {}, {}
        session = WorkContext(current)
        rows = groups[key]
        history = None
        personal = None
        notes = deepcopy((personal_contexts or {}).get(key, {}).get('notes', {}))
        previous_turn = 0
        for index, row in enumerate(rows):
            _require(row.get('call_index') == index and row.get('readonly') is False and not finished, 'Call ordering/readonly/finish differs')
            _require(row.get('context_sha256') == current['context_sha256'], 'Call context differs from lawful observation')
            blocks = _prompt_blocks(row['messages'])
            visible_asks = [r['data']['ask_id'] for r in blocks['recent_observations']
                            if (r.get('data') or {}).get('ask_id')]
            identity = blocks['agent']
            from .work import business_receipt
            pinned_work = {'phase': 'finish' if selected is not None else 'choose',
                'round': current.get('round'), 'role': current.get('role'),
                'candidate_count': len(current.get('candidate_options', [])),
                'queued_receipt': business_receipt(logged[key]['receipt']) if selected is not None else None,
                'note': '完整候选、材料与字段经observe和read_work获取。'}
            _require(identity.get('agent_id') == key[1] and identity.get('current_work') == pinned_work, 'Actor official identity/current work differs')
            if personal_contexts is not None:
                saved = personal_contexts[key]
                _require(all(identity.get(k) == saved['identity'].get(k) for k in ('schema_version', 'agent_class', 'agent_id', 'name', 'profile')) and blocks.get('memory_context') == saved['memory_context'], 'Prompt personal memory differs from immutable round-start workspace')
                _require(identity.get('skills') == {'visible': [], 'activated': [], 'disabled': [], 'default_activated': []} and identity.get('memory') == {'enabled': True, 'summary_path': 'MEMORY.md', 'episodes_path': 'memory/episodes.jsonl'}, 'Native identity enables unauthorized skill or memory configuration')
                if key[0] > 0:
                    _require(identity.get('initialized_at') == saved['identity'].get('initialized_at'), 'Native initialization identity changed after checkpoint')
            from agentsociety2.agent.person_prompt import build_react_messages
            from .prompt import WORLD_DESCRIPTION
            official_message = build_react_messages(name=identity.get('name'), world_description=WORLD_DESCRIPTION,
                skill_catalog=[], activated_skill_content='', observations=blocks['recent_observations'],
                agent_json=identity, memory_context=blocks.get('memory_context'), todo_context=None, disable_skills=True)
            # Verify the two allowed text deltas independently, rather than
            # calling the execution adapter as the audit's answer.
            from .official_adapter import PROMPT_CORRECTIONS
            actual_system = row['messages'][0]['content']
            for original, replacement in PROMPT_CORRECTIONS:
                _require(actual_system.count(replacement) == 1 and original not in actual_system, 'Missing or repeated business prompt correction')
                actual_system = actual_system.replace(replacement, original)
            _require({'role': 'system', 'content': actual_system} == official_message[0]
                and row['messages'][1] == official_message[1], 'Prompt differs beyond the allowed official text corrections')
            snapshot = ({k:v for k,v in identity.items() if k != 'current_work'}, blocks.get('memory_context'), row['messages'][0])
            _require(personal is None or personal == snapshot, 'Personal/system context changed during one actor phase')
            personal = snapshot
            turn = row.get('official_turn')
            _require(type(turn) is int and 1 <= turn <= (profile or {}).get('max_react_turns', 10), 'Invalid official turn index')
            same_turn = index > 0 and turn == previous_turn
            _require(turn == previous_turn + 1 or same_turn and (index < 2 or rows[index-2].get('official_turn') != turn), 'Official loop/retry bounds differ')
            if history is None:
                history = blocks['recent_observations']
                _require(len(history) == 1 and history[0].get('turn') == 0 and history[0].get('action') == 'observe' and history[0].get('ok') is True and _strict(history[0]['observation']) == session.current_work, 'Initial observation differs from lawful work')
            if index and not same_turn and rows[index-1].get('response_error'):
                error = rows[index-1]['response_error']
                history.append({'turn': previous_turn, 'action': '(invalid)', 'ok': False, 'observation': error, 'data': {'error': error}})
            _require(blocks['recent_observations'] == history[-8:], 'Official prompt changed or omitted prior tool observations')
            if same_turn:
                error = rows[index-1].get('response_error')
                _require(error and row['messages'] == rows[index-1]['messages'][:2] + [
                    {'role': 'assistant', 'content': 'Invalid tool call arguments.'},
                    {'role': 'user', 'content': '<schema_error>\n' + error + '\nCall valid tool(s) with valid arguments.\n</schema_error>'}], 'Official repair prompt differs from rejected response')
            else:
                _require(len(row['messages']) == 2, 'Unexpected appended prompt context')
            previous_turn = turn
            actual_tools = row.get('request_options', {}).get('tools', [])
            names = {s['function']['name'] for s in actual_tools}
            expected_tools = official_tools
            _require(actual_tools == expected_tools and row.get('request_options', {}).get('tool_choice') == 'auto', 'Actual official tool schema differs from native surface')
            schemas = {s['function']['name']: s['function']['parameters'] for s in actual_tools}
            receipts = [r for r in receipts_all if _key(r) == key and r['call_index'] == index]
            try:
                calls = _calls(row['response'])
                for name, args in calls:
                    _require(name in schemas, 'Unavailable tool')
                    validate(args, schemas[name])
                    if name == 'finish':
                        _finish(args)
                        _require(selected is not None and len(calls) == 1, 'Premature or mixed finish')
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, ValidationError):
                _require(row.get('response_error') and not receipts and
                         (index < len(rows)-1 or same_turn and turn == (profile or {}).get('max_react_turns', 10)),
                         'Malformed call lacks rejection/retry')
                continue
            _require(not row.get('response_error'), 'Valid response was falsely marked rejected')
            if calls[0][0] == 'finish':
                _require(not receipts and index == len(rows)-1, 'Finish dispatched tools or was not final')
                finished = True
                continue
            _require(len(receipts) == len(calls), 'Missing tool execution receipts')
            for (name, args), receipt in zip(calls, receipts):
                _require(receipt.get('action') == name and receipt.get('args') == args and type(receipt.get('ok')) is bool, 'Executed tool differs from model intent')
                history.append({'turn': turn, **{k: receipt[k] for k in ('action', 'ok', 'observation', 'data')}})
                if name != 'ask_env':
                    if name in {'read', 'write', 'append', 'list', 'grep'}:
                        _audit_workspace_result(name, args, receipt, current, notes, identity.get('workspace', {}).get('root'))
                    elif name.startswith('memory_'):
                        _require(personal_contexts is not None or key[0] == 0, 'Memory retrieval lacks immutable round-start evidence')
                        _audit_memory_result(name, args, receipt, (personal_contexts or {}).get(key, {}).get('episodes', []))
                    continue
                ask_id = receipt.get('data', {}).get('ask_id')
                routed = route_groups[ask_id]
                expected_answer = {'status': 'success' if routed and all(r['ok'] for r in routed) else 'fail', 'receipts': [{k: r[k] for k in ('operation', 'payload', 'result', 'ok')} for r in routed]}
                if not routed:
                    from .interface import dispatch_plan
                    try:
                        dispatch_plan(args.get('instruction'), args.get('variables'))
                    except ValueError as exc:
                        expected_answer['error'] = str(exc)
                    else:
                        _require(False, 'Dispatchable instruction executed no environment tool')
                _require(_strict(receipt['observation']) == expected_answer and receipt['data'] == {'instruction': args['instruction'], 'template_mode': True, 'ask_id': ask_id}, 'Actor environment receipt differs from executed router results')
                for route in routed:
                    _require(route.get('visible_asks') == visible_asks and route.get('actor_turn') == turn,
                             'Router context differs from official observation window/turn')
                    op, payload = route['operation'], dict(route['payload'])
                    payload.pop('context_sha256', None)
                    if not route['ok']:
                        continue
                    _require(selected is None or op == 'observe', 'Repeated environment mutation after submission')
                    if op == 'observe':
                        expected_result = session.current_work
                    elif op == 'read_work':
                        from .work import read_work_section, read_stub
                        _require(set(payload) <= {'section', 'offset'} and 'section' in payload, 'Malformed work section query')
                        page = read_work_section(current, payload['section'], payload.get('offset', 0))
                        ledger_key = ('work', payload['section'], payload.get('offset', 0))
                        prior = read_ledger.get(ledger_key)
                        if prior is not None and prior[0] == page and prior[1] in visible_asks:
                            read_counts[ledger_key] = read_counts.get(ledger_key, 1) + 1
                            expected_result = read_stub(payload['section'], payload.get('offset', 0), read_counts[ledger_key])
                        else:
                            read_ledger[ledger_key] = (page, ask_id)
                            read_counts[ledger_key] = 1
                            expected_result = page
                        expected_result = paced(turn - 1, expected_result)
                    elif op == 'submit':
                        selected = validate_action(decode_candidate_choice(payload, current), current)
                        expected_result = {'action': selected, 'receipt': logged[key]['receipt']}
                    else:
                        _require(op == 'read_materials' and set(payload) == {'read_materials', 'reason'}, 'Malformed material query')
                        ids = decode_material_read(payload, current)
                        material_key = tuple(sorted(ids))
                        prior = read_ledger.get('materials', {}).get(material_key)
                        if prior is not None and prior in visible_asks:
                            from .work import material_stub
                            counts_key = ('materials', material_key)
                            read_counts[counts_key] = read_counts.get(counts_key, 1) + 1
                            expected_result = material_stub(ids, read_counts[counts_key])
                        else:
                            read_ledger.setdefault('materials', {})[material_key] = ask_id
                            read_counts['materials', material_key] = 1
                            _require(used < len(read_groups[key]), 'Material query lacks result')
                            read = read_groups[key][used]
                            _require(read['read_index'] == used and read['source_ids'] == ids and read['before_context_sha256'] == current['context_sha256'], 'Material query differs from intent')
                            expected_result = business_material_result(read['result'])
                            session.receive(read['result'])
                            current = session.observation
                            _require(read['after_context_sha256'] == current['context_sha256'], 'Material query result hash differs')
                            used += 1
                        expected_result = paced(turn - 1, expected_result)
                    _require(route['result'] == expected_result, 'Environment result differs from independent business replay')
                    selected_routes.append(route)
        _require(finished or rows[-1]['official_turn'] == (profile or {}).get('max_react_turns', 10),
                 'Unfinished turn did not exhaust the official loop')
        if key in unfiled:
            from .failure import unfiled_receipt
            _require(selected is None and not finished, 'Unfiled turn contains a submission or finish')
            summaries[key] = {'completion_calls': len(rows), 'receipt': unfiled_receipt(key[1], key[0]),
                              'submitted': False, 'unfiled': True}
            _require(used == len(read_groups[key]), 'Unclaimed material query')
            continue
        _require(selected is not None and selected == logged[key]['action'] == submitted[key]['action'], 'Decoded candidate differs from submission')
        _require(used == len(read_groups[key]), 'Unclaimed material query')
        receipt = logged[key]['receipt']
        _require((receipt.get('round'), receipt.get('actor_id'), receipt.get('status'), receipt.get('code')) == (*key, 'queued', 'accepted_for_settlement'), 'Submission lacks queued receipt')
        summaries[key] = {'completion_calls': len(rows), 'action': selected, 'receipt': receipt}
    return summaries, selected_routes


def audit_personal_contexts(run_dir, state, frozen):
    """Read immutable round-start personal memory; never trust prompt hashes."""
    from .checkpoints import validate_commit
    root = Path(run_dir).resolve()
    parents = [root.parent / (root.name + '-commits')]
    lineage_path = root / 'recovery_lineage.json'
    if lineage_path.exists():
        parents.extend(Path(e['snapshot_path']).parent for e in _read(lineage_path))
    contexts = {}
    for round_index in range(state['round']):
        candidates = [p / f'round-{round_index:06d}' for p in parents if (p / f'round-{round_index:06d}').is_dir()]
        _require(candidates, 'Missing immutable round-start personal workspace')
        snapshot = candidates[0]
        marker = validate_commit(snapshot)
        _require(marker['round'] == round_index and _read(snapshot / 'run_config.json') == frozen, 'Personal snapshot belongs to another round/run')
        for path in (snapshot / 'agents').glob('*/AGENT.json'):
            meta = _read(path)
            actor = meta['agent_id']
            memory_path = path.parent / 'MEMORY.md'
            if memory_path.exists():
                text = memory_path.read_text(encoding='utf-8')
            else:
                _require(round_index == 0, 'Missing persisted personal memory after initialization')
                from agentsociety2.agent.memory import DEFAULT_MEMORY_MD
                text = DEFAULT_MEMORY_MD
            cap = frozen['runtime_profile']['memory_context_max_chars']
            if len(text) > cap:
                text = text[:cap] + '\n...<truncated>'
            episodes = _rows(path.parent / 'memory/episodes.jsonl')[-frozen['runtime_profile']['recent_memory_limit']:]
            contexts[round_index, actor] = {
                'identity': meta,
                'episodes': _rows(path.parent / 'memory/episodes.jsonl'),
                'notes': {str(p.relative_to(path.parent)): p.read_text(encoding='utf-8') for p in (path.parent / 'notes').rglob('*') if p.is_file()},
                'memory_context': {'memory_md': text, 'recent_episodes': episodes,
                    'files': {'summary': 'MEMORY.md', 'episodes': 'memory/episodes.jsonl'}}}
    return contexts
