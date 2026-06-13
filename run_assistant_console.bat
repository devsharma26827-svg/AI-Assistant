@echo off
cd /d "%~dp0"
echo Starting Cynthia female voice assistant...
echo Speak into your microphone. Press Ctrl+T to switch between voice and text mode.
".\venv311\Scripts\python.exe" agent.py console
