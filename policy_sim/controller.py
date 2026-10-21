"""One long-lived paid framework attempt on the original accounting ledger."""
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
from policy_sim.io import read_json, write_json, digest
from policy_sim.runtime import select_run, code_manifest
from policy_sim.spec import SPEC_VERSION
from policy_sim.execution import (AttemptRegistry, ExecutionError, check_deadline,
                                 validate_authorization, authorization_paths, file_hash, load_manifest)
from policy_sim.checkpoints import validate_commit
from policy_sim.proxy import BudgetProxy, LOCAL_KEY, ControllerLock, UPSTREAM


def validate_attempt(args, record, authorization):
    if not args.attempt_id:
        raise ExecutionError("Paid execution must be dispatched by the current stage controller")
    registry_path = authorization_paths(authorization, ROOT)["control"] / "attempts.jsonl"
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
    driver_path = args.output / 'driver_latest.json'
    prior_driver_hash = file_hash(driver_path) if driver_path.is_file() else None
    runtime_profile = read_json(record_path)["runtime_profile"]
    env = os.environ.copy()
    env.update({"WORKSPACE_PATH": str(ROOT), "PYTHONPATH": str(ROOT),
        "AGENTSOCIETY_LLM_API_KEY": LOCAL_KEY, "AGENTSOCIETY_LLM_API_BASE": base_url,
        "AGENTSOCIETY_LLM_MODEL": runtime_profile["model"], "AGENTSOCIETY_CODER_LLM_API_KEY": LOCAL_KEY,
        "AGENTSOCIETY_CODER_LLM_API_BASE": base_url, "AGENTSOCIETY_CODER_LLM_MODEL": runtime_profile["model"],
        "AGENTSOCIETY_EMBEDDING_API_KEY": LOCAL_KEY, "AGENTSOCIETY_EMBEDDING_API_BASE": base_url,
        "AGENTSOCIETY_EMBEDDING_MODEL": "bge-m3", "AGENTSOCIETY_LLM_RAY_MAX_WORKERS": "2",
        "LITELLM_LOCAL_MODEL_COST_MAP": "True", "RAY_USAGE_STATS_ENABLED": "0",
        "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
    env["AGENTSOCIETY_LLM_REQUEST_TIMEOUT"] = "660"
    command = [sys.executable, "-B", "-m", "policy_sim.driver", "--run-dir", str(args.output),
               "--record", str(record_path), "--until-complete", "--mode", "llm"]
    if args.resume:
        command.append("--resume")
    if args.test_scripted_failure_round is not None:
        command.extend(['--test-scripted-failure-round', str(args.test_scripted_failure_round)])
    with (args.output / f"controller-{report['invocation_id']}.log").open("w", encoding="utf-8") as stream:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        start = time.monotonic()
        proxy_failed_at = None
        while child.poll() is None:
            reason = None
            if proxy and proxy.fatal_event.is_set():
                report["proxy_failure"] = proxy.fatal_details
                if proxy_failed_at is None:
                    proxy_failed_at = time.monotonic()
                # Let the official driver persist its failure and shut Ray down.
                if time.monotonic() - proxy_failed_at > 30:
                    reason = "Budget proxy stopped: " + str(proxy.fatal_reason)
            if args.timeout and time.monotonic() - start > args.timeout:
                reason = "Chunk wall-clock cap reached"
                report["failure"] = {"error_type": "chunk_timeout", "retryable": True}
            if args.stop_at:
                deadline = datetime.fromisoformat(args.stop_at.replace("Z", "+00:00"))
                if (deadline - datetime.now(timezone.utc)).total_seconds() < 120:
                    reason = "Cloud deadline approached during a chunk"
                    report["failure"] = {"error_type": "deadline", "retryable": False}
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
    report['ray_shutdown'] = False
    if driver_path.is_file() and file_hash(driver_path) != prior_driver_hash:
        driver = read_json(driver_path)
        report['ray_shutdown'] = driver.get('ray_shutdown') is True
        if not driver.get('ok'):
            from policy_sim.recovery import classify_failure
            report['failure'] = classify_failure(report, driver)
    return child.returncode == 0


def load_api_key(authorization):
    """Read only the configured key after checking the local model and API base."""
    from policy_sim.providers import authorization_route
    route = authorization_route(authorization)
    from dotenv import dotenv_values
    settings = dotenv_values(authorization_paths(authorization, ROOT)["secret"])
    if authorization.get("ledger_scope") == "independent_local":
        if (settings.get("AGENTSOCIETY_LLM_MODEL") != route["model"]
                or (settings.get("AGENTSOCIETY_LLM_API_BASE") or "").rstrip("/")
                != route["base_url"]):
            raise RuntimeError("Local model configuration differs from the authorized fixed upstream/model")
    key = settings.get("AGENTSOCIETY_LLM_API_KEY")
    settings.clear()
    if not key:
        raise RuntimeError("Authorized secret configuration is missing")
    return key


def invocation_receipts(records, baseline):
    """Safe evidence snapshot of only this invocation's actual request records."""
    if type(baseline) is not int or not 0 <= baseline <= len(records):
        raise ExecutionError("Invalid invocation request baseline")
    fields = ('request', 'client_request_id', 'request_sha256', 'request_bytes',
        'started_unix', 'finished_unix', 'model', 'status', 'prompt_tokens', 'completion_tokens',
        'reasoning_tokens', 'finish_reason', 'reserved_rmb', 'estimated_rmb', 'input_rate',
        'output_rate', 'price_version', 'authorization_id', 'max_output_tokens', 'max_body_bytes', 'transport_events')
    return [{key: row[key] for key in fields if key in row} for row in records[baseline:]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--attempt-id")
    parser.add_argument("--stop-at")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    args.mode = "llm"
    args.steps = None
    args.test_scripted_failure_round = None
    args.manifest = args.manifest.resolve()
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / "runs"):
        raise SystemExit("Output must remain inside project runs")
    manifest_header = read_json(args.manifest)
    stage = manifest_header['stage']
    manifest, _ = load_manifest(args.manifest, stage, require_frozen=True)
    record = select_run(manifest, args.run_id)
    from policy_sim.execution import validate_runtime_profile
    profile = validate_runtime_profile(record["runtime_profile"])
    from policy_sim.profiles import settings_for_purpose
    args.timeout = 0
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
    if not args.authorization:
        raise SystemExit("LLM mode requires a separately approved stage authorization")
    authorization = validate_authorization(read_json(args.authorization), args.manifest, record["stage"], ROOT)
    if authorization.get('local_stop_at_utc') and args.stop_at != authorization['local_stop_at_utc']:
        raise SystemExit('Runtime deadline differs from the frozen authorization')
    from policy_sim.protocol import require_baseline
    require_baseline(manifest, ROOT)
    validate_attempt(args, record, authorization)
    args.output.mkdir(parents=True, exist_ok=args.resume)
    record_path = args.output / "record.json"
    if not args.resume:
        write_json(record_path, record)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    report = {"version": SPEC_VERSION, "interface_version": "v3.3-materials-1", "run_id": args.run_id, "stage": record["stage"], "mode": args.mode,
              "invocation_id": stamp, "status": "technical_failure", "clean_commit": False,
              "requested_steps": args.steps, "committed_steps": previous, "measured_rounds": 0,
              "requests": 0, "source_manifest": code_manifest(ROOT), "model_settings": settings_for_purpose(profile)}
    report['runtime_profile'] = profile
    started = time.monotonic()
    ledger = None
    ok = False
    try:
        # One proxy and one Ray lifecycle remain alive until completion or failure.
        with ControllerLock(ROOT / "runs" / "v3-framework-runtime"):
            from policy_sim.budget import open_stage_ledger
            ledger = open_stage_ledger(ROOT, args.authorization, args.manifest, record["stage"])
            report["budget_before"] = ledger.summary()
            key = load_api_key(authorization)
            report.update(authorization_id=authorization["authorization_id"],
                          ledger_scope=authorization["ledger_scope"],
                          historical_usage_status=authorization["historical_usage_status"])
            with BudgetProxy(key, ledger, provider_route=authorization.get("provider_route"),
                             transport_retries=False,
                    upstream_timeout_seconds=profile['upstream_timeout_seconds'],
                    native_idempotency=True,
                    native_profiles=authorization['request_profiles']) as proxy:
                key = None
                ok = launch(args, record_path, proxy.base_url, report, proxy)
            if proxy.fatal_details:
                report['proxy_failure'] = proxy.fatal_details
            if ok:
                driver = read_json(args.output / "driver_latest.json")
                committed = validate_commit(args.output)
                if not driver.get("ok") or not driver.get("ray_shutdown"):
                    raise RuntimeError("Official driver or shutdown verification failed")
                complete = driver.get('completion_status', {}).get('complete') is True
                if not complete or committed["round"] < previous:
                    raise RuntimeError("Driver returned without workload completion")
                report.update(clean_commit=True, committed_steps=committed["round"],
                    measured_rounds=committed["round"] - previous,
                    status="complete" if complete else "checkpoint",
                    checkpoint="committed.json", metrics=driver["metrics"], ray_shutdown=True)
                report['completion_status'] = driver['completion_status']
    except Exception as error:
        ok = False
        report["status"] = "technical_failure"
        report["clean_commit"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        # Failed live workspaces remain unclean, but their immutable completed
        # rounds still provide the truthful amount of settled progress.
        commits = args.output.parent / (args.output.name + '-commits')
        latest_path = commits / 'latest.json'
        if latest_path.is_file():
            try:
                latest = read_json(latest_path)
                snapshot_path = Path(latest['path']).resolve()
                if not snapshot_path.is_relative_to(commits.resolve()):
                    raise RuntimeError('Latest checkpoint escapes its attempt')
                marker = validate_commit(snapshot_path)
                if (latest['round'] != marker['round']
                        or latest['committed_sha256'] != file_hash(snapshot_path / 'committed.json')
                        or marker['round'] < previous):
                    raise RuntimeError('Latest checkpoint binding differs')
                report.update(latest_committed_round=marker['round'], committed_steps=marker['round'],
                              measured_rounds=marker['round'] - previous)
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                report['checkpoint_inspection_error'] = f'{type(error).__name__}: {error}'
        if ledger:
            report["budget_after"] = ledger.summary()
            report['pending_requests'] = sum(row.get('status') == 'reserved' for row in ledger.records)
            report["requests"] = report["budget_after"]["requests"] - report.get("budget_before", report["budget_after"])["requests"]
            # Preserve this invocation's UUID/hash/usage evidence, including failed calls.
            baseline = report.get('budget_before', report['budget_after'])['requests']
            report['request_receipts'] = invocation_receipts(ledger.records, baseline)
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(args.output / f"controller-{stamp}.json", report)
        write_json(args.output / "controller_receipt.json", report)
        print(json.dumps({k: v for k, v in report.items() if k not in {"source_manifest", "metrics", "request_receipts"}}, ensure_ascii=False), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
