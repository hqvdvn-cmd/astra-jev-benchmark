from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .aggregate import aggregate_pairs
from .browser import FakeBrowserAdapter
from .browser_runner import run_browser_attempt
from .codex_events import ParsedCodexEvents
from .codex_runner import CodexAttempt, CodexConfig, run_codex
from .guarded import GuardConfig
from .jev_client import JevClient, JevConfig
from .model import AttemptRecord, DecisionResult, RunMode, TaskSpec
from .modes import HarnessContext, run_attempt
from .pricing import Pricing
from .tasks import copy_fixture, load_manifest
from .verification import verify_task

PACKAGE_ROOT = Path(__file__).parents[1]
DEFAULT_MANIFEST = PACKAGE_ROOT / "tasks" / "manifest.json"
MODES: tuple[RunMode, ...] = (
    "astra_only",
    "astra_jev_observe",
    "astra_jev_offload",
    "astra_jev_guarded",
    "astra_jev_offload_guarded",
)
MODE_CODES: dict[RunMode, str] = {
    "astra_only": "a",
    "astra_jev_observe": "jo",
    "astra_jev_offload": "jf",
    "astra_jev_guarded": "jg",
    "astra_jev_offload_guarded": "jfg",
}


class SimulatedJevClient:
    def decide(self, question, state, choices):
        if "accept" in choices:
            choice = "accept"
        elif "sufficient" in choices:
            choice = "sufficient"
        elif "inspect_then_edit_test" in choices:
            choice = "inspect_then_edit_test"
        else:
            choice = choices[0]
        return DecisionResult("ok", choice, input_tokens=8, output_tokens=0)


def _simulate_codex(prompt: str, workspace: Path) -> CodexAttempt:
    if (workspace / "slugify.py").exists():
        (workspace / "slugify.py").write_text(
            "import re\n\ndef slugify(value: str) -> str:\n"
            "    return re.sub(r'[^\\w]+', '-', value.lower(), flags=re.UNICODE).strip('-')\n",
            encoding="utf-8",
        )
    if (workspace / "clamp.py").exists():
        (workspace / "clamp.py").write_text(
            "def clamp(value: float, lower: float, upper: float) -> float:\n"
            "    if lower > upper:\n        raise ValueError('lower exceeds upper')\n"
            "    return min(upper, max(value, lower))\n",
            encoding="utf-8",
        )
    if "Extract the email" in prompt:
        final_text = json.dumps({"value": "test@example.com"})
    elif "Allowed:" in prompt and "fill:email" in prompt and "email_filled=True" not in prompt:
        final_text = json.dumps({"choice": "fill:email", "value": "test@example.com"})
    elif "Allowed:" in prompt:
        final_text = json.dumps({"choice": "click:submit"})
    else:
        final_text = "simulated"
    parsed = ParsedCodexEvents(final_text, 120, 40, 2, 0, True)
    return CodexAttempt(parsed, 0.01, 0, False, ("simulated-codex",))


def _pricing(path: Path | None) -> Pricing:
    return Pricing.from_toml(path) if path else Pricing()


def _record_dict(record: AttemptRecord) -> dict[str, object]:
    return record.to_public_dict()


def _workspace_prefix(mode: RunMode, task_id: str, repeat: int) -> str:
    task_code = "".join(character for character in task_id.lower() if character.isalnum())[:8] or "task"
    return f"ja-{MODE_CODES[mode]}-{task_code}-{repeat}-"


def rotated_modes(modes: Sequence[RunMode], repeat: int) -> tuple[RunMode, ...]:
    if not modes:
        return ()
    offset = (repeat - 1) % len(modes)
    return tuple(modes[offset:]) + tuple(modes[:offset])


def _make_workspace_dir(root: Path, mode: RunMode, task_id: str, repeat: int) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    prefix = _workspace_prefix(mode, task_id, repeat)
    for _ in range(100):
        candidate = root / f"{prefix}{secrets.token_hex(4)}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise RuntimeError("could not allocate a unique benchmark workspace")


def _codex_version(simulate: bool) -> str | None:
    if simulate:
        return "simulated"
    try:
        result = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _percent_change(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline in (None, 0):
        return None
    return (current - baseline) / baseline * 100


def _known_sum(values: Sequence[int | None]) -> int | None:
    return sum(value for value in values if value is not None) if all(value is not None for value in values) else None


def write_report(records: Sequence[AttemptRecord], output: Path) -> dict[str, object]:
    summaries = aggregate_pairs(records)
    modes: dict[str, dict[str, object]] = {}
    for mode in MODES:
        selected = [record for record in records if record.mode == mode]
        if not selected:
            continue
        known_costs = [float(record.estimated_cost_usd) for record in selected if record.estimated_cost_usd is not None]
        durations = [record.duration_s for record in selected if record.duration_s is not None]
        total_duration = sum(durations) if len(durations) == len(selected) else None
        successes = sum(1 for record in selected if record.success)
        total_cost = sum(known_costs) if len(known_costs) == len(selected) else None
        jev_calls = sum(record.jev_calls for record in selected)
        jev_strategy_calls = sum(record.jev_strategy_calls for record in selected)
        jev_guard_calls = sum(record.jev_guard_calls for record in selected)
        modes[mode] = {
            "attempts": len(selected),
            "successes": successes,
            "success_rate": successes / len(selected),
            "duration_total_s": total_duration,
            "mean_duration_s": total_duration / len(selected) if total_duration is not None else None,
            "astra_input_tokens": _known_sum([record.astra_input_tokens for record in selected]),
            "astra_cached_input_tokens": _known_sum([record.astra_cached_input_tokens for record in selected]),
            "astra_cache_write_input_tokens": _known_sum(
                [record.astra_cache_write_input_tokens for record in selected]
            ),
            "astra_output_tokens": _known_sum([record.astra_output_tokens for record in selected]),
            "jev_input_tokens": (
                0 if jev_calls == 0 else _known_sum([record.jev_input_tokens for record in selected if record.jev_calls])
            ),
            "jev_calls": jev_calls,
            "jev_strategy_calls": jev_strategy_calls,
            "jev_guard_calls": jev_guard_calls,
            "mean_jev_calls_per_attempt": jev_calls / len(selected),
            "jev_unavailable": sum(1 for record in selected if record.verification_status == "not_checked_by_jev"),
            "pass_count": sum(len(record.passes) for record in selected),
            "retry_count": sum(record.retries for record in selected),
            "improved_after_retry": sum(1 for record in selected if record.success and record.retries > 0),
            "guard_unavailable": sum(1 for record in selected if record.guard_status == "not_checked_by_jev"),
            "estimated_cost_usd": total_cost,
            "cost_per_success_usd": total_cost / successes if total_cost is not None and successes else None,
            "cost_status": "calculated" if len(known_costs) == len(selected) else "unavailable",
        }
    comparisons: dict[str, object] = {}
    baseline = modes.get("astra_only")
    if baseline:
        for mode in (
            "astra_jev_observe",
            "astra_jev_offload",
            "astra_jev_guarded",
            "astra_jev_offload_guarded",
        ):
            current = modes.get(mode)
            if not current:
                continue
            base_cost = baseline["cost_per_success_usd"]
            current_cost = current["cost_per_success_usd"]
            comparisons[mode] = {
                "duration_change_pct": _percent_change(current["mean_duration_s"], baseline["mean_duration_s"]),
                "astra_input_token_change_pct": _percent_change(current["astra_input_tokens"], baseline["astra_input_tokens"]),
                "success_rate_change_points": (current["success_rate"] - baseline["success_rate"]) * 100,
                "cost_savings_pct": (
                    (base_cost - current_cost) / base_cost * 100
                    if base_cost not in (None, 0) and current_cost is not None
                    else None
                ),
            }
    pair_index = {(summary.task_id, summary.mode): summary for summary in summaries}
    pair_comparisons: dict[str, object] = {}
    for task_id in sorted({summary.task_id for summary in summaries}):
        task_baseline = pair_index.get((task_id, "astra_only"))
        if task_baseline is None:
            continue
        task_modes: dict[str, object] = {}
        for mode in (
            "astra_jev_observe",
            "astra_jev_offload",
            "astra_jev_guarded",
            "astra_jev_offload_guarded",
        ):
            current = pair_index.get((task_id, mode))
            if current is None:
                continue
            base_cost = float(task_baseline.cost_per_success_usd) if task_baseline.cost_per_success_usd is not None else None
            current_cost = float(current.cost_per_success_usd) if current.cost_per_success_usd is not None else None
            task_modes[mode] = {
                "duration_change_pct": _percent_change(current.mean_duration_s, task_baseline.mean_duration_s),
                "success_rate_change_points": (
                    current.successful_tasks / current.attempts - task_baseline.successful_tasks / task_baseline.attempts
                ) * 100,
                "cost_savings_pct": (
                    (base_cost - current_cost) / base_cost * 100
                    if base_cost not in (None, 0) and current_cost is not None
                    else None
                ),
            }
        pair_comparisons[task_id] = task_modes
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "records": len(records),
        "run_metadata": {
            "harness_versions": sorted({record.harness_version for record in records}),
            "codex_versions": sorted({record.codex_version for record in records if record.codex_version}),
            "astra_models": sorted({record.astra_model for record in records}),
            "reasoning_efforts": sorted({record.reasoning_effort for record in records}),
            "jev_models": sorted({record.jev_model for record in records if record.jev_model}),
            "pricing_sources": sorted({record.pricing_source for record in records if record.pricing_source}),
            "pricing_dates": sorted({record.pricing_date for record in records if record.pricing_date}),
        },
        "modes": modes,
        "comparisons_to_astra_only": comparisons,
        "task_comparisons_to_astra_only": pair_comparisons,
        "pairs": [
            {
                **asdict(summary),
                "total_cost_usd": str(summary.total_cost_usd) if summary.total_cost_usd is not None else None,
                "mean_attempt_cost_usd": str(summary.mean_attempt_cost_usd) if summary.mean_attempt_cost_usd is not None else None,
                "cost_per_success_usd": str(summary.cost_per_success_usd) if summary.cost_per_success_usd is not None else None,
            }
            for summary in summaries
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_records(path: Path) -> list[AttemptRecord]:
    source = path / "attempts.jsonl" if path.is_dir() else path
    records: list[AttemptRecord] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(AttemptRecord.from_public_dict(json.loads(line)))
    return records


def _record_key(record: AttemptRecord) -> tuple[int, str, RunMode]:
    return record.repeat, record.task_id, record.mode


def _is_infrastructure_failure(record: AttemptRecord) -> bool:
    return record.codex_exit_code not in (None, 0) and not record.codex_completed


def _prepare_resume(records_path: Path) -> tuple[list[AttemptRecord], set[tuple[int, str, RunMode]]]:
    if not records_path.exists():
        return [], set()
    prior = read_records(records_path)
    interrupted = [record for record in prior if _is_infrastructure_failure(record)]
    if interrupted:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = records_path.with_name(f"attempts.interrupted-{stamp}.jsonl")
        shutil.copy2(records_path, archive)
    kept = [record for record in prior if not _is_infrastructure_failure(record)]
    return kept, {_record_key(record) for record in kept}


def compare_reports(left: Path, right: Path, output: Path) -> dict[str, object]:
    def load(path: Path) -> dict[str, object]:
        report = path / "report.json" if path.is_dir() else path
        return json.loads(report.read_text(encoding="utf-8"))
    a, b = load(left), load(right)
    comparison: dict[str, object] = {"left": str(left), "right": str(right), "modes": {}}
    for mode in sorted(set(a.get("modes", {})) | set(b.get("modes", {}))):
        left_mode = a.get("modes", {}).get(mode)
        right_mode = b.get("modes", {}).get(mode)
        comparison["modes"][mode] = {"left": left_mode, "right": right_mode}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    return comparison


def preflight(args: argparse.Namespace) -> tuple[bool, dict[str, object]]:
    tasks = load_manifest(args.task_set)
    selected_ids = set(getattr(args, "task_id", []) or [])
    if selected_ids:
        tasks = [task for task in tasks if task.task_id in selected_ids]
    selected_modes = getattr(args, "mode", ["astra_only"])
    needs_jev = any(mode != "astra_only" for mode in selected_modes)
    simulate = getattr(args, "simulate", False)
    result = {
        "python": platform.python_version(),
        "python_ok": sys.version_info >= (3, 11),
        "codex_path": shutil.which("codex"),
        "codex_ok": bool(shutil.which("codex")) or simulate,
        "model": "gpt-6-astra",
        "tasks": len(tasks),
        "fixtures_ok": all(task.fixture_dir.exists() for task in tasks),
        "playwright_present": importlib.util.find_spec("playwright") is not None,
        "browser_tasks": sum(1 for task in tasks if task.kind == "browser"),
        "jev_key_present": bool(os.environ.get("TYPESAFE_API_KEY")),
        "jev_required": needs_jev and not simulate,
        "simulate": simulate,
    }
    ok = bool(result["python_ok"] and result["codex_ok"] and result["fixtures_ok"])
    if result["jev_required"] and not result["jev_key_present"]:
        ok = False
    if not simulate and result["browser_tasks"] and not result["playwright_present"]:
        ok = False
    result["ok"] = ok
    return ok, result


def run_command(args: argparse.Namespace) -> int:
    ok, checks = preflight(args)
    if not ok:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 2
    tasks = load_manifest(args.task_set)
    if args.task_id:
        selected_ids = set(args.task_id)
        tasks = [task for task in tasks if task.task_id in selected_ids]
        missing = selected_ids - {task.task_id for task in tasks}
        if missing:
            print(f"Unknown task ids: {', '.join(sorted(missing))}")
            return 2
    args.output.mkdir(parents=True, exist_ok=True)
    records_path = args.output / "attempts.jsonl"
    pricing = _pricing(args.config)
    guard_config = GuardConfig(args.max_astra_passes, args.guard_outage_policy)
    codex_version = _codex_version(args.simulate)
    records, completed = _prepare_resume(records_path) if args.resume else ([], set())
    workspace_root = (args.workspace_root or PACKAGE_ROOT / "results" / "_workspaces").resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    with records_path.open("w", encoding="utf-8") as sink:
        for record in records:
            sink.write(json.dumps(_record_dict(record), ensure_ascii=False) + "\n")
        sink.flush()
        for repeat in range(1, args.repeats + 1):
            for task in tasks:
                for mode in rotated_modes(args.mode, repeat):
                    if (repeat, task.task_id, mode) in completed:
                        continue
                    temp_roots: list[Path] = []
                    def workspace_factory(spec: TaskSpec, number: int) -> Path:
                        root = _make_workspace_dir(workspace_root, mode, spec.task_id, number)
                        temp_roots.append(root)
                        return copy_fixture(spec, number, root)
                    if args.simulate:
                        codex_runner = _simulate_codex
                        jev_client = SimulatedJevClient() if mode != "astra_only" else None
                    else:
                        config = CodexConfig(model="gpt-6-astra", reasoning_effort=args.reasoning_effort)
                        codex_runner = lambda prompt, workspace, config=config: run_codex(prompt, workspace, config)
                        jev_client = JevClient(JevConfig()) if mode != "astra_only" else None
                    record: AttemptRecord | None = None
                    try:
                        if task.kind == "browser":
                            record = run_browser_attempt(
                                task,
                                mode,
                                repeat,
                                codex_runner,
                                jev_client,
                                pricing,
                                FakeBrowserAdapter() if args.simulate else None,
                                guard_config,
                            )
                        else:
                            context = HarnessContext(codex_runner, jev_client, pricing, workspace_factory, verify_task)
                            record = run_attempt(task, mode, repeat, context, guard_config)
                    finally:
                        keep = bool(args.keep_failed_workspaces and record is not None and not record.success)
                        if not keep:
                            for root in temp_roots:
                                shutil.rmtree(root, ignore_errors=True)
                        elif temp_roots:
                            print(f"BENCHMARK_WORKSPACE_RETAINED task={task.task_id} root={temp_roots[0]}")
                    if record is None:
                        raise RuntimeError("attempt finished without a record")
                    record.codex_version = codex_version
                    record.reasoning_effort = args.reasoning_effort
                    record.jev_model = "jev-1.13.0" if mode != "astra_only" else None
                    records.append(record)
                    sink.write(json.dumps(_record_dict(record), ensure_ascii=False) + "\n")
                    sink.flush()
                    if _is_infrastructure_failure(record):
                        write_report(records, args.output / "report.json")
                        print(
                            "BENCHMARK_INFRASTRUCTURE_FAILURE "
                            f"task={record.task_id} mode={record.mode} repeat={record.repeat} "
                            f"exit_code={record.codex_exit_code}"
                        )
                        return 3
    write_report(records, args.output / "report.json")
    print(f"BENCHMARK_RUN_OK output={args.output} records={len(records)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jev-astra-benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--task-set", type=Path, default=DEFAULT_MANIFEST)
    common.add_argument("--config", type=Path)
    common.add_argument("--simulate", action="store_true")
    common.add_argument("--mode", action="append", choices=MODES, default=[])
    common.add_argument("--task-id", action="append", default=[])
    preflight_parser = sub.add_parser("preflight", parents=[common])
    run_parser = sub.add_parser("run", parents=[common])
    run_parser.add_argument("--repeats", type=int, default=3)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--reasoning-effort", default="xhigh")
    run_parser.add_argument("--workspace-root", type=Path)
    run_parser.add_argument("--keep-failed-workspaces", action="store_true")
    run_parser.add_argument("--max-astra-passes", type=int, choices=(1, 2, 3), default=2)
    run_parser.add_argument(
        "--guard-outage-policy",
        choices=("fail_closed", "deterministic_fallback"),
        default="fail_closed",
    )
    run_parser.add_argument("--resume", action="store_true")
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--input", type=Path, required=True)
    report_parser.add_argument("--output", type=Path, required=True)
    compare_parser = sub.add_parser("compare")
    compare_parser.add_argument("--left", type=Path, required=True)
    compare_parser.add_argument("--right", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if hasattr(args, "mode") and not args.mode:
        args.mode = ["astra_only"]
    if args.command == "preflight":
        ok, checks = preflight(args)
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0 if ok else 2
    if args.command == "run":
        if args.repeats < 1:
            parser.error("--repeats must be at least 1")
        return run_command(args)
    if args.command == "report":
        records = read_records(args.input)
        write_report(records, args.output)
        return 0
    if args.command == "compare":
        compare_reports(args.left, args.right, args.output)
        return 0
    return 2
