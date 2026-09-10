import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.fixtures import WorkspaceTemporaryDirectory
from verify_smoke import verify


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = WorkspaceTemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source, self.query = self.root / "source", self.root / "query"
        self.write(self.source / "summary.json", {
            "ok": False, "api_probe": {"reply": "CLOUD_SMOKE_OK"},
            "driver": {"ray_shutdown": True, "agent_results": [{"id": i, "ok": True, "summary": "ready"} for i in (1, 2)]},
        })
        self.query_report = {
            "ok": False, "budget_after": {},
            "driver": {"environment_restored": True, "query_answer": "blocked", "completed_steps": 1,
                       "simulation_time": "2026-01-01T09:01:00", "ray_shutdown": True},
        }
        self.write(self.query / "summary.json", self.query_report)
        simulation = self.source / "simulation"
        self.write(simulation / "SOCIETY.json", {"agent_class_name": "PersonAgent", "env_module_types": ["SimpleSocialSpace"]})
        self.write(simulation / "SOCIETY_STEP.json", {"step_count": 1, "current_time": "2026-01-01T09:01:00"})
        self.write(simulation / "env/SimpleSocialSpace/state/ENV_STATE.json", {})
        for identifier in (1, 2):
            self.write(simulation / f"agents/agent_{identifier:04d}/AGENT.json", {"step_count": 1})
        self.write(simulation / "replay/state.jsonl", {"step": 1})

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_failed_query_is_not_reported_as_overall_pass(self):
        report = verify(self.source, self.query)
        self.assertTrue(report["core_ok"])
        self.assertFalse(report["query_ok"])
        self.assertFalse(report["ok"])

    def test_successful_query_cannot_hide_failed_checkpoint(self):
        self.query_report["ok"] = True
        self.query_report["driver"]["query_answer"] = "Alice and Bob"
        self.write(self.query / "summary.json", self.query_report)
        self.write(self.source / "simulation/agents/agent_0001/AGENT.json", {"step_count": 0})
        report = verify(self.source, self.query)
        self.assertFalse(report["core_ok"])
        self.assertTrue(report["query_ok"])
        self.assertFalse(report["ok"])


if __name__ == "__main__":
    unittest.main()
