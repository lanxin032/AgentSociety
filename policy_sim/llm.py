"""Pure business response validation; no model client or execution loop."""
import json
from .interface import validate_topic_parameters

class ModelOutputError(RuntimeError):
    """Output failures that must not be disguised as an invalid candidate choice."""

    def __init__(self, error_type, message):
        super().__init__(message)
        self.error_type = error_type

def check_completion(choice):
    if choice.finish_reason == 'length':
        raise ModelOutputError('output_truncated', 'Model output reached the token limit; no format repair')
    if choice.finish_reason != 'stop':
        raise ModelOutputError('unexpected_finish_reason', 'Model completion did not stop normally; no format repair')
    if not isinstance(choice.message.content, str):
        raise ModelOutputError('invalid_response_content', 'Model response content is not text; no format repair')
    if not choice.message.content.strip():
        raise ModelOutputError('empty_output', 'Model returned empty content; no format repair')

def validate_action(value, observation):
    if not isinstance(value, dict) or set(value) - {'kind', 'target', 'params', 'reason'}:
        raise ValueError('Action must contain only kind/target/params/reason')
    if not isinstance(value.get('kind'), str) or not isinstance(value.get('params'), dict):
        raise ValueError('Invalid action fields')
    reason = value.get('reason', '')
    if not isinstance(reason, str) or len(reason) > 1000:
        raise ValueError('Invalid observable reason')
    if value.get('kind') == 'propose_project':
        if value.get('target') is not None or not any((a['kind'] == 'propose_project' for a in observation['available_actions'])):
            raise ValueError('No visible topic submission entry')
        params = validate_topic_parameters(value['params'], observation)
        return {'kind': 'propose_project', 'target': None, 'params': params, 'reason': reason}
    wanted = json.dumps({k: value.get(k) for k in ('kind', 'target', 'params')}, sort_keys=True, allow_nan=False, ensure_ascii=False)
    allowed = {json.dumps({k: a.get(k) for k in ('kind', 'target', 'params')}, sort_keys=True, allow_nan=False, ensure_ascii=False) for a in observation['available_actions']}
    if wanted not in allowed:
        raise ValueError('Action does not match a visible candidate')
    return {**value, 'reason': reason}
