# Shared helpers for backup and isolated restore. Never import the application.
Set-StrictMode -Version 2.0

function Resolve-RecoveryPhysicalPath {
    param([Parameter(Mandatory)][string]$Path, [int]$Depth = 0)
    if ($Depth -gt 16) { throw "Too many filesystem link levels: $Path" }
    $full = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetPathRoot($full)
    $current = $root
    foreach ($part in $full.Substring($root.Length).Split([char[]]'\/')) {
        if (-not $part) { continue }
        $current = Join-Path $current $part
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                $targets = @($item.Target)
                if ($targets.Count -ne 1 -or -not $targets[0]) { throw "Unsupported filesystem link: $current" }
                $target = [string]$targets[0]
                if (-not [IO.Path]::IsPathRooted($target)) { $target = Join-Path (Split-Path $current -Parent) $target }
                $current = Resolve-RecoveryPhysicalPath -Path $target -Depth ($Depth + 1)
            }
        }
    }
    return [IO.Path]::GetFullPath($current)
}

function Test-RecoveryPathWithin {
    param([string]$Path, [string]$Root)
    $base = [IO.Path]::GetFullPath($Root).TrimEnd([char[]]'\/')
    $candidate = [IO.Path]::GetFullPath($Path).TrimEnd([char[]]'\/')
    return $candidate.Equals($base, [StringComparison]::OrdinalIgnoreCase) -or
        $candidate.StartsWith($base + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-RecoveryDestinationOutside {
    param([string]$Destination, [string[]]$ProtectedRoots)
    $physical = Resolve-RecoveryPhysicalPath $Destination
    foreach ($root in $ProtectedRoots) {
        if ((Test-RecoveryPathWithin $Destination $root) -or
            (Test-RecoveryPathWithin $physical (Resolve-RecoveryPhysicalPath $root))) {
            throw "Destination resolves inside a protected source directory: $Destination"
        }
    }
    return $physical
}

function Get-RecoveryTreeFiles {
    param([string]$Root, [string[]]$ExcludeTopLevel = @(), [switch]$IncludeEmptyDirectories)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return }
    $physicalRoot = Resolve-RecoveryPhysicalPath $Root
    $pending = [Collections.Generic.Stack[string]]::new()
    $pending.Push($physicalRoot)
    while ($pending.Count -gt 0) {
        $dir = $pending.Pop()
        $items = @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)
        if ($IncludeEmptyDirectories -and $items.Count -eq 0 -and $dir -ne $physicalRoot) {
            Get-Item -LiteralPath $dir -Force
        }
        foreach ($item in $items) {
            if ($dir -eq $physicalRoot -and $item.Name -in $ExcludeTopLevel) { continue }
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Nested filesystem links must be inventoried separately: $($item.FullName)"
            }
            if ($item.PSIsContainer) { $pending.Push($item.FullName) }
            else { $item }
        }
    }
}

function Assert-RecoveryRelativePath {
    param([string]$Path)
    if (-not $Path -or [IO.Path]::IsPathRooted($Path) -or $Path -match '[\x00-\x1f<>:"|?*\\]') {
        throw "Invalid manifest path: $Path"
    }
    foreach ($part in $Path.Split('/')) {
        if (-not $part -or $part -in @('.', '..') -or $part.TrimEnd(' ', '.') -ne $part) {
            throw "Invalid manifest path: $Path"
        }
    }
}

function Get-RecoveryBaseline {
    param([string]$RepoRoot, [string]$PreviousCommit = '')
    $dataPath = Join-Path $RepoRoot 'backend/data'
    $gitCommit = $null
    $gitBranch = $null
    $gitDirty = $null
    if (Test-Path -LiteralPath (Join-Path $RepoRoot '.git')) {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) {
            $value = & $git.Source --no-optional-locks -C $RepoRoot rev-parse HEAD 2>$null
            if ($LASTEXITCODE -eq 0) {
                $gitCommit = [string]($value | Select-Object -First 1)
                $gitBranch = [string](& $git.Source --no-optional-locks -C $RepoRoot branch --show-current 2>$null | Select-Object -First 1)
                $status = @(& $git.Source --no-optional-locks -C $RepoRoot status --porcelain --untracked-files=no 2>$null)
                if ($LASTEXITCODE -eq 0) { $gitDirty = $status.Count -gt 0 }
            }
        }
    }
    # This allowlist is metadata only. No environment variables or auth DB reads.
    $recordedRelease = @{}
    $releasePath = Join-Path $dataPath 'public-runtime/release.json'
    if (Test-Path -LiteralPath $releasePath -PathType Leaf) {
        $release = Get-Content -LiteralPath $releasePath -Raw -ErrorAction Stop | ConvertFrom-Json
        foreach ($key in @('started_at', 'git_commit', 'frontend_asset', 'backend_port', 'proxy_port', 'qgis_root')) {
            $prop = $release.PSObject.Properties[$key]
            if ($prop) { $recordedRelease[$key] = $prop.Value }
        }
    }
    $frontendAsset = $null
    $indexPath = Join-Path $RepoRoot 'frontend/dist/index.html'
    if (Test-Path -LiteralPath $indexPath -PathType Leaf) {
        $html = Get-Content -LiteralPath $indexPath -Raw -ErrorAction Stop
        $frontendAsset = [regex]::Match($html, 'assets/index-[^"'']+\.js').Value
    }
    return @{
        source_repo = $RepoRoot
        source_repo_resolved = Resolve-RecoveryPhysicalPath $RepoRoot
        source_data = $dataPath
        source_data_resolved = Resolve-RecoveryPhysicalPath $dataPath
        git_commit = $gitCommit
        git_branch = $gitBranch
        git_dirty = $gitDirty
        previous_commit = $PreviousCommit
        frontend_asset = $frontendAsset
        recorded_release = $recordedRelease
        external_dependencies = @('Python API environment', 'QGIS Python/runtime', 'PowerPoint or LibreOffice', 'Caddy/cloudflared', 'Voice model files or explicit external model root')
        external_dependencies_restored = $false
    }
}

function Assert-RecoveryBackendStopped {
    param([int]$Port)
    # A cmdlet failure must not masquerade as an empty listener list.
    try { $connections = @(Get-NetTCPConnection -State Listen -ErrorAction Stop) }
    catch { throw "Cannot verify stopped backend; backup refused: $($_.Exception.Message)" }
    if (@($connections | Where-Object LocalPort -eq $Port).Count -gt 0) {
        throw "Backend is listening on $Port; stop writers before backup or explicitly accept -AllowLiveBackup."
    }
}
