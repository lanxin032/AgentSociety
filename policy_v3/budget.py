"""Stage authorization on the original API ledger, without resetting history."""
import hashlib
import json
from pathlib import Path
from policy_mve.io import digest
from policy_v3.execution import validate_authorization, ExecutionError
from tools.smoke_budget import BudgetLedger, BudgetError, ControllerLock


def prefix_digest(records):
    return digest(records)


def open_stage_ledger(root, authorization_path, manifest_path, stage):
    root = Path(root).resolve()
    authorization_path = Path(authorization_path).resolve()
    raw = authorization_path.read_bytes()
    authorization = validate_authorization(json.loads(raw), manifest_path, stage, root)
    path = root / "runs" / "api-smoke-budget-20260909.json"
    if Path(authorization["api_ledger_path"]).resolve() != path:
        raise BudgetError("V3 must use the original API ledger")
    n0 = authorization["baseline_requests"]
    if type(n0) is not int or n0 < 0:
        raise BudgetError("Invalid frozen ledger baseline")
    raw_hash = hashlib.sha256(raw).hexdigest()

    def validate(records):
        if hashlib.sha256(authorization_path.read_bytes()).hexdigest() != raw_hash:
            raise BudgetError("Stage authorization changed during execution")
        if len(records) < n0 or prefix_digest(records[:n0]) != authorization["baseline_prefix_sha256"]:
            raise BudgetError("Original ledger prefix differs from the authorized baseline")
        baseline = sum(r.get("estimated_rmb", r["reserved_rmb"]) for r in records[:n0])
        if abs(baseline - authorization["baseline_accounted_rmb"]) > 1e-10:
            raise BudgetError("Historical accounting baseline changed")
        for row in records[n0:]:
            if row.get("authorization_id") != authorization["authorization_id"]:
                raise BudgetError("Another authorization has used this stage baseline")
            if (row.get("input_rate") != authorization["input_rmb_per_million"]
                    or row.get("output_rate") != authorization["output_rmb_per_million"]
                    or row.get("price_version") != authorization["price_version"]):
                raise BudgetError("Recorded stage price differs from the frozen authorization")
        if len(records) > n0 + authorization["incremental_request_cap"]:
            raise BudgetError("Stage request cap exceeded")
        total = sum(r.get("estimated_rmb", r["reserved_rmb"]) for r in records)
        if total > baseline + authorization["incremental_rmb_cap"] + 1e-10:
            raise BudgetError("Stage monetary cap exceeded")

    class StageLedger(BudgetLedger):
        def reserve(self, payload):
            if not isinstance(payload, dict):
                raise BudgetError("Request must be a JSON object")
            validate(self.records)
            if (payload.get("temperature") != 0.2 or payload.get("max_tokens") != 4096
                    or payload.get("thinking") != {"type": "disabled"}
                    or payload.get("response_format") != {"type": "json_object"}):
                raise BudgetError("Request settings differ from the frozen V3 model settings")
            return super().reserve(payload)

    with ControllerLock(path):
        if not path.is_file():
            raise BudgetError("Original API ledger is required; V3 never creates a replacement")
        ledger = StageLedger(path,
            max_requests=n0 + authorization["incremental_request_cap"],
            max_rmb=authorization["baseline_accounted_rmb"] + authorization["incremental_rmb_cap"],
            input_rate=authorization["input_rmb_per_million"],
            output_rate=authorization["output_rmb_per_million"],
            price_version=authorization["price_version"],
            request_metadata={"authorization_id": authorization["authorization_id"]})
        validate(ledger.records)
        ledger.records_validator = validate
        ledger.authorization = authorization
        return ledger
