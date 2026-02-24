"""
Expanded Data Collection for Candlestick RAG System
====================================================
- 10-year daily data (vs 3yr previously)
- 60-day 15-minute intraday data
- 30+ instruments across 5 tiers
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
import time

# ============================================================
# Configuration
# ============================================================
INSTRUMENTS = {
    # ── Tier 1: Core Indian Indices ──
    "^NSEI":        "nifty50",
    "^NSEBANK":     "banknifty",
    "^INDIAVIX":    "indiavix",
    "^CNXIT":       "niftyit",           # Fixed: was NIFTYIT.NS (delisted)
    "^CNXPHARMA":   "niftypharma",       # NEW: Nifty Pharma
    "^CNXFMCG":     "niftyfmcg",         # NEW: Nifty FMCG
    "^CNXAUTO":     "niftyauto",         # NEW: Nifty Auto
    "^CNXMETAL":    "niftymetal",        # NEW: Nifty Metal
    "^CNXREALTY":   "niftyrealty",       # NEW: Nifty Realty
    "^CNXPSUBANK":  "niftypsubank",     # NEW: Nifty PSU Bank
    "^CNXENERGY":   "niftyenergy",       # NEW: Nifty Energy
    "^CNXMEDIA":    "niftymedia",        # NEW: Nifty Media
    "^CNXINFRA":    "niftyinfra",        # NEW: Nifty Infra
    
    # ── Tier 2: Global Indices ──
    "^GSPC":        "sp500",
    "^IXIC":        "nasdaq",
    "^DJI":         "dowjones",          # NEW: Dow Jones
    "^FTSE":        "ftse100",           # NEW: FTSE 100
    "^N225":        "nikkei225",         # NEW: Nikkei 225
    "^HSI":         "hangseng",          # NEW: Hang Seng
    "^STOXX50E":    "eurostoxx50",       # NEW: Euro Stoxx 50
    
    # ── Tier 3: Macro / Commodities / FX ──
    "DX-Y.NYB":     "dxy",
    "CL=F":         "crude_oil",
    "^TNX":         "us10y_yield",
    "GC=F":         "gold",
    "SI=F":         "silver",            # NEW: Silver
    "USDINR=X":     "usdinr",           # NEW: USD/INR
    "EURUSD=X":     "eurusd",           # NEW: EUR/USD
    "^VIX":         "vix",              # NEW: CBOE VIX (global fear gauge)
    
    # ── Tier 4: Nifty Heavyweights (Top 10 by weight) ──
    "RELIANCE.NS":  "reliance",
    "HDFCBANK.NS":  "hdfcbank",
    "INFY.NS":      "infosys",
    "TCS.NS":       "tcs",
    "ICICIBANK.NS": "icicibank",         # NEW
    "HINDUNILVR.NS":"hindunilvr",        # NEW
    "ITC.NS":       "itc",              # NEW
    "SBIN.NS":      "sbi",             # NEW
    "BHARTIARTL.NS":"bhartiartl",       # NEW
    "LT.NS":        "lt",              # NEW: Larsen & Toubro
    "KOTAKBANK.NS": "kotakbank",        # NEW
    "AXISBANK.NS":  "axisbank",         # NEW
    "BAJFINANCE.NS":"bajfinance",       # NEW
    "MARUTI.NS":    "maruti",           # NEW
    "TATAMOTORS.NS":"tatamotors",       # NEW
    "SUNPHARMA.NS": "sunpharma",        # NEW
    "WIPRO.NS":     "wipro",            # NEW
    "HCLTECH.NS":   "hcltech",         # NEW
    "TITAN.NS":     "titan",            # NEW
    "ADANIENT.NS":  "adanient",         # NEW
}

end_date = datetime.today()
daily_start = end_date - timedelta(days=10 * 365)   # 10 YEARS
intraday_start = end_date - timedelta(days=59)       # 60 days (Yahoo limit)

# Create output directories (separate from existing to not overwrite)
os.makedirs("daily_10yr", exist_ok=True)
os.makedirs("intraday_15min_v2", exist_ok=True)

summary = []
failed = []

total = len(INSTRUMENTS)
print(f"{'=' * 70}")
print(f"  EXPANDED DATA COLLECTION: {total} instruments")
print(f"  Daily: 10-year ({daily_start.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')})")
print(f"  Intraday: 60-day 15-min ({intraday_start.strftime('%Y-%m-%d')} → {end_date.strftime('%Y-%m-%d')})")
print(f"{'=' * 70}")

# ============================================================
# Fetch data for each instrument
# ============================================================
for i, (ticker, name) in enumerate(INSTRUMENTS.items(), 1):
    print(f"\n[{i}/{total}] {name.upper()} ({ticker})")

    daily_rows = 0
    intra_rows = 0
    daily_path = None
    intra_path = None

    # --- Daily (10 years) ---
    print(f"  Daily 10yr...", end=" ", flush=True)
    try:
        daily_df = yf.download(
            ticker,
            start=daily_start.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval="1d",
            progress=False,
            timeout=30
        )
        if not daily_df.empty:
            daily_path = f"daily_10yr/{name}_daily_10yr.csv"
            daily_df.to_csv(daily_path)
            daily_rows = daily_df.shape[0]
            print(f"✓ {daily_rows} rows")
        else:
            print("EMPTY")
    except Exception as e:
        print(f"FAILED: {e}")

    time.sleep(0.3)

    # --- 15-minute (60 days) ---
    print(f"  15-min 60d...", end=" ", flush=True)
    try:
        intra_df = yf.download(
            ticker,
            start=intraday_start.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            interval="15m",
            progress=False,
            timeout=30
        )
        if not intra_df.empty:
            intra_path = f"intraday_15min_v2/{name}_15min_60d.csv"
            intra_df.to_csv(intra_path)
            intra_rows = intra_df.shape[0]
            print(f"✓ {intra_rows} rows")
        else:
            print("EMPTY")
    except Exception as e:
        print(f"FAILED: {e}")

    if daily_rows == 0 and intra_rows == 0:
        failed.append(f"{name} ({ticker})")

    summary.append({
        "name": name,
        "ticker": ticker,
        "daily_rows": daily_rows,
        "daily_file": daily_path or "-",
        "intra_rows": intra_rows,
        "intra_file": intra_path or "-",
    })

    time.sleep(0.7)  # rate-limit between instruments

# ============================================================
# Summary
# ============================================================
print(f"\n\n{'=' * 80}")
print("EXPANDED DOWNLOAD SUMMARY")
print(f"{'=' * 80}")
print(f"{'Name':<15} {'Ticker':<18} {'Daily(10yr)':>11} {'15min(60d)':>11}  Status")
print("-" * 80)
total_daily = 0
total_intra = 0
ok_count = 0
for s in summary:
    status = "✓" if s["daily_rows"] > 0 or s["intra_rows"] > 0 else "✗ FAILED"
    if s["daily_rows"] > 0 or s["intra_rows"] > 0:
        ok_count += 1
    print(f"{s['name']:<15} {s['ticker']:<18} {s['daily_rows']:>11,} {s['intra_rows']:>11,}  {status}")
    total_daily += s["daily_rows"]
    total_intra += s["intra_rows"]

print("-" * 80)
print(f"{'TOTAL':<15} {'':<18} {total_daily:>11,} {total_intra:>11,}")
print(f"\nInstruments: {ok_count}/{total} successful")
print(f"Total candles: {total_daily + total_intra:,}")
print(f"\nFiles saved to: daily_10yr/ and intraday_15min_v2/")

if failed:
    print(f"\nFailed instruments: {', '.join(failed)}")

print(f"\nNext steps:")
print(f"  1. Run feature_engineering.py on the new data folders")
print(f"  2. Re-ingest expanded RAG documents into ChromaDB")
