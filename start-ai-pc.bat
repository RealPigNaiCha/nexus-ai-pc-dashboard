@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\AI-PC\app\dashboard\start.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请查看 C:\AI-PC\logs\dashboard.stderr.log
  pause
)
endlocal
