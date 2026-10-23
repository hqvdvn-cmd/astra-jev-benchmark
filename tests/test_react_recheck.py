import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jev_astra_bench.react_pilot import ROOT, file_hash, file_map


class RecheckBoundaryTests(unittest.TestCase):
    def test_protected_failure_is_retained_without_running_candidate_build(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'original', Path(directory) / 'rechecked'
            attempt = 'gpt-6-astra-baseline-r1'
            folder = source / attempt
            (folder / 'workspace/src').mkdir(parents=True)
            (folder / 'workspace/src/App.jsx').write_text('candidate')
            (folder / 'workspace/package.json').write_text('protected file was changed')
            manifest = {'runner_sha256': file_hash(ROOT / 'jev_astra_bench/react_pilot.py'),
                        'codex_runner_sha256': file_hash(ROOT / 'jev_astra_bench/codex_runner.py'),
                        'verifier_sha256': file_hash(ROOT / 'scripts/react-checks.cjs'), 'browser_runtime': {}}
            (source / 'manifest.json').write_text(json.dumps(manifest))
            row = {'attempt_id': attempt, 'model': 'gpt-6-astra', 'mode': 'baseline', 'repeat': 1,
                   'duration_s': 1, 'model_completed': True, 'model_exit_code': 0, 'success': False,
                   'failure_reason': 'protected_files_changed',
                   'verification': {'success': False, 'checks': {'source_scope': False},
                                    'failure_reason': 'protected_files_changed'},
                   'source_sha256': file_map(folder / 'workspace')}
            (folder / 'result.json').write_text(json.dumps(row))
            (source / 'attempts.jsonl').write_text(json.dumps(row) + '\n')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/recheck-react-v2.py'),
                                     str(source), str(target), 'no browser module should be loaded'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads((target / attempt / 'result.json').read_text())
            self.assertFalse(updated['success'])
            self.assertEqual(updated['failure_reason'], 'protected_files_changed')
            self.assertIn('no candidate build', updated['browser_recheck_skipped'])
            self.assertFalse((target / attempt / 'artifacts/build.txt').exists())
            self.assertEqual((source / 'attempts.jsonl').read_text(), json.dumps(row) + '\n')
