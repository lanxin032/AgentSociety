"""Run one bounded, real-API smoke test and keep a machine-readable report."""

import argparse
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from smoke_budget import BudgetLedger, BudgetProxy, LOCAL_KEY, MODEL


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-query", type=Path)
    args = parser.parse_args()
    if args.resume_query:
        args.resume_query = args.resume_query.resolve(strict=True)
        if not args.resume_query.is_relative_to(root / "runs"):
            raise SystemExit("Resume query must use this project's existing run directory.")
    configuration = dotenv_values(root / ".env.smoke")
    key = configuration.get("AGENTSOCIETY_LLM_API_KEY")
    if not key:
        raise SystemExit("Configure the cloud-only .env.smoke first.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = root / "runs" / f"smoke-{run_id}"
    run_dir.mkdir(parents=True)
    os.chdir(root)
    # One ledger covers retries and reruns of this test, not just one process.
    ledger = BudgetLedger(root / "runs" / "api-smoke-budget-20260909.json")
    report = {"ok": False, "run_id": run_id, "run_dir": str(run_dir), "model": MODEL,
              "framework_version": metadata.version("agentsociety2"), "python": sys.version}
    before = ledger.summary()
    try:
        with BudgetProxy(key, ledger) as proxy:
            if args.resume_query:
                report["resumed_from"] = str(args.resume_query)
                print("Restoring the existing checkpoint for query only; no new simulation steps.", flush=True)
            else:
                body = json.dumps({"model": MODEL, "messages": [
                    {"role": "system", "content": "This is an API connectivity test. Respond only with the requested text."},
                    {"role": "user", "content": "Reply exactly: CLOUD_SMOKE_OK"},
                ], "max_tokens": 512, "stream": False}).encode()
                request = Request(proxy.base_url + "/chat/completions", data=body, headers={
                    "Content-Type": "application/json", "Authorization": f"Bearer {LOCAL_KEY}"})
                with urlopen(request, timeout=85) as response:
                    probe = json.load(response)
                message = probe["choices"][0]["message"].get("content") or ""
                report["api_probe"] = {"reply": message, "usage": probe.get("usage")}
                if "CLOUD_SMOKE_OK" not in message:
                    raise AssertionError("API response did not contain the connectivity marker")
                print("API probe passed; starting two-agent simulation.", flush=True)
            environment = os.environ.copy()
            environment.update({
                "AGENTSOCIETY_LLM_API_KEY": LOCAL_KEY,
                "AGENTSOCIETY_LLM_API_BASE": proxy.base_url,
                "AGENTSOCIETY_LLM_MODEL": MODEL,
                "AGENTSOCIETY_CODER_LLM_API_KEY": LOCAL_KEY,
                "AGENTSOCIETY_CODER_LLM_API_BASE": proxy.base_url,
                "AGENTSOCIETY_CODER_LLM_MODEL": MODEL,
                "AGENTSOCIETY_EMBEDDING_API_KEY": LOCAL_KEY,
                "AGENTSOCIETY_EMBEDDING_API_BASE": proxy.base_url,
                "AGENTSOCIETY_EMBEDDING_MODEL": "bge-m3",
                "AGENTSOCIETY_LLM_RAY_MAX_WORKERS": "2",
                "AGENTSOCIETY_LLM_REQUEST_TIMEOUT": "85",
                "LITELLM_LOCAL_MODEL_COST_MAP": "True",
                "RAY_USAGE_STATS_ENABLED": "0",
                "HF_HUB_OFFLINE": "1",
                "PYTHONUNBUFFERED": "1",
            })
            driver_report = run_dir / "driver_summary.json"
            command = [sys.executable, str(root / "tools" / "smoke_driver.py"),
                       "--run-dir", str(args.resume_query or run_dir / "simulation"), "--report", str(driver_report)]
            if args.resume_query:
                command.append("--query-only")
            with (run_dir / "output.log").open("w", encoding="utf-8") as output:
                process = subprocess.Popen(command, env=environment, stdout=output, stderr=subprocess.STDOUT)
                try:
                    return_code = process.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise TimeoutError("Simulation exceeded the five-minute smoke-test deadline")
            report["driver_exit_code"] = return_code
            report["driver"] = json.loads(driver_report.read_text()) if driver_report.is_file() else {}
            report["ok"] = return_code == 0 and report["driver"].get("ok") is True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report["budget_before"] = before
        report["budget_after"] = ledger.summary()
        report["billing_note"] = "Estimates use the platform's displayed token prices; the account bill is authoritative. Unknown usage retains its conservative reservation."
        (run_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
