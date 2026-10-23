from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .codex_runner import CodexConfig, run_codex
from .jev_client import JevClient, JevConfig
from .offload import CODE_STRATEGY_CHOICES, strategy_instruction
from .react_report import write_report

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / 'tasks' / 'react-site-001'
MODELS = ('gpt-6-astra', 'gpt-6.1-sol')
MODES = ('baseline', 'jev_offload')
IGNORED = {'node_modules', 'dist', '.vite', '__pycache__'}


def codex_executable() -> str:
    native = shutil.which('codex.exe')
    if native:
        return native
    wrapper = shutil.which('codex.cmd')
    if os.name == 'nt' and wrapper:
        package = Path(wrapper).parent / 'node_modules/@openai/codex'
        candidates = list(package.glob('node_modules/@openai/codex-win32-*/vendor/*/bin/codex.exe'))
        if len(candidates) == 1:
            return str(candidates[0])
        raise ValueError('Cannot resolve an unambiguous native Codex executable; no model run started')
    return shutil.which('codex') or 'codex'


def matrix() -> list[tuple[int, str, str]]:
    groups = [(model, mode) for model in MODELS for mode in MODES]
    result = []
    for repeat in range(1, 6):
        shift = (repeat - 1) % len(groups)
        result.extend((repeat, model, mode) for model, mode in groups[shift:] + groups[:shift])
    return result


def load_key(path: Path) -> str:
    text = path.read_text(encoding='utf-8-sig').strip()
    if text and '\n' not in text and '=' not in text and not any(c.isspace() for c in text):
        return text
    for line in text.splitlines():
        name, separator, value = line.partition('=')
        if separator and name.strip().removeprefix('export ') == 'TYPESAFE_API_KEY':
            value = value.strip().strip('\"\'')
            if value and not any(c.isspace() for c in value):
                return value
    raise ValueError('TYPESAFE_API_KEY not found in local key file')


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_map(root: Path, *, skip_dependencies=True) -> dict[str, str]:
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        if skip_dependencies:
            dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        for name in sorted(files):
            path = Path(folder) / name
            relative = path.relative_to(root).as_posix()
            result[relative] = 'symlink' if path.is_symlink() else file_hash(path)
        for name in dirs:
            path = Path(folder) / name
            if path.is_symlink():
                result[path.relative_to(root).as_posix()] = 'symlink'
    return result


def source_changes(base: Path, work: Path) -> list[str]:
    before, after = file_map(base), file_map(work)
    return sorted(name for name in before.keys() | after.keys()
                  if (after.get(name) == 'symlink' or (before.get(name) != after.get(name)
                      and not (name.startswith('src/') or name == 'README.md'))))


def dependency_map(root: Path) -> dict[str, str]:
    result = {}
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {'.vite', '.vite-temp'})
        for name in files:
            path = Path(folder) / name
            result[path.relative_to(root).as_posix()] = 'symlink' if path.is_symlink() else file_hash(path)
        for name in dirs:
            path = Path(folder) / name
            if path.is_symlink():
                result[path.relative_to(root).as_posix()] = 'symlink'
    return result


def check_resume(path: Path, expected: dict) -> None:
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) != expected:
        raise ValueError('Run inputs changed; use a new output directory instead of mixing results')


def archive_source(work: Path, target: Path) -> None:
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for relative in file_map(work):
            path = work / relative
            if not path.is_symlink():
                archive.write(path, relative)


def run_local(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', start_new_session=os.name != 'nt')
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def is_infrastructure_failure(result) -> bool:
    return (result.exit_code != 0 and not result.timed_out and not result.parsed.completed
            and result.parsed.tool_calls == 0 and not result.parsed.final_text
            and result.parsed.input_tokens in (None, 0))


def verify(work: Path, artifacts: Path, playwright_module: str, channel: str) -> dict:
    artifacts.mkdir(parents=True, exist_ok=True)
    build = run_local(['node', str(work / 'node_modules/vite/bin/vite.js'), 'build'], cwd=work, timeout=180)
    (artifacts / 'build.txt').write_text(build.stdout + build.stderr, encoding='utf-8')
    if build.returncode:
        return {'success': False, 'checks': {'build': False}, 'failure_reason': 'build_failed'}
    result = run_local(['node', str(ROOT / 'scripts/react-checks.cjs'), str(work), str(artifacts), playwright_module, channel], cwd=ROOT, timeout=180)
    (artifacts / 'browser.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    path = artifacts / 'verification.json'
    if not path.exists():
        return {'success': False, 'checks': {'build': True, 'browser': False}, 'failure_reason': 'browser_verifier_failed'}
    return json.loads(path.read_text(encoding='utf-8'))


def run(args) -> int:
    output = args.output.resolve()
    starter = TASK / 'starter'
    if not (starter / 'node_modules/vite/bin/vite.js').exists():
        raise ValueError('Install the pinned starter dependencies with npm ci first')
    prompt = (TASK / 'PROMPT.md').read_text(encoding='utf-8')
    dependencies = dependency_map(starter / 'node_modules')
    playwright_info = run_local(['node', '-e', 'const p=require(process.argv[1]);(async()=>{const b=await p.chromium.launch({headless:true,channel:process.argv[2]});console.log(JSON.stringify({playwright:require(process.argv[1]+"/package.json").version,browser:b.version(),node:process.version}));await b.close()})().catch(e=>{console.error(e.message);process.exit(1)})', args.playwright_module, args.channel], cwd=ROOT, timeout=30)
    if playwright_info.returncode:
        raise ValueError('Browser runtime preflight failed')
    inputs = {'prompt_sha256': file_hash(TASK / 'PROMPT.md'), 'starter': file_map(starter),
              'dependencies_sha256': hashlib.sha256(json.dumps(dependencies, sort_keys=True).encode()).hexdigest(),
              'treatment_sources': {name: file_hash(ROOT / 'jev_astra_bench' / name) for name in ['offload.py', 'jev_client.py', 'redaction.py', 'codex_events.py']},
              'browser_runtime': json.loads(playwright_info.stdout),
              'runner_sha256': file_hash(Path(__file__)), 'codex_runner_sha256': file_hash(ROOT / 'jev_astra_bench/codex_runner.py'),
              'verifier_sha256': file_hash(ROOT / 'scripts/react-checks.cjs'), 'matrix': matrix(),
              'reasoning_effort': 'xhigh', 'timeout_s': 900, 'simulate': False,
              'browser_channel': args.channel, 'external_network': 'blocked_in_browser'}
    # Canonicalize tuples before comparing JSON on resume.
    inputs = json.loads(json.dumps(inputs))
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'manifest.json'
    check_resume(manifest, inputs)
    manifest.write_text(json.dumps(inputs, indent=2), encoding='utf-8')
    if args.key_file:
        os.environ['TYPESAFE_API_KEY'] = load_key(args.key_file)
    if not os.environ.get('TYPESAFE_API_KEY'):
        raise ValueError('TypeSafe key missing; no live attempts were started')
    rows_path = output / 'attempts.jsonl'
    rows = [json.loads(line) for line in rows_path.read_text(encoding='utf-8').splitlines() if line.strip()] if rows_path.exists() else []
    completed = {r['attempt_id'] for r in rows}
    if len(completed) != len(rows):
        raise ValueError('Duplicate attempt records; refusing an ambiguous resume')
    count = 0
    for repeat, model, mode in matrix():
        attempt_id = f'{model}-{mode}-r{repeat}'
        if attempt_id in completed:
            continue
        folder = output / attempt_id
        if folder.exists():
            if args.retry_infrastructure and (folder / 'infrastructure.json').exists():
                archive = output / '_infrastructure'
                archive.mkdir(exist_ok=True)
                shutil.move(str(folder), str(archive / f'{attempt_id}-{time.time_ns()}'))
            else:
                raise ValueError(f'Interrupted workspace exists for {attempt_id}; preserve it and choose explicit recovery before continuing')
        work = folder / 'workspace'
        print(f'PILOT_START {attempt_id}', flush=True)
        started = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat()
        choice = None
        jev_usage = 0
        jev_duration = 0.0
        effective_prompt = prompt
        if mode == 'jev_offload':
            jev_started = time.monotonic()
            decision = JevClient(JevConfig(max_retries=0)).decide(
                'Choose the smallest safe implementation strategy for the React task.',
                {'task': 'react-site-001', 'task_kind': 'code_write', 'verifier_present': True,
                 'requirements': ['React production build', 'responsive layout', 'motion', 'project filters', 'pricing toggle', 'form validation']},
                CODE_STRATEGY_CHOICES)
            jev_duration = time.monotonic() - jev_started
            if decision.status != 'ok':
                print(f'PILOT_BLOCKED jev_status={decision.status} code={decision.error_code}', flush=True)
                return 3
            choice, jev_usage = decision.choice, decision.input_tokens
            effective_prompt += '\n\nBounded strategy selected by Jev: ' + strategy_instruction(choice)
        shutil.copytree(starter, work, ignore=lambda folder, names: [n for n in names if n in {'.vite', '.vite-temp'} or (Path(folder) == starter and n == 'dist')])
        generated_started = time.monotonic()
        result = run_codex(effective_prompt, work, CodexConfig(model=model, reasoning_effort='xhigh', timeout_s=900,
                           executable=codex_executable(),
                           isolated=True, events_path=folder / 'codex-events.jsonl'))
        model_duration = time.monotonic() - generated_started
        if is_infrastructure_failure(result):
            (folder / 'infrastructure.json').write_text(json.dumps({'model': model, 'exit_code': result.exit_code,
                'timed_out': result.timed_out, 'input_tokens': result.parsed.input_tokens, 'output_tokens': result.parsed.output_tokens,
                'reason': 'No completed model response or tool execution; inspect retained events before retry'}), encoding='utf-8')
            print(f'PILOT_BLOCKED infrastructure={attempt_id}; events retained, attempt not scored', flush=True)
            return 3
        violation = source_changes(starter, work)
        if dependency_map(work / 'node_modules') != dependencies:
            violation.append('node_modules')
        verification = {'success': False, 'checks': {}, 'failure_reason': 'model_incomplete'}
        if violation:
            verification = {'success': False, 'checks': {'source_scope': False}, 'failure_reason': 'protected_files_changed', 'violations': violation}
        elif result.exit_code == 0 and result.parsed.completed:
            try:
                verification = verify(work, folder / 'artifacts', args.playwright_module, args.channel)
            except (OSError, subprocess.TimeoutExpired) as error:
                verification = {'success': False, 'checks': {'verifier_completed': False},
                                'failure_reason': 'verifier_infrastructure_error', 'error_type': type(error).__name__}
        else:
            # Preserve viewable build artifacts when possible even after an incomplete model invocation.
            try:
                verification = verify(work, folder / 'artifacts', args.playwright_module, args.channel)
            except (OSError, subprocess.TimeoutExpired):
                pass
            verification['success'] = False
            verification['failure_reason'] = 'model_timeout' if result.timed_out else 'model_incomplete'
        archive_source(work, folder / 'source.zip')
        row = {'attempt_id': attempt_id, 'model': model, 'mode': mode, 'repeat': repeat,
               'started_at': started_at, 'reasoning_effort': 'xhigh',
               'duration_s': time.monotonic() - started, 'model_duration_s': model_duration, 'jev_duration_s': jev_duration,
               'input_tokens': result.parsed.input_tokens, 'cached_input_tokens': result.parsed.cached_input_tokens,
               'output_tokens': result.parsed.output_tokens, 'tool_calls': result.parsed.tool_calls,
               'model_completed': result.parsed.completed, 'model_exit_code': result.exit_code, 'model_timed_out': result.timed_out,
               'jev_choice': choice, 'jev_input_tokens': jev_usage, 'verification': verification,
               'success': verification['success'], 'failure_reason': verification.get('failure_reason'),
               'prompt_sha256': inputs['prompt_sha256'], 'source_sha256': file_map(work)}
        (folder / 'result.json').write_text(json.dumps(row, indent=2), encoding='utf-8')
        with rows_path.open('a', encoding='utf-8') as sink:
            sink.write(json.dumps(row) + '\n')
        rows.append(row)
        write_report(rows, output)
        print(f'PILOT_RESULT {attempt_id} success={row["success"]} seconds={row["duration_s"]:.1f} failure={row["failure_reason"]}', flush=True)
        count += 1
        if args.limit and count >= args.limit:
            break
    return 0


def main():
    parser = argparse.ArgumentParser(description='GPT-only 20-build React pilot; always preserves existing attempts')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--playwright-module', required=True)
    parser.add_argument('--channel', choices=['chrome', 'msedge'], default='chrome')
    parser.add_argument('--limit', type=int, default=0, help='Maximum new attempts this invocation; zero runs all remaining')
    parser.add_argument('--retry-infrastructure', action='store_true', help='Archive an unscored infrastructure interruption and retry only that missing cell')
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'PILOT_STOP {type(error).__name__}: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
