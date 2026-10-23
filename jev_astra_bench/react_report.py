from __future__ import annotations

import html
import json
import statistics
from pathlib import Path


def summarize(rows: list[dict], interrupted_rows: list[dict] | None = None) -> dict:
    interrupted_rows = interrupted_rows or []
    groups = {}
    for model, mode in sorted({(r['model'], r['mode']) for r in rows + interrupted_rows}):
        selected = [r for r in rows if (r['model'], r['mode']) == (model, mode)]
        archived = [r for r in interrupted_rows if (r['model'], r['mode']) == (model, mode)]
        interruptions = sum(bool(r.get('service_error')) for r in selected) + len(archived)
        durations = [r['duration_s'] for r in selected if r.get('duration_s') is not None]
        model_durations = [r['model_duration_s'] for r in selected if r.get('model_duration_s') is not None]
        groups[f'{model}/{mode}'] = {
            'attempts': len(selected), 'successes': sum(bool(r['success']) for r in selected),
            'completed_attempts': sum(r.get('model_completed', True) for r in selected),
            'service_interruptions': interruptions,
            'timing_records': len(durations), 'missing_timing_records': len(selected) - len(durations),
            'median_duration_s': statistics.median(durations) if durations and len(durations) == len(selected) else None,
            'min_duration_s': min(durations) if durations and len(durations) == len(selected) else None,
            'max_duration_s': max(durations) if durations and len(durations) == len(selected) else None,
            'median_model_duration_s': statistics.median(model_durations) if model_durations and len(model_durations) == len(selected) else None,
            'estimated_cost_usd': None, 'cost_status': 'cli_billing_and_interrupted_usage_unavailable',
            'input_tokens': _sum_known(selected, 'input_tokens'),
            'cached_input_tokens': _sum_known(selected, 'cached_input_tokens'),
            'output_tokens': _sum_known(selected, 'output_tokens'),
            'jev_input_tokens': _sum_known(selected, 'jev_input_tokens'),
            'interrupted_duration_s': sum(r['duration_s'] for r in archived),
            'interrupted_input_tokens': _sum_known(archived, 'input_tokens') if archived else 0,
            'interrupted_jev_input_tokens': _sum_known(archived, 'jev_input_tokens') if archived else 0,
        }
    expected = {(model, mode, repeat) for model in ('gpt-6-astra', 'gpt-6.1-sol')
                for mode in ('baseline', 'jev_offload') for repeat in range(1, 6)}
    cells = {(r['model'], r['mode'], r.get('repeat')) for r in rows}
    complete = (len(rows) == 20 and cells == expected
                and all(r.get('model_completed', True) or r.get('model_timed_out', False) for r in rows)
                and not any(r.get('service_error') for r in rows))
    return {'schema_version': 2, 'records': len(rows), 'status': 'complete' if complete else 'incomplete', 'groups': groups, 'attempts': rows,
            'service_interruption_records': len(interrupted_rows), 'service_interrupted_attempts': interrupted_rows,
            'timing_comparability': 'Compare model_duration_s for generation time. duration_s includes the original evaluator; earlier samples were rechecked after evaluator corrections. Total-time statistics across evaluation revisions are descriptive and exclude recheck overhead.',
            'quality_rating': 'Functional checks only; visual ratings require human inspection.',
            'sampling_limit': 'Five repeats estimate variability on one task; they do not eliminate hallucinations.'}


def _sum_known(rows, field):
    values = [r.get(field) for r in rows]
    return sum(values) if all(isinstance(v, int) for v in values) else None


def write_report(rows: list[dict], output: Path) -> None:
    # Review sidecars preserve original append-only results while correcting evaluator
    # observations and classifying service interruptions from retained raw events.
    rows = [dict(row) for row in rows]
    for row in rows:
        sidecar = output / row['attempt_id'] / 'review.json'
        if sidecar.exists():
            row['review'] = json.loads(sidecar.read_text(encoding='utf-8'))
            if row['review'].get('service_error'):
                row['service_error'] = row['review']['service_error']
    archive = output / 'service-interruptions.jsonl'
    interrupted = [json.loads(s) for s in archive.read_text(encoding='utf-8').splitlines() if s.strip()] if archive.exists() else []
    report = summarize(rows, interrupted)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# GPT React pilot', '', f"Status: {report['status']}. Recorded: {len(rows)}/20 attempts.", '',
             f'All attempts are retained, including {len(interrupted)} archived service interruptions. Replacements start from the same clean starter. Ordinary failures are retained. Functional checks do not rate visual quality.', '',
             '| Model / mode | Successful / active samples | Service interruptions | Median total | Total range | Median generation |', '|---|---:|---:|---:|---:|---:|']
    for name, group in report['groups'].items():
        generation = f"{group['median_model_duration_s']:.1f}s" if group['median_model_duration_s'] is not None else 'unavailable'
        duration = f"{group['median_duration_s']:.1f}s" if group['median_duration_s'] is not None else 'unavailable'
        spread = f"{group['min_duration_s']:.1f}–{group['max_duration_s']:.1f}s" if group['min_duration_s'] is not None else 'unavailable'
        lines.append(f"| {name} | {group['successes']}/{group['attempts']} | {group['service_interruptions']} | {duration} | {spread} | {generation} |")
    lines += ['', 'Group timing and token statistics cover the active samples; archived interruption time and known usage are recorded separately in report.json. Cost is unavailable: CLI billing and interrupted token usage are not fully reported. Verified API rates alone cannot determine the charge.', '',
              report['timing_comparability'], '',
              'Five repeats expose variability on one prompt. They do not establish general model superiority or remove hallucinations.', '',
              'Jev offload is one bounded strategy choice before GPT runs. Jev does not write the website or perform a visual review.', '',
              'Prompt, lockfile and starter fingerprints are in manifest.json. No post-generation manual repairs are included.']
    (output / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    cards = []
    for row in rows + interrupted:
        attempt = html.escape(row.get('artifact_folder', row['attempt_id']))
        label = html.escape(f"{row['model']} · {row['mode']} · repeat {row['repeat']}")
        checks = row.get('verification', {}).get('checks', {})
        failed = ', '.join(k for k, v in checks.items() if not v)
        state = 'SERVICE INTERRUPTED' if row.get('service_error') else ('PASS' if row['success'] else 'FAIL')
        review = row.get('review', {})
        review_text = html.escape(review.get('note', ''))
        live = f'<a href="{attempt}/site/index.html">Open site</a> · ' if (output / row.get('artifact_folder', row['attempt_id']) / 'workspace/dist/index.html').exists() else ''
        timing = f'{row["duration_s"]:.1f}s' if row.get('duration_s') is not None else 'timing unavailable'
        cards.append(f'<article><h2>{label}</h2><p>{state} · {timing}</p>'
                     f'<p>{html.escape(row.get("service_error") or row.get("failure_reason") or failed)}</p><p>{review_text}</p>'
                     f'<a href="{attempt}/artifacts/desktop.png"><img loading="lazy" src="{attempt}/artifacts/desktop.png" alt="{label}"></a>'
                     f'<p>{live}<a href="{attempt}/artifacts/mobile.png">Mobile</a> · <a href="{attempt}/source.zip">Source ZIP</a> · '
                     f'<a href="{attempt}/artifacts/verification.json">Checks</a> · '
                     f'<a href="{attempt}/artifacts/desktop.webm">Desktop recording</a></p></article>')
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GPT React pilot — all attempts</title><style>body{font:16px system-ui;margin:32px;background:#eee;color:#111}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(400px,100%),1fr));gap:24px}article{background:white;padding:20px}img{width:100%}h2{font-size:18px}a{color:#1453a2}</style><h1>GPT React pilot — all attempts</h1><p>Status: ' + report['status'] + f'. Active samples: {len(rows)}/20. Archived service interruptions: {len(interrupted)}.</p><p>External functional checks. Inspect screenshots and recordings for visual quality. No best-of-five selection.</p><main>' + ''.join(cards) + '</main></html>'
    (output / 'gallery.html').write_text(page, encoding='utf-8')
