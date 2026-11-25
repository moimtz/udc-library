@echo off
cd /d "%~dp0"

rem ---- Settings you may want to change ---------------------------------
rem Address to listen on:
rem   tailscale  = this PC's Tailscale address (100.x.y.z), detected at start-up. Recommended.
rem   127.0.0.1  = this PC only (use with "tailscale serve" for HTTPS).
rem   100.x.y.z  = a fixed address.
set BUDC_HOST=tailscale
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
