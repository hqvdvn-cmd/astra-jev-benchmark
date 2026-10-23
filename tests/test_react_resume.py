from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jev_astra_bench.react_resume import service_error, recover_run, replaceable_error, copy_evidence
from jev_astra_bench.react_pilot import matrix
from jev_astra_bench.react_report import summarize, write_report


class RecoveryTests(unittest.TestCase):
    def test_only_explicit_service_errors_are_replaceable(self):
        self.assertIsNone(service_error('{"type":"item.completed","item":{"text":"usage limit"}}', ''))
        self.assertEqual(service_error('{"type":"error","message":"You have hit your usage limit"}', ''), 'usage_limit')
        self.assertEqual(service_error('', 'HTTP 401 token_revoked'), 'token_revoked')
        self.assertIsNone(service_error('{"type":"turn.failed","error":{"message":"invalid patch"}}', ''))

    def test_recovery_keeps_ordinary_failure_and_preserves_service_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'original', root / 'resumed'
            source.mkdir()
            (source / 'manifest.json').write_text('{}')
            rows = []
            for attempt, error in [('ordinary', False), ('interrupted', True)]:
                folder = source / attempt
                (folder / 'workspace/src').mkdir(parents=True)
                (folder / 'workspace/src/App.jsx').write_text(attempt)
                (folder / 'workspace/node_modules').mkdir()
                (folder / 'workspace/node_modules/fixture').write_text('dependency')
                (folder / 'codex-events.jsonl').write_text('{"type":"error","message":"usage limit"}' if error else '')
                row = {'attempt_id': attempt, 'model': 'gpt-6-astra', 'mode': 'baseline', 'repeat': 1,
                       'duration_s': 1, 'success': False, 'model_completed': not error}
                (folder / 'result.json').write_text(json.dumps(row))
                rows.append(row)
            original = ''.join(json.dumps(row) + '\n' for row in rows)
            (source / 'attempts.jsonl').write_text(original)
            recover_run(source, target)
            self.assertEqual((source / 'attempts.jsonl').read_text(), original)
            retained = [json.loads(s) for s in (target / 'attempts.jsonl').read_text().splitlines()]
            self.assertEqual([r['attempt_id'] for r in retained], ['ordinary'])
            archived = json.loads((target / 'service-interruptions.jsonl').read_text())
            self.assertEqual(archived['service_error'], 'usage_limit')
            self.assertEqual((target / archived['artifact_folder'] / 'workspace/src/App.jsx').read_text(), 'interrupted')
            self.assertTrue((target / 'ordinary/workspace/node_modules/fixture').exists())
            self.assertFalse((target / archived['artifact_folder'] / 'workspace/node_modules').exists())
            with self.assertRaises(ValueError):
                recover_run(source, target)

    def test_archived_interruptions_are_counted_without_occupying_sample_cells(self):
        rows = [{'attempt_id': f'{model}-{mode}-{repeat}', 'model': model, 'mode': mode, 'repeat': repeat,
                 'duration_s': 10, 'success': True} for repeat, model, mode in matrix()]
        interrupted = [{'model': 'gpt-6-astra', 'mode': 'baseline', 'duration_s': 99,
                        'success': False, 'service_error': 'usage_limit'}]
        report = summarize(rows, interrupted)
        self.assertEqual(report['records'], 20)
        self.assertEqual(report['service_interruption_records'], 1)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['groups']['gpt-6-astra/baseline']['median_duration_s'], 10)
        self.assertEqual(report['groups']['gpt-6-astra/baseline']['service_interruptions'], 1)

    def test_timeout_or_completed_sample_is_not_replaced_for_an_incidental_service_log(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'codex-events.jsonl').write_text('{"type":"error","message":"usage limit"}')
            self.assertIsNone(replaceable_error({'model_completed': True}, folder))
            self.assertIsNone(replaceable_error({'model_completed': False, 'model_timed_out': True}, folder))

    def test_recovery_preserves_links_and_rejects_junctions(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / 'source', Path(directory) / 'target'
            source.mkdir()
            (source / 'nested').mkdir()
            with patch('jev_astra_bench.react_resume.shutil.copytree') as copy:
                copy_evidence(source, target)
                self.assertTrue(copy.call_args.kwargs['symlinks'])
            with patch.object(Path, 'lstat', return_value=type('Junction', (), {'st_file_attributes': stat.FILE_ATTRIBUTE_REPARSE_POINT})()), patch.object(Path, 'is_symlink', return_value=False):
                with self.assertRaises(ValueError):
                    copy_evidence(source, target)

    def test_timeout_stays_in_report_success_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = [{'attempt_id': f'sample-{i}', 'model': 'gpt-6-astra', 'mode': 'baseline', 'repeat': i,
                     'duration_s': 10, 'success': i < 5, 'model_completed': i < 5, 'model_timed_out': i == 5}
                    for i in range(1, 6)]
            write_report(rows, Path(directory))
            self.assertIn('| gpt-6-astra/baseline | 4/5 |', (Path(directory) / 'REPORT.md').read_text())


if __name__ == '__main__':
    unittest.main()
