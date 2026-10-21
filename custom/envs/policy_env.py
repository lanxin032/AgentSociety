"""Official custom-module registration entry."""
from policy_sim.router import PolicyEnv as _PolicyEnv


class PolicyEnv(_PolicyEnv):
    pass
