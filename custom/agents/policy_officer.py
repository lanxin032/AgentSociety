"""Registered actor: version-specific decisions on the shared lifecycle."""
from policy_mve.core import scripted_action
from policy_mve.llm import choose_action
from policy_runtime.framework import PolicyOfficerBase


class PolicyOfficer(PolicyOfficerBase):
    scripted_action = staticmethod(scripted_action)
    choose_action = staticmethod(choose_action)

    @classmethod
    def mcp_description(cls):
        return "PolicyOfficer: bounded water-governance decisions with role-filtered observation."
