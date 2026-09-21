$ErrorActionPreference = 'Stop'

$benchmarkRoot = Split-Path -Parent $PSScriptRoot
$resultsRoot = Join-Path $benchmarkRoot 'results'
$runRoot = Join-Path $resultsRoot 'canary-test'
$codexRoot = Join-Path $env:USERPROFILE '.codex'

function Get-FileFingerprint([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return "MISSING:$Path"
    }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
    return "$Path=$hash"
}

function Get-DirectoryFingerprint([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        return "MISSING:$Path"
    }
    $entries = Get-ChildItem -LiteralPath $Path -Recurse -File |
        Sort-Object FullName |
        ForEach-Object { Get-FileFingerprint $_.FullName }
    $text = $entries -join "`n"
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes))
}

function Get-GlobalFingerprint {
    return @{
        config = Get-FileFingerprint (Join-Path $codexRoot 'config.toml')
        hooks = Get-DirectoryFingerprint (Join-Path $codexRoot 'hooks')
    } | ConvertTo-Json -Compress
}

if (Test-Path -LiteralPath $runRoot) {
    Remove-Item -LiteralPath $runRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $resultsRoot -Force | Out-Null

$before = Get-GlobalFingerprint
& python (Join-Path $benchmarkRoot 'run_benchmark.py') run `
    --simulate `
    --repeats 1 `
    --output $runRoot `
    --mode astra_only `
    --mode astra_jev_observe `
    --mode astra_jev_offload `
    --mode astra_jev_guarded `
    --mode astra_jev_offload_guarded
if ($LASTEXITCODE -ne 0) {
    throw "Canary runner failed with exit code $LASTEXITCODE"
}
$after = Get-GlobalFingerprint

if ($before -ne $after) {
    throw 'Global Codex config or hooks changed during the canary'
}

$attempts = Get-Content -LiteralPath (Join-Path $runRoot 'attempts.jsonl')
if ($attempts.Count -ne 15) {
    throw "Expected 15 attempt records, got $($attempts.Count)"
}
$report = Get-Content -Raw -LiteralPath (Join-Path $runRoot 'report.json') | ConvertFrom-Json
if ($report.records -ne 15) {
    throw "Expected report.records=15, got $($report.records)"
}
foreach ($name in @('astra_only', 'astra_jev_observe', 'astra_jev_offload', 'astra_jev_guarded', 'astra_jev_offload_guarded')) {
    $entry = $report.modes.$name
    if ($null -eq $entry -or $entry.attempts -ne 3 -or $entry.successes -ne 3) {
        throw "Canary mode $name did not produce 3 successful attempts"
    }
}

Remove-Item -LiteralPath $runRoot -Recurse -Force
Write-Output 'BENCHMARK_CANARY_OK records=15 global_state_unchanged=true'
