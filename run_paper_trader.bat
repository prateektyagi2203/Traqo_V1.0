@echo off
REM Paper Trader — Daily Scheduled Run (4 PM weekdays)
REM Activates venv, runs paper_trader.py, logs output
REM Works from any install location — uses the batch file's own directory.

cd /d "%~dp0"
call .venv\Scripts\activate.bat

echo [%date% %time%] Paper Trader starting... >> paper_trades\scheduler.log
python paper_trader.py run >> paper_trades\scheduler.log 2>&1
echo [%date% %time%] Paper Trader finished (exit code: %ERRORLEVEL%) >> paper_trades\scheduler.log
echo. >> paper_trades\scheduler.log
