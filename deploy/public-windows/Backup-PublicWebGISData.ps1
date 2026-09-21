[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepoRoot = "",
    [string]$DestinationRoot = "",
    [int]$BackendPort = 18999,
    [switch]$AllowLiveBackup
)

$ErrorActionPreference = "Stop"
$repoRoot = if ($RepoRoot) {
    (Resolve-Path -LiteralPath $RepoRoot).Path
}
else {
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}
$dataDir = (Resolve-Path -LiteralPath (Join-Path $repoRoot "backend\data")).Path
$repoParent = Split-Path -Parent $repoRoot
$destinationRoot = if ($DestinationRoot) {
    [IO.Path]::GetFullPath($DestinationRoot)
}
else {
    Join-Path $repoParent "WebGIS-AI-backups"
}

$dataFull = [IO.Path]::GetFullPath($dataDir).TrimEnd('\')
$repoFull = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\')
$destinationFull = [IO.Path]::GetFullPath($destinationRoot).TrimEnd('\')
if ($destinationFull -eq $dataFull -or $destinationFull.StartsWith("$dataFull\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "备份目录不能位于 backend/data 内部：$destinationFull"
}
if ($destinationFull -eq $repoFull -or $destinationFull.StartsWith("$repoFull\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "备份目录不能位于 Git 仓库内部：$destinationFull"
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue
if ($listener -and -not $AllowLiveBackup) {
    throw "后端仍在监听 $BackendPort。为保证 SQLite/JSON 快照一致，请先运行 Stop-PublicWebGIS.ps1；仅在明确接受非一致性风险时使用 -AllowLiveBackup。"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$gitCommit = ""
$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($gitCommand) {
    $gitCommit = (& $gitCommand.Source -C $repoRoot rev-parse --short=12 HEAD 2>$null | Select-Object -First 1)
}
if (-not $gitCommit) {
    $gitCommit = "unknown"
}
$backupDir = Join-Path $destinationFull "$timestamp-$gitCommit"
if (Test-Path -LiteralPath $backupDir) {
    throw "目标备份已存在，未覆盖：$backupDir"
}

if (-not $PSCmdlet.ShouldProcess($backupDir, "复制 WebGIS-AI 持久数据并生成清单")) {
    return
}

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$robocopyArgs = @(
    $dataDir,
    $backupDir,
    "/E",
    "/COPY:DAT",
    "/DCOPY:DAT",
    "/R:2",
    "/W:1",
    "/XJ",
    "/XD",
    (Join-Path $dataDir "public-runtime"),
    (Join-Path $dataDir "_backup"),
    "/NFL",
    "/NDL",
    "/NP"
)
& robocopy.exe @robocopyArgs | Out-Host
if ($LASTEXITCODE -ge 8) {
    throw "robocopy 备份失败，退出码：$LASTEXITCODE"
}

$files = @(Get-ChildItem -LiteralPath $backupDir -Recurse -File -ErrorAction Stop)
$criticalPatterns = @("*.db", "*.sqlite", "*.sqlite3", "runtime.json")
$criticalFiles = @($files | Where-Object {
    $name = $_.Name
    $criticalPatterns | Where-Object { $name -like $_ }
})
$criticalHashes = @($criticalFiles | ForEach-Object {
    [pscustomobject]@{
        path = $_.FullName.Substring($backupDir.Length).TrimStart('\').Replace('\', '/')
        length = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
})
$manifest = @{
    schema_version = 1
    created_at = (Get-Date).ToString("o")
    source_repo = $repoRoot
    source_data = $dataDir
    git_commit = [string]$gitCommit
    file_count = $files.Count
    total_bytes = ($files | Measure-Object Length -Sum).Sum
    live_backup = [bool]$AllowLiveBackup
    excluded = @("public-runtime", "_backup")
    critical_sha256 = $criticalHashes
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $backupDir "backup-manifest.json") -Encoding utf8

Write-Host "备份完成：$backupDir" -ForegroundColor Green
Write-Host "文件数：$($files.Count)；总字节数：$($manifest.total_bytes)"
Write-Host "恢复前必须停止服务，并按 MAINTENANCE.md 的回滚流程执行。"
