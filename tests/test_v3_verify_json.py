"""Regression for the JSON transport boundary, outside frozen runtime sources.

The verifier compares expected projections at the same JSON transport boundary.
No simulator business rules are changed by these tests.
"""
import json
import unittest
from copy import deepcopy

from policy_v3.verify import audit_observation, _hash


class ObservationJSONTransportTests(unittest.TestCase):
    def test_professional_review_integer_keys_survive_json_transport(self):
        expected = {'actor_id': 4, 'round': 6, 'visible_tickets': [], 'available_actions': [],
                    'projects': [{'id': 'P:1', 'received_reviews': {2: 'approve', 3: 'approve'}}]}
        saved = json.loads(json.dumps(expected, ensure_ascii=False, allow_nan=False))
        self.assertEqual(saved['projects'][0]['received_reviews'], {'2': 'approve', '3': 'approve'})
        self.assertEqual(audit_observation(expected, saved), [])

    def test_json_key_normalization_must_not_hide_new_privileged_fields(self):
        expected = {'actor_id': 4, 'round': 6, 'visible_tickets': [], 'available_actions': [],
                    'projects': [{'id': 'P:1', 'received_reviews': {2: 'approve', 3: 'approve'}}]}
        saved = json.loads(json.dumps(expected, ensure_ascii=False, allow_nan=False))
        saved['projects'][0]['physical_ready_round'] = 3
        self.assertTrue(audit_observation(expected, saved))

    def test_current_derived_fields_cannot_be_dropped_or_tampered(self):
        from policy_v3.core import PolicyWorld
        from policy_v3.interface import raw_observation
        expected = PolicyWorld('001', seed=1).observe(4)
        self.assertEqual(audit_observation(expected, json.loads(json.dumps(expected))), [])
        self.assertTrue(audit_observation(expected, raw_observation(expected)))
        for field in ('context_sha256', 'candidate_options', 'evidence_index'):
            altered = deepcopy(expected); altered[field] = 'tampered'
            self.assertTrue(audit_observation(expected, altered), field)

    def test_real_public_a_change_is_redecorated_without_allowing_stale_ids(self):
        from policy_v3.core import PolicyWorld
        from policy_v3.interface import decorate_observation
        expected = PolicyWorld('100', seed=1).observe(1)
        actual = deepcopy(expected)
        ticket = actual['visible_tickets'][0]
        first = 3 if ticket['recommendation']['candidates'][0] == 2 else 2
        material = {'ticket': {k: ticket[k] for k in ('text', 'category', 'district', 'facility')},
                    'directory': actual['public_rules']['directory']}
        ticket['recommendation'] = {'provenance': 'real_llm_visible_material_only',
            'model': 'deepseek-v4-flash', 'candidates': [first, 5-first], 'uncertain': True,
            'basis': 'public material only', 'input_sha256': _hash(material)}
        for action in actual['available_actions']:
            if action['target'] == ticket['id'] and action['params'].get('use_recommendation'):
                action['params']['department'] = first
        self.assertTrue(audit_observation(expected, actual))  # stale derived fields
        actual = decorate_observation(actual)
        self.assertEqual(audit_observation(expected, json.loads(json.dumps(actual))), [])
        actual['candidate_options'] = deepcopy(expected['candidate_options'])
        self.assertTrue(audit_observation(expected, actual))


if __name__ == '__main__':
    unittest.main()
