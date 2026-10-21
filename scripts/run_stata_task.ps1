param(
    [Parameter(Mandatory = $true)]
    [string]$DoFile,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedLog,

    [string]$SuccessMarker = "STATA_TASK=PASS"
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stataExe = "C:\Program Files\Stata18\StataSE-64.exe"
$storageConfigPath = Join-Path $projectRoot "config\storage_paths.json"

if (-not (Test-Path -LiteralPath $storageConfigPath -PathType Leaf)) {
    throw "Storage configuration was not found: $storageConfigPath"
}
$storageConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $storageConfigPath | ConvertFrom-Json
$stataTemp = [string]$storageConfig.stata_temp

if (-not (Test-Path -LiteralPath $stataExe -PathType Leaf)) {
    throw "Stata executable was not found: $stataExe"
}

$candidateDoFile = if ([System.IO.Path]::IsPathRooted($DoFile)) {
    $DoFile
} else {
    Join-Path $projectRoot $DoFile
}
$resolvedDoFile = (Resolve-Path -LiteralPath $candidateDoFile).Path

if (-not $resolvedDoFile.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Stata do-file must be inside the project directory: $resolvedDoFile"
}

$candidateLog = if ([System.IO.Path]::IsPathRooted($ExpectedLog)) {
    $ExpectedLog
} else {
    Join-Path $projectRoot $ExpectedLog
}
$logParent = Split-Path -Parent $candidateLog
New-Item -ItemType Directory -Force -Path $stataTemp, $logParent | Out-Null
$resolvedLog = [System.IO.Path]::GetFullPath($candidateLog)

if (-not $resolvedLog.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Stata log must be inside the project directory: $resolvedLog"
}

$env:STATATMP = $stataTemp
$env:STATA_TMPDIR = $stataTemp
$startedAt = Get-Date
$workingDirectory = Split-Path -Parent $resolvedDoFile

Write-Output "STATA_TASK_DO_FILE=$resolvedDoFile"
Write-Output "STATA_TASK_LOG=$resolvedLog"

$stataProcess = Start-Process `
    -FilePath $stataExe `
    -ArgumentList @("/e", "do", "`"$resolvedDoFile`"") `
    -WorkingDirectory $workingDirectory `
    -WindowStyle Hidden `
    -Wait `
    -PassThru

if ($stataProcess.ExitCode -ne 0) {
    throw "Stata exited with code $($stataProcess.ExitCode). See $resolvedLog"
}
if (-not (Test-Path -LiteralPath $resolvedLog -PathType Leaf)) {
    throw "Stata did not create the expected log: $resolvedLog"
}
if ((Get-Item -LiteralPath $resolvedLog).LastWriteTime -lt $startedAt) {
    throw "The Stata log is older than this run: $resolvedLog"
}
if (-not (Select-String -LiteralPath $resolvedLog -SimpleMatch $SuccessMarker -Quiet)) {
    throw "The Stata log does not contain '$SuccessMarker': $resolvedLog"
}

Write-Output "STATA_TASK=PASS"
