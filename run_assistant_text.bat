@echo off
cd /d "%~dp0"
echo Starting Cynthia female assistant in text debug mode...
".\venv311\Scripts\python.exe" agent.py console --text
