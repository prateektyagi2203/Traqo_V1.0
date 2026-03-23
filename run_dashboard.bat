@echo off
REM One-click dashboard starter
echo Killing any stale Python processes...
taskkill /F /IM python.exe 2>nul
timeout /t 1 /nobreak >nul
call .venv\Scripts\activate.bat
pip install -q yfinance
python paper_trading_dashboard.py
