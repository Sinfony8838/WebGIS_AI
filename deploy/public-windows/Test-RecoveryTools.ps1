# Filesystem acceptance only: synthetic bytes, no app imports or live DB access.
[CmdletBinding()]
param([string]$FixtureParent = [IO.Path]::GetTempPath())
$ErrorActionPreference = 'Stop'
$fixtureRoot = Join-Path ([IO.Path]::GetFullPath($FixtureParent)) ('webgis-recovery-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
$repo = Join-Path $fixtureRoot 'source'
$backups = Join-Path $fixtureRoot 'backups'
$backupScript = Join-Path $PSScriptRoot 'Backup-PublicWebGISData.ps1'
$restoreScript = Join-Path $PSScriptRoot 'Restore-PublicWebGISBackup.ps1'
$global:WebGISRecoveryTestState = @{ ListenerMode = 'stopped'; HashCalls = 0; ListenerChecks = 0 }
$script:Results = @()
function Get-NetTCPConnection {
    [CmdletBinding()]param($State)
    $global:WebGISRecoveryTestState.ListenerChecks++
    if ($global:WebGISRecoveryTestState.ListenerMode -eq 'unavailable') { throw 'synthetic listener permission error' }
    if ($global:WebGISRecoveryTestState.ListenerMode -eq 'listening' -or
        ($global:WebGISRecoveryTestState.ListenerMode -eq 'starts_after_copy' -and $global:WebGISRecoveryTestState.ListenerChecks -gt 1)) {
        [pscustomobject]@{ LocalPort = 18999 }
    }
}
function Get-FileHash {
    [CmdletBinding()]param([string]$LiteralPath, [string]$Algorithm)
    $global:WebGISRecoveryTestState.HashCalls++
    Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $LiteralPath -Algorithm $Algorithm
}
function Write-FixtureFile {
    param([string]$Relative, [string]$Text)
    $path = Join-Path $repo $Relative
    New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
    [IO.File]::WriteAllText($path, $Text, [Text.UTF8Encoding]::new($false))
}
function Assert-True { param([bool]$Condition, [string]$Message) if (-not $Condition) { throw $Message } }
function Assert-Throws {
    param([scriptblock]$Action, [string]$Pattern)
    $caught = $null
    try { & $Action } catch { $caught = $_.Exception.Message }
    if (-not $caught -or $caught -notmatch $Pattern) { throw "Expected failure /$Pattern/, got: $caught" }
}
function Run-Case {
    param([string]$Name, [scriptblock]$Action)
    try { & $Action; $script:Results += @{ name = $Name; status = 'PASS' }; Write-Host "PASS $Name" }
    catch { $script:Results += @{ name = $Name; status = 'FAIL'; error = $_.Exception.Message }; Write-Host "FAIL $Name : $($_.Exception.Message)" }
}
function Clone-Backup {
    param([string]$Name)
    $copy = Join-Path $fixtureRoot $Name
    Copy-Item -LiteralPath $script:ValidBackup -Destination $copy -Recurse
    return $copy
}

$dataFixtures = @{
    'state/runtime.json' = '{"projects":{"synthetic":{"name":"fixture"}}}'
    'state/layer_data/layer.json' = '{"type":"FeatureCollection","features":[]}'
    'auth/auth.db' = 'SYNTHETIC DATABASE BYTES, NOT A REAL ACCOUNT DATABASE'
    'uploads/question_banks/fixture/images/a.png' = 'synthetic image bytes'
    'outputs/fixture/report.json' = '{"synthetic":true}'
    'workflows/fixture/status.json' = '{"status":"success"}'
    'population/fixture/counts.sqlite' = 'synthetic population bytes'
    'voice-models/fixture.onnx' = 'synthetic model bytes'
    'cache/terrain/0.png' = 'synthetic cached tile'
}
foreach ($key in $dataFixtures.Keys) { Write-FixtureFile ('backend/data/' + $key) $dataFixtures[$key] }
$resourceFixtures = @{
    'backend/app/data/builtin/knowledge/kb_manifest.json' = '{"items":[{"id":"fixture"}]}'
    'backend/app/data/builtin/knowledge/geo_knowledge.json' = '[]'
    'backend/app/data/builtin/teaching_maps/registry.json' = '{"synthetic":true}'
    'backend/app/data/builtin/teaching_maps/课堂_teacher.png' = 'synthetic teacher map'
    'backend/app/data/builtin/teaching_maps/textbook.jpg' = 'synthetic textbook map'
    'backend/app/data/builtin/one_map/population/finland_density_2015.geojson' = '{"type":"FeatureCollection","features":[]}'
}
foreach ($key in $resourceFixtures.Keys) { Write-FixtureFile $key $resourceFixtures[$key] }
New-Item -ItemType Directory -Path (Join-Path $repo 'backend/data/uploads/empty-fixture') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $repo 'backend/app/data/builtin/knowledge/empty-fixture') -Force | Out-Null
Write-FixtureFile 'backend/data/public-runtime/release.json' '{"git_commit":"fixture-sha","frontend_asset":"assets/index-fixture.js","backend_port":18999,"private_test_field":"DO_NOT_EMIT"}'
Write-FixtureFile 'backend/data/_backup/old.txt' 'excluded old backup'
Write-FixtureFile 'frontend/dist/index.html' '<script src="/assets/index-fixture.js"></script>'
Write-FixtureFile '.env' 'DO_NOT_EMIT'
$before = @{}
foreach ($key in $dataFixtures.Keys) { $before[$key] = (Get-FileHash -LiteralPath (Join-Path $repo ('backend/data/' + $key)) -Algorithm SHA256).Hash }

Run-Case 'inventory reads no data hashes and creates no destination' {
    $start = $global:WebGISRecoveryTestState.HashCalls
    $json = & $backupScript -RepoRoot $repo -DestinationRoot $backups -InventoryOnly -PreviousCommit 'previous-fixture'
    $inventory = $json | ConvertFrom-Json
    Assert-True ($global:WebGISRecoveryTestState.HashCalls -eq $start) 'inventory hashed payload bytes'
    Assert-True (-not (Test-Path $backups)) 'inventory created files'
    Assert-True ($inventory.file_count -eq 15) 'inventory omitted data or resources'
    Assert-True ($inventory.baseline.previous_commit -eq 'previous-fixture') 'previous build omitted'
    Assert-True ($inventory.baseline.source_data_resolved -eq (Join-Path $repo 'backend/data')) 'physical path incorrect'
    Assert-True ($json -notmatch 'DO_NOT_EMIT') 'non-allowlisted metadata emitted'
}
Run-Case 'WhatIf creates no backup' {
    & $backupScript -RepoRoot $repo -DestinationRoot $backups -WhatIf
    Assert-True (-not (Test-Path $backups)) 'WhatIf wrote files'
}
Run-Case 'listener discovery failure rejects before writes' {
    $global:WebGISRecoveryTestState.ListenerMode = 'unavailable'
    Assert-Throws { & $backupScript -RepoRoot $repo -DestinationRoot $backups } 'Cannot verify stopped'
    Assert-True (-not (Test-Path $backups)) 'unverified backup wrote files'
    $global:WebGISRecoveryTestState.ListenerMode = 'stopped'
}
Run-Case 'listening backend rejects before writes' {
    $global:WebGISRecoveryTestState.ListenerMode = 'listening'
    Assert-Throws { & $backupScript -RepoRoot $repo -DestinationRoot $backups } 'Backend is listening'
    Assert-True (-not (Test-Path $backups)) 'live backup wrote files without opt-in'
    $global:WebGISRecoveryTestState.ListenerMode = 'stopped'
}
Run-Case 'backup includes resources and preserves legacy data layout' {
    & $backupScript -RepoRoot $repo -DestinationRoot $backups
    $script:ValidBackup = (Get-ChildItem $backups -Directory | Select-Object -First 1).FullName
    $manifest = Get-Content (Join-Path $script:ValidBackup 'backup-manifest.json') -Raw | ConvertFrom-Json
    Assert-True ($manifest.complete -and $manifest.schema_version -eq 2 -and $manifest.file_count -eq 15) 'incomplete receipt'
    Assert-True (Test-Path (Join-Path $script:ValidBackup 'state/runtime.json')) 'data layout changed'
    Assert-True (Test-Path (Join-Path $script:ValidBackup '_recovery/repo/backend/app/data/builtin/knowledge/kb_manifest.json')) 'knowledge omitted'
    Assert-True (-not (Test-Path (Join-Path $script:ValidBackup 'public-runtime'))) 'runtime logs copied'
    Assert-True (-not (Test-Path (Join-Path $script:ValidBackup '_backup'))) 'old backups copied'
    Assert-True (-not (Test-Path (Join-Path $script:ValidBackup '.env'))) 'environment copied'
}
Run-Case 'restore verifies every data and supplemental file' {
    $target = Join-Path $fixtureRoot 'restored'
    & $restoreScript -BackupPath $script:ValidBackup -DestinationRoot $target
    foreach ($key in $dataFixtures.Keys) {
        $hash = (Get-FileHash -LiteralPath (Join-Path $target ('backend/data/' + $key)) -Algorithm SHA256).Hash
        Assert-True ($hash -eq $before[$key]) "restored data differs: $key"
    }
    foreach ($key in $resourceFixtures.Keys) {
        Assert-True ((Get-FileHash -LiteralPath (Join-Path $target $key) -Algorithm SHA256).Hash -eq
            (Get-FileHash -LiteralPath (Join-Path $repo $key) -Algorithm SHA256).Hash) "resource differs: $key"
    }
    $receipt = Get-Content (Join-Path $target 'restore-receipt.json') -Raw | ConvertFrom-Json
    Assert-True (-not $receipt.services_started -and -not $receipt.external_dependencies_restored) 'restore overclaimed runtime readiness'
    Assert-True (Test-Path (Join-Path $target 'backend/data/uploads/empty-fixture') -PathType Container) 'empty data directory omitted'
    Assert-True (Test-Path (Join-Path $target 'backend/app/data/builtin/knowledge/empty-fixture') -PathType Container) 'empty resource directory omitted'
}
Run-Case 'restore WhatIf does not create a target' {
    $target = Join-Path $fixtureRoot 'whatif-restore'
    & $restoreScript -BackupPath $script:ValidBackup -DestinationRoot $target -WhatIf
    Assert-True (-not (Test-Path $target)) 'restore WhatIf wrote files'
}
Run-Case 'existing restore target cannot be overwritten' {
    Assert-Throws { & $restoreScript -BackupPath $script:ValidBackup -DestinationRoot $repo } 'must not exist'
    foreach ($key in $before.Keys) { Assert-True ((Get-FileHash -LiteralPath (Join-Path $repo ('backend/data/' + $key)) -Algorithm SHA256).Hash -eq $before[$key]) 'source changed' }
}
Run-Case 'corrupt bytes reject before creating target' {
    $copy = Clone-Backup 'corrupt-backup'
    [IO.File]::WriteAllText((Join-Path $copy 'state/runtime.json'), 'corrupt')
    $target = Join-Path $fixtureRoot 'corrupt-restore'
    Assert-Throws { & $restoreScript -BackupPath $copy -DestinationRoot $target } 'Checksum mismatch'
    Assert-True (-not (Test-Path $target)) 'invalid backup created target'
}
Run-Case 'traversal manifest rejects before creating target' {
    $copy = Clone-Backup 'traversal-backup'
    $path = Join-Path $copy 'backup-manifest.json'
    $m = Get-Content $path -Raw | ConvertFrom-Json
    $m.files[0].path = '../escape'
    $m | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
    $target = Join-Path $fixtureRoot 'traversal-restore'
    Assert-Throws { & $restoreScript -BackupPath $copy -DestinationRoot $target } 'Invalid manifest path'
    Assert-True (-not (Test-Path $target)) 'unsafe target created'
}
Run-Case 'extra payload rejects rather than silently restoring it' {
    $copy = Clone-Backup 'extra-backup'
    [IO.File]::WriteAllText((Join-Path $copy 'unlisted.txt'), 'extra')
    Assert-Throws { & $restoreScript -BackupPath $copy -DestinationRoot (Join-Path $fixtureRoot 'extra-restore') } 'unlisted payload'
}
Run-Case 'duplicate manifest paths are refused' {
    $copy = Clone-Backup 'duplicate-backup'
    $path = Join-Path $copy 'backup-manifest.json'
    $m = Get-Content $path -Raw | ConvertFrom-Json
    $m.files[1].path = $m.files[0].path
    $m | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
    Assert-Throws { & $restoreScript -BackupPath $copy -DestinationRoot (Join-Path $fixtureRoot 'duplicate-restore') } 'Duplicate manifest path'
}
Run-Case 'version 1 requires explicit manual recovery' {
    $copy = Clone-Backup 'v1-backup'
    $path = Join-Path $copy 'backup-manifest.json'
    $m = Get-Content $path -Raw | ConvertFrom-Json
    $m.schema_version = 1
    $m | ConvertTo-Json -Depth 8 | Set-Content $path -Encoding UTF8
    Assert-Throws { & $restoreScript -BackupPath $copy -DestinationRoot (Join-Path $fixtureRoot 'v1-restore') } 'manual process'
}
Run-Case 'backend starting during copy prevents a complete manifest' {
    $global:WebGISRecoveryTestState.ListenerMode = 'starts_after_copy'
    $global:WebGISRecoveryTestState.ListenerChecks = 0
    $target = Join-Path $fixtureRoot 'interrupted-backups'
    Assert-Throws { & $backupScript -RepoRoot $repo -DestinationRoot $target } 'Backend is listening'
    $partial = (Get-ChildItem $target -Directory | Select-Object -First 1).FullName
    Assert-True (-not (Test-Path (Join-Path $partial 'backup-manifest.json'))) 'partial copy certified complete'
    $global:WebGISRecoveryTestState.ListenerMode = 'stopped'
}
Run-Case 'nested backup junction is refused before restore writes' {
    $copy = Clone-Backup 'linked-backup'
    New-Item -ItemType Junction -Path (Join-Path $copy 'nested-link') -Target (Join-Path $repo 'backend/data/uploads') | Out-Null
    $target = Join-Path $fixtureRoot 'linked-restore'
    Assert-Throws { & $restoreScript -BackupPath $copy -DestinationRoot $target } 'Nested filesystem links'
    Assert-True (-not (Test-Path $target)) 'linked backup created restore target'
}
Run-Case 'live opt-in is explicitly recorded as unverified' {
    $global:WebGISRecoveryTestState.ListenerMode = 'listening'
    $root = Join-Path $fixtureRoot 'live-backups'
    & $backupScript -RepoRoot $repo -DestinationRoot $root -AllowLiveBackup
    $dir = (Get-ChildItem $root -Directory | Select-Object -First 1).FullName
    $m = Get-Content (Join-Path $dir 'backup-manifest.json') -Raw | ConvertFrom-Json
    Assert-True ($m.live_backup -and $m.consistency -eq 'live_or_unverified') 'live backup claims consistency'
    $global:WebGISRecoveryTestState.ListenerMode = 'stopped'
}
Run-Case 'destination junction into source rejects backup and restore' {
    $link = Join-Path $fixtureRoot 'destination-link'
    New-Item -ItemType Junction -Path $link -Target $repo | Out-Null
    Assert-Throws { & $backupScript -RepoRoot $repo -DestinationRoot (Join-Path $link 'backups') } 'protected source'
    Assert-Throws { & $restoreScript -BackupPath $script:ValidBackup -DestinationRoot (Join-Path $link 'restore') } 'protected source'
    Assert-True (-not (Test-Path (Join-Path $repo 'backups'))) 'junction escaped backup guard'
}
Run-Case 'intentional data-root junction is supported and resolved' {
    $code = Join-Path $fixtureRoot 'junction-source'
    New-Item -ItemType Directory -Path (Join-Path $code 'backend') -Force | Out-Null
    New-Item -ItemType Junction -Path (Join-Path $code 'backend/data') -Target (Join-Path $repo 'backend/data') | Out-Null
    $out = Join-Path $fixtureRoot 'junction-backups'
    & $backupScript -RepoRoot $code -DestinationRoot $out
    $dir = (Get-ChildItem $out -Directory | Select-Object -First 1).FullName
    $m = Get-Content (Join-Path $dir 'backup-manifest.json') -Raw | ConvertFrom-Json
    Assert-True ($m.baseline.source_data_resolved -eq (Join-Path $repo 'backend/data')) 'data junction not recorded'
    Assert-True ($m.file_count -eq 9 -and $m.warnings.Count -eq 3) 'missing resources not reported'
}
Run-Case 'nested source junction is refused instead of silently omitted' {
    $link = Join-Path $repo 'backend/data/nested-link'
    New-Item -ItemType Junction -Path $link -Target (Join-Path $repo 'backend/data/uploads') | Out-Null
    $target = Join-Path $fixtureRoot 'nested-backups'
    Assert-Throws { & $backupScript -RepoRoot $repo -DestinationRoot $target } 'Nested filesystem links'
    Assert-True (-not (Test-Path $target)) 'nested link rejection wrote files'
}
$failed = @($script:Results | Where-Object status -eq 'FAIL').Count
@{ fixture_root = $fixtureRoot; tests = $script:Results; passed = $script:Results.Count - $failed; failed = $failed
   production_accessed = $false; services_started = $false } |
    ConvertTo-Json -Depth 5 | Set-Content (Join-Path $fixtureRoot 'acceptance.json') -Encoding UTF8
Write-Host "RESULT $($script:Results.Count - $failed) passed, $failed failed; evidence: $fixtureRoot"
if ($failed) { throw "$failed recovery acceptance cases failed" }
