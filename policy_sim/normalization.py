"""Lossless V3 wire compatibility, bound only to the current supplied context.

This module neither selects actions nor creates, combines or repairs hypotheses.
Semantic permission and workflow validation remains with its original owners.
"""
from copy import deepcopy
import json
import math

from .interface import canonical, decorate_observation


class NormalizationEvidenceError(ValueError):
    """The saved conversion is not the conversion implied by the raw response."""


def _parse(text):
    if not isinstance(text, str):
        raise ValueError('Model response must be text')
    text, rules = text.strip(), []
    if text.startswith('```'):
        if '\n' not in text or text.count('```') != 2 or not text.endswith('```'):
            raise ValueError('Incomplete JSON code fence')
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        rules.append({'rule': 'remove_json_fence', 'path': '$'})
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError('Expected one JSON object')
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('Nonfinite JSON number')
        if isinstance(item, dict):
            for child in item.values():
                finite(child)
        elif isinstance(item, list):
            for child in item:
                finite(child)
    finite(value)
    return value, rules


def _source_ids(ids, allowed, rules, path):
    if not isinstance(ids, list):
        return ids  # The owning validator reports the schema violation.
    result = []
    for index, key in enumerate(ids):
        mapped = key
        if isinstance(key, str) and key not in allowed:
            matches = [full for full in allowed if ':' in full and full.split(':', 1)[1] == key]
            if len(matches) > 1:
                raise ValueError('Ambiguous unprefixed source reference: ' + key)
            if len(matches) == 1:
                mapped = matches[0]
                rules.append({'rule': 'restore_source_prefix', 'path': f'{path}/{index}',
                              'from': key, 'to': mapped})
        result.append(mapped)
    return result


def normalize_decision(text, observation):
    value, rules = _parse(text)
    if 'action' in value:
        if set(value) != {'action'} or not isinstance(value['action'], dict) or 'action' in value['action']:
            raise ValueError('Only one unambiguous action wrapper is accepted')
        value = value['action']
        rules.append({'rule': 'unwrap_action', 'path': '$'})
    value = deepcopy(value)
    allowed = {r['source_id'] for r in observation.get('materials', {}).get('source_index', [])}
    if 'read_materials' in value:
        if set(value) != {'read_materials', 'reason'}:
            raise ValueError('Material read requires read_materials and reason')
        value['read_materials'] = _source_ids(value['read_materials'], allowed, rules, '/read_materials')
        return value, rules
    if set(value) - {'candidate_id', 'reason', 'analysis', 'kind', 'target', 'params'}:
        raise ValueError('Unexpected decision fields')
    fresh = decorate_observation(observation)
    option = next((o for o in fresh['candidate_options']
                   if type(value.get('candidate_id')) is str and o['candidate_id'] == value['candidate_id']), None)
    if option is None:
        raise ValueError('Unknown or stale candidate_id for this observation')
    for key in ('kind', 'target'):
        if key in value:
            if canonical(value[key]) != canonical(option[key]):
                raise ValueError('Redundant decision field conflicts with candidate: ' + key)
            del value[key]
            rules.append({'rule': 'remove_matching_candidate_field', 'path': '/' + key})
    if 'params' in value:
        params = value['params']
        if option['kind'] == 'propose_project' and isinstance(params, dict) and set(params) == {'source_ids', 'hypothesis'}:
            if 'analysis' in value and canonical(value['analysis']) != canonical(params):
                raise ValueError('params and analysis conflict')
            if 'analysis' not in value:
                value['analysis'] = deepcopy(params)
            del value['params']
            rules.append({'rule': 'topic_params_as_analysis', 'path': '/params'})
        else:
            if canonical(params) != canonical(option['params']):
                raise ValueError('Redundant decision field conflicts with candidate: params')
            del value['params']
            rules.append({'rule': 'remove_matching_candidate_field', 'path': '/params'})
    if isinstance(value.get('analysis'), dict) and 'source_ids' in value['analysis']:
        value['analysis']['source_ids'] = _source_ids(value['analysis']['source_ids'], allowed, rules, '/analysis/source_ids')
    return value, rules


def normalize_service(text, material, *, strict=False):
    value, rules = _parse(text)
    if strict:
        if rules:
            raise ValueError('Return one JSON object without code fences or packaging')
        return value, []
    allowed = {r['source_id'] for r in material['sources']}
    if material['service'] == 'A' and 'source_ids' in value:
        value['source_ids'] = _source_ids(value['source_ids'], allowed, rules, '/source_ids')
    elif material['service'] == 'C' and isinstance(value.get('topics'), list):
        for index, topic in enumerate(value['topics']):
            if isinstance(topic, dict) and 'source_ids' in topic:
                topic['source_ids'] = _source_ids(topic['source_ids'], allowed, rules, f'/topics/{index}/source_ids')
    return value, rules


def verify_normalization(trace, context, *, service=False):
    """Rebuild from raw bytes; a mismatched audit claim is never a model error."""
    normalizer = (lambda text, material: normalize_service(text, material,
        strict=trace.get('output_contract') == 'strict_json_1')) if service else normalize_decision
    try:
        value, rules = normalizer(trace.get('response'), context)
    except (ValueError, TypeError, KeyError) as exc:
        if ('normalized_response' not in trace or trace['normalized_response'] is not None
                or trace.get('normalization') != []):
            raise NormalizationEvidenceError('Invalid response has inconsistent normalization evidence') from exc
        raise
    if ('normalized_response' not in trace or canonical(trace['normalized_response']) != canonical(value)
            or trace.get('normalization') != rules):
        raise NormalizationEvidenceError('Normalization evidence differs from the raw response and current context')
    return value
