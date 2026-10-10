param([string]$PythonExe = '', [switch]$Foreground)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $PythonExe) {
    $PythonExe = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $PythonExe = $command.Source }
    }
}
if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw '未找到现有 Python。请指定 -PythonExe；连接器不会自动安装软件。'
}
if ($Foreground) {
    Push-Location $repoRoot
    try { & $PythonExe -m backend.app.desktop_powerpoint } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw '本机 PowerPoint 连接器未能启动。' }
    exit
}
$existing = @(Get-NetTCPConnection -State Listen -LocalPort 18998 -ErrorAction SilentlyContinue)
if ($existing.Count) {
    throw '本机18998端口已被占用，请确认是否已启动连接器；不会结束已有进程。'
}
$process = Start-Process -FilePath $PythonExe -ArgumentList @('-m', 'backend.app.desktop_powerpoint') -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 500
if ($process.HasExited) { throw '连接器启动失败，请使用 -Foreground 查看错误。' }
Write-Host "本机 PowerPoint 连接器已启动（PID $($process.Id)）。仅监听127.0.0.1:18998，不写教学数据、不安装服务。"
