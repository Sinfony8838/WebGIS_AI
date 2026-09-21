[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$Domain = "webgisai.com",
    [int]$BackendPort = 18999,
    [int]$ProxyPort = 18080,
    [int]$TimeoutSec = 10,
    [switch]$SkipPublicCheck
)

$ErrorActionPreference = "Stop"
$repoRoot = if ($RepoRoot) {
    (Resolve-Path -LiteralPath $RepoRoot).Path
}
else {
    (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}
$runtimeDir = Join-Path $repoRoot "backend\data\public-runtime"
$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [ValidateSet("OK", "WARN", "FAIL")]
        [string]$Status,
        [string]$Details
    )
    $checks.Add([pscustomobject]@{
        Check = $Name
        Status = $Status
        Details = $Details
    })
}

function Test-ManagedProcess {
    param(
        [string]$Name,
        [string[]]$ExpectedNames
    )
    $pidPath = Join-Path $runtimeDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        Add-Check -Name "$Name process" -Status "FAIL" -Details "缺少 PID 文件：$pidPath"
        return
    }
    try {
        $processId = [int](Get-Content -LiteralPath $pidPath -Raw)
        $process = Get-Process -Id $processId -ErrorAction Stop
        if ($process.ProcessName -notin $ExpectedNames) {
            Add-Check -Name "$Name process" -Status "FAIL" -Details "PID $processId 属于 $($process.ProcessName)"
            return
        }
        Add-Check -Name "$Name process" -Status "OK" -Details "PID $processId ($($process.ProcessName))"
    }
    catch {
        Add-Check -Name "$Name process" -Status "FAIL" -Details "PID 文件存在，但进程未运行"
    }
}

function Invoke-CheckedWebRequest {
    param(
        [string]$Name,
        [string]$Uri,
        [hashtable]$Headers = @{},
        [switch]$RequireBody,
        [switch]$Public
    )
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec
        $length = if ($null -ne $response.Content) { $response.Content.Length } else { 0 }
        if ($response.StatusCode -ne 200) {
            Add-Check -Name $Name -Status "FAIL" -Details "HTTP $($response.StatusCode)"
            return $null
        }
        if ($RequireBody -and $length -eq 0) {
            $status = if ($Public) { "WARN" } else { "FAIL" }
            Add-Check -Name $Name -Status $status -Details "HTTP 200，但正文为空"
            return $response
        }
        Add-Check -Name $Name -Status "OK" -Details "HTTP 200，$length 字符"
        return $response
    }
    catch {
        $status = if ($Public) { "WARN" } else { "FAIL" }
        Add-Check -Name $Name -Status $status -Details $_.Exception.Message
        return $null
    }
}

try {
    $service = Get-Service -Name "cloudflared" -ErrorAction Stop
    $serviceStatus = if ($service.Status -eq "Running") { "OK" } else { "FAIL" }
    Add-Check -Name "cloudflared service" -Status $serviceStatus -Details "$($service.Status), $($service.StartType)"
}
catch {
    Add-Check -Name "cloudflared service" -Status "FAIL" -Details "未找到 Windows 服务"
}

Test-ManagedProcess -Name "backend" -ExpectedNames @("python", "pythonw")
Test-ManagedProcess -Name "caddy" -ExpectedNames @("caddy")

$backendResponse = Invoke-CheckedWebRequest -Name "backend health" -Uri "http://127.0.0.1:$BackendPort/health" -RequireBody
$proxyHeaders = @{ Host = $Domain }
$proxyHealth = Invoke-CheckedWebRequest -Name "local proxy health" -Uri "http://127.0.0.1:$ProxyPort/health" -Headers $proxyHeaders -RequireBody
$proxyRoot = Invoke-CheckedWebRequest -Name "local proxy root" -Uri "http://127.0.0.1:$ProxyPort/" -Headers $proxyHeaders -RequireBody

$localIndexPath = Join-Path $repoRoot "frontend\dist\index.html"
$localAsset = ""
if (Test-Path -LiteralPath $localIndexPath) {
    $localHtml = Get-Content -LiteralPath $localIndexPath -Raw
    $localAsset = [regex]::Match($localHtml, 'assets/index-[^"'']+\.js').Value
    if ($localAsset) {
        Add-Check -Name "local release asset" -Status "OK" -Details $localAsset
    }
    else {
        Add-Check -Name "local release asset" -Status "FAIL" -Details "index.html 中未找到版本化 JS"
    }
}
else {
    Add-Check -Name "local release asset" -Status "FAIL" -Details "缺少 frontend/dist/index.html"
}

if (-not $SkipPublicCheck) {
    try {
        $dnsAddresses = Resolve-DnsName $Domain -Type A -ErrorAction Stop |
            Where-Object IPAddress |
            ForEach-Object { $_.IPAddress }
        $fakeDns = $dnsAddresses | Where-Object {
            $_ -like "198.18.*" -or $_ -like "198.19.*" -or $_ -like "28.*"
        }
        if ($fakeDns) {
            Add-Check -Name "public DNS" -Status "WARN" -Details "检测到代理虚拟地址：$($fakeDns -join ', ')；请再用手机流量复核"
        }
        else {
            Add-Check -Name "public DNS" -Status "OK" -Details ($dnsAddresses -join ", ")
        }
    }
    catch {
        Add-Check -Name "public DNS" -Status "WARN" -Details $_.Exception.Message
    }

    $publicHealth = Invoke-CheckedWebRequest -Name "public health" -Uri "https://$Domain/health" -RequireBody -Public
    $publicRoot = Invoke-CheckedWebRequest -Name "public root" -Uri "https://$Domain/" -RequireBody -Public
    if ($publicRoot -and $localAsset) {
        $publicAsset = [regex]::Match([string]$publicRoot.Content, 'assets/index-[^"'']+\.js').Value
        if ($publicAsset -and $publicAsset -eq $localAsset) {
            Add-Check -Name "public release asset" -Status "OK" -Details $publicAsset
        }
        elseif ($publicAsset) {
            Add-Check -Name "public release asset" -Status "FAIL" -Details "公网 $publicAsset；本机 $localAsset"
        }
        else {
            Add-Check -Name "public release asset" -Status "WARN" -Details "无法从公网首页识别版本化 JS"
        }
    }
}

if (Test-Path -LiteralPath (Join-Path $runtimeDir "release.json")) {
    try {
        $release = Get-Content -LiteralPath (Join-Path $runtimeDir "release.json") -Raw | ConvertFrom-Json
        Add-Check -Name "release metadata" -Status "OK" -Details "$($release.git_commit) / $($release.started_at)"
    }
    catch {
        Add-Check -Name "release metadata" -Status "WARN" -Details "release.json 无法解析"
    }
}
else {
    Add-Check -Name "release metadata" -Status "WARN" -Details "下次用 Start-PublicWebGIS.ps1 启动后生成"
}

$checks | Format-Table -AutoSize -Wrap
$failures = @($checks | Where-Object Status -eq "FAIL")
$warnings = @($checks | Where-Object Status -eq "WARN")
Write-Host ""
Write-Host "Summary: $($checks.Count) checks, $($failures.Count) failed, $($warnings.Count) warnings."
if ($failures.Count -gt 0) {
    exit 1
}
