@echo off
chcp 65001 >nul
setlocal
title Nexus AI-PC Installer
set "INSTALL_ROOT=%~1"
if defined INSTALL_ROOT goto run_installer
set "INSTALL_ROOT=%LOCALAPPDATA%\Nexus-AI-PC"
echo.
echo 默认安装目录：%INSTALL_ROOT%
set /p "USER_ROOT=请输入安装目录，直接回车使用默认目录："
if defined USER_ROOT set "INSTALL_ROOT=%USER_ROOT%"

:run_installer
echo.
echo 将安装到：%INSTALL_ROOT%
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1" -InstallRoot "%INSTALL_ROOT%"
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
