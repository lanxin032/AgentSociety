"""Stage authorization on a preserved ledger; local separation requires approval."""
import hashlib
import json
from pathlib import Path
from .io import digest
from .execution import validate_authorization, authorization_paths, ExecutionError, check_deadline
from .proxy import BudgetLedger, BudgetError, ControllerLock


def prefix_digest(records):
    return digest(records)


def open_stage_ledger(root, authorization_path, manifest_path, stage):
    root = Path(root).resolve()
    authorization_path = Path(authorization_path).resolve()
    raw = authorization_path.read_bytes()
    authorization = validate_authorization(json.loads(raw), manifest_path, stage, root)
    record_only = authorization.get("cost_control_mode") == "record_only"
    if not record_only:
        raise BudgetError("Current protocol requires preserved record-only accounting")
    path = authorization_paths(authorization, root)["ledger"]
    if Path(authorization["api_ledger_path"]).resolve() != path:
        raise BudgetError("V3 must use the explicitly authorized API ledger")
    n0 = authorization["baseline_requests"]
    if type(n0) is not int or n0 < 0:
        raise BudgetError("Invalid frozen ledger baseline")
    raw_hash = hashlib.sha256(raw).hexdigest()
    profiles = authorization.get("request_profiles")
    from .profiles import validate_profile
    if not profiles:
        raise BudgetError("An explicit current request profile is required")
    profiles = [validate_profile(p) for p in profiles]

    def validate(records):
        if hashlib.sha256(authorization_path.read_bytes()).hexdigest() != raw_hash:
            raise BudgetError("Stage authorization changed during execution", error_type="evidence_or_authorization")
        if len(records) < n0 or prefix_digest(records[:n0]) != authorization["baseline_prefix_sha256"]:
            raise BudgetError("Original ledger prefix differs from the authorized baseline", error_type="evidence_or_authorization")
        baseline = sum(r.get("estimated_rmb", r["reserved_rmb"]) for r in records[:n0])
        if abs(baseline - authorization["baseline_accounted_rmb"]) > 1e-10:
            raise BudgetError("Historical accounting baseline changed", error_type="evidence_or_authorization")
        for row in records[n0:]:
            if row.get("authorization_id") != authorization["authorization_id"]:
                raise BudgetError("Another authorization has used this stage baseline", error_type="evidence_or_authorization")
            if (row.get("input_rate") != authorization["input_rmb_per_million"]
                    or row.get("output_rate") != authorization["output_rmb_per_million"]
                    or row.get("price_version") != authorization["price_version"]):
                raise BudgetError("Recorded stage price differs from the frozen authorization", error_type="evidence_or_authorization")

    class StageLedger(BudgetLedger):
        def reserve(self, payload):
            if not isinstance(payload, dict):
                raise BudgetError("Request must be a JSON object")
            validate(self.records)
            if authorization.get('local_stop_at_utc'):
                try:
                    check_deadline(authorization['local_stop_at_utc'], reserve_seconds=0)
                except ExecutionError as exc:
                    raise BudgetError('Frozen local execution deadline reached', error_type='deadline') from exc
            from .profiles import validate_payload, profile_digest, PURPOSES
            matched = False
            for profile in profiles:
                for purpose in PURPOSES:
                    try:
                        validate_payload(payload, profiles, purpose, profile_digest(profile))
                    except ValueError:
                        continue
                    matched = True
                    break
                if matched:
                    break
            if not matched:
                raise BudgetError("Request differs from authorized profile", error_type="evidence_or_authorization")
            return super().reserve(payload)

    with ControllerLock(path):
        if not path.is_file():
            raise BudgetError("Authorized API ledger is required; V3 never creates a replacement")
        ledger = StageLedger(path,
            max_requests=None,
            max_rmb=None,
            enforce_limits=False, model=authorization["model"],
            input_rate=authorization["input_rmb_per_million"],
            output_rate=authorization["output_rmb_per_million"],
            price_version=authorization["price_version"],
            max_body_bytes=authorization.get("max_body_bytes", 96 * 1024),
            max_output_tokens=16384,
            request_metadata={"authorization_id": authorization["authorization_id"]})
        validate(ledger.records)
        ledger.records_validator = validate
        ledger.authorization = authorization
        return ledger
