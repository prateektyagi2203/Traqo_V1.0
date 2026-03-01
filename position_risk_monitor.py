"""
Position Risk Monitor — Tier 1: Position Monitoring & Regime Tracking
=====================================================================
Implements age-based confidence decay, real-time regime comparison
(entry vs current), and sector momentum checks to produce an adjusted
confidence score for every open position.

Decision rules:
    Confidence 65-100% → HOLD
    Confidence 35-64%  → REDUCE 50% + tighten stop loss
    Confidence <35%    → EXIT immediately

Expected impact: ~40% reduction in unplanned losses from regime shifts.

Reference: POSITION_RISK_MANAGEMENT_FRAMEWORK.md (Tier 1)
"""

import logging
import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

from trading_config import INSTRUMENT_SECTORS

# Trajectory Health (RAG-informed mid-trade intelligence)
try:
    from trajectory_health import (
        TrajectoryProfiler,
        assess_trade_trajectory,
    )
    HAVE_TRAJECTORY_HEALTH = True
except ImportError:
    HAVE_TRAJECTORY_HEALTH = False

log = logging.getLogger("position_risk_monitor")

# Module-level trajectory profiler singleton (lazy-init)
_trajectory_profiler: Optional["TrajectoryProfiler"] = None


def set_trajectory_profiler(profiler):
    """Set the shared TrajectoryProfiler instance (avoids duplicate SP loads)."""
    global _trajectory_profiler
    _trajectory_profiler = profiler


def _get_trajectory_profiler():
    """Lazily initialise the trajectory profiler."""
    global _trajectory_profiler
    if _trajectory_profiler is None and HAVE_TRAJECTORY_HEALTH:
        try:
            _trajectory_profiler = TrajectoryProfiler()
        except Exception as e:
            log.warning(f"TrajectoryProfiler init failed: {e}")
    return _trajectory_profiler

# ============================================================
# CONSTANTS
# ============================================================

# Sector-index proxy tickers used for momentum calculations.
# Where no clean ETF exists we fall back to a Nifty sectoral index.
SECTOR_PROXY_TICKERS = {
    "banking":   "^NSEBANK",     # NIFTY Bank
    "finance":   "^NSEBANK",     # closest proxy
    "it":        "^CNXIT",       # NIFTY IT
    "auto":      "^CNXAUTO",     # NIFTY Auto
    "pharma":    "^CNXPHARMA",   # NIFTY Pharma
    "metals":    "^CNXMETAL",    # NIFTY Metal
    "fmcg":      "^CNXFMCG",    # NIFTY FMCG
    "energy":    "^CNXENERGY",   # NIFTY Energy
    "realty":    "^CNXREALTY",   # NIFTY Realty
    "infra":     "^CNXINFRA",   # NIFTY Infra
    "conglomerate": "^NSEI",     # fallback to NIFTY 50
    "cement":    "^NSEI",
    "telecom":   "^NSEI",
    "media":     "^NSEI",
    "chemicals": "^NSEI",
    "consumer":  "^NSEI",
    "industrial":"^NSEI",
    "logistics": "^NSEI",
    "unknown":   "^NSEI",
}

NIFTY_TICKER = "^NSEI"

# Age-based confidence decay schedule (days_held → multiplier)
DECAY_SCHEDULE = {
    0: 1.00,
    1: 1.00,
    2: 0.95,
    3: 0.90,
    4: 0.87,
    5: 0.85,
    6: 0.80,
    7: 0.75,
    8: 0.72,
    9: 0.70,
    10: 0.65,
}
DECAY_FLOOR = 0.50  # 11+ days

# Regime shift penalties (entry_regime → current_regime → penalty)
REGIME_SHIFT_PENALTIES = {
    ("bullish", "bearish"):  -30,
    ("bullish", "neutral"):  -15,
    ("bullish", "bullish"):    0,
    ("bearish", "bullish"):  -30,
    ("bearish", "neutral"):  -15,
    ("bearish", "bearish"):    0,
    ("neutral", "bullish"):    0,
    ("neutral", "bearish"):  -10,
    ("neutral", "neutral"):    0,
}

# Sector momentum penalty thresholds
SECTOR_MOMENTUM_THRESHOLDS = [
    (-1.0, -20),   # sector down > 1% → -20
    (-0.5, -10),   # sector down 0.5-1% → -10
]

# Action thresholds
HOLD_CONFIDENCE_MIN = 65
REDUCE_CONFIDENCE_MIN = 35

# Position monitoring DB table
MONITORING_TABLE = "position_monitoring"
MONITORING_LOG_DIR = "paper_trades/risk_logs"


# ============================================================
# MARKET DATA HELPERS (cached per session)
# ============================================================
_cache: Dict[str, dict] = {}


def _get_daily_data(ticker: str, lookback_days: int = 10) -> Optional[pd.DataFrame]:
    """Download recent daily OHLCV. Cached per ticker for the session."""
    cache_key = f"{ticker}_{lookback_days}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        end = datetime.now()
        start = end - timedelta(days=lookback_days + 15)   # extra buffer for weekends
        df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                         end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                         progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.dropna()
        _cache[cache_key] = df
        return df
    except Exception as e:
        log.warning(f"Failed to fetch {ticker}: {e}")
        return None


def clear_cache():
    """Clear the session-level data cache."""
    _cache.clear()


# ============================================================
# REGIME DETECTION (lightweight, based on recent NIFTY data)
# ============================================================
def get_current_market_regime() -> str:
    """Return simplified regime label: 'bullish', 'bearish', or 'neutral'.

    Uses Nifty 50 EMA-9 vs EMA-21 on daily timeframe.
    """
    df = _get_daily_data(NIFTY_TICKER, lookback_days=60)
    if df is None or len(df) < 22:
        return "neutral"

    close = df["Close"].astype(float)
    ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]

    # Also check last 3-day momentum for faster reaction
    last_close = float(close.iloc[-1])
    close_3d_ago = float(close.iloc[-4]) if len(close) > 4 else last_close
    momentum_3d = (last_close - close_3d_ago) / close_3d_ago * 100

    if ema9 > ema21 and momentum_3d > -0.5:
        return "bullish"
    elif ema9 < ema21 and momentum_3d < 0.5:
        return "bearish"
    else:
        return "neutral"


def get_sector_momentum(sector: str, hours: int = 24) -> float:
    """Get sector momentum as % change over the specified period.

    For daily data, ``hours=24`` means the last 1-day return.
    """
    proxy = SECTOR_PROXY_TICKERS.get(sector, NIFTY_TICKER)
    df = _get_daily_data(proxy, lookback_days=10)
    if df is None or len(df) < 2:
        return 0.0

    close = df["Close"].astype(float)
    # Use 1-day return as the momentum proxy
    current = float(close.iloc[-1])
    previous = float(close.iloc[-2])
    if previous == 0:
        return 0.0
    return round((current - previous) / previous * 100, 2)


def _classify_entry_regime(indicators_json: str) -> str:
    """Derive entry regime from the saved indicators at trade entry."""
    try:
        ind = json.loads(indicators_json) if isinstance(indicators_json, str) else (indicators_json or {})
    except (json.JSONDecodeError, TypeError):
        return "neutral"

    trend = ind.get("trend_short", "neutral")
    if trend == "bullish":
        return "bullish"
    elif trend == "bearish":
        return "bearish"
    return "neutral"


# ============================================================
# CORE: POSITION HEALTH ASSESSMENT
# ============================================================
def assess_position_health(trade: dict, check_date: date = None) -> dict:
    """Perform a full Tier-1 health check on a single open position.

    Parameters
    ----------
    trade : dict
        A row from the ``trades`` table (as returned by ``get_open_trades``).
    check_date : date, optional
        The date to assess against.  Defaults to today.

    Returns
    -------
    dict with keys:
        trade_id, ticker, days_held, original_confidence,
        adjusted_confidence, confidence_decay_pct, regime_alignment,
        entry_regime, current_regime, sector, sector_momentum,
        sector_penalty, regime_shift_penalty,
        action_required (bool), action (str), action_detail (str)
    """
    if check_date is None:
        check_date = date.today()

    trade_id = trade.get("id")
    ticker = trade.get("ticker", "UNKNOWN")
    entry_date = date.fromisoformat(trade["entry_date"])
    days_held = (check_date - entry_date).days

    # --- Original confidence (numeric 0-100) ---
    conf_str = (trade.get("confidence") or "MEDIUM").upper()
    original_confidence = {"HIGH": 80, "MEDIUM": 60, "LOW": 40}.get(conf_str, 55)

    # --- Age-based decay ---
    decay_mult = DECAY_SCHEDULE.get(min(days_held, 10), DECAY_FLOOR)
    if days_held > 10:
        decay_mult = DECAY_FLOOR

    # --- Regime comparison ---
    entry_regime = _classify_entry_regime(trade.get("indicators_json", "{}"))
    current_regime = get_current_market_regime()

    regime_pair = (entry_regime, current_regime)
    regime_shift_penalty = REGIME_SHIFT_PENALTIES.get(regime_pair, 0)

    # --- Sector health ---
    instrument = trade.get("instrument") or ""
    sector = trade.get("sector") or INSTRUMENT_SECTORS.get(instrument, "unknown")
    sector_mom = get_sector_momentum(sector)

    sector_penalty = 0
    for threshold, penalty in SECTOR_MOMENTUM_THRESHOLDS:
        if sector_mom < threshold:
            sector_penalty = penalty
            break

    # --- Direction mismatch bonus / penalty ---
    direction = (trade.get("direction") or "").upper()
    direction_penalty = 0
    if direction == "BULLISH" and current_regime == "bearish":
        direction_penalty = -10
    elif direction == "BEARISH" and current_regime == "bullish":
        direction_penalty = -10

    # --- Trajectory health (RAG-informed mid-trade intelligence) ---
    trajectory_adjustment = 0
    trajectory_score = 50.0
    trajectory_label = "N/A"
    if HAVE_TRAJECTORY_HEALTH and days_held >= 1:
        try:
            ticker = trade.get("ticker", "UNKNOWN")
            df = _get_daily_data(ticker, lookback_days=5)
            if df is not None and not df.empty:
                current_price = float(df["Close"].iloc[-1])
                profiler = _get_trajectory_profiler()
                if profiler is not None:
                    traj = assess_trade_trajectory(
                        trade=trade,
                        current_price=current_price,
                        check_date=check_date,
                        profiler=profiler,
                    )
                    trajectory_adjustment = traj.get("confidence_adjustment", 0)
                    t_health = traj.get("trajectory_health", {})
                    trajectory_score = t_health.get("score", 50.0)
                    trajectory_label = t_health.get("label", "N/A")
        except Exception as e:
            log.debug(f"Trajectory health failed for {trade.get('ticker')}: {e}")

    # --- FINAL ADJUSTED CONFIDENCE ---
    adjusted = (
        original_confidence * decay_mult
        + regime_shift_penalty
        + sector_penalty
        + direction_penalty
        + trajectory_adjustment
    )
    adjusted = max(0, min(100, adjusted))

    # --- Decision ---
    if adjusted >= HOLD_CONFIDENCE_MIN:
        action = "HOLD"
        action_detail = "Position healthy — hold with existing SL/target."
    elif adjusted >= REDUCE_CONFIDENCE_MIN:
        action = "REDUCE 50%"
        action_detail = "Confidence degraded — reduce position 50% and tighten stop loss."
    else:
        action = "EXIT IMMEDIATELY"
        action_detail = "Critical confidence drop — exit position to prevent further loss."

    return {
        "trade_id": trade_id,
        "ticker": ticker,
        "direction": direction,
        "days_held": days_held,
        "horizon_label": trade.get("horizon_label", ""),
        "entry_date": trade["entry_date"],
        "original_confidence": original_confidence,
        "confidence_decay_mult": round(decay_mult, 2),
        "confidence_decay_pct": round((1 - decay_mult) * 100, 1),
        "regime_alignment": entry_regime == current_regime,
        "entry_regime": entry_regime,
        "current_regime": current_regime,
        "regime_shift_penalty": regime_shift_penalty,
        "sector": sector,
        "sector_momentum": sector_mom,
        "sector_penalty": sector_penalty,
        "direction_penalty": direction_penalty,
        "trajectory_adjustment": trajectory_adjustment,
        "trajectory_score": round(trajectory_score, 1),
        "trajectory_label": trajectory_label,
        "adjusted_confidence": round(adjusted, 1),
        "action_required": adjusted < HOLD_CONFIDENCE_MIN,
        "action": action,
        "action_detail": action_detail,
    }


# ============================================================
# BATCH: ASSESS ALL OPEN POSITIONS
# ============================================================
def assess_all_positions(open_trades: List[dict],
                         check_date: date = None) -> List[dict]:
    """Run health assessment across every open trade.

    Returns a list of health dicts, sorted by adjusted_confidence (worst first).
    """
    if check_date is None:
        check_date = date.today()

    clear_cache()  # start fresh
    results = []
    for trade in open_trades:
        try:
            health = assess_position_health(trade, check_date)
            results.append(health)
        except Exception as e:
            log.warning(f"Health check failed for trade {trade.get('id')}: {e}")

    # Sort worst first
    results.sort(key=lambda h: h["adjusted_confidence"])
    return results


# ============================================================
# SUMMARY & LOGGING
# ============================================================
def generate_risk_summary(health_results: List[dict]) -> dict:
    """Produce a concise summary from a batch of health assessments."""
    if not health_results:
        return {"total_positions": 0, "actions": {}}

    actions = defaultdict(list)
    for h in health_results:
        actions[h["action"]].append(h["ticker"])

    avg_confidence = np.mean([h["adjusted_confidence"] for h in health_results])
    worst = min(health_results, key=lambda h: h["adjusted_confidence"])
    regime_mismatches = sum(1 for h in health_results if not h["regime_alignment"])

    return {
        "total_positions": len(health_results),
        "avg_adjusted_confidence": round(avg_confidence, 1),
        "regime_mismatches": regime_mismatches,
        "worst_position": {
            "ticker": worst["ticker"],
            "adjusted_confidence": worst["adjusted_confidence"],
            "action": worst["action"],
        },
        "action_counts": {a: len(tickers) for a, tickers in actions.items()},
        "actions": {a: tickers for a, tickers in actions.items()},
    }


def log_risk_report(health_results: List[dict], check_date: date = None):
    """Write a risk report to the console log and to a daily JSON file."""
    if check_date is None:
        check_date = date.today()

    summary = generate_risk_summary(health_results)

    log.info("=" * 60)
    log.info("POSITION RISK MONITOR — TIER 1 REPORT")
    log.info(f"Date: {check_date.isoformat()}")
    log.info(f"Positions assessed: {summary['total_positions']}")
    log.info(f"Avg adjusted confidence: {summary['avg_adjusted_confidence']:.1f}%")
    log.info(f"Regime mismatches: {summary['regime_mismatches']}")
    log.info("-" * 60)

    # Action breakdown
    for action in ("EXIT IMMEDIATELY", "REDUCE 50%", "HOLD"):
        tickers = summary["actions"].get(action, [])
        if tickers:
            flag = "🔴" if action == "EXIT IMMEDIATELY" else "🟡" if action == "REDUCE 50%" else "🟢"
            log.info(f"  {flag} {action}: {len(tickers)} positions")
            for t in tickers[:10]:
                log.info(f"      - {t}")
            if len(tickers) > 10:
                log.info(f"      ... and {len(tickers) - 10} more")

    # Detail on worst positions (EXIT + REDUCE)
    critical = [h for h in health_results if h["action"] != "HOLD"]
    if critical:
        log.info("-" * 60)
        log.info("POSITIONS REQUIRING ACTION:")
        for h in critical[:20]:
            traj_lbl = h.get("trajectory_label", "N/A")
            traj_adj = h.get("trajectory_adjustment", 0)
            log.info(
                f"  {h['ticker']:15s}  conf={h['adjusted_confidence']:5.1f}%  "
                f"age={h['days_held']}d  regime={h['entry_regime']}→{h['current_regime']}  "
                f"sector_mom={h['sector_momentum']:+.2f}%  "
                f"traj={traj_lbl}({traj_adj:+.0f})  → {h['action']}"
            )

    log.info("=" * 60)

    # Persist to JSON
    os.makedirs(MONITORING_LOG_DIR, exist_ok=True)
    report_path = os.path.join(
        MONITORING_LOG_DIR,
        f"risk_report_{check_date.isoformat()}.json",
    )
    report_data = {
        "check_date": check_date.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "summary": summary,
        "positions": health_results,
    }
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, default=str)
        log.info(f"Risk report saved → {report_path}")
    except Exception as e:
        log.warning(f"Failed to save risk report: {e}")

    return summary


# ============================================================
# DB PERSISTENCE: position_monitoring table
# ============================================================
def ensure_monitoring_table(conn: sqlite3.Connection):
    """Create the position_monitoring table if it doesn't exist."""
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {MONITORING_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            check_date TEXT,
            days_held INTEGER,
            entry_regime TEXT,
            current_regime TEXT,
            original_confidence INTEGER,
            adjusted_confidence REAL,
            confidence_decay_pct REAL,
            sector TEXT,
            sector_momentum REAL,
            sector_penalty REAL,
            regime_shift_penalty REAL,
            direction_penalty REAL,
            trajectory_adjustment REAL DEFAULT 0,
            trajectory_score REAL DEFAULT 50,
            trajectory_label TEXT DEFAULT 'N/A',
            recommended_action TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(trade_id) REFERENCES trades(id)
        );
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_posmon_trade
        ON {MONITORING_TABLE}(trade_id, check_date);
    """)
    conn.commit()

    # --- Migrate: add trajectory columns if missing ---
    try:
        cur = conn.execute(f"PRAGMA table_info({MONITORING_TABLE})")
        existing_cols = {row[1] for row in cur.fetchall()}
        for col, col_type, default in [
            ("trajectory_adjustment", "REAL", "0"),
            ("trajectory_score", "REAL", "50"),
            ("trajectory_label", "TEXT", "'N/A'"),
        ]:
            if col not in existing_cols:
                conn.execute(
                    f"ALTER TABLE {MONITORING_TABLE} ADD COLUMN {col} {col_type} DEFAULT {default}"
                )
                log.info(f"Migrated {MONITORING_TABLE}: added {col} column")
        conn.commit()
    except Exception as e:
        log.debug(f"Monitoring table migration check: {e}")


def persist_health_results(conn: sqlite3.Connection,
                           health_results: List[dict],
                           check_date: date = None):
    """Write health-check results into the position_monitoring table."""
    if check_date is None:
        check_date = date.today()
    ensure_monitoring_table(conn)

    date_str = check_date.isoformat()
    for h in health_results:
        try:
            conn.execute(f"""
                INSERT INTO {MONITORING_TABLE} (
                    trade_id, check_date, days_held,
                    entry_regime, current_regime,
                    original_confidence, adjusted_confidence,
                    confidence_decay_pct, sector, sector_momentum,
                    sector_penalty, regime_shift_penalty, direction_penalty,
                    trajectory_adjustment, trajectory_score, trajectory_label,
                    recommended_action
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                h["trade_id"], date_str, h["days_held"],
                h["entry_regime"], h["current_regime"],
                h["original_confidence"], h["adjusted_confidence"],
                h["confidence_decay_pct"], h["sector"], h["sector_momentum"],
                h["sector_penalty"], h["regime_shift_penalty"],
                h.get("direction_penalty", 0),
                h.get("trajectory_adjustment", 0),
                h.get("trajectory_score", 50),
                h.get("trajectory_label", "N/A"),
                h["action"],
            ))
        except Exception as e:
            log.warning(f"Failed to persist health for trade {h.get('trade_id')}: {e}")
    conn.commit()


# ============================================================
# ENTRY-REGIME MIGRATION: add entry_regime column to trades
# ============================================================
def ensure_entry_regime_column(conn: sqlite3.Connection):
    """Add entry_regime column to trades table if missing.

    Backfills from indicators_json for existing rows.
    """
    cursor = conn.execute("PRAGMA table_info(trades)")
    columns = [row[1] for row in cursor.fetchall()]

    if "entry_regime" not in columns:
        conn.execute("ALTER TABLE trades ADD COLUMN entry_regime TEXT DEFAULT 'neutral'")
        conn.commit()
        log.info("Added entry_regime column to trades table")

        # Backfill from indicators_json
        rows = conn.execute(
            "SELECT id, indicators_json FROM trades WHERE entry_regime IS NULL OR entry_regime='neutral'"
        ).fetchall()
        for row_id, ind_json in rows:
            regime = _classify_entry_regime(ind_json)
            conn.execute("UPDATE trades SET entry_regime=? WHERE id=?", (regime, row_id))
        conn.commit()
        if rows:
            log.info(f"Backfilled entry_regime for {len(rows)} existing trades")

    if "entry_confidence" not in columns:
        conn.execute("ALTER TABLE trades ADD COLUMN entry_confidence INTEGER")
        conn.commit()
        log.info("Added entry_confidence column to trades table")


# ============================================================
# MAIN ENTRY POINT — for standalone or integrated use
# ============================================================
class PositionRiskMonitor:
    """High-level monitor that wraps all Tier-1 logic.

    Can be used standalone or called from PaperTrader.
    """

    def __init__(self, db_conn: sqlite3.Connection = None, db_path: str = None):
        if db_conn is not None:
            self.conn = db_conn
            self._owns_conn = False
        elif db_path:
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._owns_conn = True
        else:
            default_db = "paper_trades/paper_trades.db"
            self.conn = sqlite3.connect(default_db, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._owns_conn = True

        # Ensure schema is up to date
        ensure_monitoring_table(self.conn)
        ensure_entry_regime_column(self.conn)

    def run_check(self, check_date: date = None) -> dict:
        """Execute a full risk check on all open positions.

        Returns the summary dict and also logs + persists the results.
        """
        if check_date is None:
            check_date = date.today()

        # Fetch open trades
        cur = self.conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date"
        )
        open_trades = [dict(r) for r in cur.fetchall()]

        if not open_trades:
            log.info("Position Risk Monitor: no open positions to assess")
            return {"total_positions": 0, "actions": {}}

        # Assess
        health_results = assess_all_positions(open_trades, check_date)

        # Log + persist
        summary = log_risk_report(health_results, check_date)
        persist_health_results(self.conn, health_results, check_date)

        return summary

    def get_positions_to_exit(self, check_date: date = None) -> List[dict]:
        """Return only positions that should be exited (confidence < 35%)."""
        if check_date is None:
            check_date = date.today()

        cur = self.conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date"
        )
        open_trades = [dict(r) for r in cur.fetchall()]
        if not open_trades:
            return []

        health_results = assess_all_positions(open_trades, check_date)
        return [h for h in health_results if h["action"] == "EXIT IMMEDIATELY"]

    def get_positions_to_reduce(self, check_date: date = None) -> List[dict]:
        """Return positions that should be reduced (confidence 35-64%)."""
        if check_date is None:
            check_date = date.today()

        cur = self.conn.execute(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date"
        )
        open_trades = [dict(r) for r in cur.fetchall()]
        if not open_trades:
            return []

        health_results = assess_all_positions(open_trades, check_date)
        return [h for h in health_results if h["action"] == "REDUCE 50%"]

    def close(self):
        if self._owns_conn:
            self.conn.close()


# ============================================================
# CLI — standalone usage
# ============================================================
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler()],
    )

    db_path = sys.argv[1] if len(sys.argv) > 1 else "paper_trades/paper_trades.db"
    if not os.path.exists(db_path):
        log.error(f"Database not found: {db_path}")
        sys.exit(1)

    monitor = PositionRiskMonitor(db_path=db_path)
    summary = monitor.run_check()

    # Print exit / reduce counts
    exits = summary.get("action_counts", {}).get("EXIT IMMEDIATELY", 0)
    reduces = summary.get("action_counts", {}).get("REDUCE 50%", 0)
    holds = summary.get("action_counts", {}).get("HOLD", 0)

    print(f"\nSummary: {exits} EXIT, {reduces} REDUCE, {holds} HOLD "
          f"(avg confidence: {summary.get('avg_adjusted_confidence', 'N/A')}%)")

    monitor.close()
