"""Export reviewable site outputs; omit credentials and raw model events."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import stat
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_astra_bench.react_report import write_report
from jev_astra_bench.react_resume import read_rows, safe_folder, copy_evidence
from jev_astra_bench.react_export import export_source_archive

parser = argparse.ArgumentParser()
parser.add_argument('--run', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--partial', action='store_true', help='Explicitly export an incomplete pilot with its current status')
args = parser.parse_args()
rows = read_rows(args.run / 'attempts.jsonl')
if len({r['attempt_id'] for r in rows}) != len(rows):
    raise SystemExit('Duplicate active attempt records')
write_report(rows, args.run)
report = json.loads((args.run / 'report.json').read_text(encoding='utf-8'))
if report['status'] != 'complete' and not args.partial:
    raise SystemExit('Pilot is incomplete; use --partial for a clearly marked interim export')
if args.output.exists():
    raise SystemExit('Choose a new export directory to preserve prior deliverables')
args.output.mkdir(parents=True)
for name in ['REPORT.md', 'report.json', 'manifest.json', 'gallery.html']:
    shutil.copy2(args.run / name, args.output / name)
for row in rows + report.get('service_interrupted_attempts', []):
    attempt = row.get('artifact_folder', row['attempt_id'])
    source = safe_folder(args.run, attempt)
    target = safe_folder(args.output, attempt)
    (target / 'artifacts').mkdir(parents=True)
    if (source / 'source.zip').is_symlink():
        raise SystemExit('Source ZIP must be an ordinary file')
    source_record = export_source_archive(source / 'source.zip', target / 'source.zip')
    (target / 'source-export.json').write_text(json.dumps(source_record, indent=2), encoding='utf-8')
    for path in (source / 'artifacts').glob('*'):
        if path.is_file() and not path.is_symlink() and path.suffix in {'.png', '.webm', '.json'}:
            shutil.copy2(path, target / 'artifacts' / path.name)
    dist = source / 'workspace/dist'
    attributes = getattr(dist.lstat(), 'st_file_attributes', 0) if dist.exists() else 0
    if dist.is_dir() and not dist.is_symlink() and not attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
        copy_evidence(dist, target / 'site', allow_links=False)
# Each unchanged build receives its own loopback origin so absolute assets and
# nested CSS/module requests work without rewriting generated files.
server = Path(__file__).with_name('serve-react-results.py')
shutil.copy2(server, args.output / server.name)
shutil.copy2(Path(__file__).resolve().parents[1] / 'tasks/react-site-001/PROMPT.md', args.output / 'PROMPT.md')
(args.output / 'START.txt').write_text(
    f'Status: {report["status"]}; active samples: {len(rows)}/20; archived service interruptions: {report.get("service_interruption_records", 0)}.\n'
    'Run: python serve-react-results.py --port 8765\nOpen: http://127.0.0.1:8765/gallery.html\n'
    'Live site links require this local server. Screenshots and source ZIPs can be opened directly.\n'
    'Raw model logs and credential files are excluded. Service-interrupted sites are partial.\n', encoding='utf-8')
hashes = {path.relative_to(args.output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
          for path in args.output.rglob('*') if path.is_file() and not path.is_symlink()
          and path.resolve().is_relative_to(args.output.resolve())}
(args.output / 'SHA256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
print('REACT_EXPORT_OK', len(rows), 'attempts', len(hashes), 'files')
