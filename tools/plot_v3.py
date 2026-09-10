"""Static V3 analysis figures; never runs simulations, estimates effects or calls APIs.

Usage: python tools/plot_v3.py analysis.json --output-dir figures --units both
Requires an already installed matplotlib. Missing values remain missing.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


OFFLINE_TITLE = "OFFLINE SCRIPTED — PIPELINE TEST"


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def analysis_label(report):
    mode = str(report.get("analysis_mode", "")).lower()
    if report.get("test_only") or any(word in mode for word in ("offline", "scripted", "test")):
        return OFFLINE_TITLE
    if report.get("formal_inference") is True:
        return "VERIFIED REAL-MODEL — FORMAL ANALYSIS"
    return "UNVERIFIED — NO FORMAL INFERENCE"


def contrast_data(rows, units):
    """Use explicit unit fields; legacy raw_difference is normalized, never U."""
    if units not in {"burden", "normalized"}:
        raise ValueError("Unknown contrast unit")
    mean_key, ci_key = (("burden_difference", "ci95_burden_difference") if units == "burden"
                       else ("normalized_difference", "normalized_ci95"))
    output = []
    for row in rows:
        value = row.get(mean_key)
        count = row.get("n_complete_blocks", 0)
        if type(count) is not int or count < 1 or not finite(value):
            value = None
        ci = row.get(ci_key)
        valid_ci = (value is not None and count >= 2 and isinstance(ci, (list, tuple)) and len(ci) == 2
                    and all(finite(v) for v in ci) and ci[0] <= value <= ci[1])
        output.append({"id": row.get("id", "unnamed"), "value": value,
                       "ci": list(ci) if valid_ci else None, "n": count,
                       "planned": row.get("planned_blocks", "?"),
                       "missing": bool(row.get("missing_blocks"))})
    return output


def dose_data(curves, axis):
    result = []
    for curve in curves:
        if curve.get("axis") != axis:
            continue
        points = []
        for point in curve.get("points", []):
            q, mean, count = point.get("q"), point.get("mean_normalized_burden"), point.get("n_available_blocks", 0)
            if not finite(q):
                continue
            valid = finite(mean) and type(count) is int and count > 0
            points.append({"q": q, "mean": mean if valid else None, "n": count})
        result.append({"fixed": curve.get("fixed_other_q", {}), "points": sorted(points, key=lambda p: p["q"])})
    return result


def _empty(ax, text="NO VALID ESTIMATES\nMissing outcomes were not imputed"):
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes, color="#555555")


def _forest(ax, rows, units, title, direction):
    data = contrast_data(rows, units)
    valid = sum(row["value"] is not None for row in data)
    if data:
        for position, row in enumerate(data):
            if row["value"] is None:
                continue
            ax.plot(row["value"], position, "o", color="#1f5e86", markersize=4)
            if row["ci"]:
                ax.hlines(position, *row["ci"], color="#1f5e86", linewidth=1.4)
                ax.plot(row["ci"], [position, position], "|", color="#1f5e86", markersize=5)
        labels = [r["id"].replace("RQ1_", "").replace("RQ2b_", "") +
                  f"  [{r['n']}/{r['planned']}]" + (" NA" if r["value"] is None else " (CI unavailable)" if r["ci"] is None else "")
                  for r in data]
        ax.set_yticks(range(len(data)), labels, fontsize=8)
        ax.set_ylim(len(data) - 0.5, -0.5)
    else:
        ax.set_yticks([])
    if not valid:
        _empty(ax)
    ax.axvline(0, color="#888888", linewidth=0.8, linestyle="--")
    ax.grid(axis="x", alpha=0.2)
    ax.set_title(title, fontsize=11)
    measure = "Original U difference (unresolved Issue-rounds)" if units == "burden" else "Normalized difference in U/(12H)"
    ax.set_xlabel(measure + "\n" + direction, fontsize=9)
    return valid


def render(report, output_dir, units="both", formats=("png", "pdf"), dpi=180):
    if report.get("schema_version") != "policy-v3-analysis-1.0":
        raise ValueError("Expected policy_v3.analysis.analyze JSON schema policy-v3-analysis-1.0")
    if units not in {"both", "burden", "normalized"} or not formats or set(formats) - {"png", "pdf", "svg"}:
        raise ValueError("Invalid plot units or formats")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise RuntimeError("matplotlib is not installed in this runtime; use an existing runtime with matplotlib. No dependency was installed.") from error
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_units = ("burden", "normalized") if units == "both" else (units,)
    label = analysis_label(report)
    manifest = {"analysis_label": label, "status": "empty", "plots": [],
                "notes": ["No effects or confidence intervals estimated by the plotter.",
                          "95% CIs are pointwise paired-t intervals, not simultaneous intervals.",
                          "Available-case dose means are descriptive; no dose-curve CI is supplied by the analysis.",
                          "Different window horizons remain different estimands even after normalization."]}

    def save(fig, name, count, extra_note):
        fig.suptitle(label + "\n" + name.replace("_", " "), fontsize=13)
        fig.text(0.01, 0.015, extra_note, fontsize=8, va="bottom")
        fig.tight_layout(rect=(0, 0.08, 1, 0.92))
        paths = []
        try:
            for extension in formats:
                path = output_dir / (name + "." + extension)
                fig.savefig(path, dpi=dpi, bbox_inches="tight")
                paths.append(path.name)
        finally:
            plt.close(fig)
        manifest["plots"].append({"name": name, "finite_estimates": count, "status": "plotted" if count else "empty", "files": paths})

    contrasts = report.get("contrasts", [])
    rq1 = [r for r in contrasts if str(r.get("id", "")).startswith("RQ1_")]
    for unit in selected_units:
        fig, ax = plt.subplots(figsize=(13, max(6, 0.36 * len(rq1) + 3)))
        count = _forest(ax, rq1, unit, "RQ1 paired contrasts; [complete/planned blocks]",
                        "Signed contrast in U: negative = lower burden under positive-coefficient terms")
        save(fig, "RQ1_paired_" + unit, count,
             "Pointwise 95% CI; no p-value significance stars. Factorial and conditional rows are interactions, not simple treatment differences.\n"
             "Complete-pair selection may matter; missing-cohort bounds remain in the analysis JSON and are not confidence intervals.")

    fig, axes = plt.subplots(1, 3, figsize=(16, 6.8), squeeze=False)
    count = 0
    for axis, ax in zip(("A", "B", "C"), axes[0]):
        lines = dose_data(report.get("dose_curves", []), axis)
        local_count = 0
        for line in lines:
            valid_count = sum(p["mean"] is not None for p in line["points"])
            if not valid_count:
                continue
            fixed = ", ".join(f"{k}={v:g}" if finite(v) else f"{k}={v}" for k, v in sorted(line["fixed"].items()))
            ax.plot([p["q"] for p in line["points"]],
                    [p["mean"] if p["mean"] is not None else math.nan for p in line["points"]],
                    marker="o", markersize=3, linewidth=1.1, label=fixed or "other q unspecified")
            local_count += valid_count
        if not local_count:
            _empty(ax, "NO VALID DOSE MEANS\nMissing points remain gaps")
        else:
            ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2)
        ax.set_title(f"RQ2a: vary {axis}; hold other tools fixed")
        ax.set_xlabel(f"Planned intensity q_{axis}")
        ax.set_ylabel("Mean normalized burden U/(12H), H=60\nLower = less unresolved burden")
        ax.set_xlim(-0.03, 1.03)
        ax.grid(alpha=0.2)
        count += local_count
    save(fig, "RQ2a_dose_normalized", count,
         "Means use available runs; adjacent-dose paired contrasts and their CIs are in the analysis JSON. No error bars are invented.\n"
         "Quarter intensities occur only on the single-tool axes; lines do not imply a complete five-level grid.")

    families = (("RQ2b_order_cumulative", "Cumulative introduction"), ("RQ2b_order_equal", "Equal planned exposure"))
    for unit in selected_units:
        fig, axes = plt.subplots(2, 2, figsize=(17, 10))
        count = 0
        for index, (family, title) in enumerate(families):
            for column, common in enumerate((False, True)):
                rows = [r for r in contrasts if r.get("family") == family and
                        (str(r.get("id", "")).endswith("_common_window")) == common]
                count += _forest(axes[index][column], rows, unit,
                                 title + (" — final common 30 rounds" if common else " — full 90 rounds"),
                                 "Sequence minus simultaneous; negative = lower sequence burden")
        save(fig, "RQ2b_order_" + unit, count,
             "Pointwise 95% paired CI; [complete/planned blocks]. Full 90-round and final 30-round windows are separate estimands.\n"
             "An unavailable common window is shown empty; full-window outcomes are never substituted.")
    if any(p["finite_estimates"] for p in manifest["plots"]):
        manifest["status"] = "plotted"
    (output_dir / "plot_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--units", choices=("both", "burden", "normalized"), default="both")
    parser.add_argument("--formats", nargs="+", choices=("png", "pdf", "svg"), default=["png", "pdf"])
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args(argv)
    if not 72 <= args.dpi <= 600:
        parser.error("dpi must be between 72 and 600")
    report = json.loads(args.analysis.read_text(encoding="utf-8"))
    try:
        result = render(report, args.output_dir, args.units, tuple(dict.fromkeys(args.formats)), args.dpi)
    except (ValueError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")
    result["input_sha256"] = hashlib.sha256(args.analysis.read_bytes()).hexdigest()
    (args.output_dir / "plot_manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "analysis_label": result["analysis_label"], "plots": len(result["plots"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
