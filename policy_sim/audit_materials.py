"""Independent provenance checks for delivered materials and bounded decisions."""
from collections import defaultdict
from copy import deepcopy
import json
import uuid
from policy_sim.profiles import MODEL
from .interface import INTERFACE_FIELDS, decorate_observation, raw_observation, decode_candidate_choice, decode_material_read
from .materials import source, source_index, digest, validate_packet, validate_analysis, apply_read
from .normalization import verify_normalization, NormalizationEvidenceError

def audit_projection(expected, actual, service_materials=None):
    if not isinstance(actual, dict):
        return ['Observation must be an object']
    try:
        (expected, actual) = json.loads(json.dumps([expected, actual], ensure_ascii=False, allow_nan=False))
        for value in (expected, actual):
            value.pop('policy', None)
        if not INTERFACE_FIELDS <= set(actual):
            return ['Observation lacks its derived interface']
        fresh = decorate_observation(actual)
        if any((actual[k] != fresh[k] for k in INTERFACE_FIELDS)):
            return ['Observation derived interface differs from its actual context']
        (expected, actual) = (raw_observation(expected), raw_observation(actual))
        reference = expected['materials']['analyses']
        provided = actual['materials']['analyses']
        if len(reference) != len(provided):
            return ['Policy analysis delivery differs from the role/policy projection']
        inputs = {(m['service'], m['target']): m for m in service_materials or []}
        for (baseline, packet) in zip(reference, provided):
            if packet == baseline:
                continue
            key = (baseline['service'], baseline['target'])
            if key not in inputs:
                return ['Changed policy packet requires its reconstructed lawful source inputs']
            validate_packet(packet, inputs[key], provenance='real_llm_visible_material_only', model=MODEL)
        expected['materials']['analyses'] = deepcopy(provided)
        if expected != actual:
            return ['Observation differs from reconstructed role whitelist or delivered material boundary']
        return []
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        return ['Invalid material observation: ' + str(exc)]

def _material_for_observation(material, obs):
    """Bind service raw inputs to hashes already checked by physical-world replay."""
    if set(material) != {'service', 'target', 'actor_id', 'sources', 'rules'}:
        raise ValueError('Unexpected policy service input fields')
    (service, actor) = (material['service'], obs['actor_id'])
    if material['actor_id'] != actor or (service, actor) not in (('A', 1), ('C', 4)):
        raise ValueError('Policy service has an invalid role')
    index = {r['source_id']: r for r in obs['materials']['source_index']}
    if service == 'A':
        ticket = next((t for t in obs['visible_tickets'] if t['id'] == material['target']))
        if ticket.get('a_offered') is not True or ticket['lead'] is not None or ticket['closed']:
            raise ValueError('A generation lacks an eligible pending ticket')
        expected_ids = [ticket['source_id']]
        rules = {'directory': obs['public_rules']['directory']}
    else:
        if material['target'] != 'current_signal_window' or not any((p['service'] == 'C' for p in obs['materials']['analyses'])):
            raise ValueError('C generation lacks a delivered C service')
        record_ids = {'record:' + r['id'] for p in obs['projects'] for r in p['received_records'] if r['kind'] == 'project_diagnosis'}
        expected_ids = sorted((key for (key, row) in index.items() if row['kind'] == 'contact' and row['created_round'] >= obs['materials']['window_start'] or key in record_ids))
        topic_rules = obs['public_rules']['topic_analysis']
        rules = {'signal_window': topic_rules['window_rounds'], 'signal_threshold': topic_rules['minimum_distinct_episodes'], 'group_by': ['district', 'category'], 'deduplicate_by': 'public_episode', 'root_status': 'unknown_until_lawful_field_investigation'}
    if material['rules'] != rules or [r['source_id'] for r in material['sources']] != expected_ids:
        raise ValueError('Policy input differs from its mandatory raw-source scope/rules')
    for row in material['sources']:
        if source_index(row) != index.get(row['source_id']):
            raise ValueError('Policy service used a source outside the role/version index')
        if row != source(row['source_id'], row['kind'], row['object'], row['created_round'], row['data'], row['recipient'], row['received_round']):
            raise ValueError('Policy raw input does not match the replayed source content hash')

def audit_services(rows, observations, cache=None):
    from .services import service_messages, service_repair_prompt
    (errors, groups, packets) = ([], defaultdict(list), {})
    lookup = {(r['round'], r['actor_id']): r['observation'] for r in observations}
    try:
        for row in rows:
            groups[row['input_sha256']].append(row)
        for (key, attempts) in groups.items():
            try:
                if len(attempts) not in (1, 2) or [r['attempt'] for r in attempts] != list(range(len(attempts))):
                    raise ValueError('Policy service attempts exceed one repair or repeat cached input')
                material = attempts[0]['material']
                if digest(material) != key:
                    raise ValueError('Policy input hash mismatch')
                obs = lookup[attempts[0]['round'], attempts[0]['actor_id']]
                _material_for_observation(material, obs)
                messages = service_messages(material)
                for (index, row) in enumerate(attempts):
                    if True and row.get('output_contract') != 'strict_json_1':
                        raise ValueError('Finite service lacks its strict output contract')
                    if row['material'] != material or row['messages'] != messages or row['service'] != material['service'] or (row['target'] != material['target']) or (row['round'] != attempts[0]['round']) or (row['actor_id'] != material['actor_id']):
                        raise ValueError('Policy service transcript/input identity mismatch')
                    if row.get('finish_reason') != 'stop' or not isinstance(row.get('response'), str) or (not row['response'].strip()):
                        raise ValueError('Committed service includes failed model output')
                    try:
                        packet = validate_analysis(verify_normalization(row, material, service=True), material, provenance='real_llm_visible_material_only', model=MODEL)
                    except (ValueError, TypeError, KeyError) as exc:
                        if isinstance(exc, NormalizationEvidenceError):
                            raise
                        if row.get('validation_error') != str(exc) or index == len(attempts) - 1 or 'packet' in row:
                            raise ValueError('Policy repair lacks its exact failure evidence')
                        messages += [{'role': 'assistant', 'content': row['response']}, {'role': 'user', 'content': service_repair_prompt(exc, material['service'])}]
                    else:
                        if row.get('packet') != packet or index != len(attempts) - 1 or 'validation_error' in row:
                            raise ValueError('Policy packet differs from actual validated model output')
                        packets[key] = packet
            except (ValueError, TypeError, KeyError, IndexError, StopIteration) as exc:
                errors.append('Policy service ' + str(key) + ': ' + str(exc))
        for row in observations:
            for packet in row['observation']['materials']['analyses']:
                if packet != packets.get(packet.get('input_sha256')):
                    errors.append('Delivered policy packet has no matching real service/cache provenance')
        if cache is not None and cache != packets:
            errors.append('Persisted policy cache differs from validated generated packets')
    except (ValueError, TypeError, KeyError) as exc:
        errors.append('Malformed policy service evidence: ' + str(exc))
    return errors

def replay_reads(world, observation, rows):
    current = deepcopy(observation)
    for (index, row) in enumerate(rows):
        if row.get('read_index') != index or row.get('actor_id') != current['actor_id'] or row.get('round') != current['round'] or (row.get('before_context_sha256') != current['context_sha256']):
            raise ValueError('Material query identity/order/context mismatch')
        result = world.read_materials(current['actor_id'], row['source_ids'])
        if result != row.get('result'):
            raise ValueError('Material query returned unavailable, altered or wrong-version sources')
        current = apply_read(current, result)
        if row.get('after_context_sha256') != current['context_sha256']:
            raise ValueError('Material query result context hash mismatch')
    return current
