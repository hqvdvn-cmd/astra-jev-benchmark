param(
    [Parameter(Mandatory = $true)][string]$Left,
    [Parameter(Mandatory = $true)][string]$Right,
    [Parameter(Mandatory = $true)][string]$Output
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
& python (Join-Path $root 'run_benchmark.py') compare --left $Left --right $Right --output $Output
exit $LASTEXITCODE
