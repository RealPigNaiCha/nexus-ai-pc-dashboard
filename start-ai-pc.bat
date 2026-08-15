@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请查看 ..\..\logs\dashboard.stderr.log
  pause
)
endlocal
