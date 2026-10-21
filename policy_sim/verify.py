"""Independent event-accounting and replay audit for V3. No network calls.

Event accounting is deliberately independent of PolicyWorld.metrics().  Replay
is a separate determinism check, not independent confirmation of assumptions.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from .spec import SPEC_VERSION
VERSION = SPEC_VERSION
ACTORS = (1, 2, 3, 4)

def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def _same(left, right):
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-08)
    return left == right

def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and (value >= 0)

def _project_accounting(state):
    """Rebuild stage times from produced records/events, not stored metrics."""
    (errors, projects, records, messages) = ([], {}, {}, {})
    learned = {actor: {} for actor in ACTORS}
    (repaired, technical_charges) = (set(), defaultdict(float))
    (config, end) = (state.get('config', {}), state.get('round', 0))
    facilities = state.get('facilities', {})
    for event in state.get('events', []):
        try:
            (kind, r) = (event['kind'], event['round'])
            if kind == 'project_proposed':
                pid = event['project']
                if pid in projects:
                    raise ValueError('duplicate proposal')
                projects[pid] = dict(project=pid, construction='not_started', built_at=None, physical='not_commissioned', effective_at=None, commissioned_at=None, administrative='open', accepted_at=None, cancelled_at=None, revision=0, facilities=None, construction_tasks={}, assessment=None, terminal=None)
            elif kind == 'record_created':
                record = event['record']
                records[record['id']] = record
                learned[record['author']][record['id']] = record
                (pid, data) = (record['object'], record['data'])
                if pid not in projects:
                    continue
                p = projects[pid]
                if record['kind'] == 'project_diagnosis':
                    p['facilities'] = sorted((x['facility'] for x in data['evidence']))
                elif record['kind'] == 'task_completed' and data['task']['kind'] == 'implement_project':
                    task = data['task']
                    if task['revision'] != p['revision'] or task['actor'] not in (2, 3) or task['state'] != 'completed' or (task['completed_round'] != r):
                        raise ValueError('invalid construction receipt')
                    if task['actor'] in p['construction_tasks']:
                        raise ValueError('duplicate construction completion')
                    p['construction_tasks'][task['actor']] = deepcopy(task)
                    p['construction'] = 'in_progress'
                elif record['kind'] == 'commissioning_result':
                    task = data['task']
                    if record['author'] != 2 or task['actor'] != 2 or task['kind'] != 'commission_project' or (data['revision'] != p['revision']) or (type(data['success']) is not bool):
                        raise ValueError('invalid commissioning result identity')
                    if p['assessment'] is not None or p['construction'] != 'built' or data['commissioned_at'] != r or (r < p['built_at'] + config.get('project_lag', 2)):
                        raise ValueError('commissioning before built/readiness or repeated assessment')
                    owned = learned[2].values()
                    for construction in p['construction_tasks'].values():
                        if not any((x['kind'] == 'task_completed' and x['data']['task'] == construction for x in owned)):
                            raise ValueError('commissioning lacks received construction evidence')
                    if p['administrative'] == 'cancelled':
                        raise ValueError('commissioning after cancellation')
                    expected_matching = p['facilities'] is not None and len(p['facilities']) >= 3 and (len({facilities[f]['root'] for f in p['facilities']}) == 1) and all((facilities[f]['shared_root'] and f not in repaired for f in p['facilities']))
                    if data['success'] is not expected_matching:
                        raise ValueError('commissioning assessment disagrees with physical matching')
                    expected_effect = r + 1 if data['success'] else None
                    if data['effective_at'] != expected_effect or task['completed_round'] != r or task['state'] != 'completed':
                        raise ValueError('commissioning effect boundary or task result invalid')
                    p.update(assessment=deepcopy(data), commissioned_at=r, effective_at=expected_effect, physical='commissioned_pending_effect' if data['success'] else 'commissioning_failed')
                elif record['kind'] == 'project_terminal':
                    terminal = data['state']
                    if record['author'] != 4 or p['terminal'] is not None or terminal not in ('completed', 'cancelled'):
                        raise ValueError('invalid administrative termination')
                    if terminal == 'completed':
                        if p['physical'] != 'effective' or not any((x['kind'] == 'commissioning_result' and x['data'] == p['assessment'] for x in learned[4].values())):
                            raise ValueError('administrative acceptance lacks effective/received result')
                        p.update(administrative='accepted', accepted_at=r)
                    else:
                        p.update(administrative='cancelled', cancelled_at=r)
                    p['terminal'] = terminal
            elif kind == 'message_created':
                messages[event['message']['id']] = event['message']
            elif kind == 'message_delivered':
                m = messages[event['message']]
                for record in m.get('payload', {}).get('records', []):
                    learned[m['recipient']][record['id']] = record
            elif kind == 'zero_friction_shared':
                for actor in event['recipients']:
                    record = records[event['record']]
                    learned[actor][record['id']] = record
            elif kind == 'project_plan_drafted':
                projects[event['project']]['revision'] = event['revision']
            elif kind == 'project_built':
                p = projects[event['project']]
                if p['built_at'] is not None or set(p['construction_tasks']) != {2, 3} or event['revision'] != p['revision'] or (event['built_at'] != r) or (r != max((x['completed_round'] for x in p['construction_tasks'].values()))):
                    raise ValueError('built event does not follow two real construction receipts')
                p.update(construction='built', built_at=r)
            elif kind in ('project_commissioned', 'project_commissioning_failed'):
                p = projects[event['project']]
                success = kind == 'project_commissioned'
                if p['assessment'] is None or p['assessment']['success'] is not success or event['success'] is not success or (event['commissioned_at'] != r) or (p['commissioned_at'] != r) or (event['effective_at'] != p['effective_at']) or (sorted(event['facilities']) != p['facilities']):
                    raise ValueError('commissioning event differs from produced assessment')
                if p.get('commission_event'):
                    raise ValueError('duplicate commissioning event')
                p['commission_event'] = True
            elif kind == 'physical_effect_activated':
                p = projects[event['project']]
                if p['physical'] != 'commissioned_pending_effect' or event['effective_at'] != r or p['effective_at'] != r or (event['revision'] != p['revision']) or (sorted(event['facilities']) != p['facilities']):
                    raise ValueError('physical activation lacks successful commissioning at exact boundary')
                p['physical'] = 'effective'
                repaired.update(p['facilities'])
            elif kind == 'project_completed':
                p = projects[event['project']]
                if p['administrative'] != 'accepted' or event['accepted_at'] != p['accepted_at'] or event['effective_at'] != p['effective_at'] or (event.get('source') != 'administrative_verification'):
                    raise ValueError('administrative completion event cannot create physical repair')
                if p.get('accepted_event'):
                    raise ValueError('duplicate administrative completion')
                p['accepted_event'] = True
            elif kind == 'project_cancelled':
                p = projects[event['project']]
                if p['administrative'] != 'cancelled' or p['cancelled_at'] != r or event['refunded'] != 0:
                    raise ValueError('cancellation event or no-refund rule invalid')
                p['cancel_event'] = True
            elif kind == 'resource_spent' and event.get('reason') == 'commission_project':
                if event['actor_id'] != 2 or not _same(event['labor'], config.get('project_commission_cost', 0.5)) or event.get('capital', 0) != 0 or (event.get('crew', 0) != 0):
                    raise ValueError('invalid commissioning technical cost')
                technical_charges[event['object_id'], r] += event['labor']
            elif kind == 'external_shock' and facilities:
                fid = event['facility']
                f = facilities[fid]
                probability = config.get('shock_probability', 0.1)
                if f['shared_root']:
                    probability = config.get('repaired_root_shock_probability', 0.025) if fid in repaired else config.get('common_root_shock_probability', 0.22)
                if event.get('root_repaired') is not (fid in repaired) or not _same(event.get('probability'), probability):
                    raise ValueError('shock risk differs from prior physical activation')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"Project event accounting at {event.get('event_index')}: {exc}")
    if set(state.get('projects', {})) != set(projects):
        errors.append('Stored project set differs from proposal events')
    stage_delays = []
    for (pid, p) in projects.items():
        stored = state.get('projects', {}).get(pid, {})
        for key in ('construction', 'built_at', 'physical', 'effective_at', 'commissioned_at', 'administrative', 'accepted_at', 'cancelled_at', 'revision'):
            if stored.get(key) != p[key]:
                errors.append(f'Project {pid} stored {key} differs from stage events')
        if p['facilities'] is not None and sorted(stored.get('facilities', [])) != p['facilities']:
            errors.append(f'Project {pid} facility scope differs from investigation record')
        if stored.get('commissioning_assessment') != p['assessment']:
            errors.append(f'Project {pid} stored commissioning assessment differs from record')
        if p['assessment'] is not None and (not p.get('commission_event') or not _same(technical_charges.pop((pid, p['commissioned_at']), 0), 0)):
            errors.append(f'Project {pid} commissioning charge and result do not match')
        if p['physical'] == 'commissioned_pending_effect' and p['effective_at'] <= end:
            errors.append(f'Project {pid} overdue physical activation')
        if p['administrative'] == 'accepted' and (not p.get('accepted_event') or stored.get('state') != 'completed'):
            errors.append(f'Project {pid} administrative completion is inconsistent')
        if p['administrative'] == 'cancelled' and (not p.get('cancel_event') or stored.get('state') != 'cancelled'):
            errors.append(f'Project {pid} administrative cancellation is inconsistent')
        failed = p['physical'] == 'commissioning_failed'
        cancelled = p['administrative'] == 'cancelled'
        built_end = p['commissioned_at'] if failed else p['cancelled_at'] if cancelled else end
        admin_end = p['cancelled_at'] if cancelled else end
        (b, f, a) = (p['built_at'], p['effective_at'], p['accepted_at'])
        stage_delays.append({'project': pid, 'built_at': b, 'commissioned_at': p['commissioned_at'], 'effective_at': f, 'accepted_at': a, 'construction': p['construction'], 'physical': p['physical'], 'administrative': p['administrative'], 'built_to_effective': f - b if f is not None and b is not None else None, 'built_to_effective_censored': b is not None and f is None and (not cancelled) and (not failed), 'built_to_effective_competing_event': 'cancelled' if cancelled and f is None else 'commissioning_failed' if failed else None, 'built_to_effective_followup': max(0, built_end - b) if b is not None and f is None else None, 'effective_to_accepted': a - f if a is not None and f is not None else None, 'effective_to_accepted_censored': f is not None and a is None and (not cancelled), 'effective_to_accepted_competing_event': 'cancelled' if f is not None and cancelled else None, 'effective_to_accepted_followup': max(0, admin_end - f) if f is not None and a is None else None})
    if technical_charges:
        errors.append('Commissioning charges lack corresponding technical assessments')
    if facilities and {fid for (fid, f) in facilities.items() if f.get('root_repaired')} != repaired:
        errors.append('Stored repaired facilities differ from physical activation events')
    metrics = {'repaired_facilities': len(repaired), 'source_repaired_facilities': len(repaired), 'projects_built': sum((p['construction'] == 'built' for p in projects.values())), 'projects_commissioned': sum((p['assessment'] is not None and p['assessment']['success'] for p in projects.values())), 'projects_commissioning_failed': sum((p['physical'] == 'commissioning_failed' for p in projects.values())), 'projects_physically_effective': sum((p['physical'] == 'effective' for p in projects.values())), 'projects_administratively_accepted': sum((p['administrative'] == 'accepted' for p in projects.values())), 'projects_completed': sum((p['administrative'] == 'accepted' for p in projects.values())), 'projects_cancelled': sum((p['administrative'] == 'cancelled' for p in projects.values())), 'projects_failed': 0, 'project_stage_delays': stage_delays, 'commissioning_labor': sum((e.get('labor', 0) for e in state.get('events', []) if e.get('kind') == 'resource_spent' and e.get('reason') == 'commission_project'))}
    return (metrics, errors)

def recompute_events(state):
    """Rebuild objective episodes, burden, censored times, and all resource use."""
    errors = []
    events = state.get('events', [])
    config = state.get('config', {})
    rounds = state.get('round', 0)
    horizon = state.get('horizon', 0)
    if type(rounds) is not int or rounds < 0 or horizon is not None:
        return ({}, ['Invalid round/horizon'])
    if not isinstance(events, list):
        return ({}, ['Events must be a list'])
    episodes = {}
    active = {}
    completions = []
    spending = {str(actor): 0.0 for actor in ACTORS}
    capital_spent = 0.0
    crew_by_round = defaultdict(float)
    opportunity = {tool: {} for tool in 'ABC'}
    adopted = {tool: set() for tool in 'ABC'}
    shocks = {}
    repaired = set()
    previous_round = 0
    for (index, event) in enumerate(events):
        if event.get('event_index') != index:
            errors.append(f'Event index is not contiguous at {index}')
        r = event.get('round')
        if type(r) is not int or r < previous_round or r > rounds:
            errors.append(f'Invalid event round at {index}')
            continue
        previous_round = r
        kind = event.get('kind')
        if kind == 'issue_created':
            (iid, facility) = (event.get('issue'), event.get('facility'))
            if not isinstance(iid, str) or iid in episodes or (not isinstance(facility, str)):
                errors.append(f'Duplicate or malformed episode at {index}')
                continue
            if facility in active:
                errors.append(f'Multiple unresolved episodes for facility {facility}')
            recurrence = any((item['facility'] == facility for item in episodes.values()))
            episodes[iid] = {'id': iid, 'facility': facility, 'created': r, 'resolved': None, 'initial': event.get('initial') is True, 'recurrence': recurrence}
            active[facility] = iid
        elif kind == 'issue_resolved':
            iid = event.get('issue')
            if iid not in episodes or episodes[iid]['resolved'] is not None:
                errors.append(f'Unknown or duplicate episode resolution at {index}')
                continue
            resolved = event.get('resolved_round', r + 1)
            if type(resolved) is not int or resolved != r + 1:
                errors.append(f'Resolution must be recorded at end of action round at {index}')
            episodes[iid]['resolved'] = resolved
            active.pop(episodes[iid]['facility'], None)
        elif kind == 'resource_spent':
            actor = str(event.get('actor_id'))
            values = [event.get(key, 0) for key in ('labor', 'capital', 'crew')]
            if actor not in spending or any((not _finite(v) for v in values)):
                errors.append(f'Invalid resource charge at {index}')
                continue
            (labor, capital, crew) = values
            spending[actor] += labor
            capital_spent += capital
            crew_by_round[r] += crew
        elif kind == 'external_shock':
            facility = event.get('facility')
            key = (r, facility)
            if key in shocks or facility not in {i['facility'] for i in episodes.values()}:
                errors.append(f'Duplicate or unknown facility risk observation at {index}')
            at_risk = facility not in active
            if event.get('at_risk') is not at_risk:
                errors.append(f'At-risk exposure differs from unresolved episode history at {index}')
            shocks[key] = at_risk
        elif kind == 'round_completed':
            completions.append(event)
        elif kind == 'physical_effect_activated':
            repaired.update(event.get('facilities', []))
        elif kind in ('tool_opportunity', 'tool_offer_changed'):
            (tool, key) = (event.get('tool'), event.get('opportunity'))
            if tool not in opportunity or key is None or type(event.get('offered')) is not bool:
                errors.append(f'Invalid offer record at {index}')
                continue
            if kind == 'tool_offer_changed' and str(key) not in opportunity[tool]:
                errors.append(f'Offer changed before the opportunity existed at {index}')
            opportunity[tool].setdefault(str(key), []).append(event['offered'])
        elif kind == 'tool_adopted':
            (tool, key) = (event.get('tool'), str(event.get('opportunity')))
            if tool not in opportunity or key not in opportunity[tool] or (not any(opportunity[tool][key])) or (key in adopted[tool]):
                errors.append(f'Adoption without a distinct offered opportunity at {index}')
            else:
                adopted[tool].add(key)
    if [e.get('completed_round') for e in completions] != list(range(1, rounds + 1)):
        errors.append('Exactly one completion is required for every committed round')
    initial = [item for item in episodes.values() if item['initial']]
    if len(initial) != 12 or len({item['facility'] for item in initial}) != 12:
        errors.append('Initial cohort must contain exactly twelve distinct facilities')
    if len(active) > 12:
        errors.append('More than twelve unresolved facilities')
    burden = 0
    settlement = []
    at_risk = 0
    for c in range(1, rounds + 1):
        unresolved = sum((item['created'] < c and (item['resolved'] is None or item['resolved'] > c) for item in episodes.values()))
        settlement.append(unresolved)
        burden += unresolved
        at_risk += 12 - unresolved
        if c <= len(completions):
            event = completions[c - 1]
            if event.get('settlement_unresolved') != unresolved:
                errors.append(f'Settlement unresolved count mismatch at round {c}')
            if event.get('cumulative_issue_burden', event.get('burden')) != burden:
                errors.append(f'Cumulative burden mismatch at round {c}')
    initial_resolved = sum((item['resolved'] is not None and item['resolved'] <= rounds for item in initial))
    initial_times = [min(item['resolved'] if item['resolved'] is not None else rounds, rounds) - item['created'] for item in initial]
    parameters = {'labor_per_actor': 100.0, 'capital': 24.0, 'shared_crew_capacity': 2}
    parameters.update({k: config[k] for k in parameters if k in config})
    if any(spending.values()) or capital_spent or any(crew_by_round.values()) or any((e.get('kind') == 'resource_spent' for e in events)):
        errors.append('Finite workload contains forbidden resource charges')
    if state.get('labor') != {} or state.get('capital') is not None or state.get('crew_remaining') is not None:
        errors.append('Finite workload retains resource pay gates')
    if state.get('pending'):
        errors.append('Partial actor phase cannot be a committed checkpoint')
    for (iid, item) in episodes.items():
        stored = state.get('issues', {}).get(iid)
        if not isinstance(stored, dict) or any((stored.get(k) != item[k] for k in ('facility', 'created', 'resolved', 'initial'))):
            errors.append(f'Stored episode {iid} differs from objective event history')
    if set(state.get('issues', {})) != set(episodes):
        errors.append('Stored episode set differs from event history')
    stored_burden = sum(state['burden_by_round']) if 'burden_by_round' in state else state.get('burden')
    if not _same(stored_burden, burden):
        errors.append('Stored burden differs from independent event sum')
    if 'burden_by_round' in state and state['burden_by_round'] != settlement:
        errors.append('Stored per-round burden differs from objective episode history')
    expected_shocks = set()
    if True and (len(episodes) != 12 or any((not item['initial'] or item['created'] != 0 for item in episodes.values())) or any((e.get('kind') in ('suppress_new_issue', 'horizon_reached', 'time_expired') for e in events))):
        errors.append('Finite workload contains exogenous work or time expiry')
    if set(shocks) != expected_shocks:
        errors.append('External-shock exposure trace does not cover twelve facilities in each risk round')
    tools = {tool: {'eligible': len(rows), 'offered': sum((any(values) for values in rows.values())), 'offer_rate': sum((any(values) for values in rows.values())) / len(rows) if rows else None, 'used': len(adopted[tool]), 'use_rate': len(adopted[tool]) / sum((any(v) for v in rows.values())) if any((any(v) for v in rows.values())) else None} for (tool, rows) in opportunity.items()}
    result = {'round': rounds, 'horizon': horizon, 'initial_issues': len(initial), 'initial_resolved': initial_resolved, 'initial_resolution_rate': initial_resolved / 12, 'initial_censored_mean_time': sum(initial_times) / 12, 'initial_cohort': initial, 'new_issues': sum((not item['initial'] for item in episodes.values())), 'recurrent_episodes': sum((item['recurrence'] for item in episodes.values())), 'unresolved_issues': len(active), 'cumulative_issue_burden': burden, 'normalized_burden': burden / (12 * horizon) if horizon else None, 'settlement_unresolved_by_round': settlement, 'at_risk_facility_rounds_after_settlement': at_risk, 'facility_at_risk_rounds': sum(shocks.values()), 'at_risk_facility_rounds': sum(shocks.values()), 'repaired_facilities': len(repaired), 'source_repaired_facilities': len(repaired), 'common_stage_burden': sum(settlement[60:90]) if horizon == 90 else None, 'common_stage_rounds': max(0, min(rounds, 90) - 60) if horizon == 90 else None, 'common_window_burden': sum(settlement[60:90]) if horizon == 90 else None, 'common_window_rounds': max(0, min(rounds, 90) - 60) if horizon == 90 else None, 'labor_spent': sum(spending.values()), 'labor_spent_by_actor': spending, 'capital_spent': capital_spent, 'shared_crew_units_spent': sum(crew_by_round.values()), 'construction_by_round': dict(crew_by_round), 'tool_opportunities': tools, 'prevention_interpretation': 'New-episode counts alone cannot establish prevention; compare burden, facility states, and at-risk exposure.'}
    (project_metrics, project_errors) = _project_accounting(state)
    result.update(project_metrics)
    errors.extend(project_errors)
    (completion, completion_errors) = recompute_completion(state)
    result['completion_status'] = completion
    errors.extend(completion_errors)
    return (result, errors)

def audit_observation(expected, actual, service_materials=None):
    from .audit_materials import audit_projection
    return audit_projection(expected, actual, service_materials)

def audit_information_flow(state):
    """Reconstruct record ownership and message delivery from audit events."""
    errors = []
    (records, messages) = ({}, {})
    learned = {str(actor): {} for actor in ACTORS}
    (maintenance, updates, failures) = ({}, {}, set())
    (registered, active, revisions) = ({}, set(), {})
    confirmation_kinds = {'joint_confirmation', 'project_confirmation', 'project_lead_confirmation', 'objection'}
    config = state.get('config', {})
    for event in state.get('events', []):
        (kind, r) = (event.get('kind'), event.get('round'))
        if kind == 'joint_workflow_registered':
            if state.get('scenario', {}).get('q', {}).get('B') != 1:
                errors.append('Automatic joint registration is not available under B0')
            registered[event.get('object')] = {'owner': event.get('owner'), 'participants': event.get('participants', [])}
        elif kind in ('joint_board_activated', 'project_board_activated'):
            active.add(event.get('ticket') or event.get('project'))
        elif kind == 'joint_withdrawn':
            active.discard(event.get('ticket'))
        if kind == 'record_created':
            record = event.get('record', {})
            (rid, actor) = (record.get('id'), str(record.get('author')))
            if not rid or rid in records or actor not in learned or (record.get('created_round') != r):
                errors.append('Invalid or duplicated professional/administrative record')
                continue
            records[rid] = deepcopy(record)
            learned[actor][rid] = deepcopy(record)
            if record.get('kind') == 'proposed_plan':
                revisions[record['object']] = record.get('data', {}).get('revision')
                active.discard(record['object'])
        elif kind == 'zero_friction_shared':
            rid = event.get('record')
            if not config.get('zero_communication_friction') or rid not in records:
                errors.append('Free ordinary synchronization lacks a produced record or sensitivity condition')
                continue
            for actor in event.get('recipients', []):
                if str(actor) not in learned:
                    errors.append('Invalid free-sharing recipient')
                else:
                    learned[str(actor)][rid] = deepcopy(records[rid])
        elif kind == 'message_created':
            message = deepcopy(event.get('message', {}))
            mid = message.get('id')
            free = message.get('free_service') is True
            expected_due = r if free else r + 1
            if not mid or mid in messages or message.get('created_round') != r or (message.get('deliver_round') != expected_due) or (str(message.get('sender')) not in learned) or (str(message.get('recipient')) not in learned):
                errors.append('Message identity, sender/recipient, or next-round delivery contract is invalid')
                continue
            if free and (not config.get('zero_communication_friction')):
                errors.append('Zero-wait message outside zero-friction sensitivity')
            if message.get('kind') == 'shared_update':
                oid = message.get('object')
                enrollment = registered.get(oid, {})
                if message.get('sender') != enrollment.get('owner') or message.get('recipient') not in enrollment.get('participants', []):
                    errors.append('Shared receipt lacks a registered owner or participant')
                for record in message.get('payload', {}).get('records', []):
                    control = record.get('kind') in confirmation_kinds
                    if oid not in active and (not control):
                        errors.append('Pre-activation sharing contains a non-confirmation business record')
                    if control and str(oid).startswith('P:') and (record.get('data', {}).get('revision') != revisions.get(oid, 0)):
                        errors.append('Shared confirmation belongs to another project revision')
            for record in message.get('payload', {}).get('records', []):
                rid = record.get('id')
                if records.get(rid) != record or record.get('object') != message.get('object'):
                    errors.append('Message contains a record that was not produced for this object')
                elif message.get('kind') != 'shared_update' and learned[str(message['sender'])].get(rid) != record:
                    errors.append('Ordinary message sender has not received the forwarded record')
            messages[mid] = message
        elif kind == 'message_delivered':
            message = messages.get(event.get('message'))
            if message is None or message.get('delivered_round') is not None:
                errors.append('Unknown or duplicated message delivery')
                continue
            if r != message['deliver_round'] or event.get('delivery_round') != r or event.get('recipient') != message['recipient']:
                errors.append('Message arrived outside its recorded delivery time or recipient')
            message['delivered_round'] = r
            for record in message.get('payload', {}).get('records', []):
                learned[str(message['recipient'])][record['id']] = deepcopy(record)
        elif kind == 'resource_spent' and event.get('reason') == 'shared_record_maintenance':
            key = (r, event.get('object_id'))
            if key in maintenance or not _same(event.get('labor'), config.get('maintenance_cost', 0.1)) or event.get('capital', 0) != 0 or (event.get('crew', 0) != 0):
                errors.append('Automatic sharing must charge maintenance exactly once per object/round')
            maintenance[key] = event
        elif kind == 'shared_update_sent':
            key = (r, event.get('object'))
            ids = event.get('records', [])
            if key in updates or not ids or any((rid not in records for rid in ids)):
                errors.append('Shared update is duplicated, empty, or invents an unproduced record')
            updates[key] = event
        elif kind == 'shared_update_failed':
            key = (r, event.get('object'))
            if key in failures:
                errors.append('Duplicate synchronization failure in one round')
            failures.add(key)
    if False and set(maintenance) != set(updates):
        errors.append('Maintenance charge and successful synchronization do not match one-to-one')
    if failures & set(updates) or failures & set(maintenance):
        errors.append('Failed sharing charged maintenance or also published an update')
    if 'records' in state and records != state['records']:
        errors.append('Stored record catalog differs from produced-record events')
    if 'messages' in state:
        if set(messages) != set(state['messages']):
            errors.append('Stored message set differs from message events')
        for (mid, message) in messages.items():
            stored = state['messages'].get(mid, {})
            if any((stored.get(k) != message.get(k) for k in ('sender', 'recipient', 'object', 'kind', 'created_round', 'deliver_round', 'delivered_round', 'payload'))):
                errors.append('Stored message differs from creation/delivery events')
            if message.get('delivered_round') is None and message['deliver_round'] <= state['round']:
                errors.append('Overdue message at a supposedly clean checkpoint')
    if 'knowledge' in state:
        for (actor, expected) in learned.items():
            if state['knowledge'].get(actor, {}).get('records') != expected:
                errors.append(f'Actor {actor} holds records without matching authorship or delivery evidence')
    return errors

def replay_actions(state, observations=None, material_reads=None):
    """Replay logged submitted actions in original order, never consult LLMs."""
    from policy_sim.core import PolicyWorld
    try:
        world = PolicyWorld(policy=state.get('policy', '111'), seed=state['seed'], horizon=state['horizon'], config=state['config'], scenario=state['scenario'], workload_mode='finite')
    except (ValueError, TypeError, KeyError) as exc:
        return (None, [f'Cannot reconstruct frozen initial world: {type(exc).__name__}: {exc}'])
    errors = []
    records = {}
    if observations is not None:
        for row in observations:
            key = (row.get('round'), row.get('actor_id'))
            if key in records:
                errors.append(f'Duplicate observation {key}')
            records[key] = row.get('observation')
        expected_keys = {(r, actor) for r in range(state['round']) for actor in ACTORS}
        if set(records) != expected_keys:
            errors.append('Observation trace must cover all four actors in every committed round')
    submissions = [e for e in state['events'] if e.get('kind') == 'action_submitted']
    actual_keys = [(e.get('round'), e.get('actor_id')) for e in submissions]
    phases = defaultdict(list)
    for (r, actor) in actual_keys:
        phases[r].append(actor)
    if list(phases) != list(range(state['round'])) or any((len(actors) != 4 or set(actors) != set(ACTORS) for actors in phases.values())):
        errors.append('Action submissions do not follow one complete four-actor phase per round')
        return (None, errors)
    try:
        def deliver_due():
            # Independently reproduce deterministic delivery from frozen business
            # envelopes; never replay transport-reported success as authority.
            for mid, message in world.messages.items():
                if message['delivered_round'] is None and message['deliver_round'] <= world.round:
                    world.accept_delivery(mid)
        deliver_due()
        submitted = set()
        for event in submissions:
            (actor, r) = (event['actor_id'], event['round'])
            expected_observation = world.observe(actor)
            if observations is not None and (r, actor) in records:
                from .audit_visibility import audit_visibility
                audit_visibility(records[r, actor], world.export_state())
                errors.extend((f'round={r} actor={actor}: {msg}' for msg in audit_observation(expected_observation, records[r, actor], world.material_service_inputs(actor))))
                from .audit_materials import replay_reads
                from .llm import validate_action
                reads = [row for row in material_reads or [] if (row.get('round'), row.get('actor_id')) == (r, actor)]
                delivered = replay_reads(world, records[r, actor], reads)
                validate_action(event['action'], delivered)
                world.bind_material_context(actor, delivered)
            world.submit(actor, deepcopy(event['action']))
            submitted.add(actor)
            if submitted == set(ACTORS):
                world.advance()
                deliver_due()
                submitted.clear()
        replayed = world.export_state()
        replay_hash = _hash(replayed)
        if replay_hash != _hash(state):
            errors.append('Action replay does not reproduce the complete exported state hash')
        return (replay_hash, errors)
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        errors.append(f'Action replay failed: {type(exc).__name__}: {exc}')
        return (None, errors)

def verify_state(state, metrics=None, observations=None, replay=True, material_reads=None):
    errors = []
    if state.get('spec_version') != VERSION:
        errors.append('State version is not ' + VERSION)
    (independent, account_errors) = recompute_events(state)
    errors.extend(account_errors)
    errors.extend(audit_information_flow(state))
    if metrics is not None:
        for key in ('round', 'horizon', 'initial_issues', 'initial_resolved', 'initial_resolution_rate', 'initial_censored_mean_time', 'new_issues', 'recurrent_episodes', 'unresolved_issues', 'cumulative_issue_burden', 'labor_spent', 'capital_spent', 'shared_crew_units_spent'):
            if key not in metrics or not _same(metrics[key], independent.get(key)):
                errors.append(f'Reported metric {key} differs from independent accounting')
        for key in ('normalized_burden', 'facility_at_risk_rounds', 'at_risk_facility_rounds', 'common_stage_burden', 'common_stage_rounds', 'common_window_burden', 'common_window_rounds', 'repaired_facilities', 'source_repaired_facilities', 'projects_built', 'projects_commissioned', 'projects_commissioning_failed', 'projects_physically_effective', 'projects_administratively_accepted', 'projects_completed', 'projects_cancelled', 'projects_failed', 'commissioning_labor', 'project_stage_delays'):
            if key in metrics and (not _same(metrics[key], independent.get(key))):
                errors.append(f'Reported metric {key} differs from independent accounting')
        if 'tool_process' in metrics:
            for (tool, values) in independent['tool_opportunities'].items():
                for (key, value) in values.items():
                    if not _same(metrics['tool_process'].get(tool, {}).get(key), value):
                        errors.append(f'Tool {tool} {key} denominator differs from event opportunities')
    replay_hash = None
    if replay and (not account_errors):
        (replay_hash, replay_errors) = replay_actions(state, observations, material_reads)
        errors.extend(replay_errors)
    return {'status': 'passed' if not errors else 'failed', 'passed': not errors, 'spec_version': VERSION, 'verification_scope': 'event_accounting_and_action_replay' if replay else 'event_accounting_only', 'independently_recomputed': independent, 'state_sha256': _hash(state), 'replay_hash': replay_hash, 'errors': errors, 'real_world_inference': False, 'workload_complete': independent.get('completion_status', {}).get('complete', False), 'completion_status': independent.get('completion_status')}

def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def recompute_completion(state):
    """Privileged event reconstruction; never trust the controller's stop flag."""
    errors = []
    events = state.get('events', [])
    initial = {e['issue']: e for e in events if e.get('kind') == 'issue_created' and e.get('initial') is True}
    resolved = {e['issue']: e for e in events if e.get('kind') == 'issue_resolved'}
    closed = {e['record']['object'] for e in events if e.get('kind') == 'record_created' and e.get('record', {}).get('kind') == 'issue_closed'}
    completed_tasks = {e['task'] for e in events if e.get('kind') == 'task_completed'}
    repaired = {f for e in events if e.get('kind') == 'physical_effect_activated' for f in e['facilities']}
    effective_projects = {e['project']: set(e['facilities']) for e in events if e.get('kind') == 'physical_effect_activated'}
    accepted = {e['project'] for e in events if e.get('kind') == 'project_completed'}
    cases = []
    for iid in sorted(initial):
        ticket_ids = [tid for (tid, t) in state.get('tickets', {}).items() if t.get('issue') == iid]
        event = resolved.get(iid)
        if len(ticket_ids) != 1:
            errors.append('Initial case lacks unique ticket: ' + iid)
            cases.append(iid)
            continue
        tid = ticket_ids[0]
        if event is None or tid not in closed:
            cases.append(iid)
        if bool(state['tickets'][tid].get('closed')) != (event is not None and tid in closed):
            errors.append('Stored ticket closure differs from resolution evidence: ' + tid)
    tasks = []
    for (tid, task) in state.get('tasks', {}).items():
        if task.get('object') not in state.get('tickets', {}):
            continue
        done = tid in completed_tasks
        if (task.get('state') == 'completed') != done:
            errors.append('Stored local task differs from completion evidence: ' + tid)
        if not done:
            tasks.append(tid)
    roots = defaultdict(list)
    for (fid, f) in state.get('facilities', {}).items():
        if f.get('shared_root'):
            roots[f['root']].append(fid)
    (repairs, acceptance) = ([], [])
    for (root, facilities) in sorted(roots.items()):
        ids = set(facilities)
        if not ids <= repaired:
            repairs.append({'root': root, 'facilities': sorted(ids)})
        if not any((pid in accepted and ids <= covered for (pid, covered) in effective_projects.items())):
            acceptance.append({'root': root, 'facilities': sorted(ids), 'project_ids': sorted((pid for (pid, p) in state.get('projects', {}).items() if ids <= set(p.get('facilities', []))))})
    if len(initial) != 12:
        errors.append('Finite completion requires the twelve initial cases')
    return ({'complete': not (errors or cases or tasks or repairs or acceptance), 'remaining_local_cases': cases, 'remaining_local_tasks': sorted(tasks), 'required_shared_root_repairs': repairs, 'required_administrative_acceptance': acceptance}, errors)


def valid_native_chunk(measured, requested, *, workload_complete=False, last_chunk=False):
    """None means the production controller ran until physical completion."""
    if type(measured) is not int or measured <= 0:
        return False
    if requested is None:
        return workload_complete is True and last_chunk is True
    return (type(requested) is int and measured <= requested
            and (measured == requested or workload_complete is True and last_chunk is True))


def verify_run(run_dir, root=None):
    """Audit a committed segment, source binding and every actual request."""
    from .audit import audit_native
    from .runtime import code_manifest
    from .checkpoints import validate_commit
    run_dir = Path(run_dir).resolve()
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    result = audit_native(run_dir)
    errors = result['errors']
    try:
        frozen = _read(run_dir / 'run_config.json')
        committed = validate_commit(run_dir)
        if frozen.get('version') != VERSION or frozen.get('code_manifest') != code_manifest(root):
            errors.append('Source/version differs from frozen configuration')
        if frozen.get('record', {}).get('runtime_profile') != frozen.get('runtime_profile'):
            errors.append('Frozen record/profile differs')
        world = _read(run_dir / 'world.json')
        if any(world.get(k) != frozen.get(k) for k in ('seed', 'horizon', 'scenario')):
            errors.append('World identity differs from frozen run')
        driver = _read(run_dir / 'driver_latest.json')
        if (driver.get('ok') is not True or driver.get('ray_shutdown') is not True
                or driver.get('completed_steps') != committed['round']
                or driver.get('routing') != 'official_PersonAgent_ReActRouter'
                or driver.get('framework_version') != frozen['runtime_profile']['framework_version']
                or driver.get('source_manifest') != frozen.get('code_manifest')
                or driver.get('runtime_profile') != frozen.get('runtime_profile')):
            errors.append('Official driver evidence incomplete or different')
        controllers = [_read(p) for p in sorted(run_dir.glob('controller-*.json'))]
        if not controllers:
            errors.append('Run lacks controller receipts')
        lineage_path = run_dir / 'recovery_lineage.json'
        lineage = _read(lineage_path) if lineage_path.exists() else []
        count = lineage[-1]['restored_steps'] if lineage else 0
        identities = set()
        for receipt in controllers:
            identity = receipt.get('invocation_id')
            if not identity or identity in identities:
                errors.append('Duplicate/missing controller invocation')
            identities.add(identity)
            measured = receipt.get('measured_rounds')
            if not valid_native_chunk(measured, receipt.get('requested_steps'), workload_complete=result.get('workload_complete') is True,
                                      last_chunk=count + measured == committed['round'] if type(measured) is int else False):
                errors.append('Controller segment size differs')
                continue
            count += measured
            if receipt.get('requested_steps') is None and (receipt.get('status') != 'complete' or driver.get('until_complete') is not True):
                errors.append('Until-complete controller lacks completed production driver evidence')
            if (receipt.get('clean_commit') is not True or receipt.get('ray_shutdown') is not True
                    or receipt.get('status') not in ('checkpoint', 'complete')
                    or receipt.get('committed_steps') != count
                    or receipt.get('source_manifest') != frozen.get('code_manifest')
                    or receipt.get('runtime_profile') != frozen.get('runtime_profile')
                    or receipt.get('mode') != frozen.get('mode')
                    or receipt.get('run_id') != frozen['record']['run_id']):
                errors.append('Controller identity or committed sequence differs')
        if count != committed['round']:
            errors.append('Controller segments do not cover committed checkpoint')
        result.update(source_manifest_sha256=_hash(frozen.get('code_manifest')),
                      independent_verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        errors.append('Checkpoint/driver audit: ' + str(exc))
    result.update(passed=not errors, status='failed' if errors else 'passed',
                  formal_analysis_eligible=not errors and result.get('mode') == 'llm' and result.get('workload_complete') is True,
                  audit_complete=not errors)
    return result
