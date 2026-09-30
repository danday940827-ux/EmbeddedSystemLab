@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" live_plot.py
if errorlevel 1 pause
