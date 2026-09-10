"""Frozen pre-refactor observations, receipts and complete state trajectories.

The fixture was captured before extracting the lifecycle, not regenerated from
its implementation. Hashes include event order and serialized field names.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from policy_v3.core import PolicyWorld
from tests import test_v3_physical as physical_contracts
from tests import test_v3_c_invariants as c_invariants


FIXTURE = Path(__file__).with_name("data") / "project_lifecycle_v3_1.json"
CASES = {
    "physical": (physical_contracts.PhysicalContracts, (
        "test_built_no_commission", "test_commission_not_reported", "test_late_admin",
        "test_wrong_plan", "test_cancel_before", "test_cancel_after",
        "test_same_physics_both_modes", "test_stock_vs_recurrence", "test_invalid_combination",
        "test_boundary", "test_already_repaired_accept",
        "test_zero_and_activated_sharing_can_lawfully_inform_owner",
        "test_hidden_matching_never_filters_project_observations")),
    "invariants": (c_invariants.CInvariants, (
        "test_wrong_shared_plan_spends_resources_but_fails_in_both_channels",
        "test_unsupported_topic_can_cancel_without_refund_or_success",
        "test_matched_project_succeeds_while_every_stage_is_b_invariant")),
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def capture_case(case_class, method):
    checksum, counts = hashlib.sha256(), Counter()
    observe, submit, advance = PolicyWorld.observe, PolicyWorld.submit, PolicyWorld.advance

    def record(kind, value):
        counts[kind] += 1
        checksum.update(canonical([kind, value]) + b"\n")

    def observed(world, actor):
        result = observe(world, actor)
        record("observe", {"actor": actor, "observation": result})
        return result

    def submitted(world, actor, action):
        result = submit(world, actor, action)
        record("submit", {"actor": actor, "action": action, "receipt": result})
        return result

    def advanced(world):
        result = advance(world)
        state = world.export_state()
        record("advance", {"state": state, "metrics": world.metrics(),
                           "observations": [observe(world, actor) for actor in (1, 2, 3, 4)]})
        return result

    result = unittest.TestResult()
    with patch.object(PolicyWorld, "observe", observed), patch.object(PolicyWorld, "submit", submitted), patch.object(PolicyWorld, "advance", advanced):
        case_class(method).run(result)
    if not result.wasSuccessful():
        raise AssertionError(result.errors + result.failures)
    return {"sha256": checksum.hexdigest(), "calls": dict(counts)}


def resume_path(mode, restore):
    helper = physical_contracts.PhysicalContracts()
    world, pid, automatic = helper.build(mode)
    if restore:
        world = PolicyWorld.from_state(world.export_state())
    helper.commission(world, pid)
    if restore:
        world = PolicyWorld.from_state(world.export_state())
    if not automatic:
        helper.act(world, 2, "report_status", pid, recipient=4)
    helper.act(world, 4, "accept_project", pid)
    return {"state": world.export_state(), "metrics": world.metrics(),
            "observations": [world.observe(actor) for actor in (1, 2, 3, 4)]}


class LifecycleCompatibilityTests(unittest.TestCase):
    def test_complete_trajectories_match_pre_refactor_behavior(self):
        baseline = json.loads(FIXTURE.read_text())
        for group, (case_class, methods) in CASES.items():
            for method in methods:
                key = group + "." + method
                with self.subTest(case=key):
                    self.assertEqual(capture_case(case_class, method), baseline["trajectories"][key])

    def test_built_and_commissioned_checkpoints_resume_exactly(self):
        baseline = json.loads(FIXTURE.read_text())
        for mode in ("conventional", "structured"):
            with self.subTest(mode=mode):
                uninterrupted = resume_path(mode, restore=False)
                restored = resume_path(mode, restore=True)
                self.assertEqual(restored, uninterrupted)
                self.assertEqual(hashlib.sha256(canonical(restored)).hexdigest(), baseline["resume_results"][mode])
