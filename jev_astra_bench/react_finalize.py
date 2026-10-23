"""Persist an already completed model response after its caller was interrupted."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

from .codex_events import parse_codex_events
from .react_pilot import ROOT, TASK, matrix, file_hash, file_map, dependency_map, source_changes, verify, archive_source
from .react_resume import read_rows, safe_folder, classify
from .react_report import write_report


def finalize(output: Path, attempt: str, playwright: str, channel: str = 'chrome') -> dict:
    output = output.resolve()
    folder = safe_folder(output, attempt)
    rows = read_rows(output / 'attempts.jsonl')
    if any(r['attempt_id'] == attempt for r in rows) or (folder / 'result.json').exists():
        raise ValueError('Attempt already recorded; do not duplicate or overwrite its result')
    cells = {f'{model}-{mode}-r{repeat}': (repeat, model, mode) for repeat, model, mode in matrix()}
    if attempt not in cells:
        raise ValueError('Attempt is not in the approved matrix')
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    if file_map(TASK / 'starter') != manifest['starter'] or file_hash(TASK / 'PROMPT.md') != manifest['prompt_sha256']:
        raise ValueError('Frozen starter or prompt fingerprint changed')
    for name, path in [('runner_sha256', ROOT / 'jev_astra_bench/react_pilot.py'),
                       ('codex_runner_sha256', ROOT / 'jev_astra_bench/codex_runner.py'),
                       ('verifier_sha256', ROOT / 'scripts/react-checks.cjs')]:
        if manifest[name] != file_hash(path):
            raise ValueError('Run source fingerprint changed')
    events = (folder / 'codex-events.jsonl').read_text(encoding='utf-8')
    parsed = parse_codex_events(events.splitlines())
    if not parsed.completed or parsed.malformed_events or classify(folder):
        raise ValueError('Recovery requires a complete, valid model response without a service interruption')
    work = folder / 'workspace'
    before = file_map(work)
    violations = source_changes(TASK / 'starter', work)
    deps = hashlib.sha256(json.dumps(dependency_map(work / 'node_modules'), sort_keys=True).encode()).hexdigest()
    if deps != manifest['dependencies_sha256']:
        violations.append('node_modules')
    artifacts = folder / 'artifacts'
    if artifacts.exists():
        artifacts.rename(folder / f'artifacts.caller-interrupted-{time.time_ns()}')
    if violations:
        verification = {'success': False, 'checks': {'source_scope': False},
                        'failure_reason': 'protected_files_changed', 'violations': violations}
    else:
        try:
            verification = verify(work, artifacts, playwright, channel)
        except (OSError, subprocess.TimeoutExpired) as error:
            verification = {'success': False, 'checks': {'verifier_completed': False},
                            'failure_reason': 'verifier_infrastructure_error', 'error_type': type(error).__name__}
    if file_map(work) != before:
        raise ValueError('External verification changed source; inspect before recording')
    archive_source(work, folder / 'source.zip')
    repeat, model, mode = cells[attempt]
    row = {'attempt_id': attempt, 'model': model, 'mode': mode, 'repeat': repeat,
           'started_at': None, 'reasoning_effort': manifest['reasoning_effort'],
           'duration_s': None, 'model_duration_s': None, 'jev_duration_s': None,
           'input_tokens': parsed.input_tokens, 'cached_input_tokens': parsed.cached_input_tokens,
           'output_tokens': parsed.output_tokens, 'tool_calls': parsed.tool_calls,
           'model_completed': True, 'model_exit_code': None, 'model_timed_out': False,
           'jev_choice': None, 'jev_input_tokens': None if mode == 'jev_offload' else 0,
           'verification': verification, 'success': verification['success'],
           'failure_reason': verification.get('failure_reason') or (None if verification['success'] else 'functional_checks_failed'),
           'prompt_sha256': manifest['prompt_sha256'], 'source_sha256': before,
           'caller_recovery': {'completion_evidence': 'Retained turn.completed event with token usage',
                               'missing_fields': ['started_at', 'duration_s', 'model_duration_s', 'model_exit_code', 'jev_choice', 'jev_input_tokens'],
                               'note': 'Caller stopped after the response finished. No generation retry or source edits. Timing, process exit and Jev metadata were not persisted and remain unknown.'}}
    (folder / 'result.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
    with (output / 'attempts.jsonl').open('a', encoding='utf-8') as sink:
        sink.write(json.dumps(row) + '\n')
    (folder / 'review.json').write_text(json.dumps({'note': row['caller_recovery']['note']}, indent=2), encoding='utf-8')
    write_report(rows + [row], output)
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--playwright-module', required=True)
    args = parser.parse_args()
    result = finalize(args.output, args.attempt, args.playwright_module)
    print('RECOVERED_COMPLETED_ATTEMPT', result['attempt_id'], 'success=' + str(result['success']))
