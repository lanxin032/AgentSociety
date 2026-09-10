import importlib.util
import json
from pathlib import Path
import shutil
import uuid
import unittest
from unittest.mock import patch
from policy_v3.spec import SPEC_VERSION

from policy_v3.execution import (AttemptRegistry, ExecutionError, chunk_commands, controller_lock,
    digest, file_hash, load_manifest, quote, source_hash, validate_authorization)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / ('test-v3-execution-' + uuid.uuid4().hex)
        self.root.mkdir()
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps({'runs': [{'run_id': 'd0', 'stage': 'diagnostic', 'horizon': 30}]}))

    def tearDown(self):
        assert self.root.resolve().parent == Path(__file__).resolve().parents[1]
        assert self.root.name.startswith('test-v3-execution-')
        shutil.rmtree(self.root)

    def authorization(self):
        return {'explicit_stage_authorization': True, 'manifest_sha256': file_hash(self.manifest),
            'stage': 'diagnostic', 'model': 'deepseek-v4-flash', 'source_sha256': source_hash(self.root),
            'authorization_id': 'user-phase-1', 'user_evidence_reference': 'user-message-42',
            'approval_reference': 'user-message-42', 'approved': True,
            'price_version': 'verified', 'api_ledger_path': str(self.root / 'runs/api-smoke-budget-20260909.json'),
            'baseline_prefix_sha256': 'a' * 64, 'baseline_requests': 16, 'baseline_accounted_rmb': 0.1,
            'incremental_request_cap': 100, 'max_attempts': 6, 'input_rmb_per_million': 1,
            'output_rmb_per_million': 1, 'incremental_rmb_cap': 5}

    def test_authorization_binds_phase_code_manifest_and_price(self):
        auth = self.authorization()
        validate_authorization(auth, self.manifest, 'diagnostic', self.root)
        for field, value in [('stage', 'pilot'), ('model', 'other'), ('source_sha256', 'bad'),
                             ('manifest_sha256', 'bad'), ('incremental_request_cap', 0), ('max_attempts', 851),
                             ('input_rmb_per_million', 0), ('explicit_stage_authorization', False)]:
            with self.subTest(field=field), self.assertRaises(ExecutionError):
                validate_authorization({**auth, field: value}, self.manifest, 'diagnostic', self.root)

    def test_registry_fsync_and_tamper(self):
        registry = AttemptRegistry(self.root / 'attempts.jsonl')
        import os
        with patch('policy_v3.execution.os.fsync', wraps=os.fsync) as sync:
            aid = registry.start('d0', 'user')
            registry.append('checkpoint', aid, clean_commit=True, committed_steps=5)
            registry.append('complete', aid, clean_commit=True, committed_steps=30)
            self.assertEqual(sync.call_count, 6)
        self.assertEqual(len(AttemptRegistry(registry.path).events), 3)
        registry.path.write_text(registry.path.read_text().replace('d0', 'd1'))
        with self.assertRaises(ExecutionError):
            AttemptRegistry(registry.path)

    def test_torn_tail_fail_closed(self):
        p = self.root / 'attempts.jsonl'
        p.write_text('{')
        with self.assertRaises(ExecutionError):
            AttemptRegistry(p)

    def test_whole_event_truncation_detected_by_durable_head(self):
        r = AttemptRegistry(self.root / 'registry.jsonl')
        aid = r.start('d0', 'phase')
        r.append('checkpoint', aid, clean_commit=True, committed_steps=5)
        first = r.path.read_bytes().splitlines(keepends=True)[0]
        r.path.write_bytes(first)
        with self.assertRaises(ExecutionError):
            AttemptRegistry(r.path)

    def test_chunk_resume_is_one_attempt(self):
        commands = chunk_commands(self.root, self.manifest, {'run_id': 'd0', 'horizon': 13}, 'scripted', self.root / 'd0', 5)
        self.assertEqual(len(commands), 3)
        self.assertEqual([c[c.index('--steps') + 1] for c in commands], ['5', '5', '3'])
        self.assertNotIn('--resume', commands[0])
        self.assertIn('--resume', commands[1])
        r = AttemptRegistry(self.root / 'registry.jsonl')
        aid = r.start('d0', 'phase')
        for step in (5, 10):
            r.append('checkpoint', aid, clean_commit=True, committed_steps=step)
        r.append('complete', aid, committed_steps=13)
        self.assertEqual(sum(e['kind'] == 'start' for e in r.events), 1)
        remaining = chunk_commands(self.root, self.manifest, {'run_id': 'd0', 'horizon': 13}, 'llm', self.root / 'd0',
                                   5, start_step=5, attempt_id=aid)
        self.assertEqual(len(remaining), 2)
        self.assertIn('--resume', remaining[0])
        self.assertEqual(remaining[0][-2:], ['--attempt-id', aid])

    def test_attempt_bindings_survive_checkpoint_and_running_is_not_clean(self):
        r = AttemptRegistry(self.root / 'registry.jsonl')
        aid = r.start('d0', 'phase', output_path=str(self.root / 'd0'), manifest_sha256='hash', stage='diagnostic')
        r.append('running', aid, committed_steps=0)
        r.append('checkpoint', aid, clean_commit=True, committed_steps=5)
        prior = r.for_run('d0')
        self.assertEqual(prior['output_path'], str(self.root / 'd0'))
        self.assertEqual(prior['manifest_sha256'], 'hash')
        self.assertEqual(prior['attempt_id'], aid)
        r.append('running', aid, committed_steps=5)
        self.assertEqual(r.for_run('d0')['kind'], 'running')

    def test_only_technical_retry_and_eight_retry_cap(self):
        r = AttemptRegistry(self.root / 'registry.jsonl')
        aid = r.start('d0', 'phase')
        with self.assertRaises(ExecutionError):
            r.start('d0', 'phase')
        r.append('technical_failure', aid, reason='transport')
        for _ in range(8):
            aid = r.start('d0', 'phase')
            r.append('technical_failure', aid, reason='transport')
        with self.assertRaises(ExecutionError):
            r.start('d0', 'phase')

    def test_total_850_cap_across_authorizations(self):
        r = AttemptRegistry(self.root / 'registry.jsonl')
        # Build a valid prior chain without 850 filesystem flushes in this cap test.
        for i in range(850):
            event = {'kind': 'start', 'attempt_id': str(i), 'run_id': str(i), 'authorization_id': 'old',
                     'previous': r.events[-1]['sha256'] if r.events else '0' * 64}
            event['sha256'] = digest(event)
            r.events.append(event)
        with self.assertRaises(ExecutionError):
            r.start('newrun', 'new-authorization')

    def test_unclean_checkpoint_and_lock_fail_closed(self):
        r = AttemptRegistry(self.root / 'registry.jsonl')
        aid = r.start('d0', 'phase')
        with self.assertRaises(ExecutionError):
            r.append('checkpoint', aid, clean_commit=False)
        with controller_lock(self.root / 'controller.lock'):
            with self.assertRaises(ExecutionError):
                with controller_lock(self.root / 'controller.lock'):
                    pass

    def test_quote_does_not_call_legacy_or_scripted_calibrated(self):
        runs = [{'horizon': 30}]
        legacy = {'version': '1.2', 'mode': 'llm', 'stage': 'pilot', 'committed_steps': 5, 'requests': 10, 'elapsed_seconds': 20}
        self.assertEqual(quote(runs, [legacy])['status'], 'no_measurement')
        current = {**legacy, 'version': SPEC_VERSION, 'measured_rounds': 5}
        q = quote(runs, [current])
        self.assertEqual(q['estimated_requests_with_25pct'], 75)
        self.assertEqual(q['version'], SPEC_VERSION)
        self.assertFalse(q['authorizes_execution'])
        self.assertEqual(quote(runs, [{**current, 'mode': 'scripted'}])['status'], 'no_measurement')

    def test_quote_excludes_old_v3_measurements_from_current_version(self):
        runs = [{'horizon': 30}]
        for version in ('3', '3.0', 'v3', 'policy-v3-3.0'):
            receipt = {'version': version, 'mode': 'llm', 'stage': 'diagnostic',
                       'measured_rounds': 5, 'requests': 10, 'elapsed_seconds': 20}
            with self.subTest(version=version):
                result = quote(runs, [receipt])
                self.assertEqual(result['status'], 'no_measurement')
                self.assertEqual(result['measurement_count'], 0)
                self.assertEqual(result['legacy_receipts_excluded'], 1)
                self.assertIsNone(result['estimated_requests_with_25pct'])
                self.assertIsNone(result['estimated_seconds_with_25pct'])

    def test_scripted_dryrun_never_uses_api_or_production_registry(self):
        script = Path(__file__).resolve().parents[1] / 'tools/run_v3_batch.py'
        spec = importlib.util.spec_from_file_location('v3_batch_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = self.root / 'dryrun'
        with patch('sys.argv', [str(script), '--manifest', str(self.manifest), '--stage', 'diagnostic', '--output', str(output)]), \
             patch.object(module, 'AttemptRegistry', side_effect=AssertionError('registry touched')), \
             patch.object(module.subprocess, 'run', side_effect=AssertionError('runtime called')):
            module.main()
        self.assertTrue((output / 'stage_review.json').is_file())

    def test_batch_resume_same_attempt_from_clean_checkpoint(self):
        script = Path(__file__).resolve().parents[1] / 'tools/run_v3_batch.py'
        spec = importlib.util.spec_from_file_location('v3_batch_resume_test', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = self.root / 'batch'
        argv = [str(script), '--manifest', str(self.manifest), '--stage', 'diagnostic', '--output', str(output), '--execute']
        calls = []
        def fake_runtime(command, **kwargs):
            calls.append(command)
            target = Path(command[command.index('--output') + 1])
            target.mkdir(exist_ok=True)
            path = target / 'controller_receipt.json'
            prior = json.loads(path.read_text())['committed_steps'] if path.exists() else 0
            step = prior + int(command[command.index('--steps') + 1])
            path.write_text(json.dumps({'run_id': 'd0', 'clean_commit': True, 'committed_steps': step,
                                        'status': 'complete' if step == 30 else 'checkpoint'}))
            return type('Result', (), {'returncode': 0})()
        original = module.chunk_commands
        # Simulate an orderly controller pause after its first committed chunk.
        with patch('sys.argv', argv), patch.object(module.subprocess, 'run', side_effect=fake_runtime), \
             patch.object(module, 'chunk_commands', side_effect=lambda *a, **k: original(*a, **k)[:1]):
            module.main()
        with patch('sys.argv', argv + ['--resume-batch']), patch.object(module.subprocess, 'run', side_effect=fake_runtime):
            module.main()
        registry = AttemptRegistry(output / 'scripted_control/attempts.jsonl')
        self.assertEqual(sum(e['kind'] == 'start' for e in registry.events), 1)
        self.assertEqual(registry.for_run('d0')['kind'], 'complete')
        self.assertEqual(len(calls), 6)
        with patch('sys.argv', argv + ['--resume-batch']), patch.object(module.subprocess, 'run', side_effect=AssertionError('complete run repeated')):
            module.main()


if __name__ == '__main__':
    unittest.main()
