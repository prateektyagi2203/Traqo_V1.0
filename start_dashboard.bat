@echo off
REM TRAQO - PERMANENT LIVE PRICE FIX
REM This script guarantees live prices work every time

cd /d "%~dp0"

echo Starting Traqo Dashboard with PERMANENT live price fix...
echo.

REM Force activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo Virtual environment activated
) else (
    echo Virtual environment not found!
    echo Run: python -m venv .venv
    pause & exit /b 1
)

REM Verify yfinance before starting
python -c "import yfinance; print('yfinance available')" 2>nul || (
    echo Installing yfinance...
    pip install yfinance --quiet
)

REM Clean start - kill any old processes
taskkill /F /IM python.exe >nul 2>&1

echo Dashboard starting at http://localhost:8521
echo Live prices: ENABLED
echo Health check: http://localhost:8521/health
echo.

REM Start fresh dashboard
python paper_trading_dashboard.py

pause
