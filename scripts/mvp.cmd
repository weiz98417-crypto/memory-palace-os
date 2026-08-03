@echo off
setlocal
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0mvp.ps1" %*
exit /b %ERRORLEVEL%
