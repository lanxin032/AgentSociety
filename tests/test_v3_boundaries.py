"""Deterministic mechanism boundaries, without files, model calls or framework."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_v3.core import PolicyWorld


def world_with_switch(end, environment="baseline"):
    return PolicyWorld(seed=7, scenario={"horizon": 60, "q": {"A": 0, "B": 0, "C": 0},
        "schedule": [{"start": 0, "end": end, "q": {"A": 1, "B": 1, "C": 1}}],
        "environment": environment})


def act(world, actor, kind, target=None, **params):
    candidates = [a for a in world.observe(actor)["available_actions"]
                  if a["kind"] == kind and (target is None or a["target"] == target)
                  and all(a["params"].get(k) == v for k, v in params.items())]
    if not candidates:
        raise AssertionError(f"No visible {kind} candidate for actor {actor} at round {world.round}")
    action = candidates[0]
    receipt = world.submit(actor, action)
    if receipt["status"] != "queued":
        raise AssertionError(receipt)
    before = len(world.events)
    world.advance()
    result = next(e for e in world.events[before:] if e["kind"] == "action_result" and e["actor_id"] == actor)
    if result["status"] != "executed":
        raise AssertionError(result)
    return action, result


def dependent_ticket(world):
    # Privileged fixture selection only; every tested action uses observe().
    facility = next(f for f in world.facilities.values() if f["dependent"])
    return next(t["id"] for t in world.tickets.values() if t["facility"] == facility["id"])


def start_project(world, mode):
    # Select a physically matched fixture to isolate flow/cost from plan mistakes.
    topics = world.observe(4)["topics"]
    topic = next(t for t in topics if all(world.facilities[f]["shared_root"] for f in t["facilities"]))
    act(world, 4, "propose_project", topic["id"], mode=mode)
    return next(iter(world.projects))


def finish_project(world, pid, structured):
    act(world, 4, "confirm_project_lead", pid)
    act(world, 4, "diagnose_project", pid)
    act(world, 4, "draft_plan", pid)
    if structured:
        act(world, 2, "confirm_project_task", pid)
        act(world, 3, "confirm_project_task", pid)
    act(world, 2, "review_project", opinion="approve")
    act(world, 3, "review_project", opinion="approve")
    act(world, 4, "request_budget", pid)
    act(world, 3, "implement_project")
    act(world, 2, "implement_project")
    ready = world.projects[pid]["physical_ready_round"]
    while world.round < ready:
        world.advance()
    act(world, 2, "commission_project")
    # These fixtures use active structured sharing or zero-friction ordinary
    # sharing, so the real commission receipt arrives through that channel.
    received = world.observe(4)["projects"]
    assert any(r["kind"] == "commissioning_result" and r["data"]["success"]
               for p in received if p["id"] == pid for r in p["received_records"])
    act(world, 4, "accept_project", pid)


class V3BoundaryTests(unittest.TestCase):
    def test_adopted_b_continues_confirmation_and_work_after_q_off(self):
        world = world_with_switch(3)
        tid = dependent_ticket(world)
        act(world, 1, "route", tid, department=2, use_recommendation=False)
        act(world, 2, "inspect", tid)
        act(world, 2, "request_coordination", tid, mode="joint")
        self.assertEqual(world._q("B"), 0)
        oid = world.tickets[tid]["b_opportunity"]
        self.assertTrue(world.opportunities[oid]["adopted"])
        act(world, 2, "confirm_joint_task", tid)
        act(world, 3, "confirm_joint_task", tid)
        act(world, 3, "work")
        act(world, 2, "work")
        self.assertTrue(world.tickets[tid]["closed"])
        self.assertEqual(world.tickets[tid]["joint_confirmed_by"], [2, 3])

    def test_adopted_c_completes_project_after_q_off(self):
        world = world_with_switch(1)
        pid = start_project(world, "structured")
        self.assertEqual(world._q("C"), 0)
        self.assertTrue(world.opportunities[world.projects[pid]["opportunity"]]["adopted"])
        finish_project(world, pid, structured=True)
        self.assertEqual(world.projects[pid]["state"], "completed")

    def test_pending_opportunity_keeps_same_draw_across_off_on_switches(self):
        world = PolicyWorld(seed=7, scenario={"horizon": 10, "q": {"A": 0, "B": 0, "C": 0},
            "schedule": [{"start": 1, "end": 2, "q": {"A": 1, "B": 1, "C": 1}},
                         {"start": 3, "end": 4, "q": {"A": 1, "B": 1, "C": 1}}]})
        oid = next(oid for oid, row in world.opportunities.items() if row["tool"] == "A")
        original = deepcopy(world.opportunities[oid])
        self.assertFalse(world._offered(oid))
        for expected in (True, False, True):
            world.advance()
            self.assertEqual(world._offered(oid), expected)
            self.assertEqual(world.opportunities[oid]["u"], original["u"])
            self.assertEqual(world.opportunities[oid]["created"], original["created"])
        self.assertEqual(sum(e["kind"] == "tool_opportunity" and e.get("opportunity") == oid for e in world.events), 1)

    def test_paired_policies_share_initial_physics_and_exogenous_draws(self):
        ordinary, enhanced = PolicyWorld(policy="000", seed=17), PolicyWorld(policy="111", seed=17)
        self.assertEqual(ordinary.facilities, enhanced.facilities)
        self.assertEqual(ordinary.issues, enhanced.issues)
        for _ in range(5):
            ordinary.advance()
            enhanced.advance()
        keys = lambda w: {(e["facility"], e["round"]): e["draw"] for e in w.events if e["kind"] == "external_shock"}
        self.assertEqual(len(keys(ordinary)), 60)
        self.assertEqual(keys(ordinary), keys(enhanced))

    def test_zero_friction_case_handoff_preserves_real_work_costs(self):
        world = PolicyWorld(policy="000", seed=7, config={"zero_communication_friction": True})
        tid = dependent_ticket(world)
        act(world, 1, "route", tid, department=2, use_recommendation=False)
        act(world, 2, "inspect", tid)
        act(world, 3, "work")
        act(world, 2, "work")
        self.assertTrue(world.tickets[tid]["closed"])
        work = [e for e in world.events if e["kind"] == "resource_spent" and e.get("reason") == "work"]
        self.assertEqual(len(work), 2)
        self.assertAlmostEqual(sum(e["labor"] for e in work), 2 * world.config["work_cost"])
        self.assertAlmostEqual(sum(e["capital"] for e in work), 2 * world.config["case_work_capital"])
        self.assertEqual(sum(e["crew"] for e in work), 2)

    def test_zero_friction_conventional_project_keeps_construction_costs(self):
        world = PolicyWorld(policy="000", seed=7, config={"zero_communication_friction": True})
        pid = start_project(world, "conventional")
        finish_project(world, pid, structured=False)
        self.assertEqual(world.projects[pid]["state"], "completed")
        work = [e for e in world.events if e["kind"] == "resource_spent" and e.get("reason") == "implement_project"]
        self.assertEqual(len(work), 2)
        self.assertAlmostEqual(sum(e["labor"] for e in work), 2 * world.config["project_work_cost"])
        self.assertAlmostEqual(sum(e["capital"] for e in work), 2 * world.config["project_step_capital"])
        self.assertEqual(sum(e["crew"] for e in work), 2)
        commission = [e for e in world.events if e["kind"] == "resource_spent" and e.get("reason") == "commission_project"]
        self.assertEqual(len(commission), 1)
        self.assertEqual(commission[0]["actor_id"], 2)
        self.assertAlmostEqual(commission[0]["labor"], world.config["project_commission_cost"])
        self.assertEqual((commission[0]["capital"], commission[0]["crew"]), (0, 0))
        self.assertEqual(world.projects[pid]["physical"], "effective")


if __name__ == "__main__":
    unittest.main()
