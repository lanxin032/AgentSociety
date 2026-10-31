"""Offline environment and source-bundle identity checks."""
import importlib.metadata
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from policy_sim.runtime import code_digest, code_manifest
from tools import build_source_bundle


class RuntimeIdentityTests(unittest.TestCase):
    def test_locked_environment_records_versions_and_rejects_drift(self):
        from policy_sim.runtime import runtime_environment
        environment = runtime_environment()
        self.assertEqual(environment['packages']['ray'], importlib.metadata.version('ray'))
        self.assertIn('litellm', environment['packages'])
        self.assertIn('python', environment)
        version = importlib.metadata.version
        with patch('importlib.metadata.version', side_effect=lambda name: '0.0' if name == 'ray' else version(name)):
            with self.assertRaisesRegex(ValueError, 'ray.*requirements.lock'):
                runtime_environment()

    def test_lock_changes_source_identity_and_is_shipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name in ('README.md', 'ARCHITECTURE.md', 'CONTEXT.md', '.gitignore', 'environment.yml'):
                (root / name).write_text('fixture\n')
            lock = root / 'requirements.lock'
            lock.write_text('ray==2.55.1\n')
            self.assertIn('requirements.lock', {row['path'] for row in code_manifest(root)})
            before = code_digest(root)
            lock.write_text('ray==0.0\n')
            self.assertNotEqual(code_digest(root), before)
            with patch.object(build_source_bundle, 'ROOT', root):
                result = build_source_bundle.build(root / 'runs/source.zip')
            with zipfile.ZipFile(result['path']) as archive:
                self.assertEqual(archive.read('requirements.lock'), lock.read_bytes())
