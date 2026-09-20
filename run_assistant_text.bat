@echo off
cd /d "%~dp0"

if not exist ".\venv311\Scripts\python.exe" (
    echo.
    echo [ERROR] venv311 not found at: %cd%\venv311
    echo Fix: run these two commands in this folder, then try again:
    echo     python -m venv venv311
    echo     .\venv311\Scripts\pip install -r requirement.txt
    echo.
    pause
    exit /b 1
)

if not exist ".env.local" (
    echo.
    echo [WARNING] .env.local not found. Create it with your API keys first.
    echo.
    pause
)

echo Starting Cynthia female assistant in text debug mode...
".\venv311\Scripts\python.exe" agent.py console --text

echo.
echo [Cynthia exited with code %errorlevel%]
pause
