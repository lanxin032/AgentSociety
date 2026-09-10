"""Frozen, non-executing V3 experiment design and pilot precision decision.

All numerical scenario settings are synthetic research choices. Generating a
manifest does not authorize execution or freeze a sample size from fake data.
"""
from copy import deepcopy
import hashlib
import itertools
import json
import math
import statistics
from policy_v3.spec import SPEC_VERSION


DESIGN_VERSION = "policy-v3-design-1.0"
TOOLS = ("A", "B", "C")
ENVIRONMENTS = ("zero_communication_friction", "tight_resources", "weak_slow_repair", "fewer_shared_roots")
N_CANDIDATES = (8, 10, 12)
MODEL_REPLICATE_BITS = ("000", "010", "001", "111")
STAGES = ("diagnostic", "pilot", "static", "order", "model_replicate", "sensitivity")


def q_values(values):
    return dict(zip(TOOLS, (float(v) for v in values)))


def _label(value):
    return format(float(value), ".8g").replace(".", "p")


def static_id(values):
    if isinstance(values, dict):
        values = [values[t] for t in TOOLS]
    return "static_" + "_".join(t + _label(v) for t, v in zip(TOOLS, values))


def endpoint_id(bits):
    return static_id([int(b) for b in bits])


def static_scenario(values, horizon=60, environment="baseline", prefix="static"):
    q = q_values(values)
    sid = static_id(q)
    if prefix != "static":
        sid = prefix + sid[len("static"):]
    if environment != "baseline":
        sid += "__" + environment
    return {"id": sid, "family": prefix, "horizon": horizon, "q": q,
            "schedule": [{"start": 0, "end": horizon, "q": deepcopy(q)}], "environment": environment}


def integrated_dose(scenario):
    return {t: sum((p["end"] - p["start"]) * p["q"][t] for p in scenario["schedule"]) for t in TOOLS}


def validate_scenario(scenario):
    horizon = scenario["horizon"]
    if type(horizon) is not int or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if scenario["environment"] not in ("baseline", *ENVIRONMENTS):
        raise ValueError("unknown environment")
    cursor = 0
    for phase in scenario["schedule"]:
        if type(phase["start"]) is not int or type(phase["end"]) is not int or phase["start"] != cursor or phase["end"] <= cursor:
            raise ValueError("schedule must be contiguous, nonoverlapping integer intervals")
        if set(phase["q"]) != set(TOOLS) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in phase["q"].values()):
            raise ValueError("invalid phase q")
        cursor = phase["end"]
    if cursor != horizon:
        raise ValueError("schedule must exactly cover horizon")
    return True


def _order_scenarios():
    scenarios = []
    for family in ("order_cumulative", "order_equal"):
        for permutation in itertools.permutations(TOOLS):
            schedule = []
            for phase in range(3):
                active = permutation[:phase + 1] if family == "order_cumulative" else permutation[phase:phase + 1]
                schedule.append({"start": 20 * phase, "end": 20 * (phase + 1), "q": {t: float(t in active) for t in TOOLS}})
            schedule.append({"start": 60, "end": 90, "q": q_values((1, 1, 1))})
            scenarios.append({"id": family + "_" + "".join(permutation), "family": family, "horizon": 90,
                              "q": q_values((1, 1, 1)), "schedule": schedule, "environment": "baseline"})
        fraction = 2 / 3 if family == "order_cumulative" else 1 / 3
        scenarios.append({"id": family + "_simultaneous", "family": family, "horizon": 90,
                          "q": q_values((1, 1, 1)), "schedule": [
                              {"start": 0, "end": 60, "q": q_values((fraction,) * 3)},
                              {"start": 60, "end": 90, "q": q_values((1, 1, 1))}], "environment": "baseline"})
    return scenarios


def build_design(n=12):
    if type(n) is not int or n not in N_CANDIDATES:
        raise ValueError("N must be one of 8, 10, 12")
    values = set(itertools.product((0.0, 0.5, 1.0), repeat=3))
    for axis in range(3):
        for value in (0.25, 0.75):
            row = [0.0] * 3
            row[axis] = value
            values.add(tuple(row))
    static = [static_scenario(row) for row in sorted(values)]
    endpoint = [static_scenario(tuple(int(b) for b in bits)) for bits in (f"{i:03b}" for i in range(8))]
    diagnostics = [static_scenario(tuple(int(b) for b in bits), horizon=30, prefix="diagnostic") for bits in ("000", "010", "001")]
    order = _order_scenarios()
    sensitivity = [static_scenario([scenario["q"][t] for t in TOOLS], environment=env) for env in ENVIRONMENTS for scenario in endpoint]
    scenarios = static + diagnostics + order + sensitivity
    for scenario in scenarios:
        validate_scenario(scenario)
    pools = {"diagnostic": [1001, 1002], "pilot": list(range(2001, 2005)), "static": list(range(3001, 3001 + n)),
             "order": list(range(4001, 4001 + n)), "sensitivity_reuses_static": list(range(3001, 3007)),
             "model_replicate_reuses_static": list(range(3001, 3001 + n))}
    runs = []
    def add(stage, selected, seeds, replicate=0):
        for seed in seeds:
            for scenario in selected:
                runs.append({"run_id": f"v3_{stage}_s{seed}_r{replicate}_{scenario['id']}", "stage": stage,
                             "scenario_id": scenario["id"], "seed": seed, "replicate": replicate,
                             "horizon": scenario["horizon"], "scenario": deepcopy(scenario),
                             "status": "planned_not_executed" if stage in ("diagnostic", "pilot") else "awaiting_pilot_freeze",
                             "metrics": None, "path": None, "verification": None})
    add("diagnostic", diagnostics, pools["diagnostic"])
    add("pilot", endpoint, pools["pilot"])
    add("static", static, pools["static"])
    add("order", order, pools["order"])
    replicate_scenarios = [s for s in static if s["id"] in {endpoint_id(bits) for bits in MODEL_REPLICATE_BITS}]
    add("model_replicate", replicate_scenarios, pools["static"], replicate=1)
    add("sensitivity", sensitivity, pools["sensitivity_reuses_static"])
    stage_index = {stage: index for index, stage in enumerate(STAGES)}
    runs.sort(key=lambda r: (stage_index[r["stage"]], r["seed"], hashlib.sha256((r["stage"] + "|" + str(r["seed"]) + "|" + r["run_id"]).encode()).hexdigest()))
    within = {}
    for index, record in enumerate(runs):
        key = (record["stage"], record["seed"])
        within[key] = within.get(key, 0) + 1
        record["order_in_stage_seed"] = within[key]
        record["run_order"] = index + 1
    counts = {stage: sum(r["stage"] == stage for r in runs) for stage in STAGES}
    counts["total"] = len(runs)
    assert counts["total"] == 51 * n + 230
    return {"schema_version": DESIGN_VERSION, "status": "awaiting_pilot_freeze", "n": n, "scenarios": scenarios,
            "runs": runs, "counts": counts, "seed_pools": pools,
            "limits": {"planned_runs": len(runs), "technical_redo_reserve": 8, "planned_plus_reserve": len(runs) + 8, "overall_run_cap": 850,
                       "redo_rule": "Only document and replace a technical failure; no selective reruns of unfavorable valid outcomes."},
            "metadata": protocol_specification()}


def protocol_specification():
    return {"schema_version": DESIGN_VERSION, "implementation_version": SPEC_VERSION, "purpose": "synthetic_mechanism_experiment",
            "initial_issues": 12, "actors": 4, "n_candidates": list(N_CANDIDATES),
            "static": {"horizon": 60, "grid_levels": [0, 0.5, 1], "full_grid": 27, "axis_extra_levels": [0.25, 0.75], "axis_extra_points": 6, "total_scenarios": 33},
            "order": {"phase_length": 20, "common_final_all_on": 30, "horizon": 90,
                      "cumulative": "Successive adoption remains on; simultaneous reference q=2/3 each in [0,60), then all q=1. Total dose 210 matches, individual-tool doses do not match each ordering.",
                      "equal": "One tool at a time for 20 rounds, then all on for 30; simultaneous reference q=1/3 in [0,60), then all on. Each tool dose is 50 in every scenario.",
                      "ongoing_projects": "Provision windows govern new offers; do not terminate adopted project processes when a window changes.", "groups": 14},
            "pilot_precision": {"seeds": [2001, 2002, 2003, 2004], "runs": 32, "target": "Seven endpoint-minus-000 paired mean normalized-burden differences", "metric": "cumulative_issue_burden/(12*horizon)", "variance_upper_confidence": 0.90, "variance_df": 3, "pointwise_ci_confidence": 0.95, "target_half_width": 0.10, "minimum_blocks": 8, "maximum_blocks": 12, "not_guaranteed": "Four pilot seeds only; static endpoint variance does not establish precision for strength, interactions or order contrasts."},
            "inference": {"unit": "whole simulation", "pairing": "exogenous seed within family", "model_sampling": "Independent model draws, no claim of provider seed reproducibility", "missing": "Complete paired contrasts plus worst-case normalized-burden bounds over all planned blocks", "multiplicity": "Holm within prespecified contrast families; confidence intervals remain pointwise", "rq1_primary": "Seven non000-versus-000 endpoint contrasts plus six pairwise tool interactions conditional on the third tool being 0 or 1 (13 primary contrasts).", "rq1_exploratory": "Seven marginal factorial contrasts are separate exploratory hypotheses, not substitutes for the six conditional interactions.", "order_windows": "Report both the complete 90 rounds and the final 30-round common all-on window; adjust both windows within each order family's prespecified tests.", "reporting_scale": "Report original U differences and CIs in unresolved-Issue-rounds alongside normalized differences; scaling denominator is 12H for each outcome window.", "zero_variance": "Report zero sample MCSE and degenerate t interval descriptively; t p-value undefined", "sensitivity": "Pairs reuse first six static seeds and baseline endpoint results; sensitivity is not independent confirmation of the main study.", "valid_data": "Only complete verified real-model records enter formal inference. Offline/scripted records are test-only."},
            "authorization": "Design generation and sample-size planning never execute runs or change API controls. Formal stages remain awaiting_pilot_freeze until an explicit separate freeze/authorization step.",
            "counts_formula": "6+32+33*N+14*N+4*N+8*4*6 = 51*N+230; plus eight technical reruns, maximum 850 at N=12"}


def record_version(record):
    verification = record.get("verification") or {}
    candidates = [record.get("spec_version"), verification.get("spec_version"), (record.get("metrics") or {}).get("spec_version")]
    if not any(v is not None for v in candidates):
        candidates = [record.get("version"), verification.get("version")]
    aliases = {"3": "policy-v3-3.0", "3.0": "policy-v3-3.0", "3.1": SPEC_VERSION}
    versions = {aliases.get(str(v), str(v)) for v in candidates if v is not None}
    if len(versions) != 1:
        raise ValueError("record must have one unambiguous implementation version")
    return next(iter(versions))


def is_verified_llm(record):
    mode = record.get("mode", record.get("execution_mode"))
    verification = record.get("verification") or {}
    return mode == "llm" and record.get("status") in {"complete", "completed", "completed_verified", "llm_verified_pass", "verified_llm", "real_model_verified_pass"} and verification.get("passed") is True


def normalized_burden(record):
    horizon = record["horizon"]
    if type(horizon) is not int or horizon <= 0:
        raise ValueError("invalid horizon")
    metrics = record.get("metrics") or {}
    if metrics.get("horizon", horizon) != horizon or metrics.get("round", horizon) != horizon:
        raise ValueError("incomplete or inconsistent observation horizon")
    burden = metrics.get("cumulative_issue_burden")
    if type(burden) not in (int, float) or not math.isfinite(burden) or not 0 <= burden <= 12 * horizon:
        raise ValueError("burden must be finite and in [0,12H] under the one-active-Issue-per-facility contract")
    return burden / (12 * horizon)


def source_fingerprint(record, required=False):
    """Canonical code-manifest object digest, matching the evidence verifier."""
    verification = record.get("verification") or {}
    declared = [h for h in (record.get("source_manifest_sha256"), verification.get("source_manifest_sha256")) if h is not None]
    hashes = set()
    for explicit in declared:
        if not isinstance(explicit, str) or len(explicit) != 64 or any(c not in "0123456789abcdef" for c in explicit.lower()):
            raise ValueError("invalid source manifest SHA256")
        hashes.add(explicit.lower())
    source = record.get("source_manifest") or verification.get("source_manifest")
    if source:
        raw = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        hashes.add(hashlib.sha256(raw.encode()).hexdigest())
    if len(hashes) > 1:
        raise ValueError("source manifest contents/declarations do not match canonical SHA256")
    if not hashes and required:
        raise ValueError("sample-size freeze requires a source manifest or source_manifest_sha256 on every pilot record")
    return next(iter(hashes)) if hashes else None


def freeze_sample_size(pilot_records):
    """Plan N once from complete independent, verified 8x4 pilot records."""
    from .analysis import student_t_quantile, chi_square_df3_quantile
    records = list(pilot_records)
    if len(records) != 32:
        raise ValueError("pilot freeze requires exactly 32 records")
    expected = {(seed, endpoint_id(f"{i:03b}")) for seed in range(2001, 2005) for i in range(8)}
    observed, versions = {}, set()
    prototype = build_design(8)
    scenarios = {s["id"]: s for s in prototype["scenarios"]}
    pilot_ids = {(r["seed"], r["scenario_id"]): r["run_id"] for r in prototype["runs"] if r["stage"] == "pilot"}
    for record in records:
        if record.get("stage") != "pilot" or record.get("replicate") != 0 or record.get("horizon") != 60 or not is_verified_llm(record):
            raise ValueError("pilot requires complete verified real-model pilot records, replicate 0, horizon 60")
        key = (record.get("seed"), record.get("scenario_id"))
        if key not in expected or key in observed:
            raise ValueError("pilot has duplicate or unexpected seed/scenario")
        if record.get("run_id") != pilot_ids[key]:
            raise ValueError("pilot run_id does not match its planned seed/scenario")
        scenario = record.get("scenario") or {}
        canonical = scenarios[key[1]]
        if scenario != canonical:
            raise ValueError("pilot scenario differs from frozen scenario contract")
        observed[key] = normalized_burden(record)
        versions.add(record_version(record))
    if set(observed) != expected or len(versions) != 1:
        raise ValueError("pilot is incomplete or mixes implementation versions")
    if versions != {SPEC_VERSION}:
        raise ValueError("pilot implementation version must match V3")
    denominator = chi_square_df3_quantile(0.10)
    contrasts = []
    for i in range(1, 8):
        sid = endpoint_id(f"{i:03b}")
        differences = [observed[seed, sid] - observed[seed, endpoint_id("000")] for seed in range(2001, 2005)]
        sd = statistics.stdev(differences)
        upper = sd * math.sqrt(3 / denominator)
        contrasts.append({"scenario_id": sid, "paired_differences": differences, "sample_sd": sd, "sd_upper_90": upper})
    planning_sd = max(row["sd_upper_90"] for row in contrasts)
    candidates = [{"n": n, "half_width": student_t_quantile(0.975, n - 1) * planning_sd / math.sqrt(n)} for n in N_CANDIDATES]
    eligible = [row for row in candidates if row["half_width"] <= 0.10]
    chosen = eligible[0] if eligible else candidates[-1]
    canonical_records = json.dumps(sorted(records, key=lambda r: r["run_id"]), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {"status": "precision_target_planned" if eligible else "precision_limited_at_cap", "n": chosen["n"], "target_half_width": 0.10,
            "planned_half_width": chosen["half_width"], "max_pilot_sd_upper_90": planning_sd, "chi_square_quantile_0p10_df3": denominator,
            "contrasts": contrasts, "candidates": candidates, "spec_version": next(iter(versions)), "pilot_record_sha256": hashlib.sha256(canonical_records.encode()).hexdigest(),
            "planned_total_runs": 51 * chosen["n"] + 230, "technical_redo_reserve": 8,
            "execution_authorized": False, "limitations": ["Planning approximation under a normal paired-difference variance model; four pilot blocks cannot guarantee achieved coverage or precision.", "Taking the maximum of seven individual 90% upper bounds is not a simultaneous 90% variance guarantee.", "The .10 planning target applies only to endpoint-versus-000 static contrasts, not every strength, interaction or order contrast.", "If all pilot differences have zero SD, choose the prespecified minimum but do not infer that population/model variance is zero.", "Do not increase sample size until significance; this decision precedes the independent formal data."]}


def freeze_design(pilot_records):
    """Return the chosen complete design; never grant execution authorization.

    In addition to statistical eligibility, every pilot record must identify a
    common source manifest. This binds a decision to evidence, not merely N.
    """
    records = list(pilot_records)
    decision = freeze_sample_size(records)
    source_hashes = set()
    for record in records:
        source_hashes.add(source_fingerprint(record, required=True))
    if len(source_hashes) != 1:
        raise ValueError("pilot mixes source manifests; cannot freeze a single-version experiment")
    frozen = build_design(decision["n"])
    frozen["status"] = "frozen_pending_stage_authorization"
    frozen["freeze_decision"] = decision
    frozen["execution_authorized"] = False
    frozen["pilot_binding"] = {"record_count": 32, "canonical_record_sha256": decision["pilot_record_sha256"],
                               "implementation_version": decision["spec_version"], "source_manifest_sha256": next(iter(source_hashes)),
                               "record_ids": sorted(r["run_id"] for r in records),
                               "note": "A matching sample-size freeze does not authorize diagnostics, formal stages, retries or API calls."}
    by_id = {r["run_id"]: r for r in records}
    for row in frozen["runs"]:
        if row["stage"] == "pilot":
            row.update(deepcopy(by_id[row["run_id"]]))
        elif row["stage"] not in ("diagnostic", "pilot"):
            row["status"] = "frozen_pending_stage_authorization"
    return frozen
