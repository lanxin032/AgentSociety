"""Optional installed-framework adapter contract, offline and without Ray startup."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(importlib.util.find_spec("agentsociety2"), "AgentSociety is not installed")
class FrameworkAdapterTests(unittest.TestCase):
    def test_registered_actors_round_trip_through_official_lifecycle(self):
        # Isolate framework global configuration from the ordinary offline suite.
        script = r'''
import asyncio
from datetime import datetime
import os
from pathlib import Path
from types import SimpleNamespace
from tests.fixtures import WorkspaceTemporaryDirectory
from tools.check_remote import check_imports
from policy_mve.io import read_json

os.environ["WORKSPACE_PATH"] = str(Path.cwd())
assert all(row["ok"] for row in check_imports().values())
from agentsociety2.registry import scan_and_register_custom_modules, get_agent_module_class
registered = scan_and_register_custom_modules(Path.cwd())
assert not registered.get("errors"), registered.get("errors")
from policy_mve.router import PolicyRouterActor
from policy_v3.router import PolicyV3RouterActor

class NoModel:
    model_name = "offline-no-requests"
    async def call(self, *args, **kwargs):
        raise AssertionError("This contract must not call a model")

async def run():
    for name, router_class in (("PolicyOfficer", PolicyRouterActor), ("PolicyV3Officer", PolicyV3RouterActor)):
        fixture = WorkspaceTemporaryDirectory()
        try:
            path = Path(fixture.name)
            client = NoModel()
            router = router_class(path, "111", 0, 3, "scripted", client)
            await router.init(datetime(2026, 1, 1, 9))
            proxy = SimpleNamespace(env=router, llm=SimpleNamespace(default=client))
            cls = get_agent_module_class(name)
            for actor_id in (1, 2, 3, 4):
                folder = path / "agents" / str(actor_id)
                cls.create(folder, {"id": actor_id}, {"decision_mode": "scripted", "enable_memory": False, "enable_todo_list": False})
                agent = await cls.from_workspace(folder, proxy)
                await agent.step(60, datetime(2026, 1, 1, 9))
                await agent.to_workspace(folder)
                restored = await cls.from_workspace(folder, proxy)
                assert await restored.ask("status") == await agent.ask("status")
                await restored.to_workspace(folder)
                assert read_json(folder / "AGENT.json")["step_count"] == 1
            await router.step(60, datetime(2026, 1, 1, 9))
            await router.to_workspaces()
            restored_router = router_class(path, "111", 0, 3, "scripted", client)
            assert await restored_router.from_workspaces()
            assert restored_router.owner_snapshot() == router.owner_snapshot()
            await router.close()
            await restored_router.close()
            print(name + " official adapter contract passed")
        finally:
            fixture.cleanup()

asyncio.run(run())
'''
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PolicyOfficer official adapter contract passed", result.stdout)
        self.assertIn("PolicyV3Officer official adapter contract passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
