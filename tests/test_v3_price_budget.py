"""Offline per-request prices; no production ledger or API access."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fixtures import WorkspaceTemporaryDirectory
from smoke_budget import BudgetError, BudgetLedger, MODEL


def payload():
    return {"model": MODEL, "messages": [{"role": "user", "content": "test"}]}


class PriceBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "budget.json"

    def test_zero_prices_still_enforce_request_cap_and_keep_unknown_usage(self):
        ledger = BudgetLedger(self.path, max_requests=1, max_rmb=0,
                              input_rate=0, output_rate=0, price_version="free-evidence-v3")
        index, _ = ledger.reserve(payload())
        ledger.finish(index, 502)
        self.assertEqual(ledger.records[0]["reserved_rmb"], 0)
        self.assertNotIn("estimated_rmb", ledger.records[0])
        self.assertEqual(ledger.summary()["unknown_usage_requests"], 1)
        self.assertEqual(ledger.summary()["requests"], 1)
        with self.assertRaises(BudgetError):
            ledger.reserve(payload())
        again = BudgetLedger(self.path, max_requests=1, input_rate=0, output_rate=0)
        with self.assertRaises(BudgetError):
            again.reserve(payload())

    def test_mixed_history_is_preserved_without_repricing(self):
        historical = [{"request": 1, "status": 200, "reserved_rmb": 0.03,
                       "estimated_rmb": 0.0024, "prompt_tokens": 1000, "completion_tokens": 500},
                      {"request": 2, "status": 502, "reserved_rmb": 0.02}]
        self.path.write_text(json.dumps(historical), encoding="utf-8")
        original_bytes = self.path.read_bytes()
        ledger = BudgetLedger(self.path, max_requests=3, input_rate=0, output_rate=0, price_version="v3")
        self.assertEqual(self.path.read_bytes(), original_bytes)
        index, _ = ledger.reserve(payload())
        ledger.finish(index, 200, {"prompt_tokens": 1000, "completion_tokens": 500})
        self.assertEqual(ledger.records[:2], historical)
        self.assertEqual(ledger.records[-1]["estimated_rmb"], 0)
        self.assertAlmostEqual(ledger.summary()["accounted_rmb"], 0.0224)

    def test_settlement_uses_frozen_record_price_after_attribute_change_and_reload(self):
        ledger = BudgetLedger(self.path, input_rate=2, output_rate=4, price_version="paid")
        index, _ = ledger.reserve(payload())
        ledger.input_rate, ledger.output_rate, ledger.price_version = 0, 0, "free"
        ledger.finish(index, 200, {"prompt_tokens": 1000, "completion_tokens": 100})
        self.assertAlmostEqual(ledger.records[index]["estimated_rmb"], 0.0024)
        self.assertEqual(ledger.records[index]["price_version"], "paid")
        again = BudgetLedger(self.path, input_rate=99, output_rate=99)
        again.finish(index, 200, {"prompt_tokens": 1000, "completion_tokens": 100})
        self.assertAlmostEqual(again.records[index]["estimated_rmb"], 0.0024)

    def test_legacy_pending_record_uses_original_prices(self):
        self.path.write_text(json.dumps([{"request": 1, "status": "reserved", "reserved_rmb": 0.01}]))
        ledger = BudgetLedger(self.path, input_rate=0, output_rate=0)
        ledger.finish(0, 200, {"prompt_tokens": 100, "completion_tokens": 10})
        self.assertAlmostEqual(ledger.records[0]["estimated_rmb"], 0.000144)
        self.assertNotIn("input_rate", ledger.records[0])

    def test_invalid_rates_are_rejected_without_creating_ledger(self):
        for value in (-1, True, False, float("nan"), float("inf"), -float("inf"), "0", None):
            for field in ("input_rate", "output_rate"):
                with self.subTest(value=value, field=field), self.assertRaises(BudgetError):
                    BudgetLedger(self.path, **{field: value})
        self.assertFalse(self.path.exists())

    def test_safe_metadata_is_frozen_and_reserved_fields_are_rejected(self):
        metadata = {"authorization_id": "v3-test", "price_evidence_sha256": "a" * 64}
        ledger = BudgetLedger(self.path, request_metadata=metadata)
        metadata["authorization_id"] = "caller-mutated"
        index, _ = ledger.reserve(payload())
        ledger.request_metadata["authorization_id"] = "later-request"
        self.assertEqual(ledger.records[index]["authorization_id"], "v3-test")
        for field in ("request", "status", "reserved_rmb", "estimated_rmb", "model", "input_rate", "api_key"):
            with self.subTest(field=field), self.assertRaises(BudgetError):
                BudgetLedger(self.path, request_metadata={field: "override"})

    def test_invalid_price_metadata_and_mutated_rate_rejected(self):
        for metadata in ({"price_evidence_sha256": "not-sha256"}, {"authorization_id": True}, []):
            with self.subTest(metadata=metadata), self.assertRaises(BudgetError):
                BudgetLedger(self.path, request_metadata=metadata)
        for version in ("", True, 1):
            with self.subTest(version=version), self.assertRaises(BudgetError):
                BudgetLedger(self.path, price_version=version)
        ledger = BudgetLedger(self.path)
        ledger.input_rate = float("nan")
        with self.assertRaises(BudgetError):
            ledger.reserve(payload())
        self.assertEqual(ledger.records, [])


if __name__ == "__main__":
    unittest.main()
