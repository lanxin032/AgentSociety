"""Official EnvBase wrapper; hidden world state is never a model tool."""
from datetime import timedelta
from pathlib import Path
from agentsociety2.env import EnvBase, tool
from policy_mve.core import PolicyWorld
from policy_mve.io import read_json, write_json


class PolicyCaseEnv(EnvBase):
    def __init__(self, policy="111", seed=0, horizon=30, config=None):
        super().__init__()
        self.world = PolicyWorld(policy, seed, horizon, config)

    @classmethod
    def mcp_description(cls):
        return "PolicyCaseEnv: role-filtered water service cases and audited task transitions."

    @tool(readonly=True, kind="observe")
    def observe(self, actor_id: int) -> dict:
        return self.world.observe(actor_id)

    @tool(readonly=False)
    def submit(self, actor_id: int, action: dict) -> dict:
        return self.world.submit(actor_id, action)

    async def init(self, start_datetime):
        self.t = start_datetime

    async def step(self, tick, t):
        self.world.advance()
        self.t = t + timedelta(seconds=tick)

    async def to_workspace(self, workspace_path=None):
        if workspace_path is not None:
            self._bind_workspace(Path(workspace_path))
        write_json(self._workspace_root / "state" / "ENV_STATE.json", self.world.export_state())

    async def restore(self, workspace_path):
        self._bind_workspace(Path(workspace_path))
        path = self._workspace_root / "state" / "ENV_STATE.json"
        if not path.exists():
            return False
        self.world = PolicyWorld.from_state(read_json(path))
        return True
