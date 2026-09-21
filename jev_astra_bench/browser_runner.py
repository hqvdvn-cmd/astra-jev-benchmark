from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .browser import BrowserAdapter, BrowserChoice, LocalPlaywrightSession
from .codex_runner import CodexAttempt
from .guarded import GuardConfig, add_optional
from .jev_client import JevClient
from .model import AttemptRecord, DecisionResult, PassRecord, RunMode, TaskSpec
from .pricing import Pricing, estimate_cost

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _sum_optional(current: int | None, value: int | None) -> int | None:
    if current is None or value is None:
        return None
    return current + value


def _extract_choice(text: str | None, allowed: tuple[str, ...]) -> str | None:
    if not text:
        return None
    try:
        data = json.loads(text)
        choice = data.get("choice") if isinstance(data, dict) else None
        if choice in allowed:
            return choice
    except json.JSONDecodeError:
        pass
    matches = [choice for choice in allowed if choice in text]
    return matches[0] if len(matches) == 1 else None


def _extract_email(text: str | None) -> str | None:
    match = _EMAIL.search(text or "")
    return match.group(0) if match else None


def _apply_cost(record: AttemptRecord, pricing: Pricing) -> AttemptRecord:
    estimate = estimate_cost(record, pricing)
    record.cost_status = estimate.status
    record.estimated_cost_usd = str(estimate.amount_usd) if estimate.amount_usd is not None else None
    return record


def _accumulate_browser_pass(record: AttemptRecord, current: AttemptRecord) -> None:
    record.astra_input_tokens = add_optional(record.astra_input_tokens, current.astra_input_tokens)
    record.astra_cached_input_tokens = add_optional(
        record.astra_cached_input_tokens,
        current.astra_cached_input_tokens,
    )
    record.astra_cache_write_input_tokens = add_optional(
        record.astra_cache_write_input_tokens,
        current.astra_cache_write_input_tokens,
    )
    record.astra_output_tokens = add_optional(record.astra_output_tokens, current.astra_output_tokens)
    record.tool_calls += current.tool_calls
    record.codex_exit_code = current.codex_exit_code
    record.codex_completed = record.codex_completed or current.codex_completed
    record.codex_timed_out = record.codex_timed_out or current.codex_timed_out
    record.codex_malformed_events += current.codex_malformed_events
    record.browser_action = current.browser_action
    record.browser_target = current.browser_target
    record.browser_state_hash = current.browser_state_hash
    record.jev_calls += current.jev_calls
    strategy_input = current.jev_input_tokens if current.jev_calls else 0
    strategy_output = current.jev_output_tokens if current.jev_calls else 0
    record.jev_input_tokens = add_optional(record.jev_input_tokens, strategy_input)
    record.jev_output_tokens = add_optional(record.jev_output_tokens, strategy_output)
    record.jev_strategy_calls += current.jev_strategy_calls
    record.jev_strategy_choices.extend(current.jev_strategy_choices)


def _finish_guarded_browser(record: AttemptRecord, pricing: Pricing, started: float) -> AttemptRecord:
    record.retries = max(0, len(record.passes) - 1)
    record.duration_s = time.monotonic() - started
    return _apply_cost(record, pricing)


def _run_guarded_browser_attempt(
    task: TaskSpec,
    repeat: int,
    codex_runner: Callable[[str, Path], CodexAttempt],
    jev_client: JevClient | None,
    pricing: Pricing,
    adapter: BrowserAdapter | None,
    config: GuardConfig,
    mode: RunMode,
) -> AttemptRecord:
    record = AttemptRecord(
        task.task_id,
        mode,
        repeat,
        task_kind=task.kind,
        started_at=datetime.now(timezone.utc).isoformat(),
        pricing_source=pricing.pricing_source,
        pricing_date=pricing.pricing_date,
        astra_input_tokens=0,
        astra_cached_input_tokens=0,
        astra_cache_write_input_tokens=0,
        astra_output_tokens=0,
        jev_input_tokens=0,
        jev_output_tokens=0,
        max_astra_passes=config.max_astra_passes,
    )
    started = time.monotonic()
    session = None
    if adapter is None:
        session = LocalPlaywrightSession(task.fixture_dir / "page.html")
        adapter = session.__enter__()
    trigger = "initial"
    try:
        for pass_number in range(1, config.max_astra_passes + 1):
            pass_mode: RunMode = "astra_jev_offload" if mode == "astra_jev_offload_guarded" else "astra_only"
            current = run_browser_attempt(
                task,
                pass_mode,
                repeat,
                codex_runner,
                jev_client if pass_mode == "astra_jev_offload" else None,
                pricing,
                adapter,
            )
            _accumulate_browser_pass(record, current)
            decision: DecisionResult | None = None
            if current.success:
                if jev_client is None:
                    decision = DecisionResult("unavailable", error_code="jev_not_configured")
                else:
                    decision = jev_client.decide(
                        "Choose the guarded browser completion verdict.",
                        {
                            "requirements": task.requirements,
                            "verification_status": current.verification_status,
                            "browser_action": current.browser_action,
                            "browser_target": current.browser_target,
                            "pass_number": pass_number,
                        },
                        ["accept", "retry_tests", "retry_scope", "reject"],
                    )
                record.jev_calls += 1
                record.jev_input_tokens = add_optional(record.jev_input_tokens, decision.input_tokens)
                record.jev_output_tokens = add_optional(record.jev_output_tokens, decision.output_tokens)
                record.jev_guard_calls += 1
                choice = decision.choice if decision.status == "ok" else None
            else:
                choice = "retry_tests"

            record.passes.append(
                PassRecord(
                    pass_number=pass_number,
                    trigger=trigger,
                    duration_s=current.duration_s,
                    astra_input_tokens=current.astra_input_tokens,
                    astra_cached_input_tokens=current.astra_cached_input_tokens,
                    astra_cache_write_input_tokens=current.astra_cache_write_input_tokens,
                    astra_output_tokens=current.astra_output_tokens,
                    jev_input_tokens=add_optional(
                        current.jev_input_tokens if current.jev_calls else 0,
                        decision.input_tokens if decision else 0,
                    ),
                    jev_output_tokens=add_optional(
                        current.jev_output_tokens if current.jev_calls else 0,
                        decision.output_tokens if decision else 0,
                    ),
                    tool_calls=current.tool_calls,
                    verification_status=current.verification_status,
                    failure_reason=current.failure_reason,
                    changed_files=(),
                    added_lines=0,
                    deleted_lines=0,
                    jev_choice=choice,
                    jev_strategy_choices=tuple(current.jev_strategy_choices),
                    jev_guard_choice=decision.choice if decision is not None else None,
                    jev_strategy_calls=current.jev_strategy_calls,
                    jev_guard_calls=1 if decision is not None else 0,
                )
            )
            record.verification_status = current.verification_status
            record.failure_reason = current.failure_reason
            record.jev_choice = choice

            if decision is not None and (decision.status != "ok" or choice is None):
                record.guard_status = "not_checked_by_jev"
                record.failure_reason = decision.error_code or decision.status
                if config.outage_policy == "deterministic_fallback" and current.success:
                    record.success = True
                    record.guard_status = "deterministic_fallback"
                else:
                    record.verification_status = "not_checked_by_jev"
                return _finish_guarded_browser(record, pricing, started)
            if choice == "accept":
                record.success = current.success
                record.guard_status = "accepted" if record.success else "deterministic_failure"
                return _finish_guarded_browser(record, pricing, started)
            if choice == "reject":
                record.guard_status = "rejected"
                record.failure_reason = "guard_rejected"
                return _finish_guarded_browser(record, pricing, started)
            if pass_number == config.max_astra_passes:
                record.guard_status = "retry_limit"
                record.failure_reason = choice or current.failure_reason or "retry_limit"
                return _finish_guarded_browser(record, pricing, started)
            adapter.reset()
            trigger = choice or "retry_tests"
    finally:
        if session is not None:
            session.__exit__(None, None, None)
    raise RuntimeError("guarded browser pass loop ended without a result")


def run_browser_attempt(
    task: TaskSpec,
    mode: RunMode,
    repeat: int,
    codex_runner: Callable[[str, Path], CodexAttempt],
    jev_client: JevClient | None,
    pricing: Pricing,
    adapter: BrowserAdapter | None = None,
    guard_config: GuardConfig | None = None,
) -> AttemptRecord:
    if mode in {"astra_jev_guarded", "astra_jev_offload_guarded"}:
        return _run_guarded_browser_attempt(
            task,
            repeat,
            codex_runner,
            jev_client,
            pricing,
            adapter,
            guard_config or GuardConfig(),
            mode,
        )
    record = AttemptRecord(
        task.task_id,
        mode,
        repeat,
        task_kind=task.kind,
        started_at=datetime.now(timezone.utc).isoformat(),
        pricing_source=pricing.pricing_source,
        pricing_date=pricing.pricing_date,
    )
    started = time.monotonic()
    session = None
    if adapter is None:
        session = LocalPlaywrightSession(task.fixture_dir / "page.html")
        adapter = session.__enter__()
    try:
        email_value: str | None = None
        if mode == "astra_jev_offload":
            record.jev_input_tokens = 0
            record.jev_output_tokens = 0
            value_attempt = codex_runner(
                f"Extract the email value required by this browser task. Return JSON only: {{\"value\":\"...\"}}.\nTask: {task.prompt}",
                task.fixture_dir,
            )
            record.astra_input_tokens = value_attempt.parsed.input_tokens
            record.astra_cached_input_tokens = value_attempt.parsed.cached_input_tokens
            record.astra_cache_write_input_tokens = value_attempt.parsed.cache_write_input_tokens
            record.astra_output_tokens = value_attempt.parsed.output_tokens
            record.tool_calls += value_attempt.parsed.tool_calls
            record.codex_exit_code = value_attempt.exit_code
            record.codex_completed = value_attempt.parsed.completed
            record.codex_timed_out = value_attempt.timed_out
            record.codex_malformed_events += value_attempt.parsed.malformed_events
            email_value = _extract_email(value_attempt.parsed.final_text)
            if not email_value:
                record.failure_reason = "astra_value_missing"
                record.verification_status = "browser_failed"
                return _apply_cost(record, pricing)
        else:
            record.astra_input_tokens = 0
            record.astra_cached_input_tokens = 0
            record.astra_cache_write_input_tokens = 0
            record.astra_output_tokens = 0
        for _ in range(4):
            snapshot = adapter.snapshot()
            if "state=submitted" in snapshot.state:
                record.success = True
                record.verification_status = "verified"
                break
            choice: str | None
            decision: DecisionResult | None = None
            if mode == "astra_jev_offload":
                if jev_client is None:
                    record.verification_status = "not_checked_by_jev"
                    record.failure_reason = "jev_not_configured"
                    break
                decision = jev_client.decide(
                    "Choose the next browser action.",
                    {"page_state": snapshot.state},
                    snapshot.candidates,
                )
                record.jev_calls += 1
                record.jev_strategy_calls += 1
                record.jev_input_tokens = _sum_optional(record.jev_input_tokens, decision.input_tokens)
                record.jev_output_tokens = _sum_optional(record.jev_output_tokens, decision.output_tokens)
                choice = decision.choice if decision.status == "ok" else None
                record.jev_choice = choice
                if choice:
                    record.jev_strategy_choices.append(choice)
            else:
                action_attempt = codex_runner(
                    "Choose one allowed browser action and return JSON only with keys choice and value. "
                    f"Allowed: {list(snapshot.candidates)}. Page: {snapshot.state}. Task: {task.prompt}",
                    task.fixture_dir,
                )
                record.astra_input_tokens = _sum_optional(record.astra_input_tokens, action_attempt.parsed.input_tokens)
                record.astra_cached_input_tokens = _sum_optional(
                    record.astra_cached_input_tokens,
                    action_attempt.parsed.cached_input_tokens,
                )
                record.astra_cache_write_input_tokens = _sum_optional(
                    record.astra_cache_write_input_tokens,
                    action_attempt.parsed.cache_write_input_tokens,
                )
                record.astra_output_tokens = _sum_optional(record.astra_output_tokens, action_attempt.parsed.output_tokens)
                record.tool_calls += action_attempt.parsed.tool_calls
                record.codex_exit_code = action_attempt.exit_code
                record.codex_completed = record.codex_completed or action_attempt.parsed.completed
                record.codex_timed_out = record.codex_timed_out or action_attempt.timed_out
                record.codex_malformed_events += action_attempt.parsed.malformed_events
                choice = _extract_choice(action_attempt.parsed.final_text, snapshot.candidates)
                email_value = email_value or _extract_email(action_attempt.parsed.final_text)
                if mode == "astra_jev_observe" and jev_client is not None:
                    if record.jev_calls == 0:
                        record.jev_input_tokens = 0
                        record.jev_output_tokens = 0
                    decision = jev_client.decide(
                        "Is the proposed browser action allowed by the supplied candidates?",
                        {"choice": choice, "page_state": snapshot.state},
                        ["allowed", "not_allowed"],
                    )
                    record.jev_calls += 1
                    record.jev_input_tokens = _sum_optional(record.jev_input_tokens, decision.input_tokens)
                    record.jev_output_tokens = _sum_optional(record.jev_output_tokens, decision.output_tokens)
                    record.jev_choice = decision.choice
            if not choice:
                record.verification_status = "not_checked_by_jev" if decision and decision.status != "ok" else "browser_failed"
                record.failure_reason = decision.error_code if decision else "choice_missing"
                break
            operation, target = choice.split(":", 1)
            result = adapter.perform(BrowserChoice(operation, target, email_value if choice == "fill:email" else None))
            record.browser_action = operation
            record.browser_target = target
            if not result.success:
                record.verification_status = "browser_failed"
                record.failure_reason = result.error
                break
        final_state = adapter.snapshot().state
        record.browser_state_hash = hashlib.sha256(final_state.encode("utf-8")).hexdigest()
        if not record.success and record.failure_reason is None:
            record.failure_reason = "step_limit"
            record.verification_status = "browser_failed"
    finally:
        if session is not None:
            session.__exit__(None, None, None)
        record.duration_s = time.monotonic() - started
    return _apply_cost(record, pricing)
