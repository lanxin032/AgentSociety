"""Write explicitly requested offline scripted matrix; no API and no AgentSociety."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_mve.core import PolicyWorld, scripted_action
from policy_mve.io import write_json, canonical, source_manifest
from policy_mve.spec import ACTORS, DEFAULT_CONFIG, SPEC_VERSION
from policy_mve.verify import verify_world, verify_run, state_hash


def run_one(folder, policy, seed, horizon):
    started = time.perf_counter()
    world = PolicyWorld(policy=policy, seed=seed, horizon=horizon)
    for _ in range(horizon):
        decisions = {actor: scripted_action(world.observe(actor)) for actor in ACTORS}
        for actor, action in decisions.items():
            world.submit(actor, action)
        world.advance()
    state = world.export_state()
    write_json(folder / "world.json", state)
    write_json(folder / "metrics.json", world.metrics())
    (folder / "action_events.jsonl").write_text("".join(canonical(e) + "\n" for e in state["events"] if e["kind"] in ("action_submitted", "action_result")), encoding="utf-8")
    hashes = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("world.json", "metrics.json", "action_events.jsonl")}
    write_json(folder / "committed.json", {"round": world.round, "world_sha256": state_hash(state), "files": hashes, "mode": "offline_scripted"})
    verification = verify_run(folder)
    write_json(folder / "verification.json", verification)
    hashes.update({name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("committed.json", "verification.json")})
    return {"path": folder.name, "policy": policy, "seed": seed, "horizon": horizon, "status": "offline_scripted_pass" if verification["passed"] else "offline_scripted_fail", "elapsed_seconds": time.perf_counter() - started, "files": hashes, "metrics": world.metrics(), "errors": verification["errors"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; existing directory is rejected")
    parser.add_argument("--smoke", action="store_true", help="Seed 0, eight policies, 18 rounds; checks source project completion")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new directory to preserve evidence")
    args.output.mkdir(parents=True)
    started = time.perf_counter()
    seeds, horizon = ([0], 18) if args.smoke else ([101, 102, 103], 30)
    runs = []
    for seed in seeds:
        for index in range(8):
            policy = f"{index:03b}"
            folder = args.output / f"seed-{seed}_policy-{policy}"
            try:
                record = run_one(folder, policy, seed, horizon)
                if args.smoke and record["metrics"]["projects_completed"] < 1:
                    record["status"] = "offline_scripted_fail"
                    record["errors"].append("smoke source project did not complete")
            except Exception as exc:
                record = {"path": folder.name, "policy": policy, "seed": seed, "horizon": horizon, "status": "offline_scripted_fail", "errors": [str(exc)]}
            runs.append(record)
    write_json(args.output / "batch_plan.json", {"status": "not_authorized_not_executed", "mode": "real_model_future_batch", "policies": [f"{i:03b}" for i in range(8)], "seeds": [101, 102, 103], "horizon": 30, "runs": 24, "requires": "接入后报价及另行批准；现有5元200请求仅限接入", "note": "离线脚本矩阵不是LLM预实验，也不消耗或替代真实模型重复"})
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "mode": "offline_scripted", "spec_version": SPEC_VERSION, "config": DEFAULT_CONFIG, "api_requests": 0, "framework_used": False, "is_llm_experiment": False, "note": "脚本控制器只读取observe输出；该矩阵验证业务流程，不估计真实模型响应分布。", "elapsed_seconds": time.perf_counter() - started, "runs": runs, "source_files": source_manifest(Path(__file__).resolve().parents[1]), "passed": all(r["status"] == "offline_scripted_pass" for r in runs)}
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps({"output": str(args.output.resolve()), "runs": len(runs), "passed": manifest["passed"], "mode": "offline_scripted"}, ensure_ascii=False))
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
