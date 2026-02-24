@echo off
REM Traqo — Monitor open paper trades (SL / Target / Expiry check)
REM Scheduled: 10:00 AM daily via Task Scheduler
REM Works from any install location — uses the batch file's own directory.

cd /d "%~dp0"
call .venv\Scripts\activate.bat
python paper_trader.py monitor
python paper_trader.py feedback
