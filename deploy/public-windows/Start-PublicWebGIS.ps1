[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$Domain = "webgisai.com",
    [int]$BackendPort = 18999,
    [int]$ProxyPort = 18080,
    [switch]$InstallFrontendDependencies,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

function Resolve-Executable {
    param(
        [string]$Name,
        [string[]]$Candidates = @()
    )

    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    throw "未找到 $Name。请先按 deploy/public-windows/README.md 安装发布依赖。"
}

function Assert-PortAvailable {
    param([int]$Port)

    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listener) {
        throw "端口 $Port 已被占用。请先停止旧服务，再运行此脚本。"
    }
}

function Wait-HttpReady {
    param(
        [string]$Url,
        [int]$Attempts = 40
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            return Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "服务未按时就绪：$Url"
}

function Test-HttpReady {
    param([string]$Url)

    try {
        $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 3
        return $null -ne $response
    }
    catch {
        return $false
    }
}

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$Value)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

if ($Domain -notmatch '^[A-Za-z0-9.-]+$') {
    throw "域名格式不正确：$Domain"
}

$repoRoot = if ($RepoRoot) {
    (Resolve-Path -LiteralPath $RepoRoot).Path
}
else {
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}
$frontendDir = Join-Path $repoRoot "frontend"
$frontendDist = Join-Path $frontendDir "dist"
$runtimeDir = Join-Path $repoRoot "backend\data\public-runtime"
$caddyConfig = Join-Path $PSScriptRoot "Caddyfile"
$cloudflaredRepairScript = Join-Path $PSScriptRoot "Repair-CloudflaredTunnel.ps1"

$pythonCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
)
$caddyCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\caddy.exe"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\CaddyServer.Caddy_Microsoft.Winget.Source_8wekyb3d8bbwe\caddy.exe")
)
$pythonExe = Resolve-Executable -Name "python" -Candidates $pythonCandidates
$npmExe = Resolve-Executable -Name "npm.cmd" -Candidates @("C:\Program Files\nodejs\npm.cmd")
$caddyExe = Resolve-Executable -Name "caddy" -Candidates $caddyCandidates

$runtimeEnvNames = @(
    "WEBGIS_AI_LLM_PROVIDER",
    "WEBGIS_AI_MIMO_API_KEY",
    "WEBGIS_AI_MIMO_BASE_URL",
    "WEBGIS_AI_MIMO_MODEL",
    "WEBGIS_AI_MINIMAX_API_KEY",
    "WEBGIS_AI_MINIMAX_BASE_URL",
    "WEBGIS_AI_MINIMAX_MODEL",
    "WEBGIS_AI_MINIMAX_IMAGE_BASE_URL",
    "WEBGIS_AI_MINIMAX_IMAGE_MODEL",
    "WEBGIS_AI_VISION_PROVIDER",
    "WEBGIS_AI_VISION_ENABLED",
    "WEBGIS_AI_VISION_MODEL",
    "MIMO_API_KEY",
    "MIMO_BASE_URL",
    "MIMO_MODEL",
    "XIAOMI_MIMO_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_ANTHROPIC_BASE_URL",
    "MINIMAX_MODEL",
    "QGIS_ROOT",
    "WEBGIS_AI_QGIS_ROOT",
    "WEBGIS_AI_QGIS_PYTHON"
)
foreach ($name in $runtimeEnvNames) {
    if (Get-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue) {
        continue
    }
    foreach ($scope in @("User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($name, $scope)
        if ($value) {
            Set-Item -LiteralPath "Env:$name" -Value $value
            break
        }
    }
}

if (-not ($env:QGIS_ROOT -or $env:WEBGIS_AI_QGIS_ROOT)) {
    $qgisCandidates = @(
        "D:\QGIS 3.40.10",
        "C:\OSGeo4W",
        "C:\OSGeo4W64"
    )
    $qgisCandidates += Get-ChildItem -LiteralPath "C:\Program Files" -Directory -ErrorAction SilentlyContinue |
        Where-Object Name -Match '^QGIS' |
        ForEach-Object { $_.FullName }
    $qgisRoot = $qgisCandidates |
        Where-Object { Test-Path -LiteralPath (Join-Path $_ "bin\python.exe") } |
        Select-Object -First 1
    if ($qgisRoot) {
        $env:QGIS_ROOT = $qgisRoot
        $env:WEBGIS_AI_QGIS_ROOT = $qgisRoot
        $env:WEBGIS_AI_QGIS_PYTHON = Join-Path $qgisRoot "bin\python.exe"
    }
}

$backendHealthUrl = "http://127.0.0.1:$BackendPort/health"
$proxyHealthUrl = "http://127.0.0.1:$ProxyPort/health"
$backendAlreadyReady = Test-HttpReady -Url $backendHealthUrl
$proxyAlreadyReady = Test-HttpReady -Url $proxyHealthUrl

$cloudflaredService = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($cloudflaredService -and (Test-Path -LiteralPath $cloudflaredRepairScript)) {
    $cloudflaredImagePath = [string](Get-ItemProperty -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared" -Name ImagePath -ErrorAction SilentlyContinue).ImagePath
    if ($cloudflaredImagePath -notmatch '(?i)--protocol\s+http2') {
        Write-Host "首次启用稳定公网模式需要一次管理员确认。" -ForegroundColor Yellow
        $repairProcess = Start-Process `
            -FilePath "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" `
            -Verb RunAs `
            -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ('"' + $cloudflaredRepairScript + '"')) `
            -Wait `
            -PassThru
        if ($repairProcess.ExitCode -ne 0) {
            throw "Cloudflared 稳定模式配置未完成。请在管理员确认窗口中点击是后重试。"
        }
    }
    elseif ($cloudflaredService.Status -ne "Running") {
        Write-Warning "Cloudflared 服务未运行，请以管理员身份启动该服务。"
    }
}

if ($backendAlreadyReady -and $proxyAlreadyReady) {
    Write-Host "WebGIS-AI 本地源站已经运行，已直接复用现有进程。" -ForegroundColor Green
    Write-Host "本机检查：http://127.0.0.1:$ProxyPort"
    Write-Host "公网入口：https://$Domain"
    Write-Host "无需重复构建或占用端口；如果公网显示 Down，请检查 Cloudflared 服务状态。"
    return
}

if ($backendAlreadyReady -or $proxyAlreadyReady) {
    throw "检测到 WebGIS-AI 仅有部分服务仍在运行。请先运行桌面上的关闭网站，再重新启动。"
}

Assert-PortAvailable -Port $BackendPort
Assert-PortAvailable -Port $ProxyPort
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

$env:WEBGIS_AI_HOST = "127.0.0.1"
$env:WEBGIS_AI_PORT = [string]$BackendPort
$env:WEBGIS_AI_AUTH_MODE = "users"
$env:WEBGIS_AI_COOKIE_SECURE = "true"
$env:WEBGIS_AI_CORS_ALLOW_ORIGINS = "https://$Domain,https://www.$Domain"
$env:VITE_API_BASE_URL = "https://$Domain"
$env:WEBGIS_AI_PUBLIC_PROXY_PORT = [string]$ProxyPort
$env:WEBGIS_AI_FRONTEND_DIST = $frontendDist.Replace("\", "/")

if (-not $SkipFrontendBuild) {
    Push-Location $frontendDir
    try {
        if ($InstallFrontendDependencies) {
            & $npmExe ci
            if ($LASTEXITCODE -ne 0) {
                throw "npm ci 失败，退出码：$LASTEXITCODE"
            }
        }
        elseif (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
            throw "缺少 frontend/node_modules。请加 -InstallFrontendDependencies 后重试。"
        }

        & $npmExe run build
        if ($LASTEXITCODE -ne 0) {
            throw "前端生产构建失败，退出码：$LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendDist "index.html"))) {
    throw "未找到 frontend/dist/index.html，请先完成前端生产构建。"
}

$backendStdout = Join-Path $runtimeDir "backend.stdout.log"
$backendStderr = Join-Path $runtimeDir "backend.stderr.log"
$caddyStdout = Join-Path $runtimeDir "caddy.stdout.log"
$caddyStderr = Join-Path $runtimeDir "caddy.stderr.log"
$backendProcess = $null
$caddyProcess = $null

try {
    $backendStart = @{
        FilePath = $pythonExe
        ArgumentList = @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", [string]$BackendPort)
        WorkingDirectory = $repoRoot
        RedirectStandardOutput = $backendStdout
        RedirectStandardError = $backendStderr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $backendProcess = Start-Process @backendStart

    $health = Wait-HttpReady -Url $backendHealthUrl
    $bootstrap = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/auth/bootstrap-status" -Method Get -TimeoutSec 5
    if ($bootstrap.required) {
        Write-Host "首次公网运行需要先创建管理员。信息只提交到本机后端。" -ForegroundColor Yellow
        $email = Read-Host "管理员邮箱"
        $nickname = Read-Host "管理员昵称"
        $securePassword = Read-Host "管理员密码（8-128 位，至少包含两类字符）" -AsSecureString
        $password = Convert-SecureStringToPlainText -Value $securePassword
        try {
            $payload = @{
                email = $email
                nickname = $nickname
                password = $password
            } | ConvertTo-Json
            $bootstrapRequest = @{
                Uri = "http://127.0.0.1:$BackendPort/auth/bootstrap"
                Method = "Post"
                ContentType = "application/json"
                Body = $payload
                TimeoutSec = 15
            }
            Invoke-RestMethod @bootstrapRequest | Out-Null
        }
        finally {
            $password = $null
            $securePassword.Dispose()
        }
        Write-Host "管理员已创建。" -ForegroundColor Green
    }

    $caddyStart = @{
        FilePath = $caddyExe
        ArgumentList = @("run", "--config", $caddyConfig, "--adapter", "caddyfile")
        WorkingDirectory = $repoRoot
        RedirectStandardOutput = $caddyStdout
        RedirectStandardError = $caddyStderr
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $caddyProcess = Start-Process @caddyStart

    Wait-HttpReady -Url $proxyHealthUrl | Out-Null
    Set-Content -LiteralPath (Join-Path $runtimeDir "backend.pid") -Value $backendProcess.Id -Encoding ascii
    Set-Content -LiteralPath (Join-Path $runtimeDir "caddy.pid") -Value $caddyProcess.Id -Encoding ascii

    $gitCommit = ""
    $gitBranch = ""
    $gitCommand = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCommand) {
        $gitCommit = (& $gitCommand.Source -C $repoRoot rev-parse HEAD 2>$null | Select-Object -First 1)
        $gitBranch = (& $gitCommand.Source -C $repoRoot branch --show-current 2>$null | Select-Object -First 1)
    }
    $indexHtml = Get-Content -LiteralPath (Join-Path $frontendDist "index.html") -Raw
    $frontendAsset = [regex]::Match($indexHtml, 'assets/index-[^"'']+\.js').Value
    $releaseQgisRoot = if ($env:QGIS_ROOT) { $env:QGIS_ROOT } else { $env:WEBGIS_AI_QGIS_ROOT }
    @{
        started_at = (Get-Date).ToString("o")
        domain = $Domain
        git_commit = [string]$gitCommit
        git_branch = [string]$gitBranch
        frontend_asset = $frontendAsset
        backend_port = $BackendPort
        proxy_port = $ProxyPort
        qgis_root = [string]$releaseQgisRoot
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtimeDir "release.json") -Encoding utf8

    Write-Host "WebGIS-AI 公网源站已启动。" -ForegroundColor Green
    Write-Host "本机检查：http://127.0.0.1:$ProxyPort"
    Write-Host "公网入口：https://$Domain"
    Write-Host "若公网尚不可访问，请继续完成 Cloudflare Tunnel 的域名和服务安装步骤。"
    if (-not ($env:QGIS_ROOT -or $env:WEBGIS_AI_QGIS_ROOT)) {
        Write-Warning "当前进程没有读取到 QGIS_ROOT；基础功能可启动，但 PyQGIS 工作流可能不可用。"
    }
}
catch {
    if ($caddyProcess -and -not $caddyProcess.HasExited) {
        Stop-Process -Id $caddyProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    throw
}
