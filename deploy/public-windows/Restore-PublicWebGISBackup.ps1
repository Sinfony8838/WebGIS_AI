[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][string]$BackupPath,
    [Parameter(Mandatory)][string]$DestinationRoot
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Recovery.Common.ps1')
$backupRoot = (Resolve-Path -LiteralPath $BackupPath).Path
$backupResolved = Resolve-RecoveryPhysicalPath $backupRoot
$manifestPath = Join-Path $backupRoot 'backup-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop | ConvertFrom-Json
if ($manifest.schema_version -ne 2 -or -not $manifest.complete) {
    throw 'Only complete version-2 backups support automatic isolated restore. Use the manual process for version 1.'
}
$destinationFull = [IO.Path]::GetFullPath($DestinationRoot)
if (Test-Path -LiteralPath $destinationFull) { throw "Restore target must not exist; no files overwritten: $destinationFull" }
$scriptRepo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$protected = @($backupRoot, $scriptRepo, [string]$manifest.source_repo, [string]$manifest.source_data)
$destinationResolved = Assert-RecoveryDestinationOutside $destinationFull $protected
if (Test-RecoveryPathWithin $backupResolved $destinationResolved) { throw 'Restore target cannot be an ancestor of the backup.' }
$entries = @($manifest.files)
if ($entries.Count -ne $manifest.file_count) { throw 'Backup file count mismatch.' }
$actualFiles = @(Get-RecoveryTreeFiles $backupRoot | Where-Object FullName -ne (Join-Path $backupResolved 'backup-manifest.json'))
if ($actualFiles.Count -ne $entries.Count) { throw 'Backup contains missing or unlisted payload files.' }
$seen = @{}
$verified = @()
$total = 0L
foreach ($entry in $entries) {
    $relative = [string]$entry.path
    Assert-RecoveryRelativePath $relative
    if ($seen.ContainsKey($relative)) { throw "Duplicate manifest path: $relative" }
    $seen[$relative] = $true
    if ($relative.StartsWith('_recovery/repo/', [StringComparison]::Ordinal)) {
        $targetRelative = $relative.Substring('_recovery/repo/'.Length)
        if (-not ($targetRelative.StartsWith('backend/app/data/builtin/knowledge/', [StringComparison]::Ordinal) -or
                  $targetRelative.StartsWith('backend/app/data/builtin/teaching_maps/', [StringComparison]::Ordinal) -or
                  $targetRelative -eq 'backend/app/data/builtin/one_map/population/finland_density_2015.geojson')) {
            throw "Repository restore path is not allowlisted: $relative"
        }
    } else {
        if (($relative.Split('/')[0]) -in @('_recovery', 'public-runtime', '_backup', 'backup-manifest.json')) {
            throw "Reserved data restore path: $relative"
        }
        $targetRelative = 'backend/data/' + $relative
    }
    if ([string]$entry.sha256 -notmatch '^[a-fA-F0-9]{64}$' -or [long]$entry.length -lt 0) { throw "Invalid checksum record: $relative" }
    $source = Join-Path $backupResolved $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Missing backup file: $relative" }
    $item = Get-Item -LiteralPath $source -Force
    if ($item.Length -ne [long]$entry.length -or
        (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $entry.sha256) { throw "Checksum mismatch: $relative" }
    $total += $item.Length
    $verified += @{ source = $source; target = $targetRelative; sha256 = $entry.sha256 }
}
if ($total -ne [long]$manifest.total_bytes) { throw 'Backup byte count mismatch.' }
$emptyDirectories = @()
foreach ($relative in @($manifest.empty_directories)) {
    Assert-RecoveryRelativePath $relative
    if ($relative.StartsWith('_recovery/repo/', [StringComparison]::Ordinal)) {
        $targetRelative = $relative.Substring('_recovery/repo/'.Length)
        if (-not ($targetRelative -eq 'backend/app/data/builtin/knowledge' -or
                  $targetRelative -eq 'backend/app/data/builtin/teaching_maps' -or
                  $targetRelative.StartsWith('backend/app/data/builtin/knowledge/', [StringComparison]::Ordinal) -or
                  $targetRelative.StartsWith('backend/app/data/builtin/teaching_maps/', [StringComparison]::Ordinal))) {
            throw "Repository directory is not allowlisted: $relative"
        }
    } else {
        if (($relative.Split('/')[0]) -in @('_recovery', 'public-runtime', '_backup', 'backup-manifest.json')) { throw "Reserved directory: $relative" }
        $targetRelative = 'backend/data/' + $relative
    }
    if (-not (Test-Path -LiteralPath (Join-Path $backupResolved $relative) -PathType Container)) { throw "Missing backup directory: $relative" }
    $emptyDirectories += $targetRelative
}
if (-not $PSCmdlet.ShouldProcess($destinationResolved, 'Restore verified bytes into a new isolated tree; do not start services')) { return }
New-Item -ItemType Directory -Path $destinationResolved -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path (Join-Path $destinationResolved 'backend/data') -Force | Out-Null
foreach ($relative in $emptyDirectories) { New-Item -ItemType Directory -Path (Join-Path $destinationResolved $relative) -Force | Out-Null }
foreach ($file in $verified) {
    $target = Join-Path $destinationResolved $file.target
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    if (Test-Path -LiteralPath $target) { throw "Restore target appeared during copy: $target" }
    Copy-Item -LiteralPath $file.source -Destination $target -ErrorAction Stop
    if ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -ne $file.sha256) { throw "Restore verification failed: $($file.target)" }
}
@{
    schema_version = 1; restored_at = (Get-Date).ToString('o')
    source_backup = $backupResolved
    source_manifest_sha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
    destination_resolved = $destinationResolved; file_count = $verified.Count; total_bytes = $total
    source_commit = $manifest.git_commit; services_started = $false
    external_dependencies_restored = $false; live_backup = $manifest.live_backup
    supplemental_resources = $manifest.supplemental_resources
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destinationResolved 'restore-receipt.json') -Encoding UTF8
Write-Host "Isolated restore verified: $destinationResolved"
Write-Host 'No service started. This contains data/resources, not a complete checkout or a production switch.'
