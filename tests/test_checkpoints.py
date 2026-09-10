"""Shared checkpoint commit/recovery contract, using temporary real files."""
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.fixtures import WorkspaceTemporaryDirectory
from policy_mve.io import append_jsonl, read_json, write_json
from policy_runtime.checkpoints import commit_round, validate_commit


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run_dir = Path(self.directory.name)
        self.world = {"round": 1, "cases": [{"id": "case-1", "resolved": False}]}
        for name, value in {
            "SOCIETY.json": {"agent_ids": [1, 2, 3, 4]},
            "SOCIETY_STEP.json": {"step_count": 1}, "world.json": self.world,
            "metrics.json": {"resolved": 0}, "run_config.json": {"mode": "scripted"},
            "env/PolicyCaseEnv/state/ENV_STATE.json": self.world,
            "env/PolicyCaseEnv/router.json": {"round": 1},
        }.items():
            write_json(self.run_dir / name, value)
        for identifier in (1, 2, 3, 4):
            folder = self.run_dir / "agents" / f"agent_{identifier:04d}"
            write_json(folder / "AGENT.json", {"id": identifier, "step_count": 1})
            write_json(folder / "config.json", {"decision_mode": "scripted"})
            write_json(folder / "state/business.json", {"history": [{"round": 0}]})
            append_jsonl(folder / "decisions.jsonl", {"round": 0, "kind": "wait"})
        append_jsonl(self.run_dir / "actions.jsonl", {"round": 0, "actor_id": 1})
        self.results = [{"round": 0, "actor_id": actor} for actor in (1, 2, 3, 4)]
        self.committed = commit_round(self.run_dir, 1, self.world, self.results)

    def test_intact_checkpoint_validates(self):
        self.assertEqual(validate_commit(self.run_dir), self.committed)
        commit_round(self.run_dir, 1, self.world, self.results)

    def test_round_validation_rejects_stale_society(self):
        write_json(self.run_dir / "SOCIETY_STEP.json", {"step_count": 0})
        with self.assertRaises(RuntimeError):
            commit_round(self.run_dir, 1, self.world, self.results)

    def test_round_validation_rejects_duplicate_identity_and_stale_actor(self):
        path = self.run_dir / "agents/agent_0004/AGENT.json"
        for state in ({"id": 1, "step_count": 1}, {"id": 4, "step_count": 0}):
            write_json(path, state)
            with self.subTest(state=state), self.assertRaises(RuntimeError):
                commit_round(self.run_dir, 1, self.world, self.results)

    def test_round_validation_rejects_missing_actor(self):
        (self.run_dir / "agents/agent_0004/AGENT.json").unlink()
        with self.assertRaises(RuntimeError):
            commit_round(self.run_dir, 1, self.world, self.results)

    def test_round_validation_rejects_stale_business_history(self):
        for history in ([], [{"round": -1}]):
            write_json(self.run_dir / "agents/agent_0004/state/business.json", {"history": history})
            with self.subTest(history=history), self.assertRaises(RuntimeError):
                commit_round(self.run_dir, 1, self.world, self.results)

    def test_world_tampering_rejected(self):
        write_json(self.run_dir / "world.json", {"round": 2})
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_each_actor_checkpoint_tampering_rejected(self):
        for identifier in (1, 2, 3, 4):
            path = self.run_dir / "agents" / f"agent_{identifier:04d}" / "AGENT.json"
            original = path.read_bytes()
            try:
                write_json(path, {"id": identifier, "step_count": 0})
                with self.subTest(identifier=identifier), self.assertRaises(RuntimeError):
                    validate_commit(self.run_dir)
            finally:
                path.write_bytes(original)

    def test_event_tail_append_rejected(self):
        append_jsonl(self.run_dir / "actions.jsonl", {"round": 1, "actor_id": 1})
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_agent_decision_tail_append_rejected(self):
        append_jsonl(self.run_dir / "agents/agent_0002/decisions.jsonl", {"round": 1})
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_missing_checkpoint_rejected(self):
        (self.run_dir / "agents/agent_0004/AGENT.json").unlink()
        with self.assertRaises(RuntimeError):
            validate_commit(self.run_dir)

    def test_invalid_live_round_never_replaces_marker(self):
        marker = self.run_dir / "committed.json"
        original = marker.read_bytes()
        for results, snapshot in (
            (self.results[:-1], self.world),
            (self.results[:-1] + [self.results[0]], self.world),
            (self.results, {**self.world, "cases": []}),
            (self.results, {**self.world, "round": 2}),
        ):
            with self.subTest(results=results, snapshot=snapshot), self.assertRaises(RuntimeError):
                commit_round(self.run_dir, 1, snapshot, results)
            self.assertEqual(marker.read_bytes(), original)

    def test_marker_replacement_failure_preserves_previous_commit(self):
        marker = self.run_dir / "committed.json"
        original = marker.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("interrupted replace")):
            with self.assertRaisesRegex(OSError, "interrupted replace"):
                commit_round(self.run_dir, 1, self.world, self.results)
        self.assertEqual(marker.read_bytes(), original)
        self.assertEqual(validate_commit(self.run_dir), self.committed)

    def test_missing_artifact_does_not_publish_first_commit(self):
        marker = self.run_dir / "committed.json"
        marker.unlink()
        (self.run_dir / "metrics.json").unlink()
        with self.assertRaises(OSError):
            commit_round(self.run_dir, 1, self.world, self.results)
        self.assertFalse(marker.exists())

    def test_corrupt_round_marker_cannot_authorize_resume(self):
        write_json(self.run_dir / "committed.json", {**self.committed, "round": 2})
        with self.assertRaisesRegex(RuntimeError, "committed round"):
            validate_commit(self.run_dir)

    def test_partial_failure_prevents_commit_and_resume(self):
        write_json(self.run_dir / "partial_failure.json", {"submitted": [1]})
        with self.assertRaisesRegex(RuntimeError, "Partial failure"):
            commit_round(self.run_dir, 1, self.world, self.results)
        with self.assertRaisesRegex(RuntimeError, "Partial failure"):
            validate_commit(self.run_dir)

    def test_prior_round_results_are_not_counted_again(self):
        results = [{"round": -1, "actor_id": actor} for actor in (1, 2, 3, 4)] + self.results
        self.assertEqual(commit_round(self.run_dir, 1, self.world, results), self.committed)
