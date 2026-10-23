"""Resume the frozen generation runner; retain service interruptions as separate evidence."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
from datetime import datetime, timezone
from pathlib import Path

from . import react_pilot
from .react_report import write_report


def service_error(events: str, stderr: str) -> str | None:
    if 'token_revoked' in stderr:
        return 'token_revoked'
    for line in events.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if event.get('type') not in {'error', 'turn.failed'}:
            continue
        message = str(event.get('message', '')) + str(event.get('error', ''))
        if 'usage limit' in message.lower() or 'usage_limit' in message.lower():
            return 'usage_limit'
    return None


def read_rows(path: Path) -> list[dict]:
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()] if path.exists() else []


def classify(folder: Path) -> str | None:
    def read(name):
        path = folder / name
        return path.read_text(encoding='utf-8') if path.exists() else ''
    return service_error(read('codex-events.jsonl'), read('codex-events.stderr.txt'))


def safe_folder(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError('Evidence path must stay within its run directory')
    return path


def copy_evidence(source: Path, destination: Path, *, allow_links: bool = True, **kwargs) -> None:
    for directory, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            attributes = getattr(path.lstat(), 'st_file_attributes', 0)
            if not allow_links and (path.is_symlink() or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0)):
                raise ValueError('Links are not permitted in an exported website')
            if attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0) and not path.is_symlink():
                raise ValueError('Junction in evidence; refusing to follow an external directory')
    shutil.copytree(source, destination, symlinks=True, **kwargs)


def replaceable_error(row: dict, folder: Path) -> str | None:
    if row.get('model_completed', False) or row.get('model_timed_out', False):
        return None
    return classify(folder)


def recover_run(source: Path, target: Path) -> None:
    source, target = source.resolve(), target.resolve()
    if target.exists() or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError('Choose a new, separate output directory; original evidence is preserved')
    rows = read_rows(source / 'attempts.jsonl')
    if len({r['attempt_id'] for r in rows}) != len(rows):
        raise ValueError('Ambiguous duplicate attempt records')
    decisions = [(row, replaceable_error(row, safe_folder(source, row['attempt_id']))) for row in rows]
    if not any(error for _, error in decisions):
        raise ValueError('No explicit service interruption to recover')
    target.mkdir(parents=True)
    shutil.copy2(source / 'manifest.json', target / 'manifest.json')
    shutil.copy2(source / 'attempts.jsonl', target / 'attempts.previous.jsonl')
    retained, interruptions = [], []
    for row, error in decisions:
        original = safe_folder(source, row['attempt_id'])
        relative = '_service-interruptions/' + source.name + '/' + row['attempt_id'] if error else row['attempt_id']
        destination = safe_folder(target, relative)
        # Original dependencies remain available in the original run. Interrupted
        # sources, events, ZIPs and evaluation artifacts remain reviewable here.
        copy_evidence(original, destination, ignore=(
            lambda directory, names: ['node_modules'] if error and Path(directory) == original / 'workspace' else []))
        if error:
            interruptions.append({**row, 'service_error': error, 'artifact_folder': relative,
                                  'original_run': str(source), 'success': False})
        else:
            retained.append(row)
    for row in read_rows(source / 'service-interruptions.jsonl'):
        relative = row['artifact_folder']
        copy_evidence(safe_folder(source, relative), safe_folder(target, relative))
        interruptions.append(row)
    (target / 'attempts.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in retained), encoding='utf-8')
    (target / 'service-interruptions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in interruptions), encoding='utf-8')
    (target / 'recovery.json').write_text(json.dumps({'source': str(source),
        'created_at': datetime.now(timezone.utc).isoformat(), 'retained_records': len(retained),
        'service_interruption_records': len(interruptions),
        'policy': 'Only explicit service interruptions are replaced with clean independent samples; ordinary failures and timeouts remain.'}, indent=2), encoding='utf-8')
    write_report(retained, target)


def run(args) -> int:
    args.retry_infrastructure = False
    args.limit = 1
    while True:
        rows = read_rows(args.output / 'attempts.jsonl')
        if any(replaceable_error(r, safe_folder(args.output, r['attempt_id'])) for r in rows):
            print('PILOT_STOP retained service interruption requires a new recovery directory', flush=True)
            return 3
        if len(rows) == len(react_pilot.matrix()):
            return 0
        result = react_pilot.run(args)
        if result:
            return result
        updated = read_rows(args.output / 'attempts.jsonl')
        if len(updated) <= len(rows):
            raise ValueError('Runner made no progress')
        row = updated[-1]
        folder = safe_folder(args.output, row['attempt_id'])
        error = replaceable_error(row, folder)
        if error:
            (folder / 'review.json').write_text(json.dumps({'service_error': error,
                'note': 'Generation was interrupted by the service. Any retained site is partial; this is not a completed quality sample.'}, indent=2), encoding='utf-8')
            write_report(updated, args.output)
            print('PILOT_STOP service_error=' + error + '; original events and partial source retained', flush=True)
            return 3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--recover-from', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--playwright-module')
    parser.add_argument('--channel', default='chrome')
    args = parser.parse_args()
    try:
        if args.recover_from:
            recover_run(args.recover_from, args.output)
        if args.prepare_only:
            return 0
        if not args.playwright_module:
            raise ValueError('--playwright-module is required for generation')
        return run(args)
    except (ValueError, OSError) as error:
        print(f'PILOT_STOP {type(error).__name__}: {error}', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
