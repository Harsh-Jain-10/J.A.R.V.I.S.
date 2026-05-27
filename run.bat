@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Starting J.A.R.V.I.S...
python main.py
pause
