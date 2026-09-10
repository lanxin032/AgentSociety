"""Restricted business agent using the installed AgentBase lifecycle."""
from pathlib import Path
import json
from agentsociety2.agent.base import AgentBase
from policy_mve.io import append_jsonl, read_json, write_json
from policy_mve.llm import choose_action


class PolicyOfficer(AgentBase):
    @classmethod
    def mcp_description(cls):
        return "PolicyOfficer: bounded water-governance decisions with role-filtered observation."

    async def restore(self, workspace_path, service_proxy):
        await super().restore(workspace_path, service_proxy)
        self._business_path = Path(workspace_path)
        path = self._business_path / "state" / "business.json"
        self.business_history = read_json(path).get("history", []) if path.exists() else []

    async def to_workspace(self, workspace_path):
        self.persist_agent_json(tick=None, t=self._current_time)
        write_json(Path(workspace_path) / "state" / "business.json", {"history": self.business_history[-3:]})

    async def ask(self, message, readonly=True, **kwargs):
        # Research metrics are read directly by the owner, never inferred from this answer.
        return json.dumps({"actor_id": self.id, "recent_actions": self.business_history[-3:]}, ensure_ascii=False)

    async def step(self, tick, t):
        self._current_time = t
        result, _ = await self._env.ask({"actor_id": self.id}, "observe", readonly=True)
        observation = result["observation"]
        choices = observation["available_actions"]
        trace = self._business_path / "decisions.jsonl"
        if self._config.get("decision_mode") == "scripted":
            from policy_mve.core import scripted_action
            action = scripted_action(observation)
        elif not any(item["kind"] != "wait" for item in choices):
            action = {"kind": "wait", "target": None, "params": {}, "reason": "无可执行任务"}
            append_jsonl(trace, {"round": observation["round"], "actor_id": self.id, "idle": True})
        else:
            action = await choose_action(self._dispatcher, observation, self.business_history, trace)
        result, _ = await self._env.ask({"actor_id": self.id, "action": action}, "submit", readonly=False)
        receipt = result["receipt"]
        if receipt.get("status") not in {"queued", "duplicate", "rejected", "business_rejected"}:
            raise RuntimeError("Missing structured action receipt")
        self.business_history.append({"round": observation["round"], "action": action, "receipt": receipt})
        self._step_count += 1
        return json.dumps({"actor_id": self.id, "round": observation["round"], "action": action, "receipt": receipt}, ensure_ascii=False)
