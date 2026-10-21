param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptPath,

    [string[]]$ScriptArguments = @()
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$storageConfigPath = Join-Path $projectRoot "config\storage_paths.json"

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Project Python was not found: $pythonExe"
}
if (-not (Test-Path -LiteralPath $storageConfigPath -PathType Leaf)) {
    throw "Storage configuration was not found: $storageConfigPath"
}

$storageConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $storageConfigPath | ConvertFrom-Json
$rawRoot = $storageConfig.raw_root
$pythonTemp = [string]$storageConfig.python_temp
$duckdbTemp = [string]$storageConfig.duckdb_temp
$stataTemp = [string]$storageConfig.stata_temp
$uvTemp = [string]$storageConfig.uv_cache
$logDirectory = Join-Path ([string]$storageConfig.logs_root) "python"
if (-not (Test-Path -LiteralPath $rawRoot -PathType Container)) {
    throw "Raw data directory was not found: $rawRoot"
}

$candidateScript = if ([System.IO.Path]::IsPathRooted($ScriptPath)) {
    $ScriptPath
} else {
    Join-Path $projectRoot $ScriptPath
}
$resolvedScript = (Resolve-Path -LiteralPath $candidateScript).Path

if (-not $resolvedScript.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Python script must be inside the project directory: $resolvedScript"
}

New-Item -ItemType Directory -Force -Path $pythonTemp, $duckdbTemp, $stataTemp, $uvTemp, $logDirectory | Out-Null
$env:SRTP_PROJECT_ROOT = $projectRoot
$env:SRTP_RAW_ROOT = $rawRoot
$env:SRTP_TEMP_ROOT = Split-Path -Parent $pythonTemp
$env:SRTP_DUCKDB_TEMP = $duckdbTemp
$env:TEMP = $pythonTemp
$env:TMP = $pythonTemp
$env:UV_CACHE_DIR = $uvTemp
$env:STATATMP = $stataTemp
$env:PYTHONPYCACHEPREFIX = Join-Path $pythonTemp "pycache"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$taskName = [System.IO.Path]::GetFileNameWithoutExtension($resolvedScript)
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDirectory "${timestamp}_${taskName}.log"

Write-Output "PYTHON_TASK_SCRIPT=$resolvedScript"
Write-Output "PYTHON_TASK_LOG=$logFile"

$savedErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $pythonExe -B $resolvedScript @ScriptArguments 2>&1 |
    Tee-Object -FilePath $logFile
$pythonExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorActionPreference

if ($pythonExitCode -ne 0) {
    throw "Python task failed with exit code $pythonExitCode. See $logFile"
}

Write-Output "PYTHON_TASK=PASS"
