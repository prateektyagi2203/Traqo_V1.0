# Traqo Dashboard Startup — Ensures dependencies & loads correctly

Write-Host "`n✓ Traqo Paper Trading Dashboard — Safe Startup`n" -ForegroundColor Green

# Check if .venv exists
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    Write-Host "ERROR: Virtual environment not found (.venv\Scripts\Activate.ps1)" -ForegroundColor Red
    Write-Host "Please run: python -m venv .venv" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

# Activate virtual environment
Write-Host "Activating virtual environment..." -ForegroundColor Cyan
& ".\.venv\Scripts\Activate.ps1"

# Ensure requirements installed (silent, fast)
Write-Host "Checking dependencies..." -ForegroundColor Cyan
python -m pip install -q -r requirements.txt 2>$null

# Check if yfinance specifically is available
try {
    $output = python -c "import yfinance; print('ok')" 2>$null
    if ($output -eq "ok") {
        Write-Host "✓ yfinance ready" -ForegroundColor Green
    }
} catch {
    Write-Host "⚠ yfinance not yet available, installing..." -ForegroundColor Yellow
    python -m pip install -q yfinance
}

# Start dashboard
Write-Host "`n✓ Starting Paper Trading Dashboard..." -ForegroundColor Green
Write-Host "✓ Open browser: http://localhost:8521`n" -ForegroundColor Green

python paper_trading_dashboard.py

Read-Host "Press Enter to exit"
