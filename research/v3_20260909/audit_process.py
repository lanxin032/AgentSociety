"""Post-run, descriptive process audit. This script never imports the simulator.

Use repeatable --run-dir arguments and a new --output directory.  Inputs are
read-only; input and script hashes accompany JSON and Chinese text summaries.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

AUDIT_VERSION = 'v3-process-audit-1.0'
COMMUNICATION = {'request_coordination', 'reply_coordination', 'query_status', 'reply_status', 'report_status',
                 'confirm_joint_task', 'raise_objection', 'withdraw_joint'}
TERMINAL = {'project_completed', 'project_failed', 'project_cancelled'}


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line]


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def event_ref(event):
    return {'round': event['round'], 'event_index': event['event_index'], 'kind': event['kind']}


def audit_run(run_dir):
    run_dir = Path(run_dir).resolve()
    required = ['world.json', 'observations.jsonl', 'actions.jsonl', 'run_config.json']
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        raise ValueError(f'Missing required saved evidence in {run_dir}: {missing}')
    world, config = read_json(run_dir / 'world.json'), read_json(run_dir / 'run_config.json')
    if world.get('spec_version') != 'policy-v3-3.0':
        raise ValueError('Only exact V3 world evidence is accepted')
    observations, actions = read_lines(run_dir / 'observations.jsonl'), read_lines(run_dir / 'actions.jsonl')
    input_hashes = {name: file_hash(run_dir / name) for name in required}
    events, tickets = world['events'], world['tickets']
    projects, tasks = world['projects'], world['tasks']
    opportunities = world['opportunities']
    end = world['round']
    warnings = []
    if config.get('mode') == 'scripted':
        warnings.append('这些是脚本流程证据，不是模型自主行为或正式实验效应。')
    if end != world['horizon']:
        warnings.append('观察窗口尚未完成；等待、项目持续时间及未解决状态按当前检查点截尾。')
    observed = {tool: {} for tool in 'ABC'}
    first_ticket_seen = defaultdict(dict)
    task_completion_seen = {}
    observation_keys = set()

    def mark(tool, oid, row, evidence):
        if oid not in opportunities or opportunities[oid]['tool'] != tool:
            warnings.append(f'无法解析实际可见机会：{tool}/{oid}；未将其计入已观察分子。')
            return
        entry = observed[tool].setdefault(oid, {'opportunity': oid, 'first_round': row['round'],
            'actors': set(), 'observation_count': 0, 'evidence_fields': set()})
        entry['first_round'] = min(entry['first_round'], row['round'])
        entry['actors'].add(row['actor_id'])
        # One observation, possibly both a topic and an action, counts only once.
        entry.setdefault('_seen', set()).add((row['round'], row['actor_id']))
        entry['observation_count'] = len(entry['_seen'])
        entry['evidence_fields'].add(evidence)

    for row in observations:
        key = (row['round'], row['actor_id'])
        if key in observation_keys:
            warnings.append(f'重复观察记录：round={key[0]}, actor={key[1]}；唯一机会不会重复计数。')
        observation_keys.add(key)
        obs = row['observation']
        if obs.get('round') != row['round'] or obs.get('actor_id') != row['actor_id']:
            raise ValueError('Observation wrapper identity mismatch')
        for ticket in obs.get('visible_tickets', []):
            first_ticket_seen[ticket['id']].setdefault(str(row['actor_id']), row['round'])
            if row['actor_id'] == 1 and ticket.get('a_offered') is True:
                mark('A', ticket.get('a_opportunity'), row, 'visible_tickets.a_offered')
        topic_rows = obs.get('topics', obs.get('visible_topics', []))
        topic_map = {topic['id']: topic for topic in topic_rows}
        for topic in topic_rows:
            if topic.get('c_offered') is True:
                mark('C', topic.get('opportunity'), row, 'topics.c_offered')
        for action in obs.get('available_actions', []):
            params = action.get('params', {})
            if action['kind'] == 'request_coordination' and params.get('mode') == 'joint':
                ticket = tickets.get(action['target'])
                mark('B', ticket.get('b_opportunity') if ticket else None, row, 'available_actions.joint_request')
            elif action['kind'] == 'propose_project' and params.get('mode') == 'structured':
                topic = topic_map.get(action['target'])
                if topic is None:
                    warnings.append('结构专项候选缺少同次观察的主题机会标识；未推测补齐。')
                else:
                    mark('C', topic.get('opportunity'), row, 'available_actions.structured_proposal')
        for object_view in [*obs.get('visible_tickets', []), *obs.get('projects', [])]:
            for view in object_view.get('tasks', []):
                if view.get('state') == 'completed':
                    task_completion_seen.setdefault((view['id'], row['actor_id']), row['round'])

    expected_keys = {(r, actor) for r in range(end) for actor in (1, 2, 3, 4)}
    if observation_keys != expected_keys:
        warnings.append(f'观察记录不完整：缺少{len(expected_keys - observation_keys)}个角色—轮，额外{len(observation_keys - expected_keys)}个；observed仅计已有证据。')
    action_keys = {(row['round'], row['actor_id']) for row in actions}
    if action_keys != expected_keys or len(action_keys) != len(actions):
        warnings.append('动作文件存在角色—轮缺失或重复；不把缺失记录推断为拒绝、未采用或等待。')
    completed = {tool: set() for tool in 'ABC'}
    for event in events:
        if event['kind'] == 'routed' and event.get('recommendation_used'):
            completed['A'].add(tickets[event['ticket']]['a_opportunity'])
    for ticket in tickets.values():
        oid = ticket.get('b_opportunity')
        if oid and opportunities[oid]['adopted'] and world['issues'][ticket['issue']]['resolved'] is not None:
            completed['B'].add(oid)
    for project in projects.values():
        if project['mode'] == 'structured' and project['state'] == 'completed':
            completed['C'].add(project['opportunity'])
    tool_summary = {}
    for tool in 'ABC':
        pool = {oid for oid, value in opportunities.items() if value['tool'] == tool}
        offered = {oid for oid in pool if opportunities[oid]['offered_ever']}
        used = {oid for oid in pool if opportunities[oid]['adopted']}
        visible = set(observed[tool])
        if not visible <= offered or not used <= visible:
            warnings.append(f'{tool}的提供、看见、采用记录未形成完整包含链；请检查逐机会证据，不强行配平。')
        tool_summary[tool] = {'eligible': len(pool), 'offered': len(offered), 'observed': len(visible),
            'used': len(used), 'completed': len(completed[tool]),
            'offered_per_eligible': ratio(len(offered), len(pool)), 'observed_per_offered': ratio(len(visible), len(offered)),
            'used_per_observed': ratio(len(used), len(visible)), 'completed_per_used': ratio(len(completed[tool]), len(used)),
            'eligible_ids': sorted(pool), 'offered_ids': sorted(offered), 'observed_ids': sorted(visible),
            'used_ids': sorted(used), 'completed_ids': sorted(completed[tool])}
    for values in observed.values():
        for entry in values.values():
            entry.pop('_seen', None)
            entry['actors'] = sorted(entry['actors'])
            entry['evidence_fields'] = sorted(entry['evidence_fields'])

    # Preserve event times; round indexes denote synthetic rounds, not days.
    message_rows = []
    for message in world['messages'].values():
        delivered = message['delivered_round']
        message_rows.append({'id': message['id'], 'object': message['object'], 'kind': message['kind'],
            'sender': message['sender'], 'recipient': message['recipient'], 'created_round': message['created_round'],
            'planned_delivery_round': message['deliver_round'], 'delivered_round': delivered,
            'delay_or_censor_rounds': (delivered if delivered is not None else end) - message['created_round'],
            'censored': delivered is None, 'free_service': message.get('free_service', False)})
    routing_rows = []
    for tid, ticket in tickets.items():
        routing = [e for e in events if e['kind'] == 'routed' and e['ticket'] == tid]
        issue = world['issues'].get(ticket['issue'], {})
        required_task_ids = issue.get('tasks')
        required_actors = set()
        arrival_reason = None
        if not isinstance(required_task_ids, list) or not required_task_ids:
            arrival_reason = '客观问题缺少必要任务清单；无法识别必要办理部门。'
        else:
            for task_id in required_task_ids:
                actor = tasks.get(task_id, {}).get('actor')
                if type(actor) is not int or actor not in (2, 3):
                    arrival_reason = '必要任务缺失或任务办理部门不是有效的2/3号部门。'
                    break
                required_actors.add(actor)
        seen = {str(actor): first_ticket_seen[tid].get(str(actor)) for actor in sorted(required_actors)}
        any_arrival = min((r for r in seen.values() if r is not None), default=None) if arrival_reason is None else None
        all_arrival = max(seen.values()) if arrival_reason is None and seen and all(r is not None for r in seen.values()) else None
        reported = ticket['reported']
        required_observation_keys = {(r, actor) for r in range(reported, end) for actor in required_actors}
        missing_required_observations = sorted(required_observation_keys - observation_keys)
        if missing_required_observations and arrival_reason is None:
            # Missing earlier observations prevent identification of the true first arrival,
            # even when a later saved observation contains the ticket.
            arrival_reason = '必要部门观察记录缺失；不能确认首次到达轮次，保留已保存的首次看见时点供核查。'
            any_arrival = all_arrival = None
        routing_rows.append({'ticket': tid, 'reported_round': ticket['reported'],
            'routing_events': [{**event_ref(e), 'department': e['department'], 'recommendation_used': e['recommendation_used'],
                                'responsibility_match_audit': e['initially_matched']} for e in routing],
            'first_observed_by_department': {k: v for k, v in first_ticket_seen[tid].items() if k in ('2', '3')},
            'required_departments_audit_only': sorted(required_actors), 'required_department_first_seen': seen,
            'first_effective_handler_arrival': any_arrival,
            'all_required_handlers_first_seen_round': all_arrival,
            'first_effective_handler_delay_or_censor_rounds': ((any_arrival if any_arrival is not None else end) - reported) if arrival_reason is None else None,
            'all_required_handlers_delay_or_censor_rounds': ((all_arrival if all_arrival is not None else end) - reported) if arrival_reason is None else None,
            'first_effective_handler_arrival_censored': any_arrival is None if arrival_reason is None else None,
            'all_required_handlers_arrival_censored': all_arrival is None if arrival_reason is None else None,
            'censor_round': end, 'arrival_missing_reason': arrival_reason,
            'missing_required_observation_keys': [{'round': r, 'actor_id': actor} for r, actor in missing_required_observations],
            'arrival_definition': '至少一个客观必要办理部门首次在保存观察中实际看到该工单的轮次；全体到达取各必要部门首次看见轮次的最大值。必要部门仅在事后由问题任务清单及任务actor确定，不进入模型输入。至少一个到达、全体到达、问题解决分别计量。'})

    b_kinds = {'coordination_requested', 'joint_flow_requested', 'joint_task_confirmed', 'joint_board_activated', 'joint_withdrawn', 'coordination_objection'}
    b_events = [e for e in events if e['kind'] in b_kinds and e.get('ticket', e.get('object')) in tickets]
    b_results = []
    for event in events:
        if event['kind'] != 'action_result':
            continue
        action = event['action']
        target = action['target']
        scope = tasks.get(target, {}).get('object', world['messages'].get(target, {}).get('object', target))
        if scope in tickets and action['kind'] in (COMMUNICATION | {'work'}):
            b_results.append(event)
    costs = [e for e in events if e['kind'] == 'resource_spent']
    b_costs = [e for e in costs if e.get('object_id') in tickets and (e.get('reason') in COMMUNICATION
               or e.get('reason') in {'joint_setup', 'shared_record_maintenance'}
               or e.get('reason', '').removeprefix('decision:') in COMMUNICATION)]
    # Reply targets may be message IDs; use the saved message's object as scope.
    for event in costs:
        message = world['messages'].get(event.get('object_id'))
        if message and message['object'] in tickets and event not in b_costs and event.get('reason', '').removeprefix('decision:') in COMMUNICATION:
            b_costs.append(event)
    handoffs = []
    task_done = {e['task']: e for e in events if e['kind'] == 'task_completed'}
    for task in tasks.values():
        if task['object'] not in tickets:
            continue
        for prerequisite in task['prerequisites']:
            predecessor = task_done.get(prerequisite)
            received = task_completion_seen.get((prerequisite, task['actor']))
            performed = task_done.get(task['id'])
            handoffs.append({'object': task['object'], 'task': task['id'], 'actor': task['actor'], 'prerequisite': prerequisite,
                'prerequisite_physical_completion_round': predecessor['round'] if predecessor else None,
                'prerequisite_first_seen_by_actor_round': received,
                'dependent_task_completion_round': performed['round'] if performed else None,
                'handoff_wait_from_physical_completion': received - predecessor['round'] if received is not None and predecessor else None,
                'not_yet_seen_censored': predecessor is not None and received is None,
                'not_seen_followup_rounds': end - predecessor['round'] if predecessor and received is None else None})

    project_rows = []
    c_event_kinds = {'project_proposed', 'project_lead_confirmed', 'project_task_confirmed', 'project_board_activated',
        'project_diagnosed', 'project_plan_drafted', 'project_review_package_created', 'project_task_requested',
        'project_budget_approved', 'project_budget_denied', 'project_adjusted', *TERMINAL}
    for pid, project in projects.items():
        timeline = [e for e in events if (e['kind'] in c_event_kinds and e.get('project') == pid)
                    or (e['kind'] in ('task_reviewed', 'task_completed') and e.get('object') == pid)]
        terminal = next((e for e in timeline if e['kind'] in TERMINAL), None)
        outcome_round = terminal['round'] if terminal else end
        project_costs = [e for e in costs if e.get('object_id') == pid
            or tasks.get(e.get('object_id'), {}).get('object') == pid
            or world['messages'].get(e.get('object_id'), {}).get('object') == pid
            or (e.get('object_id') == project['topic'] and e['round'] == project['created']
                and e.get('reason') in ('propose_project', 'decision:propose_project'))]
        project_rows.append({'project': pid, 'mode': project['mode'], 'opportunity': project['opportunity'],
            'created_round': project['created'], 'terminal_state': project['state'] if terminal else None,
            'terminal_round': terminal['round'] if terminal else None,
            'duration_or_censor_rounds': outcome_round - project['created'], 'censored': terminal is None,
            'timeline': timeline,
            'action_attempts': [e for e in events if e['kind'] == 'action_result' and
                (e['action']['target'] == pid or tasks.get(e['action']['target'], {}).get('object') == pid
                 or world['messages'].get(e['action']['target'], {}).get('object') == pid
                 or (e['action']['kind'] == 'propose_project' and e['action']['target'] == project['topic'] and e['round'] == project['created']))],
            'spent_labor': sum(e['labor'] for e in project_costs),
            'spent_capital': sum(e['capital'] for e in project_costs), 'cost_events': project_costs,
            'note': '零持续时间表示同一编号轮次内；并不等于现实耗时为零。撤项不算结构治理成功。'})
    matched = [e for e in events if e['kind'] == 'routed']
    result = {'run_dir': str(run_dir), 'run_id': config.get('record', {}).get('run_id'),
        'mode': config.get('mode', 'unknown'), 'completed_rounds': end, 'horizon': world['horizon'],
        'scenario': world['scenario'], 'input_sha256': input_hashes, 'tools': tool_summary,
        'observed_opportunity_evidence': observed,
        'A': {'routes': routing_rows, 'routing_match_rate': ratio(sum(e['initially_matched'] for e in matched), len(matched)),
              'routing_without_recommendation_count': sum(not e['recommendation_used'] for e in matched),
              'subjective_rejection_or_modification': None,
              'interpretation': '未使用建议只记录客观行为；不由此推断主观拒绝或修改。A完成表示采用建议派单，不表示问题解决。'},
        'B': {'events': b_events, 'event_counts': dict(Counter(e['kind'] for e in b_events)), 'handoffs': handoffs,
              'action_results': b_results,
              'business_nonimplementation': [e for e in b_results if e['status'] == 'business_rejected'],
              'necessary_task_completion_events': [e for e in events if e['kind'] == 'task_completed' and e.get('object') in tickets],
              'coordination_labor': sum(e['labor'] for e in b_costs), 'coordination_cost_events': b_costs,
              'cost_scope': '仅个案联系、回复、联合建立/确认/退出和维护劳动及相应决策劳动；不混入C项目内部协同。'},
        'C': {'projects': project_rows, 'interpretation': '阶段时间为事件记录；有确认/审批不意味着实际履约或工程成功。'},
        'messages': {'rows': message_rows, 'delivered': sum(not m['censored'] for m in message_rows),
                     'undelivered_censored': sum(m['censored'] for m in message_rows)},
        'warnings': sorted(set(warnings)), 'causal_effect_estimate': False,
        'definitions': {'eligible': '世界中已产生的工具适用机会', 'offered': '该机会在适用时曾满足提供门槛',
            'observed': '保存的角色观察中实际包含强化工具标识或可选行动；按机会去重',
            'used': '工具采用事件/状态', 'completed': 'A采用建议完成派单；B采用后的必要个案任务全部实际完成；C通过结构工程验收',
            'time_unit': '合成轮次索引；消息延迟和阶段持续时间取记录索引之差，非现实工作日',
            'zero_denominator': 'null：缺失或不适用；不记为0'}}
    # The collection must be stable during this bounded read-only audit.
    if any(file_hash(run_dir / name) != checksum for name, checksum in input_hashes.items()):
        raise RuntimeError('Input changed while being audited; use a recovered clean checkpoint')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', action='append', required=True)
    parser.add_argument('--output', required=True, help='New output directory')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError('Output must be new; existing audit evidence will not be overwritten')
    run_dirs = [Path(path).resolve() for path in args.run_dir]
    if len(set(run_dirs)) != len(run_dirs):
        raise ValueError('Duplicate run directory would double-count evidence')
    runs = [audit_run(path) for path in run_dirs]
    document = {'audit_version': AUDIT_VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'script_sha256': file_hash(__file__), 'runs': runs,
        'interpretation': '事后描述性过程核查。不是正式比较、因果中介分析或现实政策效果估计。'}
    lines = ['V3 事后过程审计', '', document['interpretation'], '']
    for run in runs:
        lines.append(f"{run['run_id'] or run['run_dir']}｜mode={run['mode']}｜{run['completed_rounds']}/{run['horizon']}轮")
        for tool, counts in run['tools'].items():
            lines.append(f"  {tool}：适用{counts['eligible']}、提供{counts['offered']}、实际看见{counts['observed']}、采用{counts['used']}、完成{counts['completed']}")
        lines.append(f"  消息：已送达{run['messages']['delivered']}，未送达截尾{run['messages']['undelivered_censored']}；个案协调劳动{run['B']['coordination_labor']:.3f}")
        lines.extend('  注意：' + warning for warning in run['warnings'])
        lines.append('')
    output.mkdir(parents=True)
    (output / 'process_audit.json').write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'summary.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
