"""Paid, explicitly directed interface fixtures; never an autonomous policy run."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_mve.core import PolicyWorld
from policy_mve.io import append_jsonl, digest, source_manifest, write_json
from policy_mve.llm import BoundedClient, MODEL, parse_object, validate_action
from policy_mve.verify import verify_world
from mve_budget import open_mve_ledger
from smoke_budget import BudgetProxy


def settle(world, actor, action):
    receipt = world.submit(actor, action)
    if receipt.get("status") != "queued":
        raise RuntimeError("Fixture submission failed")
    world.advance()
    result = next(e for e in reversed(world.events) if e["kind"] == "action_result" and e["actor_id"] == actor)
    if result.get("status") != "executed":
        raise RuntimeError("Fixture business action failed: " + json.dumps(result))


def candidate(world, actor, kind, target=None, **params):
    found = [a for a in world.observe(actor)["available_actions"]
             if a["kind"] == kind and (target is None or a["target"] == target)
             and all(a["params"].get(k) == v for k, v in params.items())]
    if not found:
        raise RuntimeError("Directed fixture action is not currently legal: " + kind)
    return found[0]


async def directed(client, world, actor, wanted, out):
    observation = world.observe(actor)
    messages = [{"role": "system", "content": "这是接口连通性测试，不是自主政策实验。请将用户指定的合法候选动作编码为JSON，只输出kind、target、params、reason。不得改目标或参数。"},
                {"role": "user", "content": json.dumps({"observation": observation, "requested_legal_action": wanted}, ensure_ascii=False)}]
    for attempt in range(2):
        response = await client.call(MODEL, messages)
        raw = response.choices[0].message.content
        append_jsonl(out / "probe_calls.jsonl", {"fixture": "directed_interface_only", "actor_id": actor,
                      "round": world.round, "attempt": attempt, "messages": messages, "input_sha256": digest(messages),
                      "response": raw, "usage": response.usage})
        try:
            action = validate_action(parse_object(raw))
            if any(action[k] != wanted[k] for k in ("kind", "target", "params")):
                raise ValueError("Model did not encode the directed candidate")
            settle(world, actor, action)
            return
        except (ValueError, TypeError):
            if attempt:
                raise RuntimeError("Directed interface schema failed after one repair")
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "请严格输出指定候选，不改变kind、target或params。"}]


async def exercise(client, out):
    world = PolicyWorld(policy="111", seed=0, horizon=30)
    # Only legal baseline actions prepare the cross-department fixture.
    settle(world, 1, candidate(world, 1, "route", "T00004", department=2, use_recommendation=False))
    settle(world, 2, candidate(world, 2, "inspect", "T00004"))
    await directed(client, world, 2, candidate(world, 2, "request_coordination", "T00004", mode="joint"), out)
    for actor in (2, 3):
        await directed(client, world, actor, candidate(world, actor, "confirm_joint_task", "T00004"), out)
    for actor in (2, 3):
        settle(world, actor, candidate(world, actor, "work", "T00004"))
    write_json(out / "B_world.json", world.export_state())
    write_json(out / "B_metrics.json", world.metrics())
    bcheck = verify_world(world.export_state())
    # Separate clean synthetic fixture: do not carry B state into C.
    world = PolicyWorld(policy="111", seed=0, horizon=30)
    await directed(client, world, 4, candidate(world, 4, "propose_project", "片区3|供水波动", mode="structured"), out)
    await directed(client, world, 4, candidate(world, 4, "diagnose_project", "P0001"), out)
    for _ in range(world.config["project_steps"]):
        await directed(client, world, 4, candidate(world, 4, "implement_project", "P0001", plan="replace_shared_main"), out)
    while world.round < world.projects["P0001"]["ready_round"]:
        world.advance()
    await directed(client, world, 4, candidate(world, 4, "accept_project", "P0001"), out)
    write_json(out / "C_world.json", world.export_state())
    write_json(out / "C_metrics.json", world.metrics())
    ccheck = verify_world(world.export_state())
    if not bcheck["passed"] or not ccheck["passed"]:
        raise RuntimeError("Independent fixture verification failed")
    return {"B": bcheck, "C": ccheck}


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "runs" / ("mve-probe-" + stamp)
    out.mkdir()
    report = {"ok": False, "kind": "directed_interface_fixture", "autonomous_policy_run": False,
              "framework_used": False, "note": "Model encodes specified legal actions; not adoption or effectiveness evidence.",
              "source_manifest": source_manifest(ROOT)}
    ledger = None
    try:
        from dotenv import dotenv_values
        key = dotenv_values(ROOT / ".env.smoke").get("AGENTSOCIETY_LLM_API_KEY")
        if not key:
            raise RuntimeError("Existing cloud secret is missing")
        ledger = open_mve_ledger(ROOT)
        report["budget_before"] = ledger.summary()
        with BudgetProxy(key, ledger) as proxy:
            key = None
            report["verification"] = asyncio.run(exercise(BoundedClient(proxy.base_url), out))
        report["ok"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if ledger:
            report["budget_after"] = ledger.summary()
        write_json(out / "probe_report.json", report)
        print(json.dumps({k: v for k, v in report.items() if k != "source_manifest"}, ensure_ascii=False, indent=2))
        print("run_dir", str(out))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
