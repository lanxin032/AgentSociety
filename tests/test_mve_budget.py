import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fixtures import WorkspaceTemporaryDirectory
from mve_budget import open_mve_ledger
from smoke_budget import BudgetError, BudgetLedger, BudgetProxy, ControllerLockError, LOCAL_KEY, MODEL


def hold_proxy(path, ready, release):
    with BudgetProxy("test-only-key", BudgetLedger(path)):
        ready.set()
        release.wait(15)


class MveBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "runs" / "api-smoke-budget-20260909.json"
        self.path.parent.mkdir()
        self.original = [{"request": i + 1, "reserved_rmb": 0.01, "estimated_rmb": 0.001,
                          "status": 200} for i in range(16)]
        self.path.write_text(json.dumps(self.original), encoding="utf-8")

    def test_rerun_does_not_add_allowance_or_rewrite_original(self):
        before = self.path.read_bytes()
        ledger = open_mve_ledger(self.root)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(ledger.max_requests, 216)
        self.assertAlmostEqual(ledger.max_rmb, 5.016)
        self.assertEqual(ledger.authorization["baseline_file_sha256"], hashlib.sha256(before).hexdigest())
        ledger.reserve({"model": MODEL, "messages": [{"role": "user", "content": "test"}]})
        again = open_mve_ledger(self.root)
        self.assertEqual(again.max_requests, 216)
        self.assertEqual(again.authorization, ledger.authorization)
        self.assertEqual(again.records[:16], self.original)
        self.assertEqual(len(again.records), 17)

    def test_modified_prefix_and_deleted_ledger_are_rejected(self):
        open_mve_ledger(self.root)
        self.original[0]["estimated_rmb"] = 0
        self.path.write_text(json.dumps(self.original))
        with self.assertRaises(BudgetError):
            open_mve_ledger(self.root)
        self.path.unlink()
        with self.assertRaises(BudgetError):
            open_mve_ledger(self.root)

    def test_proxy_reloads_stale_instance(self):
        stale = BudgetLedger(self.path, max_requests=17)
        fresh = BudgetLedger(self.path, max_requests=17)
        fresh.reserve({"model": MODEL, "messages": [{"role": "user", "content": "test"}]})
        with BudgetProxy("test-only-key", stale):
            self.assertEqual(len(stale.records), 17)
            with self.assertRaises(BudgetError):
                stale.reserve({"model": MODEL, "messages": [{"role": "user", "content": "test"}]})

    def test_second_process_cannot_start_controller(self):
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        process = context.Process(target=hold_proxy, args=(str(self.path), ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(10))
            with self.assertRaises(ControllerLockError):
                with BudgetProxy("test-only-key", BudgetLedger(self.path)):
                    self.fail("Concurrent proxy started")
            with self.assertRaises(ControllerLockError):
                open_mve_ledger(self.root)
        finally:
            release.set()
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join()
        self.assertEqual(process.exitcode, 0)
        with BudgetProxy("test-only-key", BudgetLedger(self.path)):
            pass

    def test_exhaustion_and_schema_error_never_reach_upstream(self):
        for payload in ({"model": MODEL, "messages": [{"role": "user", "content": "test"}]}, [1]):
            with self.subTest(payload=payload):
                with patch("smoke_budget.urlopen") as upstream:
                    with BudgetProxy("test-only-key", BudgetLedger(self.path)) as proxy:
                        request = Request(proxy.base_url + "/chat/completions", data=json.dumps(payload).encode(),
                                          headers={"Authorization": f"Bearer {LOCAL_KEY}"})
                        with self.assertRaises(HTTPError) as error:
                            urlopen(request, timeout=5)
                        self.assertEqual(error.exception.code, 400)
                        self.assertFalse(json.load(error.exception)["error"]["retryable"])
                        self.assertTrue(proxy.fatal_event.is_set())
                        self.assertIsNotNone(proxy.fatal_reason)
                        upstream.assert_not_called()
                self.assertEqual(json.loads(self.path.read_text()), self.original)

    def test_failed_proxy_start_releases_lock(self):
        with patch("smoke_budget.ThreadingHTTPServer", side_effect=OSError("test")):
            with self.assertRaises(OSError):
                with BudgetProxy("test-only-key", BudgetLedger(self.path)):
                    pass
        with BudgetProxy("test-only-key", BudgetLedger(self.path)):
            pass

    def test_authorization_tampering_and_late_prefix_change_are_rejected(self):
        ledger = open_mve_ledger(self.root)
        authorization_path = self.root / "runs" / "mve-authorization-20260909.json"
        authorization = json.loads(authorization_path.read_text())
        authorization["increment_requests"] = 400
        authorization_path.write_text(json.dumps(authorization))
        with self.assertRaises(BudgetError):
            open_mve_ledger(self.root)
        with self.assertRaises(BudgetError):
            with BudgetProxy("test-only-key", ledger):
                pass
        authorization_path.write_text(json.dumps(ledger.authorization))
        self.original[0]["status"] = "modified"
        self.path.write_text(json.dumps(self.original))
        with self.assertRaises(BudgetError):
            with BudgetProxy("test-only-key", ledger):
                pass

    def test_http_failure_retains_reservation_without_echoing_credentials(self):
        ledger = open_mve_ledger(self.root)
        failure = HTTPError("https://example.invalid", 400, "failed", {}, io.BytesIO(b"test-only-key secret body"))
        with patch("smoke_budget.urlopen", side_effect=failure) as upstream:
            with BudgetProxy("test-only-key", ledger) as proxy:
                payload = {"model": MODEL, "messages": [{"role": "user", "content": "test"}]}
                request = Request(proxy.base_url + "/chat/completions", data=json.dumps(payload).encode(),
                                  headers={"Authorization": f"Bearer {LOCAL_KEY}"})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=5)
                response = error.exception.read().decode()
                self.assertNotIn("test-only-key", response)
                self.assertNotIn("secret body", response)
                self.assertEqual(upstream.call_count, 1)
                # A repeat after fatal rejection is blocked before the upstream.
                with self.assertRaises(HTTPError):
                    urlopen(request, timeout=5)
                self.assertEqual(upstream.call_count, 1)
        row = ledger.records[-1]
        self.assertNotIn("estimated_rmb", row)
        self.assertEqual(row["status"], 400)
        self.assertEqual(ledger.summary()["unknown_usage_requests"], 1)
        self.assertNotIn("test-only-key", self.path.read_text())


if __name__ == "__main__":
    unittest.main()
