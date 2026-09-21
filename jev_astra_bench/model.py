from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

TaskKind = Literal["code_write", "bug_fix", "browser"]
RunMode = Literal[
    "astra_only",
    "astra_jev_observe",
    "astra_jev_offload",
    "astra_jev_guarded",
    "astra_jev_offload_guarded",
]
DecisionStatus = Literal["ok", "unavailable", "invalid_response"]
GuardPolicy = Literal["fail_closed", "deterministic_fallback"]
GuardChoice = Literal[
    "accept",
    "retry_tests",
    "retry_scope",
    "retry_simplify",
    "retry_missing_change",
    "reject",
]


@dataclass(slots=True, frozen=True)
class TaskSpec:
    task_id: str
    kind: TaskKind
    prompt: str
    fixture_dir: Path
    verifier: str
    browser_profile: str | None = None
    allowed_files: tuple[str, ...] = ()
    requirements: tuple[str, ...] = ()
    review_changed_lines_above: int | None = None


@dataclass(slots=True, frozen=True)
class DecisionResult:
    status: DecisionStatus
    choice: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_code: str | None = None


@dataclass(slots=True, frozen=True)
class PassRecord:
    pass_number: int
    trigger: str
    duration_s: float | None
    astra_input_tokens: int | None
    astra_cached_input_tokens: int | None
    astra_cache_write_input_tokens: int | None
    astra_output_tokens: int | None
    jev_input_tokens: int | None
    jev_output_tokens: int | None
    tool_calls: int
    verification_status: str
    failure_reason: str | None
    changed_files: tuple[str, ...]
    added_lines: int
    deleted_lines: int
    jev_choice: str | None
    jev_strategy_choices: tuple[str, ...] = ()
    jev_guard_choice: str | None = None
    jev_strategy_calls: int = 0
    jev_guard_calls: int = 0

    @classmethod
    def from_public_dict(cls, data: dict[str, Any]) -> "PassRecord":
        values = dict(data)
        values["changed_files"] = tuple(values.get("changed_files", ()))
        values["jev_strategy_choices"] = tuple(values.get("jev_strategy_choices", ()))
        return cls(**values)


@dataclass(slots=True)
class AttemptRecord:
    task_id: str
    mode: RunMode
    repeat: int
    task_kind: str | None = None
    harness_version: str = "0.1.0"
    codex_version: str | None = None
    astra_model: str = "gpt-6-astra"
    reasoning_effort: str = "xhigh"
    jev_model: str | None = None
    pricing_source: str | None = None
    pricing_date: str | None = None
    started_at: str | None = None
    duration_s: float | None = None
    astra_input_tokens: int | None = None
    astra_cached_input_tokens: int | None = None
    astra_cache_write_input_tokens: int | None = None
    astra_output_tokens: int | None = None
    jev_input_tokens: int | None = None
    jev_output_tokens: int | None = None
    jev_calls: int = 0
    tool_calls: int = 0
    codex_exit_code: int | None = None
    codex_completed: bool = False
    codex_timed_out: bool = False
    codex_malformed_events: int = 0
    retries: int = 0
    success: bool = False
    verification_status: str = "not_run"
    failure_reason: str | None = None
    browser_action: str | None = None
    browser_target: str | None = None
    browser_state_hash: str | None = None
    jev_choice: str | None = None
    estimated_cost_usd: str | None = None
    cost_status: str = "unavailable"
    passes: list[PassRecord] = field(default_factory=list)
    guard_status: str | None = None
    max_astra_passes: int | None = None
    jev_strategy_choices: list[str] = field(default_factory=list)
    jev_strategy_calls: int = 0
    jev_guard_calls: int = 0

    def to_public_dict(self) -> dict[str, Any]:
        """Return only bounded measurement fields suitable for a JSON log."""
        return asdict(self)

    @classmethod
    def from_public_dict(cls, data: dict[str, Any]) -> "AttemptRecord":
        values = dict(data)
        values["passes"] = [PassRecord.from_public_dict(item) for item in values.get("passes", [])]
        values["jev_strategy_choices"] = list(values.get("jev_strategy_choices", []))
        return cls(**values)
