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
GRID = "#2a2a2d"
WHITE = "#f5f5f2"
MUTED = "#9a9a9f"
ORANGE = "#ff6a22"
ORANGE_DARK = "#5a2814"
TEAL = "#20b8a7"
TEAL_DARK = "#11685f"
RED = "#f2645a"


MODE_ORDER = (
    "astra_only",
    "astra_jev_observe",
    "astra_jev_offload",
    "astra_jev_guarded",
    "astra_jev_offload_guarded",
)

MODE_LABELS = {
    "astra_only": "Astra",
    "astra_jev_observe": "Наблюдение Jev",
    "astra_jev_offload": "Разгрузка Jev",
    "astra_jev_guarded": "Проверка с возвратом",
    "astra_jev_offload_guarded": "Разгрузка + проверка",
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


def load_dashboard_data(report_path: Path) -> dict[str, ModeMetric]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    modes = report["modes"]
    return {
        mode: ModeMetric(
            attempts=int(values["attempts"]),
            successes=int(values["successes"]),
            mean_duration_s=float(values["mean_duration_s"]),
            estimated_cost_usd=float(values["estimated_cost_usd"]),
            cost_per_success_usd=float(values["cost_per_success_usd"]),
        )
        for mode, values in modes.items()
    }


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        Path("C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size=size)


def _base(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)
    draw.text((72, 58), title, font=_font(54, bold=True), fill=WHITE)
    draw.text((74, 126), subtitle, font=_font(24), fill=MUTED)
    draw.line((72, 178, WIDTH - 72, 178), fill=GRID, width=2)
    return image, draw


def _label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, color: str = WHITE, size: int = 24, bold: bool = False) -> None:
    draw.text(xy, text, font=_font(size, bold=bold), fill=color)


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
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill="#242427")
    filled = max(height, int(width * value / maximum)) if value > 0 else 0
    if filled:
        draw.rounded_rectangle((x, y, x + filled, y + height), radius=height // 2, fill=color)


def _render_overview(data: dict[str, ModeMetric], output: Path) -> None:
    image, draw = _base("Astra + Jev: 45 попыток", "3 задания × 5 режимов × 3 повтора")
    x_mode, x_success, x_time, x_cost = 86, 620, 790, 1210
    header_y = 212
    _label(draw, (x_mode, header_y), "РЕЖИМ", color=MUTED, size=18, bold=True)
    _label(draw, (x_success, header_y), "УСПЕХ", color=MUTED, size=18, bold=True)
    _label(draw, (x_time, header_y), "СРЕДНЕЕ ВРЕМЯ ↓", color=MUTED, size=18, bold=True)
    _label(draw, (x_cost, header_y), "ЦЕНА УСПЕХА ↓", color=MUTED, size=18, bold=True)

    max_time = max(metric.mean_duration_s for metric in data.values())
    max_cost = max(metric.cost_per_success_usd for metric in data.values())
    for index, mode in enumerate(MODE_ORDER):
        metric = data[mode]
        top = 255 + index * 112
        accent = ORANGE if mode == "astra_only" else TEAL
        if mode == "astra_jev_guarded":
            accent = RED
        fill = "#141416" if index % 2 == 0 else "#101012"
        draw.rounded_rectangle((72, top, WIDTH - 72, top + 92), radius=10, fill=fill)
        if mode == "astra_only":
            draw.rounded_rectangle((72, top, WIDTH - 72, top + 92), radius=10, outline=ORANGE, width=2)
        draw.rectangle((72, top + 16, 78, top + 76), fill=accent)
        _label(draw, (x_mode, top + 24), MODE_LABELS[mode], size=25, bold=True)
        success_color = WHITE if metric.successes == metric.attempts else RED
        _label(draw, (x_success, top + 24), metric.success_label, color=success_color, size=28, bold=True)
        _label(draw, (x_time, top + 15), f"{metric.mean_duration_s:.1f} с".replace(".", ","), size=26, bold=True)
        _bar(draw, (x_time, top + 58), 300, metric.mean_duration_s, max_time, accent)
        _label(draw, (x_cost, top + 15), f"${metric.cost_per_success_usd:.3f}".replace(".", ","), size=26, bold=True)
        _bar(draw, (x_cost, top + 58), 286, metric.cost_per_success_usd, max_cost, accent)

    _label(draw, (74, 830), "Astra — единственная рабочая модель", color=MUTED, size=20)
    _label(draw, (1110, 830), "Расход: эквивалент по тарифу API", color=MUTED, size=20)
    image.save(output, optimize=True)


def _render_savings(report: dict, output: Path) -> None:
    image, draw = _base("Что дала разгрузка Jev", "Снижение относительно Astra; больше полоса — больше экономия")
    comparisons = report["comparisons_to_astra_only"]
    series = (
        ("astra_jev_offload", "Разгрузка Jev", TEAL),
        ("astra_jev_offload_guarded", "Разгрузка + проверка", "#69d4c8"),
    )
    metrics = (
        ("duration_change_pct", "Среднее время", True),
        ("astra_input_token_change_pct", "Входные токены Astra", True),
        ("cost_savings_pct", "Цена успешной задачи", False),
    )
    max_value = 25.0
    for row, (key, title, negate) in enumerate(metrics):
        top = 235 + row * 185
        _label(draw, (74, top), title, size=27, bold=True)
        draw.line((400, top + 42, 1500, top + 42), fill=GRID, width=2)
        for offset, (mode, name, color) in enumerate(series):
            raw = float(comparisons[mode][key])
            savings = -raw if negate else raw
            y = top + 64 + offset * 58
            _label(draw, (74, y - 8), name, color=MUTED, size=20)
            _bar(draw, (400, y), 850, savings, max_value, color, height=24)
            _label(draw, (1280, y - 11), f"−{savings:.1f}%".replace(".", ","), color=color, size=28, bold=True)

    draw.rounded_rectangle((72, 785, WIDTH - 72, 846), radius=10, fill=PANEL)
    _label(draw, (96, 800), "Astra остаётся единственной рабочей моделью", size=23, bold=True)
    _label(draw, (1082, 802), "45 попыток • 9 на режим", color=MUTED, size=20)
    image.save(output, optimize=True)


def _render_browser(report: dict, output: Path) -> None:
    image, draw = _base("Браузерная задача", "Локальная форма • 3 повтора на режим • ниже — лучше")
    pair_index = {(pair["task_id"], pair["mode"]): pair for pair in report["pairs"]}
    modes = ("astra_only", "astra_jev_offload", "astra_jev_offload_guarded")
    colors = (ORANGE, TEAL, "#69d4c8")
    panels = (
        (72, 222, 756, 756, "Среднее время", "mean_duration_s", " с", 24.0),
        (844, 222, 1528, 756, "Цена успешной задачи", "cost_per_success_usd", "$", 0.22),
    )
    for left, top, right, bottom, title, key, suffix, maximum in panels:
        draw.rounded_rectangle((left, top, right, bottom), radius=16, fill=PANEL, outline=GRID, width=2)
        _label(draw, (left + 32, top + 30), title, size=30, bold=True)
        for index, (mode, color) in enumerate(zip(modes, colors)):
            pair = pair_index[("browser-001", mode)]
            value = float(pair[key])
            y = top + 118 + index * 125
            _label(draw, (left + 32, y), MODE_LABELS[mode], color=MUTED, size=20)
            _bar(draw, (left + 32, y + 46), 500, value, maximum, color, height=28)
            if suffix == "$":
                value_label = f"${value:.3f}".replace(".", ",")
            else:
                value_label = f"{value:.1f}{suffix}".replace(".", ",")
            _label(draw, (right - 118, y + 35), value_label, color=color, size=26, bold=True)

    _label(draw, (74, 806), "Astra", color=ORANGE, size=22, bold=True)
    _label(draw, (190, 806), "Разгрузка Jev", color=TEAL, size=22, bold=True)
    _label(draw, (420, 806), "Разгрузка + проверка", color="#69d4c8", size=22, bold=True)
    _label(draw, (1218, 808), "Все режимы: 3/3", color=MUTED, size=20)
    image.save(output, optimize=True)


def render_dashboard_set(report_path: Path, output_dir: Path) -> list[Path]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    data = load_dashboard_data(report_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        output_dir / "jev-benchmark-overview.png",
        output_dir / "jev-benchmark-savings.png",
        output_dir / "jev-browser-benchmark.png",
    ]
    _render_overview(data, outputs[0])
    _render_savings(report, outputs[1])
    _render_browser(report, outputs[2])
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Render README graphics from a Jev benchmark report")
    parser.add_argument("report", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    for output in render_dashboard_set(args.report, args.output_dir):
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
