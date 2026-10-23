import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_astra_bench.react_finalize import finalize
from jev_astra_bench.react_report import write_report


class CompletedRecoveryTests(unittest.TestCase):
    def test_complete_response_is_not_regenerated_and_missing_metrics_stay_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            attempt = 'gpt-6.1-sol-jev_offload-r2'
            folder = output / attempt
            (folder / 'workspace').mkdir(parents=True)
            (folder / 'codex-events.jsonl').write_text(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 123, 'output_tokens': 45}}))
            (output / 'manifest.json').write_text(json.dumps({'runner_sha256': 'hash', 'codex_runner_sha256': 'hash', 'verifier_sha256': 'hash',
                'dependencies_sha256': 'different', 'reasoning_effort': 'xhigh', 'prompt_sha256': 'hash', 'starter': {}}))
            with patch('jev_astra_bench.react_finalize.file_hash', return_value='hash'), patch('jev_astra_bench.react_finalize.file_map', return_value={}), patch('jev_astra_bench.react_finalize.source_changes', return_value=[]), patch('jev_astra_bench.react_finalize.dependency_map', return_value={}), patch('jev_astra_bench.react_finalize.archive_source'), patch('jev_astra_bench.react_finalize.verify') as verifier:
                row = finalize(output, attempt, 'unused')
                verifier.assert_not_called()  # Dependency violation must not execute candidate code.
            self.assertTrue(row['model_completed'])
            self.assertEqual(row['input_tokens'], 123)
            self.assertIsNone(row['duration_s'])
            self.assertIsNone(row['model_exit_code'])
            self.assertFalse(row['success'])
            self.assertEqual(row['failure_reason'], 'protected_files_changed')
            with self.assertRaises(ValueError):
                finalize(output, attempt, 'unused')

    def test_unknown_timing_is_not_zero_or_a_partial_group_median(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'attempt_id': f'sample-{i}', 'model': 'gpt-6.1-sol', 'mode': 'jev_offload', 'repeat': i,
                     'duration_s': value, 'success': True} for i, value in enumerate([10, None], 1)]
            output = Path(directory)
            write_report(rows, output)
            report = json.loads((output / 'report.json').read_text())
            group = report['groups']['gpt-6.1-sol/jev_offload']
            self.assertIsNone(group['median_duration_s'])
            self.assertEqual(group['missing_timing_records'], 1)
            self.assertIn('timing unavailable', (output / 'gallery.html').read_text())

    def test_verifier_timeout_is_recorded_and_old_artifact_archives_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            attempt = 'gpt-6-astra-baseline-r2'
            folder = output / attempt
            (folder / 'workspace').mkdir(parents=True)
            (folder / 'artifacts').mkdir()
            (folder / 'artifacts/original').write_text('partial check')
            (folder / 'artifacts.caller-interrupted').mkdir()
            (folder / 'artifacts.caller-interrupted/older').write_text('prior evidence')
            (folder / 'codex-events.jsonl').write_text('{"type":"turn.completed","usage":{"input_tokens":1}}')
            manifest = {'runner_sha256': 'hash', 'codex_runner_sha256': 'hash', 'verifier_sha256': 'hash',
                        'dependencies_sha256': hashlib.sha256(b'{}').hexdigest(),
                        'reasoning_effort': 'xhigh', 'prompt_sha256': 'hash', 'starter': {}}
            (output / 'manifest.json').write_text(json.dumps(manifest))
            with patch('jev_astra_bench.react_finalize.file_hash', return_value='hash'), patch('jev_astra_bench.react_finalize.file_map', return_value={}), patch('jev_astra_bench.react_finalize.source_changes', return_value=[]), patch('jev_astra_bench.react_finalize.dependency_map', return_value={}), patch('jev_astra_bench.react_finalize.archive_source'), patch('jev_astra_bench.react_finalize.verify', side_effect=subprocess.TimeoutExpired('browser', 180)):
                row = finalize(output, attempt, 'unused')
            self.assertEqual(row['failure_reason'], 'verifier_infrastructure_error')
            self.assertTrue((folder / 'artifacts.caller-interrupted/older').exists())
            self.assertEqual(len(list(folder.glob('artifacts.caller-interrupted-*/original'))), 1)
            self.assertTrue((folder / 'result.json').exists())
