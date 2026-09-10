"""Verify saved smoke-test evidence without importing the engine or calling APIs."""

import argparse
import hashlib
import json
from pathlib import Path


def verify(simulation_run, query_run):
    simulation_run, query_run = Path(simulation_run), Path(query_run)
    source = json.loads((simulation_run / "summary.json").read_text())
    query = json.loads((query_run / "summary.json").read_text())
    simulation = simulation_run / "simulation"
    files = ["SOCIETY.json", "SOCIETY_STEP.json", "env/SimpleSocialSpace/state/ENV_STATE.json"]
    files += [f"agents/agent_{identifier:04d}/AGENT.json" for identifier in (1, 2)]
    data = {name: json.loads((simulation / name).read_text()) for name in files}
    agent_results = source["driver"].get("agent_results", [])
    checks = {
        "real_api_probe": source.get("api_probe", {}).get("reply") == "CLOUD_SMOKE_OK",
        "official_agent_class": data["SOCIETY.json"].get("agent_class_name") == "PersonAgent",
        "official_environment": data["SOCIETY.json"].get("env_module_types") == ["SimpleSocialSpace"],
        "two_agent_tasks_succeeded": {item["id"] for item in agent_results if item.get("ok") and item.get("summary")} == {1, 2},
        "society_completed_one_step": data["SOCIETY_STEP.json"].get("step_count") == 1,
        "society_time_advanced": data["SOCIETY_STEP.json"].get("current_time") == "2026-01-01T09:01:00",
        "agent_checkpoints_completed_one_step": all(data[f"agents/agent_{identifier:04d}/AGENT.json"].get("step_count") == 1 for identifier in (1, 2)),
        "query_restored_environment": query.get("driver", {}).get("environment_restored") is True,
        "query_test_succeeded": query.get("ok") is True,
        "query_matches_expected_value": all(value in query.get("driver", {}).get("query_answer", "") for value in ([query["driver"]["query_expected"]] if query.get("driver", {}).get("query_expected") else ["Alice", "Bob"])),
        "query_did_not_advance_time": query.get("driver", {}).get("completed_steps") == 1 and query.get("driver", {}).get("simulation_time") == "2026-01-01T09:01:00",
        "ray_shutdown_after_each_run": source["driver"].get("ray_shutdown") is True and query["driver"].get("ray_shutdown") is True,
    }
    replay_counts = {}
    for path in sorted((simulation / "replay").glob("*.jsonl")):
        replay_counts[path.name] = sum(1 for line in path.read_text().splitlines() if line.strip() and isinstance(json.loads(line), dict))
    checks["replay_records_present"] = bool(replay_counts) and all(replay_counts.values())
    return {
        "ok": all(checks.values()),
        "core_ok": all(value for name, value in checks.items() if not name.startswith("query_")),
        "query_ok": all(value for name, value in checks.items() if name.startswith("query_")),
        "checks": checks,
        "simulation_run": simulation_run.name, "query_run": query_run.name,
        "initial_combined_test_ok": source["ok"],
        "query_answer": query.get("driver", {}).get("query_answer"),
        "replay_record_counts": replay_counts,
        "checkpoint_sha256": {name: hashlib.sha256((simulation / name).read_bytes()).hexdigest() for name in files},
        "final_budget": query["budget_after"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("simulation_run", type=Path)
    parser.add_argument("query_run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.simulation_run, args.query_run)
    output = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
