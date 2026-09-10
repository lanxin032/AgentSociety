"""MVE environment adapter for the shared typed router."""
from agentsociety2.registry import get_env_module_class
from policy_runtime.router import PolicyRouter


class PolicyRouterActor(PolicyRouter):
    def __init__(self, run_dir, policy, seed, horizon, decision_mode, llm_client, config=None):
        env = get_env_module_class("PolicyCaseEnv")(
            policy=policy, seed=seed, horizon=horizon, config=config)
        super().__init__(env, run_dir, "PolicyCaseEnv", decision_mode, llm_client)
