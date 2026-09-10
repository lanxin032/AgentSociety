"""Explicit, one-time MVE allowance layered on the original smoke ledger."""

import hashlib
import json
import os
from pathlib import Path

from smoke_budget import BudgetError, BudgetLedger, ControllerLock, INPUT_RATE, MODEL, OUTPUT_RATE


AUTHORIZATION_ID = "mve-20260909-5rmb-200requests"
PRICE_VERSION = "fiblab-displayed-20260909"
INCREMENT_REQUESTS = 200
INCREMENT_RMB = 5.0
BASELINE_REQUESTS = 16


def prefix_sha256(records):
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def open_mve_ledger(root):
    """Freeze authorization once; never erase records or replenish on reruns.

    Call only from an explicitly authorized execution entrypoint. Importing this
    module performs no filesystem writes. The proxy reloads and revalidates under
    the same controller lock before accepting requests.
    """
    runs = Path(root) / "runs"
    path = runs / "api-smoke-budget-20260909.json"
    authorization_path = runs / "mve-authorization-20260909.json"
    with ControllerLock(path):
        if not path.is_file():
            raise BudgetError("The original smoke ledger is required")
        ledger = BudgetLedger(path)
        if authorization_path.exists():
            authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
        else:
            if len(ledger.records) != BASELINE_REQUESTS:
                raise BudgetError("Initial authorization requires the existing 16-request ledger")
            baseline = ledger.summary()["accounted_rmb"]
            authorization = {
                "schema_version": 1,
                "authorization_id": AUTHORIZATION_ID,
                "baseline_requests": BASELINE_REQUESTS,
                "baseline_accounted_rmb": baseline,
                "baseline_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "baseline_prefix_sha256": prefix_sha256(ledger.records),
                "increment_requests": INCREMENT_REQUESTS,
                "increment_rmb": INCREMENT_RMB,
                "max_requests": BASELINE_REQUESTS + INCREMENT_REQUESTS,
                "max_estimated_rmb": baseline + INCREMENT_RMB,
                "model": MODEL,
                "price_version": PRICE_VERSION,
                "input_rmb_per_million": INPUT_RATE,
                "output_rmb_per_million": OUTPUT_RATE,
            }
            temporary = authorization_path.with_suffix(".tmp")
            with temporary.open("w", encoding="utf-8") as output:
                output.write(json.dumps(authorization, indent=2))
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(authorization_path)

        expected = {
            "schema_version": 1, "authorization_id": AUTHORIZATION_ID,
            "baseline_requests": BASELINE_REQUESTS,
            "increment_requests": INCREMENT_REQUESTS, "increment_rmb": INCREMENT_RMB,
            "max_requests": BASELINE_REQUESTS + INCREMENT_REQUESTS,
            "model": MODEL, "price_version": PRICE_VERSION,
            "input_rmb_per_million": INPUT_RATE, "output_rmb_per_million": OUTPUT_RATE,
        }
        if not isinstance(authorization, dict) or any(authorization.get(key) != value for key, value in expected.items()):
            raise BudgetError("MVE authorization metadata does not match the approved allowance")
        for field in ("baseline_file_sha256", "baseline_prefix_sha256"):
            value = authorization.get(field)
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise BudgetError("Invalid authorization digest")

        def validate(records):
            if json.loads(authorization_path.read_text(encoding="utf-8")) != authorization:
                raise BudgetError("MVE authorization changed after controller setup")
            if len(records) < BASELINE_REQUESTS or prefix_sha256(records[:BASELINE_REQUESTS]) != authorization["baseline_prefix_sha256"]:
                raise BudgetError("The original ledger prefix changed; refusing to reset the allowance")
            baseline = sum(row.get("estimated_rmb", row["reserved_rmb"]) for row in records[:BASELINE_REQUESTS])
            if authorization.get("baseline_accounted_rmb") != baseline or authorization.get("max_estimated_rmb") != baseline + INCREMENT_RMB:
                raise BudgetError("MVE authorization baseline or cumulative cap changed")

        validate(ledger.records)
        ledger.max_requests = authorization["max_requests"]
        ledger.max_rmb = authorization["max_estimated_rmb"]
        ledger.records_validator = validate
        ledger.authorization = dict(authorization)
        return ledger
