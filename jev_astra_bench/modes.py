from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Callable, Protocol

from .codex_runner import CodexAttempt
from .guarded import GuardConfig, run_guarded_attempt
from .jev_client import JevClient
from .model import AttemptRecord, DecisionResult, RunMode, TaskSpec
from .offload import CODE_STRATEGY_CHOICES, strategy_prompt
from .pricing import Pricing, estimate_cost
from .redaction import redact_state
from .verification import VerificationResult, verify_task


class CodexRunner(Protocol):
    def __call__(self, prompt: str, workspace: Path) -> CodexAttempt: ...


@dataclass(slots=True)
class HarnessContext:
    codex_runner: CodexRunner
    jev_client: JevClient | None
    pricing: Pricing
    workspace_factory: Callable[[TaskSpec, int], Path]
    verifier: Callable[[TaskSpec, Path], VerificationResult] = verify_task


def _jev_decision(
    client: JevClient | None,
    question: str,
    state: dict[str, object],
    choices: list[str],
) -> DecisionResult:
    if client is None:
        return DecisionResult("unavailable", error_code="jev_not_configured")
    return client.decide(question, redact_state(state), choices)


def run_attempt(
    task: TaskSpec,
    mode: RunMode,
    repeat: int,
    context: HarnessContext,
    guard_config: GuardConfig | None = None,
) -> AttemptRecord:
    if mode in {"astra_jev_guarded", "astra_jev_offload_guarded"}:
        return run_guarded_attempt(task, repeat, context, guard_config or GuardConfig(), mode)
    record = AttemptRecord(
        task_id=task.task_id,
        mode=mode,
        repeat=repeat,
        task_kind=task.kind,
        started_at=datetime.now(timezone.utc).isoformat(),
        pricing_source=context.pricing.pricing_source,
        pricing_date=context.pricing.pricing_date,
    )
    workspace = context.workspace_factory(task, repeat)
    started = time.monotonic()
    jev_result: DecisionResult | None = None
    prompt = task.prompt
    if mode == "astra_jev_offload":
        jev_result = _jev_decision(
            context.jev_client,
            "Choose the smallest safe strategy for this task.",
            {"task_id": task.task_id, "task_kind": task.kind, "verifier_present": bool(task.verifier)},
            list(CODE_STRATEGY_CHOICES),
        )
        record.jev_calls = 1
        record.jev_strategy_calls = 1
        record.jev_input_tokens = jev_result.input_tokens
        record.jev_output_tokens = jev_result.output_tokens
        record.jev_choice = jev_result.choice
        if jev_result.choice:
            record.jev_strategy_choices.append(jev_result.choice)
        if jev_result.status == "ok":
            prompt = strategy_prompt(task, jev_result.choice)
        elif task.kind == "browser":
            record.duration_s = time.monotonic() - started
            record.verification_status = "not_checked_by_jev"
            record.failure_reason = jev_result.error_code
            return _finalize(record, context.pricing)
        else:
            record.verification_status = "not_checked_by_jev"
            record.failure_reason = jev_result.error_code
    codex = context.codex_runner(prompt, workspace)
    record.astra_input_tokens = codex.parsed.input_tokens
    record.astra_cached_input_tokens = codex.parsed.cached_input_tokens
    record.astra_cache_write_input_tokens = codex.parsed.cache_write_input_tokens
    record.astra_output_tokens = codex.parsed.output_tokens
    record.tool_calls = codex.parsed.tool_calls
    record.codex_exit_code = codex.exit_code
    record.codex_completed = codex.parsed.completed
    record.codex_timed_out = codex.timed_out
    record.codex_malformed_events = codex.parsed.malformed_events
    if codex.timed_out or codex.exit_code != 0 or not codex.parsed.completed:
        record.duration_s = time.monotonic() - started
        record.verification_status = "codex_failed"
        record.failure_reason = "timeout" if codex.timed_out else f"exit_{codex.exit_code}"
        return _finalize(record, context.pricing)
    evidence = {
        "task_kind": task.kind,
        "codex_completed": codex.parsed.completed,
        "agent_message_present": bool(codex.parsed.final_text),
        "tool_calls": codex.parsed.tool_calls,
    }
    if mode == "astra_jev_observe":
        jev_result = _jev_decision(context.jev_client, "Is the evidence sufficient?", evidence, ["sufficient", "insufficient"])
        record.jev_calls = 1
    verified = context.verifier(task, workspace)
    record.success = verified.success
    record.verification_status = verified.status
    record.failure_reason = verified.failure_reason
    if jev_result is not None:
        record.jev_input_tokens = jev_result.input_tokens
        record.jev_output_tokens = jev_result.output_tokens
        record.jev_choice = jev_result.choice
        if jev_result.status == "unavailable":
            record.verification_status = "not_checked_by_jev"
    record.duration_s = time.monotonic() - started
    return _finalize(record, context.pricing)


def _finalize(record: AttemptRecord, pricing: Pricing) -> AttemptRecord:
    estimate = estimate_cost(record, pricing)
    record.cost_status = estimate.status
    record.estimated_cost_usd = str(estimate.amount_usd) if estimate.amount_usd is not None else None
    return record
