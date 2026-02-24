"""
Paper Trader Engine — Fully Automated Backtesting-on-Live-Data
================================================================
Runs autonomously without human intervention:
  1. On startup: catches up on any missed trading days
  2. Scans ALL RAG-backed stocks across ALL 5 horizons (1d, 3d, 5d, 10d, 25d)
  3. Auto-enters every qualifying signal into paper portfolio
  4. Monitors open positions — closes on SL hit / target hit / expiry
  5. Feeds outcomes back to RAG learning engine
  6. Generates daily performance reports

Resilience:
  - Idempotent: re-running the same day won't create duplicate trades
  - Catch-up: detects missed days and backfills automatically
  - Crash-safe: SQLite DB with transactions
  - No scheduler needed: runs on startup, handles gaps

Usage:
    from paper_trader import PaperTrader
    engine = PaperTrader()
    engine.run()           # Full run: catch-up + scan + monitor + report
    engine.scan_today()    # Only scan for new signals
    engine.monitor()       # Only check open positions
"""

import os
import json
import sqlite3
import logging
import time as _time
from datetime import datetime, timedelta, date
from typing import List, Dict, Optional
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf
import warnings

warnings.filterwarnings("ignore")

from pattern_detector import detect_live_patterns
from statistical_predictor import StatisticalPredictor
from trading_config import (
    WHITELISTED_PATTERNS, EXCLUDED_PATTERNS,
    STRUCTURAL_SL_PATTERNS, STRUCTURAL_SL_MULTIPLIER, STANDARD_SL_MULTIPLIER,
    SL_FLOOR_PCT, SL_CAP_PCT,
    INSTRUMENT_SECTORS,
    is_tradeable_pattern,
)

# ============================================================
# CONFIGURATION
# ============================================================
DB_PATH = "paper_trades/paper_trades.db"
LOG_DIR = "paper_trades/logs"
os.makedirs("paper_trades", exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/paper_trader.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("paper_trader")

# Signal quality filters
MIN_WIN_RATE = 55.0
MIN_CONFIDENCE = "MEDIUM"
MIN_RR_RATIO = 1.5
MIN_MATCHES = 5

# Horizon configuration
HORIZON_CONFIG = {
    1:  {"sl_mult_scale": 0.7,  "sl_cap": 2.5, "rr_min": 1.5, "label": "BTST_1d"},
    3:  {"sl_mult_scale": 0.8,  "sl_cap": 3.5, "rr_min": 1.8, "label": "Swing_3d"},
    5:  {"sl_mult_scale": 1.0,  "sl_cap": 5.0, "rr_min": 2.0, "label": "Swing_5d"},
    10: {"sl_mult_scale": 1.2,  "sl_cap": 5.0, "rr_min": 2.0, "label": "Swing_10d"},
    25: {"sl_mult_scale": 1.5,  "sl_cap": 6.0, "rr_min": 2.0, "label": "Swing_25d"},
}

# All stocks to scan
SCAN_TICKERS = list(dict.fromkeys([
    # --- Nifty 50 ---
    "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
    "BHARTIARTL.NS", "SBIN.NS", "LT.NS", "BAJFINANCE.NS", "AXISBANK.NS",
    "KOTAKBANK.NS", "ITC.NS", "HINDUNILVR.NS", "MARUTI.NS", "TATAMOTORS.NS",
    "HCLTECH.NS", "SUNPHARMA.NS", "TITAN.NS", "ADANIENT.NS", "WIPRO.NS",
    "TATASTEEL.NS", "M&M.NS", "NTPC.NS", "POWERGRID.NS", "ULTRACEMCO.NS",
    "ASIANPAINT.NS", "BAJAJFINSV.NS", "COALINDIA.NS", "NESTLEIND.NS", "JSWSTEEL.NS",
    "GRASIM.NS", "ONGC.NS", "DIVISLAB.NS", "DRREDDY.NS", "CIPLA.NS",
    "APOLLOHOSP.NS", "HEROMOTOCO.NS", "EICHERMOT.NS", "BPCL.NS", "TECHM.NS",
    "TATACONSUM.NS", "BRITANNIA.NS", "HINDALCO.NS", "INDUSINDBK.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "ADANIPORTS.NS", "SHRIRAMFIN.NS",
    "ETERNAL.NS", "TRENT.NS",
    # --- Nifty Next 50 ---
    "ABB.NS", "ACC.NS", "ADANIGREEN.NS", "ADANIPOWER.NS", "AMBUJACEM.NS",
    "ATGL.NS", "AUROPHARMA.NS", "BAJAJHLDNG.NS", "BANKBARODA.NS", "BEL.NS",
    "BERGEPAINT.NS", "BIOCON.NS", "BOSCHLTD.NS", "CANBK.NS", "CHOLAFIN.NS",
    "COLPAL.NS", "DABUR.NS", "DLF.NS", "GAIL.NS", "GODREJCP.NS",
    "HAL.NS", "HAVELLS.NS", "ICICIPRULI.NS", "INDIGO.NS", "IOC.NS",
    "IRCTC.NS", "IRFC.NS", "JINDALSTEL.NS", "JIOFIN.NS", "LICI.NS",
    "LTIM.NS", "LTTS.NS", "LUPIN.NS", "MAXHEALTH.NS", "MOTHERSON.NS",
    "NAUKRI.NS", "NHPC.NS", "OBEROIRLTY.NS", "OFSS.NS", "PAYTM.NS",
    "PFC.NS", "PIDILITIND.NS", "PNB.NS", "POLYCAB.NS", "RECLTD.NS",
    "SBICARD.NS", "SIEMENS.NS", "SRF.NS", "TATAPOWER.NS",
    # --- Nifty Midcap 150 ---
    "AARTIIND.NS", "ABCAPITAL.NS", "ABFRL.NS", "ALKEM.NS", "ANGELONE.NS",
    "APLAPOLLO.NS", "APLLTD.NS", "ASHOKLEY.NS", "ASTRAL.NS", "ATUL.NS",
    "AUBANK.NS", "BALKRISIND.NS", "BANKINDIA.NS", "BATAINDIA.NS", "BHARATFORG.NS",
    "BHEL.NS", "BSE.NS", "CANFINHOME.NS", "CARBORUNIV.NS", "CASTROLIND.NS",
    "CDSL.NS", "CESC.NS", "CGPOWER.NS", "CHAMBLFERT.NS", "CLEAN.NS",
    "COCHINSHIP.NS", "COFORGE.NS", "COROMANDEL.NS", "CROMPTON.NS", "CUB.NS",
    "CUMMINSIND.NS", "CYIENT.NS", "DALBHARAT.NS", "DEEPAKNTR.NS", "DELHIVERY.NS",
    "DEVYANI.NS", "DIXON.NS", "EMAMILTD.NS", "ENDURANCE.NS", "ESCORTS.NS",
    "EXIDEIND.NS", "FACT.NS", "FEDERALBNK.NS", "FINEORG.NS", "FLUOROCHEM.NS",
    "FORTIS.NS", "GILLETTE.NS", "GLENMARK.NS", "GLAXO.NS", "GMRAIRPORT.NS",
    "GNFC.NS", "GODREJIND.NS", "GODREJPROP.NS", "GRANULES.NS", "GRAPHITE.NS",
    "GRINDWELL.NS", "GUJGASLTD.NS", "HATSUN.NS", "HINDPETRO.NS", "HONAUT.NS",
    "IDFCFIRSTB.NS", "IEX.NS", "IIFL.NS", "INDIANB.NS", "INDHOTEL.NS",
    "INDIAMART.NS", "INDUSTOWER.NS", "INTELLECT.NS", "IPCALAB.NS", "JKCEMENT.NS", "JSWENERGY.NS",
    "JUBLFOOD.NS", "KALYANKJIL.NS", "KEI.NS", "KIMS.NS", "KPITTECH.NS",
    "LALPATHLAB.NS", "LAURUSLABS.NS", "LICHSGFIN.NS", "MANAPPURAM.NS", "MANKIND.NS",
    "MARICO.NS", "MAZDOCK.NS", "METROBRAND.NS", "MFSL.NS", "MGL.NS",
    "MPHASIS.NS", "MRF.NS", "MUTHOOTFIN.NS", "NATCOPHARM.NS", "NAVINFLUOR.NS",
    "NMDC.NS", "OIL.NS", "PAGEIND.NS", "PATANJALI.NS", "PERSISTENT.NS",
    "PETRONET.NS", "PHOENIXLTD.NS", "PIIND.NS", "POLYMED.NS", "PRESTIGE.NS",
    "PVRINOX.NS", "RADICO.NS", "RAIN.NS", "RAJESHEXPO.NS", "RAMCOCEM.NS",
    "RATNAMANI.NS", "RBLBANK.NS", "SAIL.NS", "SCHAEFFLER.NS", "SHREECEM.NS",
    "SONACOMS.NS", "STARHEALTH.NS", "SUMICHEM.NS", "SUNDARMFIN.NS", "SUNDRMFAST.NS",
    "SUNTV.NS", "SUPREMEIND.NS", "SYNGENE.NS", "TATACHEM.NS", "TATACOMM.NS",
    "TATAELXSI.NS", "TATATECH.NS", "TIINDIA.NS", "TIMKEN.NS", "TORNTPHARM.NS",
    "TORNTPOWER.NS", "TRIDENT.NS", "TVSMOTOR.NS", "UBL.NS", "UNIONBANK.NS",
    "UNITDSPR.NS", "UPL.NS", "VBL.NS", "VEDL.NS", "VOLTAS.NS",
    "WHIRLPOOL.NS", "YESBANK.NS", "ZEEL.NS", "ZYDUSLIFE.NS", "PGHH.NS",
    "3MINDIA.NS", "AIAENG.NS", "AJANTPHARM.NS", "NAM-INDIA.NS", "JSWINFRA.NS",
    "POONAWALLA.NS", "SUNTECK.NS",
]))

# Only non-trivial aliases (where Yahoo base name != internal name)
_YAHOO_ALIAS = {
    "infy": "infosys", "m&m": "mahindra", "bajaj-auto": "bajajauto",
    "one97": "paytm", "paytm": "paytm", "indhotel": "indianhotels",
    "nam-india": "namindia", "eternal": "eternal",
}


def _yahoo_to_internal(ticker: str) -> str:
    base = ticker.replace(".NS", "").replace(".BO", "").lower()
    return _YAHOO_ALIAS.get(base, base)


# ============================================================
# NSE CALENDAR
# ============================================================
_NSE_HOLIDAYS_2026 = {
    date(2026, 1, 26), date(2026, 3, 10), date(2026, 3, 30),
    date(2026, 4, 2), date(2026, 4, 3), date(2026, 4, 14),
    date(2026, 5, 1), date(2026, 5, 25), date(2026, 6, 5),
    date(2026, 7, 6), date(2026, 8, 15), date(2026, 8, 16),
    date(2026, 10, 2), date(2026, 10, 20), date(2026, 11, 9),
    date(2026, 11, 10), date(2026, 11, 30), date(2026, 12, 25),
}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _NSE_HOLIDAYS_2026


def get_trading_days_between(start: date, end: date) -> List[date]:
    days = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current)
        current += timedelta(days=1)
    return days


def add_trading_days(start: date, n: int) -> date:
    current = start
    added = 0
    while added < n:
        current += timedelta(days=1)
        if is_trading_day(current):
            added += 1
    return current


# ============================================================
# DATABASE LAYER
# ============================================================
class PaperTradeDB:
    """SQLite database for paper trades."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                instrument TEXT,
                sector TEXT,
                direction TEXT NOT NULL,
                horizon_days INTEGER NOT NULL,
                horizon_label TEXT,
                patterns TEXT,
                entry_price REAL NOT NULL,
                target_price REAL NOT NULL,
                sl_price REAL NOT NULL,
                target_pct REAL,
                sl_pct REAL,
                rr_ratio REAL,
                predicted_win_rate REAL,
                predicted_pf REAL,
                confidence TEXT,
                n_matches INTEGER,
                match_tier TEXT,
                entry_date TEXT NOT NULL,
                expiry_date TEXT NOT NULL,
                status TEXT DEFAULT 'OPEN',
                exit_price REAL,
                exit_date TEXT,
                exit_reason TEXT,
                actual_return_pct REAL,
                indicators_json TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(ticker, horizon_days, entry_date)
            );

            CREATE TABLE IF NOT EXISTS scan_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_date TEXT NOT NULL UNIQUE,
                tickers_scanned INTEGER,
                signals_found INTEGER,
                trades_entered INTEGER,
                errors INTEGER,
                duration_seconds REAL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS daily_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL UNIQUE,
                trades_opened INTEGER DEFAULT 0,
                trades_closed INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                expired_wins INTEGER DEFAULT 0,
                expired_losses INTEGER DEFAULT 0,
                total_return_pct REAL DEFAULT 0,
                avg_win_pct REAL DEFAULT 0,
                avg_loss_pct REAL DEFAULT 0,
                win_rate REAL DEFAULT 0,
                best_trade TEXT,
                worst_trade TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
            CREATE INDEX IF NOT EXISTS idx_trades_entry_date ON trades(entry_date);
            CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
        """)
        self.conn.commit()

    # ---- INSERT / UPDATE ----

    def insert_trade(self, trade: dict) -> Optional[int]:
        """Insert trade. Returns row ID or None if duplicate."""
        try:
            cur = self.conn.cursor()
            cur.execute("""
                INSERT INTO trades (
                    ticker, instrument, sector, direction, horizon_days, horizon_label,
                    patterns, entry_price, target_price, sl_price,
                    target_pct, sl_pct, rr_ratio,
                    predicted_win_rate, predicted_pf, confidence, n_matches, match_tier,
                    entry_date, expiry_date, status, indicators_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'OPEN',?)
            """, (
                trade["ticker"], trade.get("instrument"), trade.get("sector"),
                trade["direction"], trade["horizon_days"], trade.get("horizon_label"),
                trade.get("patterns", ""), trade["entry_price"],
                trade["target_price"], trade["sl_price"],
                trade.get("target_pct"), trade.get("sl_pct"), trade.get("rr_ratio"),
                trade.get("predicted_win_rate"), trade.get("predicted_pf"),
                trade.get("confidence"), trade.get("n_matches"), trade.get("match_tier"),
                trade["entry_date"], trade["expiry_date"],
                json.dumps(trade.get("indicators", {})),
            ))
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def close_trade(self, trade_id: int, exit_price: float, exit_date: str,
                    exit_reason: str, actual_return_pct: float, status: str):
        self.conn.execute("""
            UPDATE trades SET status=?, exit_price=?, exit_date=?,
                exit_reason=?, actual_return_pct=?, updated_at=datetime('now')
            WHERE id=?
        """, (status, exit_price, exit_date, exit_reason, actual_return_pct, trade_id))
        self.conn.commit()

    # ---- QUERIES ----

    def get_open_trades(self) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date")
        return [dict(r) for r in cur.fetchall()]

    def get_trades_by_date(self, entry_date: str) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM trades WHERE entry_date=?", (entry_date,))
        return [dict(r) for r in cur.fetchall()]

    def get_closed_trades(self, since: str = None) -> List[dict]:
        if since:
            cur = self.conn.execute(
                "SELECT * FROM trades WHERE status!='OPEN' AND exit_date>=? ORDER BY exit_date",
                (since,))
        else:
            cur = self.conn.execute(
                "SELECT * FROM trades WHERE status!='OPEN' ORDER BY exit_date")
        return [dict(r) for r in cur.fetchall()]

    def get_all_trades(self) -> List[dict]:
        cur = self.conn.execute("SELECT * FROM trades ORDER BY entry_date DESC, ticker")
        return [dict(r) for r in cur.fetchall()]

    def was_scanned(self, scan_date: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM scan_log WHERE scan_date=?", (scan_date,))
        return cur.fetchone() is not None

    def log_scan(self, scan_date: str, tickers: int, signals: int,
                 entered: int, errors: int, duration: float):
        try:
            self.conn.execute("""
                INSERT INTO scan_log (scan_date, tickers_scanned, signals_found,
                                      trades_entered, errors, duration_seconds)
                VALUES (?,?,?,?,?,?)
            """, (scan_date, tickers, signals, entered, errors, duration))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def save_daily_summary(self, s: dict):
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO daily_summary (
                    report_date, trades_opened, trades_closed,
                    wins, losses, expired_wins, expired_losses,
                    total_return_pct, avg_win_pct, avg_loss_pct,
                    win_rate, best_trade, worst_trade
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                s["report_date"], s.get("trades_opened", 0), s.get("trades_closed", 0),
                s.get("wins", 0), s.get("losses", 0),
                s.get("expired_wins", 0), s.get("expired_losses", 0),
                s.get("total_return_pct", 0), s.get("avg_win_pct", 0),
                s.get("avg_loss_pct", 0), s.get("win_rate", 0),
                s.get("best_trade", ""), s.get("worst_trade", ""),
            ))
            self.conn.commit()
        except Exception as e:
            log.error(f"Failed to save daily summary: {e}")

    def get_daily_summaries(self, limit: int = 90) -> List[dict]:
        cur = self.conn.execute(
            "SELECT * FROM daily_summary ORDER BY report_date DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    # ---- STATISTICS ----

    def get_stats(self) -> dict:
        c = self.conn
        open_n = c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
        closed_n = c.execute("SELECT COUNT(*) FROM trades WHERE status!='OPEN'").fetchone()[0]
        wins = c.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0]
        losses = c.execute("SELECT COUNT(*) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0]
        avg_w = c.execute("SELECT AVG(actual_return_pct) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0] or 0
        avg_l = c.execute("SELECT AVG(actual_return_pct) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0] or 0
        tot_ret = c.execute("SELECT SUM(actual_return_pct) FROM trades WHERE status!='OPEN'").fetchone()[0] or 0
        wr = (wins / closed_n * 100) if closed_n else 0
        pf = (abs(avg_w * wins) / abs(avg_l * losses)) if (losses and avg_l) else 0
        return {
            "open_trades": open_n, "closed_trades": closed_n,
            "total_trades": open_n + closed_n,
            "wins": wins, "losses": losses,
            "win_rate": round(wr, 1),
            "avg_win_pct": round(avg_w, 2), "avg_loss_pct": round(avg_l, 2),
            "profit_factor": round(pf, 2), "total_return_pct": round(tot_ret, 2),
        }

    def get_stats_by_horizon(self) -> List[dict]:
        cur = self.conn.execute("""
            SELECT horizon_days, horizon_label,
                   COUNT(*) as total,
                   SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
                   AVG(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN actual_return_pct END) as avg_win,
                   AVG(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN actual_return_pct END) as avg_loss,
                   SUM(actual_return_pct) as total_ret
            FROM trades WHERE status!='OPEN'
            GROUP BY horizon_days ORDER BY horizon_days
        """)
        results = []
        for row in cur.fetchall():
            r = dict(row)
            t = r["wins"] + r["losses"]
            r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
            results.append(r)
        return results

    def get_stats_by_pattern(self) -> List[dict]:
        cur = self.conn.execute("""
            SELECT patterns,
                   COUNT(*) as total,
                   SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
                   AVG(actual_return_pct) as avg_ret
            FROM trades WHERE status!='OPEN'
            GROUP BY patterns ORDER BY total DESC
        """)
        results = []
        for row in cur.fetchall():
            r = dict(row)
            t = r["wins"] + r["losses"]
            r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
            results.append(r)
        return results

    def get_stats_by_stock(self) -> List[dict]:
        cur = self.conn.execute("""
            SELECT ticker,
                   COUNT(*) as total,
                   SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
                   AVG(actual_return_pct) as avg_ret,
                   SUM(actual_return_pct) as total_ret
            FROM trades WHERE status!='OPEN'
            GROUP BY ticker ORDER BY total DESC
        """)
        results = []
        for row in cur.fetchall():
            r = dict(row)
            t = r["wins"] + r["losses"]
            r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
            results.append(r)
        return results

    def close(self):
        self.conn.close()


# ============================================================
# PAPER TRADER ENGINE
# ============================================================
class PaperTrader:
    """Fully autonomous paper trading engine."""

    def __init__(self, db_path: str = DB_PATH):
        self.db = PaperTradeDB(db_path)
        self.sp = StatisticalPredictor()
        log.info("Paper Trader initialized")

    # ----------------------------------------------------------
    # MAIN ENTRY POINT
    # ----------------------------------------------------------
    def run(self) -> dict:
        """Full autonomous run: catch-up -> scan -> monitor -> report -> feed RAG."""
        log.info("=" * 60)
        log.info("PAPER TRADER RUN STARTED")
        log.info("=" * 60)

        today = date.today()
        summary = {
            "run_date": today.isoformat(),
            "catchup_days": 0,
            "today_scanned": False,
            "signals_found": 0,
            "trades_entered": 0,
            "trades_closed": 0,
            "errors": [],
        }

        # 1. CATCH UP on missed days
        catchup_count = self._catch_up(today)
        summary["catchup_days"] = catchup_count

        # 2. SCAN today
        if is_trading_day(today):
            scan_result = self.scan_date(today)
            summary["today_scanned"] = True
            summary["signals_found"] = scan_result.get("signals_found", 0)
            summary["trades_entered"] = scan_result.get("trades_entered", 0)
        else:
            log.info(f"Today ({today}) is not a trading day — skip scan")

        # 3. MONITOR open positions
        close_result = self.monitor_open_positions(today)
        summary["trades_closed"] = close_result.get("closed", 0)

        # 4. DAILY REPORT
        self._generate_daily_report(today)

        # 5. FEED OUTCOMES TO RAG
        self.feed_outcomes_to_rag()

        log.info(f"RUN COMPLETE: {json.dumps(summary, indent=2)}")
        return summary

    # ----------------------------------------------------------
    # CATCH-UP
    # ----------------------------------------------------------
    def _catch_up(self, today: date) -> int:
        cur = self.db.conn.execute("SELECT MAX(scan_date) FROM scan_log")
        row = cur.fetchone()
        last_scan = row[0] if row and row[0] else None

        if last_scan is None:
            log.info("First run — no catch-up needed")
            return 0

        last_scan_date = date.fromisoformat(last_scan)
        yesterday = today - timedelta(days=1)
        missed_days = get_trading_days_between(last_scan_date + timedelta(days=1), yesterday)

        if not missed_days:
            log.info("No missed trading days")
            return 0

        log.info(f"CATCH-UP: {len(missed_days)} missed days ({missed_days[0]} to {missed_days[-1]})")

        for missed in missed_days:
            log.info(f"  Catching up: {missed}")
            try:
                self.monitor_open_positions(missed)
                self._retrospective_check(missed)
            except Exception as e:
                log.error(f"  Error on {missed}: {e}")

        return len(missed_days)

    def _retrospective_check(self, check_date: date):
        """For a missed day, close expired trades using actual OHLC."""
        open_trades = self.db.get_open_trades()
        for trade in open_trades:
            expiry_dt = date.fromisoformat(trade["expiry_date"])
            entry_dt = date.fromisoformat(trade["entry_date"])
            if check_date < entry_dt or check_date > expiry_dt:
                continue
            try:
                start_str = (check_date - timedelta(days=3)).strftime("%Y-%m-%d")
                end_str = (check_date + timedelta(days=3)).strftime("%Y-%m-%d")
                df = yf.download(trade["ticker"], start=start_str, end=end_str, progress=False)
                if df.empty:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                df.index = pd.to_datetime(df.index).date
                if check_date not in df.index:
                    continue

                row = df.loc[check_date]
                high, low, close = float(row["High"]), float(row["Low"]), float(row["Close"])
                result = self._check_trade_exit(trade, high, low, close)
                if result:
                    self.db.close_trade(
                        trade["id"], result["exit_price"], check_date.isoformat(),
                        result["exit_reason"], result["actual_return_pct"], result["status"],
                    )
                    log.info(f"    Retro-close: {trade['ticker']} {trade['horizon_label']} "
                             f"-> {result['status']} ({result['actual_return_pct']:+.2f}%)")
            except Exception as e:
                log.warning(f"    Retro-check failed {trade['ticker']}: {e}")

    # ----------------------------------------------------------
    # SCAN
    # ----------------------------------------------------------
    def scan_date(self, scan_date: date) -> dict:
        date_str = scan_date.isoformat()
        if self.db.was_scanned(date_str):
            log.info(f"Already scanned {date_str} — skip")
            return {"signals_found": 0, "trades_entered": 0, "skipped": True}

        log.info(f"SCANNING {len(SCAN_TICKERS)} stocks for {date_str}...")
        t0 = _time.time()
        signals_found = 0
        trades_entered = 0
        errors = 0

        for i, ticker in enumerate(SCAN_TICKERS):
            try:
                result = self._analyse_ticker(ticker)
                if not result or result.get("error") or result.get("direction") == "NO SIGNAL":
                    continue

                horizon_levels = result.get("horizon_levels", {})
                for days, hz_data in horizon_levels.items():
                    signals_found += 1
                    # Filters
                    if result.get("win_rate", 0) < MIN_WIN_RATE:
                        continue
                    if result.get("confidence", "LOW") == "LOW":
                        continue
                    if hz_data.get("rr_ratio", 0) < MIN_RR_RATIO:
                        continue

                    expiry = add_trading_days(scan_date, days)
                    trade = {
                        "ticker": ticker,
                        "instrument": result.get("instrument"),
                        "sector": result.get("sector"),
                        "direction": result["direction"],
                        "horizon_days": days,
                        "horizon_label": HORIZON_CONFIG[days]["label"],
                        "patterns": ",".join(result.get("patterns_tradeable", [])),
                        "entry_price": result["entry"],
                        "target_price": hz_data["target"],
                        "sl_price": hz_data["sl"],
                        "target_pct": hz_data.get("target_pct"),
                        "sl_pct": hz_data.get("sl_pct"),
                        "rr_ratio": hz_data.get("rr_ratio"),
                        "predicted_win_rate": result.get("win_rate"),
                        "predicted_pf": result.get("profit_factor"),
                        "confidence": result.get("confidence"),
                        "n_matches": result.get("n_matches"),
                        "match_tier": result.get("match_tier"),
                        "entry_date": date_str,
                        "expiry_date": expiry.isoformat(),
                        "indicators": result.get("indicators", {}),
                    }
                    row_id = self.db.insert_trade(trade)
                    if row_id:
                        trades_entered += 1
                        log.info(f"  ENTER: {ticker} {HORIZON_CONFIG[days]['label']} "
                                 f"{result['direction']} @ {result['entry']:.2f} "
                                 f"(WR={result.get('win_rate',0):.0f}%, "
                                 f"R:R={hz_data.get('rr_ratio',0):.1f}x)")

            except Exception as e:
                errors += 1
                log.warning(f"  Error {ticker}: {e}")

            if (i + 1) % 10 == 0:
                log.info(f"  Progress: {i+1}/{len(SCAN_TICKERS)}")

        duration = _time.time() - t0
        self.db.log_scan(date_str, len(SCAN_TICKERS), signals_found, trades_entered, errors, duration)
        log.info(f"SCAN DONE: {signals_found} signals, {trades_entered} entered, "
                 f"{errors} errors in {duration:.1f}s")
        return {"signals_found": signals_found, "trades_entered": trades_entered,
                "errors": errors, "duration": duration}

    def _analyse_ticker(self, ticker: str) -> Optional[dict]:
        """Analyse a single ticker for signals across all horizons."""
        try:
            df = yf.download(ticker, period="6mo", interval="1d", progress=False)
            if df is None or df.empty or len(df) < 50:
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            df = df.dropna()
        except Exception:
            return None

        current_price = float(df["Close"].iloc[-1])
        instrument = _yahoo_to_internal(ticker)
        sector = INSTRUMENT_SECTORS.get(instrument, "unknown")

        # Detect patterns
        pr = detect_live_patterns(df)
        if isinstance(pr, dict):
            patterns = [p.strip() for p in pr.get("patterns", "none").split(",") if p.strip()]
            vol_confirmed = pr.get("volume_confirmed", False)
        else:
            patterns = [p.strip() for p in str(pr).split(",") if p.strip()]
            vol_confirmed = False

        tradeable = [p for p in patterns if is_tradeable_pattern(p)]
        if not tradeable:
            return None

        indicators = self._compute_indicators(df)
        prediction = self.sp.predict_multi_pattern(
            ",".join(tradeable), timeframe="daily",
            trend_short=indicators.get("trend_short"),
            rsi_zone=indicators.get("rsi_zone"),
            price_vs_vwap=indicators.get("price_vs_vwap"),
            instrument=instrument,
        )

        if not prediction or prediction.get("predicted_direction") not in ("bullish", "bearish"):
            return None

        direction = prediction["predicted_direction"].upper()
        atr = indicators.get("atr_14", current_price * 0.015)
        is_structural = bool(set(tradeable) & STRUCTURAL_SL_PATTERNS)
        sl_mult = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
        horizons_data = prediction.get("horizons", {})

        horizon_levels = {}
        for days, cfg in HORIZON_CONFIG.items():
            h_sl_pct = cfg["sl_mult_scale"] * sl_mult * atr / current_price * 100
            h_sl_pct = max(SL_FLOOR_PCT, min(cfg["sl_cap"], h_sl_pct))
            hk = horizons_data.get(f"+{days}_candles", {})
            h_avg_ret = abs(hk.get("avg_return", 0)) if hk else 0
            h_target_pct = max(h_sl_pct * cfg["rr_min"], h_avg_ret) if h_avg_ret > 0 \
                else h_sl_pct * cfg["rr_min"]
            if direction == "BULLISH":
                h_sl = round(current_price * (1 - h_sl_pct / 100), 2)
                h_target = round(current_price * (1 + h_target_pct / 100), 2)
            else:
                h_sl = round(current_price * (1 + h_sl_pct / 100), 2)
                h_target = round(current_price * (1 - h_target_pct / 100), 2)
            horizon_levels[days] = {
                "sl": h_sl, "target": h_target,
                "sl_pct": round(h_sl_pct, 2), "target_pct": round(h_target_pct, 2),
                "rr_ratio": round(h_target_pct / h_sl_pct, 1) if h_sl_pct > 0 else 0,
            }

        return {
            "ticker": ticker, "instrument": instrument, "sector": sector,
            "direction": direction, "entry": current_price,
            "horizon_levels": horizon_levels,
            "confidence": prediction.get("confidence_level", "LOW"),
            "win_rate": prediction.get("win_rate", 0),
            "profit_factor": prediction.get("profit_factor", 0),
            "n_matches": prediction.get("n_matches", 0),
            "match_tier": prediction.get("match_tier", "unknown"),
            "patterns_tradeable": tradeable,
            "vol_confirmed": vol_confirmed,
            "indicators": indicators,
        }

    def _compute_indicators(self, df) -> dict:
        close = df["Close"].astype(float)
        high = df["High"].astype(float)
        low = df["Low"].astype(float)
        volume = df["Volume"].astype(float) if "Volume" in df.columns else None
        ind = {}
        for p in [9, 21, 50, 200]:
            if len(close) >= p:
                ind[f"ema_{p}"] = float(close.ewm(span=p, adjust=False).mean().iloc[-1])
        if len(close) >= 15:
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss_s = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss_s
            ind["rsi_14"] = float((100 - (100 / (1 + rs))).iloc[-1])
        if len(close) >= 15:
            tr = pd.concat([high - low, (high - close.shift()).abs(),
                            (low - close.shift()).abs()], axis=1).max(axis=1)
            ind["atr_14"] = float(tr.rolling(14).mean().iloc[-1])
        if volume is not None and len(volume) >= 21 and volume.sum() > 0:
            vol_ma = float(volume.rolling(20).mean().iloc[-1])
            if vol_ma > 0:
                ind["vol_ratio"] = float(volume.iloc[-1] / vol_ma)
        if volume is not None and volume.sum() > 0:
            try:
                tp = (high + low + close) / 3
                ind["price_vs_vwap"] = "above" if close.iloc[-1] > float(
                    (tp * volume).cumsum().iloc[-1] / volume.cumsum().iloc[-1]) else "below"
            except Exception:
                pass
        if "ema_9" in ind and "ema_21" in ind:
            ind["trend_short"] = "bullish" if ind["ema_9"] > ind["ema_21"] else "bearish"
        if "rsi_14" in ind:
            v = ind["rsi_14"]
            ind["rsi_zone"] = "oversold" if v < 30 else "overbought" if v > 70 else "neutral"
        return ind

    # ----------------------------------------------------------
    # MONITOR
    # ----------------------------------------------------------
    def monitor_open_positions(self, check_date: date = None) -> dict:
        if check_date is None:
            check_date = date.today()

        open_trades = self.db.get_open_trades()
        if not open_trades:
            log.info("No open positions")
            return {"checked": 0, "closed": 0}

        log.info(f"MONITORING {len(open_trades)} positions for {check_date}")

        # Group by ticker
        ticker_trades = defaultdict(list)
        for t in open_trades:
            ticker_trades[t["ticker"]].append(t)

        closed = 0
        checked = 0

        for ticker, trades in ticker_trades.items():
            try:
                earliest = min(date.fromisoformat(t["entry_date"]) for t in trades)
                start_str = (earliest - timedelta(days=3)).strftime("%Y-%m-%d")
                end_str = (check_date + timedelta(days=1)).strftime("%Y-%m-%d")
                df = yf.download(ticker, start=start_str, end=end_str, progress=False)
                if df.empty:
                    continue
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                df.index = pd.to_datetime(df.index).date

                for trade in trades:
                    checked += 1
                    entry_dt = date.fromisoformat(trade["entry_date"])
                    expiry_dt = date.fromisoformat(trade["expiry_date"])

                    # Check candles from day after entry to min(check_date, expiry)
                    mask = (df.index > entry_dt) & (df.index <= min(check_date, expiry_dt))
                    relevant = df.loc[mask]

                    trade_closed = False
                    for candle_date, row in relevant.iterrows():
                        h, l, c = float(row["High"]), float(row["Low"]), float(row["Close"])
                        result = self._check_trade_exit(trade, h, l, c)
                        if result:
                            d_str = candle_date.isoformat() if isinstance(candle_date, date) else str(candle_date)
                            self.db.close_trade(
                                trade["id"], result["exit_price"], d_str,
                                result["exit_reason"], result["actual_return_pct"],
                                result["status"],
                            )
                            closed += 1
                            log.info(f"  CLOSED: {ticker} {trade['horizon_label']} "
                                     f"-> {result['status']} ({result['actual_return_pct']:+.2f}%)")
                            trade_closed = True
                            break

                    # Expiry check
                    if not trade_closed and check_date >= expiry_dt:
                        mask_exp = df.index <= expiry_dt
                        if mask_exp.any():
                            last_close = float(df.loc[mask_exp].iloc[-1]["Close"])
                            ret = self._calc_return(trade, last_close)
                            status = "EXPIRED_WIN" if ret > 0 else "EXPIRED_LOSS"
                            self.db.close_trade(
                                trade["id"], last_close, expiry_dt.isoformat(),
                                "expired", ret, status,
                            )
                            closed += 1
                            log.info(f"  EXPIRED: {ticker} {trade['horizon_label']} "
                                     f"-> {status} ({ret:+.2f}%)")

            except Exception as e:
                log.warning(f"  Monitor error {ticker}: {e}")

        log.info(f"MONITOR DONE: {checked} checked, {closed} closed")
        return {"checked": checked, "closed": closed}

    def _check_trade_exit(self, trade: dict, high: float, low: float,
                          close: float) -> Optional[dict]:
        direction = trade["direction"]
        target = trade["target_price"]
        sl = trade["sl_price"]

        if direction == "BULLISH":
            if low <= sl:
                return {"exit_price": sl, "exit_reason": "sl_hit",
                        "actual_return_pct": self._calc_return(trade, sl), "status": "LOST"}
            if high >= target:
                return {"exit_price": target, "exit_reason": "target_hit",
                        "actual_return_pct": self._calc_return(trade, target), "status": "WON"}
        else:
            if high >= sl:
                return {"exit_price": sl, "exit_reason": "sl_hit",
                        "actual_return_pct": self._calc_return(trade, sl), "status": "LOST"}
            if low <= target:
                return {"exit_price": target, "exit_reason": "target_hit",
                        "actual_return_pct": self._calc_return(trade, target), "status": "WON"}
        return None

    def _calc_return(self, trade: dict, exit_price: float) -> float:
        entry = trade["entry_price"]
        if trade["direction"] == "BULLISH":
            return round((exit_price - entry) / entry * 100, 2)
        return round((entry - exit_price) / entry * 100, 2)

    # ----------------------------------------------------------
    # DAILY REPORT
    # ----------------------------------------------------------
    def _generate_daily_report(self, report_date: date):
        date_str = report_date.isoformat()
        today_trades = self.db.get_trades_by_date(date_str)
        all_closed = self.db.get_closed_trades()
        today_closed = [t for t in all_closed if t.get("exit_date") == date_str]

        wins = [t for t in today_closed if t["status"] in ("WON", "EXPIRED_WIN")]
        losses = [t for t in today_closed if t["status"] in ("LOST", "EXPIRED_LOSS")]
        total_ret = sum(t.get("actual_return_pct", 0) for t in today_closed)
        avg_w = float(np.mean([t["actual_return_pct"] for t in wins])) if wins else 0
        avg_l = float(np.mean([t["actual_return_pct"] for t in losses])) if losses else 0
        wr = (len(wins) / len(today_closed) * 100) if today_closed else 0

        best = max(today_closed, key=lambda t: t.get("actual_return_pct", 0)) if today_closed else None
        worst = min(today_closed, key=lambda t: t.get("actual_return_pct", 0)) if today_closed else None

        summary = {
            "report_date": date_str,
            "trades_opened": len(today_trades),
            "trades_closed": len(today_closed),
            "wins": len(wins), "losses": len(losses),
            "expired_wins": len([t for t in wins if t["status"] == "EXPIRED_WIN"]),
            "expired_losses": len([t for t in losses if t["status"] == "EXPIRED_LOSS"]),
            "total_return_pct": round(total_ret, 2),
            "avg_win_pct": round(avg_w, 2), "avg_loss_pct": round(avg_l, 2),
            "win_rate": round(wr, 1),
            "best_trade": f"{best['ticker']} {best['horizon_label']} {best['actual_return_pct']:+.2f}%" if best else "",
            "worst_trade": f"{worst['ticker']} {worst['horizon_label']} {worst['actual_return_pct']:+.2f}%" if worst else "",
        }
        self.db.save_daily_summary(summary)
        log.info(f"REPORT: {json.dumps(summary)}")

    # ----------------------------------------------------------
    # RAG FEEDBACK
    # ----------------------------------------------------------
    def feed_outcomes_to_rag(self):
        """Push closed trade outcomes into RAG feedback system."""
        FEEDBACK_FILE = "feedback/feedback_log.json"
        LEARNING_FILE = "feedback/learned_rules.json"

        def _load_json(path, default=None):
            if default is None:
                default = []
            if not os.path.exists(path):
                return default
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return default

        def _save_json(path, data):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)

        def _is_trend_aligned(entry):
            trend = entry.get("indicators_at_entry", {}).get("trend_short", "")
            direction = entry.get("direction", "")
            return (direction == "BULLISH" and trend == "bullish") or \
                   (direction == "BEARISH" and trend == "bearish")

        def _generate_pattern_note(pattern, win_rate, avg_ret, stats):
            if win_rate >= 60:
                return f"Strong performer — {win_rate:.0f}% win rate, avg return {avg_ret:+.1f}%"
            elif win_rate >= 45:
                return f"Moderate — {win_rate:.0f}% win rate. Check trend alignment before trading."
            else:
                sl_hits = sum(1 for r in stats["reasons"] if r == "stop_loss_hit")
                time_exits = sum(1 for r in stats["reasons"] if r == "time_exit")
                total = stats["wins"] + stats["losses"]
                note = f"Underperforming — {win_rate:.0f}% win rate."
                if sl_hits > total * 0.4:
                    note += " Frequent SL hits — may need wider stops or better timing."
                if time_exits > total * 0.3:
                    note += " Often exits on time — direction may be right but slow."
                return note

        def _update_learnings(feedback):
            if len(feedback) < 3:
                return
            learnings = _load_json(LEARNING_FILE, {"rules": [], "pattern_adjustments": {}, "updated_at": None})
            pattern_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "returns": [], "reasons": []})
            for entry in feedback:
                for p in entry.get("patterns", []):
                    stats = pattern_stats[p]
                    if entry["outcome"] == "win":
                        stats["wins"] += 1
                    else:
                        stats["losses"] += 1
                    stats["returns"].append(entry.get("actual_return_pct", 0))
                    stats["reasons"].append(entry.get("exit_reason", ""))
            for pattern, stats in pattern_stats.items():
                total = stats["wins"] + stats["losses"]
                if total >= 2:
                    win_rate = stats["wins"] / total * 100
                    avg_ret = np.mean(stats["returns"]) if stats["returns"] else 0
                    learnings["pattern_adjustments"][pattern] = {
                        "actual_win_rate": win_rate,
                        "avg_return": round(avg_ret, 2),
                        "total_trades": total,
                        "note": _generate_pattern_note(pattern, win_rate, avg_ret, stats),
                        "updated_at": datetime.now().isoformat(),
                    }
            rules = []
            trend_aligned_wins = sum(1 for e in feedback if e["outcome"] == "win" and _is_trend_aligned(e))
            trend_aligned_total = sum(1 for e in feedback if _is_trend_aligned(e))
            trend_against_wins = sum(1 for e in feedback if e["outcome"] == "win" and not _is_trend_aligned(e))
            trend_against_total = sum(1 for e in feedback if not _is_trend_aligned(e))
            if trend_aligned_total >= 3 and trend_against_total >= 3:
                aligned_wr = trend_aligned_wins / trend_aligned_total * 100
                against_wr = trend_against_wins / trend_against_total * 100
                if aligned_wr > against_wr + 10:
                    rules.append({"rule": f"Trend-aligned trades win {aligned_wr:.0f}% vs counter-trend {against_wr:.0f}%. Prefer trend-aligned setups.",
                                  "confidence": min(0.9, trend_aligned_total / 20), "type": "prefer", "context": "trend_alignment"})
            vol_conf_wins = sum(1 for e in feedback if e["outcome"] == "win" and e.get("indicators_at_entry", {}).get("vol_ratio", 1) > 1.2)
            vol_conf_total = sum(1 for e in feedback if e.get("indicators_at_entry", {}).get("vol_ratio", 1) > 1.2)
            if vol_conf_total >= 3:
                vol_wr = vol_conf_wins / vol_conf_total * 100
                if vol_wr > 60:
                    rules.append({"rule": f"Trades with volume confirmation (>1.2x avg) win {vol_wr:.0f}%. Prioritize volume-confirmed patterns.",
                                  "confidence": min(0.85, vol_conf_total / 15), "type": "prefer", "context": "volume_confirmation"})
            sl_exits = [e for e in feedback if e.get("exit_reason") == "stop_loss_hit"]
            if len(sl_exits) >= 3:
                sl_rate = len(sl_exits) / len(feedback) * 100
                if sl_rate > 40:
                    rules.append({"rule": f"Stop-loss hit rate is {sl_rate:.0f}% — consider widening SL or waiting for better confirmation.",
                                  "confidence": min(0.8, len(sl_exits) / 10), "type": "adjust", "context": "stop_loss_tuning"})
            learnings["rules"] = rules
            learnings["updated_at"] = datetime.now().isoformat()
            _save_json(LEARNING_FILE, learnings)

        # Main logic
        closed = self.db.get_closed_trades()
        existing = _load_json(FEEDBACK_FILE, [])
        seen_ids = {f.get("trade_id") for f in existing}
        new = 0

        for t in closed:
            pid = f"paper_{t['id']}"
            if pid in seen_ids:
                continue
            outcome = "win" if t["status"] in ("WON", "EXPIRED_WIN") else "loss"
            existing.append({
                "trade_id": pid,
                "ticker": t["ticker"],
                "instrument": t.get("instrument", ""),
                "direction": t["direction"],
                "patterns": t.get("patterns", "").split(","),
                "predicted_win_rate": t.get("predicted_win_rate", 0),
                "predicted_pf": t.get("predicted_pf", 0),
                "confidence": t.get("confidence", ""),
                "outcome": outcome,
                "actual_return_pct": t.get("actual_return_pct", 0),
                "exit_reason": t.get("exit_reason", ""),
                "indicators_at_entry": json.loads(t.get("indicators_json", "{}")),
                "notes": f"Paper trade (auto) — {t.get('horizon_label', '')}",
                "timestamp": t.get("exit_date", ""),
                "source": "paper_trader",
            })
            new += 1

        if new:
            _save_json(FEEDBACK_FILE, existing)
            _update_learnings(existing)
            log.info(f"Fed {new} outcomes to RAG")
        else:
            log.info("No new outcomes for RAG")


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sys
    engine = PaperTrader()

    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "run"
    if cmd == "scan":
        engine.scan_date(date.today())
    elif cmd == "monitor":
        engine.monitor_open_positions()
    elif cmd == "feedback":
        engine.feed_outcomes_to_rag()
    elif cmd == "stats":
        print(json.dumps(engine.db.get_stats(), indent=2))
    elif cmd == "run":
        engine.run()
    else:
        print(f"Unknown: {cmd}. Use: run|scan|monitor|feedback|stats")
