"""Paired V3 analysis; standard-library statistics, no simulation or API access.

Student-t tails use a continued-fraction incomplete beta, checked in tests
against numerical reference quantiles. SciPy is not required.
"""
from collections import defaultdict
import itertools
import math
import statistics
from policy_v3.spec import SPEC_VERSION

from .design import TOOLS, ENVIRONMENTS, MODEL_REPLICATE_BITS, endpoint_id, static_id, normalized_burden, is_verified_llm, record_version, source_fingerprint


def _beta_fraction(a, b, x):
    tiny, eps = 1e-300, 3e-14
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 401):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        c = 1 + aa / c
        if abs(d) < tiny:
            d = tiny
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        c = 1 + aa / c
        if abs(d) < tiny:
            d = tiny
        if abs(c) < tiny:
            c = tiny
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            return h
    raise ArithmeticError("incomplete beta failed to converge")


def _regularized_beta(x, a, b):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        value = front * _beta_fraction(a, b, x) / a
    else:
        value = 1 - front * _beta_fraction(b, a, 1 - x) / b
    return min(1.0, max(0.0, value))


def student_t_two_sided(t, df):
    if df <= 0:
        raise ValueError("positive degrees of freedom required")
    if math.isinf(t):
        return 0.0
    return _regularized_beta(df / (df + t * t), df / 2, 0.5)


def student_t_quantile(probability, df):
    if not 0 < probability < 1 or df <= 0:
        raise ValueError("invalid t quantile arguments")
    if probability == 0.5:
        return 0.0
    if probability < 0.5:
        return -student_t_quantile(1 - probability, df)
    target = 2 * (1 - probability)
    low, high = 0.0, 1.0
    while student_t_two_sided(high, df) > target:
        high *= 2
    for _ in range(100):
        middle = (low + high) / 2
        if student_t_two_sided(middle, df) > target:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def chi_square_df3_quantile(probability):
    if not 0 < probability < 1:
        raise ValueError("invalid chi-square quantile probability")
    def cdf(x):
        return math.erf(math.sqrt(x / 2)) - math.sqrt(2 * x / math.pi) * math.exp(-x / 2)
    low, high = 0.0, 4.0
    while cdf(high) < probability:
        high *= 2
    for _ in range(100):
        middle = (low + high) / 2
        if cdf(middle) < probability:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def summarize_differences(values):
    values = list(values)
    if any(not math.isfinite(x) for x in values):
        raise ValueError("nonfinite difference")
    n = len(values)
    mean = statistics.mean(values) if n else None
    sd = statistics.stdev(values) if n >= 2 else None
    if n >= 2 and max(values) - min(values) <= 1e-12:
        # Ratios of integer U values can acquire subtraction roundoff; do not
        # turn machine-epsilon variation into a spuriously precise t test.
        sd = 0.0
    mcse = sd / math.sqrt(n) if sd is not None else None
    half = student_t_quantile(0.975, n - 1) * mcse if n >= 2 else None
    pvalue = student_t_two_sided(mean / mcse, n - 1) if mcse is not None and mcse > 0 else None
    return {"n_complete_blocks": n, "raw_difference": mean, "benefit_difference": -mean if mean is not None else None,
            "sample_sd": sd, "mcse": mcse, "ci95_raw": [mean - half, mean + half] if half is not None else None,
            "ci95_benefit": [-mean - half, -mean + half] if half is not None else None, "half_width": half,
            "pvalue_two_sided": pvalue, "pvalue_holm": None,
            "variance_note": "zero observed sample variance; p-value undefined, not proof of zero population variance" if sd == 0 else ("fewer than two complete blocks" if n < 2 else "paired t approximation; interval is pointwise")}


def paired_summary(terms, seeds, outcomes):
    """terms is [(cell-key, signed coefficient)]; outcomes[(cell-key, seed)].

    Missing outcomes stay [0,1], giving a worst-case full-planned-cohort bound.
    Complete-pair estimates never substitute a missing outcome with zero.
    """
    merged = defaultdict(float)
    for key, coefficient in terms:
        merged[key] += coefficient
    terms = [(key, coefficient) for key, coefficient in merged.items() if coefficient]
    complete, missing, bounds = [], [], []
    for seed in seeds:
        lo, hi, value, absent = 0.0, 0.0, 0.0, []
        for key, coefficient in terms:
            outcome = outcomes.get((key, seed))
            if outcome is None:
                lo += min(0.0, coefficient)
                hi += max(0.0, coefficient)
                absent.append(key)
            else:
                value += coefficient * outcome
                lo += coefficient * outcome
                hi += coefficient * outcome
        bounds.append((lo, hi))
        if absent:
            missing.append({"seed": seed, "missing_cells": absent})
        else:
            complete.append({"seed": seed, "raw_difference": value})
    report = summarize_differences(row["raw_difference"] for row in complete)
    report.update({"planned_blocks": len(seeds), "complete_blocks": complete, "missing_blocks": missing,
                   "missingness_warning": "Complete-pair inference may be selected when failures depend on treatment; full-cohort bounds are separate, not confidence intervals." if missing else None,
                   "full_planned_mean_raw_bounds": [sum(b[0] for b in bounds) / len(seeds), sum(b[1] for b in bounds) / len(seeds)] if seeds else None})
    if report["full_planned_mean_raw_bounds"] is not None:
        low, high = report["full_planned_mean_raw_bounds"]
        report["full_planned_mean_benefit_bounds"] = [-high, -low]
    return report


def _with_burden_units(report, horizon, window="full"):
    """Keep normalized planning scale and expose the original U scale explicitly."""
    scale = 12 * horizon
    report["normalized_difference"] = report["raw_difference"]
    report["normalized_benefit_difference"] = report["benefit_difference"]
    report["normalized_ci95"] = report["ci95_raw"]
    report["burden_difference"] = None if report["raw_difference"] is None else report["raw_difference"] * scale
    report["burden_benefit_difference"] = None if report["benefit_difference"] is None else report["benefit_difference"] * scale
    report["ci95_burden_difference"] = None if report["ci95_raw"] is None else [v * scale for v in report["ci95_raw"]]
    report["ci95_burden_benefit"] = None if report["ci95_benefit"] is None else [v * scale for v in report["ci95_benefit"]]
    report["mcse_burden"] = None if report["mcse"] is None else report["mcse"] * scale
    report["full_planned_mean_burden_bounds"] = None if report.get("full_planned_mean_raw_bounds") is None else [v * scale for v in report["full_planned_mean_raw_bounds"]]
    report["units"] = {"burden_difference": "unresolved_Issue_rounds", "normalized_difference": "U/(12*window_horizon)", "window_horizon": horizon,
                       "window": window, "scale_factor": scale, "legacy_raw_difference_field": "normalized signed difference, NOT original U units"}
    return report


def holm_adjust(contrasts):
    """Adjust over all prespecified contrasts, retaining missing p-values."""
    groups = defaultdict(list)
    for contrast in contrasts:
        groups[contrast["family"]].append(contrast)
    for group in groups.values():
        valid = sorted((c for c in group if c["pvalue_two_sided"] is not None), key=lambda c: c["pvalue_two_sided"])
        previous = 0.0
        for index, contrast in enumerate(valid):
            previous = max(previous, min(1.0, (len(group) - index) * contrast["pvalue_two_sided"]))
            contrast["pvalue_holm"] = previous
        for contrast in group:
            contrast["holm_family_size"] = len(group)
    return contrasts


def _cell(stage, scenario_id, replicate=0):
    return f"{stage}|{scenario_id}|replicate={replicate}"


def _validate_records(records, design, allow_offline):
    planned = {r["run_id"]: r for r in design["runs"]}
    accepted, invalid, seen, versions, source_hashes = {}, [], set(), set(), set()
    frozen_source = (design.get("pilot_binding") or {}).get("source_manifest_sha256")
    for record in records:
        rid = record.get("run_id")
        if rid in seen:
            raise ValueError("duplicate run_id; resolve attempts explicitly before analysis: " + str(rid))
        seen.add(rid)
        if rid not in planned:
            invalid.append({"run_id": rid, "reason": "not in frozen design"})
            continue
        expected = planned[rid]
        if expected["stage"] in ("diagnostic", "pilot"):
            continue
        try:
            if any(record.get(k) != expected[k] for k in ("stage", "scenario_id", "seed", "replicate", "horizon", "scenario")):
                raise ValueError("scenario, stage, seed, replicate or horizon differs from design")
            if not is_verified_llm(record):
                offline = record.get("mode", record.get("execution_mode")) in {"offline", "scripted", "offline_scripted"}
                if not (allow_offline and offline and (record.get("verification") or {}).get("passed") is True and record.get("status") in {"complete", "completed", "offline_scripted_pass", "scripted_verified_pass"}):
                    raise ValueError("not complete verified real-model data")
            version = record_version(record)
            fingerprint = source_fingerprint(record, required=bool(frozen_source))
            if frozen_source and fingerprint != frozen_source:
                raise ValueError("source manifest differs from the pilot-bound frozen design")
            value = normalized_burden(record)
            accepted[rid] = {"record": record, "outcome": value}
            versions.add(version)
            if fingerprint:
                source_hashes.add(fingerprint)
        except (TypeError, ValueError, KeyError) as exc:
            invalid.append({"run_id": rid, "reason": str(exc)})
    if len(versions) > 1:
        raise ValueError("formal data mix implementation versions; analyze separate frozen studies")
    if versions and versions != {SPEC_VERSION}:
        raise ValueError("formal data version does not match V3")
    if len(source_hashes) > 1:
        raise ValueError("formal data mix source manifests; analyze separate frozen studies")
    return accepted, invalid, versions


def analyze(records, design, allow_offline=False):
    accepted, invalid, versions = _validate_records(list(records), design, allow_offline)
    outcomes, common_outcomes, common_unavailable, full_records = {}, {}, [], {}
    for row in accepted.values():
        r = row["record"]
        cell = _cell(r["stage"], r["scenario_id"], r["replicate"])
        outcomes[cell, r["seed"]] = row["outcome"]
        full_records[cell, r["seed"]] = r
        if r["stage"] == "order":
            common = r["metrics"].get("common_window_burden")
            common_rounds = r["metrics"].get("common_window_rounds", r["metrics"].get("common_window_horizon", 30))
            if type(common) in (int, float) and math.isfinite(common) and 0 <= common <= 12 * 30 and common_rounds == 30:
                common_outcomes[cell, r["seed"]] = common / (12 * 30)
            else:
                common_unavailable.append({"run_id": r["run_id"], "reason": "missing or invalid final-30-round common_window_burden; full-window result is not substituted"})
    static_seeds = design["seed_pools"]["static"]
    order_seeds = design["seed_pools"]["order"]
    sensitivity_seeds = design["seed_pools"]["sensitivity_reuses_static"]
    contrasts = []
    def add(identifier, family, terms, seeds, label=None, horizon=60, window="full", outcome_values=None):
        result = paired_summary(terms, seeds, outcomes if outcome_values is None else outcome_values)
        _with_burden_units(result, horizon, window)
        result.update({"id": identifier, "family": family, "label": label or identifier,
                       "terms": [{"cell": key, "coefficient": coefficient} for key, coefficient in terms]})
        contrasts.append(result)
        return result
    base = _cell("static", endpoint_id("000"))
    for i in range(1, 8):
        bits = f"{i:03b}"
        add("RQ1_" + bits + "_minus_000", "RQ1_primary", [(_cell("static", endpoint_id(bits)), 1), (base, -1)], static_seeds)
    for pair in itertools.combinations(range(3), 2):
        third = next(index for index in range(3) if index not in pair)
        for fixed in (0, 1):
            terms = []
            for left, right in itertools.product((0, 1), repeat=2):
                bits = [0, 0, 0]
                bits[pair[0]], bits[pair[1]], bits[third] = left, right, fixed
                terms.append((_cell("static", static_id(bits)), (1 if left else -1) * (1 if right else -1)))
            add("RQ1_conditional_" + "".join(TOOLS[i] for i in pair) + "_given_" + TOOLS[third] + str(fixed), "RQ1_primary", terms, static_seeds)
    for count in (1, 2, 3):
        for subset in itertools.combinations(range(3), count):
            terms = []
            for bits in itertools.product((0, 1), repeat=3):
                weight = math.prod(1 if bits[index] else -1 for index in subset) / (2 ** (3 - count))
                terms.append((_cell("static", static_id(bits)), weight))
            add("RQ1_factorial_" + "".join(TOOLS[i] for i in subset), "RQ1_exploratory_factorial", terms, static_seeds)
    static_scenarios = [s for s in design["scenarios"] if s["family"] == "static" and s["environment"] == "baseline"]
    dose_curves = []
    for axis in TOOLS:
        other = [t for t in TOOLS if t != axis]
        for levels in itertools.product((0.0, 0.5, 1.0), repeat=2):
            matches = sorted((s for s in static_scenarios if all(s["q"][t] == q for t, q in zip(other, levels))), key=lambda s: s["q"][axis])
            points = []
            label = axis + "_given_" + "_".join(t + str(q) for t, q in zip(other, levels))
            for scenario in matches:
                cell = _cell("static", scenario["id"])
                available = [outcomes[cell, seed] for seed in static_seeds if (cell, seed) in outcomes]
                points.append({"q": scenario["q"][axis], "scenario_id": scenario["id"], "n_available_blocks": len(available), "mean_normalized_burden": statistics.mean(available) if available else None})
            for previous, following in zip(matches, matches[1:]):
                add("RQ2a_" + label + "_" + str(previous["q"][axis]) + "_to_" + str(following["q"][axis]), "RQ2a_intensity",
                    [(_cell("static", following["id"]), 1), (_cell("static", previous["id"]), -1)], static_seeds)
            dose_curves.append({"axis": axis, "fixed_other_q": dict(zip(other, levels)), "points": points,
                                "note": "Point means use available runs; adjacent differences use complete pairs. Quarter points exist only with both other tools at zero."})
    for family in ("order_cumulative", "order_equal"):
        reference = _cell("order", family + "_simultaneous")
        for permutation in itertools.permutations(TOOLS):
            sid = family + "_" + "".join(permutation)
            terms = [(_cell("order", sid), 1), (reference, -1)]
            add("RQ2b_" + sid, "RQ2b_" + family, terms, order_seeds, horizon=90)
            add("RQ2b_" + sid + "_common_window", "RQ2b_" + family, terms, order_seeds, horizon=30, window="final_30_all_on", outcome_values=common_outcomes)
    for env in ENVIRONMENTS:
        env_base = _cell("sensitivity", endpoint_id("000") + "__" + env)
        for i in range(8):
            bits = f"{i:03b}"
            sid = endpoint_id(bits)
            env_cell = _cell("sensitivity", sid + "__" + env)
            baseline_cell = _cell("static", sid)
            add("sensitivity_environment_" + env + "_" + bits, "sensitivity_environment", [(env_cell, 1), (baseline_cell, -1)], sensitivity_seeds)
            if i:
                add("sensitivity_effect_change_" + env + "_" + bits, "sensitivity_effect_change",
                    [(env_cell, 1), (env_base, -1), (baseline_cell, -1), (base, 1)], sensitivity_seeds)
    model_repeats = []
    for bits in MODEL_REPLICATE_BITS:
        sid = endpoint_id(bits)
        original, repeated = _cell("static", sid), _cell("model_replicate", sid, 1)
        summary = paired_summary([(repeated, 1), (original, -1)], static_seeds, outcomes)
        _with_burden_units(summary, 60)
        pairs = [(outcomes[original, s], outcomes[repeated, s]) for s in static_seeds if (original, s) in outcomes and (repeated, s) in outcomes]
        summary.update({"scenario_id": sid, "n_exogenous_blocks": len(pairs), "independent_sample_size_is_not": 2 * len(pairs),
                        "mean_absolute_repeat_difference": statistics.mean(abs(b - a) for a, b in pairs) if pairs else None,
                        "within_exogenous_model_variance_estimate": statistics.mean((b - a) ** 2 / 2 for a, b in pairs) if pairs else None,
                        "note": "Two independent model draws within the same exogenous block; not two independent exogenous samples. Variance estimate assumes independent identically configured draws."})
        model_repeats.append(summary)
    # A frontier is descriptive and uses a common cohort across all 33 cells.
    frontier_cells = [_cell("static", s["id"]) for s in static_scenarios]
    common_seeds = [seed for seed in static_seeds if all((cell, seed) in full_records and all(type(full_records[cell, seed]["metrics"].get(m)) in (int, float) and math.isfinite(full_records[cell, seed]["metrics"][m]) for m in ("labor_spent", "capital_spent")) for cell in frontier_cells)]
    points = []
    for s, cell in zip(static_scenarios, frontier_cells):
        vector = [statistics.mean(outcomes[cell, seed] for seed in common_seeds), statistics.mean(full_records[cell, seed]["metrics"]["labor_spent"] for seed in common_seeds), statistics.mean(full_records[cell, seed]["metrics"]["capital_spent"] for seed in common_seeds)] if common_seeds else None
        points.append({"scenario_id": s["id"], "objectives": vector})
    for point in points:
        value = point["objectives"]
        point["nondominated"] = None if value is None else not any(other["objectives"] is not None and all(a <= b for a, b in zip(other["objectives"], value)) and any(a < b for a, b in zip(other["objectives"], value)) for other in points)
    holm_adjust(contrasts)
    complete_primary = sum(c["n_complete_blocks"] == c["planned_blocks"] for c in contrasts)
    return {"schema_version": "policy-v3-analysis-1.0", "analysis_mode": "offline_test_only" if allow_offline else "verified_real_model",
            "formal_inference": bool(accepted) and not allow_offline, "n_planned_blocks": design["n"], "implementation_versions": sorted(versions),
            "accepted_formal_records": len(accepted), "excluded_records": invalid, "planned_formal_records": sum(r["stage"] not in ("diagnostic", "pilot") for r in design["runs"]),
            "complete_contrasts": complete_primary, "contrasts": contrasts, "dose_curves": dose_curves, "common_window_unavailable": common_unavailable,
            "nondominated": {"objectives_minimized": ["mean_normalized_burden", "mean_labor_spent", "mean_capital_spent"], "common_seeds": common_seeds, "points": points, "note": "Descriptive observed-mean frontier, not statistically established dominance; workload units are not API currency."},
            "model_replicates": model_repeats,
            "limitations": ["Independent pilot and diagnostic records are excluded from formal inference.", "Intervals are pointwise paired-t approximations; Holm p-values are adjusted only within named prespecified families.", "Complete-pair estimates can be biased by treatment-dependent failures; report worst-case full-planned-cohort bounds alongside them.", "Sensitivity reuses main-study baseline seeds and is not independent validation.", "Cumulative ordering matches total planned exposure only; equal-window ordering matches each tool's planned exposure. Actual offers and adoption are post-treatment quantities.", "Normalized 60-round static outcomes and 90-round order outcomes are not interchangeable estimands.", "Three-quarter and quarter intensities are tested only on the single-tool axes; no complete five-level grid claim.", "No result proves real-world policy causality or universal benefit of all-on treatment."]}


def render_markdown(report):
    def fmt(value):
        return "NA" if value is None else f"{value:.4f}"
    lines = ["# V3配对分析", "", "状态：" + ("离线测试结果，不作正式推断。" if not report["formal_inference"] else "仅纳入已完整核验的真实模型运行。"), "",
             f"计划每组{report['n_planned_blocks']}个外生区组；纳入{report['accepted_formal_records']}条运行，排除{len(report['excluded_records'])}条。",
             "原始U差的单位为未解决Issue·轮，收益U差取其相反数；归一化差另列为U/(12H)。全程H为60或90，共同末期窗口H为30。置信区间为点区间，p值在预设比较族内作Holm调整。缺失不补零。", "",
             "| 对比 | 完整/计划区组 | 原始U差 | 收益U差 | 归一化差 | U差MCSE | U差95%CI | Holm p | 全计划队列U缺失界限 |",
             "|---|---:|---:|---:|---:|---:|---|---:|---|"]
    for row in report["contrasts"]:
        ci = "NA" if row["ci95_burden_difference"] is None else "[" + ", ".join(fmt(v) for v in row["ci95_burden_difference"]) + "]"
        bounds = "NA" if row["full_planned_mean_burden_bounds"] is None else "[" + ", ".join(fmt(v) for v in row["full_planned_mean_burden_bounds"]) + "]"
        lines.append(f"| {row['id']} | {row['n_complete_blocks']}/{row['planned_blocks']} | {fmt(row['burden_difference'])} | {fmt(row['burden_benefit_difference'])} | {fmt(row['normalized_difference'])} | {fmt(row['mcse_burden'])} | {ci} | {fmt(row['pvalue_holm'])} | {bounds} |")
    lines.extend(["", "## 模型重复", "", "| 情景 | 外生区组 | 平均绝对重复差 | 区组内模型方差估计 |", "|---|---:|---:|---:|"])
    for row in report["model_replicates"]:
        lines.append(f"| {row['scenario_id']} | {row['n_exogenous_blocks']} | {fmt(row['mean_absolute_repeat_difference'])} | {fmt(row['within_exogenous_model_variance_estimate'])} |")
    frontier = report["nondominated"]
    names = [p["scenario_id"] for p in frontier["points"] if p["nondominated"] is True]
    lines.extend(["", "## 非支配与剂量", "", f"非支配比较采用所有33情景共同完整的{len(frontier['common_seeds'])}个区组；按负担、劳动、工程资金三个维度最小化。",
                  "观察均值非支配情景：" + ("、".join(names) if names else "资料不足或无可计算结果"), "剂量曲线的逐点值与全部缺失区组列表见机器JSON；不能用观察均值声称统计优势。", "", "## 限制", ""])
    human_limitations = [
        "探索pilot和诊断记录不纳入正式推断；离线脚本数据只能用于分析程序测试。",
        "区间采用配对t近似，属于点区间；Holm调整仅在预先指定的比较族内进行，不能声称同时区间覆盖。",
        "若失败与处理有关，完整配对结果可能存在选择偏差；全计划队列缺失界限与置信区间应分别报告。",
        "敏感性复用正式静态前6个种子及其对照结果，不构成独立验证。",
        "持续叠加只匹配计划总暴露；等时长匹配各工具计划暴露。实际适用、提供和采用次数不能事后强行配平。",
        "静态60轮、顺序90轮及共同末期30轮是不同观察窗口；归一化不消除窗口差异。",
        "0.25和0.75只补充在单工具轴上，没有完成五档125点全网格。",
        "观察均值、模拟差异和工具验收不能证明现实政策因果效应，也不要求111更优。",
    ]
    lines.extend("- " + note for note in human_limitations)
    if report["excluded_records"]:
        lines.extend(["", "## 排除记录", ""])
        lines.extend("- " + str(row["run_id"]) + ": " + row["reason"] for row in report["excluded_records"])
    return "\n".join(lines) + "\n"
