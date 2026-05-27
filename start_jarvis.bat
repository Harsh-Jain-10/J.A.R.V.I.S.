@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
rem The following line has been commented out to disable auto-startup:
rem start /min python main.py
