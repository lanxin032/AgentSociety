"""Versioned runtime identity; excludes changing reports, ledgers and secrets."""
from pathlib import Path
import hashlib
import json


def is_public_source(path, root):
    """Exclude credentials and links before reading bytes for a source bundle."""
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    for part in relative.parts:
        name = part.lower()
        if (name == ".env" or name.startswith(".env.") or name in {"__pycache__", ".git"}
                or name.endswith((".pem", ".key", ".p12", ".pfx"))):
            return False
    return path.is_file() and not any(p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root))


def code_manifest(root):
    root = Path(root)
    files = []
    for folder in ("policy_sim", "custom", "tools"):
        for path in sorted((root / folder).rglob("*.py")):
            if is_public_source(path, root):
                files.append({"path": path.relative_to(root).as_posix(),
                              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for path in sorted((root / "custom/skills").rglob("*")):
        if is_public_source(path, root):
            files.append({"path": path.relative_to(root).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for name in ('environment.yml', 'requirements.lock'):
        path = root / name
        if is_public_source(path, root):
            files.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return sorted(files, key=lambda row: row["path"])


def code_digest(root):
    return hashlib.sha256(json.dumps(code_manifest(root), sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def runtime_environment():
    """Check the installed lock and record the environment used by a run."""
    from importlib.metadata import version
    import platform
    packages = {}
    lock = Path(__file__).resolve().parents[1] / 'requirements.lock'
    for line in lock.read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        name, expected = line.split('==')
        actual = version(name)
        if actual != expected:
            raise ValueError(f'{name} differs from requirements.lock: expected {expected}, installed {actual}')
        packages[name] = actual
    return {'python': platform.python_version(), 'platform': platform.system(),
            'machine': platform.machine(), 'packages': packages}


def select_run(manifest, run_id):
    rows = [row for row in manifest.get("runs", []) if row.get("run_id") == run_id]
    if len(rows) != 1:
        raise ValueError("run_id must identify exactly one frozen run")
    row = rows[0]
    if row.get("workload_mode") != "finite" or type(row.get("seed")) is not int or row.get("horizon") is not None:
        raise ValueError("Current runs require finite workload without fixed horizon")
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
