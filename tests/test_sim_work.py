"""Bounded native workspace access preserves complete lawful evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from policy_sim.core import PolicyWorld
from policy_sim.materials import read_materials
from policy_sim.interface import dispatch_plan
from policy_sim.work import WorkContext, lawful_work, _size, WORK_BYTES


class DispatchPlanTests(unittest.TestCase):
    """Known answers for the deterministic ask_env translation."""

    def test_canonical_and_tolerant_templates_dispatch(self):
        self.assertEqual(dispatch_plan('submit candidate {candidate_id} with reason {reason}',
                                       {'candidate_id': 'C01-abc', 'reason': '依据材料申请。'}),
                         ('submit', {'candidate_id': 'C01-abc', 'reason': '依据材料申请。'}))
        self.assertEqual(dispatch_plan('submit candidate {candidate_id} with reason {reason}',
                                       {'candidate_id': 'C01-abc', 'reason': 'r',
                                        'analysis': {'source_ids': ['contact:1'], 'hypothesis': 'h'}}),
                         ('submit', {'candidate_id': 'C01-abc', 'reason': 'r',
                                     'analysis': {'source_ids': ['contact:1'], 'hypothesis': 'h'}}))
        self.assertEqual(dispatch_plan('read_work section {section} offset {offset}',
                                       {'section': 'public_rules', 'offset': 2}),
                         ('read_work', {'section': 'public_rules', 'offset': 2}))
        self.assertEqual(dispatch_plan('read_work section {section}', {'section': 'inbox'}),
                         ('read_work', {'section': 'inbox', 'offset': 0}))
        self.assertEqual(dispatch_plan('read_materials source_ids {source_ids} reason {reason}',
                                       {'source_ids': ['contact:1', 'contact:2'], 'reason': '核对'}),
                         ('read_materials', {'read_materials': ['contact:1', 'contact:2'], 'reason': '核对'}))
        # Forms the real model produced in attempt-0056 stay dispatchable.
        self.assertEqual(dispatch_plan('read_materials source_id {source_id}', {'source_id': 'contact:10'}),
                         ('read_materials', {'read_materials': ['contact:10'], 'reason': 'ask_env read_materials'}))
        self.assertEqual(dispatch_plan('observe the current work', {}), ('observe', {}))

    def test_unknown_or_malformed_asks_fail_with_corrective_errors(self):
        for instruction, variables in (('delete everything', {}), ('', {}),
                                       ('submit candidate {candidate_id} with reason {reason}',
                                        {'candidate_id': 'C01'}),
                                       ('submit candidate {candidate_id} with reason {reason}',
                                        {'candidate_id': 'C01', 'reason': 'r', 'extra': 1}),
                                       ('submit candidate {candidate_id} with reason {reason}',
                                        {'candidate_id': 'C01', 'reason': 'r', 'analysis': 'text'}),
                                       ('read_work section {section} offset {offset}',
                                        {'section': 'inbox', 'offset': True}),
                                       ('read_materials source_ids {source_ids}',
                                        {'source_ids': 'contact:1', 'read_materials': ['contact:2']}),
                                       ('read_materials source_ids {source_ids}', {'source_ids': 7}),
                                       ('observe now', {'section': 'inbox'})):
            with self.subTest(instruction=instruction, variables=variables):
                with self.assertRaises(ValueError):
                    dispatch_plan(instruction, variables)


class WorkContextTests(unittest.TestCase):
    def test_empty_status_reply_carries_inband_note_everywhere(self):
        # attempt-0059 regression: a contentless reply must say so in-band,
        # or its recipient re-reads it until the official loop exhausts.
        from policy_sim.work import read_work_section
        obs = PolicyWorld(policy='000', seed=3001).observe(4)
        obs['inbox'] = [{'id': 'message-11', 'sender': 3, 'recipient': 4, 'object': 'P:1',
            'kind': 'status_reply', 'created_round': 7, 'delivered_round': 8, 'replied': False,
            'payload': {'records': []}}]
        obs['sent_messages'] = [deepcopy(obs['inbox'][0])]
        context = WorkContext(obs)
        overview = context.current_work['inbox']['recent'][0]
        self.assertIn('空records即完整答复', overview['content_note'])
        page = read_work_section(context.observation, 'inbox')
        self.assertIn('空records即完整答复', page['value'][0]['content_note'])
        sent = read_work_section(context.observation, 'sent_messages')
        self.assertIn('content_note', sent['value'][0])

    def test_read_pages_anchor_state_time_and_prompt_forbids_polling(self):
        # attempt-0060 regression: pages must state their as-of round and the
        # persistent guidance must forbid intra-round polling and last-turn submits.
        from policy_sim.work import read_work_section
        from policy_sim.prompt import WORLD_DESCRIPTION
        obs = PolicyWorld(policy='000', seed=3001).observe(2)
        obs['round'] = 7
        self.assertEqual(read_work_section(obs, 'visible_tickets')['as_of_round'], 7)
        self.assertEqual(read_work_section(obs, 'topics')['as_of_round'], 7)
        self.assertIn('as_of_round', WORLD_DESCRIPTION)
        self.assertIn('不能等待前置任务完成', WORLD_DESCRIPTION)
        self.assertIn('不要把提交留到本轮最后一次工具调用', WORLD_DESCRIPTION)

    def test_batch_limit_errors_state_the_bound_and_teach_it(self):
        # attempt-0061 regression: a rejected request must say its exact limit,
        # and the taught grammar must state it before the model has to ask.
        from policy_sim.interface import decode_material_read, validate_topic_parameters, decorate_observation
        from policy_sim.work import WorkContext
        obs = decorate_observation(PolicyWorld(policy='000', seed=3001).observe(1))
        five = {'read_materials': [r['source_id'] for r in obs['materials']['source_index'][:5]], 'reason': 'check'}
        with self.assertRaises(ValueError) as ctx:
            decode_material_read(five, obs)
        self.assertIn('at most 4', str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            validate_topic_parameters({'source_ids': ['a'] * 5, 'hypothesis': 'x'}, obs)
        self.assertIn('unique', str(ctx.exception))
        overview = WorkContext(PolicyWorld(policy='000', seed=3001).observe(1)).current_work
        self.assertIn('每次最多4个', overview['query_help'])

    def test_pace_note_annotates_only_late_reads_deterministically(self):
        # attempt-0063 regression: once the actor's own loop is more than half
        # spent, read results must state that fact in-band; the audit replays
        # the identical annotation from the recorded call index.
        from policy_sim.work import paced, read_work_section, PACE_FROM_CALL
        obs = PolicyWorld(policy='000', seed=3001).observe(2)
        early = paced(PACE_FROM_CALL - 1, read_work_section(obs, 'visible_tickets'))
        late = paced(PACE_FROM_CALL, read_work_section(obs, 'visible_tickets'))
        self.assertNotIn('pace_note', early)
        self.assertIn('pace_note', late)
        self.assertIn('finish', late['pace_note'])
        self.assertEqual(paced(None, dict(early)), early)

    def test_identical_reread_within_round_serves_stub_not_content(self):
        # attempt-0059/0060/0063/0067 regression class: an identical re-read in
        # the same round must not re-serve its content; the stub is the only
        # honest answer and the material quota is not charged again.
        from policy_sim.materials import read_materials
        from policy_sim.work import read_stub, material_stub
        world = PolicyWorld(policy='000', seed=3001)
        obs = world.observe(2)
        context = WorkContext(obs)
        first = context.read_work_once('inbox', 0, ask_id='first')
        self.assertNotIn('unchanged_since_last_read', first)
        second = context.read_work_once('inbox', 0, visible_asks=['first'])
        self.assertEqual(second, read_stub('inbox', 0, 2))
        self.assertIn('不会产生新信息', second['note'])
        other = context.read_work_once('public_rules', 0)
        self.assertNotIn('unchanged_since_last_read', other)
        sid = 'contact:fixture-1'
        self.assertFalse(context.seen_materials([sid]))
        context.mark_materials([sid], 'material-read')
        self.assertTrue(context.seen_materials([sid], ['material-read']))
        self.assertFalse(context.seen_materials([sid], []))
        self.assertEqual(material_stub([sid], 2)['read_count_this_turn'], 2)
        self.assertEqual(context.read_work_once('inbox', 0, visible_asks=['first']), read_stub('inbox', 0, 3))
        self.assertEqual(context.read_work_once('inbox', 0), first)
