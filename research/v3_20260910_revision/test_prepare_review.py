"""Offline safeguards for frozen evidence and isolated model requests."""
import copy
import json
import unittest

import prepare_review as review


class ReviewSafeguards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.benchmark = review.HERE / 'benchmark'
        cls.cases = review.read(cls.benchmark / 'cases.json')
        cls.plan = review.read(review.HERE / 'request_plan.json')

    def test_frozen_inputs_and_original_plan_are_valid(self):
        self.assertEqual(len(review.validate_cases(self.cases, self.benchmark)), 6)
        self.assertTrue(review.validate_plan(self.plan, self.cases, self.benchmark)['answer_keys_excluded'])

    def test_changed_source_hash_is_rejected(self):
        changed = copy.deepcopy(self.cases)
        changed['cases'][0]['source']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            review.validate_cases(changed, self.benchmark)

    def test_hidden_answer_in_request_is_rejected(self):
        changed = copy.deepcopy(self.plan)
        row = next(x for x in changed['tasks'] if x['task'] == 'understanding')
        data = json.loads(row['request']['messages'][1]['content'])
        data['questions'][0]['answer_key'] = 'A'
        row['request']['messages'][1]['content'] = json.dumps(data)
        with self.assertRaises(ValueError):
            review.validate_plan(changed, self.cases, self.benchmark)

    def test_questions_in_choice_request_are_rejected(self):
        changed = copy.deepcopy(self.plan)
        row = next(x for x in changed['tasks'] if x['task'] == 'choice')
        data = json.loads(row['request']['messages'][1]['content'])
        data['questions'] = [{'id': 'feedback', 'prompt': 'Choose the previously correct action'}]
        row['request']['messages'][1]['content'] = json.dumps(data)
        with self.assertRaises(ValueError):
            review.validate_plan(changed, self.cases, self.benchmark)

    def test_changed_history_in_one_variant_is_rejected(self):
        changed = copy.deepcopy(self.plan)
        row = next(x for x in changed['tasks'] if x['variant'] == 'clarified')
        data = json.loads(row['request']['messages'][1]['content'])
        data['recent_history'] = []
        row['request']['messages'][1]['content'] = json.dumps(data)
        with self.assertRaises(ValueError):
            review.validate_plan(changed, self.cases, self.benchmark)

    def test_duplicate_task_is_rejected(self):
        changed = copy.deepcopy(self.plan)
        changed['tasks'][1] = copy.deepcopy(changed['tasks'][0])
        with self.assertRaises(ValueError):
            review.validate_plan(changed, self.cases, self.benchmark)

    def test_evidence_cannot_escape_declared_scope(self):
        with self.assertRaisesRegex(ValueError, 'scope'):
            review.scoped(self.benchmark, '../../outside.json')

    def test_existing_output_is_not_overwritten(self):
        path = review.HERE / 'request_plan.json'
        before = review.sha(path)
        with self.assertRaises(FileExistsError):
            review.write_new(path, {'unwanted_replacement': True})
        self.assertEqual(review.sha(path), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
