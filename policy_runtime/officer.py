"""A complete business turn, independent of framework imports and scheduling."""
import json
from pathlib import Path

from policy_mve.io import append_jsonl, read_json, write_json


class OfficerRuntime:
    """Own decision ordering and the persisted, bounded business history.

    The environment is the official typed proxy in production. Tests use the
    same observe/submit protocol with an in-process environment. Version-specific
    decision functions retain their prompts, validation and repair allowances.
    """

    def __init__(self, actor_id, workspace, *, decision_mode, scripted_action, choose_action):
        self.actor_id = actor_id
        self.workspace = Path(workspace)
        self.decision_mode = decision_mode
        self.scripted_action = scripted_action
        self.choose_action = choose_action
        path = self.workspace / "state" / "business.json"
        self.history = read_json(path).get("history", []) if path.exists() else []

    def save(self, workspace):
        write_json(Path(workspace) / "state" / "business.json", {"history": self.history[-3:]})

    def describe(self):
        return json.dumps({"actor_id": self.actor_id, "recent_actions": self.history[-3:]}, ensure_ascii=False)

    async def step(self, environment, client):
        result, _ = await environment.ask({"actor_id": self.actor_id}, "observe", readonly=True)
        observation = result["observation"]
        trace = self.workspace / "decisions.jsonl"
        if self.decision_mode == "scripted":
            action = self.scripted_action(observation)
        elif not any(item["kind"] != "wait" for item in observation["available_actions"]):
            action = {"kind": "wait", "target": None, "params": {}, "reason": "无可执行任务"}
            append_jsonl(trace, {"round": observation["round"], "actor_id": self.actor_id, "idle": True})
        else:
            action = await self.choose_action(client, observation, self.history, trace)
        result, _ = await environment.ask({"actor_id": self.actor_id, "action": action}, "submit", readonly=False)
        receipt = result["receipt"]
        if receipt.get("status") not in {"queued", "duplicate", "rejected", "business_rejected"}:
            raise RuntimeError("Missing structured action receipt")
        self.history.append({"round": observation["round"], "action": action, "receipt": receipt})
        return json.dumps({"actor_id": self.actor_id, "round": observation["round"],
                           "action": action, "receipt": receipt}, ensure_ascii=False)
