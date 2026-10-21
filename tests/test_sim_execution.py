"""Current-only execution integrity checks; no paid requests or live ledger."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from policy_sim.io import write_json, read_json
from policy_sim.profiles import make_profile
from policy_sim.protocol import make_manifest, validate_manifest, prepare
from policy_sim.execution import AttemptRegistry, ExecutionError, execute_stage, validate_authorization
from policy_sim.checkpoints import commit_round, validate_commit, restore_payload_links
from policy_sim.router import RUNTIME_VERSION


class ExecutionIntegrityTests(unittest.TestCase):
    def test_current_manifest_freezes_finite_science(self):
        root = Path(__file__).resolve().parents[1]
        manifest = make_manifest(root)
        self.assertEqual(len(validate_manifest(manifest, 'finite_baseline')), 1)
        self.assertIsNone(manifest['runs'][0]['horizon'])
        manifest['runs'][0]['seed'] = 7
        with self.assertRaises(ExecutionError):
            validate_manifest(manifest, 'finite_baseline')
        manifest['schema_version'] = 'finite-workload-plan-1'
        with self.assertRaises(ExecutionError):
            validate_manifest(manifest, 'finite_baseline')

    def test_authorization_accepts_only_current_record_only_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / 'runs/api-local-budget.json', [{'status': 'complete', 'input_rate': 2.0,
                'output_rate': 8.0, 'reserved_rmb': 0.1, 'estimated_rmb': 0.01}])
            proposal = prepare(root, root / 'runs/proposal')
            auth = {**proposal['proposal'], 'approved': True, 'explicit_stage_authorization': True,
                    'user_evidence_reference': 'offline fixture', 'approval_reference': 'offline fixture'}
            path = Path(proposal['manifest'])
            self.assertEqual(validate_authorization(auth, path, 'finite_baseline', root), auth)
            for mutation in ({'cost_control_mode': 'enforced'}, {'automatic_technical_retries': True},
                             {'max_recoveries_per_run': 1}, {'request_profiles': []}):
                with self.assertRaises(ExecutionError):
                    validate_authorization({**auth, **mutation}, path, 'finite_baseline', root)

    def test_explicit_continuation_keeps_initial_cap_and_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = AttemptRegistry(Path(directory) / 'attempts.jsonl')
            first = registry.start('run', 'auth', 1, attempt_scope='authorization')
            registry.append('technical_failure', first)
            with self.assertRaises(ExecutionError):
                registry.start('run', 'auth', 1, attempt_scope='authorization')
            second = registry.start_continuation('run', 'auth', first, 'a' * 64)
            self.assertEqual(registry.latest(second)['recovery_of'], first)
            with self.assertRaises(ExecutionError):
                registry.start_continuation('run', 'auth', first, 'a' * 64)
            self.assertEqual(AttemptRegistry(registry.path).latest(second)['checkpoint_sha256'], 'a' * 64)

    def test_incomplete_attempt_launches_once_and_pauses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'runs').mkdir()
            manifest_path, auth_path = root / 'manifest.json', root / 'auth.json'
            write_json(manifest_path, make_manifest(root))
            auth = {'authorization_id': 'test', 'max_attempts': 1}
            write_json(auth_path, auth)
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                output = Path(command[command.index('--output') + 1])
                write_json(output / 'controller_receipt.json', {'clean_commit': False,
                    'ray_shutdown': True, 'latest_committed_round': 3, 'committed_steps': 3,
                    'failure': {'error_type': 'turn_incomplete'}})
                return SimpleNamespace(returncode=1)
            with patch('policy_sim.execution.validate_authorization', return_value=auth), \
                    patch('policy_sim.execution.authorization_paths', return_value={'control': root / 'control'}):
                self.assertFalse(execute_stage(root, manifest_path, auth_path, root / 'runs/batch', runner=runner))
            self.assertEqual(len(calls), 1)
            self.assertNotIn('--steps', calls[0])
            status = read_json(root / 'runs/batch/batch_status.json')
            self.assertEqual(status['status'], 'paused')
            self.assertEqual(next(iter(status['runs'].values()))['committed_steps'], 3)

    def test_round_zero_snapshot_survives_partial_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / 'run'
            run.mkdir()
            world = {'round': 0}
            for name, value in [('world.json', world), ('metrics.json', {}), ('SOCIETY.json', {}),
                                ('SOCIETY_STEP.json', {'step_count': 0}),
                                ('run_config.json', {'runtime_profile': make_profile(), 'mode': 'scripted'})]:
                write_json(run / name, value)
            for identifier in range(1, 5):
                folder = run / 'agents' / str(identifier)
                folder.mkdir(parents=True)
                write_json(folder / 'AGENT.json', {'schema_version': 1, 'agent_class': 'PolicyOfficer',
                    'agent_id': identifier, 'id': identifier, 'name': f'Role-{identifier}',
                    'profile': {'id': identifier, 'name': f'Role-{identifier}'},
                    'step_count': 0, 'current_time': None, 'tick': None, 'visible_skills': [],
                    'activated_skills': [], 'disabled_skills': [], 'default_activated_skills': [],
                    'initialized_at': None})
                profile = make_profile()
                config = {'decision_mode': 'scripted', 'runtime_version': RUNTIME_VERSION,
                    'runtime_profile': profile, 'enable_memory': True, 'enable_todo_list': False,
                    'max_react_turns': 10, 'default_activated_skill_ids': [],
                    'memory_context_max_chars': 4000, 'recent_memory_limit': 8,
                    'memory_consolidation_pending_threshold': 10, 'memory_consolidation_interval_steps': 8,
                    'memory_high_importance_threshold': 0.75}
                write_json(folder / 'config.json', config)
            agent_meta = read_json(run / 'agents/1/AGENT.json')
            write_json(run / 'agents/1/AGENT.json', {**agent_meta, 'step_count': 3})
            with self.assertRaises(RuntimeError):
                commit_round(run, 0, world, [])
            write_json(run / 'agents/1/AGENT.json', agent_meta)
            payload = run / "model_payloads/example.json"
            payload.parent.mkdir()
            payload.write_text("canonical immutable payload")
            commit_round(run, 0, world, [])
            snapshot = Path(read_json(Path(directory) / 'run-commits/latest.json')['path'])
            self.assertFalse((snapshot / 'model_payloads').exists())
            restored = Path(directory) / 'restored'
            restored.mkdir()
            restore_payload_links(snapshot, restored)
            self.assertEqual(payload.stat().st_ino, (restored / 'model_payloads/example.json').stat().st_ino)
            write_json(run / 'partial_failure.json', {'actor': 2})
            write_json(run / 'world.json', {'round': 0, 'mutated': True})
            with self.assertRaises(RuntimeError):
                validate_commit(run)
            self.assertEqual(validate_commit(snapshot)['round'], 0)
            write_json(snapshot / 'world.json', {'round': 1})
            with self.assertRaises(RuntimeError):
                validate_commit(snapshot)


if __name__ == '__main__':
    unittest.main()
