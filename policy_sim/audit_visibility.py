"""Independent receipt-based checks for raw business observations.

The exported, replayed state is the authority for receipt provenance. This module
never invokes the observation builder. Global task status is deliberately not a
receipt: a legally received pending task may have since been cancelled privately.
This checks business objects/messages, not material-service or candidate policy.
"""
import json

from .spec import PUBLIC_RULES


def _same(actual, expected, path):
    # JSON round trips turn integer department keys into strings.
    if json.dumps(actual, sort_keys=True, ensure_ascii=False) != json.dumps(expected, sort_keys=True, ensure_ascii=False):
        raise ValueError('visibility: ' + path)


def _require(condition, path):
    if not condition:
        raise ValueError('visibility: ' + path)


def _receipts(view, knowledge, oid, path, visible_tasks=None):
    records = [r for r in knowledge['records'].values() if r['object'] == oid]
    tasks = [t for t in knowledge['tasks'].values() if t['object'] == oid]
    if 'received_records' in view:
        _same(view['received_records'], records, path + '.received_records provenance')
    if 'tasks' in view:
        _same(view['tasks'], visible_tasks if visible_tasks is not None else tasks, path + '.tasks provenance')
    return records, tasks


def _project(view, state, actor, knowledge):
    oid = view['id']
    path = 'projects.' + oid
    _require(oid in knowledge['objects'] and oid in state['projects'], path + ' access')
    actual = state['projects'][oid]
    requested = actual.get('requested') or {}

    # The expected revision comes from receipts (never the audited view), so a
    # tampered view revision cannot alter which tasks are expected.
    revisions_probe = [t for t in knowledge['tasks'].values() if t['object'] == oid]
    revisions = [t['revision'] for t in revisions_probe]
    revisions += [r['data'].get('revision', 0) for r in knowledge['records'].values() if r['object'] == oid]
    expected_revision = actual['revision'] if actor == 4 else max(revisions, default=0)

    def dispatched(task):
        # Same dispatch rule as the observation builder: a pending task of
        # another actor is visible only after its request went out for the
        # task's own revision (stale-revision and completed tasks stay).
        return (task['actor'] == actor or task['state'] != 'pending'
                or task['revision'] != expected_revision
                or task['actor'] in requested.get(task['kind'], []))

    all_tasks = [t for t in knowledge['tasks'].values() if t['object'] == oid]
    visible_tasks = [t for t in all_tasks if dispatched(t)]
    records, tasks = _receipts(view, knowledge, oid, path, visible_tasks=visible_tasks)
    revisions = [t['revision'] for t in tasks]
    revisions += [r['data'].get('revision', 0) for r in records]
    revision = actual['revision'] if actor == 4 else max(revisions, default=0)
    expected = {
        'id': oid, 'topic': actual['topic'], 'mode': actual['mode'], 'owner': 4,
        'joint_required': actual['b_required'], 'joint_registered': actual['b_registered'],
        'revision': revision, 'received_records': records, 'tasks': visible_tasks,
    }
    active = actual['b_registered'] and actual['mode'] == 'structured' and actual.get('activated_round') is not None
    expected['joint_ready'] = not actual['b_required'] or bool(active and any(
        r['kind'] == 'project_activation' and r['data'].get('revision') == actual['revision']
        for r in records))
    diagnoses = [r for r in records if r['kind'] == 'project_diagnosis']
    expected['evidence'] = diagnoses[-1]['data']['evidence'] if diagnoses else []
    builds = [t for t in tasks if t['kind'] == 'implement_project' and t['revision'] == revision]
    completed = [t for t in builds if t['state'] == 'completed']
    built = len(builds) == len(completed) == 2
    expected['construction'] = 'built' if built else 'in_progress' if completed else 'unknown'
    expected['built_at'] = max(t['completed_round'] for t in builds) if built else None
    commissions = [r['data'] for r in records if r['kind'] == 'commissioning_result' and r['data']['revision'] == revision]
    expected.update(physical='unknown', effective_at=None)
    if commissions:
        commission = commissions[-1]
        expected['effective_at'] = commission['effective_at']
        expected['physical'] = ('effective' if state['round'] >= commission['effective_at'] else 'commissioned_pending_effect') if commission['success'] else 'commissioning_failed'
    terminals = [r for r in records if r['kind'] == 'project_terminal']
    expected['administrative'] = 'unknown'
    expected['accepted_at'] = None
    if terminals:
        terminal = terminals[-1]
        expected['administrative'] = 'accepted' if terminal['data']['state'] == 'completed' else terminal['data']['state']
        if terminal['data']['state'] == 'completed':
            expected['accepted_at'] = terminal['created_round']
    reviews = {t['actor']: t['opinion'] for t in tasks if t['kind'] == 'review_project' and t['revision'] == revision and t['state'] == 'completed'}
    if actor == 4:
        for key in ('administrative', 'state', 'lead_confirmed', 'plan', 'budget_requested', 'budget_approved', 'ready_round', 'facilities', 'requested', 'paused'):
            expected[key] = actual[key]
        expected['received_reviews'] = reviews
    if actual['b_registered']:
        expected['own_confirmed'] = actor in actual['confirmed_by']
        expected['project_package'] = {
            'participants': [2, 3, 4], 'template': PUBLIC_RULES['project_template'],
            'received_review_departments': sorted(reviews),
            'note': '仅整理已有授权材料及拟案任务，未收到的意见和进度仍未知。',
        }
    _same(sorted(view), sorted(expected), path + ' field boundary')
    for key, value in expected.items():
        _same(view[key], value, path + '.' + key)


def audit_visibility(observation, state):
    """Raise ValueError on a raw observation inconsistent with lawful receipts.

    ``state`` must be the exported world at the observation's round, preferably
    independently replayed by the verifier. Both arguments remain unchanged.
    Material projections, available actions and the integrity of the replayed
    state itself remain the responsibility of their existing audit checks.
    """
    try:
        actor = observation['actor_id']
        _require(type(actor) is int and actor in (1, 2, 3, 4), 'actor_id')
        _same(observation['round'], state['round'], 'round')
        knowledge = state['knowledge'][str(actor)]
        for record in knowledge['records'].values():
            _require(record['created_round'] <= state['round'], 'future receipt')
            _same(record, state['records'].get(record['id']), 'record registry provenance')
        project_ids = [p['id'] for p in observation['projects']]
        _same(project_ids, [pid for pid in state['projects'] if pid in knowledge['objects']], 'project access set')
        for project in observation['projects']:
            _project(project, state, actor, knowledge)
        ticket_ids = [t['id'] for t in observation['visible_tickets']]
        _same(ticket_ids, [tid for tid in state['tickets'] if actor in (1, 4) or tid in knowledge['objects']], 'ticket access set')
        for ticket in observation['visible_tickets']:
            oid = ticket['id']
            records, _ = _receipts(ticket, knowledge, oid, 'tickets.' + oid)
            _same(ticket['closed'], any(r['kind'] == 'issue_closed' for r in records), 'tickets.' + oid + '.closed')
            if 'shared_records' in ticket:
                _same(ticket['shared_records'], [r for r in records if r['kind'] in ('task_completed', 'joint_confirmation')], 'tickets.' + oid + '.shared_records')
        inbox = []
        for mid in knowledge['inbox']:
            message = state['messages'][mid]
            _require(message['recipient'] == actor and message['delivered_round'] is not None and message['delivered_round'] <= state['round'], 'inbox delivery provenance')
            inbox.append({k: message[k] for k in ('id', 'sender', 'object', 'kind', 'created_round', 'delivered_round', 'replied', 'payload')})
        _same(observation['inbox'], inbox, 'inbox provenance')
        sent = [{k: m[k] for k in ('id', 'recipient', 'object', 'kind', 'created_round', 'payload')}
                for m in state['messages'].values() if m['sender'] == actor]
        _same(observation['sent_messages'], sent, 'sent_messages provenance')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('visibility: malformed observation or state') from exc
