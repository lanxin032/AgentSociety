"""Inspect the cloud environment without creating a simulation or using an LLM."""

import hashlib
import importlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import time


def read_limit(path):
    file = Path(path)
    return file.read_text().strip() if file.is_file() else None


def inspect_environment():
    versions = {}
    for name in ("agentsociety2", "ray", "numpy", "pandas", "pydantic", "openai"):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None

    variable_names = (
        "AGENTSOCIETY_LLM_API_KEY",
        "AGENTSOCIETY_LLM_API_BASE",
        "AGENTSOCIETY_LLM_MODEL",
    )
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "packages": versions,
        "original_config_present": {name: bool(os.environ.get(name)) for name in variable_names},
        "cgroup_limits": {
            "cpu_quota_us": read_limit("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
            "cpu_period_us": read_limit("/sys/fs/cgroup/cpu/cpu.cfs_period_us"),
            "memory_bytes": read_limit("/sys/fs/cgroup/memory/memory.limit_in_bytes"),
            "cpu_max": read_limit("/sys/fs/cgroup/cpu.max"),
            "memory_max": read_limit("/sys/fs/cgroup/memory.max"),
        },
    }


def check_imports():
    def blocked(*args, **kwargs):
        raise RuntimeError("Python network connections disabled for offline check")

    # These values exist only in this diagnostic process, never in a saved .env.
    os.environ["AGENTSOCIETY_LLM_API_KEY"] = "offline-diagnostic-not-a-real-key"
    os.environ["AGENTSOCIETY_LLM_API_BASE"] = "http://127.0.0.1:9/v1"
    os.environ["AGENTSOCIETY_LLM_MODEL"] = "offline-diagnostic"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    socket.create_connection = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked

    results = {}
    for name in ("ray", "agentsociety2", "agentsociety2.society"):
        start = time.monotonic()
        try:
            module = importlib.import_module(name)
            results[name] = {
                "ok": True,
                "module_version": getattr(module, "__version__", None),
                "seconds": round(time.monotonic() - start, 2),
            }
        except Exception as error:
            results[name] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
    return results


def main():
    report = inspect_environment()
    payload = b"AgentSociety cloud read/write diagnostic\n"
    with tempfile.TemporaryDirectory(prefix=".connection-check-", dir=Path.cwd()) as directory:
        file = Path(directory) / "probe.txt"
        file.write_bytes(payload)
        report["file_roundtrip_ok"] = file.read_bytes() == payload
        report["file_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        report["pip_check"] = {
            "exit_code": result.returncode,
            "output": result.stdout.strip(),
            "error": result.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        report["pip_check"] = {"exit_code": None, "error": str(error)}

    report["offline_imports"] = check_imports()
    report["simulation_started"] = False
    report["real_model_credentials_used"] = False
    print(json.dumps(report, indent=2))
    return 0 if report["file_roundtrip_ok"] and all(
        entry["ok"] for entry in report["offline_imports"].values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
