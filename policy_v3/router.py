"""V3 environment and observation adapter for the shared typed router."""
from agentsociety2.registry import get_env_module_class
from policy_runtime.router import PolicyRouter
from .interface import decorate_observation


class PolicyV3RouterActor(PolicyRouter):
    def __init__(self, run_dir, policy, seed, horizon, decision_mode, llm_client,
                 config=None, scenario=None):
        env = get_env_module_class("PolicyV3Env")(
            policy=policy, seed=seed, horizon=horizon, config=config, scenario=scenario)
        super().__init__(env, run_dir, "PolicyV3Env", decision_mode, llm_client,
                         finalize_observation=decorate_observation)
