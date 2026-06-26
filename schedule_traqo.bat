@echo off
:: schedule_traqo.bat
:: Registers two Windows Task Scheduler tasks for Traqo:
::   1. traqo_monitor  — runs daily at 08:00 AM (before market open)
::   2. traqo_scan     — runs daily at 16:30 PM (after NSE close at 15:30)
::
:: Run this ONCE as Administrator.  To remove, run unschedule_traqo.bat.

setlocal
set PROJECT_DIR=%~dp0
set VENV_PYTHON=%PROJECT_DIR%.venv\Scripts\python.exe
set TRADER_SCRIPT=%PROJECT_DIR%paper_trader.py

echo.
echo =========================================================
echo  Traqo Task Scheduler Setup
echo =========================================================
echo  Project dir : %PROJECT_DIR%
echo  Python      : %VENV_PYTHON%
echo =========================================================
echo.

:: ── Task 1: Daily monitor at 08:00 ──────────────────────────────────────────
schtasks /create /tn "traqo_monitor" /tr "\"%VENV_PYTHON%\" \"%TRADER_SCRIPT%\" monitor" /sc daily /st 08:00 /f /rl highest
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create traqo_monitor task.
) else (
    echo [OK] traqo_monitor registered — runs daily at 08:00
)

:: ── Task 2: Daily scan at 16:30 ─────────────────────────────────────────────
schtasks /create /tn "traqo_scan" /tr "\"%VENV_PYTHON%\" \"%TRADER_SCRIPT%\" scan" /sc daily /st 16:30 /f /rl highest
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create traqo_scan task.
) else (
    echo [OK] traqo_scan registered — runs daily at 16:30
)

echo.
echo Done. Verify with:  schtasks /query /tn traqo_monitor
echo                     schtasks /query /tn traqo_scan
echo.
endlocal
