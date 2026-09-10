from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
import uuid
import shutil

from policy_mve.core import PolicyWorld, scripted_action
from policy_mve.io import write_json
from policy_mve.spec import ACTORS
from policy_mve.verify import verify_world, verify_run, state_hash


def fixture(horizon=8, config=None):
    world = PolicyWorld(policy="111", seed=0, horizon=horizon, config=config)
    for _ in range(horizon):
        actions = {a: scripted_action(world.observe(a)) for a in ACTORS}
        for actor, action in actions.items():
            world.submit(actor, action)
        world.advance()
    return world


class IndependentVerificationTests(unittest.TestCase):
    def test_metrics_and_replay(self):
        world = fixture()
        report = verify_world(world.export_state())
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["metrics"], world.metrics())
        self.assertEqual(report["state_sha256"], report["replay_sha256"])

    def test_burden_excludes_next_round_shocks(self):
        world = fixture(8, {"shock_probability": 1.0, "common_root_shock_probability": 1.0})
        report = verify_world(world.export_state())
        self.assertTrue(report["passed"], report["errors"])
        completed = [e for e in world.events if e["kind"] == "round_completed"]
        self.assertTrue(any(e["unresolved"] > report["burden_per_round"][e["completed_round"] - 1] for e in completed))

    def test_resource_tampering_detected(self):
        state = fixture().export_state()
        state["labor"]["1"] += 1
        report = verify_world(state)
        self.assertFalse(report["passed"])
        self.assertIn("labor conservation mismatch: 1", report["errors"])

    def test_event_gap_detected(self):
        state = fixture(2).export_state()
        state["events"][2]["event_index"] = 999
        self.assertIn("event_index not continuous", verify_world(state)["errors"])

    def test_hidden_state_tamper_replay(self):
        state = fixture(2).export_state()
        state["facilities"]["F1-1"]["root_repaired"] = True
        self.assertIn("full state action replay hash mismatch", verify_world(state)["errors"])

    def test_offer_denominator_tampering(self):
        state = fixture().export_state()
        for e in state["events"]:
            if e["kind"] == "tool_opportunity" and e["tool"] == "A":
                e["offered"] = False
        self.assertFalse(verify_world(state)["passed"])

    def test_crew_overdraw_detected(self):
        state = fixture().export_state()
        spending = next(e for e in state["events"] if e["kind"] == "resource_spent")
        spending["crew"] = state["config"]["shared_crew_capacity"] + 1
        self.assertIn("shared crew overdraw", verify_world(state)["errors"])

    def test_effect_lag_tampering(self):
        state = fixture(18).export_state()
        event = next(e for e in state["events"] if e["kind"] == "project_completed")
        state["projects"][event["project"]]["ready_round"] = event["round"] + 1
        self.assertIn("project ready_round violated", verify_world(state)["errors"])

    def test_missing_initial_issue_detected(self):
        state = fixture(2).export_state()
        state["initial_ids"].pop()
        self.assertIn("initial_ids differs from created fixed queue", verify_world(state)["errors"])

    def test_joint_confirmation_metrics_from_events(self):
        world = fixture(18)
        state = world.export_state()
        report = verify_world(state)
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["metrics"], world.metrics())
        process = report["metrics"]["tool_process"]["B"]
        self.assertGreater(process["fully_confirmed_cases"], 0)
        self.assertEqual(process["confirmed_participations"], sum(e["kind"] == "joint_task_confirmed" for e in state["events"]))

    def test_joint_checkpoint_confirmer_tampering(self):
        state = fixture(18).export_state()
        tid = next(e["ticket"] for e in state["events"] if e["kind"] == "joint_task_confirmed")
        state["tickets"][tid]["joint_confirmed_by"].append(4)
        self.assertIn("joint confirmation checkpoint mismatch: " + tid, verify_world(state)["errors"])

    def test_joint_duplicate_confirmation_event(self):
        state = fixture(18).export_state()
        confirmed = [e for e in state["events"] if e["kind"] == "joint_task_confirmed"]
        first = confirmed[0]
        second = next(e for e in confirmed if e["ticket"] == first["ticket"] and e["actor_id"] != first["actor_id"])
        second["actor_id"] = first["actor_id"]
        self.assertIn("duplicate joint confirmation: " + first["ticket"], verify_world(state)["errors"])

    def test_joint_activation_time_tampering(self):
        state = fixture(18).export_state()
        event = next(e for e in state["events"] if e["kind"] == "joint_board_activated")
        state["tickets"][event["ticket"]]["joint_activated_round"] = event["round"] + 1
        self.assertIn("joint activation checkpoint mismatch: " + event["ticket"], verify_world(state)["errors"])

    def test_ordinary_work_before_joint_confirmation_is_valid(self):
        world = PolicyWorld(policy="111", seed=0, horizon=8)
        def action(kind, target=None, **params):
            return {"kind": kind, "target": target, "params": params, "reason": "verification fixture"}
        sequence = [
            {1: action("route", "T00004", department=2)},
            {2: action("inspect", "T00004")},
            {2: action("request_coordination", "T00004", mode="joint")},
            {2: action("work", "T00004"), 3: action("work", "T00004")},
        ]
        for actions in sequence:
            for actor, decision in actions.items():
                world.submit(actor, decision)
            world.advance()
        report = verify_world(world.export_state())
        self.assertTrue(report["passed"], report["errors"])
        self.assertEqual(report["metrics"], world.metrics())
        b = report["metrics"]["tool_process"]["B"]
        self.assertEqual(b["completed"], 1)
        self.assertEqual(b["fully_confirmed_cases"], 0)

    def test_joint_shared_board_premature_activation(self):
        state = fixture(8).export_state()
        tid = next(t["id"] for t in state["tickets"].values() if t["coordination"] == "joint" and not t.get("repeat_of"))
        state["tickets"][tid]["shared_board"] = not state["tickets"][tid]["shared_board"]
        self.assertIn("joint shared board checkpoint mismatch: " + tid, verify_world(state)["errors"])

    def test_legacy_state_requires_archived_verifier(self):
        state = fixture(2).export_state()
        state["spec_version"] = "policy-mve-1.0"
        report = verify_world(state)
        self.assertFalse(report["passed"])
        self.assertIsNone(report["metrics"])
        self.assertIn("archived source snapshot", report["errors"][0])

    def test_files_hash_and_metrics(self):
        world = fixture(2)
        # mkdir default ACL avoids Windows tempfile's restrictive mode=0700 behavior.
        parent = Path(__file__).resolve().parents[1]
        folder = parent / (".verify-test-" + uuid.uuid4().hex)
        folder.mkdir()
        try:
            write_json(folder / "world.json", world.export_state())
            write_json(folder / "metrics.json", world.metrics())
            files = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in ("world.json", "metrics.json")}
            write_json(folder / "committed.json", {"round": world.round, "world_sha256": state_hash(world.export_state()), "files": files})
            self.assertTrue(verify_run(folder)["passed"])
            altered = world.metrics()
            altered["initial_resolution_rate"] = 0.999
            write_json(folder / "metrics.json", altered)
            report = verify_run(folder)
            self.assertFalse(report["passed"])
            self.assertIn("metrics.json differs from independent metrics", report["errors"])
        finally:
            self.assertEqual(folder.resolve().parent, parent.resolve())
            shutil.rmtree(folder)


if __name__ == "__main__":
    unittest.main()
