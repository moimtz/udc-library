@echo off
cd /d "%~dp0"

rem ---- Settings you may want to change ---------------------------------
rem Address to listen on. 127.0.0.1 = this PC only (use with "tailscale serve").
rem To use the Tailscale address directly, put this PC's 100.x.y.z here.
set BUDC_HOST=127.0.0.1
set BUDC_PORT=8765
rem Storage limit for PDFs (+ trash), in gigabytes. Change it whenever you need.
set BUDC_MAX_STORAGE_GB=20
set BUDC_TRASH_DAYS=30
rem set BUDC_DATA_DIR=D:\biblioteca_data
rem set BUDC_CONTACT_EMAIL=you@example.com
rem ----------------------------------------------------------------------

:loop
.venv\Scripts\python.exe main.py
echo Server stopped. Restarting in 10 seconds (close this window to quit)...
timeout /t 10 /nobreak >nul
goto loop
