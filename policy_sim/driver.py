"""Run a registered PolicyOfficer/PolicyEnv on official AgentSociety + Ray."""
import argparse
import asyncio
from datetime import datetime
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_sim.io import read_json, write_json, source_manifest
from policy_sim.checkpoints import commit_round, validate_commit
from policy_sim.spec import SPEC_VERSION
from policy_sim.client import DRAIN_TIMEOUT


class TaskDrain:
    """Track official awaiters without replacing the framework scheduler."""
    def __init__(self, run_dir, timeout=DRAIN_TIMEOUT):
        self.run_dir = run_dir
        self.timeout = timeout
        self.pending = set()

    async def wait(self, reference, validate):
        async def settle():
            try:
                result = await reference
                validate(result)
                return result
            except BaseException:
                from policy_sim.client import stop_requests
                stop_requests(self.run_dir)
                raise
        task = asyncio.create_task(settle())
        self.pending.add(task)
        try:
            return await asyncio.shield(task)
        finally:
            # Keep unfinished work after gather's early failure/cancellation.
            if task.done():
                self.pending.discard(task)

    async def close(self):
        if not self.pending:
            return
        done, pending = await asyncio.wait(self.pending, timeout=self.timeout)
        for task in done:
            if not task.cancelled():
                task.exception()  # retrieve errors; original failure still propagates
        self.pending.difference_update(done)
        if pending:
            raise RuntimeError("Official task drain deadline exceeded; evidence may be incomplete")


async def run(args, report):
    import ray
    from agentsociety2.registry import scan_and_register_custom_modules
    from agentsociety2.agent.service_proxy import build_service_proxy, LLMClients
    from agentsociety2.env.env_router_proxy import EnvRouterProxy
    from agentsociety2.society import AgentSociety
    from policy_sim.router import PolicyRouter as PolicyRouterActor
    from policy_sim.spec import ACTORS

    drain = TaskDrain(args.run_dir)

    class AuditedSociety(AgentSociety):
        async def _await_ref(self, reference):
            return await drain.wait(reference, self._validate_result)

        def _validate_result(self, result):
            if not getattr(self, "_audit_steps", False):
                return result
            if (not isinstance(result, dict) or not isinstance(result.get("results"), list)
                    or len(result["results"]) != 1
                    or not isinstance(result["results"][0], dict)):
                raise RuntimeError("Missing or invalid official task results")
            for item in result["results"]:
                if not item.get("ok"):
                    import re
                    from policy_sim.client import ModelClientError
                    matched = re.fullmatch(r"ModelClientError\('([a-z_]+)'\)", str(item.get("error", "")))
                    if matched:
                        raise ModelClientError(matched.group(1))
                    raise RuntimeError("Official agent task failed: " + str(item))
                parsed = json.loads(item.get("summary") or "null")
                if (not isinstance(parsed, dict) or type(parsed.get("actor_id")) is not int
                        or parsed.get("actor_id") not in {1, 2, 3, 4}):
                    raise RuntimeError("Invalid actor receipt summary")
                report.setdefault("agent_results", []).append(parsed)
                if (args.test_scripted_failure_round is not None
                        and len(report['agent_results']) == 2
                        and self.step_count == args.test_scripted_failure_round):
                    raise RuntimeError('Injected scripted failure after two official actor results')
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
        from policy_sim.client import ModelClient
        client = ModelClient(os.environ["AGENTSOCIETY_LLM_API_BASE"],
                             args.run_dir / "model_requests.jsonl", profile=args.runtime_profile)
        proxy.llm = LLMClients(default=client, coder=None, embedding=None)
        remote_class = ray.remote(num_cpus=0, max_concurrency=1)(PolicyRouterActor)
        actor = remote_class.remote(str(args.run_dir), args.policy, args.seed, args.horizon, args.mode, client, scenario=args.scenario)
        env = EnvRouterProxy(actor, run_dir=args.run_dir, env_module_types=["PolicyEnv"])
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
            from policy_sim.agent import RUNTIME_VERSION
            config = {"decision_mode": args.mode, "runtime_version": RUNTIME_VERSION,
                "runtime_profile": args.runtime_profile, "enable_memory": True,
                "enable_todo_list": False, "max_react_turns": 10,
                "default_activated_skill_ids": []}
            config.update({k: v for k, v in args.runtime_profile.items() if k in (
                "memory_context_max_chars", "recent_memory_limit", "memory_consolidation_pending_threshold",
                "memory_consolidation_interval_steps", "memory_high_importance_threshold")})
            specs = [{"id": identifier, "profile": {"id": identifier, "name": f"Role-{identifier}", "bio": str(ACTORS[identifier])},
                      "config": config}
                     for identifier in [1, 2, 3, 4]]
            society = AuditedSociety(agent_specs=specs, agent_class_name="PolicyOfficer", env_router=env,
                        start_t=datetime(2026, 1, 1, 9), run_dir=args.run_dir, service_proxy=proxy,
                        batch_size=1, enable_replay=True, env_module_types=["PolicyEnv"],
                        env_kwargs={"PolicyEnv": {"policy": args.policy, "seed": args.seed, "horizon": args.horizon, "scenario": args.scenario}})
            await society.init()
            await society.to_workspace()
            initial = await actor.owner_snapshot.remote()
            commit_round(args.run_dir, 0, initial, [])
        society._audit_steps = True
        end_step = None if args.until_complete else society.step_count + args.steps
        while end_step is None or society.step_count < end_step:
            await society.run(num_steps=1, tick=60)
            count = society.step_count
            snapshot = await actor.owner_snapshot.remote()
            commit_round(args.run_dir, count, snapshot, report.get("agent_results", []))
            print(json.dumps({"completed_round": count, "metrics": await actor.owner_metrics.remote()}, ensure_ascii=False), flush=True)
            report['completion_status'] = await actor.owner_completion.remote()
            if report['completion_status']['complete']:
                break
        report["completion_status"] = await actor.owner_completion.remote()
        report["completed_steps"] = society.step_count
        report["metrics"] = await actor.owner_metrics.remote()
        report["ok"] = True
    finally:
        if not report.get("ok"):
            from policy_sim.client import stop_requests
            stop_requests(args.run_dir)
        try:
            await drain.close()
            report["inflight_drained"] = True
        except Exception as error:
            report["inflight_drained"] = False
            report["drain_error"] = str(error)
            report["ok"] = False
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


def failure_details(error):
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        if hasattr(error, "error_type"):
            return {"error_type": error.error_type, "retryable": False}
        if "TurnIncomplete" in str(error) or type(error).__name__ == "TurnIncomplete":
            return {"error_type": "turn_incomplete", "retryable": False}
        error = getattr(error, "cause", None) or error.__cause__ or error.__context__
    return {"error_type": "unclassified_failure", "retryable": False}


def main():
    from policy_sim.runtime import code_manifest
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    work = parser.add_mutually_exclusive_group(required=True)
    work.add_argument("--steps", type=int)
    work.add_argument("--until-complete", action="store_true")
    parser.add_argument("--mode", choices=["scripted", "llm"], default="scripted")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument('--test-scripted-failure-round', type=int)
    args = parser.parse_args()
    if args.test_scripted_failure_round is not None and args.mode != 'scripted':
        raise SystemExit('Fault injection is restricted to offline scripted validation')
    record = read_json(args.record)
    args.policy = record.get('policy', '111')
    from policy_sim.profiles import validate_profile, settings_for_purpose
    os.environ["AGENTSOCIETY_LLM_REQUEST_TIMEOUT"] = "660"
    if importlib.metadata.version("agentsociety2") != record['runtime_profile']['framework_version']:
        raise SystemExit("Runtime requires its exact frozen AgentSociety2 version")
    args.runtime_profile = validate_profile(record['runtime_profile'])
    request_settings = settings_for_purpose(args.runtime_profile)
    args.seed, args.horizon = record["seed"], record["horizon"]
    args.scenario = record["scenario"]
    if args.steps is not None and args.steps < 0:
        raise SystemExit("Steps must be nonnegative")
    os.chdir(ROOT)
    args.run_dir = args.run_dir.resolve()
    if not args.run_dir.is_relative_to(ROOT / "runs"):
        raise SystemExit("Run must be under project runs")
    frozen = {"version": SPEC_VERSION, "mode": args.mode, "record": record,
              "seed": args.seed, "horizon": args.horizon, "scenario": args.scenario,
              "code_manifest": code_manifest(ROOT), "request_settings": request_settings}
    frozen['runtime_profile'] = args.runtime_profile
    if args.resume:
        if not (args.run_dir / "committed.json").is_file() or (args.run_dir / "partial_failure.json").exists():
            raise SystemExit("Resume requires an intact clean committed checkpoint")
        committed = validate_commit(args.run_dir)
        if read_json(args.run_dir / "run_config.json") != frozen:
            raise SystemExit("Resume source, model or run definition differs from the frozen checkpoint")
    else:
        if (args.run_dir / "run_config.json").exists() or (args.run_dir / "SOCIETY.json").exists():
            raise SystemExit("Refusing to overwrite a prior attempt")
        args.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.run_dir / "run_config.json", frozen)
    report = {"ok": False, "version": SPEC_VERSION, "mode": args.mode,
              "run_id": record["run_id"], "seed": args.seed,
              "scenario_id": record["scenario_id"], "scenario": args.scenario,
              "framework_version": importlib.metadata.version("agentsociety2"),
              "source_manifest": code_manifest(ROOT), "request_settings": request_settings,
              "requested_steps": args.steps, "until_complete": args.until_complete, "llm_seed_supported": False,
              "routing": "official_PersonAgent_ReActRouter"}
    report.update(runtime_profile=args.runtime_profile, model_settings=request_settings)
    try:
        asyncio.run(run(args, report))
    except Exception as error:
        report["ok"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        report["failure"] = failure_details(error)
        traceback.print_exc()
    finally:
        suffix = f"resume-{report.get('completed_steps', report.get('restored_round', 'failed'))}" if args.resume else "initial"
        write_json(args.run_dir / f"driver-{suffix}.json", report)
        write_json(args.run_dir / "driver_latest.json", report)
        print(json.dumps({k: v for k, v in report.items() if k not in {"agent_results", "source_manifest"}}, ensure_ascii=False), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
