"""Meaningful contract, causal-boundary and replay tests; no paid execution."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from policy_mve import PolicyWorld, scripted_action


def action(kind, target=None, **params):
    return {"kind": kind, "target": target, "params": params, "reason": "test"}


def play(world, rounds=1):
    for _ in range(rounds):
        observations = {i: world.observe(i) for i in range(1, 5)}
        for actor, observation in observations.items():
            world.submit(actor, scripted_action(observation))
        world.advance()
    return world


def coordination_fixture(policy="111", mode="joint"):
    world = PolicyWorld(policy, config={"shock_probability": 0, "common_root_shock_probability": 0})
    for actor, choice in [(1, action("route", "T00004", department=2)),
                          (2, action("inspect", "T00004")),
                          (2, action("request_coordination", "T00004", mode=mode))]:
        world.submit(actor, choice)
        world.advance()
    return world


class PolicyCoreTests(unittest.TestCase):
    def test_last_receipt_reports_own_settlement_and_exact_paid_resources(self):
        world = PolicyWorld()
        self.assertIsNone(world.observe(1)["last_receipt"])
        world.submit(1, action("route", "T00001", department=2, use_recommendation=True))
        self.assertIsNone(world.observe(1)["last_receipt"])
        world.advance()
        self.assertEqual(world.observe(1)["last_receipt"], {
            "round": 0, "status": "executed", "code": "routed",
            "action_kind": "route", "target": "T00001",
            "resources_paid": {"labor": .8, "capital": 0, "crew": 0},
        })
        self.assertEqual(world.observe(2)["last_receipt"], {
            "round": 0, "status": "executed", "code": "waited",
            "action_kind": "wait", "target": None,
            "resources_paid": {"labor": 0, "capital": 0, "crew": 0},
        })

    def test_rejected_business_action_returns_private_reason_after_settlement(self):
        world = PolicyWorld()
        receipt = world.submit(4, action("inspect", "T00001"))
        self.assertEqual(receipt["status"], "queued")
        world.advance()
        result = world.observe(4)["last_receipt"]
        self.assertEqual(result["status"], "business_rejected")
        self.assertEqual(result["code"], "department_action_required")
        self.assertEqual(result["resources_paid"], {"labor": .1, "capital": 0, "crew": 0})
        self.assertEqual(result["action_kind"], "inspect")
        self.assertNotIn("department_action_required", json.dumps(world.observe(2)["last_receipt"]))
        self.assertNotIn("events", world.observe(4))

    def test_last_receipt_is_latest_actor_only_and_observation_is_immutable(self):
        world = coordination_fixture()
        for actor in (2, 3):
            world.submit(actor, action("work", "T00004"))
        world.advance()
        result = world.observe(2)["last_receipt"]
        self.assertEqual(result["resources_paid"], {"labor": 1.1, "capital": .5, "crew": 1})
        self.assertEqual(set(result), {"round", "status", "code", "action_kind", "target", "resources_paid"})
        snapshot = world.export_state()
        observation = world.observe(2)
        observation["last_receipt"]["resources_paid"]["capital"] = 999
        observation["public_rules"]["project_workflow"] = "modified"
        self.assertEqual(snapshot, world.export_state())
        self.assertEqual(world.observe(2)["last_receipt"], result)
        world.advance()
        self.assertEqual(world.observe(2)["last_receipt"]["round"], 4)
        self.assertEqual(world.observe(2)["last_receipt"]["action_kind"], "wait")

    def test_public_workflow_rules_are_shared_across_roles_and_policies(self):
        expected = PolicyWorld("000").observe(1)["public_rules"]
        for policy in ("000", "111"):
            for actor in range(1, 5):
                rules = PolicyWorld(policy).observe(actor)["public_rules"]
                self.assertEqual(rules, expected)
                self.assertIn("角色2或3", rules["case_workflow"])
                for stage in ("propose_project", "diagnose_project", "implement_project", "accept_project"):
                    self.assertIn(stage, rules["project_workflow"])

    def test_joint_confirmation_is_explicit_and_only_activates_information_board(self):
        world = coordination_fixture()
        ticket = world.tickets["T00004"]
        self.assertEqual(ticket["joint_participants"], [2, 3])
        self.assertEqual(ticket["joint_confirmed_by"], [])
        self.assertIsNone(ticket["joint_activated_round"])
        self.assertFalse(ticket["shared_board"])
        prior_capital, prior_labor = world.capital, deepcopy(world.labor)
        prior_crew = world.metrics()["shared_crew_units_spent"]
        before_issues = deepcopy(world.issues)
        for actor in (2, 3):
            world.submit(actor, action("confirm_joint_task", "T00004"))
        world.advance()
        self.assertEqual(ticket["joint_confirmed_by"], [2, 3])
        self.assertEqual(ticket["joint_activated_round"], 3)
        self.assertTrue(ticket["shared_board"])
        self.assertEqual(ticket["done"], [])
        self.assertFalse(ticket["closed"])
        self.assertEqual(before_issues, world.issues)
        self.assertEqual(prior_capital, world.capital)
        self.assertEqual(prior_crew, world.metrics()["shared_crew_units_spent"])
        for actor in (2, 3):
            self.assertAlmostEqual(prior_labor[str(actor)] - world.labor[str(actor)], world.config["decision_cost"])
        self.assertEqual(sum(e["kind"] == "joint_task_confirmed" for e in world.events), 2)
        self.assertEqual(sum(e["kind"] == "joint_board_activated" for e in world.events), 1)
        metrics = world.metrics()["tool_process"]["B"]
        self.assertEqual(metrics["confirmed_participations"], 2)
        self.assertEqual(metrics["fully_confirmed_cases"], 1)
        self.assertEqual(metrics["confirmed_and_resolved"], 0)

    def test_joint_confirmation_permissions_identity_and_repetition(self):
        world = coordination_fixture()
        self.assertEqual(world.submit(2, action("confirm_joint_task", "T00004", actor_id=3))["code"], "unexpected_action_params")
        world.submit(4, action("confirm_joint_task", "T00004"))
        world.submit(1, action("confirm_joint_task", "T00004"))
        world.advance()
        self.assertEqual(world.tickets["T00004"]["joint_confirmed_by"], [])
        request = action("confirm_joint_task", "T00004")
        world.submit(2, request)
        snapshot = world.export_state()
        self.assertEqual(world.submit(2, deepcopy(request))["code"], "duplicate_idempotent")
        self.assertEqual(world.export_state(), snapshot)
        world.advance()
        world.submit(2, request)
        world.advance()
        self.assertEqual(world.tickets["T00004"]["joint_confirmed_by"], [2])
        self.assertEqual(sum(e["kind"] == "joint_task_confirmed" for e in world.events), 1)
        self.assertTrue(any(e["kind"] == "action_result" and e["code"] == "joint_task_already_confirmed" for e in world.events))

    def test_unconfirmed_and_partly_confirmed_cases_can_finish_ordinary_work(self):
        for confirm_first in (False, True):
            world = coordination_fixture()
            if confirm_first:
                world.submit(2, action("confirm_joint_task", "T00004"))
                world.advance()
            for actor in (2, 3):
                self.assertTrue(any(a["kind"] == "work" and a["target"] == "T00004" for a in world.observe(actor)["available_actions"]))
                world.submit(actor, action("work", "T00004"))
            world.advance()
            self.assertTrue(world.tickets["T00004"]["closed"])
            self.assertFalse(world.tickets["T00004"]["shared_board"])
            process = world.metrics()["tool_process"]["B"]
            self.assertEqual(process["completed"], 1)
            self.assertEqual(process["fully_confirmed_cases"], 0)
            self.assertEqual(process["confirmed_participations"], int(confirm_first))
            world.submit(3, action("confirm_joint_task", "T00004"))
            world.advance()
            self.assertEqual(world.metrics()["tool_process"]["B"]["confirmed_participations"], int(confirm_first))

    def test_baseline_cannot_confirm_and_keeps_conventional_work(self):
        world = coordination_fixture("000", "conventional")
        for actor in (2, 3):
            self.assertFalse(any(a["kind"] == "confirm_joint_task" for a in world.observe(actor)["available_actions"]))
            world.submit(actor, action("confirm_joint_task", "T00004"))
        world.advance()
        self.assertEqual(world.tickets["T00004"]["joint_confirmed_by"], [])
        for actor in (2, 3):
            world.submit(actor, action("work", "T00004"))
        world.advance()
        self.assertTrue(world.tickets["T00004"]["closed"])

    def test_confirmation_observation_whitelist_and_restore(self):
        world = coordination_fixture()
        for actor in (1, 4):
            self.assertFalse(any("joint_invitation" in t or "shared_board" in t for t in world.observe(actor)["visible_tickets"]))
        for actor in (2, 3):
            ticket = next(t for t in world.observe(actor)["visible_tickets"] if t["id"] == "T00004")
            self.assertEqual(ticket["joint_invitation"], {"participants": [2, 3], "confirmed_by": [], "activated_round": None})
            self.assertNotIn("shared_board", ticket)
            self.assertIn("conventional_feedback", ticket)
        world.submit(2, action("confirm_joint_task", "T00004"))
        world.advance()
        restored = PolicyWorld.from_state(json.loads(json.dumps(world.export_state())))
        for copy in (world, restored):
            copy.submit(3, action("confirm_joint_task", "T00004"))
            copy.advance()
        self.assertEqual(world.export_state(), restored.export_state())
        for actor in (2, 3):
            ticket = next(t for t in world.observe(actor)["visible_tickets"] if t["id"] == "T00004")
            self.assertEqual(ticket["shared_board"], {"required": [2, 3], "done": []})
        legacy = world.export_state()
        legacy["spec_version"] = "policy-mve-1.0"
        with self.assertRaises(ValueError):
            PolicyWorld.from_state(legacy)

    def test_confirmed_cases_record_resolution_separately(self):
        world = coordination_fixture()
        for kind in ("confirm_joint_task", "work"):
            for actor in (2, 3):
                world.submit(actor, action(kind, "T00004"))
            world.advance()
        process = world.metrics()["tool_process"]["B"]
        self.assertEqual(process["used"], 1)
        self.assertEqual(process["completed"], 1)
        self.assertEqual(process["confirmed_participations"], 2)
        self.assertEqual(process["fully_confirmed_cases"], 1)
        self.assertEqual(process["confirmed_and_resolved"], 1)

    def test_initial_fixture_and_all_policy_legality(self):
        for n in range(8):
            world = PolicyWorld(f"{n:03b}")
            self.assertEqual(len(world.issues), 12)
            self.assertEqual(len(world.tickets), 12)
            play(world, 18)
            self.assertGreaterEqual(world.metrics()["projects_completed"], 1, f"{n:03b}")
            self.assertTrue(any(t["coordination"] for t in world.tickets.values()))
            self.assertTrue(all(v >= 0 for v in world.labor.values()))
            self.assertGreaterEqual(world.capital, 0)

    def test_complete_json_checkpoint_and_deterministic_continuation(self):
        world = play(PolicyWorld(seed=17), 7)
        world.submit(1, scripted_action(world.observe(1)))
        restored = PolicyWorld.from_state(json.loads(json.dumps(world.export_state())))
        for actor in (2, 3, 4):
            chosen = scripted_action(world.observe(actor))
            self.assertEqual(world.submit(actor, chosen), restored.submit(actor, chosen))
        world.advance()
        restored.advance()
        play(world, 5)
        play(restored, 5)
        self.assertEqual(world.export_state(), restored.export_state())

    def test_observation_whitelist_and_hidden_mutation_invariance(self):
        world = PolicyWorld()
        before = {i: world.observe(i) for i in range(1, 5)}
        for facility in world.facilities.values():
            facility["root"] = "DO_NOT_EXPOSE"
            facility["required"] = [3]
        for issue in world.issues.values():
            issue["required"] = [3]
        after = {i: world.observe(i) for i in range(1, 5)}
        self.assertEqual(before, after)
        for observation in after.values():
            self.assertNotIn("policy", observation)
            text = json.dumps(observation)
            for forbidden in ("DO_NOT_EXPOSE", '"issue"', '"root"', '"root_repaired"', '"archetype"'):
                self.assertNotIn(forbidden, text)
        routes = [a for a in world.observe(1)["available_actions"] if a["kind"] == "route" and a["target"] == "T00001"]
        self.assertEqual({a["params"]["department"] for a in routes}, {2, 3})

    def test_observe_is_pure_and_cannot_mutate_world(self):
        world = PolicyWorld()
        checkpoint = world.export_state()
        observation = world.observe(1)
        observation["visible_tickets"][0]["text"] = "modified"
        world.observe(4)
        self.assertEqual(world.export_state(), checkpoint)

    def test_duplicate_submit_and_bound_identity(self):
        world = PolicyWorld()
        a = action("route", "T00001", department=2)
        self.assertEqual(world.submit(1, a)["status"], "queued")
        pending_state = world.export_state()
        self.assertEqual(world.submit(1, deepcopy(a))["code"], "duplicate_idempotent")
        self.assertEqual(world.export_state(), pending_state)
        self.assertEqual(world.submit(1, action("wait"))["code"], "one_action_per_round")
        world.advance()
        routed = [e for e in world.events if e["kind"] == "routed"]
        self.assertEqual(len(routed), 1)
        self.assertEqual(world.submit(2, {**a, "actor_id": 1})["status"], "technical_error")
        world.submit(2, action("route", "T00002", department=2))
        world.advance()
        self.assertIsNone(world.tickets["T00002"]["lead"])

    def test_baseline_cross_department_parallel_work_is_legal(self):
        world = PolicyWorld("000", config={"shock_probability": 0, "common_root_shock_probability": 0})
        for actor, a in [(1, action("route", "T00004", department=2)),
                         (2, action("inspect", "T00004")),
                         (2, action("request_coordination", "T00004", mode="conventional"))]:
            world.submit(actor, a)
            world.advance()
        world.submit(2, action("work", "T00004"))
        world.submit(3, action("work", "T00004"))
        world.advance()
        self.assertTrue(world.tickets["T00004"]["closed"])
        self.assertEqual(world.issues[world.tickets["T00004"]["issue"]]["done"], [2, 3])

    def test_wrong_route_is_recoverable_after_paid_inspection(self):
        world = PolicyWorld("000")
        for actor, a in [(1, action("route", "T00001", department=3)),
                         (3, action("inspect", "T00001")),
                         (3, action("request_coordination", "T00001", mode="conventional")),
                         (2, action("work", "T00001"))]:
            world.submit(actor, a)
            world.advance()
        self.assertTrue(world.tickets["T00001"]["closed"])

    def test_false_common_cause_cannot_pass_acceptance(self):
        world = PolicyWorld("111")
        seq = [action("propose_project", "片区4|供水波动", mode="structured"),
               action("diagnose_project", "P0001"),
               action("implement_project", "P0001", plan="replace_shared_main"),
               action("implement_project", "P0001", plan="replace_shared_main"),
               action("wait"), action("accept_project", "P0001")]
        for a in seq:
            world.submit(4, a)
            world.advance()
        self.assertEqual(world.projects["P0001"]["state"], "failed")
        self.assertFalse(any(f["root_repaired"] for f in world.facilities.values()))
        self.assertEqual(world.metrics()["capital_spent"], 6)

    def test_project_requires_evidence_resources_and_lag(self):
        world = PolicyWorld()
        for a in [action("propose_project", "片区3|供水波动", mode="structured"),
                  action("implement_project", "P0001", plan="replace_shared_main")]:
            world.submit(4, a)
            world.advance()
        self.assertEqual(world.projects["P0001"]["steps_done"], 0)
        for a in [action("diagnose_project", "P0001"),
                  action("implement_project", "P0001", plan="replace_shared_main"),
                  action("implement_project", "P0001", plan="replace_shared_main"),
                  action("accept_project", "P0001")]:
            world.submit(4, a)
            world.advance()
        self.assertEqual(world.projects["P0001"]["state"], "awaiting_acceptance")
        world.submit(4, action("accept_project", "P0001"))
        world.advance()
        self.assertEqual(world.projects["P0001"]["state"], "completed")
        poor = PolicyWorld(config={"capital": 0})
        play(poor, 12)
        self.assertEqual(poor.metrics()["projects_completed"], 0)
        self.assertEqual(poor.capital, 0)

    def test_public_repeat_deduplication(self):
        world = PolicyWorld(config={"shock_probability": 0, "common_root_shock_probability": 0})
        for _ in range(4):
            world.advance()
        self.assertEqual(len(world.issues), 12)
        self.assertEqual(len(world.tickets), 24)
        topic = next(t for t in world.observe(4)["topics"] if t["id"] == "片区3|供水波动")
        self.assertEqual(topic["record_count"], 3)

    def test_policy_independent_external_random_draws(self):
        a, b = play(PolicyWorld("000", seed=8), 18), play(PolicyWorld("111", seed=8), 18)
        def draws(w):
            return [(e["round"], e["facility"], e["draw"]) for e in w.events if e["kind"] == "external_shock"]
        self.assertEqual(draws(a), draws(b))

    def test_no_policy_bonus_for_identical_legal_actions(self):
        a, b = PolicyWorld("000"), PolicyWorld("111")
        for actor, choice in [(1, action("route", "T00001", department=2)),
                              (2, action("inspect", "T00001")),
                              (2, action("work", "T00001"))]:
            a.submit(actor, choice)
            b.submit(actor, choice)
            a.advance()
            b.advance()
        self.assertEqual(a.issues, b.issues)
        self.assertEqual(a.labor, b.labor)
        self.assertEqual(a.capital, b.capital)

    def test_resource_ledger_conservation_and_horizon_noop(self):
        world = play(PolicyWorld(horizon=10), 10)
        spending = [e for e in world.events if e["kind"] == "resource_spent"]
        self.assertAlmostEqual(sum(e["labor"] for e in spending), world.metrics()["labor_spent"])
        self.assertAlmostEqual(sum(e["capital"] for e in spending), world.metrics()["capital_spent"])
        before = world.export_state()
        world.advance()
        self.assertEqual(before, world.export_state())
        self.assertEqual(world.submit(1, action("wait"))["code"], "horizon_reached")

    def test_shared_crew_and_capital_competition_with_rotating_priority(self):
        world = PolicyWorld(config={"shock_probability": 0, "common_root_shock_probability": 0})
        world.submit(1, action("route", "T00001", department=2))
        world.submit(4, action("propose_project", "片区3|供水波动", mode="conventional"))
        world.advance()
        world.submit(1, action("route", "T00003", department=3))
        world.submit(2, action("inspect", "T00001"))
        world.submit(4, action("diagnose_project", "P0001"))
        world.advance()
        world.submit(3, action("inspect", "T00003"))
        world.advance()
        world.submit(2, action("work", "T00001"))
        world.submit(3, action("work", "T00003"))
        world.submit(4, action("implement_project", "P0001", plan="replace_shared_main"))
        world.advance()
        self.assertEqual(world.projects["P0001"]["steps_done"], 0)
        self.assertEqual(world.capital, 23)
        self.assertTrue(any(e["kind"] == "action_result" and e["round"] == 3 and e["actor_id"] == 4 and e["code"] == "insufficient_project_resources" for e in world.events))
        orders = [e["actors"] for e in world.events if e["kind"] == "settlement_order"]
        self.assertEqual(orders[:3], [[1, 2, 3, 4], [1, 3, 4, 2], [1, 4, 2, 3]])
        world.submit(4, action("implement_project", "P0001", plan="replace_shared_main"))
        world.advance()
        self.assertEqual(world.projects["P0001"]["steps_done"], 1)
        self.assertEqual(world.capital, 20)
        for r in range(world.round):
            self.assertLessEqual(sum(e["crew"] for e in world.events if e["kind"] == "resource_spent" and e["round"] == r), 2)

    def test_cooldown_begins_at_terminal_event(self):
        world = PolicyWorld(config={"signal_window": 100})
        seq = [action("propose_project", "片区3|供水波动", mode="conventional"),
               action("diagnose_project", "P0001"),
               action("implement_project", "P0001", plan="replace_shared_main"),
               action("implement_project", "P0001", plan="replace_shared_main"),
               action("wait"), action("accept_project", "P0001")]
        for a in seq:
            world.submit(4, a)
            world.advance()
        self.assertEqual(world.topic_history["片区3|供水波动"], 5)
        topic = next(t for t in world.observe(4)["topics"] if t["id"] == "片区3|供水波动")
        self.assertFalse(topic["eligible"])
        for _ in range(5):
            world.advance()
        topic = next(t for t in world.observe(4)["topics"] if t["id"] == "片区3|供水波动")
        self.assertTrue(topic["eligible"])

    def test_persistent_fault_does_not_generate_duplicate_issues(self):
        world = PolicyWorld(config={"shock_probability": 1, "common_root_shock_probability": 1})
        for _ in range(4):
            world.advance()
        self.assertEqual(len(world.issues), 12)
        self.assertEqual(world.metrics()["new_issues"], 0)
        self.assertEqual(world.metrics()["repeat_contacts"], 12)
        self.assertEqual(sum(e["kind"] == "suppress_new_issue" for e in world.events), 48)

    def test_param_whitelist_and_completion_not_resolution(self):
        world = PolicyWorld()
        for extra in ("actor_id", "capital", "root_id", "success"):
            self.assertEqual(world.submit(1, action("route", "T00001", department=2, **{extra: 1}))["code"], "unexpected_action_params")
        self.assertFalse(world.pending)
        world.submit(1, action("route", "T00001", department=2, use_recommendation=True))
        world.advance()
        process = world.metrics()["tool_process"]["A"]
        self.assertEqual(process["completed"], 1)
        self.assertEqual(process["objective_resolved"], 0)
        play(world, 10)
        self.assertGreaterEqual(world.metrics()["tool_process"]["C"]["completed"], 1)
        self.assertEqual(world.metrics()["tool_process"]["C"]["objective_resolved"], 0)


if __name__ == "__main__":
    unittest.main()
