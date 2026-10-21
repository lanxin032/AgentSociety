"""Snapshot one authorized 000; repetition is advisory, never an automatic stop."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_sim.budget import prefix_digest
from policy_sim.io import canonical, write_json


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_bytes().splitlines(keepends=True)
            if line.endswith(b"\n") and line.strip()]


def repeated_reads(receipts, *, committed_round, completed=()):
    """Separate stale signals from still-open turns; neither proves a deadlock."""
    groups = defaultdict(list)
    for row in receipts:
        if not row.get("ok"):
            continue
        args = row.get("args", {})
        candidates = []
        if row.get("action") == "read":
            candidates.append(("read", {"path": args.get("path")}, row.get("observation", "")))
        elif row.get("action") == "ask_env":
            try:
                answer = json.loads(row["observation"])
            except (ValueError, KeyError):
                continue
            for receipt in answer.get('receipts', []):
                if receipt.get('ok') and receipt['operation'] in {'observe', 'read_materials', 'read_work'}:
                    result = receipt['result']
                    if isinstance(result, dict):
                        result = {k: v for k, v in result.items() if k not in {'read_count_this_turn', 'pace_note'}}
                    candidates.append((receipt['operation'], receipt['payload'], canonical(result)))
        for operation, payload, answer in candidates:
            from hashlib import sha256
            key = (row["round"], row["actor_id"], operation,
                canonical({k: v for k, v in payload.items() if k != "reason"}),
                sha256(answer.encode()).hexdigest())
            groups[key].append(row["call_index"])
    active, historical = [], []
    for key, calls in groups.items():
        if len(calls) < 3:
            continue
        closed = key[0] < committed_round or key[:2] in completed
        record = {"round": key[0], "actor": key[1], "operation": key[2],
                  "query": json.loads(key[3]), "identical_returns": len(calls), "calls": calls,
                  "severity": "historical" if closed else "advisory", "stop_warranted": False}
        (historical if closed else active).append(record)
    return {"active_advisories": active, "historical_repetitions": historical}


def processes(batch):
    result = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,command="],
                            capture_output=True, text=True, check=True)
    return [line.strip() for line in result.stdout.splitlines()
            if "policy_sim" in line and str(batch) in line]


def snapshot(preflight, batch):
    authorization = read(preflight / "authorization.json")
    ledger_path = Path(authorization["api_ledger_path"])
    if ledger_path.resolve() != (ROOT / "runs/api-local-budget.json").resolve():
        raise ValueError("Monitor must use the original ledger")
    ledger = read(ledger_path)
    baseline = authorization["baseline_requests"]
    if prefix_digest(ledger[:baseline]) != authorization["baseline_prefix_sha256"]:
        raise ValueError("Original ledger prefix changed")
    new = ledger[baseline:]
    if any(row.get("authorization_id") != authorization["authorization_id"] for row in new):
        raise ValueError("Another authorization used this ledger baseline")
    status = read(batch / "batch_status.json", {})
    run_record = next(iter(status.get("runs", {}).values()), {})
    run = Path(run_record.get("output_path", batch / "finite-000-s3001-deepseek_official"))
    if not run.resolve().is_relative_to(batch.resolve()):
        raise ValueError("Unexpected run path")
    events = rows(run / "model_requests.jsonl")
    starts = {row["request_id"]: row for row in events if row["event"] == "request_started"}
    usage = defaultdict(lambda: {"requests": 0, "input": 0, "output": 0, "unknown": 0, "pending": 0})
    for row in new:
        group = usage[starts.get(row.get("client_request_id"), {}).get("purpose", "unmatched")]
        group["requests"] += 1
        if row.get("status") == "reserved":
            group["pending"] += 1
        elif row.get("prompt_tokens") is None or row.get("completion_tokens") is None:
            group["unknown"] += 1
        else:
            group["input"] += row["prompt_tokens"]
            group["output"] += row["completion_tokens"]
    committed = read(run / "committed.json", {}).get("round", 0)
    completed, receipts = set(), []
    for folder in sorted((run / "agents").glob("*")):
        state = read(folder / "state/native-turn.json", {})
        if state.get("step_completed"):
            completed.add((state["round"], state["actor_id"]))
        receipts.extend(rows(folder / "native_tool_receipts.jsonl")[-80:])
    repeats = repeated_reads(receipts, committed_round=committed, completed=completed)
    metrics = read(run / "metrics.json", {})
    failures = [{k: row.get(k) for k in ("request_id", "purpose", "round", "actor_id", "error_type")}
                for row in events if row["event"] == "request_failed"]
    try:
        live, process_error = processes(batch), None
    except (subprocess.CalledProcessError, OSError) as exc:
        live, process_error = [], type(exc).__name__
    return {"monitor_version": 3, "at_utc": datetime.now(timezone.utc).isoformat(),
            "attempt_id": run_record.get("attempt_id"), "batch_status": status.get("status", "not_started"),
            "run_dir": str(run), "committed_round": committed,
            "metrics": {k: metrics.get(k) for k in ("initial_resolved", "initial_issues", "projects_built",
                "projects_physically_effective", "projects_administratively_accepted", "business_rejections")},
            "requests": len(new), "logical_requests": len(starts),
            "reported_tokens": sum(group["input"] + group["output"] for group in usage.values()),
            "usage_by_purpose": dict(usage),
            "pending": sum(group["pending"] for group in usage.values()),
            "unknown_usage": sum(group["unknown"] for group in usage.values()),
            "max_request_bytes": max((row.get("request_bytes", 0) for row in new), default=0),
            **repeats, "client_failures": failures,
            "partial_failure": ({"path": str(run / "partial_failure.json"),
                **{k: v for k, v in read(run / "partial_failure.json", {}).items()
                   if k in {"submitted", "completed", "fatal_error"}}}
                if (run / "partial_failure.json").exists() else None),
            "processes": live, "process_inspection_error": process_error,
            "source_sha256": authorization["source_sha256"],
            "recent_actions": rows(run / "actions.jsonl")[-8:],
            "decision_rule": "Repetition is advisory. Inspect current completion and progress before stopping; closed turns never justify a repetition stop."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--stop", help="Explicit evidence-based reason; signal only the matching driver")
    args = parser.parse_args()
    preflight, batch = args.preflight.resolve(), args.batch.resolve()
    if not all(path.is_relative_to(ROOT / "runs") for path in (preflight, batch)):
        raise ValueError("Choose this project's run paths")
    result = snapshot(preflight, batch)
    output = preflight / "monitor"
    if args.stop:
        matches = [line for line in result["processes"] if " -m policy_sim.driver " in line
                   and result["run_dir"] in shlex.split(line)]
        if len(matches) != 1 or (output / "stop-evidence.json").exists():
            raise ValueError("Expected one matching live driver and no prior stop")
        pid = int(matches[0].split()[0])
        write_json(output / "stop-evidence.json", {"reason": args.stop, "pid": pid,
                   "process": matches[0], "signal": "SIGINT", "snapshot": result})
        os.kill(pid, signal.SIGINT)
        result["stop_requested"] = args.stop
    write_json(output / "latest.json", result)
    with (output / "history.jsonl").open("a") as stream:
        stream.write(canonical(result) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "recent_actions"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
