"""Official AgentBase adapter for the shared business-turn module."""
from agentsociety2.agent.base import AgentBase

from .officer import OfficerRuntime


class PolicyOfficerBase(AgentBase):
    # Concrete registered actors supply their version's decision functions.
    async def restore(self, workspace_path, service_proxy):
        await super().restore(workspace_path, service_proxy)
        self.business = OfficerRuntime(
            self.id, workspace_path, decision_mode=self._config.get("decision_mode"),
            scripted_action=self.scripted_action, choose_action=self.choose_action)

    async def to_workspace(self, workspace_path):
        self.persist_agent_json(tick=None, t=self._current_time)
        self.business.save(workspace_path)

    async def ask(self, message, readonly=True, **kwargs):
        # Research metrics are read by the owner, never inferred from this answer.
        return self.business.describe()

    async def step(self, tick, t):
        self._current_time = t
        result = await self.business.step(self._env, self._dispatcher)
        self._step_count += 1
        return result
