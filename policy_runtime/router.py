"""Typed implementation of the official EnvLike protocol, owned by one Ray actor.

No generated Python or natural-language mutation routes. AgentSociety retains
its scheduler, lifecycle, official proxy, replay and AgentBase/EnvBase modules.
"""
import copy
import json
from pathlib import Path
from policy_mve.io import write_json, read_json, append_jsonl, digest


class PolicyRouter:
    def __init__(self, env, run_dir, env_name, decision_mode, llm_client, *, finalize_observation=None):
        self.run_dir = Path(run_dir)
        self.env_path = self.run_dir / "env" / env_name
        self.env = env
        self.env._bind_workspace(self.env_path)
        self.decision_mode = decision_mode
        self.llm_client = llm_client
        self.finalize_observation = finalize_observation
        self.submitted = set()
        self.advice_cache = {}
        self.replay = None
        self.last_snapshot = None

    def set_current_time(self, t):
        self.t = t

    def set_replay_writer(self, writer):
        self.replay = writer

    async def get_world_description(self):
        return "合成供水办理：各角色依法观察与选择行动，资源有限，个案和源头治理共享资源。"

    async def init(self, start_datetime):
        await self.env.init(start_datetime)
        self.t = start_datetime
        await self.to_workspaces()
        return True

    async def ask(self, ctx, instruction, readonly=False, template_mode=False, trace_id=None, parent_span_id=None):
        actor_id = ctx.get("actor_id")
        if type(actor_id) is not int or actor_id not in {1, 2, 3, 4}:
            raise ValueError("Runtime actor identity required")
        if instruction == "observe" and readonly:
            obs = copy.deepcopy(self.env.observe(actor_id))
            obs.pop("policy", None)
            # Tool advice enhancement is implemented separately; core fixture
            # advice must never be mislabelled as a real-model recommendation.
            obs = await self.enrich_advice(obs)
            if self.finalize_observation is not None:
                obs = self.finalize_observation(obs)
            append_jsonl(self.run_dir / "observations.jsonl", {"round": obs["round"], "actor_id": actor_id, "observation": obs})
            return {"observation": obs}, ""
        if instruction == "submit" and not readonly:
            receipt = self.env.submit(actor_id, ctx["action"])
            self.submitted.add(actor_id)
            append_jsonl(self.run_dir / "actions.jsonl", {"round": self.env.world.round, "actor_id": actor_id,
                         "action": ctx["action"], "receipt": receipt})
            return {"receipt": receipt}, ""
        raise ValueError("Only typed observe and submit are available")

    async def enrich_advice(self, observation):
        if self.decision_mode != "llm" or observation["actor_id"] != 1:
            return observation
        from policy_mve.llm import MODEL, parse_object
        for ticket in observation.get("visible_tickets", []):
            if not ticket.get("a_offered") or ticket.get("lead") is not None or ticket.get("closed"):
                continue
            material = {"ticket": {k: ticket.get(k) for k in ["text", "category", "district", "facility"]},
                        "directory": observation.get("public_rules", {}).get("directory", {})}
            key = digest(material)
            if key not in self.advice_cache:
                messages = [{"role": "system", "content": "你是供水诉求派单辅助工具，只根据工单和职责目录给出建议，不知道实际原因。返回JSON：candidates（整数2或3组成的候选数组）、uncertain（布尔）、basis（简短依据）。允许不确定或错误，不承诺效果；不能输出代码。"},
                            {"role": "user", "content": json.dumps(material, ensure_ascii=False)}]
                for attempt in range(2):
                    result = await self.llm_client.call(MODEL, messages)
                    raw = result.choices[0].message.content
                    append_jsonl(self.run_dir / "advice.jsonl", {"round": observation["round"], "ticket_id": ticket["id"],
                                 "input_sha256": key, "messages": messages, "response": raw, "usage": result.usage, "attempt": attempt})
                    try:
                        advice = parse_object(raw)
                        if not isinstance(advice.get("candidates"), list) or not advice["candidates"] or any(type(x) is not int or x not in {2, 3} for x in advice["candidates"]):
                            raise ValueError("Invalid department suggestions")
                        if type(advice.get("uncertain")) is not bool or not isinstance(advice.get("basis"), str):
                            raise ValueError("Invalid advice fields")
                        self.advice_cache[key] = {"candidates": advice["candidates"], "uncertain": advice["uncertain"],
                                                  "basis": advice["basis"][:600], "provenance": "real_llm_visible_material_only",
                                                  "model": MODEL, "input_sha256": key}
                        break
                    except (ValueError, TypeError):
                        if attempt:
                            raise RuntimeError("Advice schema failed after one repair")
                        messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "仅返回指定JSON字段，请修复格式。"}]
            ticket["recommendation"] = copy.deepcopy(self.advice_cache[key])
            for action in observation["available_actions"]:
                if action["kind"] == "route" and action["target"] == ticket["id"] and action["params"].get("use_recommendation"):
                    action["params"]["department"] = ticket["recommendation"]["candidates"][0]
        return observation

    async def step(self, tick, t):
        if self.submitted != {1, 2, 3, 4}:
            raise RuntimeError(f"Incomplete actor phase: {sorted(self.submitted)}")
        await self.env.step(tick, t)
        self.submitted.clear()
        snapshot = self.env.world.export_state()
        append_jsonl(self.run_dir / "rounds.jsonl", {"round": self.env.world.round,
                     "state_sha256": digest(snapshot), "metrics": self.env.world.metrics()})
        self.last_snapshot = snapshot

    async def to_workspaces(self):
        if self.submitted:
            raise RuntimeError("Cannot checkpoint a partially submitted round")
        await self.env.to_workspace()
        write_json(self.env_path / "router.json", {"advice_cache": self.advice_cache, "round": self.env.world.round})
        write_json(self.run_dir / "world.json", self.env.world.export_state())
        write_json(self.run_dir / "metrics.json", self.env.world.metrics())

    async def from_workspaces(self):
        if not await self.env.restore(self.env_path):
            return False
        data = read_json(self.env_path / "router.json")
        if data["round"] != self.env.world.round:
            raise RuntimeError("Environment/router checkpoint mismatch")
        self.advice_cache = data["advice_cache"]
        self.submitted.clear()
        return True

    async def close(self):
        await self.env.close()

    def owner_snapshot(self):
        """Owner-only Ray method; never exposed by the model observation/tool set."""
        return self.env.world.export_state()

    def owner_metrics(self):
        return self.env.world.metrics()

    def owner_partial(self):
        return {"submitted": sorted(self.submitted), "state": self.env.world.export_state()}
