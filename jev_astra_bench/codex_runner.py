from __future__ import annotations

import os
import re
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
    isolated: bool = False
    events_path: Path | None = None


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
        *(["--ignore-user-config", "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
           *(['-c', 'windows.sandbox="unelevated"'] if os.name == 'nt' else [])] if config.isolated else []),
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


def model_environment(isolated: bool) -> dict[str, str]:
    env = os.environ.copy()
    if isolated:
        for key in list(env):
            if re.search(r"API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", key, re.I):
                env.pop(key, None)
        for key in ('CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'CODEX_TOOL_CALL_ID', 'CODEX_APP_TOOLS_PIPE_PATH',
                    'CODEX_PERMISSION_PROFILE', 'CODEX_SHELL', 'CODEX_CI', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE'):
            env.pop(key, None)
    return env


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
    # Pass the complete multiline prompt over stdin. Windows .cmd wrappers can truncate
    # multiline command arguments and strip TOML quoting before Codex receives them.
    command = build_command("-", workspace, config)
    process_env = model_environment(config.isolated)
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=workspace,
        env=process_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    try:
        stdout, _stderr = process.communicate(input=platform_prompt, timeout=config.timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
        else:
            process.kill()
        stdout, _stderr = process.communicate()
        # communicate() after kill drains the complete buffered output; do not double-count it.
    if config.events_path is not None:
        config.events_path.parent.mkdir(parents=True, exist_ok=True)
        config.events_path.write_text(stdout or "", encoding="utf-8")
        config.events_path.with_suffix(".stderr.txt").write_text(_stderr or "", encoding="utf-8")
    parsed = parse_codex_events((stdout or "").splitlines())
    return CodexAttempt(parsed, time.monotonic() - started, process.returncode, timed_out, tuple(command))
