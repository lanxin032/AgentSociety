"""Registered actor: version-specific decisions on the shared lifecycle."""
from policy_v3.scripted import scripted_action
from policy_v3.llm import choose_action
from policy_runtime.framework import PolicyOfficerBase


class PolicyV3Officer(PolicyOfficerBase):
    scripted_action = staticmethod(scripted_action)
    choose_action = staticmethod(choose_action)

    @classmethod
    def mcp_description(cls):
        return "PolicyV3Officer: bounded department decisions and project review/execution."
