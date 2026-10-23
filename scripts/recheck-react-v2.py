"""Preserve v1 measurements and reevaluate unchanged sources with the corrected evaluator."""
from __future__ import annotations
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_astra_bench.react_pilot import verify, file_map, file_hash, ROOT
from jev_astra_bench.react_report import write_report
from jev_astra_bench.react_resume import read_rows, safe_folder, copy_evidence, replaceable_error

source = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
playwright = sys.argv[3]
revision = int(sys.argv[5]) if len(sys.argv) > 5 else 2
if target.exists():
    raise SystemExit('Use an empty target to preserve measurements')
target.mkdir(parents=True)
old_manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
manifest = json.loads(Path(sys.argv[4]).read_text(encoding='utf-8')) if len(sys.argv) > 4 else dict(old_manifest)
changed = {key for key in old_manifest.keys() | manifest.keys() if old_manifest.get(key) != manifest.get(key)}
if changed - {'browser_runtime', 'verifier_sha256'}:
    raise SystemExit('Generation inputs changed; refusing to combine conditions: ' + ', '.join(sorted(changed)))
if manifest['runner_sha256'] != file_hash(ROOT / 'jev_astra_bench/react_pilot.py'):
    raise SystemExit('Generation runner changed; explicit migration review required')
if manifest['codex_runner_sha256'] != file_hash(ROOT / 'jev_astra_bench/codex_runner.py'):
    raise SystemExit('Model invocation changed; generation inputs cannot be mixed')
manifest['verifier_sha256'] = file_hash(ROOT / 'scripts/react-checks.cjs')
(target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
history_name = source.name
shutil.copy2(source / 'manifest.json', target / ('manifest.previous-' + history_name + '.json'))
rows = [json.loads(s) for s in (source / 'attempts.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
for row in rows:
    attempt = row['attempt_id']
    folder = target / attempt
    copy_evidence(safe_folder(source, attempt), folder, ignore=lambda directory, names: ['artifacts'] if Path(directory) == source / attempt else [])
    history = folder / 'evaluation-history' / history_name
    history.mkdir(parents=True)
    if (source / attempt / 'artifacts').exists():
        copy_evidence(source / attempt / 'artifacts', history / 'artifacts')
    shutil.copy2(folder / 'result.json', history / 'result.json')
    before = file_map(folder / 'workspace')
    if row.get('source_sha256') and before != row['source_sha256']:
        raise SystemExit('Original source fingerprint differs; refusing to reclassify changed evidence')
    original_verification = row.get('verification', {})
    protected_failure = (row.get('failure_reason') == 'protected_files_changed'
                         or original_verification.get('failure_reason') == 'protected_files_changed'
                         or original_verification.get('checks', {}).get('source_scope') is False)
    if protected_failure:
        verified = dict(original_verification)
        verified['success'] = False
        verified['failure_reason'] = 'protected_files_changed'
        row['browser_recheck_skipped'] = 'Immutable source-scope failure; no candidate build was executed'
        if (source / attempt / 'artifacts').exists():
            copy_evidence(source / attempt / 'artifacts', folder / 'artifacts')
        else:
            (folder / 'artifacts').mkdir()
            (folder / 'artifacts/verification.json').write_text(json.dumps(verified, indent=2), encoding='utf-8')
    else:
        verified = verify(folder / 'workspace', folder / 'artifacts', playwright, 'chrome')
    if file_map(folder / 'workspace') != before:
        raise SystemExit('Recheck changed source unexpectedly')
    row['verification'] = verified
    row['functional_success'] = verified['success']
    completion_retained = row.get('caller_recovery', {}).get('completion_evidence') == 'Retained turn.completed event with token usage'
    row['success'] = verified['success'] and row['model_completed'] and (row['model_exit_code'] == 0 or completion_retained)
    row['failure_reason'] = None if row['success'] else (verified.get('failure_reason') or 'functional_checks_failed')
    if row.get('model_timed_out'):
        row['failure_reason'] = 'model_timeout'
    elif not row['model_completed']:
        row['failure_reason'] = 'model_incomplete'
        service = replaceable_error(row, folder)
        if service:
            row['service_error'] = service
            row['failure_reason'] = service
    row['evaluation_revision'] = revision
    row['browser_runtime'] = manifest['browser_runtime']
    row['original_measurement'] = str(source / attempt / 'result.json')
    row['source_unchanged_during_recheck'] = True
    (folder / 'result.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
    print('RECHECK', revision, attempt, 'functional_success=' + str(verified['success']), flush=True)
(target / 'attempts.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
archive = source / 'service-interruptions.jsonl'
if archive.exists():
    shutil.copy2(archive, target / archive.name)
    for row in read_rows(archive):
        copy_evidence(safe_folder(source, row['artifact_folder']), safe_folder(target, row['artifact_folder']))
(target / 'EVALUATOR-REVISION.md').write_text(
    '# Evaluator correction and runtime verification\n\nPreviously generated sources were copied without edits and rechecked under one evaluator and browser runtime. '
    'The generation prompt, starter, dependencies, model runner, effort and time budget did not change. '
    'The evaluator now waits for menu/dialog exit animations and scrolls through content before full-page screenshots. '
    'Original result JSON, evaluator artifacts and manifest are retained in evaluation-history and previous-manifest files; the original run directory remains untouched. '
    'Any browser runtime patch difference is recorded in both manifests. '
    'Generation durations and token usage are the original values. Recheck time is not included in those original measurements.\n', encoding='utf-8')
if revision >= 3:
    with (target / 'EVALUATOR-REVISION.md').open('a', encoding='utf-8') as sink:
        sink.write('\nRevision 3 accepts browser-chrome focus for a native modal dialog while rejecting focus into background page controls. '
                   'The focus and video tests reload the page independently to avoid cascading failures. '
                   'The native-dialog behavior is documented by W3C: https://www.w3.org/WAI/WCAG22/Techniques/html/H102 . '
                   'The source matrix, generation budget, ordinary failures, timeout records and archived service interruptions are retained.\n')
write_report(rows, target)
