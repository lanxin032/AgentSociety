"""One bounded official-framework chunk; LLM mode requires an active stage attempt."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_mve.io import read_json, write_json, digest
from policy_v3.runtime import select_run, code_manifest, MODEL_SETTINGS
from policy_v3.spec import SPEC_VERSION
from policy_v3.execution import (AttemptRegistry, ExecutionError, check_deadline,
                                 validate_authorization, file_hash)
from tools.v3_driver import validate_commit
from tools.smoke_budget import BudgetProxy, LOCAL_KEY, ControllerLock


def validate_attempt(args, record, authorization):
    if not args.attempt_id:
        raise ExecutionError("LLM mode must be dispatched by the capped V3 batch controller")
    registry_path = ROOT / "runs" / "v3_control" / "attempts.jsonl"
    if not registry_path.is_file():
        raise ExecutionError("Real attempt registry is missing")
    registry = AttemptRegistry(registry_path)
    active = registry.latest(args.attempt_id)
    if not active or active.get("kind") not in {"start", "running", "checkpoint"}:
        raise ExecutionError("Attempt is not active")
    expected = {"run_id": args.run_id, "authorization_id": authorization["authorization_id"],
                "stage": record["stage"], "manifest_sha256": file_hash(args.manifest),
                "output_path": str(args.output)}
    if any(active.get(k) != v for k, v in expected.items()):
        raise ExecutionError("Attempt does not bind this run, output, stage and authorization")


def launch(args, record_path, base_url, report, proxy=None):
    env = os.environ.copy()
    env.update({"WORKSPACE_PATH": str(ROOT), "PYTHONPATH": str(ROOT),
        "AGENTSOCIETY_LLM_API_KEY": LOCAL_KEY, "AGENTSOCIETY_LLM_API_BASE": base_url,
        "AGENTSOCIETY_LLM_MODEL": MODEL_SETTINGS["model"], "AGENTSOCIETY_CODER_LLM_API_KEY": LOCAL_KEY,
        "AGENTSOCIETY_CODER_LLM_API_BASE": base_url, "AGENTSOCIETY_CODER_LLM_MODEL": MODEL_SETTINGS["model"],
        "AGENTSOCIETY_EMBEDDING_API_KEY": LOCAL_KEY, "AGENTSOCIETY_EMBEDDING_API_BASE": base_url,
        "AGENTSOCIETY_EMBEDDING_MODEL": "bge-m3", "AGENTSOCIETY_LLM_RAY_MAX_WORKERS": "2",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True", "RAY_USAGE_STATS_ENABLED": "0",
        "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
    command = [sys.executable, "-B", str(ROOT / "tools/v3_driver.py"), "--run-dir", str(args.output),
               "--record", str(record_path), "--steps", str(args.steps), "--mode", args.mode]
    if args.resume:
        command.append("--resume")
    with (args.output / f"controller-{report['invocation_id']}.log").open("w", encoding="utf-8") as stream:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        start = time.monotonic()
        while child.poll() is None:
            reason = None
            if proxy and proxy.fatal_event.is_set():
                reason = "Budget proxy stopped: " + str(proxy.fatal_reason)
            if time.monotonic() - start > args.timeout:
                reason = "Chunk wall-clock cap reached"
            if args.stop_at:
                deadline = datetime.fromisoformat(args.stop_at.replace("Z", "+00:00"))
                if (deadline - datetime.now(timezone.utc)).total_seconds() < 120:
                    reason = "Cloud deadline approached during a chunk"
            if reason:
                report["stop_reason"] = reason
                child.send_signal(signal.SIGINT)
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
                break
            time.sleep(0.5)
        report["driver_exit_code"] = child.returncode
    return child.returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("scripted", "llm"), default="scripted")
    parser.add_argument("--steps", type=int, default=5)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--attempt-id")
    parser.add_argument("--stop-at")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / "runs"):
        raise SystemExit("Output must remain inside project runs")
    record = select_run(read_json(args.manifest), args.run_id)
    if not 1 <= args.timeout <= 2400 or args.steps < 0 or args.steps > record["horizon"]:
        raise SystemExit("Invalid bounded chunk size")
    if args.steps == 0 and not args.resume:
        raise SystemExit("Zero steps only verifies checkpoint restore")
    if args.stop_at:
        check_deadline(args.stop_at, reserve_seconds=180)
    previous = 0
    if args.resume:
        if (args.output / "partial_failure.json").exists():
            raise SystemExit("Cannot resume a partially failed run")
        previous = validate_commit(args.output)["round"]
        if read_json(args.output / "record.json") != record:
            raise SystemExit("Frozen run record differs")
    elif args.output.exists():
        raise SystemExit("Output exists; use an explicit clean resume or a new attempt path")
    if previous + args.steps > record["horizon"]:
        raise SystemExit("Chunk exceeds the frozen horizon")
    authorization = None
    if args.mode == "llm":
        if not args.authorization:
            raise SystemExit("LLM mode requires a separately approved stage authorization")
        check_deadline(args.stop_at, reserve_seconds=180)
        authorization = validate_authorization(read_json(args.authorization), args.manifest, record["stage"], ROOT)
        if record.get("status") == "awaiting_pilot_freeze":
            raise SystemExit("Formal design remains unfrozen")
        validate_attempt(args, record, authorization)
    args.output.mkdir(parents=True, exist_ok=args.resume)
    record_path = args.output / "record.json"
    if not args.resume:
        write_json(record_path, record)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    report = {"version": SPEC_VERSION, "run_id": args.run_id, "stage": record["stage"], "mode": args.mode,
              "invocation_id": stamp, "status": "technical_failure", "clean_commit": False,
              "requested_steps": args.steps, "committed_steps": previous, "measured_rounds": 0,
              "requests": 0, "source_manifest": code_manifest(ROOT), "model_settings": MODEL_SETTINGS}
    started = time.monotonic()
    ledger = None
    ok = False
    try:
        # Every mode owns the same framework lifecycle; only LLM opens the API proxy.
        with ControllerLock(ROOT / "runs" / "v3-framework-runtime"):
            if args.mode == "scripted":
                ok = launch(args, record_path, "http://127.0.0.1:9/v1", report)
            else:
                from policy_v3.budget import open_stage_ledger
                from dotenv import dotenv_values
                ledger = open_stage_ledger(ROOT, args.authorization, args.manifest, record["stage"])
                report["budget_before"] = ledger.summary()
                key = dotenv_values(ROOT / ".env.smoke").get("AGENTSOCIETY_LLM_API_KEY")
                if not key:
                    raise RuntimeError("Existing cloud-only secret configuration is missing")
                with BudgetProxy(key, ledger) as proxy:
                    key = None
                    ok = launch(args, record_path, proxy.base_url, report, proxy)
            if ok:
                driver = read_json(args.output / "driver_latest.json")
                committed = validate_commit(args.output)
                if not driver.get("ok") or not driver.get("ray_shutdown"):
                    raise RuntimeError("Official driver or shutdown verification failed")
                if committed["round"] != previous + args.steps:
                    raise RuntimeError("Committed round differs from requested chunk")
                report.update(clean_commit=True, committed_steps=committed["round"],
                    measured_rounds=committed["round"] - previous,
                    status="complete" if committed["round"] == record["horizon"] else "checkpoint",
                    checkpoint="committed.json", metrics=driver["metrics"], ray_shutdown=True)
    except Exception as error:
        ok = False
        report["status"] = "technical_failure"
        report["clean_commit"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if ledger:
            report["budget_after"] = ledger.summary()
            report["requests"] = report["budget_after"]["requests"] - report["budget_before"]["requests"]
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(args.output / f"controller-{stamp}.json", report)
        write_json(args.output / "controller_receipt.json", report)
        print(json.dumps({k: v for k, v in report.items() if k not in {"source_manifest", "metrics"}}, ensure_ascii=False), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
