"""Single-owner bounded controller. Scripted mode never reads the real secret."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_mve.io import write_json
from smoke_budget import BudgetProxy, LOCAL_KEY, MODEL
from mve_budget import open_mve_ledger


def driver(args, run_dir, base_url, report, proxy=None):
    env = os.environ.copy()
    env.update({"WORKSPACE_PATH": str(ROOT), "PYTHONPATH": str(ROOT),
                "AGENTSOCIETY_LLM_API_KEY": LOCAL_KEY, "AGENTSOCIETY_LLM_API_BASE": base_url,
                "AGENTSOCIETY_LLM_MODEL": MODEL, "AGENTSOCIETY_CODER_LLM_API_KEY": LOCAL_KEY,
                "AGENTSOCIETY_CODER_LLM_API_BASE": base_url, "AGENTSOCIETY_CODER_LLM_MODEL": MODEL,
                "AGENTSOCIETY_EMBEDDING_API_KEY": LOCAL_KEY, "AGENTSOCIETY_EMBEDDING_API_BASE": base_url,
                "AGENTSOCIETY_EMBEDDING_MODEL": "bge-m3", "AGENTSOCIETY_LLM_RAY_MAX_WORKERS": "2",
                "LITELLM_LOCAL_MODEL_COST_MAP": "True", "RAY_USAGE_STATS_ENABLED": "0",
                "HF_HUB_OFFLINE": "1", "PYTHONUNBUFFERED": "1"})
    command = [sys.executable, "-B", str(ROOT / "tools/mve_driver.py"), "--run-dir", str(run_dir),
               "--policy", args.policy, "--seed", str(args.seed), "--steps", str(args.steps),
               "--horizon", str(args.horizon), "--mode", args.mode]
    if args.resume:
        command.append("--resume")
    log_path = run_dir / f"controller-{report['invocation_id']}.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        start = time.monotonic()
        while process.poll() is None:
            reason = None
            if proxy and proxy.fatal_event.is_set():
                reason = "Budget proxy terminated: " + str(proxy.fatal_reason)
            if time.monotonic() - start > args.timeout:
                reason = "Controller wall-clock limit reached"
            if reason:
                report["stop_reason"] = reason
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                break
            time.sleep(0.5)
        report["driver_exit_code"] = process.returncode
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        report["ok"] = process.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scripted", "llm"], default="scripted")
    parser.add_argument("--policy", choices=[f"{x:03b}" for x in range(8)], default="111")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--horizon", type=int, default=30)
    parser.add_argument("--steps", type=int, default=18)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    if args.steps < 0 or args.steps > args.horizon or not 1 <= args.timeout <= 2400:
        raise SystemExit("Invalid bounded run size")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = args.resume.resolve() if args.resume else ROOT / "runs" / f"mve-{args.mode}-{stamp}"
    if not run_dir.is_relative_to(ROOT / "runs"):
        raise SystemExit("Run directory is outside project runs")
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "invocation_id": stamp, "run_dir": str(run_dir), "mode": args.mode,
              "billing_note": "Token-price estimate, not a reconciled provider bill."}
    ledger = None
    try:
        if args.mode == "scripted":
            driver(args, run_dir, "http://127.0.0.1:9/v1", report)
        else:
            from dotenv import dotenv_values
            key = dotenv_values(ROOT / ".env.smoke").get("AGENTSOCIETY_LLM_API_KEY")
            if not key:
                raise RuntimeError("Cloud-only secret configuration is missing")
            ledger = open_mve_ledger(ROOT)
            report["budget_before"] = ledger.summary()
            report["authorization"] = ledger.authorization
            with BudgetProxy(key, ledger) as proxy:
                key = None
                driver(args, run_dir, proxy.base_url, report, proxy)
    except Exception as error:
        report["ok"] = False
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if ledger:
            report["budget_after"] = ledger.summary()
        write_json(run_dir / f"controller-{stamp}.json", report)
        print(__import__("json").dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
