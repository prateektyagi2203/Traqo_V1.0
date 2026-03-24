@echo off
REM ============================================================
REM Traqo Dashboard Startup — Ensures dependencies & loads correctly
REM ============================================================

echo.
echo Traqo Paper Trading Dashboard — Safe Startup
echo =============================================
echo.

REM Check if .venv exists
if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found (.venv\Scripts\activate.bat)
    echo Please run: python -m venv .venv
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Ensure requirements installed (silent, fast)
echo Checking dependencies...
pip install -q -r requirements.txt

REM Check if yfinance specifically is available
python -c "import yfinance; print('✓ yfinance ready')" >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: yfinance not yet available, will retry at runtime...
    pip install -q yfinance
)

REM Start dashboard
echo.
echo ✓ Starting Paper Trading Dashboard...
echo ✓ Open browser: http://localhost:8521
echo.

python paper_trading_dashboard.py
pause
