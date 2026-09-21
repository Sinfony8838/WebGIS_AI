#Requires -RunAsAdministrator
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$serviceName = "cloudflared"
$serviceRegistryPath = "HKLM:\SYSTEM\CurrentControlSet\Services\cloudflared"
$cloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$tokenFile = "C:\ProgramData\cloudflared\token"

if (-not (Test-Path -LiteralPath $cloudflaredExe)) {
    throw "cloudflared executable was not found: $cloudflaredExe"
}
if (-not (Test-Path -LiteralPath $tokenFile)) {
    throw "Cloudflare Tunnel token file was not found: $tokenFile"
}
if (-not (Test-Path -LiteralPath $serviceRegistryPath)) {
    throw "Cloudflared Windows service was not found."
}

$oldCommand = [string](Get-ItemProperty -LiteralPath $serviceRegistryPath -Name ImagePath).ImagePath
$newCommand = '"' + $cloudflaredExe + '" tunnel --protocol http2 --edge-ip-version 4 run --token-file ' + $tokenFile

if ($oldCommand -ne $newCommand) {
    Set-ItemProperty -LiteralPath $serviceRegistryPath -Name ImagePath -Value $newCommand
}

try {
    Restart-Service -Name $serviceName -Force
    $service = Get-Service -Name $serviceName
    $service.WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Running,
        [TimeSpan]::FromSeconds(20)
    )
}
catch {
    Set-ItemProperty -LiteralPath $serviceRegistryPath -Name ImagePath -Value $oldCommand
    Start-Service -Name $serviceName -ErrorAction SilentlyContinue
    throw "Cloudflared could not start with HTTP/2. The previous configuration was restored. $($_.Exception.Message)"
}

$savedCommand = [string](Get-ItemProperty -LiteralPath $serviceRegistryPath -Name ImagePath).ImagePath
if ($savedCommand -ne $newCommand) {
    throw "Cloudflared service configuration verification failed."
}

Write-Host "Cloudflared now uses HTTP/2 and IPv4." -ForegroundColor Green
Write-Host "This setting persists after Windows restarts."
