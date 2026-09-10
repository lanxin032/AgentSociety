"""Versioned runtime identity; excludes changing reports, ledgers and secrets."""
from pathlib import Path
import hashlib
import json


MODEL_SETTINGS = {
    "model": "deepseek-v4-flash", "temperature": 0.2, "max_tokens": 4096,
    "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
}


def code_manifest(root):
    root = Path(root)
    files = []
    for folder in ("policy_v3", "policy_mve", "policy_runtime", "custom", "tools"):
        for path in sorted((root / folder).rglob("*.py")):
            if "__pycache__" not in path.parts:
                files.append({"path": path.relative_to(root).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return sorted(files, key=lambda row: row["path"])


def code_digest(root):
    return hashlib.sha256(json.dumps(code_manifest(root), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def select_run(manifest, run_id):
    rows = [row for row in manifest.get("runs", []) if row.get("run_id") == run_id]
    if len(rows) != 1:
        raise ValueError("run_id must identify exactly one frozen run")
    row = rows[0]
    if type(row.get("seed")) is not int or type(row.get("horizon")) is not int:
        raise ValueError("Run requires an integer seed and horizon")
    scenario = row.get("scenario")
    if not isinstance(scenario, dict):
        matched = [s for s in manifest.get("scenarios", [])
                   if s.get("id") == row.get("scenario_id")]
        if len(matched) != 1:
            raise ValueError("scenario_id must identify exactly one scenario")
        scenario = matched[0]
    if not isinstance(scenario, dict) or scenario.get("horizon") != row["horizon"]:
        raise ValueError("Run and scenario horizons must agree")
    return {**row, "scenario": scenario}
