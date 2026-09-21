param(
    [ValidateSet('preflight', 'canary', 'full')]
    [string]$Mode = 'preflight',
    [string]$Output = '',
    [string]$Config = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'run_benchmark.py'

if (-not $Output) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $Output = Join-Path $root "results/$Mode-$stamp"
}

if ($Mode -eq 'preflight') {
    & python $runner preflight --task-set (Join-Path $root 'tasks/manifest.json')
    exit $LASTEXITCODE
}

$arguments = @(
    $runner, 'run', '--task-set', (Join-Path $root 'tasks/manifest.json'),
    '--output', $Output, '--mode', 'astra_only', '--mode', 'astra_jev_observe',
    '--mode', 'astra_jev_offload', '--mode', 'astra_jev_guarded',
    '--mode', 'astra_jev_offload_guarded'
)
if ($Mode -eq 'canary') {
    $arguments += @('--simulate', '--repeats', '1')
} else {
    $arguments += @('--repeats', '3')
}
if ($Config) {
    $arguments += @('--config', $Config)
}
& python @arguments
exit $LASTEXITCODE
