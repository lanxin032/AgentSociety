"""Temporary test storage with normal inherited Windows workspace permissions."""
from pathlib import Path
import shutil
import uuid


class WorkspaceTemporaryDirectory:
    def __init__(self):
        self.base = Path(__file__).resolve().parent
        self.path = self.base / ("_fixture_" + uuid.uuid4().hex)
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        target = self.path.resolve()
        if target.parent != self.base or not target.name.startswith("_fixture_"):
            raise RuntimeError("Test cleanup path escaped its workspace")
        if target.exists():
            shutil.rmtree(target)
