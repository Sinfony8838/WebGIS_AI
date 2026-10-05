[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$RepoRoot = '',
    [string]$DestinationRoot = '',
    [int]$BackendPort = 18999,
    [switch]$AllowLiveBackup,
    [switch]$InventoryOnly,
    [string]$PreviousCommit = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Recovery.Common.ps1')
$repoRoot = if ($RepoRoot) { (Resolve-Path -LiteralPath $RepoRoot).Path }
    else { (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path }
$dataDir = Join-Path $repoRoot 'backend/data'
if (-not (Test-Path -LiteralPath $dataDir -PathType Container)) { throw "Data directory not found: $dataDir" }
$destinationRoot = if ($DestinationRoot) { [IO.Path]::GetFullPath($DestinationRoot) }
    else { Join-Path (Split-Path $repoRoot -Parent) 'WebGIS-AI-backups' }
$destinationResolved = Assert-RecoveryDestinationOutside $destinationRoot @($repoRoot, $dataDir)
$baseline = Get-RecoveryBaseline $repoRoot $PreviousCommit
# Preserve the historical data layout; extras live under a reserved directory.
foreach ($name in @('_recovery', 'backup-manifest.json')) {
    if (Test-Path -LiteralPath (Join-Path $dataDir $name)) { throw "Reserved backup name exists in source data: $name" }
}
$dataResolved = Resolve-RecoveryPhysicalPath $dataDir
$emptyDirectories = @()
$payload = @(foreach ($file in Get-RecoveryTreeFiles $dataDir @('public-runtime', '_backup') -IncludeEmptyDirectories) {
    $relative = $file.FullName.Substring($dataResolved.TrimEnd('\', '/').Length + 1).Replace('\', '/')
    if ($file.PSIsContainer) { $emptyDirectories += $relative; continue }
    [pscustomobject]@{ source = $file.FullName; path = $relative; length = $file.Length; category = 'data' }
})
$resources = @()
foreach ($relativeRoot in @('backend/app/data/builtin/knowledge', 'backend/app/data/builtin/teaching_maps',
        'backend/app/data/builtin/one_map/population/finland_density_2015.geojson')) {
    $source = Join-Path $repoRoot $relativeRoot
    $present = Test-Path -LiteralPath $source
    $resources += @{ repo_path = $relativeRoot; present = [bool]$present }
    if (-not $present) { continue }
    $item = Get-Item -LiteralPath $source -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Repository resource is a filesystem link: $source" }
    $sourceResolved = Resolve-RecoveryPhysicalPath $source
    $files = if ($item.PSIsContainer) { @(Get-RecoveryTreeFiles $source -IncludeEmptyDirectories) } else { @($item) }
    if ($item.PSIsContainer -and $files.Count -eq 0) { $emptyDirectories += '_recovery/repo/' + $relativeRoot }
    foreach ($file in $files) {
        $relative = if ($item.PSIsContainer) {
            $relativeRoot + '/' + $file.FullName.Substring($sourceResolved.TrimEnd('\', '/').Length + 1).Replace('\', '/')
        } else { $relativeRoot }
        if ($file.PSIsContainer) { $emptyDirectories += '_recovery/repo/' + $relative; continue }
        $payload += [pscustomobject]@{ source = $file.FullName; path = '_recovery/repo/' + $relative; length = $file.Length; category = 'repository_resource' }
    }
}
$warnings = @()
if ($baseline.git_commit -and $baseline.recorded_release.ContainsKey('git_commit') -and
    $baseline.git_commit -ne $baseline.recorded_release.git_commit) {
    $warnings += 'Source Git commit differs from recorded release; not proof of the running build.'
}
foreach ($resource in $resources) {
    if (-not $resource.present) { $warnings += "Resource absent in selected source: $($resource.repo_path)" }
}
if ($InventoryOnly) {
    @{
        schema_version = 2; inventory_only = $true; baseline = $baseline
        destination_root_resolved = $destinationResolved; supplemental_resources = $resources
        excluded = @('public-runtime', '_backup'); warnings = $warnings
        empty_directories = $emptyDirectories
        file_count = $payload.Count; total_bytes = [long](($payload | Measure-Object length -Sum).Sum)
        # Names/sizes only; never hash or read database/state bytes in inventory.
        files = @($payload | Select-Object path, length, category)
    } | ConvertTo-Json -Depth 8
    return
}
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$commitLabel = if ($baseline.git_commit) { $baseline.git_commit.Substring(0, 12) } else { 'unknown' }
$backupDir = Join-Path $destinationResolved "$timestamp-$commitLabel"
if (Test-Path -LiteralPath $backupDir) { throw "Backup target exists; no files overwritten: $backupDir" }
if (-not $PSCmdlet.ShouldProcess($backupDir, 'Copy data plus knowledge/teaching resources and verify hashes')) { return }
if (-not $AllowLiveBackup) { Assert-RecoveryBackendStopped $BackendPort }
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
foreach ($relative in $emptyDirectories) {
    Assert-RecoveryRelativePath $relative
    New-Item -ItemType Directory -Path (Join-Path $backupDir $relative) -Force | Out-Null
}
$manifestFiles = @()
foreach ($file in $payload) {
    Assert-RecoveryRelativePath $file.path
    $target = Join-Path $backupDir $file.path
    $sourceHash = (Get-FileHash -LiteralPath $file.source -Algorithm SHA256 -ErrorAction Stop).Hash
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    if (Test-Path -LiteralPath $target) { throw "Duplicate backup path: $($file.path)" }
    Copy-Item -LiteralPath $file.source -Destination $target -ErrorAction Stop
    $targetHash = (Get-FileHash -LiteralPath $target -Algorithm SHA256 -ErrorAction Stop).Hash
    $finalSourceHash = (Get-FileHash -LiteralPath $file.source -Algorithm SHA256 -ErrorAction Stop).Hash
    if ($sourceHash -ne $targetHash -or $sourceHash -ne $finalSourceHash) {
        throw "Source changed or copy failed; incomplete backup retained: $($file.path)"
    }
    $manifestFiles += [pscustomobject]@{
        path = $file.path; length = (Get-Item -LiteralPath $target).Length
        sha256 = $targetHash; category = $file.category
    }
}
if (-not $AllowLiveBackup) { Assert-RecoveryBackendStopped $BackendPort }
$manifest = @{
    schema_version = 2; complete = $true; created_at = (Get-Date).ToString('o')
    source_repo = $repoRoot; source_data = $dataDir; git_commit = $baseline.git_commit
    baseline = $baseline; backup_path = $backupDir
    file_count = $manifestFiles.Count; total_bytes = [long](($manifestFiles | Measure-Object length -Sum).Sum)
    live_backup = [bool]$AllowLiveBackup
    consistency = if ($AllowLiveBackup) { 'live_or_unverified' } else { 'selected_backend_port_stopped' }
    excluded = @('public-runtime', '_backup'); supplemental_resources = $resources
    empty_directories = $emptyDirectories
    warnings = $warnings; files = $manifestFiles
    # Preserve the legacy critical-file summary.
    critical_sha256 = @($manifestFiles | Where-Object {
        $_.category -eq 'repository_resource' -or $_.path -match '(?i)(\.db|\.sqlite|\.sqlite3|/runtime\.json)$'
    } | Select-Object path, length, sha256)
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backupDir 'backup-manifest.json') -Encoding UTF8
Write-Host "Backup complete: $backupDir"
Write-Host "Files: $($manifest.file_count); bytes: $($manifest.total_bytes)"
Write-Host 'Restore only into a new isolated directory first. See MAINTENANCE.md.'
