"""Render the completed 20-cell React pilot; no ongoing-study inputs."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jev_astra_bench.graphics import BACKGROUND, GRID, MUTED, ORANGE, RED, TEAL, WHITE, _base, _font, _label

GROUPS = [('gpt-6-astra', 'baseline', 'Astra'), ('gpt-6-astra', 'jev_offload', 'Astra + Jev'),
          ('gpt-6.1-sol', 'baseline', 'Sol 6.1'), ('gpt-6.1-sol', 'jev_offload', 'Sol 6.1 + Jev')]
COLORS = {'success': TEAL, 'timeout': ORANGE, 'failure': RED}
TEXT = {
    'en': {'title': 'React pilot: all outcomes', 'subtitle': '20 cells per revision · original series and 3 owner-requested reruns',
           'original': 'Original', 'revised': 'After reruns', 'success': 'Success', 'timeout': 'Time limit',
           'failure': 'Check failed', 'note': '17 cells unchanged. Failed attempts remain included; no best-of-five selection.',
           'limit': 'Functional checks only. Five repeats do not establish general superiority.',
           'timing_title': 'React pilot: generation time', 'timing_subtitle': 'After requested reruns · one point per attempt · 19 of 20 timings known',
           'median': 'Median', 'unknown': 'Unknown', 'deadline': '900 s budget', 'axis': 'GPT generation time, seconds',
           'timing_note': 'All outcomes included. Unknown time is not zero; Sol + Jev has no group median.',
           'timing_limit': 'Generation excludes the external evaluator. Actual CLI cost is unavailable.'},
    'ru': {'title': 'React-пилот: все исходы', 'subtitle': 'По 20 ячеек в каждой редакции · исходная серия и три повтора по просьбе владельца',
           'original': 'Исходная', 'revised': 'С повторами', 'success': 'Успех', 'timeout': 'Лимит времени',
           'failure': 'Ошибка проверок', 'note': '17 ячеек не менялись. Все неудачи учтены; отбора лучшего из пяти нет.',
           'limit': 'Проверены функции сайта. Пять повторов не доказывают общего преимущества.',
           'timing_title': 'React-пилот: время генерации', 'timing_subtitle': 'После повторов · точка — отдельная попытка · известно время 19 из 20 попыток',
           'median': 'Медиана', 'unknown': 'Нет данных', 'deadline': 'Бюджет 900 с', 'axis': 'Время генерации GPT, секунды',
           'timing_note': 'Учтены все исходы. Неизвестное время не равно нулю; медианы Sol + Jev нет.',
           'timing_limit': 'Внешняя проверка не входит во время генерации. Фактическая стоимость CLI неизвестна.'},
}


def load_data(evidence: Path) -> dict:
    data = {}
    for name, filename in [('original', 'original-summary.json'), ('revised', 'rerun-summary.json')]:
        report = json.loads((evidence / filename).read_text(encoding='utf-8'))
        if report.get('schema') != 'public-react-pilot-summary-v1' or report.get('status') != 'complete':
            raise ValueError('Only completed public React pilot summaries are accepted')
        rows = report['attempts']
        expected = {(model, mode, repeat) for model, mode, _ in GROUPS for repeat in range(1, 6)}
        if len(rows) != 20 or {(r['model'], r['mode'], r['repeat']) for r in rows} != expected:
            raise ValueError('The figure requires exactly the approved twenty cells')
        result = []
        for model, mode, label in GROUPS:
            selected = sorted((r for r in rows if (r['model'], r['mode']) == (model, mode)), key=lambda r: r['repeat'])
            samples = []
            for row in selected:
                outcome = 'success' if row['success'] else 'timeout' if row['model_timed_out'] else 'failure'
                samples.append({key: row[key] for key in ('attempt_id', 'repeat', 'model_duration_s')} | {'outcome': outcome})
            times = [s['model_duration_s'] for s in samples]
            median = statistics.median(times) if all(t is not None for t in times) else None
            recorded = report['groups'][model + '/' + mode]['median_model_duration_s']
            if median != recorded:
                raise ValueError('Published median differs from attempt-level values')
            result.append({'model': model, 'mode': mode, 'label': label, 'attempts': 5,
                           **{outcome: sum(s['outcome'] == outcome for s in samples) for outcome in COLORS},
                           'median_model_duration_s': median, 'unknown_timing': times.count(None), 'samples': samples})
        data[name] = result
    data['scope'] = 'Completed React pilot only; original and owner-requested rerun revision. No ongoing paired-study results.'
    return data


def legend(draw, text, y):
    for x, outcome in zip((90, 430, 860), COLORS):
        draw.rectangle((x, y + 4, x + 20, y + 24), fill=COLORS[outcome])
        _label(draw, (x + 34, y), text[outcome], size=22)


def outcomes(data: dict, output: Path, language: str):
    text = TEXT[language]
    image, draw = _base(text['title'], text['subtitle'])
    for index, (_, _, label) in enumerate(GROUPS):
        top = 234 + index * 126
        _label(draw, (86, top + 21), label, size=28, bold=True)
        for offset, revision in enumerate(('original', 'revised')):
            group = data[revision][index]
            y = top + offset * 46
            _label(draw, (395, y + 2), text[revision], size=20, color=MUTED)
            x = 610
            for outcome in COLORS:
                count = group[outcome]
                if count:
                    end = x + count * 160
                    draw.rectangle((x, y, end, y + 32), fill=COLORS[outcome])
                    number = str(count)
                    width = draw.textlength(number, font=_font(21, bold=True))
                    _label(draw, (int((x + end - width) / 2), y + 1), number, size=21, color=BACKGROUND, bold=True)
                    x = end
            _label(draw, (1434, y + 1), f"{group['success']}/5", size=22, bold=True)
    legend(draw, text, 750)
    _label(draw, (74, 806), text['note'], size=21, color=MUTED)
    _label(draw, (74, 843), text['limit'], size=20, color=MUTED)
    image.save(output, optimize=True)


def generation(data: dict, output: Path, language: str):
    text = TEXT[language]
    image, draw = _base(text['timing_title'], text['timing_subtitle'])
    legend(draw, text, 202)
    left, width = 520, 820
    for value in range(0, 1001, 200):
        x = left + int(width * value / 1000)
        draw.line((x, 242, x, 703), fill=GRID, width=1)
        _label(draw, (x - 16, 711), str(value), size=18, color=MUTED)
    deadline = left + int(width * 0.9)
    for y in range(242, 703, 14):
        draw.line((deadline, y, deadline, y + 6), fill=ORANGE, width=2)
    _label(draw, (deadline - 80, 201), text['deadline'], size=18, color=ORANGE)
    _label(draw, (1398, 201), text['unknown'], size=18, color=MUTED)
    for index, group in enumerate(data['revised']):
        center = 280 + index * 128
        _label(draw, (86, center - 27), group['label'], size=28, bold=True)
        median = group['median_model_duration_s']
        value = f'{median:.1f}' if median is not None else '—'
        if language == 'ru':
            value = value.replace('.', ',')
        _label(draw, (86, center + 14), text['median'] + ': ' + value, size=21, color=MUTED)
        if median is not None:
            x = left + int(width * median / 1000)
            draw.line((x, center - 44, x, center + 44), fill=WHITE, width=2)
        for sample in group['samples']:
            duration = sample['model_duration_s']
            y = center + (sample['repeat'] - 3) * 18
            if duration is None:
                _label(draw, (1450, y - 13), '?', size=26, color=MUTED, bold=True)
                continue
            x = left + int(width * duration / 1000)
            draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=COLORS[sample['outcome']], outline=WHITE)
    _label(draw, (520, 746), text['axis'], size=21, color=MUTED)
    _label(draw, (74, 803), text['timing_note'], size=21, color=MUTED)
    _label(draw, (74, 842), text['timing_limit'], size=20, color=MUTED)
    image.save(output, optimize=True)


def render(evidence: Path, output: Path):
    data = load_data(evidence)
    for language in TEXT:
        directory = output / language
        directory.mkdir(parents=True, exist_ok=True)
        outcomes(data, directory / 'react-pilot-outcomes.png', language)
        generation(data, directory / 'react-pilot-generation.png', language)
    (output / 'react-pilot-chart-data.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'evidence/2026-10-23-react-pilot')
    parser.add_argument('--output', type=Path, default=ROOT / 'docs/images')
    args = parser.parse_args()
    render(args.evidence, args.output)
