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
        return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-8)
    return left == right


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _project_accounting(state):
    """Rebuild stage times from produced records/events, not stored metrics."""
    errors, projects, records, messages = [], {}, {}, {}
    learned = {actor: {} for actor in ACTORS}
    repaired, technical_charges = set(), defaultdict(float)
    config, end = state.get('config', {}), state.get('round', 0)
    facilities = state.get('facilities', {})
    for event in state.get('events', []):
        try:
            kind, r = event['kind'], event['round']
            if kind == 'project_proposed':
                pid = event['project']
                if pid in projects:
                    raise ValueError('duplicate proposal')
                projects[pid] = dict(project=pid, construction='not_started', built_at=None,
                    physical='not_commissioned', effective_at=None, commissioned_at=None,
                    administrative='open', accepted_at=None, cancelled_at=None, revision=0,
                    facilities=None, construction_tasks={}, assessment=None, terminal=None)
            elif kind == 'record_created':
                record = event['record']; records[record['id']] = record
                learned[record['author']][record['id']] = record
                pid, data = record['object'], record['data']
                if pid not in projects:
                    continue
                p = projects[pid]
                if record['kind'] == 'project_diagnosis':
                    p['facilities'] = sorted(x['facility'] for x in data['evidence'])
                elif record['kind'] == 'task_completed' and data['task']['kind'] == 'implement_project':
                    task = data['task']
                    if task['revision'] != p['revision'] or task['actor'] not in (2, 3) or task['state'] != 'completed' or task['completed_round'] != r:
                        raise ValueError('invalid construction receipt')
                    if task['actor'] in p['construction_tasks']:
                        raise ValueError('duplicate construction completion')
                    p['construction_tasks'][task['actor']] = deepcopy(task)
                    p['construction'] = 'in_progress'
                elif record['kind'] == 'commissioning_result':
                    task = data['task']
                    if record['author'] != 2 or task['actor'] != 2 or task['kind'] != 'commission_project' or data['revision'] != p['revision'] or type(data['success']) is not bool:
                        raise ValueError('invalid commissioning result identity')
                    if p['assessment'] is not None or p['construction'] != 'built' or data['commissioned_at'] != r or r < p['built_at'] + config.get('project_lag', 2):
                        raise ValueError('commissioning before built/readiness or repeated assessment')
                    owned = learned[2].values()
                    for construction in p['construction_tasks'].values():
                        if not any(x['kind'] == 'task_completed' and x['data']['task'] == construction for x in owned):
                            raise ValueError('commissioning lacks received construction evidence')
                    if p['administrative'] == 'cancelled':
                        raise ValueError('commissioning after cancellation')
                    expected_matching = (p['facilities'] is not None and len(p['facilities']) >= 3
                        and len({facilities[f]['root'] for f in p['facilities']}) == 1
                        and all(facilities[f]['shared_root'] and f not in repaired for f in p['facilities']))
                    if data['success'] is not expected_matching:
                        raise ValueError('commissioning assessment disagrees with physical matching')
                    expected_effect = r + 1 if data['success'] else None
                    if data['effective_at'] != expected_effect or task['completed_round'] != r or task['state'] != 'completed':
                        raise ValueError('commissioning effect boundary or task result invalid')
                    p.update(assessment=deepcopy(data), commissioned_at=r, effective_at=expected_effect,
                             physical='commissioned_pending_effect' if data['success'] else 'commissioning_failed')
                elif record['kind'] == 'project_terminal':
                    terminal = data['state']
                    if record['author'] != 4 or p['terminal'] is not None or terminal not in ('completed', 'cancelled'):
                        raise ValueError('invalid administrative termination')
                    if terminal == 'completed':
                        if p['physical'] != 'effective' or not any(x['kind'] == 'commissioning_result' and x['data'] == p['assessment'] for x in learned[4].values()):
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
                if p['built_at'] is not None or set(p['construction_tasks']) != {2, 3} or event['revision'] != p['revision'] or event['built_at'] != r or r != max(x['completed_round'] for x in p['construction_tasks'].values()):
                    raise ValueError('built event does not follow two real construction receipts')
                p.update(construction='built', built_at=r)
            elif kind in ('project_commissioned', 'project_commissioning_failed'):
                p = projects[event['project']]
                success = kind == 'project_commissioned'
                if p['assessment'] is None or p['assessment']['success'] is not success or event['success'] is not success or event['commissioned_at'] != r or p['commissioned_at'] != r or event['effective_at'] != p['effective_at'] or sorted(event['facilities']) != p['facilities']:
                    raise ValueError('commissioning event differs from produced assessment')
                if p.get('commission_event'):
                    raise ValueError('duplicate commissioning event')
                p['commission_event'] = True
            elif kind == 'physical_effect_activated':
                p = projects[event['project']]
                if p['physical'] != 'commissioned_pending_effect' or event['effective_at'] != r or p['effective_at'] != r or event['revision'] != p['revision'] or sorted(event['facilities']) != p['facilities']:
                    raise ValueError('physical activation lacks successful commissioning at exact boundary')
                p['physical'] = 'effective'
                repaired.update(p['facilities'])
            elif kind == 'project_completed':
                p = projects[event['project']]
                if p['administrative'] != 'accepted' or event['accepted_at'] != p['accepted_at'] or event['effective_at'] != p['effective_at'] or event.get('source') != 'administrative_verification':
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
                if event['actor_id'] != 2 or not _same(event['labor'], config.get('project_commission_cost', .5)) or event.get('capital', 0) != 0 or event.get('crew', 0) != 0:
                    raise ValueError('invalid commissioning technical cost')
                technical_charges[(event['object_id'], r)] += event['labor']
            elif kind == 'external_shock' and facilities:
                fid = event['facility']; f = facilities[fid]
                probability = config.get('shock_probability', .10)
                if f['shared_root']:
                    probability = config.get('repaired_root_shock_probability', .025) if fid in repaired else config.get('common_root_shock_probability', .22)
                if event.get('root_repaired') is not (fid in repaired) or not _same(event.get('probability'), probability):
                    raise ValueError('shock risk differs from prior physical activation')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f'Project event accounting at {event.get("event_index")}: {exc}')
    if set(state.get('projects', {})) != set(projects):
        errors.append('Stored project set differs from proposal events')
    stage_delays = []
    for pid, p in projects.items():
        stored = state.get('projects', {}).get(pid, {})
        for key in ('construction', 'built_at', 'physical', 'effective_at', 'commissioned_at', 'administrative', 'accepted_at', 'cancelled_at', 'revision'):
            if stored.get(key) != p[key]:
                errors.append(f'Project {pid} stored {key} differs from stage events')
        if p['facilities'] is not None and sorted(stored.get('facilities', [])) != p['facilities']:
            errors.append(f'Project {pid} facility scope differs from investigation record')
        if stored.get('commissioning_assessment') != p['assessment']:
            errors.append(f'Project {pid} stored commissioning assessment differs from record')
        if p['assessment'] is not None and (not p.get('commission_event') or not _same(technical_charges.pop((pid, p['commissioned_at']), 0), config.get('project_commission_cost', .5))):
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
        b, f, a = p['built_at'], p['effective_at'], p['accepted_at']
        stage_delays.append({'project': pid, 'built_at': b, 'commissioned_at': p['commissioned_at'], 'effective_at': f, 'accepted_at': a,
            'construction': p['construction'], 'physical': p['physical'], 'administrative': p['administrative'],
            'built_to_effective': f - b if f is not None and b is not None else None,
            'built_to_effective_censored': b is not None and f is None and not cancelled and not failed,
            'built_to_effective_competing_event': 'cancelled' if cancelled and f is None else 'commissioning_failed' if failed else None,
            'built_to_effective_followup': max(0, built_end - b) if b is not None and f is None else None,
            'effective_to_accepted': a - f if a is not None and f is not None else None,
            'effective_to_accepted_censored': f is not None and a is None and not cancelled,
            'effective_to_accepted_competing_event': 'cancelled' if f is not None and cancelled else None,
            'effective_to_accepted_followup': max(0, admin_end - f) if f is not None and a is None else None})
    if technical_charges:
        errors.append('Commissioning charges lack corresponding technical assessments')
    if facilities and {fid for fid, f in facilities.items() if f.get('root_repaired')} != repaired:
        errors.append('Stored repaired facilities differ from physical activation events')
    metrics = {'repaired_facilities': len(repaired), 'source_repaired_facilities': len(repaired),
        'projects_built': sum(p['construction'] == 'built' for p in projects.values()),
        'projects_commissioned': sum(p['assessment'] is not None and p['assessment']['success'] for p in projects.values()),
        'projects_commissioning_failed': sum(p['physical'] == 'commissioning_failed' for p in projects.values()),
        'projects_physically_effective': sum(p['physical'] == 'effective' for p in projects.values()),
        'projects_administratively_accepted': sum(p['administrative'] == 'accepted' for p in projects.values()),
        'projects_completed': sum(p['administrative'] == 'accepted' for p in projects.values()),
        'projects_cancelled': sum(p['administrative'] == 'cancelled' for p in projects.values()),
        'projects_failed': 0, 'project_stage_delays': stage_delays,
        'commissioning_labor': sum(e.get('labor', 0) for e in state.get('events', []) if e.get('kind') == 'resource_spent' and e.get('reason') == 'commission_project')}
    return metrics, errors


def recompute_events(state):
    """Rebuild objective episodes, burden, censored times, and all resource use."""
    errors = []
    events = state.get('events', [])
    config = state.get('config', {})
    rounds = state.get('round', 0)
    horizon = state.get('horizon', 0)
    if type(rounds) is not int or type(horizon) is not int or not 0 <= rounds <= horizon:
        return {}, ['Invalid round/horizon']
    if not isinstance(events, list):
        return {}, ['Events must be a list']
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
    for index, event in enumerate(events):
        if event.get('event_index') != index:
            errors.append(f'Event index is not contiguous at {index}')
        r = event.get('round')
        if type(r) is not int or r < previous_round or r > rounds:
            errors.append(f'Invalid event round at {index}')
            continue
        previous_round = r
        kind = event.get('kind')
        if kind == 'issue_created':
            iid, facility = event.get('issue'), event.get('facility')
            if not isinstance(iid, str) or iid in episodes or not isinstance(facility, str):
                errors.append(f'Duplicate or malformed episode at {index}')
                continue
            if facility in active:
                errors.append(f'Multiple unresolved episodes for facility {facility}')
            recurrence = any(item['facility'] == facility for item in episodes.values())
            episodes[iid] = {'id': iid, 'facility': facility, 'created': r, 'resolved': None,
                             'initial': event.get('initial') is True, 'recurrence': recurrence}
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
            if actor not in spending or any(not _finite(v) for v in values):
                errors.append(f'Invalid resource charge at {index}')
                continue
            labor, capital, crew = values
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
            tool, key = event.get('tool'), event.get('opportunity')
            if tool not in opportunity or key is None or type(event.get('offered')) is not bool:
                errors.append(f'Invalid offer record at {index}')
                continue
            if kind == 'tool_offer_changed' and str(key) not in opportunity[tool]:
                errors.append(f'Offer changed before the opportunity existed at {index}')
            opportunity[tool].setdefault(str(key), []).append(event['offered'])
        elif kind == 'tool_adopted':
            tool, key = event.get('tool'), str(event.get('opportunity'))
            if tool not in opportunity or key not in opportunity[tool] or not any(opportunity[tool][key]) or key in adopted[tool]:
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
        # A shock born at round c starts the next interval, after settlement c.
        unresolved = sum(item['created'] < c and (item['resolved'] is None or item['resolved'] > c)
                         for item in episodes.values())
        settlement.append(unresolved)
        burden += unresolved
        at_risk += 12 - unresolved
        if c <= len(completions):
            event = completions[c - 1]
            if event.get('settlement_unresolved') != unresolved:
                errors.append(f'Settlement unresolved count mismatch at round {c}')
            if event.get('cumulative_issue_burden', event.get('burden')) != burden:
                errors.append(f'Cumulative burden mismatch at round {c}')
    initial_resolved = sum(item['resolved'] is not None and item['resolved'] <= rounds for item in initial)
    initial_times = [min(item['resolved'] if item['resolved'] is not None else rounds, rounds) - item['created'] for item in initial]
    parameters = {'labor_per_actor': 100.0, 'capital': 24.0, 'shared_crew_capacity': 2}
    parameters.update({k: config[k] for k in parameters if k in config})
    for actor, spent in spending.items():
        if spent > parameters['labor_per_actor'] + 1e-8:
            errors.append(f'Labor overspent for actor {actor}')
        if actor not in state.get('labor', {}) or not _same(state['labor'][actor], parameters['labor_per_actor'] - spent):
            errors.append(f'Actor {actor} remaining labor does not reconcile to event charges')
    if capital_spent > parameters['capital'] + 1e-8:
        errors.append('Engineering funds overspent')
    if not _same(state.get('capital'), parameters['capital'] - capital_spent):
        errors.append('Remaining capital does not reconcile to event charges')
    if any(value > parameters['shared_crew_capacity'] + 1e-8 for value in crew_by_round.values()):
        errors.append('Per-round construction capacity exceeded')
    if state.get('pending'):
        errors.append('Partial actor phase cannot be a committed checkpoint')
    for iid, item in episodes.items():
        stored = state.get('issues', {}).get(iid)
        if not isinstance(stored, dict) or any(stored.get(k) != item[k] for k in ('facility', 'created', 'resolved', 'initial')):
            errors.append(f'Stored episode {iid} differs from objective event history')
    if set(state.get('issues', {})) != set(episodes):
        errors.append('Stored episode set differs from event history')
    stored_burden = sum(state['burden_by_round']) if 'burden_by_round' in state else state.get('burden')
    if not _same(stored_burden, burden):
        errors.append('Stored burden differs from independent event sum')
    if 'burden_by_round' in state and state['burden_by_round'] != settlement:
        errors.append('Stored per-round burden differs from objective episode history')
    expected_shocks = {(r, item['facility']) for r in range(1, min(rounds + 1, horizon)) for item in initial}
    if set(shocks) != expected_shocks:
        errors.append('External-shock exposure trace does not cover twelve facilities in each risk round')
    tools = {tool: {'eligible': len(rows), 'offered': sum(any(values) for values in rows.values()),
                    'offer_rate': sum(any(values) for values in rows.values()) / len(rows) if rows else None,
                    'used': len(adopted[tool]),
                    'use_rate': len(adopted[tool]) / sum(any(v) for v in rows.values()) if any(any(v) for v in rows.values()) else None}
             for tool, rows in opportunity.items()}
    result = {'round': rounds, 'horizon': horizon, 'initial_issues': len(initial), 'initial_resolved': initial_resolved,
              'initial_resolution_rate': initial_resolved / 12, 'initial_censored_mean_time': sum(initial_times) / 12,
              'initial_cohort': initial, 'new_issues': sum(not item['initial'] for item in episodes.values()),
              'recurrent_episodes': sum(item['recurrence'] for item in episodes.values()),
              'unresolved_issues': len(active), 'cumulative_issue_burden': burden,
              'normalized_burden': burden / (12 * horizon) if horizon else None,
              'settlement_unresolved_by_round': settlement,
              'at_risk_facility_rounds_after_settlement': at_risk,
              'facility_at_risk_rounds': sum(shocks.values()), 'at_risk_facility_rounds': sum(shocks.values()),
              'repaired_facilities': len(repaired), 'source_repaired_facilities': len(repaired),
              'common_stage_burden': sum(settlement[60:90]) if horizon == 90 else None,
              'common_stage_rounds': max(0, min(rounds, 90) - 60) if horizon == 90 else None,
              'common_window_burden': sum(settlement[60:90]) if horizon == 90 else None,
              'common_window_rounds': max(0, min(rounds, 90) - 60) if horizon == 90 else None,
              'labor_spent': sum(spending.values()), 'labor_spent_by_actor': spending,
              'capital_spent': capital_spent, 'shared_crew_units_spent': sum(crew_by_round.values()),
              'construction_by_round': dict(crew_by_round), 'tool_opportunities': tools,
              'prevention_interpretation': 'New-episode counts alone cannot establish prevention; compare burden, facility states, and at-risk exposure.'}
    project_metrics, project_errors = _project_accounting(state)
    result.update(project_metrics)
    errors.extend(project_errors)
    return result, errors


def audit_observation(expected, actual):
    """Check the exact legal projection, allowing only the public A component.

    Investigation findings may lawfully contain root information.  Such fields
    pass only when present in this actor's reconstructed legitimate observation.
    """
    if not isinstance(actual, dict):
        return ['Observation must be an object']
    # Official transport and saved JSON stringify integer mapping keys. Compare
    # both legal projections at that same transport boundary, retaining fields.
    try:
        expected = json.loads(json.dumps(expected, ensure_ascii=False, allow_nan=False))
        actual = json.loads(json.dumps(actual, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return ['Observation must be finite JSON']
    from .interface import INTERFACE_FIELDS, decorate_observation, raw_observation
    expected.pop('policy', None)  # Official router removes the legacy adapter label.
    errors = []
    expected_derived, actual_derived = INTERFACE_FIELDS & set(expected), INTERFACE_FIELDS & set(actual)
    use_interface = bool(expected_derived or actual_derived)
    if use_interface:
        if actual_derived != INTERFACE_FIELDS:
            errors.append('Observation drops or incompletely supplies required interface fields')
        else:
            try:
                fresh = decorate_observation(actual)
                if any(actual[key] != fresh[key] for key in INTERFACE_FIELDS):
                    errors.append('Observation derived interface differs from its actual raw context')
            except (KeyError, TypeError, ValueError):
                errors.append('Observation derived interface cannot be reconstructed')
        expected, actual = raw_observation(expected), raw_observation(actual)
    expected_tickets = {t['id']: t for t in expected.get('visible_tickets', [])}
    provided_recommendations = {t.get('id'): deepcopy(t.get('recommendation')) for t in actual.get('visible_tickets', [])}
    for ticket in actual.get('visible_tickets', []):
        baseline = expected_tickets.get(ticket.get('id'))
        if baseline is None:
            errors.append('Observation contains a ticket outside the role projection')
            continue
        recommendation = ticket.get('recommendation')
        if recommendation is not None and recommendation != baseline.get('recommendation'):
            permitted = {'candidates', 'uncertain', 'basis', 'provenance', 'model', 'input_sha256'}
            material = {'ticket': {k: baseline.get(k) for k in ('text', 'category', 'district', 'facility')},
                        'directory': expected.get('public_rules', {}).get('directory', {})}
            valid = (expected.get('actor_id') == 1 and baseline.get('a_offered') is True
                     and isinstance(recommendation, dict) and not set(recommendation) - permitted
                     and isinstance(recommendation.get('candidates'), list) and bool(recommendation['candidates'])
                     and all(type(a) is int and a in (2, 3) for a in recommendation['candidates'])
                     and type(recommendation.get('uncertain')) is bool
                     and isinstance(recommendation.get('basis'), str)
                     and recommendation.get('provenance') == 'real_llm_visible_material_only'
                     and recommendation.get('model') == 'deepseek-v4-flash'
                     and recommendation.get('input_sha256') == _hash(material))
            if not valid:
                errors.append('A recommendation exceeds its public-input component schema')
            if 'recommendation' in baseline:
                ticket['recommendation'] = deepcopy(baseline['recommendation'])
            else:
                ticket.pop('recommendation', None)
    expected_actions = expected.get('available_actions', [])
    actual_actions = actual.get('available_actions', [])
    if len(actual_actions) == len(expected_actions):
        for baseline, action in zip(expected_actions, actual_actions):
            if (baseline.get('kind') == action.get('kind') == 'route'
                    and baseline.get('target') == action.get('target')
                    and baseline.get('params', {}).get('use_recommendation') is True
                    and action.get('params', {}).get('use_recommendation') is True
                    and type(action.get('params', {}).get('department')) is int
                    and action['params']['department'] in (2, 3)):
                recommendation = provided_recommendations.get(action.get('target'))
                if not isinstance(recommendation, dict) or not recommendation.get('candidates') or action['params']['department'] != recommendation['candidates'][0]:
                    errors.append('A route candidate differs from its provided recommendation')
                action['params']['department'] = baseline['params']['department']
    if use_interface:
        try:
            # Advice changes the raw-context hash. Rebuild only after validating
            # the actual supplied fields, so normalization cannot hide stale IDs.
            expected, actual = decorate_observation(expected), decorate_observation(actual)
        except (KeyError, TypeError, ValueError):
            errors.append('Normalized interface cannot be reconstructed')
    if actual != expected:
        errors.append('Observation differs from reconstructed role whitelist or received information')
    return errors


def audit_information_flow(state):
    """Reconstruct record ownership and message delivery from audit events."""
    errors = []
    records, messages = {}, {}
    learned = {str(actor): {} for actor in ACTORS}
    maintenance, updates, failures = {}, {}, set()
    config = state.get('config', {})
    for event in state.get('events', []):
        kind, r = event.get('kind'), event.get('round')
        if kind == 'record_created':
            record = event.get('record', {})
            rid, actor = record.get('id'), str(record.get('author'))
            if not rid or rid in records or actor not in learned or record.get('created_round') != r:
                errors.append('Invalid or duplicated professional/administrative record')
                continue
            records[rid] = deepcopy(record)
            learned[actor][rid] = deepcopy(record)
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
            if (not mid or mid in messages or message.get('created_round') != r or message.get('deliver_round') != expected_due
                    or str(message.get('sender')) not in learned or str(message.get('recipient')) not in learned):
                errors.append('Message identity, sender/recipient, or next-round delivery contract is invalid')
                continue
            if free and not config.get('zero_communication_friction'):
                errors.append('Zero-wait message outside zero-friction sensitivity')
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
            if key in maintenance or not _same(event.get('labor'), config.get('maintenance_cost', .1)) or event.get('capital', 0) != 0 or event.get('crew', 0) != 0:
                errors.append('Automatic sharing must charge maintenance exactly once per object/round')
            maintenance[key] = event
        elif kind == 'shared_update_sent':
            key = (r, event.get('object'))
            ids = event.get('records', [])
            if key in updates or not ids or any(rid not in records for rid in ids):
                errors.append('Shared update is duplicated, empty, or invents an unproduced record')
            updates[key] = event
        elif kind == 'shared_update_failed':
            key = (r, event.get('object'))
            if key in failures:
                errors.append('Duplicate synchronization failure in one round')
            failures.add(key)
    if set(maintenance) != set(updates):
        errors.append('Maintenance charge and successful synchronization do not match one-to-one')
    if failures & set(updates) or failures & set(maintenance):
        errors.append('Failed sharing charged maintenance or also published an update')
    if 'records' in state and records != state['records']:
        errors.append('Stored record catalog differs from produced-record events')
    if 'messages' in state:
        if set(messages) != set(state['messages']):
            errors.append('Stored message set differs from message events')
        for mid, message in messages.items():
            stored = state['messages'].get(mid, {})
            if any(stored.get(k) != message.get(k) for k in ('sender', 'recipient', 'object', 'kind', 'created_round', 'deliver_round', 'delivered_round', 'payload')):
                errors.append('Stored message differs from creation/delivery events')
            if message.get('delivered_round') is None and message['deliver_round'] <= state['round']:
                errors.append('Overdue message at a supposedly clean checkpoint')
    if 'knowledge' in state:
        for actor, expected in learned.items():
            if state['knowledge'].get(actor, {}).get('records') != expected:
                errors.append(f'Actor {actor} holds records without matching authorship or delivery evidence')
    return errors


def replay_actions(state, observations=None):
    """Replay logged submitted actions in original order, never consult LLMs."""
    from policy_v3.core import PolicyWorld
    try:
        world = PolicyWorld(policy=state.get('policy', '111'), seed=state['seed'], horizon=state['horizon'],
                            config=state['config'], scenario=state['scenario'])
    except (ValueError, TypeError, KeyError) as exc:
        return None, [f'Cannot reconstruct frozen initial world: {type(exc).__name__}: {exc}']
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
    for r, actor in actual_keys:
        phases[r].append(actor)
    if (list(phases) != list(range(state['round'])) or
            any(len(actors) != 4 or set(actors) != set(ACTORS) for actors in phases.values())):
        errors.append('Action submissions do not follow one complete four-actor phase per round')
        return None, errors
    try:
        submitted = set()
        for event in submissions:
            actor, r = event['actor_id'], event['round']
            expected_observation = world.observe(actor)
            if observations is not None and (r, actor) in records:
                errors.extend(f'round={r} actor={actor}: {msg}' for msg in audit_observation(expected_observation, records[(r, actor)]))
            world.submit(actor, deepcopy(event['action']))
            submitted.add(actor)
            if submitted == set(ACTORS):
                world.advance()
                submitted.clear()
        replayed = world.export_state()
        replay_hash = _hash(replayed)
        if replay_hash != _hash(state):
            errors.append('Action replay does not reproduce the complete exported state hash')
        return replay_hash, errors
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        errors.append(f'Action replay failed: {type(exc).__name__}: {exc}')
        return None, errors


def verify_state(state, metrics=None, observations=None, replay=True):
    errors = []
    if state.get('spec_version') != VERSION:
        errors.append('State version is not ' + VERSION)
    independent, account_errors = recompute_events(state)
    errors.extend(account_errors)
    errors.extend(audit_information_flow(state))
    if metrics is not None:
        for key in ('round', 'horizon', 'initial_issues', 'initial_resolved', 'initial_resolution_rate',
                    'initial_censored_mean_time', 'new_issues', 'recurrent_episodes', 'unresolved_issues',
                    'cumulative_issue_burden', 'labor_spent', 'capital_spent', 'shared_crew_units_spent'):
            if key not in metrics or not _same(metrics[key], independent.get(key)):
                errors.append(f'Reported metric {key} differs from independent accounting')
        for key in ('normalized_burden', 'facility_at_risk_rounds', 'at_risk_facility_rounds',
                    'common_stage_burden', 'common_stage_rounds', 'common_window_burden', 'common_window_rounds',
                    'repaired_facilities', 'source_repaired_facilities', 'projects_built',
                    'projects_commissioned', 'projects_commissioning_failed', 'projects_physically_effective',
                    'projects_administratively_accepted', 'projects_completed', 'projects_cancelled',
                    'projects_failed', 'commissioning_labor', 'project_stage_delays'):
            if key in metrics and not _same(metrics[key], independent.get(key)):
                errors.append(f'Reported metric {key} differs from independent accounting')
        if 'tool_process' in metrics:
            for tool, values in independent['tool_opportunities'].items():
                for key, value in values.items():
                    if not _same(metrics['tool_process'].get(tool, {}).get(key), value):
                        errors.append(f'Tool {tool} {key} denominator differs from event opportunities')
    replay_hash = None
    if replay and not account_errors:
        replay_hash, replay_errors = replay_actions(state, observations)
        errors.extend(replay_errors)
    return {'status': 'passed' if not errors else 'failed', 'passed': not errors, 'spec_version': VERSION,
            'verification_scope': 'event_accounting_and_action_replay' if replay else 'event_accounting_only',
            'independently_recomputed': independent, 'state_sha256': _hash(state), 'replay_hash': replay_hash,
            'errors': errors, 'real_world_inference': False}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit_advice_inputs(advice, observations):
    errors = []
    lookup = {(r['round'], r['actor_id']): r['observation'] for r in observations}
    for record in advice:
        try:
            observation = lookup[(record['round'], 1)]
            ticket = next(t for t in observation['visible_tickets'] if t['id'] == record['ticket_id'])
            if ticket.get('a_offered') is not True:
                errors.append('Recommendation requested without an offered A opportunity')
            material = {'ticket': {k: ticket.get(k) for k in ('text', 'category', 'district', 'facility')},
                        'directory': observation['public_rules']['directory']}
            messages = record['messages']
            if messages[1].get('role') != 'user' or json.loads(messages[1]['content']) != material:
                errors.append('Recommendation input contains material outside public ticket/directory fields')
            if record.get('input_sha256') != _hash(material):
                errors.append('Recommendation input hash does not match public material')
        except (KeyError, IndexError, TypeError, ValueError, StopIteration):
            errors.append('Malformed or untraceable recommendation request record')
    return errors


def audit_decision_traces(model_rows, observations, actions, committed_round, submissions=None):
    """Bind every saved response/repair to its context and actually logged action."""
    from .interface import INTERFACE_FIELDS, decorate_observation, decode_candidate_choice
    from .llm import SYSTEM, REPAIR_PROMPT, validate_action
    from policy_mve.llm import parse_object
    errors, groups, lookup, logged = [], defaultdict(list), {}, {}
    expected = {(r, a) for r in range(committed_round) for a in ACTORS}
    try:
        # Compare at the same finite-JSON boundary as the persisted evidence.
        model_rows, observations, actions = json.loads(json.dumps([model_rows, observations, actions], ensure_ascii=False, allow_nan=False))
        for row in observations:
            key = (row['round'], row['actor_id'])
            if key in lookup:
                errors.append(f'Duplicate decision observation {key}')
            lookup[key] = row['observation']
        for row in actions:
            key = (row['round'], row['actor_id'])
            if key in logged:
                errors.append(f'Duplicate logged action {key}')
            logged[key] = row
            receipt = row.get('receipt', {})
            if receipt.get('actor_id') != key[1] or receipt.get('round') != key[0] or receipt.get('status') != 'queued' or receipt.get('code') not in ('accepted_for_settlement', 'duplicate_idempotent'):
                errors.append(f'Logged submission has no matching queued receipt {key}')
        for row in model_rows:
            key = (row['round'], row['actor_id'])
            if type(row['round']) is not int or type(row['actor_id']) is not int or ('idle' not in row and type(row.get('attempt')) is not int):
                errors.append('Decision trace identity/attempt types are invalid')
            groups[key].append(row)
        if set(lookup) != expected or set(logged) != expected or set(groups) != expected:
            errors.append('Decision observations, traces and actions must cover every committed actor/round exactly')
        if submissions is not None:
            actual = {(e['round'], e['actor_id']): e['action'] for e in submissions}
            if len(actual) != len(submissions) or set(actual) != expected or any(logged.get(k, {}).get('action') != a for k, a in actual.items()):
                errors.append('Logged decoded actions differ from world action submissions')
        paired, idle_paired = 0, 0
        for key, rows in groups.items():
            try:
                obs = lookup[key]
                if not INTERFACE_FIELDS <= set(obs) or audit_observation(obs, obs):
                    raise ValueError('captured interface is missing, stale or inconsistent')
                fresh = decorate_observation(obs)
                if any('idle' in row for row in rows):
                    if len(rows) != 1 or rows[0] != {'round': key[0], 'actor_id': key[1], 'idle': True} or rows[0]['idle'] is not True:
                        raise ValueError('idle trace must be the single frozen idle record')
                    if any(action['kind'] != 'wait' for action in obs['available_actions']):
                        raise ValueError('idle trace hides an available non-wait action')
                    idle_action = validate_action({'kind': 'wait', 'target': None, 'params': {}, 'reason': '无可执行任务'}, obs)
                    if logged[key]['action'] != idle_action:
                        raise ValueError('idle action differs from the frozen automatic wait')
                    idle_paired += 1
                    continue
                if len(rows) not in (1, 2) or [row['attempt'] for row in rows] != list(range(len(rows))):
                    raise ValueError('attempts must be initial zero and at most one repair')
                history = [{'round': prior[0], 'action': logged[prior]['action'], 'receipt': logged[prior]['receipt']}
                           for prior in sorted(logged) if prior[1] == key[1] and prior[0] < key[0]][-3:]
                first = rows[0]['messages']
                if len(first) != 2 or first[0] != {'role': 'system', 'content': SYSTEM} or first[1].get('role') != 'user':
                    raise ValueError('initial system/messages differ from frozen decision contract')
                body = json.loads(first[1]['content'])
                if body != {'observation': obs, 'recent_history': history}:
                    raise ValueError('prompt observation or prior action history differs from saved evidence')
                selected, previous_failed = None, False
                for attempt, row in enumerate(rows):
                    if row.get('context_sha256') != fresh['context_sha256'] or row.get('candidate_options') != fresh['candidate_options']:
                        raise ValueError('trace candidate mapping or context hash is stale/altered')
                    if not isinstance(row.get('response'), str) or row.get('finish_reason') not in ('stop', 'length'):
                        raise ValueError('trace lacks a text completion/finish reason')
                    if attempt:
                        expected_messages = deepcopy(first) + [{'role': 'assistant', 'content': rows[0]['response']}, {'role': 'user', 'content': REPAIR_PROMPT}]
                        if not previous_failed or row['messages'] != expected_messages:
                            raise ValueError('repair follows a valid choice or changes the frozen repair messages')
                    try:
                        decoded = validate_action(decode_candidate_choice(parse_object(row['response']), obs), obs)
                    except (ValueError, TypeError) as exc:
                        previous_failed = True
                        if row.get('validation_error') != str(exc) or 'decoded_action' in row:
                            raise ValueError('failed response lacks its exact validation trace or invents an action')
                        if attempt == len(rows) - 1:
                            raise ValueError('committed action has no valid decoded model choice')
                    else:
                        previous_failed = False
                        if 'validation_error' in row or row.get('decoded_action') != decoded or attempt != len(rows) - 1:
                            raise ValueError('decoded action was changed or unnecessary additional model attempt occurred')
                        selected = decoded
                if selected != logged[key]['action']:
                    raise ValueError('decoded model choice differs from actions.jsonl')
                paired += 1
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f'Decision trace {key}: {exc}')
        return {'decision_groups': len(groups), 'decoded_action_pairs': paired, 'idle_action_pairs': idle_paired,
                'decision_model_responses': sum('response' in row for row in model_rows)}, errors
    except (KeyError, TypeError, ValueError) as exc:
        return {'decision_groups': len(groups), 'decoded_action_pairs': 0, 'idle_action_pairs': 0,
                'decision_model_responses': sum(isinstance(row, dict) and 'response' in row for row in model_rows)}, [*errors, f'Malformed decision evidence: {exc}']


def audit_execution_receipts(run_dir, frozen, committed_round, observations, advice):
    """Check stored lifecycle/API evidence; reservations are not called responses."""
    errors = []
    report = {'reserved_requests': 0, 'recorded_model_responses': 0, 'measured_rounds': 0,
              'unpaired_reserved_requests': None, 'api_billing_verified': False}
    driver = _read(run_dir / 'driver_latest.json')
    if driver.get('ok') is not True or driver.get('ray_shutdown') is not True or driver.get('completed_steps') != committed_round:
        errors.append('Official driver did not confirm committed steps and clean Ray shutdown')
    if driver.get('version') != VERSION or driver.get('mode') != frozen.get('mode') or driver.get('source_manifest') != frozen.get('code_manifest'):
        errors.append('Official driver identity differs from frozen experiment')
    receipts = [_read(path) for path in sorted(run_dir.glob('controller-*.json'))]
    if not receipts:
        errors.append('No per-invocation controller receipts')
    identifiers = set()
    committed = 0
    for receipt in receipts:
        identifier = receipt.get('invocation_id')
        if not identifier or identifier in identifiers:
            errors.append('Duplicate or missing controller invocation identity')
        identifiers.add(identifier)
        if (receipt.get('version') != VERSION or receipt.get('mode') != frozen.get('mode')
                or receipt.get('run_id') != frozen.get('record', {}).get('run_id')
                or receipt.get('source_manifest') != frozen.get('code_manifest')
                or receipt.get('model_settings') != frozen.get('request_settings')
                or receipt.get('clean_commit') is not True or receipt.get('ray_shutdown') is not True
                or receipt.get('status') not in ('checkpoint', 'complete')):
            errors.append('Controller receipt is failed, uncommitted, or from a different run/version')
        measured = receipt.get('measured_rounds')
        requested = receipt.get('requested_steps')
        requests = receipt.get('requests')
        if type(measured) is not int or measured < 0 or measured != requested or type(requests) is not int or requests < 0:
            errors.append('Invalid controller round/request accounting')
            continue
        committed += measured
        if receipt.get('committed_steps') != committed:
            errors.append('Controller chunks overlap, omit, or reorder committed rounds')
        report['measured_rounds'] += measured
        report['reserved_requests'] += requests
        if frozen.get('mode') == 'llm':
            before = receipt.get('budget_before', {}).get('requests')
            after = receipt.get('budget_after', {}).get('requests')
            if type(before) is not int or type(after) is not int or after - before != requests:
                errors.append('LLM reserved-request count differs from stored API ledger summary delta')
        elif requests != 0 or receipt.get('budget_before') is not None or receipt.get('budget_after') is not None:
            errors.append('Scripted validation contains production API accounting')
    if committed != committed_round:
        errors.append('Per-invocation measured rounds do not sum to committed round count')
    model_rows = []
    for path in sorted((run_dir / 'agents').rglob('decisions.jsonl')):
        model_rows.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line)
    report['recorded_model_responses'] = sum('response' in row for row in model_rows)
    if frozen.get('mode') == 'llm':
        path = run_dir / 'actions.jsonl'
        actions = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line] if path.is_file() else []
        state = _read(run_dir / 'world.json')
        submissions = [e for e in state.get('events', []) if e.get('kind') == 'action_submitted']
        decisions, decision_errors = audit_decision_traces(model_rows, observations, actions, committed_round, submissions)
        report.update(decisions)
        errors.extend(decision_errors)
    report['recorded_model_responses'] += sum('response' in row for row in advice)
    report['unpaired_reserved_requests'] = report['reserved_requests'] - report['recorded_model_responses']
    if frozen.get('mode') == 'llm':
        if report['recorded_model_responses'] == 0:
            errors.append('LLM-labelled run has no recorded real model responses')
        if report['unpaired_reserved_requests'] != 0:
            errors.append('Request reservations and saved responses differ; retain failed/unknown reservations, cannot certify complete response evidence')
    elif report['recorded_model_responses']:
        errors.append('Scripted run contains model-response evidence')
    return report, errors


def verify_run(run_dir, root=None):
    """Read a committed official run without modifying any run evidence."""
    from policy_runtime.checkpoints import validate_commit
    from policy_v3.runtime import MODEL_SETTINGS, code_manifest
    run_dir = Path(run_dir)
    verifier_root = Path(__file__).resolve().parents[1]
    root = Path(root).resolve() if root is not None else verifier_root
    errors = []
    frozen = None
    result = {'status': 'failed', 'passed': False, 'spec_version': VERSION, 'mode': 'unknown',
              'verification_scope': 'committed_run', 'independently_recomputed': {}, 'replay_hash': None}
    try:
        if (run_dir / 'partial_failure.json').exists():
            errors.append('Partial failure evidence is present; not a clean committed attempt')
        committed = validate_commit(run_dir)
        frozen = _read(run_dir / 'run_config.json')
        state = _read(run_dir / 'world.json')
        if frozen.get('version') != VERSION:
            errors.append('Frozen configuration is not V3')
        if frozen.get('code_manifest') != code_manifest(root):
            errors.append('Current source differs from the frozen source manifest')
        if root != verifier_root:
            # A corrected independent verifier can audit archived runs only
            # while the simulation/adapter dependencies remain byte-identical.
            archived = {r['path']: r['sha256'] for r in code_manifest(root)}
            current = {r['path']: r['sha256'] for r in code_manifest(verifier_root)}
            required = [p for p in current if
                        (p.startswith(('policy_v3/', 'policy_mve/', 'custom/')) and p != 'policy_v3/verify.py')
                        or p in ('tools/v3_driver.py', 'tools/run_v3.py', 'tools/smoke_budget.py')]
            if any(archived.get(p) != current[p] for p in required):
                errors.append('Archived simulation dependencies differ from the current replay implementation')
        if frozen.get('request_settings') != MODEL_SETTINGS:
            errors.append('Model settings differ from frozen V3 specification')
        if frozen.get('mode') not in ('scripted', 'llm'):
            errors.append('Official run mode must be scripted or llm')
        if any(state.get(k) != frozen.get(k) for k in ('seed', 'horizon', 'scenario')):
            errors.append('State identity differs from frozen configuration')
        if state.get('round') != committed.get('round'):
            errors.append('State round differs from committed round')
        path = run_dir / 'observations.jsonl'
        observations = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]
        advice_path = run_dir / 'advice.jsonl'
        advice = [json.loads(line) for line in advice_path.read_text(encoding='utf-8').splitlines() if line] if advice_path.exists() else []
        errors.extend(audit_advice_inputs(advice, observations))
        execution_evidence, execution_errors = audit_execution_receipts(run_dir, frozen, committed['round'], observations, advice)
        errors.extend(execution_errors)
        state_result = verify_state(state, _read(run_dir / 'metrics.json'), observations)
        result.update(state_result)
        errors.extend(state_result['errors'])
        result.update(mode=frozen.get('mode'), execution_mode=frozen.get('mode'),
                      source_manifest_sha256=_hash(frozen.get('code_manifest')),
                      full_horizon=state.get('round') == state.get('horizon'), committed_round=committed['round'],
                      execution_evidence=execution_evidence,
                      run_id=frozen.get('record', {}).get('run_id'),
                      verification_scope='committed_official_run_event_accounting_and_action_replay')
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, ImportError) as exc:
        errors.append(f'Committed-run validation failed: {type(exc).__name__}: {exc}')
    result.update(status='passed' if not errors else 'failed', passed=not errors, errors=errors)
    result['frozen_source_root'] = str(root)
    result['independent_verifier_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['formal_analysis_eligible'] = not errors and result.get('mode') == 'llm' and result.get('full_horizon') is True
    return result
