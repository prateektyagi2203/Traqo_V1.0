# -*- coding: utf-8 -*-
"""
Traqo — RAG Powered Quantitative Candlestick Intelligence by Prateek Tyagi
================================================
Zero external dependencies. Uses Python's built-in http.server.
All HTML/CSS/JS is server-rendered — no React, no Flask, no build step.

Run:
    python paper_trading_dashboard.py
    → Opens http://localhost:8521
"""

import os
import sys
import json
import sqlite3
import webbrowser
import subprocess
import urllib.parse
import threading
import logging
from datetime import date, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

try:
    import yfinance as yf
    _HAS_YF = True
    print(f"✅ yfinance loaded successfully (v{yf.__version__})")
except ImportError as e:
    _HAS_YF = False
    print(f"❌ yfinance import failed: {e}")
    print("💡 Solution: Ensure virtual environment is active and run: pip install yfinance")

# ---- Market Cap classification (based on index membership) ----
_LARGECAP_TICKERS = {
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "BHARTIARTL", "SBIN", "LT",
    "BAJFINANCE", "AXISBANK", "KOTAKBANK", "ITC", "HINDUNILVR", "MARUTI", "TATAMOTORS",
    "HCLTECH", "SUNPHARMA", "TITAN", "ADANIENT", "WIPRO", "TATASTEEL", "M&M", "NTPC",
    "POWERGRID", "ULTRACEMCO", "ASIANPAINT", "BAJAJFINSV", "COALINDIA", "NESTLEIND",
    "JSWSTEEL", "GRASIM", "ONGC", "DIVISLAB", "DRREDDY", "CIPLA", "APOLLOHOSP",
    "HEROMOTOCO", "EICHERMOT", "BPCL", "TECHM", "TATACONSUM", "BRITANNIA", "HINDALCO",
    "INDUSINDBK", "SBILIFE", "HDFCLIFE", "BAJAJ-AUTO", "ADANIPORTS", "SHRIRAMFIN",
    "ETERNAL", "TRENT",
    # Nifty Next 50
    "ABB", "ACC", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM", "ATGL", "AUROPHARMA",
    "BAJAJHLDNG", "BANKBARODA", "BEL", "BERGEPAINT", "BIOCON", "BOSCHLTD", "CANBK",
    "CHOLAFIN", "COLPAL", "DABUR", "DLF", "GAIL", "GODREJCP", "HAL", "HAVELLS",
    "ICICIPRULI", "INDIGO", "IOC", "IRCTC", "IRFC", "JINDALSTEL", "JIOFIN", "LICI",
    "LTIM", "LTTS", "LUPIN", "MAXHEALTH", "MOTHERSON", "NAUKRI", "NHPC", "OBEROIRLTY",
    "OFSS", "PAYTM", "PFC", "PIDILITIND", "PNB", "POLYCAB", "RECLTD", "SBICARD",
    "SIEMENS", "SRF", "TATAPOWER",
}

def _get_cap(ticker: str) -> str:
    """Return LargeCap / MidCap based on index membership."""
    base = ticker.replace(".NS", "").replace(".BO", "").upper()
    return "LargeCap" if base in _LARGECAP_TICKERS else "MidCap"

_SECTOR_DISPLAY = {
    "auto": "Auto", "banking": "Banking", "capital_goods": "Capital Goods",
    "chemicals": "Chemicals", "consumer": "Consumer", "consumer_tech": "Consumer Tech",
    "energy": "Energy", "finance": "Finance", "fmcg": "FMCG", "it": "IT",
    "metals": "Metals", "pharma": "Pharma", "realty": "Realty", "unknown": "Other",
    "": "Other",
}

logger = logging.getLogger(__name__)

DB_PATH = "paper_trades/paper_trades.db"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# DATABASE QUERIES
# ============================================================
def get_db():
    conn = sqlite3.connect(os.path.join(SCRIPT_DIR, DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _regenerate_learned_rules():
    """Rebuild learned_rules.json from current feedback_log.json.

    Must be called after ANY trade removal to keep penalties/boosts consistent.
    """
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from paper_trader import PaperTrader
        PaperTrader.regenerate_learned_rules()
    except Exception as e:
        logger.error(f"Failed to regenerate learned rules: {e}")


def cancel_trade(trade_id: int):
    """Cancel an open trade: mark CANCELLED in DB, remove from RAG feedback, rebuild learned rules."""
    # 1) Mark CANCELLED in SQLite
    db_full = os.path.join(SCRIPT_DIR, DB_PATH)
    conn = sqlite3.connect(db_full)
    conn.execute(
        "UPDATE trades SET status='CANCELLED', exit_date=?, exit_reason='user_cancelled',"
        " updated_at=datetime('now') WHERE id=? AND status='OPEN'",
        (date.today().isoformat(), trade_id)
    )
    conn.commit()
    conn.close()

    # 2) Erase from RAG feedback log
    fb_path = os.path.join(SCRIPT_DIR, "feedback", "feedback_log.json")
    if os.path.exists(fb_path):
        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                feedback = json.load(f)
            pid = f"paper_{trade_id}"
            cleaned = [e for e in feedback if e.get("trade_id") != pid]
            if len(cleaned) < len(feedback):
                with open(fb_path, "w", encoding="utf-8") as f:
                    json.dump(cleaned, f, indent=2, default=str)
        except Exception:
            pass

    # 3) Regenerate learned rules (penalties/boosts) from remaining feedback
    _regenerate_learned_rules()


def cancel_trades_bulk(ids: list):
    """Cancel multiple open trades, erase their RAG feedback imprints, and rebuild learned rules."""
    db_full = os.path.join(SCRIPT_DIR, DB_PATH)
    conn = sqlite3.connect(db_full)
    today = date.today().isoformat()
    for trade_id in ids:
        conn.execute(
            "UPDATE trades SET status='CANCELLED', exit_date=?, exit_reason='user_cancelled',"
            " updated_at=datetime('now') WHERE id=? AND status='OPEN'",
            (today, trade_id)
        )
    conn.commit()
    conn.close()

    fb_path = os.path.join(SCRIPT_DIR, "feedback", "feedback_log.json")
    if os.path.exists(fb_path):
        try:
            with open(fb_path, "r", encoding="utf-8") as f:
                feedback = json.load(f)
            pids = {f"paper_{tid}" for tid in ids}
            cleaned = [e for e in feedback if e.get("trade_id") not in pids]
            if len(cleaned) < len(feedback):
                with open(fb_path, "w", encoding="utf-8") as f:
                    json.dump(cleaned, f, indent=2, default=str)
        except Exception:
            pass

    # Regenerate learned rules from remaining feedback
    _regenerate_learned_rules()


def purge_closed_trades(trade_ids: list):
    """Permanently delete closed/expired trades from DB, feedback, and learned rules.

    Unlike cancel (which only works on OPEN trades), this works on any status.
    Removes all traces: DB rows, position_monitoring, feedback_log, learned_rules.
    """
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from paper_trader import PaperTrader
        return PaperTrader.purge_trades_complete(trade_ids)
    except Exception as e:
        logger.error(f"Failed to purge trades: {e}")
        return {"deleted": 0, "feedback_removed": 0, "error": str(e)}


def purge_trades_by_date(from_date: str, to_date: str = None):
    """Permanently delete all non-OPEN trades closed between from_date and to_date."""
    if not to_date:
        to_date = from_date
    db_full = os.path.join(SCRIPT_DIR, DB_PATH)
    conn = sqlite3.connect(db_full)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id FROM trades WHERE status NOT IN ('OPEN') AND exit_date >= ? AND exit_date <= ?",
        (from_date, to_date + "T23:59:59")
    ).fetchall()
    conn.close()
    if rows:
        trade_ids = [r["id"] for r in rows]
        return purge_closed_trades(trade_ids)
    return {"deleted": 0, "feedback_removed": 0}


def q_stats():
    c = get_db()
    open_n = c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]
    closed_n = c.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')").fetchone()[0]
    wins = c.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0]
    losses = c.execute("SELECT COUNT(*) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0]
    avg_w = c.execute("SELECT AVG(actual_return_pct) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0] or 0
    avg_l = c.execute("SELECT AVG(actual_return_pct) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0] or 0
    tot_ret = c.execute("SELECT SUM(actual_return_pct) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')").fetchone()[0] or 0
    wr = (wins / closed_n * 100) if closed_n else 0
    pf = (abs(avg_w * wins) / abs(avg_l * losses)) if (losses and avg_l) else 0
    last_scan = c.execute("SELECT MAX(scan_date) FROM scan_log").fetchone()[0] or "Never"
    today_entered = c.execute("SELECT COUNT(*) FROM trades WHERE entry_date=?", (date.today().isoformat(),)).fetchone()[0]
    c.close()
    return {
        "open_trades": open_n, "closed_trades": closed_n, "total_trades": open_n + closed_n,
        "wins": wins, "losses": losses, "win_rate": round(wr, 1),
        "avg_win_pct": round(avg_w, 2), "avg_loss_pct": round(avg_l, 2),
        "profit_factor": round(pf, 2), "total_return_pct": round(tot_ret, 2),
        "last_scan": last_scan, "today_entered": today_entered,
    }


def q_open_trades():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date DESC, ticker").fetchall()]
    c.close()
    return rows


def q_closed_trades():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE status NOT IN ('OPEN','CANCELLED') ORDER BY exit_date DESC LIMIT 200").fetchall()]
    c.close()
    return rows


def q_today_trades():
    c = get_db()
    today_str = date.today().isoformat()
    rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE entry_date=? ORDER BY ticker, horizon_days", (today_str,)).fetchall()]
    if not rows:
        last_date = c.execute("SELECT MAX(entry_date) FROM trades").fetchone()[0]
        if last_date:
            rows = [dict(r) for r in c.execute("SELECT * FROM trades WHERE entry_date=? ORDER BY ticker, horizon_days", (last_date,)).fetchall()]
    c.close()
    return rows


def q_stats_by_horizon():
    c = get_db()
    rows = [dict(r) for r in c.execute("""
        SELECT horizon_days, horizon_label,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
               AVG(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN actual_return_pct END) as avg_win,
               AVG(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN actual_return_pct END) as avg_loss,
               SUM(actual_return_pct) as total_ret
        FROM trades WHERE status NOT IN ('OPEN','CANCELLED')
        GROUP BY horizon_days ORDER BY horizon_days
    """).fetchall()]
    for r in rows:
        t = r["wins"] + r["losses"]
        r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
    c.close()
    return rows


def q_stats_by_pattern():
    c = get_db()
    rows = [dict(r) for r in c.execute("""
        SELECT patterns,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
               AVG(actual_return_pct) as avg_ret
        FROM trades WHERE status NOT IN ('OPEN','CANCELLED')
        GROUP BY patterns ORDER BY total DESC LIMIT 20
    """).fetchall()]
    for r in rows:
        t = r["wins"] + r["losses"]
        r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
    c.close()
    return rows


def q_stats_by_stock():
    c = get_db()
    rows = [dict(r) for r in c.execute("""
        SELECT ticker,
               COUNT(*) as total,
               SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
               AVG(actual_return_pct) as avg_ret,
               SUM(actual_return_pct) as total_ret
        FROM trades WHERE status NOT IN ('OPEN','CANCELLED')
        GROUP BY ticker ORDER BY total DESC LIMIT 30
    """).fetchall()]
    for r in rows:
        t = r["wins"] + r["losses"]
        r["win_rate"] = round(r["wins"] / t * 100, 1) if t else 0
    c.close()
    return rows


def q_scan_log():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM scan_log ORDER BY scan_date DESC LIMIT 30").fetchall()]
    c.close()
    return rows


def q_daily_summaries():
    c = get_db()
    rows = [dict(r) for r in c.execute("SELECT * FROM daily_summary ORDER BY report_date DESC LIMIT 60").fetchall()]
    c.close()
    return rows


def get_engine_log():
    log_path = os.path.join(SCRIPT_DIR, "paper_trades/logs/paper_trader.log")
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            return f.readlines()[-60:]
    return []


# ---- Live Engine Runner (background thread + polling) ----
_engine_state = {
    "running": False,
    "action": "",
    "output_lines": [],
    "done": False,
    "success": None,
    "started_at": None,
}
_engine_lock = threading.Lock()

STREAMLIT_NOISE = (
    "ScriptRunContext", "streamlit run", "Session state does not function",
    "missing ScriptRunContext", "warning can be ignored",
    "If you want to run a streamlit", "streamlit app",
)

def _is_noise(line: str) -> bool:
    return any(n in line for n in STREAMLIT_NOISE) or not line.strip()

def _engine_worker(action, extra_args=None):
    global _engine_state
    try:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        # Use absolute path to virtual environment Python
        venv_python = r"C:\Users\tyagipra\Coding\Nifty_Data\.venv\Scripts\python.exe"
        python_executable = venv_python if os.path.exists(venv_python) else sys.executable
        
        # Ensure virtual environment paths are in PATH and PYTHONPATH
        venv_dir = r"C:\Users\tyagipra\Coding\Nifty_Data\.venv"
        venv_scripts = os.path.join(venv_dir, "Scripts")
        venv_lib = os.path.join(venv_dir, "Lib", "site-packages")
        
        # Update PATH to include venv scripts first
        env["PATH"] = venv_scripts + os.pathsep + env.get("PATH", "")
        # Clear and set PYTHONPATH to prioritize venv
        env["PYTHONPATH"] = venv_lib
        # Set VIRTUAL_ENV
        env["VIRTUAL_ENV"] = venv_dir
        # Unset PYTHONHOME to avoid conflicts
        env.pop("PYTHONHOME", None)
        
        # Debug information
        with _engine_lock:
            _engine_state["output_lines"].append(f"DEBUG: Using Python: {python_executable}")
            _engine_state["output_lines"].append(f"DEBUG: Venv exists: {os.path.exists(venv_python)}")
            _engine_state["output_lines"].append(f"DEBUG: VIRTUAL_ENV: {env.get('VIRTUAL_ENV', 'Not set')}")
            _engine_state["output_lines"].append(f"DEBUG: PYTHONPATH: {env.get('PYTHONPATH', 'Not set')}")
            
        # First test yfinance import in subprocess
        test_cmd = [python_executable, "-c", "import yfinance; print('yfinance import successful')"]
        with _engine_lock:
            _engine_state["output_lines"].append(f"DEBUG: Testing yfinance import...")
            
        test_proc = subprocess.Popen(
            test_cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=SCRIPT_DIR, env=env
        )
        test_output, _ = test_proc.communicate(timeout=10)
        
        with _engine_lock:
            _engine_state["output_lines"].append(f"DEBUG: yfinance test result: {test_output.strip()}")
            
        # If test failed, don't proceed with main command
        if test_proc.returncode != 0:
            with _engine_lock:
                _engine_state["output_lines"].append("ERROR: yfinance import test failed, aborting engine run")
                _engine_state["success"] = False
                _engine_state["done"] = True
                _engine_state["running"] = False
            return
        
        cmd_list = [python_executable, os.path.join(SCRIPT_DIR, "paper_trader.py"), action]
        if extra_args:
            cmd_list.extend(extra_args)
        proc = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=SCRIPT_DIR, env=env
        )
        for line in iter(proc.stdout.readline, ""):
            if not _is_noise(line):
                with _engine_lock:
                    _engine_state["output_lines"].append(line.rstrip())
        proc.stdout.close()
        ret = proc.wait(timeout=600)
        with _engine_lock:
            _engine_state["success"] = (ret == 0)
            _engine_state["done"] = True
            _engine_state["running"] = False
    except Exception as e:
        with _engine_lock:
            _engine_state["output_lines"].append(f"ERROR: {e}")
            _engine_state["success"] = False
            _engine_state["done"] = True
            _engine_state["running"] = False

def start_engine(action, extra_args=None):
    global _engine_state
    with _engine_lock:
        if _engine_state["running"]:
            return False  # already running
        _engine_state = {
            "running": True,
            "action": action,
            "output_lines": [f"Starting engine: {action}..."],
            "done": False,
            "success": None,
            "started_at": datetime.now().isoformat(),
        }
        # Add debug info about Python executable immediately
        _engine_state["output_lines"].append("DEBUG: start_engine called")
        venv_python = r"C:\Users\tyagipra\Coding\Nifty_Data\.venv\Scripts\python.exe"
        _engine_state["output_lines"].append(f"DEBUG: venv Python exists: {os.path.exists(venv_python)}")
        _engine_state["output_lines"].append(f"DEBUG: venv Python path: {venv_python}")
    t = threading.Thread(target=_engine_worker, args=(action, extra_args), daemon=True)
    t.start()
    return True

def get_engine_status():
    with _engine_lock:
        return {
            "running": _engine_state["running"],
            "done": _engine_state["done"],
            "success": _engine_state["success"],
            "action": _engine_state["action"],
            "lines": list(_engine_state["output_lines"]),
            "started_at": _engine_state["started_at"],
        }


PENDING_SIGNALS_FILE = os.path.join(SCRIPT_DIR, "paper_trades", "pending_signals.json")

def get_pending_signals():
    """Read the pending signals staging file if it exists."""
    if os.path.exists(PENDING_SIGNALS_FILE):
        try:
            with open(PENDING_SIGNALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ============================================================
# HTML HELPERS
# ============================================================
def _e(s):
    """Escape HTML."""
    if s is None:
        return "—"
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _price(v):
    if v is None:
        return "—"
    return f"₹{float(v):,.2f}"


def _pct(v, sign=True):
    if v is None:
        return "—"
    v = float(v)
    if sign and v > 0:
        return f"+{v:.2f}%"
    return f"{v:.2f}%"


def _date(d):
    if not d:
        return "—"
    try:
        return datetime.strptime(str(d), "%Y-%m-%d").strftime("%d %b %y")
    except Exception:
        return str(d)


def _ticker(t):
    return str(t).replace(".NS", "").replace(".BO", "") if t else ""


def _days_between(a, b):
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(a, "%Y-%m-%d")).days
    except Exception:
        return 0


# ============================================================
# LIVE PRICE FETCH
# ============================================================
def fetch_live_prices(tickers: list) -> dict:
    """Fetch current prices for a list of NSE tickers via yfinance.
    Returns {ticker_raw: price} dict. Non-blocking best-effort."""
    import pandas as pd
    prices = {}
    if not _HAS_YF:
        print(f"❌ [LIVE PRICE] yfinance not available (_HAS_YF={_HAS_YF})")
        return prices
    if not tickers:
        print(f"⚠️ [LIVE PRICE] No tickers provided")
        return prices
    # Build unique Yahoo symbols — tickers may already have .NS/.BO suffix
    unique = list(set(tickers))
    yf_syms = []
    for t in unique:
        sym = t.strip()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym = sym + ".NS"
        yf_syms.append(sym)
    print(f"[LIVE PRICE] Fetching {len(yf_syms)} tickers: {yf_syms[:5]}...")
    try:
        data = yf.download(yf_syms, period="5d", interval="1d", progress=False, threads=True)
        if data is None:
            print("[LIVE PRICE] yf.download returned None")
            return prices
        if data.empty:
            print("[LIVE PRICE] yf.download returned empty DataFrame")
            return prices
        print(f"[LIVE PRICE] Got data shape={data.shape}, columns type={type(data.columns).__name__}")
        # yfinance 1.2+ always returns MultiIndex columns: (Price, Ticker)
        if isinstance(data.columns, pd.MultiIndex):
            close_df = data["Close"]
            print(f"[LIVE PRICE] Close columns: {list(close_df.columns)}")
            for raw_t, yf_t in zip(unique, yf_syms):
                try:
                    if yf_t in close_df.columns:
                        series = close_df[yf_t].dropna()
                        if not series.empty:
                            prices[raw_t] = float(series.iloc[-1])
                except Exception as ex:
                    print(f"[LIVE PRICE] Error parsing {yf_t}: {ex}")
        else:
            # Fallback for older yfinance (single ticker, flat columns)
            print(f"[LIVE PRICE] Flat columns: {list(data.columns)}")
            if "Close" in data.columns and not data["Close"].dropna().empty:
                prices[unique[0]] = float(data["Close"].dropna().iloc[-1])
        print(f"[LIVE PRICE] Got prices for {len(prices)}/{len(unique)} tickers")
    except Exception as e:
        print(f"[LIVE PRICE] Exception: {e}")
        import traceback
        traceback.print_exc()
    return prices


def _status_classes(s):
    m = {
        "OPEN": ("bg-blue-50 text-blue-700 border-blue-200", "Open"),
        "WON": ("bg-emerald-50 text-emerald-700 border-emerald-200", "Won"),
        "LOST": ("bg-red-50 text-red-700 border-red-200", "Lost"),
        "EXPIRED_WIN": ("bg-emerald-50 text-emerald-700 border-emerald-200", "Exp Win"),
        "EXPIRED_LOSS": ("bg-red-50 text-red-700 border-red-200", "Exp Loss"),
    }
    return m.get(s, ("bg-gray-100 text-gray-600", s))


# ============================================================
# HTML TEMPLATES
# ============================================================
def page_shell(title, active_tab, body_html):
    tabs = [
        ("dashboard", "Dashboard", "M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM14 5a1 1 0 011-1h4a1 1 0 011 1v2a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM4 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H5a1 1 0 01-1-1v-4zM14 12a1 1 0 011-1h4a1 1 0 011 1v7a1 1 0 01-1 1h-4a1 1 0 01-1-1v-7z"),
        ("signals", "Today's Signals", "M13 10V3L4 14h7v7l9-11h-7z"),
        ("positions", "Open Positions", "M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"),
        ("history", "Trade History", "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"),
        ("market", "Market Indices", "M2 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H3a1 1 0 01-1-1V5zM12 5a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zM2 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1H3a1 1 0 01-1-1v-4zM12 15a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z"),
        ("performance", "Performance", "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"),
        ("engine", "Engine Control", "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"),
        ("feedback", "Feedback Loop", "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"),
    ]

    nav_items = ""
    for key, label, icon_path in tabs:
        is_active = key == active_tab
        cls = "bg-blue-50 text-blue-700 border border-blue-100" if is_active else "text-gray-500 hover:text-gray-800 hover:bg-gray-50"
        extra_icon = ""
        if key == "engine":
            extra_icon = f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />'
        nav_items += f'''
        <a href="/{key}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all {cls}">
          <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="{icon_path}" />{extra_icon}
          </svg>
          {label}
        </a>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(title)} — Traqo</title>
  <link rel="icon" type="image/png" href="data:image/png;base64,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">
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {{
      darkMode: 'class',
      theme: {{
        extend: {{
          fontFamily: {{ sans: ['Inter', 'sans-serif'] }},
        }}
      }}
    }}
  </script>
  <style>
    body {{ font-family: 'Inter', sans-serif; }}
    .scrollbar-thin::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    .scrollbar-thin::-webkit-scrollbar-track {{ background: transparent; }}
    .scrollbar-thin::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
    .glass {{ background: #ffffff; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    @keyframes fade-in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    .fade-in {{ animation: fade-in 0.25s ease-out; }}
    @keyframes pulse-dot {{ 0%,100% {{ box-shadow: 0 0 0 0 rgba(16,185,129,0.4); }} 50% {{ box-shadow: 0 0 0 6px rgba(16,185,129,0); }} }}
    .pulse-dot {{ animation: pulse-dot 2s infinite; }}
  </style>
</head>
<body class="bg-gray-50 text-gray-800 min-h-screen">
  <!-- Sidebar -->
  <aside class="fixed top-0 left-0 h-screen w-60 bg-white border-r border-gray-200 flex flex-col z-50 shadow-sm">
    <div class="px-5 py-5 border-b border-gray-200">
      <div class="flex items-center gap-3">
        <img src="data:image/png;base64,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" alt="Traqo" class="w-9 h-9 rounded-xl">
        <div>
          <div class="text-base font-bold text-gray-800">Traqo</div>
          <div class="text-[10px] text-blue-500 font-medium tracking-wide uppercase">Quantitative Candlestick Intelligence</div>
        </div>
      </div>
    </div>
    <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto scrollbar-thin">
      {nav_items}
    </nav>
    <div class="px-4 py-4 border-t border-gray-200">
      <div class="flex items-center gap-2 text-xs text-gray-400 mb-2">
        <div class="w-2 h-2 rounded-full bg-emerald-500 pulse-dot"></div>
        System Online
      </div>
      <div class="text-[10px] text-gray-300">by Prateek Tyagi</div>
    </div>
  </aside>

  <!-- Main Content -->
  <main class="ml-60 min-h-screen flex flex-col">
    <div class="p-8 max-w-[1400px] mx-auto fade-in flex-1 w-full">
      {body_html}
    </div>
    <footer class="border-t border-gray-200 py-4 px-8 text-center">
      <p class="text-sm text-blue-400"><span class="font-bold text-blue-600">TRAQO</span> &mdash; RAG Powered Quantitative Candlestick Intelligence by <span class="font-medium text-blue-500">Prateek Tyagi</span></p>
    </footer>
  </main>
</body>
</html>'''


def stat_card(label, value, subtitle="", color="indigo"):
    color_map = {
        "indigo": "bg-white border-gray-200 shadow-sm",
        "green": "bg-white border-emerald-200 shadow-sm",
        "red": "bg-white border-red-200 shadow-sm",
        "amber": "bg-white border-amber-200 shadow-sm",
        "cyan": "bg-white border-blue-200 shadow-sm",
    }
    label_color = {
        "indigo": "text-blue-600",
        "green": "text-emerald-600",
        "red": "text-red-600",
        "amber": "text-amber-600",
        "cyan": "text-blue-600",
    }
    sub_html = f'<p class="mt-1 text-xs text-gray-400">{_e(subtitle)}</p>' if subtitle else ""
    return f'''<div class="rounded-xl {color_map.get(color, color_map["indigo"])} border p-5">
      <p class="text-xs font-medium uppercase tracking-wider {label_color.get(color, "text-blue-600")}">{_e(label)}</p>
      <p class="mt-2 text-2xl font-bold text-gray-800">{_e(str(value))}</p>
      {sub_html}
    </div>'''


def badge(text, variant="default"):
    styles = {
        "default": "bg-gray-100 text-gray-600 border border-gray-200",
        "success": "bg-emerald-50 text-emerald-700 border border-emerald-200",
        "danger": "bg-red-50 text-red-700 border border-red-200",
        "warning": "bg-amber-50 text-amber-700 border border-amber-200",
        "info": "bg-blue-50 text-blue-700 border border-blue-200",
        "bullish": "bg-emerald-50 text-emerald-600",
    }
    return f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {styles.get(variant, styles["default"])}">{_e(text)}</span>'


def status_badge(status):
    cls, label = _status_classes(status)
    return f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border {cls}">{_e(label)}</span>'


# ============================================================
# PAGE RENDERERS
# ============================================================
def render_dashboard():
    s = q_stats()
    open_trades = q_open_trades()

    cards = f'''
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      {stat_card("Open Trades", s["open_trades"], f'{s["today_entered"]} entered today', "indigo")}
      {stat_card("Closed Trades", s["closed_trades"], f'{s["wins"]}W / {s["losses"]}L', "cyan")}
      {stat_card("Win Rate", f'{s["win_rate"]}%', "of closed trades" if s["closed_trades"] else "no closed trades",
                 "green" if s["win_rate"] >= 55 else "amber" if s["win_rate"] >= 45 else "red")}
      {stat_card("Profit Factor", s["profit_factor"],
                 f'Avg W: {_pct(s["avg_win_pct"])} | L: {_pct(s["avg_loss_pct"])}',
                 "green" if s["profit_factor"] >= 1.5 else "amber" if s["profit_factor"] >= 1.0 else "red")}
    </div>
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
      {stat_card("Total Return", _pct(s["total_return_pct"]), "", "green" if s["total_return_pct"] >= 0 else "red")}
      {stat_card("Last Scan", _date(s["last_scan"]) if s["last_scan"] != "Never" else "Never", "", "indigo")}
      {stat_card("Total Trades", s["total_trades"], "all time", "cyan")}
    </div>'''

    # Group open trades by stock
    by_stock = {}
    for t in open_trades:
        tk = _ticker(t["ticker"])
        if tk not in by_stock:
            raw_sector = (t.get("sector") or "").strip()
            by_stock[tk] = {
                "count": 0,
                "direction": t["direction"],
                "cap": _get_cap(t["ticker"]),
                "sector": _SECTOR_DISPLAY.get(raw_sector, raw_sector.title() if raw_sector else "Other"),
            }
        by_stock[tk]["count"] += 1

    stocks_html = ""
    if by_stock:
        # Collect unique caps and sectors for filter buttons
        all_caps = sorted(set(info["cap"] for info in by_stock.values()))
        all_sectors = sorted(set(info["sector"] for info in by_stock.values()))

        cap_buttons = ''.join(
            f'<button onclick="filterDashStocks(\'cap\', \'{c}\')" class="dash-filter-btn px-3 py-1 rounded-full text-xs font-medium border border-gray-200 bg-white text-gray-600 hover:border-blue-400 hover:text-blue-600 transition" data-group="cap" data-value="{c}">{c}</button>'
            for c in all_caps
        )
        sector_buttons = ''.join(
            f'<button onclick="filterDashStocks(\'sector\', \'{_e(sector)}\')" class="dash-filter-btn px-3 py-1 rounded-full text-xs font-medium border border-gray-200 bg-white text-gray-600 hover:border-blue-400 hover:text-blue-600 transition" data-group="sector" data-value="{_e(sector)}">{_e(sector)}</button>'
            for sector in all_sectors
        )

        stock_chips = ""
        for tk, info in sorted(by_stock.items()):
            dir_badge = badge("↑", "bullish")
            cap_color = "bg-blue-50 text-blue-600" if info["cap"] == "LargeCap" else "bg-purple-50 text-purple-600"
            stock_chips += f'''
            <div class="dash-stock-chip rounded-lg bg-white border border-gray-200 p-3 hover:border-blue-300 transition shadow-sm"
                 data-cap="{_e(info['cap'])}" data-sector="{_e(info['sector'])}" data-stock="{_e(tk)}">
              <div class="flex items-center justify-between">
                <span class="text-sm font-semibold text-gray-800">{_e(tk)}</span>
                {dir_badge}
              </div>
              <p class="text-xs text-gray-400 mt-1">{info["count"]} active trade{"s" if info["count"] > 1 else ""}</p>
              <div class="flex items-center gap-1.5 mt-2">
                <span class="inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium {cap_color}">{info["cap"]}</span>
                <span class="inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-500">{_e(info["sector"])}</span>
              </div>
            </div>'''

        stocks_html = f'''
        <div class="glass rounded-xl p-6 mt-6">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-gray-800">Open Positions by Stock</h3>
            <span id="dashStockCount" class="text-xs text-gray-400">{len(by_stock)} stocks</span>
          </div>
          <!-- Sort & Filter Bar -->
          <div class="mb-4 space-y-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-medium text-gray-500 w-12">Sort:</span>
              <button onclick="sortDashStocks('alpha')" class="dash-sort-btn px-3 py-1 rounded-full text-xs font-medium border border-blue-400 bg-blue-50 text-blue-600 transition" data-sort="alpha">A→Z</button>
              <button onclick="sortDashStocks('alpha-desc')" class="dash-sort-btn px-3 py-1 rounded-full text-xs font-medium border border-gray-200 bg-white text-gray-600 hover:border-blue-400 hover:text-blue-600 transition" data-sort="alpha-desc">Z→A</button>
              <button onclick="sortDashStocks('trades')" class="dash-sort-btn px-3 py-1 rounded-full text-xs font-medium border border-gray-200 bg-white text-gray-600 hover:border-blue-400 hover:text-blue-600 transition" data-sort="trades">Most Trades</button>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-medium text-gray-500 w-12">Cap:</span>
              <button onclick="filterDashStocks('cap', 'All')" class="dash-filter-btn px-3 py-1 rounded-full text-xs font-medium border border-blue-400 bg-blue-50 text-blue-600 transition" data-group="cap" data-value="All">All</button>
              {cap_buttons}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-medium text-gray-500 w-12">Sector:</span>
              <button onclick="filterDashStocks('sector', 'All')" class="dash-filter-btn px-3 py-1 rounded-full text-xs font-medium border border-blue-400 bg-blue-50 text-blue-600 transition" data-group="sector" data-value="All">All</button>
              {sector_buttons}
            </div>
          </div>
          <div id="dashStockGrid" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">{stock_chips}</div>
        </div>
        <script>
        (function() {{
          let activeCap = 'All', activeSector = 'All';
          window.filterDashStocks = function(group, value) {{
            if (group === 'cap') activeCap = value;
            if (group === 'sector') activeSector = value;
            // Update button styles
            document.querySelectorAll('.dash-filter-btn[data-group="'+group+'"]').forEach(b => {{
              if (b.dataset.value === value) {{
                b.className = b.className.replace('border-gray-200 bg-white text-gray-600','').replace('border-blue-400 bg-blue-50 text-blue-600','') + ' border-blue-400 bg-blue-50 text-blue-600';
              }} else {{
                b.className = b.className.replace('border-blue-400 bg-blue-50 text-blue-600','').replace('border-gray-200 bg-white text-gray-600','') + ' border-gray-200 bg-white text-gray-600';
              }}
            }});
            applyDashFilters();
          }};
          window.sortDashStocks = function(mode) {{
            const grid = document.getElementById('dashStockGrid');
            const chips = Array.from(grid.querySelectorAll('.dash-stock-chip'));
            chips.sort((a, b) => {{
              if (mode === 'alpha') return a.dataset.stock.localeCompare(b.dataset.stock);
              if (mode === 'alpha-desc') return b.dataset.stock.localeCompare(a.dataset.stock);
              if (mode === 'trades') {{
                const ca = parseInt(a.querySelector('.text-gray-400').textContent);
                const cb = parseInt(b.querySelector('.text-gray-400').textContent);
                return cb - ca;
              }}
              return 0;
            }});
            chips.forEach(c => grid.appendChild(c));
            // Update sort button styles
            document.querySelectorAll('.dash-sort-btn').forEach(b => {{
              if (b.dataset.sort === mode) {{
                b.className = b.className.replace('border-gray-200 bg-white text-gray-600','').replace('border-blue-400 bg-blue-50 text-blue-600','') + ' border-blue-400 bg-blue-50 text-blue-600';
              }} else {{
                b.className = b.className.replace('border-blue-400 bg-blue-50 text-blue-600','').replace('border-gray-200 bg-white text-gray-600','') + ' border-gray-200 bg-white text-gray-600';
              }}
            }});
          }};
          function applyDashFilters() {{
            let shown = 0;
            document.querySelectorAll('.dash-stock-chip').forEach(c => {{
              const capMatch = activeCap === 'All' || c.dataset.cap === activeCap;
              const secMatch = activeSector === 'All' || c.dataset.sector === activeSector;
              if (capMatch && secMatch) {{ c.style.display = ''; shown++; }}
              else {{ c.style.display = 'none'; }}
            }});
            document.getElementById('dashStockCount').textContent = shown + ' of ' + document.querySelectorAll('.dash-stock-chip').length + ' stocks';
          }}
        }})();
        </script>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Dashboard</h2>
        <p class="text-sm text-gray-500 mt-1">Overview of your paper trading engine</p>
      </div>
      <a href="/dashboard" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
        Refresh
      </a>
    </div>
    {cards}
    {stocks_html}'''

    return page_shell("Dashboard", "dashboard", body)


def render_signals():
    trades = q_today_trades()
    entry_date = trades[0]["entry_date"] if trades else date.today().isoformat()

    # group by horizon
    by_hz = {}
    for t in trades:
        h = t.get("horizon_label") or f'{t["horizon_days"]}d'
        if h not in by_hz:
            by_hz[h] = []
        by_hz[h].append(t)

    summary_badges = f'''
    <div class="flex gap-3 flex-wrap mb-6">
      {badge(f'{len(trades)} signals', "info")}
      {badge(f'{sum(1 for t in trades if t["direction"]=="BULLISH")} bullish', "bullish")}
    </div>'''

    tables = ""
    if not trades:
        tables = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No signals yet</p>
          <p class="mt-1 text-sm text-gray-400">Run the engine to scan for signals</p>
        </div>'''
    else:
        for hz, hz_trades in by_hz.items():
            rows = ""
            for t in hz_trades:
                upside = ((t["target_price"] - t["entry_price"]) / t["entry_price"] * 100) if t["entry_price"] else 0
                dir_bdg = badge(t["direction"], "bullish")
                conf_v = "success" if t.get("confidence") == "HIGH" else "warning" if t.get("confidence") == "MEDIUM" else "danger"
                patterns = (t.get("patterns") or "").replace(",", ", ")
                rows += f'''
                <tr class="hover:bg-blue-50/50 transition border-b border-gray-100">
                  <td class="px-4 py-3 font-semibold text-gray-800">{_e(_ticker(t["ticker"]))}</td>
                  <td class="px-4 py-3">{dir_bdg}</td>
                  <td class="px-4 py-3 text-right font-mono text-gray-700">{_price(t["entry_price"])}</td>
                  <td class="px-4 py-3 text-right"><span class="font-mono text-emerald-600">{_price(t["target_price"])}</span> <span class="text-xs text-gray-400">({_pct(upside)})</span></td>
                  <td class="px-4 py-3 text-right font-mono text-red-600">{_price(t["sl_price"])}</td>
                  <td class="px-4 py-3 text-right font-semibold text-gray-800">{t["rr_ratio"]:.1f}x</td>
                  <td class="px-4 py-3 text-right font-semibold text-gray-800">{t["predicted_win_rate"]:.0f}%</td>
                  <td class="px-4 py-3 text-gray-600 text-xs max-w-[200px] truncate">{_e(patterns)}</td>
                  <td class="px-4 py-3 text-center">{badge(t.get("confidence",""), conf_v)}</td>
                </tr>'''

            tables += f'''
            <div class="glass rounded-xl overflow-hidden mb-4">
              <div class="px-5 py-3 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
                <h3 class="text-sm font-semibold text-gray-800">{_e(hz)}</h3>
                {badge(f'{len(hz_trades)} trades', "default")}
              </div>
              <div class="overflow-x-auto scrollbar-thin">
                <table class="w-full text-sm">
                  <thead><tr class="border-b border-gray-200">
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Stock</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dir</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Entry</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Target</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Stop Loss</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">R:R</th>
                    <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Win Rate</th>
                    <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pattern</th>
                    <th class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Conf</th>
                  </tr></thead>
                  <tbody>{rows}</tbody>
                </table>
              </div>
            </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-4">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Today's Signals</h2>
        <p class="text-sm text-gray-500 mt-1">Signals from {_date(entry_date)} — {len(trades)} total</p>
      </div>
      <a href="/signals" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">Refresh</a>
    </div>
    {summary_badges}
    {tables}'''
    return page_shell("Today's Signals", "signals", body)


def render_positions():
    trades = q_open_trades()
    today_str = date.today().isoformat()

    # Fetch live prices for all open tickers
    tickers_raw = [t["ticker"] for t in trades if t.get("ticker")]
    live_prices = fetch_live_prices(tickers_raw)
    price_ts = datetime.now().strftime("%H:%M")

    cards = ""
    if not trades:
        cards = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No open positions</p>
          <p class="mt-1 text-sm text-gray-400">Trades will appear here after running the engine</p>
        </div>'''
    else:
        for i, t in enumerate(trades):
            days_held = _days_between(t["entry_date"], today_str)
            days_left = max(0, _days_between(today_str, t["expiry_date"]))
            total_days = t.get("horizon_days") or max(1, _days_between(t["entry_date"], t["expiry_date"]))
            pct_done = min(100, int(days_held / total_days * 100)) if total_days > 0 else 0
            upside = ((t["target_price"] - t["entry_price"]) / t["entry_price"] * 100) if t["entry_price"] else 0
            downside = ((t["entry_price"] - t["sl_price"]) / t["entry_price"] * 100) if t["entry_price"] else 0
            dir_cls = "bg-emerald-50 text-emerald-600"
            dir_arrow = "↑"
            bar_color = "bg-amber-500" if days_left <= 1 else "bg-blue-500"
            conf_v = "success" if t.get("confidence") == "HIGH" else "warning" if t.get("confidence") == "MEDIUM" else "danger"
            patterns_display = (t.get("patterns") or "").replace(",", " · ")

            # ---- Live price & P&L computation ----
            cur_price = live_prices.get(t["ticker"])
            entry_p = t["entry_price"] or 0
            target_p = t["target_price"] or 0
            sl_p = t["sl_price"] or 0
            is_bull = t["direction"] == "BULLISH"
            
            # Determine if trade is on-track or off-track (based on target achievement)
            track_status = "on-track" if (cur_price and target_p and cur_price >= target_p) else "off-track"

            if cur_price and entry_p:
                pnl_pct = (cur_price - entry_p) / entry_p * 100
                pnl_sign = "+" if pnl_pct >= 0 else ""
                pnl_color = "text-emerald-600" if pnl_pct >= 0 else "text-red-600"
                pnl_bg = "bg-emerald-50" if pnl_pct >= 0 else "bg-red-50"

                # Distance gauge: where is cur_price between SL and Target?
                if is_bull:
                    total_range = target_p - sl_p if target_p != sl_p else 1
                    position_in_range = (cur_price - sl_p) / total_range * 100
                    dist_to_target = ((target_p - cur_price) / cur_price * 100) if cur_price else 0
                    dist_to_sl = ((cur_price - sl_p) / cur_price * 100) if cur_price else 0
                else:
                    total_range = sl_p - target_p if sl_p != target_p else 1
                    position_in_range = (sl_p - cur_price) / total_range * 100
                    dist_to_target = ((cur_price - target_p) / cur_price * 100) if cur_price else 0
                    dist_to_sl = ((sl_p - cur_price) / cur_price * 100) if cur_price else 0
                position_in_range = max(0, min(100, position_in_range))

                # Gauge bar color based on position
                if position_in_range >= 70:
                    gauge_color = "bg-emerald-500"  # near target
                elif position_in_range >= 30:
                    gauge_color = "bg-amber-400"    # mid-range
                else:
                    gauge_color = "bg-red-500"      # near SL

                live_price_html = f'''
                <div class="rounded-lg {pnl_bg} border border-gray-100 p-3 mb-4">
                  <div class="flex items-center justify-between mb-2">
                    <div>
                      <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Current Price</p>
                      <p class="text-lg font-mono font-bold {pnl_color}">{_price(cur_price)}</p>
                    </div>
                    <div class="text-right">
                      <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Unrealized P&L</p>
                      <p class="text-lg font-bold {pnl_color}">{pnl_sign}{pnl_pct:.2f}%</p>
                    </div>
                  </div>
                  <div class="mb-1">
                    <div class="flex justify-between text-[10px] text-gray-400 mb-1">
                      <span>SL ({_price(sl_p)})</span>
                      <span>Target ({_price(target_p)})</span>
                    </div>
                    <div class="w-full h-2 bg-gray-200 rounded-full overflow-hidden relative">
                      <div class="h-full rounded-full {gauge_color} transition-all" style="width:{position_in_range:.0f}%"></div>
                    </div>
                  </div>
                  <div class="flex justify-between text-[10px] mt-1">
                    <span class="text-red-500">{dist_to_sl:.1f}% to SL</span>
                    <span class="text-emerald-500">{dist_to_target:.1f}% to Target</span>
                  </div>
                </div>'''
            else:
                live_price_html = '''
                <div class="rounded-lg bg-gray-50 border border-dashed border-gray-200 p-3 mb-4 text-center">
                  <p class="text-xs text-gray-400">Live price unavailable</p>
                </div>'''

            hz_label = t.get("horizon_label", "") or ""
            cards += f'''
            <div class="glass rounded-xl p-5 hover:border-blue-300 transition-all position-card relative" data-horizon="{_e(hz_label)}" data-track="{_e(track_status)}" data-expiry="{t.get('expiry_date','')}" data-id="{t['id']}">
              <label class="select-checkbox-wrap hidden absolute top-3 left-3 z-10 cursor-pointer" title="Select">
                <input type="checkbox" class="pos-checkbox w-5 h-5 rounded border-gray-400 text-red-600 focus:ring-red-500 cursor-pointer" data-id="{t['id']}">
              </label>
              <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-3">
                  <div class="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold {dir_cls}">{dir_arrow}</div>
                  <div>
                    <p class="font-bold text-gray-800 text-base">{_e(_ticker(t["ticker"]))}</p>
                    <p class="text-xs text-gray-400">{_e(t.get("sector") or "NSE")} · Entered {_date(t["entry_date"])}</p>
                  </div>
                </div>
                {badge(hz_label, "info")}
              </div>
              {live_price_html}
              <div class="grid grid-cols-3 gap-3 mb-4">
                <div>
                  <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Entry</p>
                  <p class="text-sm font-mono font-semibold text-gray-800">{_price(t["entry_price"])}</p>
                </div>
                <div>
                  <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Target</p>
                  <p class="text-sm font-mono font-semibold text-emerald-600">{_price(t["target_price"])}</p>
                  <p class="text-[10px] text-emerald-500">+{upside:.1f}%</p>
                </div>
                <div>
                  <p class="text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Stop Loss</p>
                  <p class="text-sm font-mono font-semibold text-red-600">{_price(t["sl_price"])}</p>
                  <p class="text-[10px] text-red-500">-{downside:.1f}%</p>
                </div>
              </div>
              <div class="mb-3">
                <div class="flex justify-between text-xs text-gray-400 mb-1.5">
                  <span>Day {days_held} of {total_days}</span>
                  <span class="font-medium text-gray-500">Expires {_date(t["expiry_date"])}</span>
                  <span>{days_left}d left</span>
                </div>
                <div class="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div class="h-full rounded-full {bar_color} transition-all" style="width:{pct_done}%"></div>
                </div>
              </div>
              <div class="flex items-center justify-between pt-3 border-t border-gray-100">
                <span class="text-xs text-gray-500">R:R {t.get("rr_ratio",0):.1f}x</span>
                <span class="text-xs text-gray-500">WR {t.get("predicted_win_rate",0):.0f}%</span>
                {badge(t.get("confidence",""), conf_v)}
              </div>
              <div class="mt-2">
                <p class="text-[10px] text-gray-400 truncate" title="{_e(t.get('patterns',''))}">{_e(patterns_display)}</p>
              </div>
              <form method="POST" action="/trade/cancel?id={t['id']}" onsubmit="return confirm('Cancel this trade and erase all RAG imprints? This cannot be undone.')" class="cancel-trade-form mt-3 pt-3 border-t border-gray-100">
                <button type="submit" class="w-full py-1.5 text-xs font-medium text-red-500 border border-red-200 rounded-lg hover:bg-red-50 transition-all">&#x2715; Cancel Trade &amp; Remove from RAG</button>
              </form>
            </div>'''

    price_note = f'<span class="text-xs text-gray-400 ml-2">Prices as of {price_ts}</span>' if live_prices else ''

    # Build horizon filter buttons from actual data
    horizon_counts = {}
    track_counts = {"on-track": 0, "off-track": 0}
    for t in trades:
        hz = t.get("horizon_label", "") or ""
        horizon_counts[hz] = horizon_counts.get(hz, 0) + 1
        
        # Count on-track vs off-track
        cur_price = live_prices.get(t["ticker"])
        target_p = t.get("target_price") or 0
        is_on_track = cur_price and target_p and cur_price >= target_p
        track_status = "on-track" if is_on_track else "off-track"
        track_counts[track_status] += 1

    # Sort horizons by horizon_days
    hz_order = sorted(horizon_counts.keys(), key=lambda h: next((t.get("horizon_days", 0) for t in trades if (t.get("horizon_label") or "") == h), 0))

    hz_buttons = ''
    for hz in hz_order:
        cnt = horizon_counts[hz]
        hz_buttons += f'<button onclick="filterPositions(this, \'{_e(hz)}\')" class="hz-filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-200 bg-white text-gray-600 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700 transition-all" data-hz="{_e(hz)}">{_e(hz)} <span class="text-gray-400 ml-1">({cnt})</span></button>'

    on_track_cnt = track_counts.get("on-track", 0)
    off_track_cnt = track_counts.get("off-track", 0)

    # Collect unique expiry dates with counts, sorted chronologically
    expiry_counts = {}
    for t in trades:
        ed = t.get("expiry_date", "")
        if ed:
            expiry_counts[ed] = expiry_counts.get(ed, 0) + 1
    expiry_order = sorted(expiry_counts.keys())
    expiry_buttons = ''
    for ed in expiry_order:
        cnt = expiry_counts[ed]
        # Color-code: today = red/urgent, tomorrow = amber, rest = default
        is_today = (ed == today_str)
        is_tomorrow = False
        try:
            from datetime import timedelta
            is_tomorrow = (ed == (date.today() + timedelta(days=1)).isoformat())
        except Exception:
            pass
        if is_today:
            exp_cls = "border-red-300 bg-red-50 text-red-600 hover:bg-red-100"
        elif is_tomorrow:
            exp_cls = "border-amber-300 bg-amber-50 text-amber-600 hover:bg-amber-100"
        else:
            exp_cls = "border-gray-200 bg-white text-gray-600 hover:bg-blue-50 hover:border-blue-300 hover:text-blue-700"
        expiry_buttons += f'<button onclick="filterByExpiry(this, \'{ed}\')" class="exp-filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border {exp_cls} transition-all" data-exp="{ed}">{_date(ed)}{" ⚠️" if is_today else ""} <span class="opacity-60 ml-1">({cnt})</span></button>'

    filter_bar = f'''
    <div class="glass rounded-xl p-4 mb-5 space-y-2">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-1 w-16">Horizon:</span>
        <button onclick="filterPositions(this, 'ALL')" class="hz-filter-btn active-filter px-3 py-1.5 rounded-lg text-xs font-medium border border-blue-300 bg-blue-50 text-blue-700 transition-all" data-hz="ALL">All <span class="text-blue-400 ml-1">({len(trades)})</span></button>
        {hz_buttons}
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-1 w-16">Status:</span>
        <button onclick="filterByTrack(this, 'ALL')" class="track-filter-btn active-track-filter px-3 py-1.5 rounded-lg text-xs font-medium border border-blue-300 bg-blue-50 text-blue-700 transition-all" data-track="ALL">All <span class="text-blue-400 ml-1">({len(trades)})</span></button>
        <button onclick="filterByTrack(this, 'on-track')" class="track-filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-200 bg-white text-emerald-600 hover:bg-emerald-50 hover:border-emerald-300 transition-all" data-track="on-track">✓ On Track ({on_track_cnt})</button>
        <button onclick="filterByTrack(this, 'off-track')" class="track-filter-btn px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-200 bg-white text-amber-600 hover:bg-amber-50 hover:border-amber-300 transition-all" data-track="off-track">⚠ Off Track ({off_track_cnt})</button>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-1 w-16">Expiry:</span>
        <button onclick="filterByExpiry(this, 'ALL')" class="exp-filter-btn active-exp-filter px-3 py-1.5 rounded-lg text-xs font-medium border border-blue-300 bg-blue-50 text-blue-700 transition-all" data-exp="ALL">All</button>
        {expiry_buttons}
      </div>
      <p class="text-[10px] text-gray-400 mt-2" id="filter-summary">Showing all {len(trades)} positions</p>
    </div>''' if trades else ''

    filter_js = '''
    <script>
    (function() {
      var activeHz = 'ALL', activeTrack = 'ALL', activeExp = 'ALL';

      function applyFilters() {
        var cards = document.querySelectorAll('.position-card');
        var shown = 0;
        cards.forEach(function(card) {
          var hz = card.getAttribute('data-horizon');
          var track = card.getAttribute('data-track');
          var exp = card.getAttribute('data-expiry');
          var hzMatch = (activeHz === 'ALL' || hz === activeHz);
          var trackMatch = (activeTrack === 'ALL' || track === activeTrack);
          var expMatch = (activeExp === 'ALL' || exp === activeExp);
          if (hzMatch && trackMatch && expMatch) {
            card.style.display = '';
            shown++;
          } else {
            card.style.display = 'none';
          }
        });
        var summary = document.getElementById('filter-summary');
        if (summary) {
          var parts = [];
          if (activeHz !== 'ALL') parts.push(activeHz);
          if (activeTrack !== 'ALL') parts.push(activeTrack === 'on-track' ? 'On Track' : 'Off Track');
          if (activeExp !== 'ALL') parts.push('expiry ' + activeExp);
          var label = parts.length ? parts.join(' + ') : 'all';
          summary.textContent = 'Showing ' + shown + ' of ' + cards.length + ' positions' + (parts.length ? ' \u2014 ' + label : '');
        }
      }

      window.filterPositions = function(btn, hz) {
        activeHz = hz;
        document.querySelectorAll('.hz-filter-btn').forEach(function(b) {
          b.classList.remove('active-filter', 'bg-blue-50', 'border-blue-300', 'text-blue-700');
          b.classList.add('bg-white', 'text-gray-600', 'border-gray-200');
        });
        btn.classList.add('active-filter', 'bg-blue-50', 'border-blue-300', 'text-blue-700');
        btn.classList.remove('bg-white', 'text-gray-600', 'border-gray-200');
        applyFilters();
      };

      window.filterByTrack = function(btn, track) {
        activeTrack = track;
        document.querySelectorAll('.track-filter-btn').forEach(function(b) {
          b.classList.remove('active-track-filter', 'bg-blue-50', 'border-blue-300', 'text-blue-700');
          b.classList.add('bg-white', 'border-gray-200');
        });
        btn.classList.add('active-track-filter', 'bg-blue-50', 'border-blue-300', 'text-blue-700');
        btn.classList.remove('bg-white', 'border-gray-200');
        applyFilters();
      };

      window.filterByExpiry = function(btn, exp) {
        activeExp = exp;
        document.querySelectorAll('.exp-filter-btn').forEach(function(b) {
          b.classList.remove('active-exp-filter', 'bg-blue-50', 'border-blue-300', 'text-blue-700');
          if (!b.classList.contains('bg-red-50') && !b.classList.contains('bg-amber-50')) {
            b.classList.add('bg-white', 'border-gray-200');
          }
        });
        btn.classList.add('active-exp-filter', 'bg-blue-50', 'border-blue-300', 'text-blue-700');
        btn.classList.remove('bg-white', 'border-gray-200', 'bg-red-50', 'border-red-300', 'bg-amber-50', 'border-amber-300');
        applyFilters();
      };
    })();
    </script>'''

    bulk_bar = '''
    <div id="bulk-cancel-bar" class="hidden fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-5 py-3 bg-white border border-gray-200 rounded-2xl shadow-2xl">
      <span id="bulk-count" class="text-sm font-medium text-gray-700">0 selected</span>
      <button onclick="selectAllVisible()" class="px-3 py-2 rounded-lg bg-gray-100 text-gray-700 text-sm hover:bg-gray-200 transition font-medium">Select All Visible</button>
      <button onclick="cancelSelected()" class="px-4 py-2 rounded-lg bg-red-500 text-white text-sm font-semibold hover:bg-red-600 transition">&#x2715; Cancel Selected</button>
      <button onclick="toggleSelectMode()" class="px-3 py-2 rounded-lg bg-gray-100 text-gray-500 text-sm hover:bg-gray-200 transition">Exit Select</button>
    </div>'''

    multiselect_js = '''
    <script>
    (function() {
      var selectMode = false;
      window.toggleSelectMode = function() {
        selectMode = !selectMode;
        var btn = document.getElementById('select-mode-btn');
        var checkboxWraps = document.querySelectorAll('.select-checkbox-wrap');
        var cancelForms = document.querySelectorAll('.cancel-trade-form');
        var bar = document.getElementById('bulk-cancel-bar');
        if (selectMode) {
          btn.innerHTML = '&#x2715; Exit Select';
          btn.classList.add('bg-blue-50', 'border-blue-300', 'text-blue-700');
          btn.classList.remove('text-gray-600');
          checkboxWraps.forEach(function(w) { w.classList.remove('hidden'); });
          cancelForms.forEach(function(f) { f.classList.add('hidden'); });
          bar.classList.remove('hidden');
        } else {
          btn.innerHTML = '&#x2611; Select';
          btn.classList.remove('bg-blue-50', 'border-blue-300', 'text-blue-700');
          btn.classList.add('text-gray-600');
          checkboxWraps.forEach(function(w) {
            w.classList.add('hidden');
            w.querySelector('input').checked = false;
          });
          cancelForms.forEach(function(f) { f.classList.remove('hidden'); });
          bar.classList.add('hidden');
          updateBulkCount();
        }
      };
      window.updateBulkCount = function() {
        var checked = document.querySelectorAll('.pos-checkbox:checked');
        document.getElementById('bulk-count').textContent = checked.length + ' selected';
      };
      window.selectAllVisible = function() {
        document.querySelectorAll('.position-card').forEach(function(card) {
          if (card.style.display !== 'none') {
            var cb = card.querySelector('.pos-checkbox');
            if (cb) cb.checked = true;
          }
        });
        updateBulkCount();
      };
      window.cancelSelected = function() {
        var checked = document.querySelectorAll('.pos-checkbox:checked');
        if (!checked.length) { alert('No trades selected.'); return; }
        if (!confirm('Cancel ' + checked.length + ' selected trade(s) and remove their RAG imprints? This cannot be undone.')) return;
        var ids = Array.from(checked).map(function(cb) { return cb.getAttribute('data-id'); }).join(',');
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/trade/cancel-bulk';
        var inp = document.createElement('input');
        inp.type = 'hidden'; inp.name = 'ids'; inp.value = ids;
        form.appendChild(inp);
        document.body.appendChild(form);
        form.submit();
      };
      document.addEventListener('change', function(e) {
        if (e.target && e.target.classList.contains('pos-checkbox')) {
          updateBulkCount();
        }
      });
    })();
    </script>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Open Positions</h2>
        <p class="text-sm text-gray-500 mt-1">{len(trades)} active trades {price_note}</p>
      </div>
      <div class="flex items-center gap-2">
        <button id="select-mode-btn" onclick="toggleSelectMode()" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-blue-50 hover:border-blue-300 text-gray-600 text-sm transition shadow-sm">&#x2611; Select</button>
        <a href="/positions" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          Refresh Prices
        </a>
      </div>
    </div>
    {filter_bar}
    <div class="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4" id="positions-grid">
      {cards}
    </div>
    {filter_js}
    {bulk_bar}
    {multiselect_js}'''
    return page_shell("Open Positions", "positions", body)


def render_history():
    trades = q_closed_trades()

    wins = sum(1 for t in trades if t["status"] in ("WON", "EXPIRED_WIN"))
    losses = sum(1 for t in trades if t["status"] in ("LOST", "EXPIRED_LOSS"))
    wr = (wins / len(trades) * 100) if trades else 0

    summary = f'''
    <div class="grid grid-cols-4 gap-4 mb-6">
      {stat_card("Total", len(trades), "", "indigo")}
      {stat_card("Wins", wins, "", "green")}
      {stat_card("Losses", losses, "", "red")}
      {stat_card("Win Rate", f"{wr:.1f}%", "", "green" if wr >= 55 else "amber")}
    </div>'''

    if not trades:
        table = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No closed trades yet</p>
          <p class="mt-1 text-sm text-gray-400">Trades will appear here once they hit SL, target, or expire</p>
        </div>'''
    else:
        rows = ""
        for t in trades:
            ret = t.get("actual_return_pct", 0) or 0
            ret_cls = "text-emerald-600" if ret >= 0 else "text-red-600"
            dir_bdg = badge(t["direction"][0] if t.get("direction") else "?", "bullish")
            rows += f'''
            <tr class="hover:bg-blue-50/50 transition border-b border-gray-100">
              <td class="px-4 py-3">{status_badge(t["status"])}</td>
              <td class="px-4 py-3 font-semibold text-gray-800">{_e(_ticker(t["ticker"]))}</td>
              <td class="px-4 py-3 text-gray-600">{_e(t.get("horizon_label",""))}</td>
              <td class="px-4 py-3">{dir_bdg}</td>
              <td class="px-4 py-3 text-right font-mono text-gray-600">{_price(t["entry_price"])}</td>
              <td class="px-4 py-3 text-right font-mono text-gray-600">{_price(t.get("exit_price"))}</td>
              <td class="px-4 py-3 text-right font-mono font-semibold {ret_cls}">{_pct(ret)}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{_e(t.get("exit_reason",""))}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{_date(t["entry_date"])}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{_date(t.get("exit_date"))}</td>
              <td class="px-4 py-3 text-xs text-gray-500 max-w-[150px] truncate">{_e(t.get("patterns",""))}</td>
            </tr>'''

        table = f'''
        <div class="glass rounded-xl overflow-hidden">
          <div class="overflow-x-auto scrollbar-thin">
            <table class="w-full text-sm">
              <thead><tr class="border-b border-gray-200">
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Stock</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Horizon</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Dir</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Entry</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Exit</th>
                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Return</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Reason</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entry</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Exit</th>
                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Pattern</th>
              </tr></thead>
              <tbody>{rows}</tbody>
            </table>
          </div>
        </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Trade History</h2>
        <p class="text-sm text-gray-500 mt-1">{len(trades)} closed trades</p>
      </div>
      <a href="/history" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 text-sm transition shadow-sm">Refresh</a>
    </div>
    {summary}
    {table}'''
    return page_shell("Trade History", "history", body)


def render_performance():
    s = q_stats()
    hz_stats = q_stats_by_horizon()
    pat_stats = q_stats_by_pattern()
    stock_stats = q_stats_by_stock()

    kpis = f'''
    <div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
      {stat_card("Total Trades", s["total_trades"], "", "indigo")}
      {stat_card("Win Rate", f'{s["win_rate"]}%', "", "green" if s["win_rate"] >= 55 else "amber")}
      {stat_card("Profit Factor", s["profit_factor"], "", "green" if s["profit_factor"] >= 1.5 else "amber")}
      {stat_card("Avg Win", _pct(s["avg_win_pct"]), "", "green")}
      {stat_card("Avg Loss", _pct(s["avg_loss_pct"]), "", "red")}
    </div>'''

    # Horizon table
    hz_html = ""
    if hz_stats:
        hz_rows = ""
        for h in hz_stats:
            hz_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 font-medium text-gray-800">{_e(h.get("horizon_label",""))}</td>
              <td class="px-4 py-2 text-right text-gray-600">{h["total"]}</td>
              <td class="px-4 py-2 text-right text-emerald-600">{h["wins"]}</td>
              <td class="px-4 py-2 text-right text-red-600">{h["losses"]}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{h["win_rate"]}%</td>
              <td class="px-4 py-2 text-right text-emerald-600">{_pct(h.get("avg_win"))}</td>
              <td class="px-4 py-2 text-right text-red-600">{_pct(h.get("avg_loss"))}</td>
            </tr>'''
        hz_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Performance by Horizon</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Horizon</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Wins</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Losses</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Win Rate</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Win</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Loss</th>
          </tr></thead><tbody>{hz_rows}</tbody></table>
        </div>'''

    # Pattern table
    pat_html = ""
    if pat_stats:
        pat_rows = ""
        for p in pat_stats:
            ret_cls = "text-emerald-600" if (p.get("avg_ret") or 0) >= 0 else "text-red-600"
            pat_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-gray-800 text-xs">{_e((p.get("patterns","") or "").replace(",", " · "))}</td>
              <td class="px-4 py-2 text-right text-gray-600">{p["total"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{p["wins"]} / {p["losses"]}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{p["win_rate"]}%</td>
              <td class="px-4 py-2 text-right font-mono {ret_cls}">{_pct(p.get("avg_ret"))}</td>
            </tr>'''
        pat_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Performance by Pattern</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Pattern</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">W / L</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Win Rate</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
          </tr></thead><tbody>{pat_rows}</tbody></table>
        </div>'''

    # Stock table
    stk_html = ""
    if stock_stats:
        stk_rows = ""
        for st in stock_stats:
            avg_cls = "text-emerald-600" if (st.get("avg_ret") or 0) >= 0 else "text-red-600"
            tot_cls = "text-emerald-600" if (st.get("total_ret") or 0) >= 0 else "text-red-600"
            stk_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 font-semibold text-gray-800">{_e(_ticker(st["ticker"]))}</td>
              <td class="px-4 py-2 text-right text-gray-600">{st["total"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{st["wins"]} / {st["losses"]}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{st["win_rate"]}%</td>
              <td class="px-4 py-2 text-right font-mono {avg_cls}">{_pct(st.get("avg_ret"))}</td>
              <td class="px-4 py-2 text-right font-mono font-semibold {tot_cls}">{_pct(st.get("total_ret"))}</td>
            </tr>'''
        stk_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Performance by Stock</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Stock</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">W / L</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Win Rate</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Total Return</th>
          </tr></thead><tbody>{stk_rows}</tbody></table>
        </div>'''

    empty = ""
    if s["closed_trades"] == 0:
        empty = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-600">No performance data yet</p>
          <p class="mt-1 text-sm text-gray-400">Analytics will appear once trades are closed</p>
        </div>'''

    body = f'''
    <h2 class="text-2xl font-bold text-gray-800 mb-6">Performance Analytics</h2>
    {kpis}
    {hz_html}
    {pat_html}
    {stk_html}
    {empty}'''
    return page_shell("Performance", "performance", body)


def _render_index_card(label, ticker, size="normal"):
    """Render a single index card. size='normal' for broad indices, 'compact' for sector."""
    try:
        data = yf.download(ticker, period="5d", progress=False, interval="1d")

        if data.empty or len(data) < 2:
            return f'''
            <div class="glass rounded-xl p-{'6' if size == 'normal' else '4'}">
              <div class="text-sm font-medium text-gray-500 uppercase tracking-wide">{_e(label)}</div>
              <div class="mt-2 text-gray-400 text-xs">No data available</div>
            </div>'''

        close_col = data["Close"]
        # Flatten MultiIndex columns from yfinance if present
        if hasattr(close_col, 'columns'):
            close_col = close_col.iloc[:, 0]
        prev_close = float(close_col.iloc[-2])
        current = float(close_col.iloc[-1])
        pct_change = ((current - prev_close) / prev_close) * 100

        if pct_change >= 0:
            color_class = "text-emerald-600"
            badge_cls = "bg-emerald-50 text-emerald-700 border-emerald-200"
            arrow = "&#9650;"  # ▲
        else:
            color_class = "text-red-600"
            badge_cls = "bg-red-50 text-red-700 border-red-200"
            arrow = "&#9660;"  # ▼

        if size == "normal":
            return f'''
            <div class="glass rounded-xl p-6">
              <div class="text-sm font-medium text-gray-500 uppercase tracking-wide">{_e(label)}</div>
              <div class="mt-4 flex items-end gap-4">
                <div>
                  <div class="text-3xl font-bold text-gray-800">{current:,.2f}</div>
                  <div class="text-xs text-gray-400 mt-1">Current Value</div>
                </div>
                <div class="ml-auto text-right">
                  <div class="{color_class} text-2xl font-bold flex items-center gap-1 justify-end">
                    {arrow} {abs(pct_change):.2f}%
                  </div>
                  <div class="text-xs text-gray-400 mt-1">Today's Change</div>
                </div>
              </div>
              <div class="mt-4 pt-4 border-t border-gray-100">
                <div class="text-xs text-gray-500">Prev Close: <span class="font-medium text-gray-700">{prev_close:,.2f}</span></div>
              </div>
            </div>'''
        else:
            # Compact card for sector indices
            return f'''
            <div class="glass rounded-xl p-4 flex flex-col gap-2">
              <div class="flex items-center justify-between">
                <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide">{_e(label)}</div>
                <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold border {badge_cls}">
                  {arrow} {abs(pct_change):.2f}%
                </span>
              </div>
              <div class="flex items-end justify-between">
                <div class="text-xl font-bold text-gray-800">{current:,.2f}</div>
                <div class="text-[10px] text-gray-400">Prev: {prev_close:,.2f}</div>
              </div>
            </div>'''

    except Exception as e:
        return f'''
        <div class="glass rounded-xl p-{'6' if size == 'normal' else '4'}">
          <div class="text-sm font-medium text-gray-500 uppercase tracking-wide">{_e(label)}</div>
          <div class="mt-2 text-red-600 text-xs">Error: {_e(str(e)[:60])}</div>
        </div>'''


def render_market_indices():
    """Render market indices dashboard showing broad-market and sector proxy indices."""
    try:
        if not _HAS_YF:
            return page_shell("Market Indices", "market",
                '''<div class="flex flex-col items-center justify-center py-16 text-center">
                  <p class="text-lg font-medium text-gray-600">yfinance module not available</p>
                  <p class="mt-1 text-sm text-gray-400">Please install yfinance to view market data</p>
                </div>''')

        # ---- Section 1: Broad Market Indices ----
        broad_indices = [
            ("NIFTY 50",           "^NSEI"),
            ("NIFTY Next 50",      "^NSMIDCP"),
            ("NIFTY Bank",         "^NSEBANK"),
        ]

        broad_cards = ""
        for label, ticker in broad_indices:
            broad_cards += _render_index_card(label, ticker, size="normal")

        # ---- Section 2: Sector Proxy Indices (from position_risk_monitor) ----
        sector_indices = [
            ("NIFTY Bank",    "^NSEBANK",    "Banking &amp; Finance"),
            ("NIFTY IT",      "^CNXIT",      "Information Technology"),
            ("NIFTY Auto",    "^CNXAUTO",    "Automobile"),
            ("NIFTY Pharma",  "^CNXPHARMA",  "Pharmaceuticals"),
            ("NIFTY Metal",   "^CNXMETAL",   "Metals &amp; Mining"),
            ("NIFTY FMCG",    "^CNXFMCG",    "Fast-Moving Consumer Goods"),
            ("NIFTY Energy",  "^CNXENERGY",  "Energy &amp; Oil/Gas"),
            ("NIFTY Realty",  "^CNXREALTY",   "Real Estate"),
            ("NIFTY Infra",   "^CNXINFRA",   "Infrastructure"),
        ]

        sector_cards = ""
        for label, ticker, _desc in sector_indices:
            sector_cards += _render_index_card(label, ticker, size="compact")

        # ---- Section 3: Sector–Index mapping reference ----
        mapping_rows = ""
        sector_map_display = [
            ("Banking",        "^NSEBANK",   "NIFTY Bank"),
            ("Finance",        "^NSEBANK",   "NIFTY Bank"),
            ("IT",             "^CNXIT",     "NIFTY IT"),
            ("Auto",           "^CNXAUTO",   "NIFTY Auto"),
            ("Pharma",         "^CNXPHARMA", "NIFTY Pharma"),
            ("Metals",         "^CNXMETAL",  "NIFTY Metal"),
            ("FMCG",           "^CNXFMCG",   "NIFTY FMCG"),
            ("Energy",         "^CNXENERGY", "NIFTY Energy"),
            ("Realty",         "^CNXREALTY",  "NIFTY Realty"),
            ("Infra",          "^CNXINFRA",  "NIFTY Infra"),
            ("Conglomerate",   "^NSEI",      "NIFTY 50 (fallback)"),
            ("Cement",         "^NSEI",      "NIFTY 50 (fallback)"),
            ("Telecom",        "^NSEI",      "NIFTY 50 (fallback)"),
            ("Media",          "^NSEI",      "NIFTY 50 (fallback)"),
            ("Chemicals",      "^NSEI",      "NIFTY 50 (fallback)"),
            ("Consumer",       "^NSEI",      "NIFTY 50 (fallback)"),
            ("Industrial",     "^NSEI",      "NIFTY 50 (fallback)"),
            ("Logistics",      "^NSEI",      "NIFTY 50 (fallback)"),
        ]
        for sector, ticker, idx_name in sector_map_display:
            fallback = "fallback" in idx_name
            tag_cls = "bg-gray-100 text-gray-500" if fallback else "bg-blue-50 text-blue-700"
            mapping_rows += f'''
              <tr class="border-b border-gray-50 hover:bg-gray-50/50">
                <td class="px-4 py-2 text-sm font-medium text-gray-700">{sector}</td>
                <td class="px-4 py-2 font-mono text-xs text-gray-500">{ticker}</td>
                <td class="px-4 py-2 text-sm">
                  <span class="inline-block px-2 py-0.5 rounded text-xs font-medium {tag_cls}">{idx_name}</span>
                </td>
              </tr>'''

        body = f'''
        <h2 class="text-2xl font-bold text-gray-800 mb-6">Market Indices</h2>

        <!-- Broad Market -->
        <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
          {broad_cards}
        </div>

        <!-- Sector Indices -->
        <div class="mt-10">
          <h3 class="text-lg font-semibold text-gray-800 mb-1">Sector Indices</h3>
          <p class="text-xs text-gray-400 mb-4">Proxy tickers used by Position Risk Monitor for sector momentum checks</p>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {sector_cards}
          </div>
        </div>

        <!-- Sector → Index Mapping -->
        <div class="mt-10 glass rounded-xl p-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Sector &rarr; Proxy Index Mapping</h3>
          <p class="text-xs text-gray-400 mb-3">Used by <span class="font-mono">position_risk_monitor.py</span> to calculate sector momentum penalties. Sectors without a dedicated index fall back to NIFTY 50.</p>
          <div class="overflow-x-auto">
            <table class="min-w-full text-left">
              <thead>
                <tr class="border-b border-gray-200">
                  <th class="px-4 py-2 text-xs font-semibold text-gray-500 uppercase">Sector</th>
                  <th class="px-4 py-2 text-xs font-semibold text-gray-500 uppercase">Ticker</th>
                  <th class="px-4 py-2 text-xs font-semibold text-gray-500 uppercase">Index Name</th>
                </tr>
              </thead>
              <tbody>
                {mapping_rows}
              </tbody>
            </table>
          </div>
        </div>

        <!-- Info Footer -->
        <div class="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-100">
          <p class="text-xs text-blue-800">
            Last updated at market close. Data sourced from YFinance.
            Sector indices are used by the Tier-1 Position Risk Monitor to detect regime shifts and sector momentum divergence.
          </p>
        </div>'''

        return page_shell("Market Indices", "market", body)

    except Exception as e:
        body = f'''
        <div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-red-600">Error loading market indices</p>
          <p class="mt-2 text-sm text-gray-500 font-mono">{_e(str(e))}</p>
        </div>'''
        return page_shell("Market Indices", "market", body)


# ============================================================
# FEEDBACK LOOP PAGE
# ============================================================
FEEDBACK_FILE = os.path.join("feedback", "feedback_log.json")
LEARNING_FILE = os.path.join("feedback", "learned_rules.json")


def _load_feedback_log():
    """Load feedback log entries."""
    try:
        with open(FEEDBACK_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _load_learned_rules():
    """Load learned rules / adjustments."""
    try:
        with open(LEARNING_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _feedback_csv_bytes():
    """Generate CSV bytes from feedback log for download."""
    entries = _load_feedback_log()
    if not entries:
        return b"No feedback data available"
    # Column order
    cols = [
        "trade_id", "ticker", "sector", "direction", "patterns", "horizon_label",
        "horizon_days", "predicted_win_rate", "predicted_pf", "confidence",
        "outcome", "actual_return_pct", "exit_reason", "notes", "timestamp", "source",
    ]
    indicator_cols = ["ema_9", "ema_21", "ema_50", "rsi_14", "atr_14", "vol_ratio",
                      "price_vs_vwap", "trend_short", "rsi_zone"]
    import io, csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols + indicator_cols)
    for e in entries:
        row = []
        for c in cols:
            v = e.get(c, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            row.append(v)
        ind = e.get("indicators_at_entry", {})
        for ic in indicator_cols:
            row.append(ind.get(ic, ""))
        w.writerow(row)
    return buf.getvalue().encode("utf-8")


def _get_shadow_trade_stats():
    """Compute shadow trade validation statistics."""
    db = get_db()
    
    # Shadow trade stats
    sh_total = db.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
    sh_closed = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status NOT IN ('SHADOW_OPEN')").fetchone()[0]
    sh_wins = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status IN ('SHADOW_WON','SHADOW_EXPIRED_WIN')").fetchone()[0]
    sh_losses = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status IN ('SHADOW_LOST','SHADOW_EXPIRED_LOSS')").fetchone()[0]
    
    # Real trade stats
    real_total = db.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')").fetchone()[0]
    real_wins = db.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0]
    real_losses = db.execute("SELECT COUNT(*) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0]
    
    # Win rates
    sh_wr = (sh_wins / sh_closed * 100) if sh_closed > 0 else 0
    real_wr = (real_wins / real_total * 100) if real_total > 0 else 0
    gap = real_wr - sh_wr  # positive = real outperforms shadow
    
    # Per-horizon comparison
    horizon_comp = []
    horizons = ['BTST_1d', 'Swing_3d', 'Swing_5d', 'Swing_10d']
    for hz in horizons:
        sh_hz = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status!='SHADOW_OPEN' AND horizon_label=?", (hz,)).fetchone()[0]
        sh_hz_wins = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status IN ('SHADOW_WON','SHADOW_EXPIRED_WIN') AND horizon_label=?", (hz,)).fetchone()[0]
        
        real_hz = db.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED') AND horizon_label=?", (hz,)).fetchone()[0]
        real_hz_wins = db.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN') AND horizon_label=?", (hz,)).fetchone()[0]
        
        sh_hz_wr = (sh_hz_wins / sh_hz * 100) if sh_hz > 0 else None
        real_hz_wr = (real_hz_wins / real_hz * 100) if real_hz > 0 else None
        
        horizon_comp.append({
            'horizon': hz,
            'shadow_count': sh_hz,
            'shadow_wr': sh_hz_wr,
            'real_count': real_hz,
            'real_wr': real_hz_wr,
        })
    
    # Pattern comparison
    pattern_comp = []
    patterns_in_shadow = db.execute("SELECT DISTINCT patterns FROM shadow_trades WHERE status!='SHADOW_OPEN'").fetchall()
    
    for row in patterns_in_shadow[:10]:  # Top 10 patterns
        pat = row[0] if isinstance(row[0], str) else (row[0][0] if row[0] else '')
        if not pat:
            continue
        
        sh_pat = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status!='SHADOW_OPEN' AND patterns LIKE ?", (f'%{pat}%',)).fetchone()[0]
        sh_pat_wins = db.execute("SELECT COUNT(*) FROM shadow_trades WHERE status IN ('SHADOW_WON','SHADOW_EXPIRED_WIN') AND patterns LIKE ?", (f'%{pat}%',)).fetchone()[0]
        
        real_pat = db.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED') AND patterns LIKE ?", (f'%{pat}%',)).fetchone()[0]
        real_pat_wins = db.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN') AND patterns LIKE ?", (f'%{pat}%',)).fetchone()[0]
        
        sh_pat_wr = (sh_pat_wins / sh_pat * 100) if sh_pat > 0 else None
        real_pat_wr = (real_pat_wins / real_pat * 100) if real_pat > 0 else None
        
        if sh_pat > 0 or real_pat > 0:
            pattern_comp.append({
                'pattern': pat,
                'shadow_wr': sh_pat_wr,
                'real_wr': real_pat_wr,
            })
    
    db.close()
    
    return {
        'shadow_total': sh_total,
        'shadow_closed': sh_closed,
        'shadow_wins': sh_wins,
        'shadow_losses': sh_losses,
        'shadow_wr': sh_wr,
        'real_total': real_total,
        'real_wins': real_wins,
        'real_losses': real_losses,
        'real_wr': real_wr,
        'gap': gap,  # positive = filtering working
        'efficiency': (real_wr / sh_wr) if sh_wr > 0 else 0,
        'horizon_comp': horizon_comp,
        'pattern_comp': pattern_comp,
    }


def render_feedback():
    """Render the Feedback Loop page — RAG learning visibility."""
    entries = _load_feedback_log()
    rules = _load_learned_rules()
    shadow_stats = _get_shadow_trade_stats()

    # ---- Summary stats ----
    total_entries = len(entries)
    updated_at = rules.get("updated_at", "—")
    if updated_at and updated_at != "—":
        try:
            updated_at = datetime.fromisoformat(updated_at).strftime("%d %b %Y %H:%M")
        except Exception:
            pass

    pat_adj = rules.get("pattern_adjustments", {})
    regime_adj = rules.get("regime_adjustments", {})
    horizon_adj = rules.get("horizon_adjustments", {})
    triple_adj = rules.get("triple_adjustments", {})
    sector_adj = rules.get("sector_adjustments", {})

    filter_pen = rules.get("filter_penalties", {})
    filter_bst = rules.get("filter_boosts", {})
    hz_pen = rules.get("horizon_filter_penalties", {})
    hz_bst = rules.get("horizon_filter_boosts", {})
    sec_pen = rules.get("sector_filter_penalties", {})
    sec_bst = rules.get("sector_filter_boosts", {})
    active_rules = rules.get("rules", [])

    # Build set of penalized/boosted patterns
    penalized_patterns = set(filter_pen.keys()) | set(hz_pen.keys()) | set(sec_pen.keys())
    boosted_patterns = set(filter_bst.keys()) | set(hz_bst.keys()) | set(sec_bst.keys())

    # Outcome counts
    wins = sum(1 for e in entries if e.get("outcome") == "win")
    losses = sum(1 for e in entries if e.get("outcome") == "loss")
    fb_wr = f"{wins/total_entries*100:.1f}" if total_entries else "0"

    cards = f'''
    <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-4 mb-6">
      {stat_card("Feedback Entries", total_entries, f"W: {wins} / L: {losses}", "indigo")}
      {stat_card("Feedback Win Rate", f"{fb_wr}%", "", "green" if float(fb_wr) >= 50 else "red")}
      {stat_card("Patterns Tracked", len(pat_adj), f"{len(penalized_patterns)} penalized · {len(boosted_patterns)} boosted", "amber")}
      {stat_card("Regime Rules", len(regime_adj), "", "cyan")}
      {stat_card("Learned Rules", len(active_rules), f"Updated: {_e(updated_at)}", "green")}
      {stat_card("Cross-Dim Keys", f"{len(triple_adj)} + {len(sector_adj)}", "triple + sector", "indigo")}
    </div>'''

    # ---- Shadow Trade Validation Section ----
    sh = shadow_stats
    sh_quality = "✓ Working" if sh['gap'] >= 10 else ("⚠ Moderate" if sh['gap'] >= 5 else "⚠ Weak")
    sh_quality_color = "emerald" if sh['gap'] >= 10 else ("amber" if sh['gap'] >= 5 else "red")
    gap_color = "emerald" if sh['gap'] > 0 else "red"
    gap_msg = "✓ Filters are working as intended." if sh['gap'] >= 10 else ("⚠ Monitor filter effectiveness." if sh['gap'] >= 5 else "⚠ Consider loosening filters.")
    
    # Horizon comparison rows
    hz_rows = ""
    for hz_data in sh['horizon_comp']:
        hz = hz_data['horizon']
        sh_wr = hz_data['shadow_wr']
        real_wr = hz_data['real_wr']
        
        if sh_wr is not None and real_wr is not None:
            sh_cls = "text-emerald-600" if sh_wr >= 50 else "text-red-600"
            real_cls = "text-emerald-600" if real_wr >= 50 else "text-red-600"
            gap_val = real_wr - sh_wr
            gap_cls = "text-emerald-600" if gap_val > 0 else "text-red-600"
            hz_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-xs font-medium text-gray-800">{_e(hz)}</td>
              <td class="px-4 py-2 text-right text-xs font-mono {sh_cls}">{sh_wr:.1f}%</td>
              <td class="px-4 py-2 text-right text-xs text-gray-600">{hz_data['shadow_count']}</td>
              <td class="px-4 py-2 text-right text-xs font-mono {real_cls}">{real_wr:.1f}%</td>
              <td class="px-4 py-2 text-right text-xs text-gray-600">{hz_data['real_count']}</td>
              <td class="px-4 py-2 text-right text-xs font-mono {gap_cls}">{gap_val:+.1f}pp</td>
            </tr>'''
        elif sh_wr is not None:
            sh_cls = "text-emerald-600" if sh_wr >= 50 else "text-red-600"
            hz_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-xs font-medium text-gray-800">{_e(hz)}</td>
              <td class="px-4 py-2 text-right text-xs font-mono {sh_cls}">{sh_wr:.1f}%</td>
              <td class="px-4 py-2 text-right text-xs text-gray-600">{hz_data['shadow_count']}</td>
              <td class="px-4 py-2 text-right text-xs text-gray-400">—</td>
              <td class="px-4 py-2 text-right text-xs text-gray-600">0</td>
              <td class="px-4 py-2 text-right text-xs text-gray-400">N/A</td>
            </tr>'''
    
    shadow_section = f'''
    <div class="glass rounded-xl p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h3 class="text-lg font-semibold text-gray-800">Shadow Trade Validation</h3>
          <p class="text-xs text-gray-500 mt-1">Filter quality assessment: Real trades vs Filtered signal performance</p>
        </div>
      </div>
      
      <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {stat_card("Shadow Win Rate", f"{sh['shadow_wr']:.1f}%", f"{sh['shadow_closed']} closed", "amber")}
        {stat_card("Real Win Rate", f"{sh['real_wr']:.1f}%", f"{sh['real_total']} closed", "green")}
        {stat_card("Filter Gap", f"{sh['gap']:+.1f}pp", "Real outperforms", gap_color)}
        {stat_card("Filter Efficiency", f"{sh['efficiency']:.2f}x", "Real / Shadow ratio", sh_quality_color)}
      </div>
      
      <div class="mb-4">
        <h4 class="text-sm font-semibold text-gray-700 mb-2">Interpretation</h4>
        <div class="text-sm text-gray-600 bg-{sh_quality_color}-50 border border-{sh_quality_color}-200 rounded-lg p-4">
          {sh_quality}: Filtered signals underperform real trades by <span class="font-semibold">{sh['gap']:.1f} percentage points</span>.
          Your filters are <span class="font-semibold">{sh['efficiency']:.2f}x more effective</span> than random selections.
          {gap_msg}
        </div>
      </div>
      
      <h4 class="text-sm font-semibold text-gray-700 mb-3">Performance by Horizon</h4>
      <div class="overflow-x-auto">
        <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Horizon</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Shadow WR</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Shadow N</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Real WR</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Real N</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Gap</th>
        </tr></thead><tbody>{hz_rows}</tbody></table>
      </div>
    </div>'''

    # ---- Section 2: Pattern Adjustments ----
    pat_rows = ""
    if pat_adj:
        for pname, pdata in sorted(pat_adj.items()):
            actual_wr = pdata.get("actual_win_rate", 0)
            decay_wr = pdata.get("decay_weighted_win_rate", 0)
            avg_ret = pdata.get("avg_return", 0)
            total_t = pdata.get("total_trades", 0)
            vol = pdata.get("volume_breakdown", {})
            vol_str = " · ".join(f"{k}: {v}" for k, v in sorted(vol.items())) if vol else "—"

            # Status
            if pname in penalized_patterns:
                st_badge = '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-700 border border-red-200">Penalized</span>'
            elif pname in boosted_patterns:
                st_badge = '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200">Boosted</span>'
            else:
                st_badge = '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 border border-gray-200">Neutral</span>'

            wr_cls = "text-emerald-600" if actual_wr >= 50 else "text-red-600"
            ret_cls = "text-emerald-600" if avg_ret >= 0 else "text-red-600"

            pat_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2.5 font-medium text-gray-800 text-xs">{_e(pname.replace("_", " ").title())}</td>
              <td class="px-4 py-2.5 text-right font-mono {wr_cls}">{actual_wr:.1f}%</td>
              <td class="px-4 py-2.5 text-right font-mono text-gray-600">{decay_wr:.1f}%</td>
              <td class="px-4 py-2.5 text-right font-mono {ret_cls}">{avg_ret:+.2f}%</td>
              <td class="px-4 py-2.5 text-right text-gray-600">{total_t}</td>
              <td class="px-4 py-2.5 text-xs text-gray-500">{_e(vol_str)}</td>
              <td class="px-4 py-2.5 text-center">{st_badge}</td>
            </tr>'''

    pat_section = f'''
    <div class="glass rounded-xl p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-gray-800">Pattern Adjustments</h3>
        <span class="text-xs text-gray-400">{len(pat_adj)} patterns · temporal decay half-life 60 days</span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Pattern</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Actual WR</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Decay WR</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Volume Breakdown</th>
          <th class="px-4 py-2 text-center text-xs text-gray-500 uppercase">Status</th>
        </tr></thead><tbody>{pat_rows}</tbody></table>
      </div>
    </div>''' if pat_adj else ""

    # ---- Section 3: Cross-Dimensional Intelligence ----

    def _adj_table(title, adj_dict, key_label="Key"):
        """Build a collapsible table for adjustment dicts."""
        if not adj_dict:
            return ""
        rows = ""
        for k, v in sorted(adj_dict.items()):
            actual_wr = v.get("actual_win_rate", 0)
            decay_wr = v.get("decay_weighted_win_rate", 0)
            avg_ret = v.get("avg_return", 0)
            total_t = v.get("total_trades", 0)
            wr_cls = "text-emerald-600" if actual_wr >= 50 else "text-red-600"
            ret_cls = "text-emerald-600" if avg_ret >= 0 else "text-red-600"
            # Format the key nicely
            display_key = k.replace("_", " ").replace("|", " → ").title()
            rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-xs text-gray-800">{_e(display_key)}</td>
              <td class="px-4 py-2 text-right font-mono {wr_cls}">{actual_wr:.1f}%</td>
              <td class="px-4 py-2 text-right font-mono text-gray-600">{decay_wr:.1f}%</td>
              <td class="px-4 py-2 text-right font-mono {ret_cls}">{avg_ret:+.2f}%</td>
              <td class="px-4 py-2 text-right text-gray-600">{total_t}</td>
            </tr>'''
        uid = title.lower().replace(" ", "_").replace("-", "_")
        return f'''
        <div class="glass rounded-xl mb-4 overflow-hidden">
          <button onclick="document.getElementById('adj_{uid}').classList.toggle('hidden'); this.querySelector('.chevron').classList.toggle('rotate-90')" class="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors">
            <div class="flex items-center gap-3">
              <h4 class="text-sm font-semibold text-gray-700">{_e(title)}</h4>
              <span class="text-xs font-medium text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">{len(adj_dict)} entries</span>
            </div>
            <svg class="w-4 h-4 text-gray-400 chevron transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
          </button>
          <div id="adj_{uid}" class="hidden">
            <div class="overflow-x-auto px-6 pb-4">
              <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
                <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">{_e(key_label)}</th>
                <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Actual WR</th>
                <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Decay WR</th>
                <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
                <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Trades</th>
              </tr></thead><tbody>{rows}</tbody></table>
            </div>
          </div>
        </div>'''

    cross_dim = f'''
    <div class="mb-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">Cross-Dimensional Intelligence</h3>
      {_adj_table("Regime Adjustments", regime_adj, "Regime")}
      {_adj_table("Horizon Adjustments", horizon_adj, "Horizon")}
      {_adj_table("Sector Adjustments", sector_adj, "Sector")}
      {_adj_table("Triple Adjustments (Pattern × Regime × Horizon)", triple_adj, "Combination")}
    </div>'''

    # ---- Section 3b: Filter Penalties & Boosts ----
    def _filter_table(title, pen_dict, bst_dict, uid_prefix):
        if not pen_dict and not bst_dict:
            return ""
        rows = ""
        all_keys = sorted(set(list(pen_dict.keys()) + list(bst_dict.keys())))
        for k in all_keys:
            pen_val = pen_dict.get(k)
            bst_val = bst_dict.get(k)
            display = k.replace("_", " ").replace("|", " → ").title()
            # Values can be dicts with {actual_wr, trades, action, reason} or plain floats
            if isinstance(pen_val, dict):
                wr = pen_val.get("actual_wr", 0)
                action = pen_val.get("action", "")
                reason = pen_val.get("reason", "")
                pen_html = f'<span class="font-mono text-red-600">{wr:.1f}% WR</span> <span class="text-red-400 text-[10px]">({_e(action)})</span>'
                pen_tip = reason
            elif pen_val is not None:
                pen_html = f'<span class="font-mono text-red-600">{float(pen_val):.3f}</span>'
                pen_tip = ""
            else:
                pen_html = '<span class="text-gray-300">—</span>'
                pen_tip = ""

            if isinstance(bst_val, dict):
                wr = bst_val.get("actual_wr", 0)
                action = bst_val.get("action", "")
                reason = bst_val.get("reason", "")
                bst_html = f'<span class="font-mono text-emerald-600">{wr:.1f}% WR</span> <span class="text-emerald-400 text-[10px]">({_e(action)})</span>'
                bst_tip = reason
            elif bst_val is not None:
                bst_html = f'<span class="font-mono text-emerald-600">{float(bst_val):.3f}</span>'
                bst_tip = ""
            else:
                bst_html = '<span class="text-gray-300">—</span>'
                bst_tip = ""

            rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-xs text-gray-800">{_e(display)}</td>
              <td class="px-4 py-2 text-center" title="{_e(pen_tip)}">{pen_html}</td>
              <td class="px-4 py-2 text-center" title="{_e(bst_tip)}">{bst_html}</td>
            </tr>'''
        return f'''
        <div class="glass rounded-xl mb-4 overflow-hidden">
          <button onclick="document.getElementById('{uid_prefix}_tbl').classList.toggle('hidden'); this.querySelector('.chevron').classList.toggle('rotate-90')" class="w-full flex items-center justify-between px-6 py-4 hover:bg-gray-50 transition-colors">
            <div class="flex items-center gap-3">
              <h4 class="text-sm font-semibold text-gray-700">{_e(title)}</h4>
              <span class="text-xs font-medium text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">{len(all_keys)} entries</span>
            </div>
            <svg class="w-4 h-4 text-gray-400 chevron transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
          </button>
          <div id="{uid_prefix}_tbl" class="hidden">
            <div class="overflow-x-auto px-6 pb-4">
              <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
                <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Key</th>
                <th class="px-4 py-2 text-center text-xs text-gray-500 uppercase">Penalty</th>
                <th class="px-4 py-2 text-center text-xs text-gray-500 uppercase">Boost</th>
              </tr></thead><tbody>{rows}</tbody></table>
            </div>
          </div>
        </div>'''

    filter_section = f'''
    <div class="mb-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">Active Filters</h3>
      {_filter_table("Pattern Filters", filter_pen, filter_bst, "flt_pat")}
      {_filter_table("Horizon Filters", hz_pen, hz_bst, "flt_hz")}
      {_filter_table("Sector Filters", sec_pen, sec_bst, "flt_sec")}
    </div>'''

    # ---- Section 4: Raw Feedback Log ----
    log_rows = ""
    for e in reversed(entries):  # newest first
        outcome = e.get("outcome", "")
        out_cls = "text-emerald-600 font-semibold" if outcome == "win" else "text-red-600 font-semibold"
        ret_val = e.get("actual_return_pct")
        ret_cls = "text-emerald-600" if (ret_val or 0) >= 0 else "text-red-600"
        pats = e.get("patterns", [])
        pat_str = ", ".join(pats) if isinstance(pats, list) else str(pats)
        ts = e.get("timestamp", "")
        if ts:
            try:
                ts = datetime.fromisoformat(ts).strftime("%d %b %y %H:%M")
            except Exception:
                pass
        log_rows += f'''
        <tr class="hover:bg-blue-50/50 border-b border-gray-100">
          <td class="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">{_e(ts)}</td>
          <td class="px-3 py-2 text-xs font-medium text-gray-800">{_e(_ticker(e.get("ticker","")))}</td>
          <td class="px-3 py-2 text-xs text-gray-600">{_e(e.get("direction",""))}</td>
          <td class="px-3 py-2 text-xs text-gray-600 max-w-[200px] truncate" title="{_e(pat_str)}">{_e(pat_str)}</td>
          <td class="px-3 py-2 text-xs text-gray-600">{_e(e.get("horizon_label",""))}</td>
          <td class="px-3 py-2 text-xs text-right text-gray-600">{e.get("predicted_win_rate","—")}</td>
          <td class="px-3 py-2 text-xs text-right {out_cls}">{_e(outcome)}</td>
          <td class="px-3 py-2 text-xs text-right font-mono {ret_cls}">{_pct(ret_val)}</td>
          <td class="px-3 py-2 text-xs text-gray-500">{_e(e.get("exit_reason",""))}</td>
        </tr>'''

    log_section = f'''
    <div class="glass rounded-xl p-6 mb-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-gray-800">Raw Feedback Log</h3>
        <a href="/feedback/download" class="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition-colors shadow-sm">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          Download CSV
        </a>
      </div>
      <div class="overflow-x-auto max-h-[500px] overflow-y-auto scrollbar-thin">
        <table class="w-full text-sm"><thead class="sticky top-0 bg-white"><tr class="border-b border-gray-200">
          <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Timestamp</th>
          <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Ticker</th>
          <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Dir</th>
          <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Patterns</th>
          <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Horizon</th>
          <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">Pred WR</th>
          <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">Outcome</th>
          <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">Return</th>
          <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Exit Reason</th>
        </tr></thead><tbody>{log_rows}</tbody></table>
      </div>
    </div>'''

    # ---- Learned Rules ----
    rules_html = ""
    if active_rules:
        rule_items = ""
        for r in active_rules:
            rule_items += f'''
            <div class="glass rounded-lg p-4 mb-2">
              <div class="text-sm text-gray-800">{_e(json.dumps(r, indent=2) if isinstance(r, dict) else str(r))}</div>
            </div>'''
        rules_html = f'''
        <div class="mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Learned Rules</h3>
          {rule_items}
        </div>'''

    body = f'''
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">RAG Feedback Loop</h2>
        <p class="text-sm text-gray-500 mt-1">How the system learns from trade outcomes — pattern penalties, regime adjustments, and cross-dimensional intelligence</p>
      </div>
    </div>
    {cards}
    {shadow_section}
    {pat_section}
    {filter_section}
    {cross_dim}
    {rules_html}
    {log_section}'''
    return page_shell("Feedback Loop", "feedback", body)


def render_engine(action_result=None):
    scan_log = q_scan_log()
    log_lines = get_engine_log()
    status = get_engine_status()
    pending = get_pending_signals()

    # Action buttons - disabled while engine is running
    disabled = 'opacity-50 pointer-events-none' if status['running'] else ''
    buttons = f'''
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      <form method="POST" action="/engine?action=run">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-blue-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-blue-600 transition">Full Run</p>
              <p class="text-xs text-gray-400">Catch-up + Scan + Monitor + Report</p>
            </div>
          </div>
        </button>
      </form>
      <form method="POST" action="/engine?action=scan">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-emerald-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-emerald-600 transition">Scan Only</p>
              <p class="text-xs text-gray-400">Scan + auto-enter signals</p>
            </div>
          </div>
        </button>
      </form>
      <form method="POST" action="/engine?action=scan_preview">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-purple-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-purple-600 transition">Scan & Review</p>
              <p class="text-xs text-gray-400">Scan signals, approve manually</p>
            </div>
          </div>
        </button>
      </form>
      <form method="POST" action="/engine?action=monitor">
        <button type="submit" class="w-full glass rounded-xl p-6 text-left hover:border-amber-400 transition-all group {disabled}">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
              <svg class="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
            </div>
            <div>
              <p class="font-semibold text-gray-800 group-hover:text-amber-600 transition">Monitor Only</p>
              <p class="text-xs text-gray-400">Check open positions for SL/target</p>
            </div>
          </div>
        </button>
      </form>
    </div>'''

    # Live output panel (shows when engine is running OR just finished)
    live_html = ""
    if status['running'] or status['done']:
        status_label = '<span class="inline-flex items-center gap-2"><span class="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span> Running...</span>' if status['running'] else (
            '<span class="text-emerald-600 font-semibold">Completed Successfully</span>' if status['success'] else '<span class="text-red-600 font-semibold">Failed</span>'
        )
        lines_text = _e("\n".join(status['lines']))
        live_html = f'''
        <div id="live-output" class="glass rounded-xl p-5 border-blue-300 mb-6 fade-in">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-3">
              <h3 class="text-lg font-semibold text-gray-800">Engine Output</h3>
              <span class="text-xs px-2 py-1 rounded-full bg-blue-50 text-blue-700">{_e(status['action']).upper()}</span>
            </div>
            <div id="status-indicator" class="text-sm">{status_label}</div>
          </div>
          <pre id="output-log" class="text-xs text-gray-700 bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto scrollbar-thin whitespace-pre-wrap font-mono leading-relaxed border border-gray-200">{lines_text}</pre>
          <div class="flex items-center justify-between mt-3">
            <span id="line-count" class="text-xs text-gray-400">{len(status['lines'])} lines</span>
            <span class="text-xs text-gray-400">Started: {status['started_at'][:19] if status['started_at'] else ''}</span>
          </div>
        </div>
        '''
        # Add polling JS only while running
        if status['running']:
            live_html += '''
        <script>
        (function() {
          let prevLen = 0;
          function poll() {
            fetch('/engine/stream')
              .then(r => r.json())
              .then(data => {
                const el = document.getElementById('output-log');
                const si = document.getElementById('status-indicator');
                const lc = document.getElementById('line-count');
                if (el) {
                  el.textContent = data.lines.join('\\n');
                  el.scrollTop = el.scrollHeight;
                }
                if (lc) lc.textContent = data.lines.length + ' lines';
                if (data.done) {
                  if (si) si.innerHTML = data.success
                    ? '<span class="text-emerald-600 font-semibold">Completed Successfully</span>'
                    : '<span class="text-red-600 font-semibold">Failed</span>';
                  // Re-enable buttons
                  document.querySelectorAll('form button').forEach(b => {
                    b.classList.remove('opacity-50', 'pointer-events-none');
                  });
                  // If scan_preview just finished, check for pending signals and reload
                  if (data.action === 'scan_preview' && data.success) {
                    fetch('/engine/pending').then(r => r.json()).then(p => {
                      if (p.has_pending) setTimeout(() => location.reload(), 500);
                    });
                  }
                  // If approve just finished, reload to clear review panel
                  if (data.action === 'approve' && data.success) {
                    setTimeout(() => location.reload(), 500);
                  }
                } else {
                  setTimeout(poll, 800);
                }
              })
              .catch(() => setTimeout(poll, 2000));
          }
          setTimeout(poll, 800);
        })();
        </script>'''

    # Action result (legacy — for non-streaming fallback)
    result_html = ""

    # Scan history
    scan_html = ""
    if scan_log:
        scan_rows = ""
        for s in scan_log:
            scan_rows += f'''
            <tr class="hover:bg-blue-50/50 border-b border-gray-100">
              <td class="px-4 py-2 text-gray-800">{_date(s["scan_date"])}</td>
              <td class="px-4 py-2 text-right text-gray-600">{s["tickers_scanned"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{s["signals_found"]}</td>
              <td class="px-4 py-2 text-right text-emerald-600">{s["trades_entered"]}</td>
              <td class="px-4 py-2 text-right text-red-600">{s["errors"]}</td>
              <td class="px-4 py-2 text-right text-gray-600">{s.get("duration_seconds",0):.1f}s</td>
            </tr>'''
        scan_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Scan History</h3>
          <div class="overflow-x-auto scrollbar-thin">
            <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
              <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Date</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Scanned</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Signals</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Entered</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Errors</th>
              <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Duration</th>
            </tr></thead><tbody>{scan_rows}</tbody></table>
          </div>
        </div>'''

    # Engine log
    log_text = _e("".join(log_lines)) if log_lines else '<span class="italic text-gray-400">No log entries yet</span>'
    log_html = f'''
    <div class="glass rounded-xl p-6">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-lg font-semibold text-gray-800">Engine Log</h3>
        <a href="/engine" class="text-xs text-gray-400 hover:text-gray-800 transition">Refresh</a>
      </div>
      <div class="bg-gray-50 rounded-lg p-4 max-h-80 overflow-y-auto scrollbar-thin border border-gray-200">
        <pre class="text-xs text-gray-600 font-mono leading-relaxed whitespace-pre-wrap">{log_text}</pre>
      </div>
    </div>'''

    # Signal Review Panel (shows when pending signals exist)
    review_html = ""
    if pending and not status['running']:
        total = pending.get("total_signals", 0)
        qualifying = pending.get("qualifying", 0)
        filtered_out = pending.get("filtered_out", 0)
        scan_dt = pending.get("scan_date", "")
        skip_summary = pending.get("skip_reason_summary", {})
        signals = pending.get("signals", [])
        skipped = pending.get("skipped", [])

        # Skip reason badges
        skip_badges = ""
        for reason, cnt in sorted(skip_summary.items(), key=lambda x: -x[1]):
            colors = {"Low Win Rate": "red", "Low Confidence": "amber",
                      "Low R:R Ratio": "orange", "Duplicate Trade": "gray"}.get(reason, "gray")
            skip_badges += f'<span class="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs bg-{colors}-50 text-{colors}-700">{_e(reason)}: {cnt}</span> '

        # Summary bar
        summary_bar = f'''
        <div class="glass rounded-xl p-5 mb-6 border-purple-300 fade-in">
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <h3 class="text-lg font-semibold text-gray-800">Signal Review</h3>
              <span class="text-xs px-2 py-1 rounded-full bg-purple-50 text-purple-700">Scan {_e(scan_dt)}</span>
            </div>
            <span class="text-xs text-gray-400">Awaiting your approval</span>
          </div>
          <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div class="bg-gray-50 rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-gray-800">{total}</p>
              <p class="text-xs text-gray-500">Total Signals</p>
            </div>
            <div class="bg-emerald-50 rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-emerald-700">{qualifying}</p>
              <p class="text-xs text-emerald-600">Qualifying</p>
            </div>
            <div class="bg-red-50 rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-red-700">{filtered_out}</p>
              <p class="text-xs text-red-600">Filtered Out</p>
            </div>
            <div class="bg-blue-50 rounded-lg p-3 text-center">
              <p class="text-2xl font-bold text-blue-700">{pending.get("duration", 0):.0f}s</p>
              <p class="text-xs text-blue-600">Scan Duration</p>
            </div>
          </div>
          <div class="flex flex-wrap gap-2 mb-1">
            <span class="text-xs text-gray-500 font-medium">Skip Reasons:</span>
            {skip_badges if skip_badges else '<span class="text-xs text-gray-400 italic">None</span>'}
          </div>
        </div>'''

        # Fetch live prices for qualifying signal tickers
        all_tickers = list(set(sig.get("ticker", "") for sig in signals + skipped))
        live_prices = fetch_live_prices(all_tickers) if all_tickers else {}

        # Qualifying signals table
        if signals:
            sig_rows = ""
            for i, sig in enumerate(signals):
                dir_color = "emerald"
                dir_icon = "&#9650;"
                wr = sig.get("predicted_win_rate", 0)
                wr_color = "emerald" if wr >= 60 else ("amber" if wr >= 55 else "red")
                rr = sig.get("rr_ratio", 0)
                rr_val = f"{rr:.1f}x" if rr else "-"
                conf = sig.get("confidence", "-")
                conf_color = {"HIGH": "emerald", "MEDIUM": "amber", "LOW": "red"}.get(conf, "gray")
                sector = _e(sig.get("sector", "-") or "-")
                patterns = _e(sig.get("patterns", "-") or "-")
                if len(patterns) > 30:
                    patterns = patterns[:28] + ".."
                # Current market price
                cmp = live_prices.get(sig.get("ticker", ""))
                entry_p = sig.get("entry_price", 0)
                if cmp:
                    cmp_diff = ((cmp - entry_p) / entry_p * 100) if entry_p else 0
                    cmp_color = "emerald" if cmp_diff >= 0 else "red"
                    cmp_html = f'{cmp:.2f} <span class="text-xs text-{cmp_color}-500">({cmp_diff:+.1f}%)</span>'
                else:
                    cmp_html = '<span class="text-gray-400">-</span>'

                sig_rows += f'''
                <tr class="hover:bg-purple-50/50 border-b border-gray-100">
                  <td class="px-3 py-2 text-center">
                    <input type="checkbox" name="sig_idx" value="{i}" checked
                      class="sig-checkbox w-4 h-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500">
                  </td>
                  <td class="px-3 py-2 font-medium text-gray-800">{_e(sig.get("ticker",""))}</td>
                  <td class="px-3 py-2 text-center">
                    <span class="text-{dir_color}-600 font-semibold">{dir_icon} {_e(sig.get("direction",""))}</span>
                  </td>
                  <td class="px-3 py-2 text-center">
                    <span class="px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-700">{_e(sig.get("horizon_label",""))}</span>
                  </td>
                  <td class="px-3 py-2 text-right text-gray-700">{sig.get("entry_price",0):.2f}</td>
                  <td class="px-3 py-2 text-right font-medium">{cmp_html}</td>
                  <td class="px-3 py-2 text-right text-emerald-600">{sig.get("target_price",0):.2f}</td>
                  <td class="px-3 py-2 text-right text-red-600">{sig.get("sl_price",0):.2f}</td>
                  <td class="px-3 py-2 text-center">
                    <span class="text-{wr_color}-600 font-medium">{wr:.0f}%</span>
                  </td>
                  <td class="px-3 py-2 text-center text-gray-700">{rr_val}</td>
                  <td class="px-3 py-2 text-center">
                    <span class="px-2 py-0.5 rounded-full text-xs bg-{conf_color}-50 text-{conf_color}-700">{_e(conf)}</span>
                  </td>
                  <td class="px-3 py-2 text-xs text-gray-500">{sector}</td>
                  <td class="px-3 py-2 text-xs text-gray-500">{patterns}</td>
                </tr>'''

            signals_table = f'''
            <div class="glass rounded-xl p-5 mb-6 border-purple-200 fade-in">
              <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-3">
                  <h3 class="text-lg font-semibold text-gray-800">Qualifying Signals ({qualifying})</h3>
                  <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
                    <input type="checkbox" id="select-all" checked
                      class="w-4 h-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500">
                    Select All
                  </label>
                </div>
                <div class="flex gap-2">
                  <button onclick="approveSelected()" class="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 transition">
                    Approve Selected
                  </button>
                  <button onclick="approveAll()" class="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm font-medium hover:bg-purple-700 transition">
                    Approve All
                  </button>
                  <form method="POST" action="/engine?action=discard" style="display:inline">
                    <button type="submit" class="px-4 py-2 rounded-lg bg-red-100 text-red-700 text-sm font-medium hover:bg-red-200 transition">
                      Discard All
                    </button>
                  </form>
                </div>
              </div>
              <div class="overflow-x-auto scrollbar-thin">
                <table class="w-full text-sm">
                  <thead>
                    <tr class="border-b border-gray-200">
                      <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase w-10"></th>
                      <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Ticker</th>
                      <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">Direction</th>
                      <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">Horizon</th>
                      <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">Entry</th>
                      <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">CMP</th>
                      <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">Target</th>
                      <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">SL</th>
                      <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">Win%</th>
                      <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">R:R</th>
                      <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">Conf</th>
                      <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Sector</th>
                      <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Patterns</th>
                    </tr>
                  </thead>
                  <tbody>{sig_rows}</tbody>
                </table>
              </div>
            </div>'''
        else:
            signals_table = ""

        # Skipped signals (collapsible)
        skipped_html = ""
        if skipped:
            skip_rows = ""
            for sig in skipped:
                dir_color = "emerald"
                dir_icon = "&#9650;"
                reasons = "; ".join(sig.get("skip_reasons", []))
                skip_rows += f'''
                <tr class="hover:bg-red-50/30 border-b border-gray-100 text-gray-400">
                  <td class="px-3 py-1.5">{_e(sig.get("ticker",""))}</td>
                  <td class="px-3 py-1.5 text-center">
                    <span class="text-{dir_color}-400">{dir_icon}</span>
                  </td>
                  <td class="px-3 py-1.5 text-center text-xs">{_e(sig.get("horizon_label",""))}</td>
                  <td class="px-3 py-1.5 text-right">{sig.get("entry_price",0):.2f}</td>
                  <td class="px-3 py-1.5 text-xs text-red-500">{_e(reasons)}</td>
                </tr>'''

            skipped_html = f'''
            <div class="glass rounded-xl p-5 mb-6 border-red-100 fade-in">
              <details>
                <summary class="cursor-pointer text-sm font-semibold text-gray-600 hover:text-gray-800 transition">
                  Filtered Out Signals ({filtered_out}) — click to expand
                </summary>
                <div class="overflow-x-auto scrollbar-thin mt-3">
                  <table class="w-full text-sm">
                    <thead>
                      <tr class="border-b border-gray-200">
                        <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Ticker</th>
                        <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">Dir</th>
                        <th class="px-3 py-2 text-center text-xs text-gray-500 uppercase">Horizon</th>
                        <th class="px-3 py-2 text-right text-xs text-gray-500 uppercase">Entry</th>
                        <th class="px-3 py-2 text-left text-xs text-gray-500 uppercase">Skip Reason(s)</th>
                      </tr>
                    </thead>
                    <tbody>{skip_rows}</tbody>
                  </table>
                </div>
              </details>
            </div>'''

        # JS for select all & approve actions
        review_js = '''
        <script>
        document.getElementById('select-all').addEventListener('change', function() {
          document.querySelectorAll('.sig-checkbox').forEach(cb => cb.checked = this.checked);
        });
        document.querySelectorAll('.sig-checkbox').forEach(cb => {
          cb.addEventListener('change', function() {
            const all = document.querySelectorAll('.sig-checkbox');
            const checked = document.querySelectorAll('.sig-checkbox:checked');
            document.getElementById('select-all').checked = all.length === checked.length;
          });
        });

        function approveSelected() {
          const checked = document.querySelectorAll('.sig-checkbox:checked');
          if (checked.length === 0) { alert('No signals selected'); return; }
          const indices = Array.from(checked).map(cb => cb.value).join(',');
          const form = document.createElement('form');
          form.method = 'POST';
          form.action = '/engine?action=approve&indices=' + indices;
          document.body.appendChild(form);
          form.submit();
        }

        function approveAll() {
          if (!confirm('Approve all qualifying signals?')) return;
          const form = document.createElement('form');
          form.method = 'POST';
          form.action = '/engine?action=approve';
          document.body.appendChild(form);
          form.submit();
        }
        </script>'''

        review_html = summary_bar + signals_table + skipped_html + review_js

    body = f'''
    <h2 class="text-2xl font-bold text-gray-800 mb-2">Engine Control</h2>
    <p class="text-sm text-gray-500 mb-6">Run the paper trading engine manually or view logs</p>
    {buttons}
    {live_html}
    {review_html}
    {scan_html}
    {log_html}'''
    return page_shell("Engine Control", "engine", body)


# ============================================================
# HTTP REQUEST HANDLER
# ============================================================
class DashboardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")

        routes = {
            "": ("dashboard", render_dashboard),
            "dashboard": ("dashboard", render_dashboard),
            "signals": ("signals", render_signals),
            "positions": ("positions", render_positions),
            "history": ("history", render_history),
            "market": ("market", render_market_indices),
            "performance": ("performance", render_performance),
            "engine": ("engine", lambda: render_engine()),
            "feedback": ("feedback", render_feedback),
        }

        if path == "feedback/download":
            # CSV download of feedback log
            csv_bytes = _feedback_csv_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=traqo_feedback_log.csv")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(csv_bytes)
        elif path == "engine/stream":
            # JSON endpoint for live polling
            status = get_engine_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode("utf-8"))
        elif path == "engine/pending":
            # JSON endpoint: check if pending signals file exists
            pending = get_pending_signals()
            result = {"has_pending": pending is not None}
            if pending:
                result["qualifying"] = pending.get("qualifying", 0)
                result["filtered_out"] = pending.get("filtered_out", 0)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode("utf-8"))
        elif path in routes:
            _, renderer = routes[path]
            try:
                html = renderer()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"<h1>Error</h1><pre>{_e(str(e))}</pre>".encode("utf-8"))
        elif path == "favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(302)
            self.send_header("Location", "/dashboard")
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")
        params = urllib.parse.parse_qs(parsed.query)

        if path == "engine":
            action = params.get("action", ["run"])[0]
            if action in ("run", "scan", "monitor", "scan_preview"):
                start_engine(action)
                # Redirect to GET /engine so user sees live output
                self.send_response(302)
                self.send_header("Location", "/engine")
                self.end_headers()
                return
            elif action == "approve":
                indices_str = params.get("indices", [None])[0]
                extra = [indices_str] if indices_str else None
                start_engine("approve", extra_args=extra)
                self.send_response(302)
                self.send_header("Location", "/engine")
                self.end_headers()
                return
            elif action == "discard":
                # Quick operation — just delete staging file, no engine needed
                if os.path.exists(PENDING_SIGNALS_FILE):
                    os.remove(PENDING_SIGNALS_FILE)
                self.send_response(302)
                self.send_header("Location", "/engine")
                self.end_headers()
                return

        elif path == "health":
            # Health check endpoint for debugging
            health_status = {
                "yfinance_available": _HAS_YF,
                "yfinance_version": yf.__version__ if _HAS_YF else "Not available",
                "open_trades_count": len(q_open_trades()),
                "timestamp": datetime.now().isoformat()
            }
            
            if _HAS_YF:
                # Test a quick price fetch
                try:
                    test_data = yf.download("SBIN.NS", period="1d", progress=False)
                    health_status["price_test"] = "✅ SUCCESS" if not test_data.empty else "❌ Empty data"
                except Exception as e:
                    health_status["price_test"] = f"❌ ERROR: {e}"
            else:
                health_status["price_test"] = "❌ yfinance not available"
                
            response_html = f"""
            <!DOCTYPE html>
            <html><head><title>Traqo Health Check</title>
            <style>body{{font-family:monospace; padding:20px; background:#f5f5f5;}} 
            .status{{padding:10px; margin:5px; border-radius:5px; background:white;}}</style>
            </head><body>
            <h1>🏥 Traqo Health Check</h1>
            <div class="status"><strong>yfinance Available:</strong> {health_status['yfinance_available']}</div>
            <div class="status"><strong>yfinance Version:</strong> {health_status['yfinance_version']}</div>
            <div class="status"><strong>Price Test:</strong> {health_status['price_test']}</div>
            <div class="status"><strong>Open Trades:</strong> {health_status['open_trades_count']}</div>
            <div class="status"><strong>Timestamp:</strong> {health_status['timestamp']}</div>
            <p><a href="/">← Back to Dashboard</a></p>
            </body></html>
            """
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(response_html.encode("utf-8"))
            return

        elif path == "trade/cancel":
            try:
                trade_id = int(params.get("id", [0])[0])
                if trade_id > 0:
                    cancel_trade(trade_id)
            except Exception:
                pass
            self.send_response(302)
            self.send_header("Location", "/positions")
            self.end_headers()
            return

        elif path == "trade/cancel-bulk":
            try:
                ids_str = params.get("ids", [""])[0]
                ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
                if ids:
                    cancel_trades_bulk(ids)
            except Exception:
                pass
            self.send_response(302)
            self.send_header("Location", "/positions")
            self.end_headers()
            return

        elif path == "trade/purge":
            # Purge specific trade IDs (works on any status, not just OPEN)
            try:
                ids_str = params.get("ids", [""])[0]
                ids = [int(x.strip()) for x in ids_str.split(",") if x.strip().isdigit()]
                if ids:
                    purge_closed_trades(ids)
            except Exception:
                pass
            self.send_response(302)
            self.send_header("Location", "/trades")
            self.end_headers()
            return

        elif path == "trade/purge-date":
            # Purge all non-OPEN trades closed between from_date and to_date
            try:
                from_dt = params.get("from", [""])[0]
                to_dt = params.get("to", [from_dt])[0]
                if from_dt:
                    purge_trades_by_date(from_dt, to_dt)
            except Exception:
                pass
            self.send_response(302)
            self.send_header("Location", "/trades")
            self.end_headers()
            return

        self.send_response(302)
        self.send_header("Location", "/dashboard")
        self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging noise
        pass


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    port = 8521
    print(f"\n  Traqo — RAG Powered Quantitative Candlestick Intelligence")
    print(f"  http://localhost:{port}")
    
    # Display yfinance status prominently
    if _HAS_YF:
        print(f"  ✅ Live prices: ENABLED (yfinance v{yf.__version__})")
    else:
        print(f"  ❌ Live prices: DISABLED (yfinance not found)")
        print(f"  💡 Fix: Activate virtual environment and run 'pip install yfinance'")
    
    print(f"  🏥 Health check: http://localhost:{port}/health\n")

    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)

    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
