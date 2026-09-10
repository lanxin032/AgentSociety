"""Run a registered PolicyV3Officer/PolicyV3Env on official AgentSociety + Ray."""
import argparse
import asyncio
from datetime import datetime
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_mve.io import read_json, write_json, digest, source_manifest
from policy_v3.spec import SPEC_VERSION


def checkpoint_files(run_dir):
    paths = [run_dir / name for name in ["SOCIETY.json", "SOCIETY_STEP.json", "world.json", "metrics.json", "run_config.json"]]
    paths += list((run_dir / "env").rglob("*.json"))
    for path in (run_dir / "agents").rglob("*.json"):
        if path.name in {"AGENT.json", "config.json", "business.json"}:
            paths.append(path)
    paths += list(run_dir.glob("*.jsonl"))
    paths += list((run_dir / "agents").rglob("decisions.jsonl"))
    return {p.relative_to(run_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def validate_commit(run_dir):
    committed = read_json(run_dir / "committed.json")
    if committed["files"] != checkpoint_files(run_dir):
        raise RuntimeError("Checkpoint set changed or was only partially persisted")
    if digest(read_json(run_dir / "world.json")) != committed["world_sha256"]:
        raise RuntimeError("World does not match committed checkpoint")
    return committed


def validate_round_state(run_dir, count):
    if read_json(run_dir / "SOCIETY_STEP.json")["step_count"] != count:
        raise RuntimeError("Society did not persist the completed round")
    agent_files = sorted((run_dir / "agents").glob("*/AGENT.json"))
    if len(agent_files) != 4:
        raise RuntimeError("Expected exactly four actor checkpoints")
    ids = set()
    for path in agent_files:
        meta = read_json(path)
        actor_id = meta.get("agent_id", meta.get("id"))
        if actor_id not in {1, 2, 3, 4} or actor_id in ids or meta.get("step_count") != count:
            raise RuntimeError("Actor checkpoint identity or round mismatch")
        ids.add(actor_id)
        business = read_json(path.parent / "state/business.json")
        if not business.get("history") or business["history"][-1]["round"] != count - 1:
            raise RuntimeError("Actor business state is not from the completed round")


async def run(args, report):
    import ray
    from agentsociety2.registry import scan_and_register_custom_modules
    from agentsociety2.agent.service_proxy import build_service_proxy, LLMClients
    from agentsociety2.env.env_router_proxy import EnvRouterProxy
    from agentsociety2.society import AgentSociety
    from policy_mve.llm import BoundedClient
    from policy_v3.router import PolicyV3RouterActor as PolicyRouterActor
    from policy_v3.spec import ACTORS

    class AuditedSociety(AgentSociety):
        async def _await_ref(self, reference):
            result = await reference
            if not getattr(self, "_mve_audit_steps", False):
                return result
            if not isinstance(result, dict) or "results" not in result:
                raise RuntimeError("Missing official task results")
            for item in result["results"]:
                if not item.get("ok"):
                    raise RuntimeError("Official agent task failed: " + str(item))
                parsed = json.loads(item.get("summary") or "null")
                if not isinstance(parsed, dict) or parsed.get("actor_id") not in {1, 2, 3, 4}:
                    raise RuntimeError("Invalid actor receipt summary")
                report.setdefault("agent_results", []).append(parsed)
            return result

        async def to_workspace(self, *, tick=None):
            # Installed default only logs persistence errors; this experiment
            # must stop before marking an unpersisted environment step complete.
            await self._env_router.to_workspaces()
            await super().to_workspace(tick=tick)

    envvars = {key: value for key, value in os.environ.items()
               if key.startswith("AGENTSOCIETY_") or key in {"WORKSPACE_PATH", "PYTHONPATH", "LITELLM_LOCAL_MODEL_COST_MAP", "RAY_USAGE_STATS_ENABLED", "HF_HUB_OFFLINE"}}
    ray.init(address="local", num_cpus=2, include_dashboard=False,
             object_store_memory=128 * 1024 * 1024, runtime_env={"env_vars": envvars}, log_to_driver=False)
    actor = None
    society = None
    try:
        scanned = scan_and_register_custom_modules(ROOT)
        report["custom_registration"] = {key: list(scanned.get(key, {})) if isinstance(scanned.get(key), dict) else str(scanned.get(key, [])) for key in ["envs", "agents", "errors"]}
        proxy = build_service_proxy(None, run_dir=args.run_dir, trace=True, replay=True)
        client = BoundedClient(os.environ["AGENTSOCIETY_LLM_API_BASE"])
        proxy.llm = LLMClients(default=client, coder=BoundedClient(client.base_url), embedding=None)
        remote_class = ray.remote(num_cpus=0, max_concurrency=1)(PolicyRouterActor)
        actor = remote_class.remote(str(args.run_dir), args.policy, args.seed, args.horizon, args.mode, client, scenario=args.scenario)
        env = EnvRouterProxy(actor, run_dir=args.run_dir, env_module_types=["PolicyV3Env"])
        proxy.env = env
        if args.resume:
            society = await AuditedSociety.from_workspace(args.run_dir, env_router=env, service_proxy=proxy)
            if not await env.from_workspaces():
                raise RuntimeError("Checkpoint restore failed")
            restored = await actor.owner_snapshot.remote()
            report["restored_round"] = society.step_count
            if restored.get("round") != society.step_count:
                raise RuntimeError("Society/environment checkpoint round mismatch")
        else:
            specs = [{"id": identifier, "profile": {"id": identifier, "name": f"Role-{identifier}", "bio": str(ACTORS[identifier])},
                      "config": {"decision_mode": args.mode, "enable_memory": False, "enable_todo_list": False}}
                     for identifier in [1, 2, 3, 4]]
            society = AuditedSociety(agent_specs=specs, agent_class_name="PolicyV3Officer", env_router=env,
                        start_t=datetime(2026, 1, 1, 9), run_dir=args.run_dir, service_proxy=proxy,
                        batch_size=1, enable_replay=True, env_module_types=["PolicyV3Env"],
                        env_kwargs={"PolicyV3Env": {"policy": args.policy, "seed": args.seed, "horizon": args.horizon, "scenario": args.scenario}})
            await society.init()
            await society.to_workspace()
        society._mve_audit_steps = True
        for _ in range(args.steps):
            await society.run(num_steps=1, tick=60)
            count = society.step_count
            entries = [x for x in report.get("agent_results", []) if x["round"] == count - 1]
            if len(entries) != 4 or {x["actor_id"] for x in entries} != {1, 2, 3, 4}:
                raise RuntimeError("Missing or duplicate actor results")
            snapshot = await actor.owner_snapshot.remote()
            world_disk = read_json(args.run_dir / "world.json")
            if digest(snapshot) != digest(world_disk):
                raise RuntimeError("Persisted environment does not match live actor")
            validate_round_state(args.run_dir, count)
            checkpoints = {"round": count, "world_sha256": digest(snapshot), "files": checkpoint_files(args.run_dir)}
            write_json(args.run_dir / "committed.json", checkpoints)
            print(json.dumps({"completed_round": count, "metrics": await actor.owner_metrics.remote()}, ensure_ascii=False), flush=True)
        report["completed_steps"] = society.step_count
        report["metrics"] = await actor.owner_metrics.remote()
        report["ok"] = True
    finally:
        if actor is not None and not report.get("ok"):
            try:
                write_json(args.run_dir / "partial_failure.json", await actor.owner_partial.remote())
            except Exception:
                pass
        try:
            if society is not None:
                await society.close()
        finally:
            try:
                if actor is not None:
                    ray.kill(actor, no_restart=True)
            finally:
                ray.shutdown()
                report["ray_shutdown"] = True


def main():
    from policy_v3.runtime import code_manifest, MODEL_SETTINGS
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--mode", choices=["scripted", "llm"], default="scripted")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    record = read_json(args.record)
    args.policy = "111"
    args.seed, args.horizon = record["seed"], record["horizon"]
    args.scenario = record["scenario"]
    if args.steps < 0 or (args.steps == 0 and not args.resume) or args.steps > args.horizon:
        raise SystemExit("Steps must fit the horizon; zero only checks a clean restore")
    os.chdir(ROOT)
    args.run_dir = args.run_dir.resolve()
    if not args.run_dir.is_relative_to(ROOT / "runs"):
        raise SystemExit("Run must be under project runs")
    frozen = {"version": SPEC_VERSION, "mode": args.mode, "record": record,
              "seed": args.seed, "horizon": args.horizon, "scenario": args.scenario,
              "code_manifest": code_manifest(ROOT), "request_settings": MODEL_SETTINGS}
    if args.resume:
        if not (args.run_dir / "committed.json").is_file() or (args.run_dir / "partial_failure.json").exists():
            raise SystemExit("Resume requires an intact clean committed checkpoint")
        committed = validate_commit(args.run_dir)
        if read_json(args.run_dir / "run_config.json") != frozen:
            raise SystemExit("Resume source, model or run definition differs from the frozen checkpoint")
        if committed["round"] + args.steps > args.horizon:
            raise SystemExit("Resume exceeds the frozen horizon")
    else:
        if (args.run_dir / "run_config.json").exists() or (args.run_dir / "SOCIETY.json").exists():
            raise SystemExit("Refusing to overwrite a prior attempt")
        args.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.run_dir / "run_config.json", frozen)
    report = {"ok": False, "version": SPEC_VERSION, "mode": args.mode,
              "run_id": record["run_id"], "seed": args.seed,
              "scenario_id": record["scenario_id"], "scenario": args.scenario,
              "framework_version": importlib.metadata.version("agentsociety2"),
              "source_manifest": code_manifest(ROOT), "request_settings": MODEL_SETTINGS,
              "requested_steps": args.steps, "llm_seed_supported": False,
              "routing": "typed_EnvLike_official_proxy_no_codegen"}
    try:
        asyncio.run(run(args, report))
    except Exception as error:
        report["ok"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        traceback.print_exc()
    finally:
        suffix = f"resume-{report.get('completed_steps', report.get('restored_round', 'failed'))}" if args.resume else "initial"
        write_json(args.run_dir / f"driver-{suffix}.json", report)
        write_json(args.run_dir / "driver_latest.json", report)
        print(json.dumps({k: v for k, v in report.items() if k not in {"agent_results", "source_manifest"}}, ensure_ascii=False), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
