"""Reuse the audited official-proxy adapter, select only the V3 environment."""
from pathlib import Path
from agentsociety2.registry import get_env_module_class
from policy_mve.router import PolicyRouterActor
from .interface import decorate_observation


class PolicyV3RouterActor(PolicyRouterActor):
    async def enrich_advice(self, observation):
        # Public advice and removal of the legacy label change the ID context.
        return decorate_observation(await super().enrich_advice(observation))

    def __init__(self, run_dir, policy, seed, horizon, decision_mode, llm_client,
                 config=None, scenario=None):
        self.run_dir = Path(run_dir)
        self.env_path = self.run_dir / "env" / "PolicyV3Env"
        self.env = get_env_module_class("PolicyV3Env")(
            policy=policy, seed=seed, horizon=horizon, config=config, scenario=scenario)
        self.env._bind_workspace(self.env_path)
        self.decision_mode = decision_mode
        self.llm_client = llm_client
        self.submitted = set()
        self.advice_cache = {}
        self.replay = None
        self.last_snapshot = None
