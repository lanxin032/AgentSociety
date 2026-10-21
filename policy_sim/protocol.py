"""Finite workload protocol and a quote on the existing ledger. No API calls."""
from copy import deepcopy
import json
from pathlib import Path

from .profiles import make_profile, validate_profile, EXECUTION_POLICY
from .runtime import code_digest, code_manifest
from .execution import ExecutionError, digest, file_hash

SCHEMA = "policy-sim-plan-1"
DEFAULT_BODY_BYTES = 256 * 1024


def make_manifest(root, stage="finite_baseline", *, baseline_evidence=None, provider="deepseek_official"):
    if stage not in ("finite_baseline", "finite_endpoints"):
        raise ExecutionError("Unknown finite workload stage")
    bits = ("000",) if stage == "finite_baseline" else ("111", "001", "010", "011", "100", "101", "110")
    profile = make_profile(provider=provider)
    rows = []
    for policy in bits:
        scenario = {"id": "finite-" + policy, "family": "finite_workload", "horizon": None,
            "q": {name: float(policy[i]) for i, name in enumerate("ABC")}, "schedule": [],
            "environment": "baseline", "workload_mode": "finite"}
        rows.append({"run_id": "finite-" + policy + "-s3001" + ("-" + provider if provider else ""), "stage": stage, "policy": policy,
            "seed": 3001, "replicate": 0, "horizon": None, "workload_mode": "finite",
            "scenario_id": scenario["id"], "scenario": scenario, "runtime_profile": deepcopy(profile)})
    return {"schema_version": SCHEMA, "stage": stage, "status": "frozen_pending_stage_authorization",
        "purpose": "fixed_workload_system_token_efficiency", "runtime_profile": profile,
        "metadata": {"actors": 4, "initial_issues": 12, "seed": 3001,
            "completion": "local_repairs_and_cases_and_shared_roots_and_required_acceptance",
            "metric": "T_system", "new_issues": False, "resource_limits": False,
            "source_expiry": False, "scientific_round_limit": None},
        "source_binding": {"source_manifest_sha256": code_digest(root)},
        "baseline_evidence": deepcopy(baseline_evidence), "runs": rows}


def validate_manifest(manifest, stage, require_frozen=False):
    if manifest.get("schema_version") != SCHEMA or stage not in ("finite_baseline", "finite_endpoints"):
        raise ExecutionError("Invalid finite workload protocol")
    # Compare every scientific field, including per-run profiles and all eight
    # workload conditions. Only source and separately audited release evidence vary.
    expected = make_manifest(Path(__file__).resolve().parents[1], stage,
                             baseline_evidence=manifest.get("baseline_evidence"),
                             provider=manifest.get("runtime_profile", {}).get("provider_route", {}).get("provider"))
    expected["source_binding"] = manifest.get("source_binding")
    if manifest != expected:
        raise ExecutionError("Finite workload manifest differs from frozen protocol")
    validate_profile(manifest["runtime_profile"])
    binding = (manifest.get("source_binding") or {}).get("source_manifest_sha256")
    if not isinstance(binding, str) or len(binding) != 64 or any(c not in "0123456789abcdef" for c in binding):
        raise ExecutionError("Finite workload manifest lacks its source freeze")
    return deepcopy(manifest["runs"])


def require_baseline(manifest, root):
    """A frozen single-case helper can never release the policy comparisons."""
    if manifest["stage"] == "finite_baseline":
        return
    evidence = manifest.get("baseline_evidence") or {}
    path = (Path(root) / evidence.get("run_dir", "")).resolve()
    if not path.is_relative_to(Path(root).resolve() / "runs"):
        raise ExecutionError("Baseline evidence must belong to project runs")
    from .verify import verify_run
    result = verify_run(path, root)
    frozen = json.loads((path / "run_config.json").read_text())
    if (not result.get("passed") or not result.get("workload_complete")
            or frozen.get("mode") != "llm" or frozen.get("record", {}).get("policy") != "000"
            or frozen.get("runtime_profile") != manifest["runtime_profile"]
            or frozen.get("code_manifest") != code_manifest(root)
            or evidence.get("committed_sha256") != file_hash(path / "committed.json")):
        raise ExecutionError("Policy comparisons require a completed matching real 000 baseline")


def prepare(root, output, *, provider="deepseek_official"):
    """Freeze a reviewable one-run proposal; never approve, reset or open a ledger."""
    from policy_sim.io import read_json, write_json
    from .budget import prefix_digest
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or not output.is_relative_to(root / "runs"):
        raise ExecutionError("Preparation requires a new output under project runs")
    ledger_path = root / "runs/api-local-budget.json"
    records = read_json(ledger_path)
    if not isinstance(records, list) or any(r.get("status") == "reserved" for r in records):
        raise ExecutionError("Inspect the original ledger's pending state before freezing")
    manifest = make_manifest(root, provider=provider)
    output.mkdir(parents=True)
    write_json(output / "manifest.json", manifest)
    write_json(output / "source_manifest.json", code_manifest(root))
    # Rates are the last recorded gateway rates, explicitly an estimate until
    # the proposed stage's price evidence is reviewed and authorized.
    prior = next((row for row in reversed(records) if "input_rate" in row and "output_rate" in row), None)
    if prior is None:
        raise ExecutionError("Existing gateway price provenance is required")
    proposal = {"approved": False, "explicit_stage_authorization": False,
        "authorization_id": "finite-baseline-2.8.7", "stage": "finite_baseline",
        "model": manifest["runtime_profile"]["model"], "execution_environment": "local",
        "manifest_sha256": file_hash(output / "manifest.json"), "source_sha256": code_digest(root),
        "request_profiles": [manifest["runtime_profile"]], "ledger_scope": "independent_local",
        "api_ledger_path": str(ledger_path), "baseline_requests": len(records),
        "baseline_prefix_sha256": prefix_digest(records),
        "baseline_accounted_rmb": sum(row.get("estimated_rmb", row.get("reserved_rmb", 0)) for row in records),
        "cost_control_mode": "record_only",
        "cost_control_user_evidence_reference": "User instruction: record fees only; do not interrupt on spending or request thresholds.",
        "incremental_request_cap": None, "incremental_rmb_cap": None,
        "max_attempts": 1, "max_recoveries_total": 0, "max_recoveries_per_run": 0,
        "automatic_technical_retries": False, "manual_resume_allowed": True, "max_body_bytes": DEFAULT_BODY_BYTES,
        "input_rmb_per_million": prior["input_rate"], "output_rmb_per_million": prior["output_rate"],
        "price_version": prior.get("price_version", "prior_ledger_rates"),
        "price_status": "last_recorded_gateway_rates_pending_stage_review",
        "price_evidence_reference": "runs/api-local-budget.json:last_recorded_rates",
        "historical_usage_status": "not_migrated",
        "independent_ledger_explicitly_approved": True,
        "independent_ledger_user_evidence_reference": "existing_local_ledger_authorization_retained",
        "user_evidence_reference": "", "approval_reference": "",
        "completion_guaranteed_by_budget": False, "round_limit": None,
        "stop_on_cap": False,
        "completion_control": "continue until workload complete, explicit user stop, or an unresolved technical/integrity failure"}
    if provider is not None:
        proposal["provider_route"] = manifest["runtime_profile"]["provider_route"]
        proposal["authorization_id"] += "-" + provider
        if provider == "deepseek_official":
            proposal.update(input_rmb_per_million=2.0, output_rmb_per_million=8.0,
                price_version="deepseek-flash-20260913-peak-uncached-upper-estimate",
                price_status="upper_estimate_excludes_cache_and_offpeak_discounts_not_invoice",
                price_evidence_reference="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/")
    write_json(output / "authorization-proposal.json", proposal)
    return {"manifest": str(output / "manifest.json"), "proposal": proposal, "api_requests": 0}
