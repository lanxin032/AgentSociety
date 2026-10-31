"""Current-only execution integrity checks; no paid requests or live ledger."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from policy_sim.io import write_json, read_json
from policy_sim.profiles import make_profile, settings_for_purpose
from policy_sim.protocol import make_manifest, validate_manifest, prepare, require_baseline
from policy_sim.execution import (AttemptRegistry, ExecutionError, execute_stage, validate_authorization,
                                  authorization_paths, file_hash, source_hash)
from policy_sim.checkpoints import commit_round, validate_commit, restore_payload_links
from policy_sim.runtime import code_manifest
from policy_sim.router import RUNTIME_VERSION


def make_checkpoint(path, root, record):
    path.mkdir(parents=True, exist_ok=True)
    for name, value in [('world.json', {'round': 1}), ('metrics.json', {}), ('SOCIETY.json', {}),
                        ('SOCIETY_STEP.json', {'step_count': 1}), ('record.json', record),
                        ('run_config.json', {'record': record, 'code_manifest': code_manifest(root)})]:
        write_json(path / name, value)
    for actor in range(1, 5):
        write_json(path / 'agents' / str(actor) / 'AGENT.json', {'agent_id': actor, 'step_count': 1})
    commit_round(path, 1, {'round': 1}, [])


def make_paused_batch(root, manifest_path, auth_path, auth, control):
    manifest = read_json(manifest_path)
    output, record = root / 'runs/batch', manifest['runs'][0]
    failed = output / record['run_id']
    make_checkpoint(failed, root, record)
    registry = AttemptRegistry(control / 'attempts.jsonl')
    aid = registry.start(record['run_id'], auth['authorization_id'], auth['max_attempts'],
                         attempt_scope='authorization')
    registry.append('technical_failure', aid)
    rows = {r['run_id']: {'status': 'prepared'} for r in manifest['runs']}
    rows[record['run_id']].update(status='paused', output_path=str(failed), attempt_id=aid, committed_steps=1)
    write_json(output / 'batch_status.json', {'source_sha256': source_hash(root),
        'manifest_sha256': file_hash(manifest_path), 'authorization_sha256': file_hash(auth_path),
        'stage': manifest['stage'], 'status': 'paused', 'runs': rows})
    return output


def authorized_baseline(root):
    write_json(root / 'runs/api-local-budget.json', [{'request': 1, 'status': 200,
        'reserved_rmb': 0.1, 'estimated_rmb': 0.01, 'input_rate': 2.0,
        'output_rate': 8.0, 'price_version': 'fixture-historical'}])
    prepared = prepare(root, root / 'runs/preflight')
    manifest_path, auth_path = Path(prepared['manifest']), root / 'runs/preflight/authorization.json'
    auth = {**prepared['proposal'], 'approved': True, 'explicit_stage_authorization': True,
            'user_evidence_reference': 'offline fixture', 'approval_reference': 'offline fixture'}
    write_json(auth_path, auth)
    return manifest_path, auth_path, auth


class ExecutionIntegrityTests(unittest.TestCase):
    def test_restored_payloads_are_readable_and_new_requests_preserve_failed_evidence(self):
        from uuid import uuid4
        from policy_sim.evidence import append_model_event, load_model_events
        from policy_sim.recovery import tree_hashes
        from policy_sim.checkpoints import copy_checkpoint
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'attempt'
            original.mkdir()
            row = {'event': 'request_started', 'request_id': str(uuid4()),
                   'messages': [{'role': 'user', 'content': 'known input'}]}
            append_model_event(original / 'model_requests.jsonl', row)
            write_json(original / 'recovery_lineage.json', [{'parent_attempt_id': 'earlier'}])
            snapshot = root / 'attempt-commits/round-000001'
            copy_checkpoint(original, snapshot)
            before = tree_hashes(original)
            resumed = root / 'resumed'
            copy_checkpoint(snapshot, resumed)
            restore_payload_links(snapshot, resumed)
            self.assertEqual(load_model_events(resumed)[0]['messages'], row['messages'])
            self.assertEqual(read_json(resumed / 'recovery_lineage.json'), [{'parent_attempt_id': 'earlier'}])
            append_model_event(resumed / 'model_requests.jsonl', {**row, 'request_id': str(uuid4())})
            self.assertEqual(tree_hashes(original), before)
            self.assertEqual(len(load_model_events(resumed)), 2)
            self.assertTrue(tree_hashes(resumed))
            second_snapshot = root / 'resumed-commits/round-000002'
            copy_checkpoint(resumed, second_snapshot)
            second = root / 'second'
            copy_checkpoint(second_snapshot, second)
            restore_payload_links(second_snapshot, second)
            before_resume = tree_hashes(resumed)
            append_model_event(second / 'model_requests.jsonl', {**row, 'request_id': str(uuid4())})
            self.assertEqual(len(load_model_events(second)), 3)
            self.assertEqual(tree_hashes(original), before)
            self.assertEqual(tree_hashes(resumed), before_resume)
            self.assertEqual(read_json(second / 'recovery_lineage.json'), [{'parent_attempt_id': 'earlier'}])

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

    def test_comparisons_require_independently_audited_000_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'runs/baseline'
            manifest = make_manifest(root, 'finite_endpoints')
            write_json(run / 'run_config.json', {'mode': 'llm', 'record': {'policy': '000'},
                'runtime_profile': manifest['runtime_profile'], 'code_manifest': code_manifest(root)})
            write_json(run / 'committed.json', {})
            manifest['baseline_evidence'] = {'run_dir': 'runs/baseline', 'committed_sha256': file_hash(run / 'committed.json')}
            result = {'passed': True, 'workload_complete': True, 'policy': '000'}
            with patch('policy_sim.verify.verify_run', return_value=result):
                require_baseline(manifest, root)
            for policy in ('111', None):
                with patch('policy_sim.verify.verify_run', return_value={**result, 'policy': policy}):
                    with self.assertRaises(ExecutionError):
                        require_baseline(manifest, root)

    def test_open_stage_rejects_old_reservations_but_allows_active_requests(self):
        from policy_sim.budget import open_stage_ledger
        from policy_sim.proxy import BudgetError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, auth_path, auth = authorized_baseline(root)
            payload = {**settings_for_purpose(read_json(manifest_path)['runtime_profile']),
                       'messages': [{'role': 'user', 'content': 'offline'}]}
            ledger = open_stage_ledger(root, auth_path, manifest_path, 'finite_baseline')
            first, _ = ledger.reserve(payload)
            second, _ = ledger.reserve(payload)
            self.assertEqual([ledger.records[i]['status'] for i in (first, second)], ['reserved', 'reserved'])
            ledger.finish(first, 200, {'prompt_tokens': 2, 'completion_tokens': 3})
            ledger.finish(second, 200, {'prompt_tokens': 2, 'completion_tokens': 3})
            reopened = open_stage_ledger(root, auth_path, manifest_path, 'finite_baseline')
            reopened.reserve(payload)
            path = authorization_paths(auth, root)['ledger']
            before = path.read_bytes()
            with self.assertRaisesRegex(BudgetError, 'unsettled.*reserved'):
                open_stage_ledger(root, auth_path, manifest_path, 'finite_baseline')
            self.assertEqual(path.read_bytes(), before)

    def test_resume_rejects_old_reservation_before_launch(self):
        from policy_sim.budget import open_stage_ledger
        from policy_sim.proxy import BudgetError
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, auth_path, auth = authorized_baseline(root)
            payload = {**settings_for_purpose(read_json(manifest_path)['runtime_profile']),
                       'messages': [{'role': 'user', 'content': 'offline'}]}
            open_stage_ledger(root, auth_path, manifest_path, 'finite_baseline').reserve(payload)
            control = authorization_paths(auth, root)['control']
            output = make_paused_batch(root, manifest_path, auth_path, auth, control)
            ledger_path = authorization_paths(auth, root)['ledger']
            ledger_before, status_before = ledger_path.read_bytes(), (output / 'batch_status.json').read_bytes()
            attempts_before = (control / 'attempts.jsonl').read_bytes()
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=1)
            with self.assertRaisesRegex(BudgetError, 'unsettled.*reserved'):
                execute_stage(root, manifest_path, auth_path, output, resume=True, runner=runner)
            self.assertFalse(calls)
            self.assertEqual(ledger_path.read_bytes(), ledger_before)
            self.assertEqual((output / 'batch_status.json').read_bytes(), status_before)
            self.assertEqual((control / 'attempts.jsonl').read_bytes(), attempts_before)

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
            registry.append('complete', second, clean_commit=True)
            with self.assertRaises(ExecutionError):
                registry.start('other', 'auth', 1, attempt_scope='authorization')
            registry.start('other', 'auth', 2, attempt_scope='authorization')
            with self.assertRaises(ExecutionError):
                registry.start('third', 'auth', 2, attempt_scope='authorization')
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
            with patch('policy_sim.budget.open_stage_ledger'), \
                    patch('policy_sim.execution.validate_authorization', return_value=auth), \
                    patch('policy_sim.execution.authorization_paths', return_value={'control': root / 'control'}):
                self.assertFalse(execute_stage(root, manifest_path, auth_path, root / 'runs/batch', runner=runner))
            self.assertEqual(len(calls), 1)
            self.assertNotIn('--steps', calls[0])
            status = read_json(root / 'runs/batch/batch_status.json')
            self.assertEqual(status['status'], 'paused')
            self.assertEqual(next(iter(status['runs'].values()))['committed_steps'], 3)

    def test_resume_restores_attempt_then_starts_prepared_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path, auth_path = root / 'manifest.json', root / 'auth.json'
            manifest = make_manifest(root, 'finite_endpoints')
            write_json(manifest_path, manifest)
            auth = {'authorization_id': 'offline', 'max_attempts': len(manifest['runs']), 'manual_resume_allowed': True}
            write_json(auth_path, auth)
            control = root / 'control'
            output = make_paused_batch(root, manifest_path, auth_path, auth, control)
            launched = []
            def runner(command, **kwargs):
                run_id = command[command.index('--run-id') + 1]
                destination = Path(command[command.index('--output') + 1])
                row = read_json(output / 'batch_status.json')['runs'][run_id]
                launched.append((run_id, '--resume' in command, row['committed_steps']))
                if '--resume' not in command:
                    record = next(r for r in manifest['runs'] if r['run_id'] == run_id)
                    make_checkpoint(destination, root, record)
                write_json(destination / 'controller_receipt.json', {'clean_commit': True, 'ray_shutdown': True,
                    'pending_requests': 0, 'committed_steps': 1, 'completion_status': {'complete': True}})
                return SimpleNamespace(returncode=0)
            with patch('policy_sim.budget.open_stage_ledger'), \
                    patch('policy_sim.execution.validate_authorization', return_value=auth), \
                    patch('policy_sim.execution.authorization_paths', return_value={'control': control}), \
                    patch('policy_sim.protocol.require_baseline'), \
                    patch('policy_sim.verify.verify_run', return_value={'passed': True, 'workload_complete': True}):
                self.assertTrue(execute_stage(root, manifest_path, auth_path, output, resume=True, runner=runner))
            self.assertEqual(launched, [(r['run_id'], i == 0, 1 if i == 0 else 0)
                                        for i, r in enumerate(manifest['runs'])])
            self.assertTrue(all(row['status'] == 'complete'
                                for row in read_json(output / 'batch_status.json')['runs'].values()))

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
