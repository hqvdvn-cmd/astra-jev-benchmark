from __future__ import annotations

from .model import TaskSpec


CODE_STRATEGY_CHOICES = (
    "edit_then_test",
    "inspect_then_edit_test",
    "test_only",
)

_STRATEGY_INSTRUCTIONS = {
    "edit_then_test": "Make the smallest required edit, then run the declared tests.",
    "inspect_then_edit_test": (
        "Inspect the relevant file first, make the smallest edit, then run the declared tests."
    ),
    "test_only": "Run the declared tests first; edit only when the failure proves it is needed.",
}


def strategy_instruction(choice: str) -> str:
    try:
        return _STRATEGY_INSTRUCTIONS[choice]
    except KeyError as error:
        raise ValueError(f"unknown offload strategy: {choice}") from error


def strategy_prompt(task: TaskSpec, choice: str, retry_instruction: str | None = None) -> str:
    parts = [task.prompt]
    if retry_instruction:
        parts.append(
            "The previous pass did not meet the completion gate. "
            f"{retry_instruction} Review the existing workspace before editing."
        )
    parts.append(f"Bounded strategy selected by Jev: {strategy_instruction(choice)}")
    return "\n\n".join(parts)
