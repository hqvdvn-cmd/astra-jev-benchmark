from __future__ import annotations

import shlex
import subprocess
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path

from .model import TaskSpec


@dataclass(slots=True, frozen=True)
class VerificationResult:
    success: bool
    status: str
    failure_reason: str | None
    changed_files: tuple[str, ...] = ()
    added_lines: int = 0
    deleted_lines: int = 0

    @property
    def changed_lines(self) -> int:
        return self.added_lines + self.deleted_lines


def verify_task(task: TaskSpec, workspace: Path) -> VerificationResult:
    changed = _changed_files(workspace, task.fixture_dir)
    added, deleted = _diff_line_counts(workspace, task.fixture_dir, changed)
    if task.allowed_files and any(path not in task.allowed_files for path in changed):
        return VerificationResult(
            False,
            "changed_file_outside_allow_list",
            "unexpected_file_change",
            changed,
            added,
            deleted,
        )
    if not task.verifier:
        return VerificationResult(True, "no_verifier", None, changed, added, deleted)
    command = shlex.split(task.verifier, posix=True)
    if not command:
        return VerificationResult(False, "invalid_verifier", "empty_verifier", changed, added, deleted)
    try:
        result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        return VerificationResult(False, "verifier_error", type(error).__name__, changed, added, deleted)
    if result.returncode != 0:
        return VerificationResult(False, "tests_failed", f"exit_{result.returncode}", changed, added, deleted)
    return VerificationResult(True, "verified", None, changed, added, deleted)


def _text_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    data = path.read_bytes()
    if b"\x00" in data:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def _diff_line_counts(workspace: Path, baseline: Path, changed: tuple[str, ...]) -> tuple[int, int]:
    if not baseline.exists() or baseline.resolve() == workspace.resolve():
        return 0, 0
    added = 0
    deleted = 0
    for name in changed:
        before = _text_lines(baseline / name)
        after = _text_lines(workspace / name)
        for tag, before_start, before_end, after_start, after_end in SequenceMatcher(None, before, after).get_opcodes():
            if tag in {"replace", "delete"}:
                deleted += before_end - before_start
            if tag in {"replace", "insert"}:
                added += after_end - after_start
    return added, deleted


def _files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _changed_files(workspace: Path, baseline: Path) -> tuple[str, ...]:
    if baseline.exists() and baseline.resolve() != workspace.resolve():
        before = _files(baseline)
        after = _files(workspace)
        names = set(before) | set(after)
        return tuple(sorted(name for name in names if before.get(name) != after.get(name)))
    result = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
