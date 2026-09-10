[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
$runtimeDir = Join-Path $repoRoot "backend\data\public-runtime"
$expectedProcessNames = @{
    caddy = @("caddy")
    backend = @("python", "pythonw")
}

foreach ($name in @("caddy", "backend")) {
    $pidPath = Join-Path $runtimeDir "$name.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        continue
    }

    $processId = [int](Get-Content -LiteralPath $pidPath -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in $expectedProcessNames[$name]) {
        Stop-Process -Id $processId
        Write-Host "已停止 $name（PID $processId）。"
    }
    elseif ($process) {
        Write-Warning "PID $processId 当前属于 $($process.ProcessName)，未停止该进程。"
    }
    Remove-Item -LiteralPath $pidPath -Force
}
