@echo off
chcp 65001 >nul
setlocal
title Nexus AI-PC Installer
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"
if errorlevel 1 (
  echo.
  echo Installation failed. See the message above.
  pause
  exit /b 1
)
echo.
echo Installation completed.
pause
endlocal
