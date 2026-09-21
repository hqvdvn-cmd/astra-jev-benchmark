from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Callable, Protocol

from .codex_runner import CodexAttempt
from .model import AttemptRecord, DecisionResult, GuardPolicy, PassRecord, RunMode, TaskSpec
from .offload import CODE_STRATEGY_CHOICES, strategy_prompt
from .pricing import Pricing, estimate_cost
from .redaction import redact_state
from .verification import VerificationResult


class JevDecider(Protocol):
    def decide(self, question: str, state: dict[str, object], choices: list[str]) -> DecisionResult: ...


class GuardContext(Protocol):
    codex_runner: Callable[[str, Path], CodexAttempt]
    jev_client: JevDecider | None
    pricing: Pricing
    workspace_factory: Callable[[TaskSpec, int], Path]
    verifier: Callable[[TaskSpec, Path], VerificationResult]


@dataclass(slots=True, frozen=True)
class GuardConfig:
    max_astra_passes: int = 2
    outage_policy: GuardPolicy = "fail_closed"

    def __post_init__(self) -> None:
        if self.max_astra_passes not in {1, 2, 3}:
            raise ValueError("max_astra_passes must be 1, 2, or 3")


GUARD_CHOICES = [
    "accept",
    "retry_tests",
    "retry_scope",
    "retry_simplify",
    "retry_missing_change",
    "reject",
]

HARD_FAILURE_CHOICES = {
    "changed_file_outside_allow_list": "retry_scope",
    "tests_failed": "retry_tests",
    "invalid_verifier": "retry_tests",
    "verifier_error": "retry_tests",
}

RETRY_INSTRUCTIONS = {
    "retry_tests": "Run the declared checks and make the result satisfy every named requirement.",
    "retry_scope": "Reduce the change to the declared scope and preserve passing tests.",
    "retry_simplify": "Review the diff and replace unnecessary code with the smallest change that satisfies the task.",
    "retry_missing_change": "Inspect the required behavior, make the missing change, and verify it.",
}


def add_optional(total: int | None, value: int | None) -> int | None:
    if total is None or value is None:
        return None
    return total + value


def accumulate_codex(record: AttemptRecord, attempt: CodexAttempt) -> None:
    record.astra_input_tokens = add_optional(record.astra_input_tokens, attempt.parsed.input_tokens)
    record.astra_cached_input_tokens = add_optional(
        record.astra_cached_input_tokens,
        attempt.parsed.cached_input_tokens,
    )
    record.astra_cache_write_input_tokens = add_optional(
        record.astra_cache_write_input_tokens,
        attempt.parsed.cache_write_input_tokens,
    )
    record.astra_output_tokens = add_optional(record.astra_output_tokens, attempt.parsed.output_tokens)
    record.tool_calls += attempt.parsed.tool_calls
    record.codex_exit_code = attempt.exit_code
    record.codex_completed = record.codex_completed or attempt.parsed.completed
    record.codex_timed_out = record.codex_timed_out or attempt.timed_out
    record.codex_malformed_events += attempt.parsed.malformed_events


def _accumulate_jev(record: AttemptRecord, result: DecisionResult) -> None:
    record.jev_calls += 1
    record.jev_input_tokens = add_optional(record.jev_input_tokens, result.input_tokens)
    record.jev_output_tokens = add_optional(record.jev_output_tokens, result.output_tokens)
    record.jev_choice = result.choice


def _decision_tokens(results: tuple[DecisionResult | None, ...], field: str) -> int | None:
    total = 0
    for result in results:
        if result is None:
            continue
        value = getattr(result, field)
        if value is None:
            return None
        total += value
    return total


def _retry_prompt(task: TaskSpec, choice: str) -> str:
    instruction = RETRY_INSTRUCTIONS[choice]
    return (
        f"{task.prompt}\n\n"
        "The previous pass did not meet the completion gate. "
        f"{instruction} Review the existing workspace before editing."
    )


def _guard_evidence(
    task: TaskSpec,
    verified: VerificationResult,
    attempt: CodexAttempt,
    pass_number: int,
) -> dict[str, object]:
    return {
        "task_kind": task.kind,
        "requirements": task.requirements,
        "verification_status": verified.status,
        "changed_files": verified.changed_files,
        "added_lines": verified.added_lines,
        "deleted_lines": verified.deleted_lines,
        "changed_lines": verified.changed_lines,
        "review_changed_lines_above": task.review_changed_lines_above,
        "tool_calls": attempt.parsed.tool_calls,
        "pass_number": pass_number,
    }


def _apply_cost(record: AttemptRecord, pricing: Pricing) -> AttemptRecord:
    estimate = estimate_cost(record, pricing)
    record.cost_status = estimate.status
    record.estimated_cost_usd = str(estimate.amount_usd) if estimate.amount_usd is not None else None
    return record


def _append_pass(
    record: AttemptRecord,
    pass_number: int,
    trigger: str,
    duration_s: float,
    attempt: CodexAttempt,
    verified: VerificationResult,
    strategy_result: DecisionResult | None,
    guard_result: DecisionResult | None,
    choice: str | None,
) -> None:
    record.passes.append(
        PassRecord(
            pass_number=pass_number,
            trigger=trigger,
            duration_s=duration_s,
            astra_input_tokens=attempt.parsed.input_tokens,
            astra_cached_input_tokens=attempt.parsed.cached_input_tokens,
            astra_cache_write_input_tokens=attempt.parsed.cache_write_input_tokens,
            astra_output_tokens=attempt.parsed.output_tokens,
            jev_input_tokens=_decision_tokens((strategy_result, guard_result), "input_tokens"),
            jev_output_tokens=_decision_tokens((strategy_result, guard_result), "output_tokens"),
            tool_calls=attempt.parsed.tool_calls,
            verification_status=verified.status,
            failure_reason=verified.failure_reason,
            changed_files=verified.changed_files,
            added_lines=verified.added_lines,
            deleted_lines=verified.deleted_lines,
            jev_choice=choice,
            jev_strategy_choices=(strategy_result.choice,) if strategy_result and strategy_result.choice else (),
            jev_guard_choice=guard_result.choice if guard_result is not None else None,
            jev_strategy_calls=1 if strategy_result is not None else 0,
            jev_guard_calls=1 if guard_result is not None else 0,
        )
    )


def _finish(record: AttemptRecord, pricing: Pricing, started: float) -> AttemptRecord:
    record.retries = max(0, len(record.passes) - 1)
    record.duration_s = time.monotonic() - started
    return _apply_cost(record, pricing)


def run_guarded_attempt(
    task: TaskSpec,
    repeat: int,
    context: GuardContext,
    config: GuardConfig,
    mode: RunMode = "astra_jev_guarded",
) -> AttemptRecord:
    if mode not in {"astra_jev_guarded", "astra_jev_offload_guarded"}:
        raise ValueError(f"unsupported guarded mode: {mode}")
    record = AttemptRecord(
        task_id=task.task_id,
        mode=mode,
        repeat=repeat,
        task_kind=task.kind,
        started_at=datetime.now(timezone.utc).isoformat(),
        pricing_source=context.pricing.pricing_source,
        pricing_date=context.pricing.pricing_date,
        astra_input_tokens=0,
        astra_cached_input_tokens=0,
        astra_cache_write_input_tokens=0,
        astra_output_tokens=0,
        jev_input_tokens=0,
        jev_output_tokens=0,
        max_astra_passes=config.max_astra_passes,
    )
    workspace = context.workspace_factory(task, repeat)
    started = time.monotonic()
    trigger = "initial"

    for pass_number in range(1, config.max_astra_passes + 1):
        strategy_result: DecisionResult | None = None
        if mode == "astra_jev_offload_guarded":
            if context.jev_client is None:
                strategy_result = DecisionResult("unavailable", error_code="jev_not_configured")
            else:
                strategy_result = context.jev_client.decide(
                    "Choose the smallest safe strategy for this guarded pass.",
                    redact_state(
                        {
                            "task_id": task.task_id,
                            "task_kind": task.kind,
                            "requirements": task.requirements,
                            "pass_number": pass_number,
                            "retry_choice": None if trigger == "initial" else trigger,
                        }
                    ),
                    list(CODE_STRATEGY_CHOICES),
                )
            _accumulate_jev(record, strategy_result)
            record.jev_strategy_calls += 1
            if strategy_result.choice:
                record.jev_strategy_choices.append(strategy_result.choice)
            if strategy_result.status != "ok" or strategy_result.choice not in CODE_STRATEGY_CHOICES:
                record.guard_status = "not_checked_by_jev"
                record.verification_status = "not_checked_by_jev"
                record.failure_reason = strategy_result.error_code or strategy_result.status
                return _finish(record, context.pricing, started)
            retry_instruction = RETRY_INSTRUCTIONS.get(trigger) if trigger != "initial" else None
            prompt = strategy_prompt(task, strategy_result.choice, retry_instruction)
        else:
            prompt = task.prompt if trigger == "initial" else _retry_prompt(task, trigger)

        pass_started = time.monotonic()
        attempt = context.codex_runner(prompt, workspace)
        accumulate_codex(record, attempt)
        guard_result: DecisionResult | None = None

        if attempt.timed_out or attempt.exit_code != 0 or not attempt.parsed.completed:
            failure = "timeout" if attempt.timed_out else f"exit_{attempt.exit_code}"
            verified = VerificationResult(False, "codex_failed", failure)
            choice = "retry_tests"
        else:
            verified = context.verifier(task, workspace)
            choice = HARD_FAILURE_CHOICES.get(verified.status, "retry_tests") if not verified.success else None
            if verified.success and task.kind in {"code_write", "bug_fix"} and not verified.changed_files:
                choice = "retry_missing_change"

        if choice is None:
            if context.jev_client is None:
                guard_result = DecisionResult("unavailable", error_code="jev_not_configured")
            else:
                guard_result = context.jev_client.decide(
                    "Choose the guarded completion verdict.",
                    redact_state(_guard_evidence(task, verified, attempt, pass_number)),
                    GUARD_CHOICES,
                )
            _accumulate_jev(record, guard_result)
            record.jev_guard_calls += 1
            choice = guard_result.choice if guard_result.status == "ok" else None

        _append_pass(
            record,
            pass_number,
            trigger,
            time.monotonic() - pass_started,
            attempt,
            verified,
            strategy_result,
            guard_result,
            choice,
        )
        record.verification_status = verified.status
        record.failure_reason = verified.failure_reason
        record.jev_choice = choice

        if guard_result is not None and (guard_result.status != "ok" or choice not in GUARD_CHOICES):
            record.guard_status = "not_checked_by_jev"
            record.failure_reason = guard_result.error_code or guard_result.status
            if config.outage_policy == "deterministic_fallback" and verified.success:
                record.success = True
                record.guard_status = "deterministic_fallback"
            else:
                record.verification_status = "not_checked_by_jev"
            return _finish(record, context.pricing, started)

        if choice == "accept":
            record.success = verified.success
            record.guard_status = "accepted" if record.success else "deterministic_failure"
            return _finish(record, context.pricing, started)
        if choice == "reject":
            record.guard_status = "rejected"
            record.failure_reason = "guard_rejected"
            return _finish(record, context.pricing, started)
        if pass_number == config.max_astra_passes:
            record.guard_status = "retry_limit"
            record.failure_reason = choice or verified.failure_reason or "retry_limit"
            return _finish(record, context.pricing, started)

        trigger = choice or "retry_tests"

    raise RuntimeError("guarded pass loop ended without a result")
