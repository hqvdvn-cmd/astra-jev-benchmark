from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 900
BACKGROUND = "#0b0b0c"
PANEL = "#121214"
PANEL_ALT = "#101012"
GRID = "#303035"
TRACK = "#28282d"
WHITE = "#f5f5f2"
MUTED = "#b5b5bb"
ORANGE = "#ff6a22"
BLUE = "#5b8ff9"
TEAL = "#20b8a7"
PURPLE = "#b784f7"
TEAL_LIGHT = "#69d4c8"
RED = "#ff6b63"


MODE_ORDER = (
    "astra_only",
    "astra_jev_observe",
    "astra_jev_offload",
    "astra_jev_guarded",
    "astra_jev_offload_guarded",
)

MODE_COLORS = {
    "astra_only": ORANGE,
    "astra_jev_observe": BLUE,
    "astra_jev_offload": TEAL,
    "astra_jev_guarded": PURPLE,
    "astra_jev_offload_guarded": TEAL_LIGHT,
}

TASK_ORDER = ("code-write-001", "bug-fix-001", "browser-001")

TEXT = {
    "en": {
        "mode_labels": {
            "astra_only": "Astra",
            "astra_jev_observe": "Jev Observe",
            "astra_jev_offload": "Jev Offload",
            "astra_jev_guarded": "Guarded retry",
            "astra_jev_offload_guarded": "Offload + guard",
        },
        "mode_short": {
            "astra_only": "Astra",
            "astra_jev_observe": "Observe",
            "astra_jev_offload": "Offload",
            "astra_jev_guarded": "Guarded",
            "astra_jev_offload_guarded": "Hybrid",
        },
        "task_labels": {
            "code-write-001": "Code writing",
            "bug-fix-001": "Bug fixing",
            "browser-001": "Browser form",
        },
        "overview_title": "Astra + Jev: 45 attempts",
        "overview_subtitle": "3 tasks × 5 modes × 3 repeats",
        "mode": "MODE",
        "success": "PASS",
        "mean_time": "MEAN TIME ↓",
        "cost_success": "COST / SUCCESS ↓",
        "astra_only_note": "Only Astra performs task work",
        "api_cost_note": "Cost is an API-price equivalent",
        "savings_title": "What Jev offloading changed",
        "savings_subtitle": "Reduction versus Astra; longer bars mean larger savings",
        "astra_input": "Astra input tokens",
        "offload": "Jev Offload",
        "hybrid": "Offload + guard",
        "attempts_note": "45 attempts • 9 per mode",
        "breakdown_title": "Results by task",
        "breakdown_subtitle": "Every panel includes all 5 modes • lower is better",
        "seconds": "s",
    },
    "ru": {
        "mode_labels": {
            "astra_only": "Astra",
            "astra_jev_observe": "Наблюдение Jev",
            "astra_jev_offload": "Разгрузка Jev",
            "astra_jev_guarded": "Проверка с возвратом",
            "astra_jev_offload_guarded": "Разгрузка + проверка",
        },
        "mode_short": {
            "astra_only": "Astra",
            "astra_jev_observe": "Наблюд.",
            "astra_jev_offload": "Разгрузка",
            "astra_jev_guarded": "Проверка",
            "astra_jev_offload_guarded": "Совмещ.",
        },
        "task_labels": {
            "code-write-001": "Написание кода",
            "bug-fix-001": "Исправление ошибки",
            "browser-001": "Браузерная форма",
        },
        "overview_title": "Astra + Jev: 45 попыток",
        "overview_subtitle": "3 задания × 5 режимов × 3 повтора",
        "mode": "РЕЖИМ",
        "success": "УСПЕХ",
        "mean_time": "СРЕДНЕЕ ВРЕМЯ ↓",
        "cost_success": "ЦЕНА УСПЕХА ↓",
        "astra_only_note": "Задачу выполняет только Astra",
        "api_cost_note": "Расход: эквивалент по тарифу API",
        "savings_title": "Что дала разгрузка Jev",
        "savings_subtitle": "Снижение относительно Astra; длиннее полоса — больше экономия",
        "astra_input": "Входные токены Astra",
        "offload": "Разгрузка Jev",
        "hybrid": "Разгрузка + проверка",
        "attempts_note": "45 попыток • 9 на режим",
        "breakdown_title": "Результаты по заданиям",
        "breakdown_subtitle": "В каждой панели все 5 режимов • ниже — лучше",
        "seconds": "с",
    },
}


@dataclass(frozen=True)
class ModeMetric:
    attempts: int
    successes: int
    mean_duration_s: float
    estimated_cost_usd: float
    cost_per_success_usd: float

    @property
    def success_label(self) -> str:
        return f"{self.successes}/{self.attempts}"


def _metric(values: dict, *, task_pair: bool = False) -> ModeMetric:
    return ModeMetric(
        attempts=int(values["attempts"]),
        successes=int(values["successful_tasks"] if task_pair else values["successes"]),
        mean_duration_s=float(values["mean_duration_s"]),
        estimated_cost_usd=float(
            values["total_cost_usd"] if task_pair else values["estimated_cost_usd"]
        ),
        cost_per_success_usd=float(values["cost_per_success_usd"]),
    )


def load_dashboard_data(report_path: Path) -> dict[str, ModeMetric]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {mode: _metric(values) for mode, values in report["modes"].items()}


def load_task_breakdown_data(report_path: Path) -> dict[str, dict[str, ModeMetric]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    data: dict[str, dict[str, ModeMetric]] = {task_id: {} for task_id in TASK_ORDER}
    for pair in report["pairs"]:
        task_id = pair["task_id"]
        mode = pair["mode"]
        if task_id in data and mode in MODE_ORDER:
            data[task_id][mode] = _metric(pair, task_pair=True)
    return data


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def _base(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((72, 54), title, font=_font(52, bold=True), fill=WHITE)
    draw.text((74, 122), subtitle, font=_font(23), fill=MUTED)
    draw.line((72, 174, WIDTH - 72, 174), fill=GRID, width=2)
    return image, draw


def _label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    *,
    color: str = WHITE,
    size: int = 24,
    bold: bool = False,
) -> None:
    draw.text(xy, text, font=_font(size, bold=bold), fill=color)


def _label_right(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    *,
    color: str = WHITE,
    size: int = 20,
    bold: bool = False,
) -> None:
    font = _font(size, bold=bold)
    width = draw.textlength(text, font=font)
    draw.text((x - width, y), text, font=font, fill=color)


def _bar(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    width: int,
    value: float,
    maximum: float,
    color: str,
    *,
    height: int = 12,
) -> None:
    x, y = xy
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=TRACK)
    filled = max(height, int(width * value / maximum)) if value > 0 else 0
    if filled:
        draw.rounded_rectangle((x, y, x + filled, y + height), radius=height // 2, fill=color)


def _decimal(value: float, digits: int, locale: str) -> str:
    result = f"{value:.{digits}f}"
    return result.replace(".", ",") if locale == "ru" else result


def _render_overview(data: dict[str, ModeMetric], output: Path, locale: str) -> None:
    text = TEXT[locale]
    image, draw = _base(text["overview_title"], text["overview_subtitle"])
    x_mode, x_success, x_time, x_cost = 86, 620, 790, 1210
    header_y = 207
    _label(draw, (x_mode, header_y), text["mode"], color=MUTED, size=18, bold=True)
    _label(draw, (x_success, header_y), text["success"], color=MUTED, size=18, bold=True)
    _label(draw, (x_time, header_y), text["mean_time"], color=MUTED, size=18, bold=True)
    _label(draw, (x_cost, header_y), text["cost_success"], color=MUTED, size=18, bold=True)

    max_time = max(metric.mean_duration_s for metric in data.values())
    max_cost = max(metric.cost_per_success_usd for metric in data.values())
    for index, mode in enumerate(MODE_ORDER):
        metric = data[mode]
        top = 250 + index * 111
        color = MODE_COLORS[mode]
        fill = PANEL if index % 2 == 0 else PANEL_ALT
        draw.rounded_rectangle((72, top, WIDTH - 72, top + 91), radius=10, fill=fill)
        if mode == "astra_only":
            draw.rounded_rectangle(
                (72, top, WIDTH - 72, top + 91),
                radius=10,
                outline=ORANGE,
                width=2,
            )
        draw.rectangle((72, top + 16, 78, top + 75), fill=color)
        _label(draw, (x_mode, top + 23), text["mode_labels"][mode], size=24, bold=True)
        success_color = WHITE if metric.successes == metric.attempts else RED
        _label(
            draw,
            (x_success, top + 23),
            metric.success_label,
            color=success_color,
            size=27,
            bold=True,
        )
        _label(
            draw,
            (x_time, top + 14),
            f"{_decimal(metric.mean_duration_s, 1, locale)} {text['seconds']}",
            size=25,
            bold=True,
        )
        _bar(draw, (x_time, top + 57), 300, metric.mean_duration_s, max_time, color)
        _label(
            draw,
            (x_cost, top + 14),
            f"${_decimal(metric.cost_per_success_usd, 3, locale)}",
            size=25,
            bold=True,
        )
        _bar(draw, (x_cost, top + 57), 286, metric.cost_per_success_usd, max_cost, color)

    _label(draw, (74, 824), text["astra_only_note"], color=MUTED, size=19)
    _label_right(draw, 1526, 824, text["api_cost_note"], color=MUTED, size=19)
    image.save(output, optimize=True)


def _render_savings(report: dict, output: Path, locale: str) -> None:
    text = TEXT[locale]
    image, draw = _base(text["savings_title"], text["savings_subtitle"])
    comparisons = report["comparisons_to_astra_only"]
    series = (
        ("astra_jev_offload", text["offload"], TEAL),
        ("astra_jev_offload_guarded", text["hybrid"], TEAL_LIGHT),
    )
    metrics = (
        ("duration_change_pct", text["mean_time"].replace(" ↓", ""), True),
        ("astra_input_token_change_pct", text["astra_input"], True),
        ("cost_savings_pct", text["cost_success"].replace(" ↓", ""), False),
    )
    for row, (key, title, negate) in enumerate(metrics):
        top = 225 + row * 184
        _label(draw, (74, top), title, size=27, bold=True)
        draw.line((400, top + 42, 1500, top + 42), fill=GRID, width=2)
        for offset, (mode, name, color) in enumerate(series):
            raw = float(comparisons[mode][key])
            savings = -raw if negate else raw
            y = top + 64 + offset * 58
            _label(draw, (74, y - 8), name, color=MUTED, size=20)
            _bar(draw, (400, y), 850, savings, 25.0, color, height=24)
            _label(
                draw,
                (1280, y - 11),
                f"−{_decimal(savings, 1, locale)}%",
                color=color,
                size=28,
                bold=True,
            )

    draw.rounded_rectangle((72, 780, WIDTH - 72, 844), radius=10, fill=PANEL)
    _label(draw, (96, 797), text["astra_only_note"], size=22, bold=True)
    _label_right(draw, 1502, 799, text["attempts_note"], color=MUTED, size=20)
    image.save(output, optimize=True)


def _render_task_breakdown(
    data: dict[str, dict[str, ModeMetric]], output: Path, locale: str
) -> None:
    text = TEXT[locale]
    image, draw = _base(text["breakdown_title"], text["breakdown_subtitle"])
    panel_width = 466
    panel_height = 286
    x_positions = (72, 567, 1062)
    y_positions = (200, 507)
    metrics = (
        ("mean_duration_s", text["mean_time"].replace(" ↓", "")),
        ("cost_per_success_usd", text["cost_success"].replace(" ↓", "")),
    )

    for column, task_id in enumerate(TASK_ORDER):
        task_data = data[task_id]
        for row, (metric_name, metric_title) in enumerate(metrics):
            left = x_positions[column]
            top = y_positions[row]
            right = left + panel_width
            bottom = top + panel_height
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=14,
                fill=PANEL,
                outline=GRID,
                width=2,
            )
            _label(draw, (left + 20, top + 18), text["task_labels"][task_id], size=21, bold=True)
            _label(draw, (left + 20, top + 48), metric_title, color=MUTED, size=16)
            maximum = max(getattr(metric, metric_name) for metric in task_data.values())
            for index, mode in enumerate(MODE_ORDER):
                metric = task_data[mode]
                value = getattr(metric, metric_name)
                y = top + 83 + index * 38
                _label(draw, (left + 20, y), text["mode_short"][mode], color=MUTED, size=15)
                _bar(draw, (left + 132, y + 7), 205, value, maximum, MODE_COLORS[mode], height=11)
                if metric_name == "mean_duration_s":
                    value_label = f"{_decimal(value, 1, locale)} {text['seconds']}"
                else:
                    value_label = f"${_decimal(value, 3, locale)}"
                value_color = RED if metric.successes < metric.attempts else WHITE
                if metric.successes < metric.attempts:
                    value_label = f"{value_label} · {metric.success_label}"
                _label_right(
                    draw,
                    right - 16,
                    y - 2,
                    value_label,
                    color=value_color,
                    size=15,
                    bold=True,
                )

    image.save(output, optimize=True)


def render_dashboard_set(
    report_path: Path,
    output_dir: Path,
    *,
    locale: str = "en",
) -> list[Path]:
    if locale not in TEXT:
        raise ValueError(f"unsupported locale: {locale}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    overview_data = load_dashboard_data(report_path)
    task_data = load_task_breakdown_data(report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        output_dir / "benchmark-overview.png",
        output_dir / "benchmark-savings.png",
        output_dir / "task-breakdown.png",
    ]
    _render_overview(overview_data, outputs[0], locale)
    _render_savings(report, outputs[1], locale)
    _render_task_breakdown(task_data, outputs[2], locale)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Render localized benchmark graphics")
    parser.add_argument("report", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--locale", choices=tuple(TEXT), default="en")
    args = parser.parse_args()
    for output in render_dashboard_set(args.report, args.output_dir, locale=args.locale):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
