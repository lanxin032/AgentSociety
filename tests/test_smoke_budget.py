import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fixtures import WorkspaceTemporaryDirectory
from smoke_budget import BudgetError, BudgetLedger, MAX_OUTPUT, MODEL


def request(**overrides):
    return {"model": MODEL, "messages": [{"role": "user", "content": "test"}], **overrides}


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "budget.json"

    def test_model_allowlist(self):
        with self.assertRaises(BudgetError):
            BudgetLedger(self.path).reserve(request(model="expensive-model"))

    def test_output_limit_and_single_choice(self):
        _, body = BudgetLedger(self.path).reserve(request(max_tokens=50000, n=20))
        parsed = json.loads(body)
        self.assertEqual(parsed["max_tokens"], MAX_OUTPUT)
        self.assertEqual(parsed["n"], 1)

    def test_streaming_is_rejected(self):
        with self.assertRaises(BudgetError):
            BudgetLedger(self.path).reserve(request(stream=True))

    def test_completion_limit_alias_is_bounded(self):
        _, body = BudgetLedger(self.path).reserve(request(max_completion_tokens=100000))
        self.assertEqual(json.loads(body)["max_tokens"], MAX_OUTPUT)
        self.assertNotIn("max_completion_tokens", json.loads(body))

    def test_budget_is_reserved_before_request(self):
        with self.assertRaises(BudgetError):
            BudgetLedger(self.path, max_rmb=0.000001).reserve(request())

    def test_unknown_usage_keeps_reservation(self):
        ledger = BudgetLedger(self.path)
        index, _ = ledger.reserve(request())
        reserved = ledger.summary()["accounted_rmb"]
        ledger.finish(index, 502)
        self.assertEqual(ledger.summary()["accounted_rmb"], reserved)

    def test_reported_usage_replaces_reservation(self):
        ledger = BudgetLedger(self.path)
        index, _ = ledger.reserve(request())
        ledger.finish(index, 200, {"prompt_tokens": 100, "completion_tokens": 10})
        self.assertAlmostEqual(ledger.summary()["accounted_rmb"], 0.000144)

    def test_reruns_cannot_reset_request_count(self):
        BudgetLedger(self.path, max_requests=1).reserve(request())
        with self.assertRaises(BudgetError):
            BudgetLedger(self.path, max_requests=1).reserve(request())

    def test_concurrent_requests_share_limit(self):
        ledger = BudgetLedger(self.path, max_requests=2)
        accepted = []

        def send():
            try:
                accepted.append(ledger.reserve(request())[0])
            except BudgetError:
                pass

        threads = [threading.Thread(target=send) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(accepted), 2)


if __name__ == "__main__":
    unittest.main()
