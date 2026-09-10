"""Final C boundary checks: lawful actions only, no model or cloud calls."""
from copy import deepcopy
import unittest

from policy_v3.core import PolicyWorld


class CInvariants(unittest.TestCase):
    def act(self, world, actor, kind, target=None, expect="executed", **params):
        choices = [a for a in world.observe(actor)["available_actions"]
                   if a["kind"] == kind and (target is None or a["target"] == target)
                   and all(a["params"].get(k) == v for k, v in params.items())]
        self.assertTrue(choices, (world.round, actor, kind, target))
        self.assertEqual(world.submit(actor, choices[0])["status"], "queued")
        start = len(world.events)
        world.advance()
        result = next(e for e in world.events[start:] if e["kind"] == "action_result"
                      and e["actor_id"] == actor)
        self.assertEqual(result["status"], expect, result)
        self.check_b_invariance(world)
        return result

    def check_b_invariance(self, world):
        """Change only B offering intensity, retaining every physical/known state."""
        copies = [PolicyWorld.from_state(world.export_state()) for _ in range(2)]
        copies[0].scenario["q"]["B"] = 0
        copies[1].scenario["q"]["B"] = 1
        for clone, label in zip(copies, ("001", "011")):
            clone.policy = label
        for actor in (2, 3, 4):
            projections = []
            for clone in copies:
                obs = clone.observe(actor)
                project_ids = set(clone.projects)
                topic_ids = {p["topic"] for p in clone.projects.values()}
                task_ids = {t["id"] for t in clone.tasks.values() if t["object"] in project_ids}
                message_ids = {m["id"] for m in clone.messages.values() if m["object"] in project_ids}
                targets = project_ids | topic_ids | task_ids | message_ids
                projections.append({
                    "projects": obs["projects"],
                    "actions": [a for a in obs["available_actions"] if a["target"] in targets],
                    "inbox": [m for m in obs["inbox"] if m["object"] in project_ids],
                    "public_rules": obs["public_rules"],
                })
            self.assertEqual(projections[0], projections[1], (world.round, actor))

    def prepare(self, mode, shared):
        world = PolicyWorld("001", seed=0, horizon=60)
        # Privileged fixture selection isolates match/failure; model-facing
        # decisions below always come from the lawful candidate list.
        topic = next(t for t in world.observe(4)["topics"]
                     if all(world.facilities[f]["shared_root"] == shared for f in t["facilities"]))
        self.act(world, 4, "propose_project", topic["id"], mode=mode)
        pid = next(iter(world.projects))
        self.act(world, 4, "confirm_project_lead", pid)
        self.act(world, 4, "diagnose_project", pid)
        return world, pid

    def construct(self, world, pid, mode):
        self.act(world, 4, "draft_plan", pid)
        if mode == "structured":
            for actor in (2, 3):
                self.act(world, actor, "confirm_project_task", pid)
        for actor in (2, 3):
            if mode == "conventional":
                self.act(world, 4, "request_review", pid, department=actor)
            self.act(world, actor, "review_project", opinion="approve")
            if mode == "conventional":
                self.act(world, actor, "report_status", pid, recipient=4)
        self.act(world, 4, "request_budget", pid)
        if mode == "conventional":
            for actor in (2, 3):
                self.act(world, 4, "request_project_work", pid, department=actor)
        self.act(world, 3, "implement_project")
        if mode == "conventional":
            for recipient in (2, 4):
                self.act(world, 3, "report_status", pid, recipient=recipient)
        self.act(world, 2, "implement_project")
        if mode == "conventional":
            self.act(world, 2, "report_status", pid, recipient=4)
        visible = next(p for p in world.observe(4)["projects"] if p["id"] == pid)
        while world.round < visible["ready_round"]:
            self.act(world, 4, "wait")

    def test_wrong_shared_plan_spends_resources_but_fails_in_both_channels(self):
        for mode in ("conventional", "structured"):
            with self.subTest(mode=mode):
                world, pid = self.prepare(mode, shared=False)
                self.construct(world, pid, mode)
                before = deepcopy(world.metrics())
                result = self.act(world, 2, "commission_project", expect="business_rejected")
                self.assertEqual(result["code"], "physical_intervention_not_matched")
                self.assertEqual(world.projects[pid]["physical"], "commissioning_failed")
                self.assertIsNone(world.projects[pid]["effective_at"])
                self.assertEqual(world.projects[pid]["capital_spent"], 6)
                self.assertEqual(world.metrics()["capital_spent"], before["capital_spent"])
                self.assertAlmostEqual(world.metrics()["labor_spent"] - before["labor_spent"],
                                       world.config["decision_cost"] + world.config["project_commission_cost"] +
                                       (world.config["maintenance_cost"] if mode == "structured" else 0))
                if mode == "conventional":
                    self.act(world, 2, "report_status", pid, recipient=4)
                refusal = self.act(world, 4, "accept_project", pid, expect="business_rejected")
                self.assertEqual(refusal["code"], "commissioning_success_receipt_not_received")
                self.assertEqual(world.metrics()["projects_completed"], 0)
                self.assertEqual(world.metrics()["repaired_facilities"], 0)

    def test_unsupported_topic_can_cancel_without_refund_or_success(self):
        for mode in ("conventional", "structured"):
            with self.subTest(mode=mode):
                world, pid = self.prepare(mode, shared=False)
                self.construct(world, pid, mode)
                before = world.metrics()
                self.act(world, 4, "cancel_project", pid, reason_code="evidence_does_not_support")
                after = world.metrics()
                self.assertEqual(world.projects[pid]["state"], "cancelled")
                self.assertEqual(after["capital_spent"], before["capital_spent"])
                self.assertEqual(after["capital_spent"], 6)
                self.assertGreater(after["labor_spent"], before["labor_spent"])
                self.assertEqual(after["projects_completed"], 0)
                self.assertEqual(after["repaired_facilities"], 0)

    def test_matched_project_succeeds_while_every_stage_is_b_invariant(self):
        for mode in ("conventional", "structured"):
            with self.subTest(mode=mode):
                world, pid = self.prepare(mode, shared=True)
                self.construct(world, pid, mode)
                self.act(world, 2, "commission_project")
                self.assertEqual(world.projects[pid]["physical"], "effective")
                self.assertEqual(world.projects[pid]["administrative"], "open")
                if mode == "conventional":
                    self.act(world, 2, "report_status", pid, recipient=4)
                self.act(world, 4, "accept_project", pid)
                self.assertEqual(world.projects[pid]["state"], "completed")
                self.assertEqual(world.metrics()["repaired_facilities"], 3)
                self.assertEqual(world.metrics()["initial_resolved"], 0)


if __name__ == "__main__":
    unittest.main()
