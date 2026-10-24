"""Prepare static public copies from a reviewed export of the completed pilot."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'https://hqvdvn-cmd.github.io/astra-jev-benchmark/gallery/'
BASE = '/astra-jev-benchmark/gallery/'
SITE_TYPES = {'.html', '.js', '.css', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.mp4', '.woff', '.woff2', '.ico'}


def relocate(text: str, urls: dict[str, str]) -> str:
    # Only complete URL literals for files that actually exist in the same build.
    for old in sorted(urls, key=len, reverse=True):
        for quote in ('"', "'", '`'):
            text = text.replace(quote + old + quote, quote + urls[old] + quote)
        text = text.replace('url(' + old + ')', 'url(' + urls[old] + ')')
    return text


def public_row(row: dict, slug: str, archived: bool) -> dict:
    return {**{key: row.get(key) for key in ('attempt_id', 'model', 'mode', 'repeat', 'success', 'model_timed_out', 'model_duration_s')},
            'slug': slug, 'archived': archived,
            'status': 'SERVICE INTERRUPTED' if archived else 'PASS' if row['success'] else 'TIME LIMIT' if row.get('model_timed_out') else 'CHECK FAILED',
            'checks': row.get('verification', {}).get('checks', {}),
            'service_error': row.get('service_error') if archived else None,
            'site_url': PUBLIC + slug + '/site/'}


def ordinary(root: Path, path: Path):
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Publication path escapes the reviewed export')
    for part in (path, *path.parents):
        if part == root.parent:
            break
        info = part.lstat()
        if part.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0):
            raise ValueError('Links/reparse points are not publishable')


def prepare(source: Path, target: Path):
    source = source.resolve()
    report = json.loads((source / 'report.json').read_text(encoding='utf-8'))
    if report['status'] != 'complete' or len(report['attempts']) != 20:
        raise ValueError('Only the completed twenty-cell React pilot is publishable')
    if target.exists():
        raise ValueError('Choose an absent gallery target; existing publications are preserved')
    target.mkdir(parents=True)
    rows, files, cards, archive_cards = [], {}, [], []
    samples = [(row, False, 0) for row in sorted(report['attempts'], key=lambda r: (r['model'], r['mode'], r['repeat']))]
    samples += [(row, True, i) for i, row in enumerate(report.get('service_interrupted_attempts', []), 1)]
    for row, archived, index in samples:
        relative = row.get('artifact_folder', row['attempt_id'])
        original = source / relative
        ordinary(source, original)
        slug = ('archive-' + str(index) + '-' if archived else '') + row['attempt_id']
        if not re.fullmatch('[a-zA-Z0-9_.-]+', slug):
            raise ValueError('Unsafe sample identifier')
        site = original / 'site'
        ordinary(source, site)
        paths = sorted(p for p in site.rglob('*') if p.is_file())
        if not (site / 'index.html').is_file():
            raise ValueError('Every linked sample must retain a build, even incomplete ones')
        urls = {'/' + p.relative_to(site).as_posix(): BASE + slug + '/site/' + p.relative_to(site).as_posix() for p in paths}
        for path in paths:
            ordinary(source, path)
            if path.suffix.lower() not in SITE_TYPES:
                raise ValueError('Unexpected built-site file type')
            data = path.read_bytes()
            published = relocate(data.decode('utf-8'), urls).encode('utf-8') if path.suffix in {'.html', '.js', '.css'} else data
            name = slug + '/site/' + path.relative_to(site).as_posix()
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(published)
            files[name] = {'original_sha256': hashlib.sha256(data).hexdigest(),
                           'published_sha256': hashlib.sha256(published).hexdigest(),
                           'url_relocated': data != published}
        metadata = public_row(row, slug, archived)
        rows.append(metadata)
        (target / slug / 'result.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        image = original / 'artifacts/desktop.png'
        image_html = ''
        if image.is_file():
            ordinary(source, image)
            shutil.copy2(image, target / slug / 'desktop.png')
            image_html = f'<img loading="lazy" src="{slug}/desktop.png" alt="{html.escape(row["attempt_id"])}">'
        label = html.escape(f'{row["model"]} · {row["mode"]} · repeat {row["repeat"]}')
        state = metadata['status']
        note = 'Archived partial output; excluded from scored samples.' if archived else 'Scored attempt; retained exactly as generated apart from static URL relocation.'
        if not archived and row['attempt_id'] == 'gpt-6-astra-baseline-r1':
            note = 'Starter only after time budget expired. No completed website was produced.'
        card = (f'<article id="{slug}"><h2>{"ARCHIVE · " if archived else ""}{label}</h2><p>{state}</p>'
                f'<p>{note}</p>{image_html}<p><a href="{slug}/site/">Open site</a> · '
                f'<a href="{slug}/result.json">Result / checks</a></p></article>')
        (archive_cards if archived else cards).append(card)
    data = {'study': 'completed-react-pilot', 'active': 20, 'archived': len(archive_cards), 'samples': rows,
            'scope': 'Original twenty-cell matrix with three owner-requested replacements. Ongoing pairs excluded.',
            'deployment_transform': 'Only complete static root-asset URL literals relocated to the GitHub Pages sample subpath. No functional repair.',
            'raw_logs_source_zips_and_profiles': 'not published'}
    (target / 'samples.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    (target / 'deployment-hashes.json').write_text(json.dumps(files, indent=2) + '\n', encoding='utf-8')
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Completed GPT React pilot — all sites</title><style>body{font:16px system-ui;margin:32px;background:#eee;color:#111}'
            'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(400px,100%),1fr));gap:24px}'
            'article{background:white;padding:20px}img{width:100%}h2{font-size:18px}a{color:#1453a2}</style>'
            '<h1>Completed GPT React pilot</h1><p>20 scored sites / attempts · 17 passed · 2 time limits · 1 functional failure.</p>'
            '<p>Five repeats per model/mode. Functional checks do not rate visual quality. Failures and the starter-only attempt remain visible.</p>'
            '<p>These are fictional studio demos; forms do not send requests. The ongoing planner/builder study is excluded.</p>'
            '<p><a href="https://github.com/hqvdvn-cmd/astra-jev-benchmark/tree/react-sol-pilot">Harness / tests branch</a> · '
            '<a href="samples.json">All results</a> · <a href="deployment-hashes.json">Deployment hashes</a></p><main>'
            + ''.join(cards) + '</main><details><summary>5 archived service interruptions — partial outputs</summary><main>'
            + ''.join(archive_cards) + '</main></details></html>')
    (target / 'index.html').write_text(page, encoding='utf-8')
    return rows


def readme_links(rows: list[dict], language: str) -> str:
    ru = language == 'ru'
    lines = ['## ' + ('Галерея сайтов и проведённые тесты' if ru else 'Website gallery and completed tests'), '',
             ('[Открыть публичную галерею](' if ru else '[Open the public gallery](') + PUBLIC + ').', '',
             ('Проверены `gpt-6-astra` и `gpt-6.1-sol`, baseline и Jev offload, по пять независимых прогонов: 20 ячеек. Один ORBIT React-промпт, стартер и ассеты; xhigh, 900 секунд; 18 внешних функциональных проверок. После трёх повторов: 17 успехов, 2 тайм-аута и 1 ошибка проверок. Исходная серия — 16/20. Качество дизайна не оценивалось автоматически.' if ru else
              'Tested `gpt-6-astra` and `gpt-6.1-sol`, baseline and Jev offload, five independent runs each: 20 cells. Identical ORBIT React task, starter and assets; xhigh, 900 seconds; 18 external functional checks. After three requested reruns: 17 successes, 2 timeouts and 1 check failure. Original series: 16/20. Visual quality was not automatically scored.'), '',
             ('Ссылки ниже ведут на все 20 основных вариантов, включая неудачные. Astra baseline r1 остался стартером. Далее отдельно указаны 5 частичных архивных вариантов. Текущий замер связок сюда не включён. При публикации изменены только адреса статических ассетов для подкаталогов GitHub Pages; исходные результаты проверок сохранены.' if ru else
              'All 20 active outputs are linked below, including failures. Astra baseline r1 remained the starter. Five partial archived versions follow separately. The ongoing paired study is excluded. Publication changes only static asset URL prefixes for GitHub Pages subpaths; original check outcomes are retained.'), '',
             '| ' + ('Модель / режим / повтор | Результат | Сайт |' if ru else 'Model / mode / repeat | Result | Site |'), '|---|---|---|']
    for archived in (False, True):
        if archived:
            lines += ['', '### ' + ('Архив прерываний — частичные сайты' if ru else 'Interrupted archive — partial sites'), '',
                      '| ' + ('Модель / режим / повтор | Результат | Сайт |' if ru else 'Model / mode / repeat | Result | Site |'), '|---|---|---|']
        for row in rows:
            if row['archived'] == archived:
                label = f'{row["model"]} / {row["mode"]} / {row["repeat"]}'
                lines.append(f'| {label} | {row["status"]} | [{"Открыть" if ru else "Open"}]({row["site_url"]}) |')
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Reviewed local export; never copied wholesale')
    args = parser.parse_args()
    rows = prepare(args.source, ROOT / 'docs/gallery')
    (ROOT / 'docs/.nojekyll').write_text('', encoding='utf-8')
    (ROOT / 'docs/index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=gallery/"><a href="gallery/">React pilot gallery</a>', encoding='utf-8')
    for language, name in [('en', 'README.md'), ('ru', 'README.ru.md')]:
        path = ROOT / name
        text = path.read_text(encoding='utf-8')
        marker = '\n## Result' if language == 'en' else '\n## Результат'
        assert marker in text
        text = text.replace(marker, '\n' + readme_links(rows, language) + marker, 1)
        path.write_text(text, encoding='utf-8')
    print(json.dumps({'published_candidates': 20, 'archived_outputs': len(rows) - 20, 'gallery_url': PUBLIC}))
