param(
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$storageConfigPath = Join-Path $projectRoot "config\storage_paths.json"
if (-not (Test-Path -LiteralPath $storageConfigPath -PathType Leaf)) {
    throw "Storage configuration not found: $storageConfigPath"
}
$storageConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $storageConfigPath | ConvertFrom-Json
$rawRoot = $storageConfig.raw_root
$tempRoot = Join-Path $projectRoot "data\temp"
$pythonTemp = Join-Path $tempRoot "python"
$duckdbTemp = Join-Path $tempRoot "duckdb"
$stataTemp = Join-Path $tempRoot "stata"
$uvTemp = Join-Path $tempRoot "uv"
$pycacheTemp = Join-Path $pythonTemp "pycache"
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$environmentCheck = Join-Path $PSScriptRoot "check_storage_environment.py"

$requiredDirectories = @(
    $pythonTemp,
    $duckdbTemp,
    $stataTemp,
    $uvTemp,
    $pycacheTemp,
    (Join-Path $projectRoot "logs"),
    (Join-Path $projectRoot "outputs\status")
)

foreach ($directory in $requiredDirectories) {
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
}

if (-not (Test-Path -LiteralPath $rawRoot -PathType Container)) {
    throw "Raw data directory not found: $rawRoot"
}
if (-not (Test-Path -LiteralPath $projectPython -PathType Leaf)) {
    throw "Project Python not found: $projectPython. Run 'uv sync' in the project directory."
}
if (-not (Test-Path -LiteralPath $environmentCheck -PathType Leaf)) {
    throw "Environment check not found: $environmentCheck"
}

# These variables affect only this launcher and the VS Code process it starts.
# They do not change the global Windows TEMP/TMP settings.
$env:SRTP_PROJECT_ROOT = $projectRoot
$env:SRTP_RAW_ROOT = $rawRoot
$env:SRTP_TEMP_ROOT = $tempRoot
$env:SRTP_DUCKDB_TEMP = $duckdbTemp
$env:TEMP = $pythonTemp
$env:TMP = $pythonTemp
$env:UV_CACHE_DIR = $uvTemp
$env:PIP_CACHE_DIR = Join-Path $uvTemp "pip"
$env:PYTHONPYCACHEPREFIX = $pycacheTemp
$env:STATATMP = $stataTemp

Write-Host "Checking the SRTP D-drive environment..." -ForegroundColor Cyan
& $projectPython $environmentCheck
if ($LASTEXITCODE -ne 0) {
    throw "D-drive environment check failed with exit code $LASTEXITCODE"
}

if ($CheckOnly) {
    Write-Host "Check complete. VS Code will not be started." -ForegroundColor Green
    exit 0
}

$runningCode = @(Get-Process -Name "Code" -ErrorAction SilentlyContinue)
if ($runningCode.Count -gt 0) {
    Write-Host "" 
    Write-Host "VS Code is still running." -ForegroundColor Yellow
    Write-Host "Save your work, close every VS Code window, and run the project launcher again." -ForegroundColor Yellow
    exit 2
}

# A Stata MCP server can survive after every VS Code window is closed. If that
# happens, the next VS Code session reconnects to the stale server and inherits
# its old C-drive temporary directory. Only stop port 4000 after its health
# endpoint confirms that it is the Stata MCP service.
$stataMcpHealth = $null
try {
    $stataMcpHealth = Invoke-RestMethod -Uri "http://localhost:4000/health" -TimeoutSec 2
} catch {
    $stataMcpHealth = $null
}

if ($stataMcpHealth -and $stataMcpHealth.service -eq "Stata MCP Server") {
    $stataMcpListeners = @(
        Get-NetTCPConnection -LocalPort 4000 -State Listen -ErrorAction Stop |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    foreach ($processId in $stataMcpListeners) {
        Write-Host "Stopping stale Stata MCP process $processId..." -ForegroundColor Cyan
        & taskkill.exe /PID $processId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not stop stale Stata MCP process $processId"
        }
    }
}

# VS Code itself uses the Stata temp root so that the Stata MCP extension creates
# each isolated worker under data\temp\stata. Integrated terminals override TEMP
# and TMP back to data\temp\python in .vscode\settings.json.
$env:TEMP = $stataTemp
$env:TMP = $stataTemp

$codeCommand = Get-Command "code.cmd" -ErrorAction SilentlyContinue
if (-not $codeCommand) {
    throw "VS Code command 'code.cmd' was not found. Confirm that VS Code is installed and available on PATH."
}

Write-Host "Environment check passed. Opening the SRTP project..." -ForegroundColor Green
& $codeCommand.Source --new-window $projectRoot
if ($LASTEXITCODE -ne 0) {
    throw "VS Code failed to start with exit code $LASTEXITCODE"
}
