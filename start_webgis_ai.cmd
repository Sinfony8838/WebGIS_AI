@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\start_webgis_ai.ps1" -InstallIfMissing -OpenBrowser %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [WebGIS-AI] Startup failed. Review the error above.
    pause
)

exit /b %EXIT_CODE%

