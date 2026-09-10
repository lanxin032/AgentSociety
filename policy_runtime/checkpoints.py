"""Commit and validate one complete four-actor framework round.

Drivers persist their framework workspaces first, then call ``commit_round``.
Only its final atomic write makes the round eligible for recovery. Reading a
commit always checks the same file set and completed-round invariants.
"""
import hashlib
from pathlib import Path

from policy_mve.io import digest, read_json, write_json


def _checkpoint_files(run_dir):
    paths = [run_dir / name for name in (
        "SOCIETY.json", "SOCIETY_STEP.json", "world.json", "metrics.json", "run_config.json")]
    paths += list((run_dir / "env").rglob("*.json"))
    paths += [path for path in (run_dir / "agents").rglob("*.json")
              if path.name in {"AGENT.json", "config.json", "business.json"}]
    paths += list(run_dir.glob("*.jsonl"))
    paths += list((run_dir / "agents").rglob("decisions.jsonl"))
    return {path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def _validate_round_state(run_dir, count):
    if type(count) is not int or count < 1:
        raise RuntimeError("Checkpoint requires a completed round")
    if read_json(run_dir / "SOCIETY_STEP.json")["step_count"] != count:
        raise RuntimeError("Society did not persist the completed round")
    agent_files = sorted((run_dir / "agents").glob("*/AGENT.json"))
    if len(agent_files) != 4:
        raise RuntimeError("Expected exactly four actor checkpoints")
    ids = set()
    for path in agent_files:
        meta = read_json(path)
        actor_id = meta.get("agent_id", meta.get("id"))
        if type(actor_id) is not int or actor_id not in {1, 2, 3, 4} or actor_id in ids or meta.get("step_count") != count:
            raise RuntimeError("Actor checkpoint identity or round mismatch")
        ids.add(actor_id)
        business = read_json(path.parent / "state/business.json")
        if not business.get("history") or business["history"][-1]["round"] != count - 1:
            raise RuntimeError("Actor business state is not from the completed round")


def _require_clean(run_dir):
    if (run_dir / "partial_failure.json").exists():
        raise RuntimeError("Partial failure evidence is present; not a clean committed attempt")


def commit_round(run_dir, count, snapshot, actor_results):
    """Validate persisted artifacts against the live round, then publish its marker.

    ``actor_results`` may include earlier rounds. A failed validation or failed
    atomic marker replacement leaves the previous marker intact; changed files
    will still prevent that old marker from being used to resume.
    """
    run_dir = Path(run_dir)
    _require_clean(run_dir)
    entries = [entry for entry in actor_results if entry["round"] == count - 1]
    if (len(entries) != 4 or any(type(entry.get("actor_id")) is not int for entry in entries)
            or {entry["actor_id"] for entry in entries} != {1, 2, 3, 4}):
        raise RuntimeError("Missing or duplicate actor results")
    if snapshot.get("round") != count:
        raise RuntimeError("Live environment does not match the completed round")
    if digest(snapshot) != digest(read_json(run_dir / "world.json")):
        raise RuntimeError("Persisted environment does not match live actor")
    _validate_round_state(run_dir, count)
    committed = {"round": count, "world_sha256": digest(snapshot), "files": _checkpoint_files(run_dir)}
    write_json(run_dir / "committed.json", committed)
    return committed


def validate_commit(run_dir):
    """Read an intact, complete checkpoint without changing its evidence."""
    run_dir = Path(run_dir)
    _require_clean(run_dir)
    committed = read_json(run_dir / "committed.json")
    if committed["files"] != _checkpoint_files(run_dir):
        raise RuntimeError("Checkpoint set changed or was only partially persisted")
    world = read_json(run_dir / "world.json")
    if digest(world) != committed["world_sha256"]:
        raise RuntimeError("World does not match committed checkpoint")
    if world.get("round") != committed["round"]:
        raise RuntimeError("World does not match committed round")
    _validate_round_state(run_dir, committed["round"])
    return committed
