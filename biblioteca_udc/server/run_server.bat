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

rem "run_server.bat --log" (the start-up task, no window): output to logs\server.log (logs\server.log.old
rem keeps the previous 10 MB).
set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
set "LOG="
if /i "%~1"=="--log" (
    if not exist logs mkdir logs
    set "LOG=%~dp0logs\server.log"
)

:loop
if defined LOG (
    if exist "%LOG%" for %%F in ("%LOG%") do if %%~zF GTR 10000000 move /y "%LOG%" "%LOG%.old" >nul
    echo ==== %DATE% %TIME% starting >> "%LOG%"
    .venv\Scripts\python.exe main.py >> "%LOG%" 2>&1
    echo ==== %DATE% %TIME% server stopped, restarting in 10 seconds >> "%LOG%"
) else (
    .venv\Scripts\python.exe main.py
    echo Server stopped. Restarting in 10 seconds ^(close this window to quit^)...
)
rem ping instead of timeout: timeout fails without a console (start-up task)
ping -n 11 127.0.0.1 >nul
goto loop
