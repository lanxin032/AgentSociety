"""Isolated text-contract corrections for the installed PersonAgent 2.8.7.

The official formatter still owns all messages and recent-observation windows.
Only these contradictory clauses change; unexpected upstream text fails closed.
"""
from copy import deepcopy

PROMPT_CORRECTIONS = (
    ("(use an empty list only when nothing notable happened).",
     "(always provide 1 to 8 memories; for an uneventful step record one brief observation)."),
    ("   - execute_skill_script: run a skill's Python script.",
     "   - Policy role skills provide guidance only; skill scripts are unavailable."),
    ('- Do not use ask_env to "wait", "wait 30 minutes", or create waiting/status events; simulation time advances automatically between steps. To continue an ongoing activity, finish the step or query the current event.',
     '- Simulation time advances between steps. In this policy task, wait is a valid business candidate: explicitly submit its candidate_id through ask_env. Do not request an artificial time delay.'),
)


def adapt_official_messages(messages):
    result = deepcopy(messages)
    text = result[0]["content"]
    for old, new in PROMPT_CORRECTIONS:
        if text.count(old) != 1:
            raise RuntimeError("Installed PersonAgent prompt differs from the 2.8.7 contract")
        text = text.replace(old, new)
    result[0]["content"] = text
    return result
