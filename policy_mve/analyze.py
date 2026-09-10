"""Descriptive paired-block summaries; never treats tickets as replications."""
from copy import deepcopy
import math

POLICIES = tuple(f"{i:03b}" for i in range(8))
METRICS = {
    "cumulative_issue_burden": {"direction": -1, "unit": "unresolved_issue_rounds", "primary": True},
    "initial_resolution_rate": {"direction": 1, "unit": "proportion", "primary": False},
    "labor_spent": {"direction": -1, "unit": "synthetic_labor_units", "primary": False},
    "capital_spent": {"direction": -1, "unit": "synthetic_capital_units", "primary": False},
}
SUCCESS_STATUSES = {"offline_scripted_pass", "passed", "pass", "completed", "success"}


def _stats(values):
    numbers = [item["value"] for item in values]
    return {"n_paired_blocks": len(values), "values": values,
            "mean": sum(numbers) / len(numbers) if numbers else None,
            "range": {"min": min(numbers), "max": max(numbers)} if numbers else None}


def _interaction_terms(pair, fixed):
    indices = ["ABC".index(letter) for letter in pair]
    other = next(i for i in range(3) if i not in indices)
    terms = []
    for x, y, weight in ((1, 1, 1), (1, 0, -1), (0, 1, -1), (0, 0, 1)):
        bits = [0, 0, 0]
        bits[indices[0]], bits[indices[1]], bits[other] = x, y, fixed
        terms.append({"policy": "".join(str(bit) for bit in bits), "weight": weight})
    return terms


def summarize(data):
    """Accept a manifest with embedded run metrics or an explicit run-record list.

    A record needs seed, policy, a successful status (or ok=True), and metrics.
    The eight records in each seed must have the same horizon when provided.
    Optional manifest.seeds/expected_seeds makes wholly missing blocks visible.
    This summarizes supplied evidence; it does not replace artifact hash/replay verification.
    """
    if isinstance(data, list):
        records, metadata = data, {}
    elif isinstance(data, dict) and isinstance(data.get("runs", data.get("records")), list):
        records, metadata = data.get("runs", data.get("records")), data
    else:
        raise ValueError("expected a record list or manifest with runs/records")
    declared_modes = {str(r["mode"]) for r in records if isinstance(r, dict) and "mode" in r}
    if metadata.get("mode"):
        declared_modes.add(str(metadata["mode"]))
    if not declared_modes and records and all(isinstance(r, dict) and str(r.get("status", "")).startswith("offline_scripted_") for r in records):
        declared_modes.add("offline_scripted")
    mode = next(iter(declared_modes)) if len(declared_modes) == 1 else ("mixed" if declared_modes else "unspecified")
    expected = metadata.get("expected_seeds", metadata.get("seeds", []))
    blocks, invalid, audit = {}, [], []
    for seed in expected:
        if type(seed) is not int:
            raise ValueError("expected seeds must be integers")
        blocks.setdefault(seed, {})
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            invalid.append({"record_index": index, "reasons": ["record_not_object"]})
            continue
        seed, policy, metric = record.get("seed"), record.get("policy"), record.get("metrics")
        reasons = []
        if type(seed) is not int:
            reasons.append("missing_or_invalid_seed")
        if policy not in POLICIES:
            reasons.append("missing_or_invalid_policy")
        if record.get("status") not in SUCCESS_STATUSES and not (record.get("status") is None and record.get("ok") is True):
            reasons.append("unsuccessful_or_unconfirmed_status")
        if record.get("errors"):
            reasons.append("record_has_errors")
        if not isinstance(metric, dict):
            reasons.append("metrics_missing")
            metric = {}
        for name in METRICS:
            value = metric.get(name)
            if type(value) not in (int, float) or not math.isfinite(value):
                reasons.append("invalid_metric:" + name)
            elif value < 0 or (name == "initial_resolution_rate" and value > 1):
                reasons.append("out_of_range_metric:" + name)
        for key in ("seed", "policy"):
            if key in metric and metric[key] != record.get(key):
                reasons.append("metric_metadata_mismatch:" + key)
        horizon = record.get("horizon", metric.get("horizon"))
        if "horizon" in record and "horizon" in metric and record["horizon"] != metric["horizon"]:
            reasons.append("metric_metadata_mismatch:horizon")
        if horizon is not None and (type(horizon) is not int or horizon < 1):
            reasons.append("invalid_horizon")
        if "round" in metric and horizon is not None and metric["round"] != horizon:
            reasons.append("unfinished_horizon")
        row = {"record_index": index, "seed": seed, "policy": policy,
               "path": record.get("path"), "status": record.get("status"),
               "errors": deepcopy(record.get("errors", [])), "reasons": reasons,
               "horizon": horizon, "metrics": {k: (str(metric[k]) if type(metric.get(k)) is float and not math.isfinite(metric[k]) else metric.get(k)) for k in METRICS}}
        audit.append(row)
        if type(seed) is int and policy in POLICIES:
            blocks.setdefault(seed, {}).setdefault(policy, []).append(row)
        else:
            invalid.append(row)
    complete, incomplete = {}, []
    for seed in sorted(blocks):
        entries = blocks[seed]
        missing = [policy for policy in POLICIES if policy not in entries]
        duplicates = {policy: [r["record_index"] for r in rows] for policy, rows in entries.items() if len(rows) != 1}
        failed = [deepcopy(row) for rows in entries.values() for row in rows if row["reasons"]]
        horizons = {row["horizon"] for rows in entries.values() for row in rows}
        mismatch = len(horizons) > 1
        if missing or duplicates or failed or mismatch or mode == "mixed":
            incomplete.append({"seed": seed, "missing_policies": missing, "duplicate_policies": duplicates,
                               "failed_records": failed, "horizon_mismatch": mismatch,
                               "mixed_execution_modes": mode == "mixed",
                               "included_in_contrasts": False})
        else:
            complete[seed] = {policy: entries[policy][0]["metrics"] for policy in POLICIES}
    results = {}
    for metric, definition in METRICS.items():
        sign = definition["direction"]
        levels, differences, interactions = {}, {}, {}
        for policy in POLICIES:
            raw = [{"seed": seed, "value": block[policy][metric]} for seed, block in complete.items()]
            benefit = [{"seed": r["seed"], "value": sign * r["value"]} for r in raw]
            levels[policy] = {"original_units": _stats(raw), "benefit_direction": _stats(benefit)}
            diff = [{"seed": seed, "value": block[policy][metric] - block["000"][metric]} for seed, block in complete.items()]
            differences[policy] = {"contrast": f"{policy} - 000", "original_units": _stats(diff),
                                   "benefit_direction": _stats([{"seed": r["seed"], "value": sign * r["value"]} for r in diff])}
        for pair, other in (("AB", "C"), ("AC", "B"), ("BC", "A")):
            for fixed in (0, 1):
                terms = _interaction_terms(pair, fixed)
                raw = [{"seed": seed, "value": sum(t["weight"] * block[t["policy"]][metric] for t in terms)} for seed, block in complete.items()]
                interactions[f"{pair}|{other}{fixed}"] = {
                    "terms": terms, "original_units": _stats(raw),
                    "benefit_direction": _stats([{"seed": r["seed"], "value": sign * r["value"]} for r in raw]),
                }
        results[metric] = {**definition, "benefit_transform": f"{'-' if sign < 0 else '+'}{metric}",
                           "policy_levels": levels, "paired_differences_from_000": differences,
                           "conditional_interactions": interactions}
    return {"analysis_version": "paired-block-descriptive-1.0", "mode": mode,
            "is_llm_experiment": False if mode == "offline_scripted" else metadata.get("is_llm_experiment"),
            "unit_of_replication": "one_complete_simulation_run; eight policy runs paired by seed",
            "primary": "-cumulative_issue_burden", "input_record_count": len(records),
            "complete_block_count": len(complete), "complete_seeds": list(complete),
            "incomplete_blocks": incomplete, "invalid_records": invalid, "record_audit": audit,
            "results": results, "inference": "descriptive_only_no_p_values_or_confidence_intervals",
            "notes": ["Only complete eight-policy blocks enter paired contrasts; every exclusion is listed.",
                      "A negative benefit-direction interaction can indicate diminishing returns; it does not alone establish cancellation.",
                      "Outcomes and costs retain distinct units; no composite score or cross-metric weighting.",
                      "Offline scripted runs test mechanics, not LLM behavior or real-world causal effects.",
                      "Hash and replay verification remains a separate prerequisite; this function analyzes supplied records."]}
