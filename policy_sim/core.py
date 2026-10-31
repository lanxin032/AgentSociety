"""Finite business world: partial information, communication and full projects.

No network or model calls. Only observe() is a model-facing information boundary.
Snapshots and audit events contain privileged physical state and must stay private.
"""
from collections import deque
from copy import deepcopy
import hashlib
import json
import math
from .interface import decorate_observation
from .project_lifecycle import ProjectLifecycle, activate_due_projects
from .materials import projection, lawful_sources, read_materials, service_inputs, topic_facts, represented_ids, source_index
from .spec import ACTORS, ACTION_PARAM_KEYS, ALLOWED_KINDS, COMMUNICATION_KINDS, DEFAULT_CONFIG, ENVIRONMENTS, PUBLIC_RULES, FINITE_PUBLIC_RULES, SCHEMA_VERSION, SPEC_VERSION

def _action(kind, target=None, **params):
    return {'kind': kind, 'target': target, 'params': params, 'reason': '依据本人已获知材料选择'}

def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

class PolicyWorld:

    def __init__(self, policy='111', seed=3001, horizon=None, config=None, scenario=None, workload_mode='finite'):
        if policy not in {f'{i:03b}' for i in range(8)}:
            raise ValueError('policy must be a three-bit endpoint label')
        if type(seed) is not int:
            raise ValueError('seed must be an integer')
        if workload_mode not in ('finite',):
            raise ValueError('unknown workload_mode')
        self.workload_mode = workload_mode
        (self.policy, self.seed) = (policy, seed)
        self.scenario = deepcopy(scenario or {})
        if not isinstance(self.scenario, dict):
            raise ValueError('scenario must be an object')
        if horizon is not None or self.scenario.get('horizon') is not None:
            raise ValueError('finite workload requires horizon=None')
        self.horizon = None
        self.scenario.setdefault('id', 'endpoint-' + policy)
        self.scenario.setdefault('family', 'endpoint')
        self.scenario.setdefault('horizon', None)
        self.scenario.setdefault('q', {tool: float(policy[i]) for (i, tool) in enumerate('ABC')})
        self.scenario.setdefault('schedule', [])
        self.scenario.setdefault('environment', 'baseline')
        self.config = deepcopy(DEFAULT_CONFIG)
        environment = self.scenario['environment']
        if isinstance(environment, str):
            if environment not in ENVIRONMENTS:
                raise ValueError('unknown environment')
            self.config.update(ENVIRONMENTS[environment])
        elif isinstance(environment, dict):
            name = environment.get('id', environment.get('name', 'baseline'))
            if name not in ENVIRONMENTS:
                raise ValueError('unknown environment')
            self.config.update(ENVIRONMENTS[name])
            self.config.update(environment.get('overrides', {}))
        else:
            raise ValueError('environment must be a registered name or object')
        if config:
            self.config.update(deepcopy(config))
        if set(self.config) != set(DEFAULT_CONFIG):
            raise ValueError('unknown configuration parameter')
        for (name, value) in self.config.items():
            if name in ('zero_communication_friction', 'fewer_shared_roots'):
                if type(value) is not bool:
                    raise ValueError('boolean configuration required: ' + name)
            elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid nonnegative finite parameter: ' + name)
        for name in ('signal_window', 'signal_threshold', 'signal_cooldown', 'project_lag', 'project_steps', 'repeat_report_interval', 'shared_crew_capacity'):
            if self.config[name] < 1 or int(self.config[name]) != self.config[name]:
                raise ValueError('positive integer parameter required: ' + name)
        if self.config['project_steps'] != 2:
            raise ValueError('V3 public engineering template has exactly two construction tasks')
        for name in ('shock_probability', 'common_root_shock_probability', 'repaired_root_shock_probability'):
            if self.config[name] > 1:
                raise ValueError('probability exceeds one')
        self._validate_schedule()
        self.round = 0
        (self.events, self.pending, self.burden_by_round) = ([], {}, [])
        (self.facilities, self.issues, self.tickets, self.tasks, self.projects) = ({}, {}, {}, {}, {})
        (self.contacts, self.messages, self.records) = ([], {}, {})
        self.knowledge = {str(a): {'objects': [], 'tasks': {}, 'records': {}, 'inbox': []} for a in ACTORS}
        (self.opportunities, self.topic_episodes, self.topic_terminal) = ({}, {}, {})
        (self.service_dirty, self.service_last_attempt) = ({}, {})
        self.material_contexts = {}
        self._rebuild_indices()
        self.initial_ids = []
        self.labor = {}
        self.capital = None
        self.crew_remaining = None
        self._build()
        self._refresh_topics()

    @property
    def finite_workload(self):
        return self.workload_mode == 'finite'

    def _validate_schedule(self):

        def check_q(q):
            if not isinstance(q, dict) or set(q) != set('ABC'):
                raise ValueError('q must specify A, B and C')
            if any((type(v) not in (int, float) or not math.isfinite(v) or v not in (0, 1) for v in q.values())):
                raise ValueError('V3.2 supports binary static policies only')
        check_q(self.scenario['q'])
        schedule = self.scenario['schedule']
        if not isinstance(schedule, list):
            raise ValueError('schedule must be a list')
        if schedule:
            raise ValueError('finite workload requires a static scenario without schedule')

    @staticmethod
    def public_directory():
        return deepcopy(PUBLIC_RULES['directory'])

    def material_sources(self, actor_id):
        return lawful_sources(self, actor_id)

    def material_service_inputs(self, actor_id):
        return service_inputs(self, actor_id)

    def read_materials(self, actor_id, source_ids):
        return read_materials(self, actor_id, source_ids)

    def bind_material_context(self, actor_id, observation):
        """Bind trusted router/replay delivery evidence; never an agent action."""
        if type(actor_id) is not int or actor_id not in ACTORS or observation.get('actor_id') != actor_id or (observation.get('round') != self.round):
            raise ValueError('Material context actor/round mismatch')
        materials = observation['materials']
        if materials.get('as_of_round') != self.round:
            raise ValueError('Material context is stale')
        sources = self.material_sources(actor_id)
        indexes = materials.get('source_index', [])
        versions = {}
        for row in indexes:
            sid = row.get('source_id')
            if sid not in sources or row != source_index(sources[sid]) or sid in versions:
                raise ValueError('Material context exceeds current lawful source versions')
            versions[sid] = row['version']
        delivered = represented_ids(materials)
        if not delivered <= versions.keys():
            raise ValueError('Material context cites unavailable sources')
        self.material_contexts[str(actor_id)] = {'round': self.round, 'source_versions': versions, 'represented_ids': sorted(delivered)}

    def _random(self, *event_key):
        return int.from_bytes(hashlib.sha256(_canonical([self.seed, *event_key]).encode()).digest()[:8], 'big') / 2 ** 64

    def _q(self, tool):
        return self.scenario['q'][tool]

    def _rebuild_indices(self):
        self._indices = {'records': {}, 'tasks': {}, 'ticket_received': {},
                         'record_received': {}, 'pending_messages': deque()}
        for actor in ACTORS:
            for kind in ('records', 'tasks'):
                for key, row in self.knowledge[str(actor)][kind].items():
                    self._indices[kind].setdefault((actor, row['object']), []).append(key)
        for event in self.events:
            self._index_ticket_grant(event)
        for mid, message in self.messages.items():
            if message['delivered_round'] is None:
                self._indices['pending_messages'].append(mid)
            else:
                self._index_record_delivery(message)

    def _index_ticket_grant(self, event):
        if event['kind'] == 'routed':
            key = (event['department'], event['ticket'])
        elif event['kind'] == 'message_delivered':
            key = (event['recipient'], event['object'])
        else:
            return
        received = self._indices['ticket_received']
        received[key] = min(received.get(key, event['round']), event['round'])

    def _index_record_delivery(self, message):
        received = self._indices['record_received']
        for record in message.get('payload', {}).get('records', []):
            key = (message['recipient'], record.get('id'))
            received[key] = min(received.get(key, message['delivered_round']), message['delivered_round'])

    def _remember(self, actor, kind, key, row):
        rows = self.knowledge[str(actor)][kind]
        previous = rows.get(key)
        rows[key] = deepcopy(row)
        index = self._indices[kind]
        if previous is None:
            index.setdefault((actor, row['object']), []).append(key)
        elif previous['object'] != row['object']:
            for index_key in [index_key for index_key in index if index_key[0] == actor]:
                del index[index_key]
            for row_key, saved in rows.items():
                index.setdefault((actor, saved['object']), []).append(row_key)

    def _views_for(self, actor, kind, oid):
        rows = self.knowledge[str(actor)][kind]
        return [rows[key] for key in self._indices[kind].get((actor, oid), ())]

    def pending_message_ids(self):
        return [mid for mid in self._indices['pending_messages']
                if self.messages[mid]['deliver_round'] <= self.round]

    def _log(self, kind, **details):
        event = {'event_index': len(self.events), 'round': self.round, 'kind': kind, **deepcopy(details)}
        self.events.append(event)
        self._index_ticket_grant(event)
        return event

    def _opportunity(self, tool, target, key):
        oid = tool + ':' + key
        if oid not in self.opportunities:
            u = self._random('offer', tool, key)
            self.opportunities[oid] = {'id': oid, 'tool': tool, 'target': target, 'u': u, 'created': self.round, 'adopted': False, 'closed': False, 'offered_ever': u < self._q(tool), 'last_offered': u < self._q(tool)}
            self._log('tool_opportunity', tool=tool, opportunity=oid, target=target, u=u, q=self._q(tool), offered=u < self._q(tool))
        return oid

    def _offered(self, oid):
        item = self.opportunities.get(oid)
        return bool(item and (not item['closed']) and (item['adopted'] or item['u'] < self._q(item['tool'])))

    def _adopt(self, oid):
        item = self.opportunities[oid]
        (item['adopted'], item['offered_ever']) = (True, True)
        self._log('tool_adopted', tool=item['tool'], opportunity=oid, target=item['target'])

    def _refresh_offers(self):
        for item in self.opportunities.values():
            if item['closed'] or item['adopted']:
                continue
            offered = item['u'] < self._q(item['tool'])
            item['offered_ever'] = item['offered_ever'] or offered
            if offered != item['last_offered']:
                item['last_offered'] = offered
                self._log('tool_offer_changed', tool=item['tool'], opportunity=item['id'], q=self._q(item['tool']), u=item['u'], offered=offered)

    def _build(self):
        types = sorted(range(4), key=lambda t: self._random('district_archetype', t))
        rows = []
        for (district, archetype) in enumerate(types, 1):
            for local in range(1, 4):
                rows.append((f'F{district}-{local}', district, archetype))
        clear = set((fid for (fid, _, _) in sorted(rows, key=lambda r: self._random('wording', r[0]))[:6]))
        crosses = [fid for (fid, _, archetype) in rows if archetype in (1, 3)]
        dependent = set(sorted(crosses, key=lambda f: self._random('case_dependency', f))[:3])
        singles = [fid for (fid, _, archetype) in rows if archetype in (0, 2)]
        water = set(sorted(singles, key=lambda f: self._random('single_department', f))[:3])
        removed = min((2, 3), key=lambda a: self._random('fewer_roots_drop', a))
        for (fid, district, archetype) in rows:
            shared = archetype in (2, 3) and (not (self.config['fewer_shared_roots'] and archetype == removed))
            actors = [2, 3] if archetype in (1, 3) else [2 if fid in water else 3]
            self.facilities[fid] = {'id': fid, 'district': f'片区{district}', 'archetype': archetype, 'shared_root': shared, 'root': f'root-d{district}' if shared else 'root-' + fid, 'root_repaired': False, 'case_actors': actors, 'dependent': fid in dependent, 'clear_text': fid in clear, 'category': '供水服务异常'}
            self.initial_ids.append(self._new_issue(fid, initial=True))
        self._log('initialized', spec_version=SPEC_VERSION, schema_version=SCHEMA_VERSION, policy=self.policy, scenario=self.scenario, config=self.config, **{'workload_mode': self.workload_mode}, labor=self.labor, capital=self.capital, shared_crew_capacity=self.crew_remaining)

    def _new_issue(self, fid, initial=False):
        facility = self.facilities[fid]
        (iid, tid) = (f'I:{fid}:{self.round}', f'T:{fid}:{self.round}')
        recurrence = any((i['facility'] == fid and i['resolved'] is not None for i in self.issues.values()))
        task_ids = [f'K:{tid}:{actor}' for actor in facility['case_actors']]
        issue = {'id': iid, 'facility': fid, 'created': self.round, 'resolved': None, 'initial': initial, 'recurrence': recurrence, 'tasks': task_ids}
        self.issues[iid] = issue
        for (actor, task_id) in zip(facility['case_actors'], task_ids):
            prerequisites = [f'K:{tid}:3'] if facility['dependent'] and actor == 2 else []
            self.tasks[task_id] = {'id': task_id, 'object': tid, 'scope': 'case', 'kind': 'work', 'actor': actor, 'prerequisites': prerequisites, 'state': 'pending', 'completed_round': None, 'assigned': [], 'revision': 0, 'opinion': None}
        if facility['clear_text']:
            text = '供水泵及基础接口均需核实处理' if len(facility['case_actors']) == 2 else '供水泵无法正常运行' if facility['case_actors'] == [2] else '基础设施接口破损影响供水'
        else:
            text = '用水服务异常，附近情况不明，请有关单位核实处理'
        aid = self._opportunity('A', tid, fid + '@' + str(self.round))
        self.tickets[tid] = {'id': tid, 'issue': iid, 'facility': fid, 'district': facility['district'], 'text': text, 'category': facility['category'], 'reported': self.round, 'public_episode': f'居民记录:{fid}:{self.round}', 'lead': None, 'inspected': False, 'known_required': [], 'coordination': None, 'closed': False, 'a_opportunity': aid, 'a_called': False, 'b_opportunity': None, 'joint_participants': [], 'joint_confirmed_by': [], 'b_required': False, 'b_registered': False, 'joint_activated_round': None, 'joint_withdrawn': False, 'assigned_departments': [], 'objections': [], 'last_contact_round': self.round}
        self._contact(tid, repeat=False)
        self._log('issue_created', issue=iid, ticket=tid, facility=fid, initial=initial, recurrence=recurrence)
        return iid

    def _contact(self, tid, repeat):
        ticket = self.tickets[tid]
        contact = {'id': f'contact-{len(self.contacts) + 1}', 'ticket': tid, 'facility': ticket['facility'], 'district': ticket['district'], 'category': ticket['category'], 'public_episode': ticket['public_episode'], 'reported': self.round, 'repeat': repeat}
        self.contacts.append(contact)
        ticket['last_contact_round'] = self.round
        if repeat:
            self._log('repeat_contact', **contact)

    def _topics(self):
        groups = {}
        for contact in self.contacts:
            key = contact['district'] + '|' + contact['category']
            row = groups.setdefault(key, {'id': key, 'district': contact['district'], 'category': contact['category'], 'episodes': set(), 'facilities': set()})
            row['episodes'].add(contact['public_episode'])
            row['facilities'].add(contact['facility'])
        result = []
        for key in sorted(groups):
            group = groups[key]
            if len(group['episodes']) < self.config['signal_threshold']:
                continue
            active = any((p['topic'] == key and p['state'] not in ('completed', 'failed', 'cancelled') for p in self.projects.values()))
            last = self.topic_terminal.get(key)
            eligible = not active
            episode = self.topic_episodes.get(key)
            oid = 'C:' + episode if episode else None
            result.append({'id': key, 'district': group['district'], 'category': group['category'], 'record_count': len(group['episodes']), 'facilities': sorted(group['facilities']), 'eligible': eligible, 'opportunity': oid, 'c_offered': eligible and self._offered(oid)})
        return result

    def _refresh_topics(self):
        for topic in self._topics():
            if not topic['eligible']:
                continue
            key = topic['id']
            previous = self.topic_episodes.get(key)
            prior_item = self.opportunities.get('C:' + previous) if previous else None
            if previous is None or (prior_item and prior_item['closed']):
                episode = key + '@' + str(self.round)
                self.topic_episodes[key] = episode
                self._opportunity('C', key, episode)

    def _obj(self, oid):
        return self.tickets.get(oid) or self.projects.get(oid)

    def _owner(self, oid):
        return self.tickets[oid]['lead'] if oid in self.tickets else 4

    def _members(self, oid):
        if oid in self.tickets:
            ticket = self.tickets[oid]
            return sorted(set(([ticket['lead']] if ticket['lead'] else []) + ticket['known_required']))
        return [2, 3, 4]

    def _active_service(self, oid):
        if not self._obj(oid).get('b_required') or not self._obj(oid).get('b_registered'):
            return False
        if oid in self.tickets:
            obj = self.tickets[oid]
            return obj['joint_activated_round'] is not None and (not obj['joint_withdrawn'])
        obj = self.projects[oid]
        return obj['mode'] == 'structured' and obj['activated_round'] is not None

    def _joint_ready(self, actor, oid):
        obj = self._obj(oid)
        if not obj.get('b_required'):
            return True
        if not self._active_service(oid):
            return False
        kind = 'joint_activation' if oid in self.tickets else 'project_activation'
        return any((r['kind'] == kind and (oid in self.tickets or r['data'].get('revision') == obj['revision']) for r in self._legal_records(actor, oid)))

    def _register_joint(self, oid):
        (obj, owner) = (self._obj(oid), self._owner(oid))
        if not obj.get('b_required'):
            return (False, 'joint_workflow_not_required')
        if obj.get('b_registered'):
            return (True, 'joint_workflow_already_registered')
        if not self._pay(owner, self.config['setup_cost'], reason='joint_setup', oid=oid):
            self._log('joint_registration_blocked', object=oid, reason='insufficient_owner_labor')
            return (False, 'insufficient_joint_setup_labor')
        obj['b_registered'] = True
        if oid in self.tickets:
            (obj['coordination'], obj['joint_withdrawn']) = ('joint', False)
            obj['joint_participants'] = self._members(oid)
            self._adopt(obj['b_opportunity'])
            for other in obj['joint_participants']:
                self._send_assignment(owner, other, oid, 'joint_invitation', self._case_definitions(oid))
            self._log('joint_flow_requested', ticket=oid, participants=obj['joint_participants'], mandatory=True)
        else:
            obj['mode'] = 'structured'
            self._adopt(obj['b_opportunity'])
            self._dispatch_joint_reviews(obj)
        self._log('joint_workflow_registered', object=oid, owner=owner, participants=self._members(oid))
        return (True, 'mandatory_joint_workflow_registered')

    def _received_project_assignment(self, actor, project):
        return any((task['revision'] == project['revision'] and (task['actor'] == actor) and (task['kind'] == 'review_project') for task in self._views_for(actor, 'tasks', project['id'])))

    def _dispatch_joint_reviews(self, project):
        (project['confirmed_by'], project['activated_round']) = ([4], None)
        self._record(project['id'], 4, 'project_lead_confirmation', {'owner': 4, 'revision': project['revision']})
        for other in (2, 3):
            self._send_assignment(4, other, project['id'], 'review_assignment', self._project_definitions(project['id'], 'review_project'))
        project['requested']['review_project'] = [2, 3]
        project['state'] = 'under_review'
        self._log('project_review_package_created', project=project['id'], revision=project['revision'], from_public_template=True, controlled_by='B')

    def _ordinary_zero(self, oid):
        return self.config['zero_communication_friction']

    def _access(self, actor, oid):
        return oid in self.knowledge[str(actor)]['objects']

    def _grant(self, actor, oid):
        if oid not in self.knowledge[str(actor)]['objects']:
            self.knowledge[str(actor)]['objects'].append(oid)

    def _task_definition(self, task):
        return {key: deepcopy(task[key]) for key in ('id', 'object', 'scope', 'kind', 'actor', 'prerequisites', 'revision')}

    def _task_view(self, task):
        return {**self._task_definition(task), 'state': task['state'], 'completed_round': task['completed_round'], 'opinion': task['opinion'], 'as_of_round': self.round}

    def _assign(self, actor, oid, definitions):
        self._grant(actor, oid)
        for definition in definitions:
            task = self.tasks.get(definition['id'])
            if task is None:
                continue
            prior = self.knowledge[str(actor)]['tasks'].get(task['id'])
            if prior is None or prior['revision'] != definition['revision']:
                self._remember(actor, 'tasks', task['id'], {**definition, 'state': 'pending', 'completed_round': None, 'opinion': None, 'as_of_round': self.round})
            if task['actor'] == actor and actor not in task['assigned']:
                task['assigned'].append(actor)
                self._log('task_assigned', task=task['id'], object=oid, actor_id=actor)

    def _record(self, oid, actor, kind, data):
        data = {k: v for (k, v) in data.items() if k != 'capital_spent'}
        rid = f'record-{len(self.records) + 1}'
        record = {'id': rid, 'object': oid, 'author': actor, 'kind': kind, 'created_round': self.round, 'data': deepcopy(data)}
        self.records[rid] = record
        self._learn(actor, record)
        self.service_dirty.setdefault(oid, []).append(rid)
        self._log('record_created', record=record)
        if self._ordinary_zero(oid):
            for recipient in self._members(oid):
                if recipient != actor and not (kind == 'review_completed' and oid in self.projects and recipient == self._owner(oid)):
                    self._message(actor, recipient, oid, 'status_reply', {'records': [record]}, free=True)
        return record

    def _learn(self, actor, record):
        self._grant(actor, record['object'])
        self._remember(actor, 'records', record['id'], record)
        if record['kind'] == 'project_terminal':
            for view in self._views_for(actor, 'tasks', record['object']):
                if view['state'] == 'pending':
                    view['state'] = 'cancelled'
        if record['kind'] in ('task_completed', 'review_completed', 'commissioning_result'):
            view = record['data']['task']
            prior = self.knowledge[str(actor)]['tasks'].get(view['id'])
            if prior is None or view['revision'] > prior['revision'] or (view['revision'] == prior['revision'] and (prior['state'] == 'pending' or view['as_of_round'] >= prior['as_of_round'])):
                self._remember(actor, 'tasks', view['id'], view)
            if actor == 4 and record['object'] in self.projects and (view['kind'] == 'implement_project' or record['kind'] == 'commissioning_result'):
                project = self.projects[record['object']]
                self._project_lifecycle(project).receive_owner_record(record, self.knowledge['4']['tasks'], self._legal_records(4, project['id']))

    def _payload(self, actor, oid):
        return {'records': self._legal_records(actor, oid)}

    def _message(self, sender, recipient, oid, kind, payload, free=False):
        mid = f'message-{len(self.messages) + 1}'
        due = self.round if free else self.round + 1
        message = {'id': mid, 'sender': sender, 'recipient': recipient, 'object': oid, 'kind': kind, 'created_round': self.round, 'deliver_round': due, 'delivered_round': None, 'replied': False, 'payload': deepcopy(payload), 'free_service': free}
        self.messages[mid] = message
        self._indices['pending_messages'].append(mid)
        self._log('message_created', message=message)
        return mid

    def accept_delivery(self, message_id):
        """Apply a trusted transport receipt; this domain method performs no transport."""
        if message_id not in self.messages:
            raise ValueError('Unknown business message')
        message = self.messages[message_id]
        if message['deliver_round'] > self.round:
            raise ValueError('Business message is not due')
        if message['delivered_round'] is not None:
            return
        message['delivered_round'] = self.round
        pending = self._indices['pending_messages']
        if pending[0] == message_id:
            pending.popleft()
        else:
            pending.remove(message_id)
        self._index_record_delivery(message)
        (recipient, oid, payload) = (message['recipient'], message['object'], message['payload'])
        self._grant(recipient, oid)
        self.knowledge[str(recipient)]['inbox'].append(message['id'])
        if payload.get('tasks'):
            self._assign(recipient, oid, payload['tasks'])
        for record in payload.get('records', []):
            self._learn(recipient, record)
        self._log('message_delivered', message=message['id'], sender=message['sender'], recipient=recipient, object=oid, delivery_round=self.round)

    def _flush_services(self):
        confirmation_kinds = {'joint_confirmation', 'project_confirmation', 'project_lead_confirmation', 'objection'}
        for (oid, record_ids) in list(self.service_dirty.items()):
            obj = self._obj(oid)
            if not record_ids or not obj.get('b_registered') or self.service_last_attempt.get(oid) == self.round:
                continue
            current = [rid for rid in record_ids if self.records[rid]['kind'] not in confirmation_kinds or oid in self.tickets or self.records[rid]['data'].get('revision') == obj['revision']]
            self.service_dirty[oid] = current
            send_ids = [rid for rid in current if self._active_service(oid) or self.records[rid]['kind'] in confirmation_kinds]
            if not send_ids:
                continue
            self.service_last_attempt[oid] = self.round
            owner = self._owner(oid)
            if not self._pay(owner, self.config['maintenance_cost'], reason='shared_record_maintenance', oid=oid):
                self._log('shared_update_failed', object=oid, owner=owner, pending_records=send_ids, reason='insufficient_owner_labor')
                continue
            payload = {'records': [deepcopy(self.records[rid]) for rid in send_ids]}
            for recipient in self._members(oid):
                self._message(owner, recipient, oid, 'shared_update', payload)
            self.service_dirty[oid] = [rid for rid in current if rid not in send_ids]
            self._log('shared_update_sent', object=oid, owner=owner, records=send_ids, recipients=self._members(oid))

    def _pay(self, actor, labor, capital=0.0, crew=0, reason='action', oid=None):
        return actor in ACTORS

    def _case_definitions(self, tid):
        return [self._task_definition(self.tasks[t]) for t in self.issues[self.tickets[tid]['issue']]['tasks']]

    def _project_definitions(self, pid, kind=None):
        project = self.projects[pid]
        return [self._task_definition(t) for t in self.tasks.values() if t['object'] == pid and t['revision'] == project['revision'] and (kind is None or t['kind'] == kind)]

    def _send_assignment(self, sender, recipient, oid, kind, definitions, free=False):
        payload = {**self._payload(sender, oid), 'tasks': definitions}
        self._message(sender, recipient, oid, kind, payload, free=free)

    def _new_project_tasks(self, project, kind):
        (revision, pid) = (project['revision'], project['id'])
        for actor in (2, 3):
            tid = f'J:{pid}:{revision}:{kind}:{actor}'
            prerequisite = [f'J:{pid}:{revision}:implement_project:3'] if kind == 'implement_project' and actor == 2 else []
            self.tasks[tid] = {'id': tid, 'object': pid, 'scope': 'project', 'kind': kind, 'actor': actor, 'prerequisites': prerequisite, 'state': 'pending', 'completed_round': None, 'assigned': [], 'revision': revision, 'opinion': None}
        self._assign(4, pid, self._project_definitions(pid, kind))

    def _construction_package(self, pid):
        return self._project_definitions(pid, 'implement_project') + self._project_definitions(pid, 'commission_project')

    def _new_commission_task(self, project):
        (pid, revision) = (project['id'], project['revision'])
        tid = f'J:{pid}:{revision}:commission_project:2'
        self.tasks[tid] = {'id': tid, 'object': pid, 'scope': 'project', 'kind': 'commission_project', 'actor': 2, 'prerequisites': [f'J:{pid}:{revision}:implement_project:{a}' for a in (2, 3)], 'state': 'pending', 'completed_round': None, 'assigned': [], 'revision': revision, 'opinion': None}
        self._assign(4, pid, [self._task_definition(self.tasks[tid])])

    def _visible_project_revision(self, actor, project):
        if actor == 4:
            return project['revision']
        revisions = [t['revision'] for t in self._views_for(actor, 'tasks', project['id'])]
        revisions.extend(r['data'].get('revision', 0) for r in self._views_for(actor, 'records', project['id']))
        return max(revisions, default=0)

    def _received_reviews(self, actor, project):
        reviews = {}
        revision = self._visible_project_revision(actor, project)
        for view in self._views_for(actor, 'tasks', project['id']):
            if view['kind'] == 'review_project' and (view['revision'] == revision) and (view['state'] == 'completed'):
                reviews[view['actor']] = view['opinion']
        return reviews

    def _known_project_evidence(self, actor, pid):
        evidence = []
        for record in self._views_for(actor, 'records', pid):
            if record['kind'] == 'project_diagnosis':
                evidence = deepcopy(record['data']['evidence'])
        return evidence

    def _legal_records(self, actor, oid):
        return [deepcopy(r) for r in self._views_for(actor, 'records', oid)]

    def _visible_ticket(self, actor, ticket):
        result = {k: deepcopy(ticket[k]) for k in ('id', 'facility', 'district', 'category', 'reported', 'public_episode', 'lead')}
        result['source_id'] = 'ticket:' + ticket['id']
        if actor in (2, 3):
            result['text'] = ticket['text']
        records = self._legal_records(actor, ticket['id'])
        result['closed'] = any((r['kind'] == 'issue_closed' for r in records))
        if actor == 1:
            result['a_offered'] = self._q('A') == 1
        if actor in (2, 3) and self._access(actor, ticket['id']):
            result['coordination'] = ticket['coordination']
            result['joint_required'] = ticket['b_required']
            result['joint_registered'] = ticket['b_registered']
            result['joint_ready'] = self._joint_ready(actor, ticket['id'])
            result['inspected_by_lead'] = ticket['inspected']
            result['tasks'] = [deepcopy(t) for t in self._views_for(actor, 'tasks', ticket['id'])]
            result['received_records'] = self._legal_records(actor, ticket['id'])
            if ticket['coordination'] == 'joint' and actor in ticket['joint_participants']:
                received = [r['author'] for r in result['received_records'] if r['kind'] == 'joint_confirmation']
                result['joint_invitation'] = {'participants': ticket['joint_participants'][:], 'confirmed_by': sorted(set(received)), 'own_confirmed': actor in ticket['joint_confirmed_by']}
                result['shared_records'] = [r for r in result['received_records'] if r['kind'] in ('task_completed', 'joint_confirmation')]
        return result

    def _visible_project(self, actor, project):
        pid = project['id']
        revision = self._visible_project_revision(actor, project)
        # Pending tasks of other actors are visible only once their review or
        # work request was actually dispatched for this revision; template
        # tasks created by a redraft must not masquerade as requested work
        # (attempt-0066: the lead waited forever for reviews it never asked
        # for because undispatched template tasks showed as pending).
        requested = project.get('requested') or {}
        def dispatched(view):
            return view['actor'] == actor or view['state'] != 'pending' or view['actor'] in requested.get(view['kind'], [])
        result = {'id': pid, 'topic': project['topic'], 'mode': project['mode'], 'owner': 4, 'joint_required': project['b_required'], 'joint_registered': project['b_registered'], 'joint_ready': self._joint_ready(actor, pid), 'revision': revision, 'received_records': self._legal_records(actor, pid), 'tasks': [deepcopy(t) for t in self._views_for(actor, 'tasks', pid) if t.get('revision') != revision or dispatched(t)], 'evidence': self._known_project_evidence(actor, pid)}
        construction = [t for t in result['tasks'] if t['kind'] == 'implement_project' and t['revision'] == revision]
        all_built = len(construction) == 2 and all((t['state'] == 'completed' for t in construction))
        result['construction'] = 'built' if all_built else 'in_progress' if any((t['state'] == 'completed' for t in construction)) else 'unknown'
        result['built_at'] = max((t['completed_round'] for t in construction)) if all_built else None
        commissioning = [r for r in result['received_records'] if r['kind'] == 'commissioning_result' and r['data']['revision'] == revision]
        (result['physical'], result['effective_at']) = ('unknown', None)
        if commissioning:
            data = commissioning[-1]['data']
            result['effective_at'] = data['effective_at']
            result['physical'] = ('effective' if self.round >= data['effective_at'] else 'commissioned_pending_effect') if data['success'] else 'commissioning_failed'
        terminal = [r for r in result['received_records'] if r['kind'] == 'project_terminal']
        result['administrative'] = ('accepted' if terminal[-1]['data']['state'] == 'completed' else terminal[-1]['data']['state']) if terminal else 'unknown'
        result['accepted_at'] = terminal[-1]['created_round'] if terminal and terminal[-1]['data']['state'] == 'completed' else None
        if actor == 4:
            result['administrative'] = project['administrative']
            result.update({k: deepcopy(project[k]) for k in ('state', 'lead_confirmed', 'plan', 'budget_requested', 'budget_approved', 'ready_round', 'facilities', 'requested', 'paused')})
            result['received_reviews'] = self._received_reviews(actor, project)
        if project['b_registered']:
            result['own_confirmed'] = actor in project['confirmed_by']
            result['project_package'] = {'participants': [2, 3, 4], 'template': deepcopy(PUBLIC_RULES['project_template']), 'received_review_departments': sorted(self._received_reviews(actor, project)), 'note': '仅整理已有授权材料及拟案任务，未收到的意见和进度仍未知。'}
        return result

    def _latest_receipt(self, actor):
        event = next((e for e in reversed(self.events) if e['kind'] == 'action_result' and e['actor_id'] == actor), None)
        if event is None:
            return None
        action = event.get('action') or {}
        receipt = {'round': event['round'], 'status': event['status'], 'code': event['code'],
                   'action_kind': action.get('kind'), 'target': action.get('target')}
        if event.get('detail'):
            receipt['detail'] = event['detail']
        return receipt

    def observe(self, actor_id):
        if type(actor_id) is not int or actor_id not in ACTORS:
            raise ValueError('unknown actor_id')
        (actor, zero) = (actor_id, self.config['zero_communication_friction'])
        visible_tickets = [self._visible_ticket(actor, t) for t in self.tickets.values() if actor in (1, 4) or self._access(actor, t['id'])]
        projects = [self._visible_project(actor, p) for p in self.projects.values() if self._access(actor, p['id'])]
        topics = []
        inbox = [{k: deepcopy(m[k]) for k in ('id', 'sender', 'object', 'kind', 'created_round', 'delivered_round', 'replied', 'payload')} for mid in self.knowledge[str(actor)]['inbox'] for m in [self.messages[mid]]]
        sent_messages = [{k: deepcopy(m[k]) for k in ('id', 'recipient', 'object', 'kind', 'created_round', 'payload')} for m in self.messages.values() if m['sender'] == actor]
        actions = [_action('wait')]
        for ticket in visible_tickets:
            tid = ticket['id']
            actual = self.tickets[tid]
            if ticket['closed']:
                continue
            if actor == 1 and ticket['lead'] is None:
                actions.extend((_action('route', tid, department=d) for d in (2, 3)))
            if actor in (2, 3) and actor == ticket['lead']:
                if not actual['inspected']:
                    actions.append(_action('inspect', tid))
                elif len(actual['known_required']) > 1 or actor not in actual['known_required']:
                    if actual['b_required'] and (not actual['b_registered']):
                        actions.append(_action('register_joint_workflow', tid))
                    if not zero and (not actual['b_required']):
                        for other in actual['known_required']:
                            if other != actor:
                                actions.append(_action('request_coordination', tid, mode='conventional', department=other))
            if actor in (2, 3) and ticket.get('joint_invitation'):
                if not ticket['joint_invitation']['own_confirmed'] and (not actual['joint_withdrawn']):
                    actions.append(_action('confirm_joint_task', tid))
                actions.append(_action('raise_objection', tid, reason_code='scope_or_capacity_concern'))
        for view in self.knowledge[str(actor)]['tasks'].values():
            if view['actor'] != actor or view['state'] != 'pending':
                continue
            obj = self._obj(view['object'])
            if obj is None or any((r['kind'] in ('issue_closed', 'project_terminal') for r in self._legal_records(actor, view['object']))):
                continue
            if not self._joint_ready(actor, view['object']):
                continue
            if view['kind'] == 'review_project':
                actions.extend((_action('review_project', view['id'], opinion=o) for o in ('approve', 'revise', 'reject')))
            else:
                from .availability import task_blockers
                entry = _action(view['kind'], view['id'])
                blockers = task_blockers(self, actor, view)
                if blockers:
                    entry['blocked_by'] = blockers
                actions.append(entry)
        for project in projects:
            (pid, actual) = (project['id'], self.projects[project['id']])
            if actor == 4 and actual['state'] in ('completed', 'failed', 'cancelled') or any((r['kind'] == 'project_terminal' for r in project['received_records'])):
                continue
            if actor in (2, 3) and actual['b_registered'] and (actor not in actual['confirmed_by']) and self._received_project_assignment(actor, actual):
                actions.append(_action('confirm_project_task', pid))
                actions.append(_action('raise_objection', pid, reason_code='scope_or_capacity_concern'))
            if actor == 4:
                if actual['b_required'] and (not actual['b_registered']) and actual['plan']:
                    actions.append(_action('register_joint_workflow', pid))
                if not actual['lead_confirmed']:
                    actions.append(_action('confirm_project_lead', pid))
                elif actual['state'] == 'lead_confirmed':
                    actions.append(_action('diagnose_project', pid))
                elif actual['state'] in ('diagnosed', 'planned', 'under_review'):
                    actions.append(_action('draft_plan', pid, plan='replace_shared_main', budget=0))
                    if actual['plan']:
                        if not zero and (not actual['b_required']):
                            actions.extend((_action('request_review', pid, department=d) for d in (2, 3)))
                        actions.append(_action('request_budget', pid))
                elif actual['state'] in ('approved', 'building', 'awaiting_commissioning', 'awaiting_acceptance', 'commissioning_failed'):
                    if not zero and (not actual['b_required']):
                        actions.extend((_action('request_project_work', pid, department=d) for d in (2, 3)))
                    actions.append(_action('accept_project', pid))
                    actions.append(_action('adjust_project', pid, decision='resume' if actual['paused'] else 'pause', reason_code='await_information_or_capacity'))
                if actual['evidence']:
                    actions.append(_action('cancel_project', pid, reason_code='evidence_does_not_support'))
                    actions.append(_action('cancel_project', pid, reason_code='budget_or_capacity_infeasible'))
        if actor == 4:
            if self.contacts:
                actions.append(_action('propose_project', source_ids=[], hypothesis=''))
        if not zero:
            for message in inbox:
                if message['replied']:
                    continue
                if message['kind'] == 'case_assignment' and actor in (2, 3):
                    actions.extend((_action('reply_coordination', message['id'], decision=d) for d in ('accept', 'decline')))
                elif message['kind'] == 'status_query':
                    actions.append(_action('reply_status', message['id']))
            for oid in self.knowledge[str(actor)]['objects']:
                obj = self._obj(oid)
                if obj is None:
                    continue
                for recipient in self._members(oid):
                    if recipient == actor:
                        continue
                    actions.append(_action('query_status', oid, department=recipient))
                    if self._legal_records(actor, oid):
                        actions.append(_action('report_status', oid, recipient=recipient))
        unique = {_canonical(a): a for a in actions}
        actions = [unique[key] for key in sorted(unique, key=lambda key: self._random('action_order', self.round, actor, key))]
        rules = deepcopy(FINITE_PUBLIC_RULES)
        rules.update({'project_lag': self.config['project_lag'], 'project_steps': self.config['project_steps'], 'topic_analysis': {'window_rounds': None, 'minimum_distinct_episodes': self.config['signal_threshold'], 'cooldown_rounds': 0, 'group_by': ['district', 'category'], 'deduplicate_by': 'public_episode', 'submission': '引用已取得的contact材料提出待现场检验的假设；材料持续可用。'}, 'communication': '消息结算后在下一轮送达。' if not zero else '合法回执在整轮结算后送达。', 'budget': '专业意见齐备后申请作业授权；当前作业所需资源可用。'})
        return decorate_observation({'spec_version': SPEC_VERSION, 'schema_version': SCHEMA_VERSION, 'round': self.round, 'horizon': None, 'actor_id': actor, 'role': ACTORS[actor], 'last_receipt': self._latest_receipt(actor), 'visible_tickets': visible_tickets, 'projects': projects, 'topics': topics, 'inbox': inbox, 'sent_messages': sent_messages, 'zero_communication_friction': zero, 'resources': {'availability': '当前作业所需资源可用'}, 'public_rules': rules, 'available_actions': actions, 'materials': projection(self, actor)})

    def submit(self, actor_id, action):
        receipt = {'actor_id': actor_id, 'round': self.round}
        if type(actor_id) is not int or actor_id not in ACTORS:
            return {**receipt, 'status': 'technical_error', 'code': 'unknown_actor'}
        if not isinstance(action, dict) or set(action) != {'kind', 'target', 'params', 'reason'} or (not isinstance(action.get('kind'), str)) or (not isinstance(action.get('params'), dict)) or (not isinstance(action.get('reason'), str)) or (action.get('target') is not None and (not isinstance(action['target'], str))):
            return {**receipt, 'status': 'technical_error', 'code': 'invalid_action_schema'}
        if set(action['params']) - ACTION_PARAM_KEYS.get(action['kind'], set()):
            return {**receipt, 'status': 'technical_error', 'code': 'unexpected_action_params'}
        try:
            encoded = _canonical(action)
        except (TypeError, ValueError):
            return {**receipt, 'status': 'technical_error', 'code': 'non_json_action'}
        key = str(actor_id)
        if key in self.pending:
            duplicate = self.pending[key]['canonical'] == encoded
            return {**receipt, 'status': 'queued' if duplicate else 'business_rejected', 'code': 'duplicate_idempotent' if duplicate else 'one_action_per_round'}
        context = self.observe(actor_id)
        self._log('decision_context', actor_id=actor_id, action_order=context['available_actions'], observation_sha256=hashlib.sha256(_canonical(context).encode()).hexdigest())
        self.pending[key] = {'action': deepcopy(action), 'canonical': encoded}
        self._log('action_submitted', actor_id=actor_id, action=action)
        return {**receipt, 'status': 'queued', 'code': 'accepted_for_settlement'}

    def _execute(self, actor, action):
        (kind, target, params) = (action['kind'], action['target'], action['params'])
        if kind == 'wait':
            return (True, 'waited')
        if not self._pay(actor, self.config['decision_cost'], reason='decision:' + kind, oid=target):
            return (False, 'insufficient_decision_labor')
        if kind not in ALLOWED_KINDS:
            return (False, 'unknown_business_action')
        if kind == 'register_joint_workflow':
            if self._obj(target) is None or self._owner(target) != actor:
                return (False, 'joint_registration_owner_required')
            return self._register_joint(target)
        if kind in COMMUNICATION_KINDS or kind in ('request_coordination', 'confirm_joint_task', 'raise_objection', 'withdraw_joint'):
            return self._communication_action(actor, kind, target, params)
        if kind == 'route':
            ticket = self.tickets.get(target)
            if actor != 1 or ticket is None or ticket['closed'] or (ticket['lead'] is not None):
                return (False, 'route_not_permitted')
            department = params.get('department')
            if type(department) is not int or department not in (2, 3):
                return (False, 'invalid_route_parameters')
            if not self._pay(actor, self.config['route_cost'], reason=kind, oid=target):
                return (False, 'insufficient_labor')
            use = self._q('A') == 1
            (ticket['lead'], ticket['a_called']) = (department, use)
            self._message(actor, department, target, 'ticket_assignment', {})
            if use:
                self._adopt(ticket['a_opportunity'])
            self.opportunities[ticket['a_opportunity']]['closed'] = True
            matched = department in [self.tasks[t]['actor'] for t in self.issues[ticket['issue']]['tasks']]
            self._log('routed', ticket=target, department=department, a_material_provided=use, recommendation_used=None, initially_matched=matched)
            return (True, 'routed')
        if kind == 'inspect':
            ticket = self.tickets.get(target)
            if actor not in (2, 3) or ticket is None or ticket['lead'] != actor or ticket['inspected'] or ticket['closed']:
                return (False, 'inspection_not_permitted')
            if not self._pay(actor, self.config['inspect_cost'], reason=kind, oid=target):
                return (False, 'insufficient_labor')
            definitions = self._case_definitions(target)
            ticket['inspected'] = True
            ticket['known_required'] = sorted({t['actor'] for t in definitions})
            self._assign(actor, target, definitions)
            self._record(target, actor, 'case_survey', {'tasks': definitions, 'method': '现场业务调查'})
            if len(ticket['known_required']) > 1 or actor not in ticket['known_required']:
                ticket['b_opportunity'] = self._opportunity('B', target, ticket['public_episode'])
                ticket['b_required'] = self._q('B') == 1
                if ticket['b_required']:
                    self._log('joint_workflow_required', object=target, participants=self._members(target), basis='received_case_survey')
                    self._register_joint(target)
            if self.config['zero_communication_friction'] and (not ticket['b_required']):
                ticket['coordination'] = 'conventional'
                for other in ticket['known_required']:
                    if other != actor:
                        self._send_assignment(actor, other, target, 'case_assignment', definitions, free=True)
                self._log('zero_friction_coordination', ticket=target, participants=self._members(target))
            return (True, 'inspection_revealed_local_task_plan')
        if kind in ('work', 'review_project', 'implement_project', 'commission_project'):
            return self._task_action(actor, kind, target, params)
        return self._project_action(actor, kind, target, params)

    def _communication_action(self, actor, kind, target, params):
        zero = self.config['zero_communication_friction']
        if kind in ('reply_coordination', 'reply_status'):
            message = self.messages.get(target)
            if message is None or message['recipient'] != actor or message['delivered_round'] is None or message['replied']:
                return (False, 'message_reply_not_permitted')
            required_kind = 'case_assignment' if kind == 'reply_coordination' else 'status_query'
            if message['kind'] != required_kind:
                return (False, 'wrong_reply_kind')
            if zero:
                return (False, 'communication_is_passive')
            decision = params.get('decision', 'accept')
            if decision not in ('accept', 'decline'):
                return (False, 'invalid_coordination_reply')
            if not self._pay(actor, self.config['communication_cost'], reason=kind, oid=message['object']):
                return (False, 'insufficient_labor')
            message['replied'] = True
            if kind == 'reply_coordination':
                self._record(message['object'], actor, 'ordinary_assignment_reply', {'decision': decision})
            self._message(actor, message['sender'], message['object'], 'status_reply', self._payload(actor, message['object']))
            return (True, 'reply_sent')
        if kind == 'request_coordination':
            ticket = self.tickets.get(target)
            if ticket is None or actor != ticket['lead'] or (not ticket['inspected']) or ticket['closed']:
                return (False, 'coordination_not_permitted')
            if len(ticket['known_required']) == 1 and actor in ticket['known_required']:
                return (False, 'no_cross_department_need_or_dispute')
            if ticket['b_required']:
                return (False, 'mandatory_joint_workflow_no_ordinary_bypass')
            mode = params.get('mode')
            if mode == 'joint':
                return (False, 'joint_service_not_available_in_ordinary_policy')
            if mode != 'conventional':
                return (False, 'invalid_coordination_mode')
            if zero:
                return (False, 'communication_is_passive')
            other = params.get('department')
            if type(other) is not int or other == actor or other not in ticket['known_required']:
                return (False, 'invalid_collaborator')
            if not self._pay(actor, self.config['communication_cost'], reason=kind, oid=target):
                return (False, 'insufficient_labor')
            if ticket['coordination'] is None:
                ticket['coordination'] = 'conventional'
            self._send_assignment(actor, other, target, 'case_assignment', self._case_definitions(target))
            self._log('coordination_requested', ticket=target, requester=actor, collaborator=other)
            return (True, 'ordinary_assignment_sent')
        if kind == 'confirm_joint_task':
            ticket = self.tickets.get(target)
            if ticket is None or not ticket['b_registered'] or ticket['closed'] or ticket['joint_withdrawn'] or (actor not in ticket['joint_participants']) or (not self._access(actor, target)):
                return (False, 'joint_confirmation_not_permitted')
            if actor in ticket['joint_confirmed_by']:
                return (False, 'already_confirmed')
            ticket['joint_confirmed_by'] = sorted(ticket['joint_confirmed_by'] + [actor])
            self._record(target, actor, 'joint_confirmation', {'accepted': True})
            self._log('joint_task_confirmed', ticket=target, actor_id=actor)
            if ticket['joint_confirmed_by'] == ticket['joint_participants']:
                ticket['joint_activated_round'] = self.round
                self._record(target, actor, 'joint_activation', {'participants': ticket['joint_participants']})
                self._log('joint_board_activated', ticket=target, participants=ticket['joint_participants'])
            return (True, 'joint_task_confirmed')
        obj = self._obj(target)
        if obj is None or not self._access(actor, target):
            return (False, 'object_not_accessible')
        if kind == 'raise_objection':
            if actor not in self._members(target) or params.get('reason_code') != 'scope_or_capacity_concern':
                return (False, 'invalid_objection')
            if target in self.projects and actor != 4 and (not self._received_project_assignment(actor, obj)):
                return (False, 'current_project_assignment_not_delivered')
            self._record(target, actor, 'objection', {'reason_code': params['reason_code'], **({'revision': obj['revision']} if target in self.projects else {})})
            self._log('coordination_objection', object=target, actor_id=actor, reason=params['reason_code'])
            return (True, 'objection_recorded_without_forcing_compliance')
        if kind == 'withdraw_joint':
            if obj.get('b_required'):
                return (False, 'mandatory_joint_workflow_cannot_be_withdrawn')
            if target not in self.tickets or actor != obj['lead'] or obj['coordination'] != 'joint' or obj['joint_withdrawn']:
                return (False, 'withdrawal_not_permitted')
            (obj['joint_withdrawn'], obj['coordination']) = (True, 'conventional')
            self._log('joint_withdrawn', ticket=target, actor_id=actor)
            return (True, 'ordinary_channel_retained')
        if zero:
            return (False, 'communication_is_passive')
        if kind in ('query_status', 'report_status'):
            recipient = params.get('department' if kind == 'query_status' else 'recipient')
            if type(recipient) is not int or recipient not in self._members(target) or recipient == actor:
                return (False, 'invalid_message_recipient')
            if not self._pay(actor, self.config['communication_cost'], reason=kind, oid=target):
                return (False, 'insufficient_labor')
            self._message(actor, recipient, target, 'status_query' if kind == 'query_status' else 'status_reply', {} if kind == 'query_status' else self._payload(actor, target))
            return (True, 'message_sent')
        if kind in ('request_review', 'request_project_work'):
            project = self.projects.get(target)
            department = params.get('department')
            if actor != 4 or project is None or type(department) is not int or (department not in (2, 3)):
                return (False, 'project_request_not_permitted')
            if project['b_required']:
                return (False, 'mandatory_joint_workflow_no_ordinary_bypass')
            task_kind = 'review_project' if kind == 'request_review' else 'implement_project'
            allowed_states = ('planned', 'under_review') if task_kind == 'review_project' else ('approved', 'building', 'awaiting_commissioning', 'awaiting_acceptance', 'commissioning_failed')
            if project['state'] not in allowed_states:
                return (False, 'project_request_stage_missing')
            if not self._pay(actor, self.config['communication_cost'], reason=kind, oid=target):
                return (False, 'insufficient_labor')
            self._send_assignment(actor, department, target, 'review_assignment' if task_kind == 'review_project' else 'construction_assignment', self._project_definitions(target, task_kind) if task_kind == 'review_project' else self._construction_package(target))
            project['requested'][task_kind] = sorted(set(project['requested'][task_kind] + [department]))
            if task_kind == 'review_project':
                project['state'] = 'under_review'
            self._log('project_task_requested', project=target, department=department, task_kind=task_kind)
            return (True, 'project_task_request_sent')
        return (False, 'unsupported_communication_action')

    def _task_action(self, actor, kind, target, params):
        task = self.tasks.get(target)
        view = self.knowledge[str(actor)]['tasks'].get(target)
        if actor not in (2, 3) or task is None or task['actor'] != actor or (task['kind'] != kind) or (actor not in task['assigned']) or (view is None):
            return (False, 'task_not_assigned_to_actor')
        if task['state'] != 'pending':
            return (False, 'task_not_pending')
        oid = task['object']
        if not self._joint_ready(actor, oid):
            return (False, 'mandatory_joint_confirmation_or_delivered_activation_missing')
        project = self.projects.get(oid)
        if project and (project['state'] in ('completed', 'failed', 'cancelled') or task['revision'] != project['revision']):
            return (False, 'project_task_inactive')
        if project and project['paused'] and (kind in ('implement_project', 'commission_project')):
            return (False, 'project_paused_by_owner')
        if kind == 'commission_project':
            return self._commission_action(actor, task, project)
        if kind == 'review_project':
            if project is None or not self._known_project_evidence(actor, oid):
                return (False, 'review_material_not_received')
            opinion = params.get('opinion')
            if opinion not in ('approve', 'revise', 'reject'):
                return (False, 'invalid_professional_opinion')
            if not self._pay(actor, self.config['review_cost'], reason=kind, oid=oid):
                return (False, 'insufficient_review_labor')
            task['opinion'] = opinion
        else:
            if project and project['budget_approved'] is None:
                return (False, 'construction_budget_not_authorized')
            from .availability import task_blockers
            blockers = task_blockers(self, actor, task)
            for prerequisite in task['prerequisites']:
                received = self.knowledge[str(actor)]['tasks'].get(prerequisite)
                if self.tasks[prerequisite]['state'] != 'completed' or not received or received['state'] != 'completed':
                    detail = {'unmet': blockers} if blockers else {'unmet': [
                        {'task': prerequisite, 'received_completion': False, 'note': '前置作业尚未完成交接。'}]}
                    return (False, 'prerequisites_or_received_handoff_missing', detail)
            labor = self.config['project_work_cost'] if project else self.config['work_cost']
            capital = 0
            if not self._pay(actor, labor, capital, 1, reason=kind, oid=oid):
                self._record(oid, actor, 'capacity_obstacle', {'task': target, 'reason': 'insufficient_work_resources', 'as_of_round': self.round})
                return (False, 'insufficient_work_labor_capital_or_crew')
            if project:
                return self._project_lifecycle(project).complete_construction(actor, task, capital, self.knowledge[str(actor)]['tasks'])
        (task['state'], task['completed_round']) = ('completed', self.round)
        self._remember(actor, 'tasks', target, self._task_view(task))
        record = self._record(oid, actor, 'review_completed' if kind == 'review_project' else 'task_completed', {'task': self._task_view(task), 'capital_spent': 0 if kind == 'review_project' else capital})
        self._log('task_reviewed' if kind == 'review_project' else 'task_completed', task=target, object=oid, actor_id=actor, task_kind=kind, opinion=task['opinion'])
        if kind == 'review_project' and project:
            # The professional opinion is a mandatory procedural outcome: the
            # world transports it to the project lead through the same official
            # delivery channel as assignments. The lead still learns it only
            # after the mailbox receive succeeds; nothing is granted early.
            self._message(actor, self._owner(oid), oid, 'status_reply', {'records': [record]})
        if not project:
            issue = self.issues[self.tickets[oid]['issue']]
            if all((self.tasks[t]['state'] == 'completed' for t in issue['tasks'])):
                issue['resolved'] = self.round + 1
                self.tickets[oid]['closed'] = True
                self._record(oid, actor, 'issue_closed', {'resolved_round': self.round + 1})
                bop = self.tickets[oid]['b_opportunity']
                if bop:
                    self.opportunities[bop]['closed'] = True
                self._log('issue_resolved', issue=issue['id'], ticket=oid, resolved_round=self.round + 1, source='individual_tasks')
        return (True, 'professional_opinion_recorded' if kind == 'review_project' else 'work_completed')

    def _project_lifecycle(self, project):
        tasks = {key: task for (key, task) in self.tasks.items() if task['object'] == project['id']}
        return ProjectLifecycle(project, tasks, self.round, self.config['project_lag'], pay=self._pay, record=self._record, log=self._log, task_view=self._task_view, close_topic=self.topic_terminal.__setitem__)

    def _commission_action(self, actor, task, project):
        if actor != 2 or project is None:
            return (False, 'commissioning_authorization_missing')
        return self._project_lifecycle(project).commission(actor, task, self.knowledge[str(actor)]['tasks'], [self.facilities[fid] for fid in project['facilities']], self.config['project_commission_cost'])

    def _project_action(self, actor, kind, target, params):
        if kind == 'confirm_project_task':
            project = self.projects.get(target)
            if actor not in (2, 3) or project is None or (not project['b_registered']) or (not self._access(actor, target)) or (project['state'] in ('failed', 'cancelled', 'completed')):
                return (False, 'project_confirmation_not_permitted')
            if not self._received_project_assignment(actor, project):
                return (False, 'current_project_assignment_not_delivered')
            if actor in project['confirmed_by']:
                return (False, 'already_confirmed')
            project['confirmed_by'] = sorted(project['confirmed_by'] + [actor])
            self._record(target, actor, 'project_confirmation', {'accepted': True, 'revision': project['revision']})
            self._log('project_task_confirmed', project=target, actor_id=actor)
            if project['confirmed_by'] == [2, 3, 4]:
                project['activated_round'] = self.round
                self._record(target, actor, 'project_activation', {'participants': [2, 3, 4], 'revision': project['revision']})
                self._log('project_board_activated', project=target, participants=[2, 3, 4])
            return (True, 'project_task_confirmed')
        if actor != 4:
            return (False, 'project_owner_required')
        if kind == 'propose_project':
            ids = params.get('source_ids')
            sources = self.material_sources(actor)
            if not isinstance(ids, list) or not ids or len(ids) > 128 or any((not isinstance(sid, str) for sid in ids)) or (len(set(ids)) != len(ids)):
                return (False, 'topic_source_ids_invalid')
            if any((sid not in sources or sources[sid]['kind'] != 'contact' for sid in ids)):
                return (False, 'topic_sources_unavailable')
            context = self.material_contexts.get(str(actor))
            if context is None:
                delivered = represented_ids(projection(self, actor))
            else:
                if context['round'] != self.round or any((context['source_versions'].get(sid) != sources[sid]['version'] for sid in ids)):
                    return (False, 'topic_sources_unavailable')
                delivered = set(context['represented_ids'])
            rows = [sources[sid] for sid in ids]
            if any((sid not in delivered for sid in ids)) or any((row['received_round'] > self.round for row in rows)):
                return (False, 'topic_sources_not_delivered')
            if len({row['data']['district'] for row in rows}) != 1:
                return (False, 'topic_sources_cross_district')
            if len({row['data']['category'] for row in rows}) != 1:
                return (False, 'topic_sources_cross_category')
            facts = topic_facts(ids, sources)
            hypothesis = params.get('hypothesis')
            if target is not None or not isinstance(hypothesis, str) or (not hypothesis.strip()) or (len(hypothesis) > 1200):
                return (False, 'invalid_topic_hypothesis')
            if facts['record_count'] < self.config['signal_threshold']:
                return (False, 'topic_distinct_episode_threshold_not_met')
            target = facts['id']
            if any((p['topic'] == target and p['state'] not in ('completed', 'failed', 'cancelled') for p in self.projects.values())):
                return (False, 'topic_already_active')
            last = self.topic_terminal.get(target)
            topic = next((t for t in self._topics() if t['id'] == target and t['eligible']))
            if not self._pay(actor, self.config['project_proposal_cost'], reason=kind, oid=target):
                return (False, 'insufficient_labor')
            pid = f'P:{len(self.projects) + 1}'
            self.projects[pid] = {'id': pid, 'topic': target, 'opportunity': topic['opportunity'], 'owner': 4, 'facilities': facts['facilities'], 'mode': 'conventional', 'state': 'proposed', 'created': self.round, 'analysis_source_ids': facts['source_ids'], 'analysis_hypothesis': hypothesis, 'c_available': self._q('C') == 1, 'b_required': False, 'b_registered': False, 'b_opportunity': None, 'lead_confirmed': False, 'confirmed_by': [], 'activated_round': None, 'evidence': [], 'plan': None, 'revision': 0, 'budget_requested': None, 'budget_approved': None, 'capital_spent': 0.0, 'ready_round': None, 'physical_ready_round': None, 'construction': 'not_started', 'built_at': None, 'physical': 'not_commissioned', 'effective_at': None, 'commissioned_at': None, 'commissioning_assessment': None, 'administrative': 'open', 'accepted_at': None, 'cancelled_at': None, 'paused': False, 'requested': {'review_project': [], 'implement_project': []}}
            self._grant(4, pid)
            if self._q('C') == 1:
                self._adopt(topic['opportunity'])
            self.opportunities[topic['opportunity']]['closed'] = True
            self._log('project_proposed', project=pid, topic=target, mode='conventional', c_available=self._q('C') == 1, source_ids=facts['source_ids'], hypothesis=hypothesis, opportunity=topic['opportunity'])
            return (True, 'project_proposed')
        project = self.projects.get(target)
        if project is None or not self._access(actor, target):
            return (False, 'unknown_project')
        if project['state'] in ('completed', 'failed', 'cancelled'):
            return (False, 'project_already_terminal')
        if kind == 'confirm_project_lead':
            if project['lead_confirmed']:
                return (False, 'project_lead_already_confirmed')
            (project['lead_confirmed'], project['state']) = (True, 'lead_confirmed')
            project['confirmed_by'] = [4]
            self._record(target, actor, 'project_lead_confirmation', {'owner': 4, 'revision': project['revision']})
            self._log('project_lead_confirmed', project=target, actor_id=actor)
            return (True, 'project_lead_confirmed')
        if kind == 'diagnose_project':
            if project['state'] != 'lead_confirmed':
                return (False, 'lead_confirmation_or_diagnosis_stage_missing')
            if not self._pay(actor, self.config['project_diagnosis_cost'], reason=kind, oid=target):
                return (False, 'insufficient_diagnosis_labor')
            evidence = []
            for fid in project['facilities']:
                facility = self.facilities[fid]
                label = hashlib.sha256(('observed-asset:' + facility['root']).encode()).hexdigest()[:8]
                evidence.append({'facility': fid, 'method': '现场管线溯源', 'observed_asset': '勘察资产-' + label, 'defect_observed': not facility['root_repaired']})
            (project['evidence'], project['state']) = (evidence, 'diagnosed')
            self._record(target, actor, 'project_diagnosis', {'evidence': evidence})
            self._log('project_diagnosed', project=target, actor_id=actor)
            return (True, 'field_evidence_collected')
        if kind == 'draft_plan':
            if project['state'] not in ('diagnosed', 'planned', 'under_review') or not project['evidence']:
                return (False, 'plan_stage_or_evidence_missing')
            budget = params.get('budget')
            if params.get('plan') != 'replace_shared_main' or type(budget) not in (int, float) or (not math.isfinite(budget)) or (budget < 0):
                return (False, 'plan_or_budget_invalid')
            for task in self.tasks.values():
                if task['object'] == target and task['state'] == 'pending':
                    task['state'] = 'cancelled'
            project['revision'] += 1
            (project['plan'], project['budget_requested'], project['state']) = (params['plan'], float(budget), 'planned')
            project['requested'] = {'review_project': [], 'implement_project': []}
            self._new_project_tasks(project, 'review_project')
            self._record(target, actor, 'proposed_plan', {'plan': project['plan'], 'revision': project['revision'], 'budget': budget, 'template': deepcopy(PUBLIC_RULES['project_template'])})
            if self._q('B') == 1:
                project['b_required'] = True
                if project['b_opportunity'] is None:
                    project['b_opportunity'] = self._opportunity('B', target, 'project:' + target)
                    self._log('joint_workflow_required', object=target, participants=[2, 3, 4], basis='public_plan_responsibilities')
                if project['b_registered']:
                    self._dispatch_joint_reviews(project)
                else:
                    self._register_joint(target)
            elif self._ordinary_zero(target):
                for department in (2, 3):
                    self._send_assignment(4, department, target, 'review_assignment', self._project_definitions(target, 'review_project'), free=self._ordinary_zero(target))
                project['requested']['review_project'] = [2, 3]
                project['state'] = 'under_review'
                self._log('project_review_package_created', project=target, revision=project['revision'], from_public_template=True)
            self._log('project_plan_drafted', project=target, plan=project['plan'], budget=budget, revision=project['revision'])
            return (True, 'proposed_plan_recorded')
        if kind == 'request_budget':
            if project['state'] not in ('planned', 'under_review') or project['plan'] is None:
                return (False, 'budget_request_stage_missing')
            if not self._joint_ready(actor, target):
                return (False, 'mandatory_joint_confirmation_or_delivered_activation_missing')
            reviews = self._received_reviews(4, project)
            if reviews != {2: 'approve', 3: 'approve'}:
                self._log('project_budget_denied', project=target, reason='received_professional_approvals_incomplete')
                return (False, 'received_professional_approvals_incomplete')
            amount = project['budget_requested']
            (project['budget_approved'], project['state']) = (amount, 'approved')
            self._new_project_tasks(project, 'implement_project')
            self._new_commission_task(project)
            self._record(target, actor, 'budget_authorization', {'amount': amount, 'reserved_resources': False, 'revision': project['revision']})
            if project['b_registered'] or self._ordinary_zero(target):
                for department in (2, 3):
                    self._send_assignment(4, department, target, 'construction_assignment', self._construction_package(target), free=self._ordinary_zero(target))
                project['requested']['implement_project'] = [2, 3]
            self._log('project_budget_approved', project=target, amount=amount, capital_available=self.capital, reserves_resources=False)
            return (True, 'budget_ceiling_authorized_no_resource_reservation')
        if kind == 'cancel_project':
            reason = params.get('reason_code')
            if not project['evidence'] or reason not in ('evidence_does_not_support', 'budget_or_capacity_infeasible'):
                return (False, 'cancellation_requires_recorded_basis')
            if reason == 'budget_or_capacity_infeasible':
                received = self._legal_records(actor, target)
                known_spent = sum((r['data'].get('capital_spent', 0) for r in received if r['kind'] == 'task_completed'))
                remaining = max(0, (project['budget_approved'] or project['budget_requested'] or 2 * self.config['project_step_capital']) - known_spent)
                obstacle = any((r['kind'] in ('capacity_obstacle', 'objection') for r in received))
                if not obstacle:
                    return (False, 'budget_infeasibility_not_recorded')
            self._terminate_project(project, 'cancelled')
            self._log('project_cancelled', project=target, reason=reason, spent_capital=project['capital_spent'], refunded=0)
            return (True, 'project_cancelled_ordinary_cases_retained')
        if kind == 'adjust_project':
            if project['state'] not in ('approved', 'building', 'awaiting_commissioning', 'awaiting_acceptance', 'commissioning_failed') or params.get('decision') not in ('pause', 'resume') or params.get('reason_code') != 'await_information_or_capacity':
                return (False, 'project_adjustment_not_permitted')
            paused = params['decision'] == 'pause'
            if project['paused'] == paused:
                return (False, 'project_already_in_requested_state')
            project['paused'] = paused
            self._record(target, actor, 'project_adjustment', {'paused': paused, 'reason_code': params['reason_code']})
            self._log('project_adjusted', project=target, paused=paused, reason=params['reason_code'])
            return (True, 'project_execution_plan_adjusted_without_resource_bonus')
        if kind == 'accept_project':
            return self._project_lifecycle(project).accept(self._legal_records(actor, target), self.knowledge['4']['tasks'], self._received_reviews(4, project), self.config['project_accept_cost'])
        return (False, 'unsupported_project_action')

    def _terminate_project(self, project, state):
        self._project_lifecycle(project).terminate(state)

    def advance(self):
        # An actor whose turn failed settles as unfiled for this round: the
        # fact is recorded, nothing is fabricated, the world advances with
        # the actors who did transact (see policy_sim/failure.py).
        from .failure import unfiled_receipt
        order_actors = [1, 2, 3, 4]
        missing = [actor for actor in order_actors if str(actor) not in self.pending]
        for actor in missing:
            self._log('action_result', actor_id=actor, action=None,
                      status='unfiled', code='actor_turn_failed', detail=None,
                      receipt=unfiled_receipt(actor, self.round))
        actors = [2, 3, 4]
        offset = (self.round + int(self._random('settlement_start') * 3)) % 3
        order = [1] + actors[offset:] + actors[:offset]
        self._log('settlement_order', actors=order, unfiled=missing, shared_crew_capacity=None)
        for actor in order:
            pending = self.pending.get(str(actor))
            if pending is None:
                continue
            action = pending['action']
            result = self._execute(actor, action)
            (ok, code, detail) = (result + (None,))[:3]
            self._log('action_result', actor_id=actor, action=action, status='executed' if ok else 'business_rejected', code=code, detail=detail)
        self.pending = {}
        self.material_contexts = {}
        self._flush_services()
        unresolved = sum((i['resolved'] is None for i in self.issues.values()))
        self.burden_by_round.append(unresolved)
        self._log('round_completed', completed_round=self.round + 1, settlement_unresolved=unresolved, unresolved=unresolved, cumulative_issue_burden=sum(self.burden_by_round))
        self.round += 1
        activate_due_projects(self.projects.values(), self.facilities, self.round, self._log)
        self.crew_remaining = None
        self._refresh_offers()
        self._refresh_topics()

    def completion_status(self):
        """Privileged controller/audit status; never part of an actor observation."""
        cases = sorted((iid for iid in self.initial_ids if self.issues[iid]['resolved'] is None or not any((t['issue'] == iid and t['closed'] for t in self.tickets.values()))))
        tasks = sorted((t['id'] for t in self.tasks.values() if t['object'] in self.tickets and t['state'] == 'pending'))
        roots = {}
        for f in self.facilities.values():
            if f['shared_root']:
                roots.setdefault(f['root'], []).append(f['id'])
        (repairs, acceptance) = ([], [])
        for (root, ids) in sorted(roots.items()):
            if not all((self.facilities[fid]['root_repaired'] for fid in ids)):
                repairs.append({'root': root, 'facilities': sorted(ids)})
            accepted = any((p['administrative'] == 'accepted' and p['physical'] == 'effective' and (set(ids) <= set(p['facilities'])) for p in self.projects.values()))
            if not accepted:
                acceptance.append({'root': root, 'facilities': sorted(ids), 'project_ids': sorted((p['id'] for p in self.projects.values() if set(ids) <= set(p['facilities'])))})
        return {'complete': not (cases or tasks or repairs or acceptance), 'remaining_local_cases': cases, 'remaining_local_tasks': tasks, 'required_shared_root_repairs': repairs, 'required_administrative_acceptance': acceptance}

    def metrics(self):
        initial = [self.issues[i] for i in self.initial_ids]
        resources = [e for e in self.events if e['kind'] == 'resource_spent']
        results = [e for e in self.events if e['kind'] == 'action_result']
        routed = [e for e in self.events if e['kind'] == 'routed']
        process = {}
        for tool in 'ABC':
            opportunities = [o for o in self.opportunities.values() if o['tool'] == tool]
            (offered, used) = (sum((o['offered_ever'] for o in opportunities)), sum((o['adopted'] for o in opportunities)))
            process[tool] = {'eligible': len(opportunities), 'offered': offered, 'used': used, 'offer_rate': offered / len(opportunities) if opportunities else None, 'use_rate': used / offered if offered else None}
        used_a = [t for t in self.tickets.values() if t['a_called']]
        used_b = [t for t in self.tickets.values() if t['b_opportunity'] and self.opportunities[t['b_opportunity']]['adopted']]
        used_b_projects = [p for p in self.projects.values() if p['b_registered']]
        used_c = [p for p in self.projects.values() if p['c_available']]
        completed = {'A': len(used_a), 'B': sum((t['closed'] for t in used_b)) + sum((p['state'] == 'completed' for p in used_b_projects)), 'C': sum((p['state'] == 'completed' for p in used_c))}
        for tool in 'ABC':
            process[tool]['completed'] = completed[tool]
            process[tool]['completion_rate'] = completed[tool] / process[tool]['used'] if process[tool]['used'] else None
        process['A'].update({'objective_resolved': sum((t['closed'] for t in used_a)), 'used_definition': 'routing_with_A_material_available_not_proven_cognitive_adoption'})
        process['B'].update({'objective_resolved': sum((t['closed'] for t in used_b)), 'confirmed_participations': sum((len(t['joint_confirmed_by']) for t in used_b)), 'registered_cases': len(used_b), 'registered_projects': len(used_b_projects), 'completed_projects': sum((p['state'] == 'completed' for p in used_b_projects)), 'fully_confirmed_cases': sum((t['joint_activated_round'] is not None for t in used_b)), 'confirmed_and_resolved': sum((t['joint_activated_round'] is not None and t['closed'] for t in used_b)), 'ordinary_requests': sum((e['kind'] == 'coordination_requested' for e in self.events)), 'objections': sum((e['kind'] == 'coordination_objection' and e['object'] in self.tickets for e in self.events))})
        process['C'].update({'objective_resolved': 0, 'cancelled': sum((p['state'] == 'cancelled' for p in used_c)), 'used_definition': 'project_proposed_with_C_available_not_proven_cognitive_adoption', 'physically_effective': sum((p['physical'] == 'effective' for p in used_c)), 'administratively_accepted': sum((p['administrative'] == 'accepted' for p in used_c)), 'all_projects_proposed': len(self.projects), 'all_projects_cancelled': sum((p['state'] == 'cancelled' for p in self.projects.values())), 'professional_reviews': sum((e['kind'] == 'task_reviewed' for e in self.events))})
        stage_delays = []
        for p in self.projects.values():
            built_followup_end = p['commissioned_at'] if p['physical'] == 'commissioning_failed' else p['cancelled_at'] if p['cancelled_at'] is not None else self.round
            administrative_followup_end = p['cancelled_at'] if p['cancelled_at'] is not None else self.round
            stage_delays.append({'project': p['id'], 'built_at': p['built_at'], 'commissioned_at': p['commissioned_at'], 'effective_at': p['effective_at'], 'accepted_at': p['accepted_at'], 'construction': p['construction'], 'physical': p['physical'], 'administrative': p['administrative'], 'built_to_effective': p['effective_at'] - p['built_at'] if p['effective_at'] is not None and p['built_at'] is not None else None, 'built_to_effective_censored': p['built_at'] is not None and p['effective_at'] is None and (p['administrative'] != 'cancelled') and (p['physical'] != 'commissioning_failed'), 'built_to_effective_competing_event': 'cancelled' if p['administrative'] == 'cancelled' and p['effective_at'] is None else 'commissioning_failed' if p['physical'] == 'commissioning_failed' else None, 'built_to_effective_followup': max(0, built_followup_end - p['built_at']) if p['built_at'] is not None and p['effective_at'] is None else None, 'effective_to_accepted': p['accepted_at'] - p['effective_at'] if p['accepted_at'] is not None else None, 'effective_to_accepted_censored': p['effective_at'] is not None and p['accepted_at'] is None and (p['administrative'] != 'cancelled'), 'effective_to_accepted_competing_event': 'cancelled' if p['effective_at'] is not None and p['administrative'] == 'cancelled' else None, 'effective_to_accepted_followup': max(0, administrative_followup_end - p['effective_at']) if p['effective_at'] is not None and p['accepted_at'] is None else None})
        return {'schema_version': SCHEMA_VERSION, 'spec_version': SPEC_VERSION, 'scenario_id': self.scenario['id'], 'family': self.scenario['family'], 'environment': self.scenario['environment'], 'round': self.round, 'horizon': None, 'policy': self.policy, 'seed': self.seed, 'initial_issues': len(initial), 'initial_resolved': sum((i['resolved'] is not None for i in initial)), 'initial_resolution_rate': sum((i['resolved'] is not None for i in initial)) / len(initial), 'initial_censored_mean_time': sum((i['resolved'] if i['resolved'] is not None else self.round for i in initial)) / len(initial), 'unresolved_issues': sum((i['resolved'] is None for i in self.issues.values())), 'cumulative_issue_burden': sum(self.burden_by_round), 'normalized_burden': None, 'common_stage_burden': None, 'common_stage_rounds': None, 'common_window_burden': None, 'common_window_rounds': None, 'new_issues': sum((not i['initial'] for i in self.issues.values())), 'recurrent_episodes': sum((i['recurrence'] for i in self.issues.values())), 'repeat_contacts': sum((c['repeat'] for c in self.contacts)), 'facility_at_risk_rounds': sum((e['kind'] == 'external_shock' and e['at_risk'] for e in self.events)), 'at_risk_facility_rounds': sum((e['kind'] == 'external_shock' and e['at_risk'] for e in self.events)), 'repaired_facilities': sum((f['root_repaired'] for f in self.facilities.values())), 'source_repaired_facilities': sum((f['root_repaired'] for f in self.facilities.values())), 'first_routing_match_rate': sum((e['initially_matched'] for e in routed)) / len(routed) if routed else None, 'projects_completed': sum((p['state'] == 'completed' for p in self.projects.values())), 'projects_completed_definition': 'administrative_acceptance_only; use projects_physically_effective for physical effects', 'projects_built': sum((p['construction'] == 'built' for p in self.projects.values())), 'projects_commissioned': sum((p['commissioning_assessment'] is not None and p['commissioning_assessment']['success'] for p in self.projects.values())), 'projects_commissioning_failed': sum((p['physical'] == 'commissioning_failed' for p in self.projects.values())), 'projects_physically_effective': sum((p['physical'] == 'effective' for p in self.projects.values())), 'projects_administratively_accepted': sum((p['administrative'] == 'accepted' for p in self.projects.values())), 'project_stage_delays': stage_delays, 'commissioning_labor': round(sum((e['labor'] for e in resources if e['reason'] == 'commission_project')), 8), 'projects_failed': sum((p['state'] == 'failed' for p in self.projects.values())), 'projects_cancelled': sum((p['state'] == 'cancelled' for p in self.projects.values())), 'labor_spent': round(sum((e['labor'] for e in resources)), 8), 'capital_spent': round(sum((e['capital'] for e in resources)), 8), 'shared_crew_units_spent': sum((e['crew'] for e in resources)), 'tool_process': process, 'communication_labor': round(sum((e['labor'] for e in resources if e['reason'] in COMMUNICATION_KINDS or e['reason'] == 'request_coordination')), 8), 'maintenance_labor': round(sum((e['labor'] for e in resources if e['reason'] == 'shared_record_maintenance')), 8), 'business_rejections': sum((e['status'] == 'business_rejected' for e in results)), 'shared_update_failures': sum((e['kind'] == 'shared_update_failed' for e in self.events)), 'parameter_basis': 'synthetic_uncalibrated', 'unit_of_replication': 'complete_simulation_run'}

    def export_state(self):
        return {'schema_version': SCHEMA_VERSION, 'spec_version': SPEC_VERSION,
                **deepcopy({key: value for key, value in self.__dict__.items() if key != '_indices'})}

    @classmethod
    def from_state(cls, state, workload_mode=None):
        if state.get('schema_version') != SCHEMA_VERSION or state.get('spec_version') != SPEC_VERSION:
            raise ValueError('V3 checkpoints require the exact matching schema and source version')
        saved_mode = state.get('workload_mode')
        if saved_mode not in ('finite',) or (workload_mode is not None and workload_mode != saved_mode):
            raise ValueError('workload mode mismatch')
        if state.get('horizon') is not None:
            raise ValueError('checkpoint horizon is incompatible with workload mode')
        if state.get('scenario', {}).get('horizon', state.get('horizon')) != state.get('horizon'):
            raise ValueError('checkpoint scenario horizon mismatch')
        if saved_mode == 'finite' and state.get('scenario', {}).get('schedule'):
            raise ValueError('finite workload requires a static scenario')
        world = cls.__new__(cls)
        world.__dict__.update(deepcopy({k: v for (k, v) in state.items() if k not in ('schema_version', 'spec_version', '_indices')}))
        world.workload_mode = saved_mode
        world._rebuild_indices()
        return world
