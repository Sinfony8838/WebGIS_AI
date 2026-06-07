param(
    [switch]$OpenBrowser,
    [switch]$InstallIfMissing,
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[WebGIS-AI] $Message" -ForegroundColor Cyan
}

function Get-PythonVersionString {
    param([string]$PythonExe)

    try {
        return ((& $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')") | Select-Object -First 1).ToString().Trim()
    }
    catch {
        return $null
    }
}

function Resolve-Python312 {
    param([string]$RequestedPythonExe)

    $candidates = New-Object System.Collections.Generic.List[string]

    if ($RequestedPythonExe) {
        $candidates.Add($RequestedPythonExe)
    }

    @(
        "C:\Users\zcyxn\AppData\Local\Programs\Python\Python312\python.exe",
        "D:\Anaconda3\python.exe"
    ) | ForEach-Object {
        $candidates.Add($_)
    }

    try {
        $wherePython = & where.exe python 2>$null
        foreach ($candidate in $wherePython) {
            if ($candidate) {
                $candidates.Add($candidate)
            }
        }
    }
    catch {
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $candidates.Add($pythonCmd.Source)
    }

    $uniqueCandidates = $candidates | Where-Object { $_ } | Select-Object -Unique

    foreach ($candidate in $uniqueCandidates) {
        if (Test-Path $candidate) {
            Write-Step "Checking Python candidate: $candidate"
            $version = Get-PythonVersionString -PythonExe $candidate
            if ($version) {
                Write-Step "Detected Python version $version at $candidate"
            }
            else {
                Write-Step "Could not query Python version at $candidate"
            }

            if ($version -and [version]$version -ge [version]"3.10") {
                return $candidate
            }
        }
    }

    if ($RequestedPythonExe) {
        throw "The requested Python interpreter is unavailable or below 3.10: $RequestedPythonExe"
    }

    throw "No usable Python 3.10+ interpreter was found. Please install and use Python 3.12."
}

function Test-PythonModule {
    param(
        [string]$PythonExe,
        [string]$ModuleName
    )

    & $PythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$ModuleName') else 1)" | Out-Null
    return $LASTEXITCODE -eq 0
}

function Ensure-BackendDeps {
    param(
        [string]$RepoRoot,
        [string]$PythonExe,
        [bool]$AllowInstall
    )

    $requiredModules = @("fastapi", "uvicorn", "multipart")
    $missing = @()
    foreach ($module in $requiredModules) {
        if (-not (Test-PythonModule -PythonExe $PythonExe -ModuleName $module)) {
            $missing += $module
        }
    }

    if ($missing.Count -eq 0) {
        return
    }

    if (-not $AllowInstall) {
        throw "Missing backend dependencies: $($missing -join ', '). Run `n& '$PythonExe' -m pip install -r '$RepoRoot\requirements.txt'`nor use -InstallIfMissing."
    }

    Write-Step "Missing backend dependencies detected. Installing now."
    & $PythonExe -m pip install -r (Join-Path $RepoRoot "requirements.txt")
}

function Ensure-FrontendDeps {
    param(
        [string]$RepoRoot,
        [string]$NodeExe,
        [string]$NpmCli,
        [bool]$AllowInstall
    )

    $nodeModulesPath = Join-Path $RepoRoot "frontend\node_modules"
    if (Test-Path $nodeModulesPath) {
        return
    }

    if (-not $AllowInstall) {
        throw "Frontend dependencies are not installed. Run npm install in the frontend directory or use -InstallIfMissing."
    }

    Write-Step "Missing frontend dependencies detected. Installing now."
    Push-Location (Join-Path $RepoRoot "frontend")
    try {
        & $NodeExe $NpmCli install
    }
    finally {
        Pop-Location
    }
}

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )

    $fullCommand = @"
Set-Location '$WorkingDirectory'
`$Host.UI.RawUI.WindowTitle = '$Title'
$Command
"@

    return Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-ExecutionPolicy", "Bypass", "-NoExit", "-Command", $fullCommand) `
        -PassThru
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $repoRoot "frontend"
$stateDir = Join-Path $repoRoot "backend\data\state"
$stateFile = Join-Path $stateDir "startup_processes.json"

$envNames = @(
    "WEBGIS_AI_LLM_PROVIDER",
    "WEBGIS_AI_MIMO_API_KEY",
    "WEBGIS_AI_MIMO_BASE_URL",
    "WEBGIS_AI_MIMO_MODEL",
    "WEBGIS_AI_VISION_PROVIDER",
    "WEBGIS_AI_VISION_ENABLED",
    "WEBGIS_AI_VISION_MODEL",
    "MIMO_API_KEY",
    "XIAOMI_MIMO_API_KEY",
    "QGIS_ROOT",
    "WEBGIS_AI_QGIS_ROOT",
    "WEBGIS_AI_QGIS_PYTHON"
)
foreach ($name in $envNames) {
    $value = [Environment]::GetEnvironmentVariable($name, "User")
    if ($value) {
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Resolve-QgisRoot {
    # Already set by the user / environment? Trust it.
    foreach ($var in @($env:QGIS_ROOT, $env:WEBGIS_AI_QGIS_ROOT)) {
        if ($var -and (Test-Path (Join-Path $var "bin\python.exe"))) {
            return $var
        }
    }
    # Hunt common OSGeo4W install roots: C:\OSGeo4W, C:\Program Files\QGIS x.y,
    # plus every drive letter at the root level (matches D:\QGIS 3.40.10).
    $candidates = New-Object System.Collections.Generic.List[string]
    @('C:\OSGeo4W', 'C:\OSGeo4W64') | ForEach-Object { $candidates.Add($_) }
    $programDirs = @('C:\Program Files', 'C:\Program Files (x86)')
    foreach ($programDir in $programDirs) {
        Get-ChildItem -Path $programDir -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^QGIS' } |
            ForEach-Object { $candidates.Add($_.FullName) }
    }
    Get-PSDrive -PSProvider FileSystem | ForEach-Object {
        Get-ChildItem -Path $_.Root -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^QGIS' -or $_.Name -match '^OSGeo4W' } |
            ForEach-Object { $candidates.Add($_.FullName) }
    }
    foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (Test-Path (Join-Path $candidate "bin\python.exe")) {
            return $candidate
        }
    }
    return $null
}

$qgisRoot = Resolve-QgisRoot
if ($qgisRoot) {
    Write-Step "Detected QGIS install at: $qgisRoot"
    $env:QGIS_ROOT = $qgisRoot
    $env:WEBGIS_AI_QGIS_ROOT = $qgisRoot
    $qgisPython = Join-Path $qgisRoot "bin\python.exe"
    if (Test-Path $qgisPython) {
        $env:WEBGIS_AI_QGIS_PYTHON = $qgisPython
        Write-Step "PyQGIS worker will spawn under: $qgisPython"
    }
}
else {
    Write-Step "[warn] No QGIS install detected. Workflow steps will fail with QGIS_ENV_NOT_READY."
    Write-Step "[hint] Set QGIS_ROOT to your QGIS install dir (the folder containing bin\python.exe) and re-run."
}

$pythonExe = Resolve-Python312 -RequestedPythonExe $PythonExe
$nodeExe = "C:\Program Files\nodejs\node.exe"
$npmCli = "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"

if (-not (Test-Path $nodeExe)) {
    throw "Node.js was not found: $nodeExe"
}

if (-not (Test-Path $npmCli)) {
    throw "npm-cli.js was not found: $npmCli"
}

Write-Step "Repository root: $repoRoot"
Write-Step "Using Python: $pythonExe"
Write-Step "Using Node: $nodeExe"

Ensure-BackendDeps -RepoRoot $repoRoot -PythonExe $pythonExe -AllowInstall:$InstallIfMissing
Ensure-FrontendDeps -RepoRoot $repoRoot -NodeExe $nodeExe -NpmCli $npmCli -AllowInstall:$InstallIfMissing

$backendCommand = "& '$pythonExe' -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 18999"
$frontendCommand = "& '$nodeExe' '$npmCli' run dev"

Write-Step "Starting backend window."
$backendProcess = Start-ServiceWindow -Title "WebGIS-AI Backend" -WorkingDirectory $repoRoot -Command $backendCommand

Write-Step "Starting frontend window."
$frontendProcess = Start-ServiceWindow -Title "WebGIS-AI Frontend" -WorkingDirectory $frontendRoot -Command $frontendCommand

New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
@{
    backend_pid = $backendProcess.Id
    frontend_pid = $frontendProcess.Id
    backend_url = "http://127.0.0.1:18999"
    frontend_url = "http://127.0.0.1:5173"
    started_at = (Get-Date).ToString("s")
} | ConvertTo-Json | Set-Content -Path $stateFile -Encoding utf8

Write-Step "Startup complete."
Write-Host ""
Write-Host "Backend: http://127.0.0.1:18999" -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "PID log: $stateFile" -ForegroundColor DarkGray

if ($OpenBrowser) {
    Write-Step "Opening browser."
    Start-Process "http://127.0.0.1:5173"
}
