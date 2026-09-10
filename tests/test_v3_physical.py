"""Executable physical/knowledge contracts for V3.1, without model or API calls.

All positive paths obtain assignment and evidence through real actions/messages.
Privileged fixture selection chooses a topic archetype only; it is never injected
into role observations. Snapshot perturbations below are explicit negative tests.
"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_v3.core import PolicyWorld
from policy_v3.spec import SPEC_VERSION


class PhysicalContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert Path(sys.modules[PolicyWorld.__module__].__file__).resolve() == ROOT / "policy_v3" / "core.py"
        assert SPEC_VERSION == "policy-v3-3.1"

    def candidate(self, world, actor, kind, target=None, **params):
        choices = [a for a in world.observe(actor)["available_actions"]
                   if a["kind"] == kind and (target is None or a["target"] == target)
                   and all(a["params"].get(k) == v for k, v in params.items())]
        self.assertTrue(choices, (world.round, actor, kind, target, params))
        return choices[0]

    def settle(self, world, actions, expected=None):
        start = len(world.events)
        for actor, action in actions.items():
            self.assertEqual(world.submit(actor, action)["status"], "queued")
        world.advance()
        results = {e["actor_id"]: e for e in world.events[start:] if e["kind"] == "action_result"}
        for actor in actions:
            status = (expected or {}).get(actor, "executed")
            self.assertEqual(results[actor]["status"], status, results[actor])
        return results

    def act(self, world, actor, kind, target=None, expect="executed", **params):
        return self.settle(world, {actor: self.candidate(world, actor, kind, target, **params)}, {actor: expect})[actor]

    def view(self, world, actor, pid):
        return next(p for p in world.observe(actor)["projects"] if p["id"] == pid)

    def prepare(self, mode="conventional", shared=True, *, zero=False, activate=True, single=False):
        world = PolicyWorld("001", seed=0, horizon=90, config={"zero_communication_friction": zero})
        # Audit-only fixture selection. No received records are fabricated.
        topic = next(t for t in world.observe(4)["topics"]
                     if all(world.facilities[f]["shared_root"] == shared for f in t["facilities"])
                     and (not single or all(len(world.facilities[f]["case_actors"]) == 1 for f in t["facilities"])))
        self.act(world, 4, "propose_project", topic["id"], mode=mode)
        pid = next(iter(world.projects))
        self.act(world, 4, "confirm_project_lead", pid)
        self.act(world, 4, "diagnose_project", pid)
        self.act(world, 4, "draft_plan", pid)
        automatic = zero or (mode == "structured" and activate)
        if mode == "structured" and activate:
            self.settle(world, {a: self.candidate(world, a, "confirm_project_task", pid) for a in (2, 3)})
        for actor in (2, 3):
            if mode == "conventional" and not zero:
                self.act(world, 4, "request_review", pid, department=actor)
            self.act(world, actor, "review_project", opinion="approve")
            if not automatic:
                self.act(world, actor, "report_status", pid, recipient=4)
        self.act(world, 4, "request_budget", pid)
        if mode == "conventional" and not zero:
            for actor in (2, 3):
                self.act(world, 4, "request_project_work", pid, department=actor)
        return world, pid, automatic

    def build(self, mode="conventional", shared=True, *, zero=False, activate=True, single=False,
              last_round=None, report_owner=True):
        world, pid, automatic = self.prepare(mode, shared, zero=zero, activate=activate, single=single)
        self.act(world, 3, "implement_project")
        if not automatic:
            self.act(world, 3, "report_status", pid, recipient=2)
            if report_owner:
                self.act(world, 3, "report_status", pid, recipient=4)
        if last_round is not None:
            self.assertLessEqual(world.round, last_round)
            while world.round < last_round:
                self.act(world, 4, "wait")
        self.act(world, 2, "implement_project")
        self.assertEqual(world.projects[pid]["construction"], "built")
        if not automatic and report_owner:
            self.act(world, 2, "report_status", pid, recipient=4)
        return world, pid, automatic

    def ready(self, world, pid):
        # Readiness is calculated only from role2's lawfully held receipts.
        tasks = [t for t in self.view(world, 2, pid)["tasks"] if t["kind"] == "implement_project"]
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(t["state"] == "completed" for t in tasks))
        ready = max(t["completed_round"] for t in tasks) + world.observe(2)["public_rules"]["project_lag"]
        while world.round < ready:
            self.act(world, 4, "wait")

    def commission(self, world, pid, expect="executed"):
        self.ready(world, pid)
        return self.act(world, 2, "commission_project", expect=expect)

    def test_built_no_commission(self):
        world, pid, _ = self.build("structured", last_round=12)
        while world.round < 14:
            self.act(world, 4, "wait")
        self.act(world, 4, "wait")
        self.assertEqual(world.projects[pid]["built_at"], 12)
        self.assertEqual(world.projects[pid]["physical"], "not_commissioned")
        self.assertEqual(world.projects[pid]["administrative"], "open")
        self.assertTrue(all(not world.facilities[f]["root_repaired"] for f in world.projects[pid]["facilities"]))
        for actor in (2, 3, 4):
            self.assertNotEqual(self.view(world, actor, pid)["physical"], "effective")

    def test_commission_not_reported(self):
        world, pid, _ = self.build()
        before = deepcopy(self.view(world, 4, pid))
        self.commission(world, pid)
        self.assertEqual(world.projects[pid]["physical"], "effective")
        self.assertEqual(world.projects[pid]["administrative"], "open")
        self.assertEqual(self.view(world, 4, pid), before)
        self.assertEqual(self.view(world, 2, pid)["physical"], "effective")

    def test_late_admin(self):
        world, pid, _ = self.build()
        self.commission(world, pid)
        effective_at = world.projects[pid]["effective_at"]
        denied = self.act(world, 4, "accept_project", pid, expect="business_rejected")
        self.assertEqual(denied["code"], "commissioning_success_receipt_not_received")
        self.assertEqual(world.projects[pid]["physical"], "effective")
        self.act(world, 2, "report_status", pid, recipient=4)
        before = world.labor["4"]
        self.act(world, 4, "accept_project", pid)
        self.assertAlmostEqual(before - world.labor["4"], 0.1)
        self.assertEqual(world.projects[pid]["administrative"], "accepted")
        self.assertEqual(world.projects[pid]["effective_at"], effective_at)

    def test_wrong_plan(self):
        for mode in ("conventional", "structured"):
            with self.subTest(mode=mode):
                world, pid, _ = self.build(mode, shared=False)
                self.ready(world, pid)
                labor, capital = world.labor["2"], world.capital
                result = self.act(world, 2, "commission_project", expect="business_rejected")
                self.assertEqual(result["code"], "physical_intervention_not_matched")
                self.assertAlmostEqual(labor - world.labor["2"], 0.6)
                self.assertEqual(world.capital, capital)
                self.assertEqual(world.projects[pid]["capital_spent"], 6)
                self.assertEqual(world.projects[pid]["physical"], "commissioning_failed")
                self.assertNotEqual(world.projects[pid]["administrative"], "accepted")
                self.assertTrue(all(not f["root_repaired"] for f in world.facilities.values()))

    def test_cancel_before(self):
        world, pid, _ = self.build(shared=False)
        self.ready(world, pid)
        before = deepcopy(self.view(world, 2, pid))
        capital = world.capital
        self.act(world, 4, "cancel_project", pid, reason_code="evidence_does_not_support")
        self.assertEqual(self.view(world, 2, pid), before)
        labor = world.labor["2"]
        self.act(world, 2, "commission_project", expect="business_rejected")
        self.assertAlmostEqual(labor - world.labor["2"], 0.1)
        self.assertEqual(world.projects[pid]["physical"], "not_commissioned")
        self.assertEqual(world.projects[pid]["construction"], "built")
        self.assertEqual(world.capital, capital)
        self.assertEqual(world.projects[pid]["capital_spent"], 6)

    def test_cancel_after(self):
        # Unconfirmed structured flow retains ordinary reports. Department3 can
        # lawfully state an objection; owner receives it before relying on it.
        world, pid, _ = self.build("structured", activate=False)
        self.commission(world, pid)
        effective_at, built_at = world.projects[pid]["effective_at"], world.projects[pid]["built_at"]
        self.act(world, 3, "raise_objection", pid, reason_code="scope_or_capacity_concern")
        self.act(world, 3, "report_status", pid, recipient=4)
        capital = world.capital
        self.act(world, 4, "cancel_project", pid, reason_code="budget_or_capacity_infeasible")
        self.assertEqual(world.projects[pid]["administrative"], "cancelled")
        self.assertEqual(world.projects[pid]["physical"], "effective")
        self.assertEqual(world.projects[pid]["effective_at"], effective_at)
        self.assertEqual(world.projects[pid]["built_at"], built_at)
        self.assertEqual(world.capital, capital)
        self.assertTrue(all(world.facilities[f]["root_repaired"] for f in world.projects[pid]["facilities"]))

    def test_same_physics_both_modes(self):
        world, pid, _ = self.build()
        self.ready(world, pid)
        copies = [PolicyWorld.from_state(world.export_state()) for _ in range(2)]
        # Explicit matched-state fixture: only mode changes. All assignment,
        # receipts, physical state, available resources and round are identical.
        for copy, mode in zip(copies, ("conventional", "structured")):
            copy.projects[pid]["mode"] = mode
            self.act(copy, 2, "commission_project")
        for key in ("physical", "effective_at", "commissioned_at", "capital_spent"):
            self.assertEqual(copies[0].projects[pid][key], copies[1].projects[pid][key])
        self.assertEqual(copies[0].labor, copies[1].labor)
        self.assertEqual(copies[0].capital, copies[1].capital)
        shocks = [[e for e in c.events if e["kind"] == "external_shock" and e["round"] == c.round] for c in copies]
        self.assertEqual(shocks[0], shocks[1])

    def test_stock_vs_recurrence(self):
        world, pid, _ = self.build(single=True)
        initial_ids = set(world.issues)
        self.commission(world, pid)
        self.assertEqual(set(world.issues), initial_ids)
        self.assertTrue(all(i["resolved"] is None for i in world.issues.values()))
        fid = world.projects[pid]["facilities"][0]
        ticket = next(t for t in world.observe(1)["visible_tickets"] if t["facility"] == fid)
        actor = world.facilities[fid]["case_actors"][0]  # fixture chooses known single-role prototype
        self.act(world, 1, "route", ticket["id"], department=actor, use_recommendation=False)
        self.act(world, actor, "inspect", ticket["id"])
        self.act(world, actor, "work")
        issue = world.issues[world.tickets[ticket["id"]]["issue"]]
        self.assertIsNotNone(issue["resolved"])
        shock = next(e for e in reversed(world.events) if e["kind"] == "external_shock" and e["facility"] == fid)
        self.assertTrue(shock["at_risk"])
        self.assertEqual(shock["probability"], world.config["repaired_root_shock_probability"])
        self.assertLessEqual(sum(i["facility"] == fid and i["resolved"] is None for i in world.issues.values()), 1)
        self.assertEqual(world.projects[pid]["administrative"], "open")

    def test_invalid_combination(self):
        world, pid, _ = self.prepare()
        self.act(world, 3, "implement_project")
        self.assertEqual(world.projects[pid]["construction"], "in_progress")
        self.act(world, 2, "commission_project", expect="business_rejected")
        self.act(world, 4, "accept_project", pid, expect="business_rejected")
        self.assertEqual(world.projects[pid]["physical"], "not_commissioned")
        self.assertNotEqual(world.projects[pid]["administrative"], "accepted")

    def test_boundary(self):
        world, pid, _ = self.build("structured", last_round=12)
        self.assertEqual(world.round, 13)
        old_shocks = deepcopy([e for e in world.events if e["kind"] == "external_shock"])
        denied = self.act(world, 2, "commission_project", expect="business_rejected")
        self.assertEqual(denied["code"], "commissioning_readiness_lag_not_elapsed")
        self.assertEqual(world.round, 14)
        self.act(world, 2, "commission_project")
        self.assertEqual(world.round, 15)
        self.assertEqual(world.projects[pid]["effective_at"], 15)
        self.assertEqual(world.projects[pid]["physical"], "effective")
        self.assertEqual([e for e in world.events if e["kind"] == "external_shock"][:len(old_shocks)], old_shocks)
        events = world.events
        activated = next(i for i, e in enumerate(events) if e["kind"] == "physical_effect_activated" and e["project"] == pid)
        next_shock = next(i for i, e in enumerate(events) if e["kind"] == "external_shock" and e["round"] == 15)
        self.assertLess(activated, next_shock)

    def test_already_repaired_accept(self):
        world, pid, _ = self.build()
        self.commission(world, pid)
        self.assertTrue(all(world.facilities[f]["root_repaired"] for f in world.projects[pid]["facilities"]))
        self.act(world, 2, "report_status", pid, recipient=4)
        self.act(world, 4, "accept_project", pid)
        self.assertEqual(world.projects[pid]["administrative"], "accepted")
        self.assertEqual(world.projects[pid]["physical"], "effective")

    def test_zero_and_activated_sharing_can_lawfully_inform_owner(self):
        for mode, zero in (("conventional", True), ("structured", False)):
            with self.subTest(mode=mode, zero=zero):
                world, pid, _ = self.build(mode, zero=zero)
                self.commission(world, pid)
                self.assertEqual(self.view(world, 4, pid)["physical"], "effective")
                self.assertTrue(any(r["kind"] == "commissioning_result" for r in self.view(world, 4, pid)["received_records"]))

    def test_hidden_matching_never_filters_project_observations(self):
        world, pid, _ = self.build()
        self.ready(world, pid)
        alternative = PolicyWorld.from_state(world.export_state())
        # Counterfactual audit-state perturbation only, not a claimed legal run.
        # Already-delivered historical material remains byte-for-byte identical.
        for fid in alternative.projects[pid]["facilities"]:
            alternative.facilities[fid]["shared_root"] = False
            alternative.facilities[fid]["root"] = "counterfactual-" + fid
        for actor in (1, 2, 3, 4):
            self.assertEqual(world.observe(actor), alternative.observe(actor))


if __name__ == "__main__":
    unittest.main(verbosity=2)
