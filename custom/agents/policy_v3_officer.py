"""Official AgentBase lifecycle; only typed, role-filtered V3 business actions."""
import json
from custom.agents.policy_officer import PolicyOfficer
from policy_mve.io import append_jsonl
from policy_v3.llm import choose_action


class PolicyV3Officer(PolicyOfficer):
    @classmethod
    def mcp_description(cls):
        return "PolicyV3Officer: bounded department decisions and project review/execution."

    async def step(self, tick, t):
        self._current_time = t
        result, _ = await self._env.ask({"actor_id": self.id}, "observe", readonly=True)
        observation = result["observation"]
        trace = self._business_path / "decisions.jsonl"
        if self._config.get("decision_mode") == "scripted":
            from policy_v3.scripted import scripted_action
            action = scripted_action(observation)
        elif not any(a["kind"] != "wait" for a in observation["available_actions"]):
            action = {"kind": "wait", "target": None, "params": {}, "reason": "无可执行任务"}
            append_jsonl(trace, {"round": observation["round"], "actor_id": self.id, "idle": True})
        else:
            action = await choose_action(self._dispatcher, observation, self.business_history, trace)
        result, _ = await self._env.ask({"actor_id": self.id, "action": action}, "submit", readonly=False)
        receipt = result["receipt"]
        if receipt.get("status") not in {"queued", "duplicate", "rejected", "business_rejected"}:
            raise RuntimeError("V3 action has no structured submission receipt")
        self.business_history.append({"round": observation["round"], "action": action, "receipt": receipt})
        self._step_count += 1
        return json.dumps({"actor_id": self.id, "round": observation["round"],
                           "action": action, "receipt": receipt}, ensure_ascii=False)
