"""Regression for a completed turn's repetition being mistaken for a live stall."""
import json
import unittest
from tools.monitor_000 import repeated_reads


class MonitorTests(unittest.TestCase):
    def test_read_work_repetitions_track_page_and_actual_return(self):
        receipts = [{"round": 0, "actor_id": 1, "call_index": call, "ok": True,
            "action": "ask_env", "args": {}, "observation": json.dumps({"receipts": [
                {"operation": "read_work", "payload": {"section": "projects", "offset": 0},
                 "ok": True, "result": {"value": [], "complete": True}}]})}
            for call in (0, 1, 2)]
        self.assertEqual(len(repeated_reads(receipts, committed_round=0)['active_advisories']), 1)
        receipts[-1]['observation'] = receipts[-1]['observation'].replace('"offset": 0', '"offset": 1')
        self.assertFalse(repeated_reads(receipts, committed_round=0)['active_advisories'])

    def test_same_trace_is_only_advisory_then_closed_by_finish_or_commit(self):
        receipts = [{"round": 0, "actor_id": 3, "call_index": call, "ok": True,
            "action": "read", "args": {"path": "business/inbox-0001.txt"},
            "observation": "[]"}
            for call in (2, 3, 4)]
        open_turn = repeated_reads(receipts, committed_round=0)
        self.assertEqual(len(open_turn["active_advisories"]), 1)
        self.assertFalse(open_turn["active_advisories"][0]["stop_warranted"])
        for committed, completed in ((5, set()), (0, {(0, 3)})):
            result = repeated_reads(receipts, committed_round=committed, completed=completed)
            self.assertFalse(result["active_advisories"])
            self.assertEqual(len(result["historical_repetitions"]), 1)
        receipts[-1]["args"]["path"] = "business/inbox-0002.txt"
        self.assertFalse(repeated_reads(receipts, committed_round=0)["active_advisories"])
