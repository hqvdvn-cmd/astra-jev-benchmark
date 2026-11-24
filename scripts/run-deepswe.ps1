param(
    [Parameter(Mandatory = $true)]
    [string]$Agent,
    [string]$Model = "",
    [string]$WslDistro = "JEVBENCH-DeepSWE",
    [Parameter(Mandatory = $true)]
    [string]$TaskPath,
    [string]$ResultsRoot = "./results",
    [string]$JobName = "",
    [int]$NTasks = 0,
    [int]$SampleSeed = 0,
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"

if (-not $JobName) {
    $stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
    $JobName = "deepswe-$Agent-$stamp"
}

$wslOut = "$ResultsRoot/$JobName"
$pierArgs = @("run", "-p", $TaskPath, "--agent", $Agent, "--env", "docker", "--jobs-dir", $wslOut)
if ($Model) {
    $pierArgs += @("--model", $Model)
}
if ($NTasks -gt 0) {
    $pierArgs += @("--n-tasks", "$NTasks", "--sample-seed", "$SampleSeed")
}
if ($ExtraArgs.Count -gt 0) {
    $pierArgs += $ExtraArgs
}

$quotedArgs = ($pierArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join " "

$bash = @"
set -euo pipefail
mkdir -p '$wslOut'
pier $quotedArgs
"@

$ErrorActionPreference = "Continue"
$bash | wsl -d $WslDistro -- sh -c "tr -d '\r' | bash"
exit $LASTEXITCODE
