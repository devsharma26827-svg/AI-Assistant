@echo off
cd /d "%~dp0"

REM --- Check venv exists ---
if not exist ".\venv311\Scripts\python.exe" (
    echo.
    echo [ERROR] venv311 not found at: %cd%\venv311
    echo This means the virtual environment was never created, or was created
    echo with a different name/location.
    echo.
    echo Fix: run these two commands in this folder, then try again:
    echo     python -m venv venv311
    echo     .\venv311\Scripts\pip install -r requirement.txt
    echo.
    pause
    exit /b 1
)

REM --- Check .env.local exists ---
if not exist ".env.local" (
    echo.
    echo [WARNING] .env.local not found. GEMINI_API_KEYS / LIVEKIT credentials
    echo will be missing and the assistant will fail to connect.
    echo Create a .env.local file in this folder with your API keys first.
    echo.
    pause
)

echo Starting Cynthia female voice assistant...
echo Speak into your microphone. Press Ctrl+T to switch between voice and text mode.
".\venv311\Scripts\python.exe" agent.py console

REM --- Keep window open so any crash/error is visible ---
echo.
echo [Cynthia exited with code %errorlevel%]
pause
