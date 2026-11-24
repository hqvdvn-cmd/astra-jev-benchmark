param(
    [string]$RunName = "",
    [string]$WslDistro = "JEVBENCH-DeepSWE",
    [string]$WslRepoPath = ".",
    [string]$Manifest = "tasks/deepswe-pilot-10.json",
    [string]$CorpusDir = "",
    [string]$ResultsRoot = "results",
    [string[]]$Modes = @("codex-baseline", "jev-auto"),
    [string[]]$OnlyTask = @(),
    [int]$StartIndex = 1,
    [int]$MaxTasks = 0,
    [string]$BaselineModel = "openai/gpt-6.2-sol",
    [string]$BaselineEffort = "high",
    [string]$CodexVersion = "",
    [Parameter(Mandatory = $true)]
    [string]$AuthJson,
    [string]$HarnessDir = "./jev-codex-harness",
    [string]$JevStateDir = "./jev-codex-home/codex-router",
    [int]$JevPort = 4319,
    [string]$ProxyUrl = "",
    [string]$LogFile = "",
    [switch]$Resume,
    [switch]$NoPrune
)

$ErrorActionPreference = "Stop"

$pyArgs = @(
    "-m", "jev_astra_bench.deepswe_runner",
    "--manifest", $Manifest,
    "--results-root", $ResultsRoot,
    "--baseline-model", $BaselineModel,
    "--baseline-effort", $BaselineEffort,
    "--auth-json", $AuthJson,
    "--harness-dir", $HarnessDir,
    "--jev-state-dir", $JevStateDir,
    "--jev-port", "$JevPort",
    "--start-index", "$StartIndex",
    "--max-tasks", "$MaxTasks",
    "--modes"
) + $Modes

if ($RunName) { $pyArgs += @("--run-name", $RunName) }
if ($CorpusDir) { $pyArgs += @("--corpus-dir", $CorpusDir) }
if ($CodexVersion) { $pyArgs += @("--codex-version", $CodexVersion) }
foreach ($t in $OnlyTask) { $pyArgs += @("--only-task", $t) }
if ($Resume) { $pyArgs += "--resume" }
if ($NoPrune) { $pyArgs += "--no-prune-after-pair" }

$quoted = ($pyArgs | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join " "
$qRepo = "'" + ($WslRepoPath -replace "'", "'\''") + "'"

$runCmd = "python3 -u $quoted"
if ($LogFile) {
    $qLog = "'" + ($LogFile -replace "'", "'\''") + "'"
    $runCmd = "mkdir -p `$(dirname $qLog); $runCmd >> $qLog 2>&1"
}

$proxyBlock = ""
if ($ProxyUrl) {
    $qProxy = "'" + ($ProxyUrl -replace "'", "'\''") + "'"
    $proxyBlock = @"
export http_proxy=$qProxy
export https_proxy=$qProxy
export HTTP_PROXY=$qProxy
export HTTPS_PROXY=$qProxy
export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="localhost,127.0.0.1,::1"
"@
}

$bash = @"
set -euo pipefail
cd $qRepo
$proxyBlock
export LITELLM_LOCAL_MODEL_COST_MAP="True"
export PYTHONPATH="$WslRepoPath"
$runCmd
"@

# Never let Windows PowerShell 5.1 abort native wsl.exe on stderr warnings.
$ErrorActionPreference = "Continue"
$bash | wsl -d $WslDistro -- sh -c "tr -d '\r' | bash"
exit $LASTEXITCODE
