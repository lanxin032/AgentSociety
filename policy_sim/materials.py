"""Lawful source projections and grounded policy packets, without model calls.

Raw access is distinct from delivery and from a derived analysis.  Neither the
fixture summarizer nor the production service receives physical world truth.
"""
from copy import deepcopy
import hashlib
import json
MATERIAL_VERSION = 'v3.3-materials-1'
MAX_READS_PER_TURN = 2
MAX_SOURCES_PER_READ = 128

class MaterialValidationError(ValueError):
    """A public contract error with a stable code and exact output location."""

    def __init__(self, message, *, code, path, details=None):
        super().__init__(message)
        (self.code, self.path) = (code, path)
        self.details = deepcopy(details or {})

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

def source(source_id, kind, object_id, created_round, data, actor_id, received_round):
    content = {'source_id': source_id, 'kind': kind, 'object': object_id, 'created_round': created_round, 'data': deepcopy(data)}
    return {**content, 'version': digest(content), 'recipient': actor_id, 'received_round': received_round}

def source_index(row):
    return {key: deepcopy(row[key]) for key in ('source_id', 'kind', 'object', 'created_round', 'version', 'recipient', 'received_round')}

def lawful_sources(world, actor_id):
    if type(actor_id) is not int or actor_id not in (1, 2, 3, 4):
        raise ValueError('Unknown material recipient')
    result = {}
    for ticket in world.tickets.values():
        if actor_id not in (1, 4) and (not world._access(actor_id, ticket['id'])):
            continue
        fields = ('id', 'facility', 'district', 'text', 'category', 'reported', 'public_episode')
        item = source('ticket:' + ticket['id'], 'ticket', ticket['id'], ticket['reported'], {key: ticket[key] for key in fields}, actor_id, ticket['reported'])
        if actor_id in (2, 3):
            item['received_round'] = world._indices['ticket_received'].get((actor_id, ticket['id']), world.round)
        result[item['source_id']] = item
    if actor_id == 4:
        for contact in world.contacts:
            data = {**deepcopy(contact), 'text': world.tickets[contact['ticket']]['text']}
            item = source('contact:' + contact['id'], 'contact', contact['ticket'], contact['reported'], data, actor_id, contact['reported'])
            result[item['source_id']] = item
    for record in world.knowledge[str(actor_id)]['records'].values():
        received = record['created_round']
        if record['author'] != actor_id:
            received = world._indices['record_received'].get((actor_id, record['id']))
            if received is None:
                raise ValueError('Received record lacks lawful delivery provenance')
        item = source('record:' + record['id'], 'record', record['object'], record['created_round'], record, actor_id, received)
        result[item['source_id']] = item
    return dict(sorted(result.items()))

def c_sources(world, sources):
    start = 0
    return [deepcopy(row) for row in sources.values() if row['kind'] == 'contact' and start <= row['created_round'] <= world.round or (row['kind'] == 'record' and row['data']['kind'] == 'project_diagnosis')]

def service_inputs(world, actor_id):
    sources = lawful_sources(world, actor_id)
    inputs = []
    if actor_id == 1 and world._q('A') == 1:
        for ticket in world.tickets.values():
            if ticket['lead'] is not None or ticket['closed']:
                continue
            row = sources['ticket:' + ticket['id']]
            inputs.append({'service': 'A', 'target': ticket['id'], 'actor_id': actor_id, 'sources': [deepcopy(row)], 'rules': {'directory': deepcopy(world.public_directory())}})
    if actor_id == 4 and world._q('C') == 1:
        rows = c_sources(world, sources)
        if rows:
            inputs.append({'service': 'C', 'target': 'current_signal_window', 'actor_id': actor_id, 'sources': rows, 'rules': {'signal_window': None, 'signal_threshold': world.config['signal_threshold'], 'group_by': ['district', 'category'], 'deduplicate_by': 'public_episode', 'root_status': 'unknown_until_lawful_field_investigation'}})
    return inputs

def _text(value, name, maximum=1200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise MaterialValidationError('Invalid ' + name, code='invalid_text', path=name, details={'maximum_characters': maximum})
    return value

def _references(ids, sources, *, kind=None):
    if not isinstance(ids, list) or not ids or len(ids) > MAX_SOURCES_PER_READ:
        raise ValueError('Expected nonempty bounded source_ids')
    if any((not isinstance(s, str) for s in ids)) or len(set(ids)) != len(ids):
        raise ValueError('Source references must be unique strings')
    if any((s not in sources or (kind is not None and sources[s]['kind'] != kind) for s in ids)):
        raise MaterialValidationError('Source reference is outside the supplied lawful materials', code='source_not_supplied', path='source_ids', details={'invalid_source_ids': [s for s in ids if s not in sources or (kind is not None and sources[s]['kind'] != kind)]})
    return [sources[s] for s in ids]

def topic_facts(ids, sources):
    rows = _references(ids, sources, kind='contact')
    groups = {(row['data']['district'], row['data']['category']) for row in rows}
    if len(groups) != 1:
        raise MaterialValidationError('Topic citations must have the same public district and category', code='mixed_topic_group', path='source_ids', details={'required_group_fields': ['district', 'category']})
    (district, category) = next(iter(groups))
    return {'id': district + '|' + category, 'district': district, 'category': category, 'record_count': len({row['data']['public_episode'] for row in rows}), 'facilities': sorted({row['data']['facility'] for row in rows}), 'source_ids': sorted(ids)}

def validate_analysis(value, material, *, provenance, model=None):
    """Ground identifiers/counts in cited inputs; narrative remains a hypothesis."""
    if not isinstance(value, dict):
        raise ValueError('Analysis must be an object')
    sources = {row['source_id']: row for row in material['sources']}
    if material['service'] == 'A':
        if set(value) != {'summary', 'candidates', 'uncertain', 'basis', 'source_ids'}:
            raise ValueError('Invalid A analysis fields')
        _references(value['source_ids'], sources, kind='ticket')
        candidates = value['candidates']
        if not isinstance(candidates, list) or not candidates or len(candidates) > 2 or any((type(x) is not int or x not in (2, 3) for x in candidates)) or (len(set(candidates)) != len(candidates)) or (type(value['uncertain']) is not bool):
            raise ValueError('Invalid A recommendation')
        payload = {'summary': _text(value['summary'], 'summary'), 'candidates': candidates[:], 'uncertain': value['uncertain'], 'basis': _text(value['basis'], 'basis'), 'source_ids': sorted(value['source_ids'])}
    else:
        if set(value) != {'overview', 'topics'} or not isinstance(value['topics'], list) or len(value['topics']) > 12:
            raise ValueError('Invalid C analysis fields')
        topics = []
        for (index, item) in enumerate(value['topics']):
            if not isinstance(item, dict) or set(item) != {'source_ids', 'hypothesis', 'uncertain', 'evidence_gaps', 'suggested_investigation'}:
                raise MaterialValidationError('Invalid C topic fields', code='invalid_topic_fields', path=f'topics/{index}')
            try:
                facts = topic_facts(item['source_ids'], sources)
            except MaterialValidationError as exc:
                raise MaterialValidationError(str(exc), code=exc.code, path=f'topics/{index}/{exc.path}', details=exc.details) from exc
            if type(item['uncertain']) is not bool or not isinstance(item['evidence_gaps'], list) or len(item['evidence_gaps']) > 8:
                raise ValueError('Invalid C uncertainty or gaps')
            topics.append({**facts, 'hypothesis': _text(item['hypothesis'], 'hypothesis'), 'uncertain': item['uncertain'], 'evidence_gaps': [_text(g, 'evidence gap', 400) for g in item['evidence_gaps']], 'suggested_investigation': _text(item['suggested_investigation'], 'investigation'), 'interpretation': 'hypothesis_not_verified_root'})
        seen = {}
        for (index, topic) in enumerate(topics):
            if topic['id'] in seen:
                raise MaterialValidationError('Duplicate C topic', code='duplicate_topic_group', path=f'topics/{index}', details={'first_topic_index': seen[topic['id']], 'duplicate_topic_index': index, 'district': topic['district'], 'category': topic['category']})
            seen[topic['id']] = index
        payload = {'overview': _text(value['overview'], 'overview'), 'topics': topics}
    return {'service': material['service'], 'target': material['target'], 'payload': payload, 'provenance': provenance, 'model': model, 'input_sha256': digest(material), 'source_versions': {key: sources[key]['version'] for key in sorted(sources)}}

def fixture_analysis(material):
    """Transparent offline controller aid, never described as model output."""
    if material['service'] == 'A':
        row = material['sources'][0]
        text = row['data']['text']
        candidates = [3, 2] if '接口破损' in text else [2, 3]
        value = {'summary': text, 'candidates': candidates, 'uncertain': '情况不明' in text or '均需' in text, 'basis': '仅依据诉求表述与职责目录；实际原因待调查。', 'source_ids': [row['source_id']]}
    else:
        groups = {}
        for row in material['sources']:
            if row['kind'] == 'contact':
                groups.setdefault((row['data']['district'], row['data']['category']), []).append(row)
        topics = []
        for (_, rows) in sorted(groups.items()):
            if len({r['data']['public_episode'] for r in rows}) >= material['rules']['signal_threshold']:
                topics.append({'source_ids': [r['source_id'] for r in rows], 'hypothesis': '同类诉求可能有关联，共同根因尚未证实。', 'uncertain': True, 'evidence_gaps': ['现场连接关系及缺陷证据'], 'suggested_investigation': '依法开展现场管线溯源并取得专业意见。'})
        value = {'overview': '依据本窗口合法诉求记录整理，假设不能替代调查。', 'topics': topics}
    return validate_analysis(value, material, provenance='rule_fixture')

def analysis_value(packet):
    if packet['service'] == 'A':
        return deepcopy(packet['payload'])
    return {'overview': packet['payload']['overview'], 'topics': [{key: deepcopy(topic[key]) for key in ('source_ids', 'hypothesis', 'uncertain', 'evidence_gaps', 'suggested_investigation')} for topic in packet['payload']['topics']]}

def validate_packet(packet, material, *, provenance, model=None):
    rebuilt = validate_analysis(analysis_value(packet), material, provenance=provenance, model=model)
    if packet != rebuilt:
        raise ValueError('Analysis packet differs from its lawful source projection')
    return rebuilt

def projection(world, actor_id):
    sources = lawful_sources(world, actor_id)
    (raw_ids, inline_ids) = ([], [])
    if actor_id == 1:
        if world._q('A') == 0:
            raw_ids = ['ticket:' + t['id'] for t in world.tickets.values() if t['lead'] is None and (not t['closed'])]
    elif actor_id == 4:
        if world._q('C') == 0:
            raw_ids = [r['source_id'] for r in c_sources(world, sources) if r['kind'] == 'contact']
    else:
        inline_ids = [key for (key, row) in sources.items() if row['kind'] == 'ticket']
    inline_ids += [key for (key, row) in sources.items() if row['kind'] == 'record']
    analyses = [fixture_analysis(item) for item in service_inputs(world, actor_id)]
    return {'version': MATERIAL_VERSION, 'as_of_round': world.round, 'source_index': [source_index(row) for row in sources.values()], 'raw': [deepcopy(sources[key]) for key in raw_ids], 'delivered_raw_ids': sorted(set(raw_ids + inline_ids)), 'analyses': analyses, 'read_limit': None, 'reads_used': 0, 'window_start': 0, 'note': '索引表示访问权限；原文送达与分析引用分列。摘要和假设不等于实地证据。'}

def represented_ids(materials):
    ids = set(materials.get('delivered_raw_ids', []))
    for packet in materials.get('analyses', []):
        payload = packet['payload']
        ids.update(payload.get('source_ids', []))
        for topic in payload.get('topics', []):
            ids.update(topic['source_ids'])
    return ids

def read_materials(world, actor_id, ids):
    sources = lawful_sources(world, actor_id)
    rows = _references(ids, sources)
    return {'version': MATERIAL_VERSION, 'actor_id': actor_id, 'round': world.round, 'sources': deepcopy(rows)}

def apply_read(observation, result):
    if result.get('actor_id') != observation['actor_id'] or result.get('round') != observation['round']:
        raise ValueError('Material response belongs to a different actor/round')
    obs = deepcopy(observation)
    materials = obs['materials']
    limit = materials.get('read_limit', MAX_READS_PER_TURN)
    if limit is not None and materials['reads_used'] >= limit:
        raise ValueError('Same-round material read limit reached')
    available = {row['source_id']: row for row in materials['source_index']}
    rows = result.get('sources')
    if not isinstance(rows, list) or not rows or len(rows) > MAX_SOURCES_PER_READ:
        raise ValueError('Invalid material response')
    existing = {r['source_id']: r for r in materials['raw']}
    for row in rows:
        if not isinstance(row, dict) or source_index(row) != available.get(row.get('source_id')):
            raise ValueError('Material response exceeds the observed source version/permission')
        rebuilt = source(row['source_id'], row['kind'], row['object'], row['created_round'], row['data'], row['recipient'], row['received_round'])
        if rebuilt != row:
            raise ValueError('Material content does not match its version')
        existing[row['source_id']] = deepcopy(row)
    materials['raw'] = [existing[key] for key in sorted(existing)]
    materials['delivered_raw_ids'] = sorted(set(materials['delivered_raw_ids']) | set(existing))
    materials['reads_used'] += 1
    from .interface import decorate_observation
    return decorate_observation(obs)
