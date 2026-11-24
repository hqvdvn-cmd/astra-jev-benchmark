"""Aggregation and paired reporting for DeepSWE Pier benchmark runs."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _parse_iso(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        cleaned = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).timestamp()
    except ValueError:
        return None


def find_latest_trial_dir(job_dir: Path, task_id: str) -> Path | None:
    """Locate the most recent trial directory inside a Pier job directory.

    Pier truncates the task-name prefix in ``<prefix>__<hash>`` trial folder
    names to 32 characters for long ``task_id`` values, so match any ``*__*``
    directory whose prefix is a non-empty prefix of ``task_id``.
    """
    if not job_dir.is_dir():
        return None
    candidates: list[Path] = []
    for path in job_dir.rglob("*__*"):
        if not path.is_dir():
            continue
        prefix = path.name.split("__", 1)[0]
        if not prefix or not task_id.startswith(prefix):
            continue
        if (path / "result.json").is_file() or (
            path / "verifier" / "reward.json"
        ).is_file():
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def parse_trajectory_metrics(trajectory_path: Path) -> dict[str, Any]:
    """Extract token counts from a Pier ATIF v1.7 ``agent/trajectory.json`` file."""
    data = _read_json(trajectory_path)
    if not data:
        return {
            "present": False,
            "prompt_tokens": 0,
            "cached_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "steps": 0,
        }

    fm = data.get("final_metrics") or {}
    extra = fm.get("extra") or {}
    steps = data.get("steps") or []

    prompt_tokens = int(fm.get("total_prompt_tokens") or 0)
    cached_tokens = int(fm.get("total_cached_tokens") or 0)
    completion_tokens = int(fm.get("total_completion_tokens") or 0)
    reasoning_tokens = int(
        extra.get("reasoning_tokens")
        or extra.get("total_reasoning_tokens")
        or fm.get("total_reasoning_tokens")
        or 0
    )

    if reasoning_tokens == 0 and isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            sm = step.get("metrics") or {}
            se = sm.get("extra") or {}
            reasoning_tokens += int(
                se.get("reasoning_tokens")
                or se.get("reasoning_output_tokens")
                or sm.get("reasoning_tokens")
                or 0
            )

    return {
        "present": True,
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "steps": len(steps) if isinstance(steps, list) else 0,
    }


def summarize_jev_log_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize ``jev-router-live.jsonl`` records collected during a single trial."""
    models: Counter[str] = Counter()
    efforts: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    gates: Counter[str] = Counter()
    policy_versions: Counter[str] = Counter()
    lease_hits = 0
    quota_fallback_events = 0
    error_events = 0
    jev_ms_total = 0
    jev_ms_count = 0

    for rec in records:
        model = str(rec.get("model") or rec.get("tier") or "unknown")
        models[model] += 1
        effort = str(
            rec.get("effective_effort")
            or rec.get("effort")
            or rec.get("depth")
            or "unset"
        )
        efforts[effort] += 1
        source = str(rec.get("decision_source") or "unknown")
        sources[source] += 1
        if rec.get("lease_hit") or source == "lease":
            lease_hits += 1
        gate = str(rec.get("gate") or "")
        if gate:
            gates[gate] += 1
        if "codex_dry" in gate or rec.get("ladder_stage") not in (None, "", "native"):
            quota_fallback_events += 1
        pv = rec.get("policy_version")
        if pv:
            policy_versions[str(pv)] += 1
        status = rec.get("status")
        if isinstance(status, int) and status >= 400:
            error_events += 1
        jev_ms = rec.get("jev_ms")
        if isinstance(jev_ms, (int, float)):
            jev_ms_total += int(jev_ms)
            jev_ms_count += 1

    return {
        "total_calls": len(records),
        "models": dict(models),
        "efforts": dict(efforts),
        "decision_sources": dict(sources),
        "gates": dict(gates),
        "policy_versions": dict(policy_versions),
        "lease_hits": lease_hits,
        "quota_fallback_events": quota_fallback_events,
        "quota_fallback_detected": quota_fallback_events > 0,
        "error_events": error_events,
        "avg_jev_ms": round(jev_ms_total / jev_ms_count, 1) if jev_ms_count else None,
    }


def read_jev_log_slice(log_path: Path, start_line: int = 0) -> list[dict[str, Any]]:
    """Read new JSONL entries from ``jev-router-live.jsonl`` starting at 0-based ``start_line``."""
    if not log_path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for idx, line in enumerate(handle):
            if idx < start_line:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except ValueError:
                continue
            if isinstance(obj, dict):
                records.append(obj)
    return records


def count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def extract_trial_summary(
    trial_dir: Path | None,
    *,
    mode: str,
    task_id: str,
    jev_records: list[dict[str, Any]] | None = None,
    returncode: int | None = None,
    wall_sec: float | None = None,
) -> dict[str, Any]:
    """Build a normalized summary record for one (task_id, mode) Pier trial."""
    result_json = _read_json(trial_dir / "result.json") if trial_dir else None
    reward_json = (
        _read_json(trial_dir / "verifier" / "reward.json") if trial_dir else None
    )
    traj = (
        parse_trajectory_metrics(trial_dir / "agent" / "trajectory.json")
        if trial_dir
        else parse_trajectory_metrics(Path("__missing__"))
    )

    duration_sec = wall_sec
    if duration_sec is None and result_json:
        t0 = _parse_iso(result_json.get("started_at"))
        t1 = _parse_iso(result_json.get("finished_at"))
        if t0 is not None and t1 is not None and t1 >= t0:
            duration_sec = round(t1 - t0, 2)

    exception_info = result_json.get("exception_info") if result_json else None
    jev_summary = (
        summarize_jev_log_records(jev_records) if jev_records is not None else None
    )
    quota_fallback = bool(
        jev_summary and jev_summary.get("quota_fallback_detected")
    )

    reward = reward_json.get("reward") if reward_json else None
    valid = (
        trial_dir is not None
        and reward is not None
        and exception_info is None
        and (returncode in (None, 0))
        and not quota_fallback
    )

    return {
        "task_id": task_id,
        "mode": mode,
        "trial_dir": str(trial_dir) if trial_dir else None,
        "returncode": returncode,
        "valid": valid,
        "invalid_reason": (
            "quota_fallback_detected"
            if quota_fallback
            else (
                str(exception_info.get("exception_type") or "trial_exception")
                if isinstance(exception_info, dict)
                else ("missing_reward" if reward is None else None)
            )
        ),
        "duration_sec": round(duration_sec, 2) if duration_sec is not None else None,
        "reward": reward,
        "partial": reward_json.get("partial") if reward_json else None,
        "f2p_passed": reward_json.get("f2p_passed") if reward_json else None,
        "f2p_total": reward_json.get("f2p_total") if reward_json else None,
        "p2p_passed": reward_json.get("p2p_passed") if reward_json else None,
        "p2p_total": reward_json.get("p2p_total") if reward_json else None,
        "tokens": traj,
        "jev_routing": jev_summary,
    }


def _fmt_num(val: Any) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


def render_markdown_summary(summary: dict[str, Any]) -> str:
    """Render a concise Markdown table comparing paired modes across tasks."""
    lines: list[str] = [
        f"# DeepSWE Paired Benchmark Summary — `{summary.get('run_name', 'run')}`",
        "",
        f"- Manifest: `{summary.get('manifest_name', '')}`",
        f"- Updated: `{summary.get('updated_at', '')}`",
        f"- Modes: {', '.join(f'`{m}`' for m in summary.get('modes', []))}",
        "",
        "## Per-Task Paired Results",
        "",
        "| # | Task | Lang | Mode | Valid | Reward | F2P | Partial | Time (s) | Prompt Tok | Cached Tok | Output Tok | Jev Routes |",
        "|---:|---|---|---|---|---:|---|---:|---:|---:|---:|---:|---|",
    ]

    for pair in summary.get("pairs", []):
        idx = pair.get("index", "")
        task_id = pair.get("task_id", "")
        lang = pair.get("language", "")
        runs = pair.get("runs", {})
        for mode in summary.get("modes", []):
            rec = runs.get(mode)
            if not rec:
                lines.append(
                    f"| {idx} | `{task_id}` | {lang} | `{mode}` | pending | — | — | — | — | — | — | — | — |"
                )
                continue
            tok = rec.get("tokens") or {}
            f2p = (
                f"{rec.get('f2p_passed')}/{rec.get('f2p_total')}"
                if rec.get("f2p_total") is not None
                else "—"
            )
            jev = rec.get("jev_routing") or {}
            if jev.get("total_calls"):
                routes_str = ", ".join(
                    f"{k}:{v}" for k, v in sorted((jev.get("models") or {}).items())
                )
                if jev.get("quota_fallback_detected"):
                    routes_str += " [FALLBACK]"
            else:
                routes_str = "—"
            valid_str = "yes" if rec.get("valid") else f"no ({rec.get('invalid_reason') or 'err'})"
            lines.append(
                f"| {idx} | `{task_id}` | {lang} | `{mode}` | {valid_str} "
                f"| {_fmt_num(rec.get('reward'))} | {f2p} | {_fmt_num(rec.get('partial'))} "
                f"| {_fmt_num(rec.get('duration_sec'))} "
                f"| {tok.get('prompt_tokens', 0)} | {tok.get('cached_tokens', 0)} "
                f"| {tok.get('completion_tokens', 0)} | {routes_str} |"
            )

    agg = summary.get("aggregate", {})
    if agg:
        lines.extend(["", "## Aggregate by Mode", ""])
        lines.append(
            "| Mode | Completed | Valid | Pass (reward=1) | Mean Partial | Total Prompt Tok | Total Cached Tok | Total Output Tok |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for mode, stats in agg.items():
            lines.append(
                f"| `{mode}` | {stats['completed']} | {stats['valid']} "
                f"| {stats['passed']} | {_fmt_num(stats['mean_partial'])} "
                f"| {stats['prompt_tokens']} | {stats['cached_tokens']} | {stats['completion_tokens']} |"
            )

    lines.append("")
    return "\n".join(lines)


def compute_aggregate(
    pairs: list[dict[str, Any]], modes: list[str]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for mode in modes:
        completed = 0
        valid = 0
        passed = 0
        partials: list[float] = []
        prompt_tok = 0
        cached_tok = 0
        comp_tok = 0
        for pair in pairs:
            rec = (pair.get("runs") or {}).get(mode)
            if not rec:
                continue
            completed += 1
            if not rec.get("valid"):
                continue
            valid += 1
            if rec.get("reward") == 1:
                passed += 1
            if isinstance(rec.get("partial"), (int, float)):
                partials.append(float(rec["partial"]))
            tok = rec.get("tokens") or {}
            prompt_tok += int(tok.get("prompt_tokens") or 0)
            cached_tok += int(tok.get("cached_tokens") or 0)
            comp_tok += int(tok.get("completion_tokens") or 0)
        result[mode] = {
            "completed": completed,
            "valid": valid,
            "passed": passed,
            "mean_partial": round(sum(partials) / len(partials), 4) if partials else None,
            "prompt_tokens": prompt_tok,
            "cached_tokens": cached_tok,
            "completion_tokens": comp_tok,
        }
    return result
