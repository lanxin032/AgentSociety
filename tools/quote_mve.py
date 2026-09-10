"""Quote the unapproved 24-run batch from one observed pilot; never grants budget."""
import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_mve.io import read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pilot", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Quote output exists; choose a new file")
    controllers = [read_json(p) for p in sorted(args.pilot.glob("controller-*.json"))]
    paid = [r for r in controllers if "budget_after" in r]
    if not paid:
        raise SystemExit("No measured paid pilot")
    before = paid[0]["budget_before"]
    after = paid[-1]["budget_after"]
    calls = after["requests"] - before["requests"]
    cost = after["accounted_rmb"] - before["accounted_rmb"]
    rounds = read_json(args.pilot / "metrics.json")["round"]
    if calls < 1 or rounds < 1:
        raise SystemExit("Pilot has no usable call/round denominator")
    elapsed = sum(r.get("elapsed_seconds", 0) for r in paid)
    factor = 24 * 30 / rounds
    calls_estimate = calls * factor
    cost_estimate = cost * factor
    # One 111 pilot cannot establish all eight arms' usage distribution. Keep
    # the same all-tools intensity for all arms, plus a separately stated margin.
    margin = 1.5
    request_cap = math.ceil(calls_estimate * margin / 100) * 100
    rmb_cap = max(5, math.ceil(cost_estimate * margin / 5) * 5)
    quote = {"status": "awaiting_user_approval_not_authorized", "pilot": str(args.pilot.resolve()),
             "pilot_observed_rounds": rounds, "pilot_requests": calls, "pilot_accounted_rmb": round(cost, 8),
             "planned_runs": 24, "rounds_per_run": 30, "matched_seeds": [101, 102, 103],
             "linear_request_estimate": math.ceil(calls_estimate), "linear_rmb_estimate": round(cost_estimate, 4),
             "contingency_multiplier": margin, "proposed_incremental_request_cap": request_cap,
             "proposed_incremental_rmb_cap": rmb_cap,
             "rough_wall_clock_hours": round(elapsed * factor / 3600, 2),
             "basis": "Observed 111-pilot call/round intensity extrapolated to all 24 runs; 50% separate contingency; rounded upward.",
             "limitations": ["One synthetic pilot, not a quote from the provider or a reconciled bill.",
                            "Policy-induced workload and schema repair frequency may change; either cap stops execution.",
                            "Elapsed extrapolation includes startup and is only an order-of-magnitude scheduling estimate.",
                            "Old or pilot allowance is not authorization for this batch; no controller/ledger is changed."],
             "input_rate_rmb_per_million": 1.2, "output_rate_rmb_per_million": 2.4}
    write_json(args.output, quote)
    print(json.dumps(quote, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
