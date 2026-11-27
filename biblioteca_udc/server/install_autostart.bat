@echo off
rem Start the server and the classifier with Windows (see install_autostart.ps1). Right click > Run as
rem administrator.  install_autostart.bat /remove  deletes the tasks.
cd /d "%~dp0"
if /i "%~1"=="/remove" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart.ps1" -Remove
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart.ps1"
)
pause
