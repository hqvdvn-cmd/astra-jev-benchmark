from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .codex_events import ParsedCodexEvents, parse_codex_events


@dataclass(slots=True, frozen=True)
class CodexConfig:
    model: str = "gpt-6-astra"
    reasoning_effort: str = "xhigh"
    timeout_s: int = 900
    executable: str = "codex"
    executable_prefix: tuple[str, ...] = ()
    sandbox: str = "workspace-write"
    approval: str = "never"


@dataclass(slots=True, frozen=True)
class CodexAttempt:
    parsed: ParsedCodexEvents
    duration_s: float
    exit_code: int | None
    timed_out: bool
    command: tuple[str, ...]


def build_command(prompt: str, workspace: Path, config: CodexConfig) -> list[str]:
    return [
        config.executable,
        *config.executable_prefix,
        "exec",
        "--json",
        "--ephemeral",
        "--disable",
        "plugins",
        "--disable",
        "hooks",
        "--disable",
        "apps",
        "--disable",
        "memories",
        "--disable",
        "multi_agent",
        "--enable",
        "skip_host_skill_discovery",
        "--skip-git-repo-check",
        "-C",
        str(workspace),
        "-m",
        config.model,
        "-c",
        f'model_reasoning_effort="{config.reasoning_effort}"',
        "-c",
        f'approval_policy="{config.approval}"',
        "-c",
        "suppress_unstable_features_warning=true",
        "-s",
        config.sandbox,
        prompt,
    ]


def run_codex(prompt: str, workspace: Path, config: CodexConfig) -> CodexAttempt:
    workspace_root = workspace.resolve()
    powershell_root = str(workspace_root).replace("'", "''")
    platform_prompt = (
        f"{prompt}\n\n"
        f"Workspace root: {workspace_root}\n"
        "The Windows workspace sandbox may start PowerShell in its own installation directory. "
        f"Begin every shell command with Set-Location -LiteralPath '{powershell_root}'; "
        "use an absolute path under the workspace root for every built-in apply_patch call. "
        "Use tools to inspect the files, edit the workspace with the built-in apply_patch tool, "
        "and run the declared tests. Do not return a suggested patch without applying it. "
        "Shell write commands may be denied by the Windows sandbox."
    )
    command = build_command(platform_prompt, workspace, config)
    process_env = os.environ.copy()
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=process_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    try:
        stdout, _stderr = process.communicate(timeout=config.timeout_s)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        process.kill()
        stdout, _stderr = process.communicate()
        stdout = (stdout or "") + "\n" + (error.output or "")
    parsed = parse_codex_events((stdout or "").splitlines())
    return CodexAttempt(parsed, time.monotonic() - started, process.returncode, timed_out, tuple(command))
