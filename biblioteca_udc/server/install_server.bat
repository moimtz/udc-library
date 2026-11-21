@echo off
cd /d "%~dp0"
echo Creating virtual environment...
python -m venv .venv || goto :error
.venv\Scripts\python.exe -m pip install --upgrade pip || goto :error
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto :error
echo.
echo Now create the administrator account:
.venv\Scripts\python.exe create_admin.py
echo.
echo Done. Start the server with run_server.bat
pause
exit /b 0
:error
echo Something failed. Read the message above.
pause
exit /b 1
