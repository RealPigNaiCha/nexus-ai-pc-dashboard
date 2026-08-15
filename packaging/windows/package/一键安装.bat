@echo off
chcp 65001 >nul
setlocal
call "%~dp0one-click-install.bat" %*
exit /b %errorlevel%
