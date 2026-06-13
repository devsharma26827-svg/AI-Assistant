@echo off
echo Starting Jarvis Ecosystem...
start "Jarvis Brain Server" cmd /k ".\venv311\Scripts\python.exe device_server.py"
timeout /t 2 /nobreak
start "Jarvis PC Client" cmd /k ".\venv311\Scripts\python.exe pc_client.py"
echo Done.