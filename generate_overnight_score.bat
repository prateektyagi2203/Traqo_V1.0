@echo off
REM Traqo — Pre-open Global Bearish Score Snapshot
REM Schedule this at ~08:45 AM IST on trading days.
REM Writes overnight_bearish_score.json used by paper_trader startup.

cd /d "%~dp0"
call .venv\Scripts\activate.bat
python global_sentiment.py >> paper_trades\scheduler.log 2>&1
