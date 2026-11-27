@echo off
cd /d "%~dp0"

rem Classifier service for the library server (same PC, 127.0.0.1:8766). The library works without it;
rem the app's "Analyze" button is only enabled while this is running.
rem Loading the model takes about a minute; then each PDF takes ~30 s (more with OCR).
rem "run_classifier.bat --log" (the start-up task, no window): output to logs\classifier.log
rem (logs\classifier.log.old keeps the previous 10 MB).

set PYTHONUTF8=1
set PYTHONUNBUFFERED=1
set "LOG="
if /i "%~1"=="--log" (
    if not exist logs mkdir logs
    set "LOG=%~dp0logs\classifier.log"
)

:loop
if defined LOG (
    if exist "%LOG%" for %%F in ("%LOG%") do if %%~zF GTR 10000000 move /y "%LOG%" "%LOG%.old" >nul
    echo ==== %DATE% %TIME% starting >> "%LOG%"
    .venv\Scripts\python.exe -m udcpoc serve >> "%LOG%" 2>&1
    echo ==== %DATE% %TIME% classifier stopped, restarting in 10 seconds >> "%LOG%"
) else (
    .venv\Scripts\python.exe -m udcpoc serve
    echo Classifier stopped. Restarting in 10 seconds ^(close this window to quit^)...
)
rem ping instead of timeout: timeout fails without a console (start-up task)
ping -n 11 127.0.0.1 >nul
goto loop
