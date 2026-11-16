@echo off
rem Launches Heddle. Double-click this file, or drag a board .json onto it to open that board.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo First run: setting up Heddle's Python environment. This takes a minute...
    rem Prefer Python 3.13 (what the app is tested with); fall back to any Python 3.
    py -3.13 -m venv .venv 2>nul || py -3 -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet || goto :fail
)

rem pythonw = no console window; "start" lets this window close immediately.
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" %*
exit /b 0

:fail
echo.
echo Setup failed. Make sure Python 3 is installed (https://www.python.org/downloads/).
pause
exit /b 1
