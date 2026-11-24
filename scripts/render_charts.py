#!/usr/bin/env python3
"""Render the README benchmark charts from the published evidence.

Every number on every chart is computed here from
``evidence/2026-11-24-deepswe-pilot-10-v1/summary.json`` (plus harness
metadata from ``manifest.json``). Nothing is typed in by hand.

Output: three charts in English and Russian, written as 2x PNGs to
``docs/images/en/`` and ``docs/images/ru/``:

* ``overview-comparison.png``  -- sums over the complete valid pairs
* ``per-task-breakdown.png``   -- per-task scorecard for every task with runs
* ``routing-diagnostics.png``  -- jev-auto routing telemetry

Requirements: Python 3.11+, ``pip install playwright`` and a Chromium build
for it (``python -m playwright install chromium``). Set
``PLAYWRIGHT_BROWSERS_PATH`` if your browsers live outside the default cache,
or pass ``--chromium <executable>`` to reuse an existing Chromium build.

Usage::

    python scripts/render_charts.py                # render all 6 PNGs
    python scripts/render_charts.py --print-metrics   # print numbers, no render
    python scripts/render_charts.py --html-dir build/charts   # also keep HTML
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence" / "2026-11-24-deepswe-pilot-10-v1"
DEFAULT_SUMMARY = EVIDENCE_DIR / "summary.json"
DEFAULT_MANIFEST = EVIDENCE_DIR / "manifest.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "images"
SOURCE_LABEL = "evidence/2026-11-24-deepswe-pilot-10-v1/summary.json"

BASE = "codex-baseline"
JEV = "jev-auto"
CHEAP_MODEL = "gpt-6.1-terra"  # down-route target named by the tested policy
CARD_WIDTH = 1280  # CSS px; PNGs are rendered at device_scale_factor=2

# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def _totals(runs: list[dict[str, Any]]) -> dict[str, float]:
    tok = [r["tokens"] for r in runs]
    prompt = sum(t["prompt_tokens"] for t in tok)
    cached = sum(t["cached_tokens"] for t in tok)
    return {
        "n": len(runs),
        "passed": sum(1 for r in runs if r["reward"] == 1),
        "prompt": prompt,
        "cached": cached,
        "uncached": prompt - cached,
        "cache_hit": cached / prompt if prompt else 0.0,
        "output": sum(t["completion_tokens"] for t in tok),
        "reasoning": sum(t["reasoning_tokens"] for t in tok),
        "steps": sum(t["steps"] for t in tok),
        "duration": sum(r["duration_sec"] for r in runs),
        "mean_partial": sum(r["partial"] for r in runs) / len(runs) if runs else 0.0,
    }


def compute_metrics(summary: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    pairs = summary["pairs"]
    complete = [
        p
        for p in pairs
        if BASE in p["runs"]
        and JEV in p["runs"]
        and p["runs"][BASE]["valid"]
        and p["runs"][JEV]["valid"]
    ]
    if not complete:
        raise SystemExit("summary.json has no complete valid pairs")

    base = _totals([p["runs"][BASE] for p in complete])
    jev = _totals([p["runs"][JEV] for p in complete])

    # Projection: keep jev-auto's measured prompt/output/steps and apply the
    # baseline's uncached share of prompt tokens. Test outcomes unchanged.
    base_uncached_share = base["uncached"] / base["prompt"]
    proj = dict(jev)
    proj["uncached"] = jev["prompt"] * base_uncached_share
    proj["cached"] = jev["prompt"] - proj["uncached"]
    proj["cache_hit"] = base["cache_hit"]

    models: Counter[str] = Counter()
    efforts: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    per_task_routing = []
    for p in complete:
        r = p["runs"][JEV]["jev_routing"]
        models.update(r["models"])
        efforts.update(r["efforts"])
        sources.update(r["decision_sources"])
        per_task_routing.append(
            {
                "index": p["index"],
                "task_id": p["task_id"],
                "calls": r["total_calls"],
                "models": dict(r["models"]),
                "efforts": dict(r["efforts"]),
                "sources": dict(r["decision_sources"]),
                "timeouts": r["gates"].get("jev_error:TimeoutExpired", 0),
                "avg_jev_ms": r["avg_jev_ms"],
            }
        )
    total_calls = sum(t["calls"] for t in per_task_routing)

    tasks = []
    for p in pairs:
        if BASE not in p["runs"] or JEV not in p["runs"]:
            continue
        row = {"index": p["index"], "task_id": p["task_id"], "language": p["language"]}
        for mode in (BASE, JEV):
            r = p["runs"][mode]
            t = r["tokens"]
            row[mode] = {
                "valid": r["valid"],
                "invalid_reason": r["invalid_reason"],
                "reward": r["reward"],
                "f2p": (r["f2p_passed"], r["f2p_total"]),
                "p2p": (r["p2p_passed"], r["p2p_total"]),
                "duration": r["duration_sec"],
                "prompt": t["prompt_tokens"],
                "uncached": t["prompt_tokens"] - t["cached_tokens"],
                "cache_hit": t["cached_tokens"] / t["prompt_tokens"] if t["prompt_tokens"] else None,
                "quota_stop": bool((r.get("jev_routing") or {}).get("quota_fallback_detected")),
            }
        tasks.append(row)

    treatment = manifest.get("treatment", {})
    return {
        "date": manifest.get("date", ""),
        "codex_cli": manifest.get("codex_cli_version", ""),
        "baseline_model": summary["baseline_model"].split("/")[-1],
        "baseline_effort": summary["baseline_effort"],
        "harness_repo": treatment.get("harness_repo", "").replace("https://github.com/", ""),
        "harness_commit": treatment.get("harness_commit", "")[:7],
        "policy": treatment.get("policy_version", ""),
        "decision_provider": treatment.get("decision_provider", ""),
        "pair_indices": [p["index"] for p in complete],
        "base": base,
        "jev": jev,
        "proj": proj,
        "routing": {
            "total_calls": total_calls,
            "models": dict(models),
            "efforts": dict(efforts),
            "sources": dict(sources),
            "per_task": per_task_routing,
        },
        "tasks": tasks,
    }


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def delta(new: float, old: float) -> str:
    d = (new / old - 1) * 100
    return f"{'+' if d >= 0 else '−'}{abs(d):.1f}%"


def ratio(new: float, old: float) -> str:
    return f"{new / old:.1f}×"


def tok(n: float, k_digits: int = 1) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.{k_digits}f}k"
    return f"{n:.0f}"


def minutes(sec: float) -> str:
    return f"{sec / 60:.1f}"


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def esc_nw(s: str, *keep: str) -> str:
    """Escape ``s`` and keep each identifier in ``keep`` on one line."""
    out = esc(s)
    for k in keep:
        if k:
            out = out.replace(esc(k), f"<span class='nw'>{esc(k)}</span>")
    return out


def timeouts_text(n: int, lang: str) -> str:
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            word = "таймаут"
        elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            word = "таймаута"
        else:
            word = "таймаутов"
        return f"{n} {word}"
    return f"{n} timeout{'' if n == 1 else 's'}"


# --------------------------------------------------------------------------
# Copy (EN / RU)
# --------------------------------------------------------------------------

T = {
    "en": {
        "min": "min",
        "ms": "ms",
        "ov_eyebrow": "DeepSWE paired pilot · {n} complete valid pairs (#{a}–#{b}) · run {date}",
        "ov_title": "Plain Codex passed {bp}. jev/auto passed {jp} and sent {x} more uncached input.",
        "ov_sub": "Baseline: Codex CLI {cli}, {model}, reasoning effort {effort}. "
        "Treatment: {repo} @ {commit}, policy {policy}.",
        "kpi_pass": "tasks passed by jev-auto, against {bp} for plain Codex",
        "kpi_unc": "more uncached input tokens than plain Codex ({j} vs {b})",
        "kpi_route": "calls routed to the cheaper {cheap}",
        "lg_base": "Codex baseline",
        "lg_base_sub": "{model} · {effort}",
        "lg_jev": "jev-auto, measured",
        "lg_jev_sub": "prompt cache hit {hit}",
        "lg_proj": "jev-auto, cache fixed",
        "lg_proj_sub": "projection: {hit} hit, everything else as measured",
        "r_base": "Codex",
        "r_jev": "jev, measured",
        "r_proj": "jev, cache fixed",
        "p_pass": "Pass rate",
        "p_pass_sub": "reward = 1 · higher is better",
        "p_cache": "Prompt cache hit",
        "p_cache_sub": "cached ÷ prompt tokens · higher is better",
        "p_unc": "Uncached input tokens",
        "p_unc_sub": "prompt − cached · lower is better",
        "p_out": "Output tokens",
        "p_out_sub": "lower is better",
        "p_time": "Wall-clock time",
        "p_time_sub": "sum of {n} runs · lower is better",
        "p_steps": "Agent steps",
        "p_steps_sub": "ATIF steps · lower is better",
        "not_modeled": "not modeled",
        "set_to": "set to baseline",
        "ov_foot": "Projection keeps jev-auto's measured prompt, output and step counts, applies the baseline "
        "cache hit rate ({hit}) and assumes test outcomes stay the same. Source: {src}",
        # per-task
        "pt_eyebrow": "DeepSWE pilot · per-task scorecard · run {date}",
        "pt_title": "jev-auto sent {lo}–{hi} more uncached input on every completed task",
        "pt_sub": "Codex baseline ({model}, {effort}) against jev-auto, tasks #{a}–#{b}. "
        "On task #{q} jev-auto stopped on call #1 with HTTP 429, so that pair is excluded from totals.",
        "h_task": "Task",
        "h_result": "Result · tests",
        "h_unc": "Uncached input tokens · lower is better",
        "h_cache": "Cache hit",
        "h_time": "Wall time",
        "pass": "Pass",
        "fail": "Fail",
        "invalid": "Invalid",
        "quota": "HTTP 429 quota stop",
        "quota_bar": "HTTP 429 on call #1, no tokens recorded",
        "lang": {"go": "Go", "typescript": "TypeScript", "python": "Python", "rust": "Rust"},
        "pt_foot": "All bars share one linear scale (0–{max}). Ratio = jev-auto ÷ Codex uncached input. "
        "F2P: fail-to-pass tests, P2P: pass-to-pass tests. Source: {src}",
        # routing
        "rt_eyebrow": "jev-auto routing telemetry · tasks #{a}–#{b} · run {date}",
        "rt_title": "{n} routed calls, {terra} sent to {cheap}",
        "rt_sub": "Policy {policy} (decision provider {provider}). Every call stayed on {sol}.",
        "rp_model": "Model routing",
        "rp_model_big_cap": "calls on {sol}",
        "rp_effort": "Reasoning effort",
        "rp_effort_big_cap": "calls at high effort",
        "rp_src": "Decision source & latency",
        "rp_src_big_cap": "calls fell back on TimeoutExpired",
        "calls": "calls",
        "per_task": "Per task",
        "per_task_ms": "Per task · mean Jev decision time, 0–{max} ms",
        "high": "high",
        "medium": "medium",
        "src_jev": "jev decision",
        "src_lease": "lease reuse",
        "src_fb": "TimeoutExpired fallback",
        "fb_short": "fallbacks",
        "rt_foot": "Counts sum the jev_routing blocks of the {n} complete jev-auto runs. Source: {src}",
    },
    "ru": {
        "min": "мин",
        "ms": "мс",
        "ov_eyebrow": "Парный пилот DeepSWE · {n} полные валидные пары (#{a}–#{b}) · прогон {date}",
        "ov_title": "Чистый Codex решил {bp}. jev/auto решил {jp} и отправил в {x} больше некэшированного входа.",
        "ov_sub": "Базовая ветка: Codex CLI {cli}, {model}, reasoning effort {effort}. "
        "Тестовая: {repo} @ {commit}, политика {policy}.",
        "kpi_pass": "задачи решил jev-auto, у чистого Codex {bp}",
        "kpi_unc": "больше некэшированных входных токенов, чем у чистого Codex ({j} против {b})",
        "kpi_route": "вызовов ушло в дешёвую {cheap}",
        "lg_base": "Codex baseline",
        "lg_base_sub": "{model} · {effort}",
        "lg_jev": "jev-auto, факт",
        "lg_jev_sub": "кэш-хит промпта {hit}",
        "lg_proj": "jev-auto, кэш починен",
        "lg_proj_sub": "оценка: кэш-хит {hit}, остальное как в факте",
        "r_base": "Codex",
        "r_jev": "jev, факт",
        "r_proj": "jev, кэш починен",
        "p_pass": "Доля решённых задач",
        "p_pass_sub": "reward = 1 · больше — лучше",
        "p_cache": "Кэш-хит промпта",
        "p_cache_sub": "кэшированные ÷ все входные токены · больше — лучше",
        "p_unc": "Некэшированные входные токены",
        "p_unc_sub": "prompt − cached · меньше — лучше",
        "p_out": "Выходные токены",
        "p_out_sub": "меньше — лучше",
        "p_time": "Общее время",
        "p_time_sub": "сумма {n} прогонов · меньше — лучше",
        "p_steps": "Шаги агента",
        "p_steps_sub": "шаги ATIF · меньше — лучше",
        "not_modeled": "не оценивалось",
        "set_to": "как у baseline",
        "ov_foot": "Оценка берёт фактические входные и выходные токены и шаги jev-auto, подставляет кэш-хит "
        "базовой ветки ({hit}) и считает, что результаты тестов не меняются. Источник: {src}",
        # per-task
        "pt_eyebrow": "Пилот DeepSWE · результаты по задачам · прогон {date}",
        "pt_title": "На каждой завершённой задаче jev-auto отправил в {lo}–{hi} больше некэшированного входа",
        "pt_sub": "Codex baseline ({model}, {effort}) и jev-auto, задачи #{a}–#{b}. "
        "На задаче #{q} jev-auto упёрся в HTTP 429 на первом вызове, эта пара в итоги не входит.",
        "h_task": "Задача",
        "h_result": "Итог · тесты",
        "h_unc": "Некэшированные входные токены · меньше — лучше",
        "h_cache": "Кэш-хит",
        "h_time": "Время",
        "pass": "Решена",
        "fail": "Не решена",
        "invalid": "Невалидно",
        "quota": "остановка по HTTP 429",
        "quota_bar": "HTTP 429 на первом вызове, токенов нет",
        "lang": {"go": "Go", "typescript": "TypeScript", "python": "Python", "rust": "Rust"},
        "pt_foot": "У всех полос одна линейная шкала (0–{max}). Кратность = некэшированный вход jev-auto ÷ Codex. "
        "F2P: тесты fail-to-pass, P2P: pass-to-pass. Источник: {src}",
        # routing
        "rt_eyebrow": "Телеметрия роутинга jev-auto · задачи #{a}–#{b} · прогон {date}",
        "rt_title": "{n} вызовов через роутер, в {cheap} ушло {terra}",
        "rt_sub": "Политика {policy} (провайдер решений {provider}). Все вызовы остались на {sol}.",
        "rp_model": "Выбор модели",
        "rp_model_big_cap": "вызовов на {sol}",
        "rp_effort": "Reasoning effort",
        "rp_effort_big_cap": "вызовов с effort high",
        "rp_src": "Источник решения и задержка",
        "rp_src_big_cap": "вызовов ушли в фоллбек по TimeoutExpired",
        "calls": "вызовов",
        "per_task": "По задачам",
        "per_task_ms": "По задачам · среднее время Jev, 0–{max} мс",
        "high": "high",
        "medium": "medium",
        "src_jev": "решение jev",
        "src_lease": "повтор по lease",
        "src_fb": "фоллбек TimeoutExpired",
        "fb_short": "фоллбеков",
        "rt_foot": "Счётчики сложены из блоков jev_routing {n} полных прогонов jev-auto. Источник: {src}",
    },
}

# --------------------------------------------------------------------------
# Styles
# --------------------------------------------------------------------------

CSS = """
:root{
  --paper:#F4F3EF; --panel:#FBFAF7; --line:#D9D5CB; --grid:#E6E2D9;
  --ink:#151C25; --ink2:#465061; --ink3:#767D88;
  --base:#22324A; --base-soft:#DCE1E8;
  --jev:#B3443A; --jev-soft:#F2DCD7;
  --proj:#A9874F; --proj-hatch:#E2D3B4;
  --pass:#2D6A4F; --pass-soft:#DCEADF;
  --mute:#9AA2AD;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent}
body{
  font-family:"Segoe UI Variable Text","Segoe UI","Inter","Helvetica Neue",Arial,"Noto Sans",sans-serif;
  color:var(--ink); font-size:17px; line-height:1.35;
  font-variant-numeric:tabular-nums lining-nums; font-feature-settings:"tnum" 1,"lnum" 1;
  text-rendering:geometricPrecision; -webkit-font-smoothing:antialiased;
  padding:8px;
}
.card{width:__CARD_W__px;background:var(--paper);border:1.5px solid var(--line);border-radius:22px;padding:40px 48px 30px}
.display{font-family:"Segoe UI Variable Display","Segoe UI","Inter","Helvetica Neue",Arial,sans-serif}
.eyebrow{font-size:16px;font-weight:600;color:var(--ink3);letter-spacing:.01em}
h1{font-size:34px;line-height:1.18;font-weight:650;letter-spacing:-.012em;margin-top:10px;max-width:1120px;text-wrap:balance}
.sub{font-size:17px;color:var(--ink2);margin-top:10px;max-width:1120px}
.code{font-weight:600;color:var(--ink)}
.nw{white-space:nowrap}
.foot{font-size:15px;color:var(--ink3);margin-top:22px;padding-top:14px;border-top:1px solid var(--grid)}
.neg{color:var(--jev)} .pos{color:var(--pass)}
/* KPI row */
.kpis{display:grid;grid-template-columns:repeat(3,1fr);margin-top:26px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.kpi{padding:18px 24px 18px 0}
.kpi + .kpi{padding-left:24px;border-left:1px solid var(--line)}
.kpi .big{font-size:54px;line-height:1;font-weight:650;letter-spacing:-.02em;color:var(--jev)}
.kpi .big small{font-size:24px;font-weight:600;color:var(--ink3);letter-spacing:0;margin-left:8px}
.kpi .lbl{font-size:16.5px;color:var(--ink2);margin-top:10px;max-width:350px;text-wrap:pretty}
/* legend */
.legend{display:flex;gap:34px;margin-top:22px;flex-wrap:wrap}
.lg{display:flex;align-items:flex-start;gap:10px}
.sw{width:16px;height:16px;border-radius:4px;flex:none;margin-top:3px}
.sw.base{background:var(--base)} .sw.jev{background:var(--jev)}
.sw.proj{background:repeating-linear-gradient(135deg,var(--proj) 0 3px,var(--proj-hatch) 3px 6px);box-shadow:inset 0 0 0 1.5px var(--proj)}
.lg b{font-weight:650;font-size:16.5px;display:block}
.lg span{font-size:15px;color:var(--ink3)}
/* panels */
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:20px}
.panel{background:var(--panel);border:1px solid var(--grid);border-radius:14px;padding:18px 22px 16px}
.panel h3{font-size:19px;font-weight:650}
.panel .ps{font-size:14.5px;color:var(--ink3);margin-top:2px}
.rows{margin-top:14px;display:grid;gap:9px}
.row{display:grid;grid-template-columns:132px 1fr;align-items:center;gap:12px}
.rl{font-size:15px;color:var(--ink2);white-space:nowrap}
.track{display:flex;align-items:center;height:26px;position:relative}
.bar{height:22px;border-radius:4px;flex:none;min-width:3px}
.bar.base{background:var(--base)} .bar.jev{background:var(--jev)}
.bar.proj{background:repeating-linear-gradient(135deg,var(--proj) 0 4px,var(--proj-hatch) 4px 8px);box-shadow:inset 0 0 0 1.5px var(--proj)}
.val{margin-left:10px;font-size:17px;font-weight:650;white-space:nowrap}
.val .d{font-weight:600;font-size:15px;margin-left:7px}
.val .d.neg{color:var(--jev)} .val .d.mut{color:var(--ink3)}
.nm{font-size:15px;color:var(--ink3);border:1.5px dashed var(--mute);border-radius:4px;height:22px;display:flex;align-items:center;padding:0 10px}
"""

ICON_OK = (
    '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="9" fill="#2D6A4F"/>'
    '<path d="M5 9.4l2.6 2.5L13 6.6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
ICON_FAIL = (
    '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="9" fill="#B3443A"/>'
    '<path d="M6 6l6 6M12 6l-6 6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>'
)
ICON_STOP = (
    '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><circle cx="9" cy="9" r="8" fill="none" stroke="#B3443A" stroke-width="2"/>'
    '<path d="M5.5 9h7" stroke="#B3443A" stroke-width="2" stroke-linecap="round"/></svg>'
)


def page(body: str, extra_css: str = "") -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + CSS.replace("__CARD_W__", str(CARD_WIDTH))
        + extra_css
        + "</style></head><body>"
        + body
        + "</body></html>"
    )


# --------------------------------------------------------------------------
# Chart 1: overview
# --------------------------------------------------------------------------

BAR_MAX = 60.0  # % of track used by the longest bar; leaves room for labels


def bar_row(label: str, kind: str, value: float, vmax: float, text: str, dtext: str = "", dclass: str = "neg") -> str:
    w = max(value / vmax * BAR_MAX, 0.4)
    d = f"<span class='d {dclass}'>{esc(dtext)}</span>" if dtext else ""
    return (
        f"<div class='row'><div class='rl'>{esc(label)}</div><div class='track'>"
        f"<div class='bar {kind}' style='width:{w:.3f}%'></div>"
        f"<div class='val'>{esc(text)}{d}</div></div></div>"
    )


def nm_row(label: str, text: str) -> str:
    return (
        f"<div class='row'><div class='rl'>{esc(label)}</div><div class='track'>"
        f"<div class='nm'>{esc(text)}</div></div></div>"
    )


def panel(title: str, sub: str, rows: list[str]) -> str:
    return (
        f"<section class='panel'><h3>{esc(title)}</h3><div class='ps'>{esc(sub)}</div>"
        f"<div class='rows'>{''.join(rows)}</div></section>"
    )


def overview_html(m: dict[str, Any], lang: str) -> str:
    t = T[lang]
    b, j, p = m["base"], m["jev"], m["proj"]
    n = b["n"]
    a, z = m["pair_indices"][0], m["pair_indices"][-1]
    terra = m["routing"]["models"].get(CHEAP_MODEL, 0)
    calls = m["routing"]["total_calls"]
    unc_x = ratio(j["uncached"], b["uncached"])
    bp, jp = f"{b['passed']}/{n}", f"{j['passed']}/{n}"
    lbl = (t["r_base"], t["r_jev"], t["r_proj"])

    head = (
        f"<div class='eyebrow'>{esc(t['ov_eyebrow'].format(n=n, a=a, b=z, date=m['date']))}</div>"
        f"<h1 class='display'>{esc(t['ov_title'].format(bp=bp, jp=jp, x=unc_x))}</h1>"
        f"<div class='sub'>{esc_nw(t['ov_sub'].format(cli=m['codex_cli'], model=m['baseline_model'], effort=m['baseline_effort'], repo=m['harness_repo'], commit=m['harness_commit'], policy=m['policy']), m['policy'], m['harness_repo'] + ' @ ' + m['harness_commit'])}</div>"
    )
    kpis = (
        "<div class='kpis'>"
        f"<div class='kpi'><div class='big display'>{jp}<small>/ {bp}</small></div>"
        f"<div class='lbl'>{esc(t['kpi_pass'].format(bp=bp))}</div></div>"
        f"<div class='kpi'><div class='big display'>{unc_x}</div>"
        f"<div class='lbl'>{esc(t['kpi_unc'].format(j=tok(j['uncached']), b=tok(b['uncached'], 0)))}</div></div>"
        f"<div class='kpi'><div class='big display'>{terra}<small>/ {calls}</small></div>"
        f"<div class='lbl'>{esc(t['kpi_route'].format(cheap=CHEAP_MODEL))}</div></div>"
        "</div>"
    )
    legend = (
        "<div class='legend'>"
        f"<div class='lg'><i class='sw base'></i><div><b>{esc(t['lg_base'])}</b><span>{esc(t['lg_base_sub'].format(model=m['baseline_model'], effort=m['baseline_effort']))}</span></div></div>"
        f"<div class='lg'><i class='sw jev'></i><div><b>{esc(t['lg_jev'])}</b><span>{esc(t['lg_jev_sub'].format(hit=pct(j['cache_hit'])))}</span></div></div>"
        f"<div class='lg'><i class='sw proj'></i><div><b>{esc(t['lg_proj'])}</b><span>{esc(t['lg_proj_sub'].format(hit=pct(b['cache_hit'])))}</span></div></div>"
        "</div>"
    )

    def passtxt(x: dict[str, float]) -> str:
        return f"{x['passed'] / n * 100:.0f}% · {x['passed']}/{n}"

    unc_max = max(b["uncached"], j["uncached"], p["uncached"])
    out_max = max(b["output"], j["output"], p["output"])
    time_max = max(b["duration"], j["duration"])
    steps_max = max(b["steps"], j["steps"])
    mn = t["min"]

    panels = [
        panel(t["p_pass"], t["p_pass_sub"], [
            bar_row(lbl[0], "base", b["passed"], n, passtxt(b)),
            bar_row(lbl[1], "jev", j["passed"], n, passtxt(j)),
            bar_row(lbl[2], "proj", p["passed"], n, passtxt(p)),
        ]),
        panel(t["p_cache"], t["p_cache_sub"], [
            bar_row(lbl[0], "base", b["cache_hit"], 1, pct(b["cache_hit"])),
            bar_row(lbl[1], "jev", j["cache_hit"], 1, pct(j["cache_hit"]),
                    f"−{(b['cache_hit'] - j['cache_hit']) * 100:.1f} pp" if lang == "en" else f"−{(b['cache_hit'] - j['cache_hit']) * 100:.1f} п.п."),
            bar_row(lbl[2], "proj", p["cache_hit"], 1, pct(p["cache_hit"]), t["set_to"], "mut"),
        ]),
        panel(t["p_unc"], t["p_unc_sub"], [
            bar_row(lbl[0], "base", b["uncached"], unc_max, tok(b["uncached"], 0)),
            bar_row(lbl[1], "jev", j["uncached"], unc_max, tok(j["uncached"]), unc_x),
            bar_row(lbl[2], "proj", p["uncached"], unc_max, "~" + tok(p["uncached"], 0), delta(p["uncached"], b["uncached"])),
        ]),
        panel(t["p_out"], t["p_out_sub"], [
            bar_row(lbl[0], "base", b["output"], out_max, tok(b["output"])),
            bar_row(lbl[1], "jev", j["output"], out_max, tok(j["output"]), delta(j["output"], b["output"])),
            bar_row(lbl[2], "proj", p["output"], out_max, tok(p["output"]), delta(p["output"], b["output"])),
        ]),
        panel(t["p_time"], t["p_time_sub"].format(n=n), [
            bar_row(lbl[0], "base", b["duration"], time_max, f"{minutes(b['duration'])} {mn}"),
            bar_row(lbl[1], "jev", j["duration"], time_max, f"{minutes(j['duration'])} {mn}", delta(j["duration"], b["duration"])),
            nm_row(lbl[2], t["not_modeled"]),
        ]),
        panel(t["p_steps"], t["p_steps_sub"], [
            bar_row(lbl[0], "base", b["steps"], steps_max, f"{b['steps']}"),
            bar_row(lbl[1], "jev", j["steps"], steps_max, f"{j['steps']}", delta(j["steps"], b["steps"])),
            bar_row(lbl[2], "proj", p["steps"], steps_max, f"{p['steps']}", delta(p["steps"], b["steps"])),
        ]),
    ]
    foot = f"<div class='foot'>{esc_nw(t['ov_foot'].format(hit=pct(b['cache_hit']), src=SOURCE_LABEL), SOURCE_LABEL)}</div>"
    body = f"<div class='card'>{head}{kpis}{legend}<div class='grid2'>{''.join(panels)}</div>{foot}</div>"
    return page(body)


# --------------------------------------------------------------------------
# Chart 2: per-task breakdown
# --------------------------------------------------------------------------

PT_CSS = """
.ptlegend{display:flex;gap:28px;margin-top:18px}
.tbl{margin-top:18px;border-top:1.5px solid var(--line)}
.thead{display:grid;grid-template-columns:250px 300px minmax(0,1fr) 88px 92px;column-gap:20px}
.thead{font-size:14.5px;font-weight:600;color:var(--ink3);padding:12px 0 10px;border-bottom:1px solid var(--line)}
.thead .r,.c.r{text-align:right}
.task{display:grid;grid-template-columns:250px minmax(0,1fr);column-gap:20px;border-bottom:1px solid var(--grid);padding:12px 0}
.task:last-child{border-bottom:1.5px solid var(--line)}
.tname .ix{font-size:14.5px;font-weight:650;color:var(--ink3)}
.tname .nm2{font-size:17px;font-weight:650;line-height:1.25;margin-top:2px;overflow-wrap:anywhere}
.tname .lng{font-size:14.5px;color:var(--ink3);margin-top:3px}
.sub2{display:grid;grid-template-columns:300px minmax(0,1fr) 88px 92px;column-gap:20px;align-items:center;min-height:38px}
.res{display:flex;align-items:center;gap:8px;font-size:15.5px;white-space:nowrap}
.res svg{flex:none}
.mode{width:8px;height:26px;border-radius:2px;flex:none}
.mode.base{background:var(--base)} .mode.jev{background:var(--jev)}
.res b{font-weight:650}
.res b.ok{color:var(--pass)} .res b.bad{color:var(--jev)}
.res .tc{color:var(--ink2)}
.ub{display:flex;align-items:center;height:24px}
.ub .bar{height:18px}
.ub .val{font-size:16px}
.c{font-size:16px;font-weight:600}
.c.dim{color:var(--ink3);font-weight:500}
.tbl + .foot{border-top:0;padding-top:0}
.qbox{font-size:14.5px;color:var(--jev);border:1.5px dashed var(--jev);border-radius:4px;padding:3px 10px;max-width:100%}
"""


def result_cell(run: dict[str, Any], kind: str, t: dict[str, str], show_p2p: bool) -> str:
    f2p = f"F2P {run['f2p'][0]}/{run['f2p'][1]}"
    p2p = f"P2P {run['p2p'][0]}/{run['p2p'][1]}"
    if not run["valid"]:
        return (
            f"<div class='res'><i class='mode {kind}'></i>{ICON_STOP}<b class='bad'>{esc(t['invalid'])}</b>"
            f"<span class='tc'>quota_fallback_detected</span></div>"
        )
    ok = run["reward"] == 1
    icon, cls, word = (ICON_OK, "ok", t["pass"]) if ok else (ICON_FAIL, "bad", t["fail"])
    tests = f"{f2p} · {p2p}" if show_p2p else f2p
    return f"<div class='res'><i class='mode {kind}'></i>{icon}<b class='{cls}'>{esc(word)}</b><span class='tc'>{esc(tests)}</span></div>"


def per_task_html(m: dict[str, Any], lang: str) -> str:
    t = T[lang]
    tasks = m["tasks"]
    complete = [x for x in tasks if x[BASE]["valid"] and x[JEV]["valid"]]
    ratios = [x[JEV]["uncached"] / x[BASE]["uncached"] for x in complete]
    quota_task = next((x["index"] for x in tasks if not x[JEV]["valid"]), None)
    scale = 3_000_000
    max_unc = max(max(x[BASE]["uncached"], x[JEV]["uncached"]) for x in tasks)
    while scale < max_unc:
        scale += 500_000
    bar_max = 72.0

    head = (
        f"<div class='eyebrow'>{esc(t['pt_eyebrow'].format(date=m['date']))}</div>"
        f"<h1 class='display'>{esc(t['pt_title'].format(lo=f'{min(ratios):.1f}×', hi=f'{max(ratios):.1f}×'))}</h1>"
        f"<div class='sub'>{esc(t['pt_sub'].format(model=m['baseline_model'], effort=m['baseline_effort'], a=tasks[0]['index'], b=tasks[-1]['index'], q=quota_task))}</div>"
        "<div class='ptlegend legend'>"
        f"<div class='lg'><i class='sw base'></i><div><b>{esc(t['lg_base'])}</b><span>{esc(m['baseline_model'])} · {esc(m['baseline_effort'])}</span></div></div>"
        f"<div class='lg'><i class='sw jev'></i><div><b>jev-auto</b><span>{esc(m['harness_repo'])} @ {esc(m['harness_commit'])}</span></div></div>"
        "</div>"
    )
    thead = (
        "<div class='thead'>"
        f"<div>{esc(t['h_task'])}</div><div>{esc(t['h_result'])}</div><div>{esc(t['h_unc'])}</div>"
        f"<div class='r'>{esc(t['h_cache'])}</div><div class='r'>{esc(t['h_time'])}</div></div>"
    )
    rows = []
    for x in tasks:
        bb, jj = x[BASE], x[JEV]
        show_p2p = bb["p2p"] != jj["p2p"] and jj["valid"]
        sub_rows = []
        for mode, kind in ((BASE, "base"), (JEV, "jev")):
            r = x[mode]
            if not r["valid"]:
                bar = f"<div class='ub'><div class='qbox'>{esc(t['quota_bar'])}</div></div>"
                cache = "<div class='c r dim'>—</div>"
            else:
                w = max(r["uncached"] / scale * bar_max, 0.4)
                d = ""
                if mode == JEV and bb["valid"]:
                    d = f"<span class='d neg'>{r['uncached'] / bb['uncached']:.1f}×</span>"
                bar = (
                    f"<div class='ub'><div class='bar {kind}' style='width:{w:.3f}%'></div>"
                    f"<div class='val'>{tok(r['uncached'])}{d}</div></div>"
                )
                cls = "neg" if r["cache_hit"] < 0.9 else ""
                cache = f"<div class='c r {cls}'>{pct(r['cache_hit'])}</div>"
            time = f"<div class='c r'>{minutes(r['duration'])} {t['min']}</div>"
            sub_rows.append(f"<div class='sub2'>{result_cell(r, kind, t, show_p2p)}{bar}{cache}{time}</div>")
        name = (
            f"<div class='tname'><div class='ix'>#{x['index']}</div><div class='nm2'>{esc(x['task_id'])}</div>"
            f"<div class='lng'>{esc(t['lang'].get(x['language'], x['language']))}</div></div>"
        )
        rows.append(f"<div class='task'>{name}<div>{''.join(sub_rows)}</div></div>")
    foot = f"<div class='foot'>{esc_nw(t['pt_foot'].format(max=f"{scale / 1_000_000:g}M", src=SOURCE_LABEL), SOURCE_LABEL)}</div>"
    body = f"<div class='card'>{head}<div class='tbl'>{thead}{''.join(rows)}</div>{foot}</div>"
    return page(body, PT_CSS)


# --------------------------------------------------------------------------
# Chart 3: routing diagnostics
# --------------------------------------------------------------------------

RT_CSS = """
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:24px}
.rp{background:var(--panel);border:1px solid var(--grid);border-radius:14px;padding:20px 22px 18px;display:flex;flex-direction:column}
.rp h3{font-size:19px;font-weight:650}
.rbig{font-size:50px;line-height:1;font-weight:650;letter-spacing:-.02em;margin-top:16px}
.rbig small{font-size:22px;font-weight:600;color:var(--ink3);margin-left:6px;letter-spacing:0}
.rcap{font-size:15.5px;color:var(--ink2);margin-top:6px;min-height:42px}
.stack{display:flex;height:30px;border-radius:5px;overflow:hidden;margin-top:14px;background:var(--grid)}
.stack i{display:block;height:100%}
.stack i + i{box-shadow:inset 1.5px 0 0 var(--panel)}
.k{margin-top:12px;display:grid;gap:6px}
.ki{display:grid;grid-template-columns:14px 1fr auto auto;gap:9px;align-items:center;font-size:15.5px}
.ki .sw{width:13px;height:13px;margin:0;border-radius:3px}
.ki .n{font-weight:650;text-align:right}
.ki .p{color:var(--ink3);text-align:right;min-width:52px}
.ki.empty .sw{background:transparent;box-shadow:inset 0 0 0 1.5px var(--jev)}
.ki.empty span:not(.sw){color:var(--jev)}
.pt{margin-top:18px;padding-top:12px;border-top:1px solid var(--grid)}
.pt .h{font-size:14.5px;font-weight:600;color:var(--ink3);margin-bottom:8px}
.pr{display:grid;grid-template-columns:30px 1fr 64px;gap:10px;align-items:center;height:28px;font-size:15px}
.pr .ix{color:var(--ink3);font-weight:600}
.pr .mini{display:flex;height:14px;border-radius:3px;overflow:hidden;background:var(--grid)}
.pr .mini i{display:block;height:100%}
.pr .mini i + i{box-shadow:inset 1.5px 0 0 var(--panel)}
.pr .n{text-align:right;font-weight:600;white-space:nowrap}
.pr .msbar{height:14px;border-radius:3px;background:var(--base)}
.pr .mstrack{display:flex;align-items:center}
.fbn{color:var(--jev);font-weight:600;font-size:14px;margin-left:8px;white-space:nowrap}
.c-sol{background:var(--base)} .c-high{background:var(--base)} .c-med{background:#8F99A8}
.c-jev{background:var(--base)} .c-lease{background:#8F99A8} .c-fb{background:var(--jev)}
"""


def stack(parts: list[tuple[str, float]], total: float, cls: str = "stack") -> str:
    segs = "".join(f"<i class='{c}' style='width:{v / total * 100:.4f}%'></i>" for c, v in parts if v > 0)
    return f"<div class='{cls}'>{segs}</div>"


def key_item(cls: str, label: str, n: int, total: int, empty: bool = False) -> str:
    return (
        f"<div class='ki{' empty' if empty else ''}'><span class='sw {cls}'></span><span>{esc(label)}</span>"
        f"<span class='n'>{n}</span><span class='p'>{n / total * 100:.1f}%</span></div>"
    )


def routing_html(m: dict[str, Any], lang: str) -> str:
    t = T[lang]
    r = m["routing"]
    total = r["total_calls"]
    sol = m["baseline_model"]
    a, z = m["pair_indices"][0], m["pair_indices"][-1]
    n_sol = r["models"].get(sol, 0)
    n_terra = r["models"].get(CHEAP_MODEL, 0)
    hi, med = r["efforts"].get("high", 0), r["efforts"].get("medium", 0)
    s_jev, s_lease, s_fb = (r["sources"].get(k, 0) for k in ("jev", "lease", "technical_fallback"))

    head = (
        f"<div class='eyebrow'>{esc(t['rt_eyebrow'].format(a=a, b=z, date=m['date']))}</div>"
        f"<h1 class='display'>{esc(t['rt_title'].format(n=total, terra=n_terra, cheap=CHEAP_MODEL))}</h1>"
        f"<div class='sub'>{esc_nw(t['rt_sub'].format(policy=m['policy'], provider=m['decision_provider'], sol=sol), m['policy'])}</div>"
    )

    def pt_rows(fn) -> str:
        return "".join(fn(x) for x in r["per_task"])

    p1_rows = pt_rows(
        lambda x: f"<div class='pr'><span class='ix'>#{x['index']}</span>"
        + stack([("c-sol", x["models"].get(sol, 0))], x["calls"], "mini")
        + f"<span class='n'>{x['models'].get(sol, 0)}/{x['calls']}</span></div>"
    )
    p1 = (
        f"<section class='rp'><h3>{esc(t['rp_model'])}</h3>"
        f"<div class='rbig display'>{n_sol}<small>/ {total}</small></div>"
        f"<div class='rcap'>{esc(t['rp_model_big_cap'].format(sol=sol))}</div>"
        + stack([("c-sol", n_sol), ("c-fb", n_terra)], total)
        + "<div class='k'>"
        + key_item("c-sol", sol, n_sol, total)
        + key_item("", CHEAP_MODEL, n_terra, total, empty=True)
        + f"</div><div class='pt'><div class='h'>{esc(t['per_task'])} · {esc(sol)}</div>{p1_rows}</div></section>"
    )

    p2_rows = pt_rows(
        lambda x: f"<div class='pr'><span class='ix'>#{x['index']}</span>"
        + stack([("c-high", x["efforts"].get("high", 0)), ("c-med", x["efforts"].get("medium", 0))], x["calls"], "mini")
        + f"<span class='n'>{x['efforts'].get('high', 0)} / {x['efforts'].get('medium', 0)}</span></div>"
    )
    p2 = (
        f"<section class='rp'><h3>{esc(t['rp_effort'])}</h3>"
        f"<div class='rbig display'>{hi / total * 100:.1f}%<small>{hi}/{total}</small></div>"
        f"<div class='rcap'>{esc(t['rp_effort_big_cap'])}</div>"
        + stack([("c-high", hi), ("c-med", med)], total)
        + "<div class='k'>"
        + key_item("c-high", t["high"], hi, total)
        + key_item("c-med", t["medium"], med, total)
        + f"</div><div class='pt'><div class='h'>{esc(t['per_task'])} · high / medium</div>{p2_rows}</div></section>"
    )

    ms_max = 2000.0
    while ms_max < max(x["avg_jev_ms"] for x in r["per_task"]):
        ms_max += 500
    p3_rows = pt_rows(
        lambda x: f"<div class='pr' style='grid-template-columns:30px minmax(0,1fr) 196px'><span class='ix'>#{x['index']}</span>"
        f"<div class='mstrack'><div class='msbar' style='width:{x['avg_jev_ms'] / ms_max * 100:.2f}%'></div></div>"
        f"<span class='n'>{x['avg_jev_ms']:.1f} {t['ms']}<span class='fbn'>{timeouts_text(x['timeouts'], lang)}</span></span></div>"
    )
    p3 = (
        f"<section class='rp'><h3>{esc(t['rp_src'])}</h3>"
        f"<div class='rbig display neg'>{s_fb}<small>/ {total} · {s_fb / total * 100:.1f}%</small></div>"
        f"<div class='rcap'>{esc(t['rp_src_big_cap'])}</div>"
        + stack([("c-jev", s_jev), ("c-lease", s_lease), ("c-fb", s_fb)], total)
        + "<div class='k'>"
        + key_item("c-jev", t["src_jev"], s_jev, total)
        + key_item("c-lease", t["src_lease"], s_lease, total)
        + key_item("c-fb", t["src_fb"], s_fb, total)
        + f"</div><div class='pt'><div class='h'>{esc(t['per_task_ms'].format(max=f'{ms_max:.0f}'))}</div>{p3_rows}</div></section>"
    )
    foot = f"<div class='foot'>{esc_nw(t['rt_foot'].format(n=len(r['per_task']), src=SOURCE_LABEL), SOURCE_LABEL)}</div>"
    body = f"<div class='card'>{head}<div class='grid3'>{p1}{p2}{p3}</div>{foot}</div>"
    return page(body, RT_CSS)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

CHARTS = {
    "overview-comparison": overview_html,
    "per-task-breakdown": per_task_html,
    "routing-diagnostics": routing_html,
}


def print_metrics(m: dict[str, Any]) -> None:
    b, j, p = m["base"], m["jev"], m["proj"]
    print(f"pairs {m['pair_indices']}")
    for name, x in (("codex-baseline", b), ("jev-auto", j), ("jev-auto cache-fixed", p)):
        print(
            f"{name:22s} pass {x['passed']}/{x['n']}  prompt {x['prompt']:,.0f}  cached {x['cached']:,.0f} "
            f"({pct(x['cache_hit'])})  uncached {x['uncached']:,.0f}  output {x['output']:,}  "
            f"reasoning {x['reasoning']:,}  steps {x['steps']}  time {x['duration']:.2f}s  partial {x['mean_partial']:.4f}"
        )
    print(f"uncached ratio {ratio(j['uncached'], b['uncached'])}  projected {delta(p['uncached'], b['uncached'])}  "
          f"output {delta(j['output'], b['output'])}  steps {delta(j['steps'], b['steps'])}  "
          f"time {delta(j['duration'], b['duration'])}  reasoning {delta(j['reasoning'], b['reasoning'])}")
    r = m["routing"]
    print(f"routing calls {r['total_calls']} models {r['models']} efforts {r['efforts']} sources {r['sources']}")
    print("avg_jev_ms " + ", ".join(f"#{x['index']} {x['avg_jev_ms']}" for x in r["per_task"]))
    for x in m["tasks"]:
        bb, jj = x[BASE], x[JEV]
        rr = f"{jj['uncached'] / bb['uncached']:.1f}x" if jj["valid"] else "n/a"
        print(f"#{x['index']} {x['task_id']}: uncached {bb['uncached']:,} vs {jj['uncached']:,} ({rr})")


def render(
    m: dict[str, Any], out_dir: Path, langs: list[str], html_dir: Path | None, chromium: Path | None = None
) -> list[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - environment dependent
        sys.exit("playwright is not installed: pip install playwright && python -m playwright install chromium")

    written: list[Path] = []
    with sync_playwright() as pw:
        launch_kwargs: dict[str, Any] = {}
        if chromium is not None:
            launch_kwargs["executable_path"] = str(chromium)
        browser = pw.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(viewport={"width": CARD_WIDTH + 40, "height": 900}, device_scale_factor=2)
        pg = ctx.new_page()
        for lang in langs:
            target = out_dir / lang
            target.mkdir(parents=True, exist_ok=True)
            for name, builder in CHARTS.items():
                doc = builder(m, lang)
                if html_dir is not None:
                    (html_dir / lang).mkdir(parents=True, exist_ok=True)
                    (html_dir / lang / f"{name}.html").write_text(doc, encoding="utf-8")
                pg.set_content(doc, wait_until="load")
                pg.evaluate("document.fonts.ready")
                path = target / f"{name}.png"
                pg.locator(".card").screenshot(path=str(path), omit_background=True)
                written.append(path)
                print(f"wrote {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")
        browser.close()
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output root; PNGs go to <out>/<lang>/")
    ap.add_argument("--lang", choices=["en", "ru"], action="append", help="render one language (repeatable)")
    ap.add_argument("--html-dir", type=Path, help="also write the intermediate HTML here")
    ap.add_argument(
        "--chromium",
        type=Path,
        default=os.environ.get("CHARTS_CHROMIUM") or None,
        help="Chromium/headless-shell executable to use instead of Playwright's bundled build "
        "(also read from CHARTS_CHROMIUM)",
    )
    ap.add_argument("--print-metrics", action="store_true", help="print computed numbers and exit")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    metrics = compute_metrics(summary, manifest)
    print_metrics(metrics)
    if args.print_metrics:
        return 0
    render(metrics, args.out, args.lang or ["en", "ru"], args.html_dir, args.chromium)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
