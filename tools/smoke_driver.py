"""Run the installed AgentSociety engine against the bounded local test proxy."""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import traceback


async def run(run_dir, report, query_only=False):
    import ray
    from agentsociety2.agent.service_proxy import build_service_proxy
    from agentsociety2.env.env_router_actor import get_env_router_actor_class
    from agentsociety2.env.env_router_proxy import EnvRouterProxy
    from agentsociety2.society import AgentSociety

    class AuditedSociety(AgentSociety):
        async def _await_ref(self, reference):
            result = await reference
            if isinstance(result, dict) and "results" in result:
                report.setdefault("agent_results", []).extend(result["results"])
                failures = [item for item in result["results"] if not item.get("ok")]
                if failures:
                    raise AssertionError(f"Agent tasks failed: {failures}")
            return result

    ray_environment = {key: value for key, value in os.environ.items() if key.startswith("AGENTSOCIETY_") or key in {"LITELLM_LOCAL_MODEL_COST_MAP", "RAY_USAGE_STATS_ENABLED", "HF_HUB_OFFLINE"}}
    ray.init(address="local", num_cpus=2, include_dashboard=False,
             object_store_memory=128 * 1024 * 1024,
             runtime_env={"env_vars": ray_environment}, log_to_driver=False)
    report["ray_initialized"] = True
    actor = None
    society = None
    try:
        config = {
            "max_react_turns": 2,
            "enable_memory": False,
            "enable_todo_list": False,
            "disabled_skill_ids": ["daily-guidance"],
        }
        specs = [
            {"id": identifier, "profile": {
                "id": identifier,
                "name": name,
                "bio": "A fictional participant in a software connectivity test. During this short step, finish with one brief sentence saying you are ready. Do not read files, activate skills, or make plans.",
            }, "config": dict(config)}
            for identifier, name in [(1, "Alice"), (2, "Bob")]
        ]
        env_types = ["SimpleSocialSpace"]
        env_kwargs = {"SimpleSocialSpace": {"agent_id_name_pairs": [(item["id"], item["profile"]["name"]) for item in specs]}}
        if query_only:
            checkpoint = json.loads((run_dir / "SOCIETY.json").read_text())
            env_types = checkpoint["env_module_types"]
            env_kwargs = checkpoint["env_kwargs"]
        proxy = build_service_proxy(None, run_dir=run_dir, trace=True, replay=True)
        actor = get_env_router_actor_class().remote(
            env_types, env_kwargs, str(run_dir),
            {"final_summary_enabled": False, "max_steps": 2, "max_llm_call_retry": 1, "template_cache_enabled": False},
            {"coder": proxy.llm.coder, "default": proxy.llm.default},
            proxy.replay, proxy.trace,
        )
        env = EnvRouterProxy(actor, run_dir=run_dir, env_module_types=env_types)
        proxy.env = env
        if query_only:
            society = await AgentSociety.from_workspace(run_dir, env_router=env, service_proxy=proxy)
            # Query existing state only; regenerating step/observe code would rerun initialization.
            report["environment_restored"] = await actor.from_workspaces.remote()
            assert report["environment_restored"]
            await actor.set_current_time.remote(society.current_time)
            report["query_only"] = True
        else:
            society = AuditedSociety(
                agent_specs=specs, agent_class_name="PersonAgent", env_router=env,
                start_t=datetime(2026, 1, 1, 9, 0), run_dir=run_dir,
                service_proxy=proxy, batch_size=1, enable_replay=True,
                env_module_types=env_types, env_kwargs=env_kwargs,
            )
            await society.init()
            await society.run(num_steps=1, tick=60)
            results = report.get("agent_results", [])
            assert len(results) == 2 and all(item.get("ok") and item.get("summary") for item in results)
        report["agents_created"] = society.agent_ids
        report["completed_steps"] = society.step_count
        report["simulation_time"] = society.current_time.isoformat()
        report["query_expected"] = society.current_time.isoformat()
        report["query_answer"] = await society.ask(
            "Use get_current_time to read the current simulation time and return its ISO value. Do not ask agents or query the environment."
        )
        assert report["query_expected"] in report["query_answer"], "Query did not return the stored simulation time"
        if not query_only:
            await society.to_workspace()
        report["ok"] = True
    finally:
        if society is not None:
            await society.close()
        if actor is not None:
            ray.kill(actor, no_restart=True)
        ray.shutdown()
        report["ray_shutdown"] = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--query-only", action="store_true")
    args = parser.parse_args()
    report = {"ok": False}
    try:
        asyncio.run(run(args.run_dir, report, args.query_only))
        expected = [args.run_dir / "SOCIETY.json", args.run_dir / "SOCIETY_STEP.json"]
        expected += [args.run_dir / "agents" / f"agent_{identifier:04d}" / "AGENT.json" for identifier in (1, 2)]
        report["checkpoint_files_present"] = all(path.is_file() for path in expected)
        report["replay_files"] = [str(path.relative_to(args.run_dir)) for path in (args.run_dir / "replay").rglob("*.jsonl")]
        assert report["checkpoint_files_present"] and report["replay_files"]
    except BaseException as error:
        report["ok"] = False
        report["error"] = f"{type(error).__name__}: {error}"
        traceback.print_exc()
    finally:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
