@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" tcp_server.py
pause
