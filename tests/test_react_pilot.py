from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_astra_bench.react_pilot import matrix, load_key, source_changes, check_resume, is_infrastructure_failure
from jev_astra_bench.react_report import summarize
from jev_astra_bench.codex_runner import CodexConfig, build_command, model_environment
from jev_astra_bench.codex_runner import CodexAttempt
from jev_astra_bench.codex_events import ParsedCodexEvents


class ReactPilotTests(unittest.TestCase):
    def test_timeout_or_admitted_usage_is_never_a_retryable_transport_failure(self):
        parsed = ParsedCodexEvents(None, None, None, 0, 0, False)
        self.assertTrue(is_infrastructure_failure(CodexAttempt(parsed, 1, 1, False, ())))
        self.assertFalse(is_infrastructure_failure(CodexAttempt(parsed, 900, 1, True, ())))
        admitted = ParsedCodexEvents(None, 123, 0, 0, 0, False)
        self.assertFalse(is_infrastructure_failure(CodexAttempt(admitted, 1, 1, False, ())))

    def test_matrix_has_twenty_unique_attempts_and_balanced_order(self):
        cells = matrix()
        self.assertEqual(len(cells), 20)
        self.assertEqual(len(set(cells)), 20)
        groups = {(model, mode) for _, model, mode in cells}
        self.assertEqual(len(groups), 4)
        for model, mode in groups:
            self.assertEqual(sum((m, k) == (model, mode) for _, m, k in cells), 5)
        self.assertEqual(len({cells[i * 4][1:] for i in range(4)}), 4)

    def test_key_loads_bare_file_without_logging_or_changing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('test-secret-value\n', encoding='utf-8')
            self.assertEqual(load_key(path), 'test-secret-value')
            self.assertEqual(path.read_text(), 'test-secret-value\n')
            path.write_text('TYPESAFE_API_KEY="test-secret-value"\n', encoding='utf-8')
            self.assertEqual(load_key(path), 'test-secret-value')

    def test_secret_environment_is_not_forwarded_to_model(self):
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'secret', 'OPENAI_API_KEY': 'other', 'BENCH_TOKEN': 't'}):
            env = model_environment(True)
        self.assertNotIn('TYPESAFE_API_KEY', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('BENCH_TOKEN', env)
        self.assertIn('PATH', env)

    def test_pilot_isolation_preserves_requested_model(self):
        cmd = build_command('work', Path('fixture'), CodexConfig(model='gpt-6.1-sol', isolated=True))
        self.assertEqual(cmd[cmd.index('-m') + 1], 'gpt-6.1-sol')
        self.assertIn('--ignore-user-config', cmd)
        self.assertIn('project_doc_max_bytes=0', cmd)
        self.assertIn('web_search="disabled"', cmd)
        if os.name == 'nt':
            self.assertIn('windows.sandbox="unelevated"', cmd)

    def test_source_scope_detects_protected_file_tampering_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, work = root / 'base', root / 'work'
            for folder in (base, work):
                (folder / 'src').mkdir(parents=True)
                (folder / 'src' / 'App.jsx').write_text('baseline')
                (folder / 'package.json').write_text('{}')
            (work / 'src' / 'App.jsx').write_text('changed')
            self.assertEqual(source_changes(base, work), [])
            (work / 'package.json').write_text('{"scripts":{"build":"echo fake"}}')
            self.assertEqual(source_changes(base, work), ['package.json'])

    def test_resume_rejects_changed_prompt_or_simulated_live_mix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            expected = {'prompt_sha256': 'a', 'simulate': False}
            check_resume(path, expected)
            path.write_text(json.dumps(expected))
            check_resume(path, expected)
            with self.assertRaises(ValueError):
                check_resume(path, {**expected, 'prompt_sha256': 'b'})
            with self.assertRaises(ValueError):
                check_resume(path, {**expected, 'simulate': True})

    def test_summary_keeps_failed_attempts_and_never_merges_models(self):
        rows = [
            {'model': 'gpt-6-astra', 'mode': 'baseline', 'success': True, 'duration_s': 10},
            {'model': 'gpt-6-astra', 'mode': 'baseline', 'success': False, 'duration_s': 30},
            {'model': 'gpt-6.1-sol', 'mode': 'baseline', 'success': True, 'duration_s': 4},
        ]
        report = summarize(rows)
        self.assertEqual(report['records'], 3)
        astra = report['groups']['gpt-6-astra/baseline']
        self.assertEqual(astra['attempts'], 2)
        self.assertEqual(astra['successes'], 1)
        self.assertEqual(astra['median_duration_s'], 20)
        self.assertEqual(astra['max_duration_s'], 30)
        self.assertIsNone(astra['estimated_cost_usd'])

    def test_incomplete_service_run_is_visible_but_not_a_completed_model_failure(self):
        report = summarize([{'model': 'gpt-6-astra', 'mode': 'baseline', 'success': False,
                             'duration_s': 831, 'model_completed': False, 'service_error': 'usage_limit'}])
        group = report['groups']['gpt-6-astra/baseline']
        self.assertEqual(group['attempts'], 1)
        self.assertEqual(group['service_interruptions'], 1)
        self.assertEqual(group['completed_attempts'], 0)
        self.assertEqual(report['status'], 'incomplete')


if __name__ == '__main__':
    unittest.main()
