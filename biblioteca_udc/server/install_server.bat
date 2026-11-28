@echo off
rem Fresh install: virtual environment, dependencies, administrator account and UDC tree.
cd /d "%~dp0"
python --version || goto :nopython
echo Creating virtual environment...
python -m venv .venv || goto :error
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
echo.
echo Now create the administrator account:
.venv\Scripts\python.exe create_admin.py || goto :error
echo.
echo Importing the UDC tree (about a minute)...
.venv\Scripts\python.exe udc_import.py || goto :error
echo.
echo Done. Start the server with run_server.bat
pause
exit /b 0
:nopython
echo Python was not found. Install Python 3.11 or later from python.org (tick "Add python.exe to PATH").
pause
exit /b 1
:error
echo Something failed. Read the message above.
pause
exit /b 1
