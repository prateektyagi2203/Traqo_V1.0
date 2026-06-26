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

from trading_config import (
    INSTRUMENT_SECTORS,
    BEARISH_SCORE_RED_ALERT,
    BEARISH_SCORE_YELLOW_ALERT,
    BEARISH_SCORE_ENTRY_DELTA_TRIM,
    BEARISH_SCORE_NSE_GAP_THRESHOLD,
    TRIM_BTST_PERCENTAGE,
    TRIM_SWING_PERCENTAGE,
    TIGHTEN_SL_YELLOW_ALERT,
    SHORT_1D_ENABLED,
    SHORT_1D_FORCE_CLOSE_TIME,
    EXECUTE_RETROACTIVE_SHORT_CLOSE,
)

# Global Sentiment — intraday bearish score monitoring
try:
    from global_sentiment import GlobalSentimentMonitor
    from startup_checkpoint import StartupCheckpoint
    _gsm = GlobalSentimentMonitor()
    _checkpoint = StartupCheckpoint()
    HAVE_GLOBAL_SENTIMENT = True
except ImportError:
    HAVE_GLOBAL_SENTIMENT = False
    _gsm = None
    _checkpoint = None

# Intraday early-exit (dead trade detection)
try:
    from intraday_exit_monitor import check_intraday_early_exit
    HAVE_INTRADAY_EXIT_MONITOR = True
except ImportError:
    HAVE_INTRADAY_EXIT_MONITOR = False

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
                         progress=False, multi_level_index=False)
        if df is None or df.empty:
            return None
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

    # --- Day-0 guard: no price history yet — assessment would be pure noise ---
    # C3 FIX: still check for a regime crash on the day of entry.
    # If the market is already bearish on entry day for a BULLISH trade, flag EXIT.
    if days_held < 1:
        orig_conf = {"HIGH": 80, "MEDIUM": 60, "LOW": 40}.get(
            (trade.get("confidence") or "MEDIUM").upper(), 55
        )
        trade_dir_d0 = (trade.get("direction") or "").upper()
        current_regime_d0 = get_current_market_regime()
        # Crash check: BULLISH trade in bearish regime on entry day
        if trade_dir_d0 == "BULLISH" and current_regime_d0 == "bearish":
            return {
                "trade_id": trade_id, "ticker": ticker,
                "direction": trade_dir_d0, "days_held": 0,
                "horizon_label": trade.get("horizon_label", ""),
                "entry_date": trade["entry_date"],
                "original_confidence": orig_conf,
                "confidence_decay_mult": 1.0, "confidence_decay_pct": 0.0,
                "regime_alignment": False,
                "entry_regime": "unknown", "current_regime": current_regime_d0,
                "regime_shift_penalty": -30,
                "sector": trade.get("sector", "unknown"),
                "sector_momentum": 0.0, "sector_penalty": 0,
                "direction_penalty": -10, "trajectory_adjustment": 0,
                "trajectory_score": 50.0, "trajectory_label": "DAY-0-CRASH",
                "adjusted_confidence": max(0, orig_conf - 40),
                "action_required": True,
                "action": "EXIT IMMEDIATELY",
                "action_detail": "Entered today into bearish regime — regime crash on entry day.",
            }
        return {
            "trade_id": trade_id, "ticker": ticker,
            "direction": trade_dir_d0, "days_held": 0,
            "horizon_label": trade.get("horizon_label", ""),
            "entry_date": trade["entry_date"],
            "original_confidence": orig_conf,
            "confidence_decay_mult": 1.0, "confidence_decay_pct": 0.0,
            "regime_alignment": True,
            "entry_regime": "unknown", "current_regime": current_regime_d0,
            "regime_shift_penalty": 0,
            "sector": trade.get("sector", "unknown"),
            "sector_momentum": 0.0, "sector_penalty": 0,
            "direction_penalty": 0, "trajectory_adjustment": 0,
            "trajectory_score": 50.0, "trajectory_label": "DAY-0",
            "adjusted_confidence": float(orig_conf),
            "action_required": False,
            "action": "HOLD",
            "action_detail": "Entered today — no trajectory data yet. Hold with SL/target.",
        }

    # --- Original confidence (numeric 0-100) ---
    conf_str = (trade.get("confidence") or "MEDIUM").upper()
    original_confidence = {"HIGH": 80, "MEDIUM": 60, "LOW": 40}.get(conf_str, 55)

    # --- Age-based decay ---
    decay_mult = DECAY_SCHEDULE.get(min(days_held, 10), DECAY_FLOOR)
    if days_held > 10:
        decay_mult = DECAY_FLOOR

    # --- Regime comparison (direction-aware) ---
    entry_regime   = _classify_entry_regime(trade.get("indicators_json", "{}"))
    current_regime = get_current_market_regime()
    trade_direction = (trade.get("direction") or "").upper()

    regime_pair = (entry_regime, current_regime)
    raw_shift_penalty = REGIME_SHIFT_PENALTIES.get(regime_pair, 0)

    # Direction-aware adjustment:
    #   BULLISH trade + bearish→bullish = tailwind (contrarian entry paid off) → BONUS
    #   BULLISH trade + bullish→bearish = headwind (trend turned against you)  → PENALTY
    #   BEARISH trade + bullish→bearish = tailwind                             → BONUS
    #   BEARISH trade + bearish→bullish = headwind                             → PENALTY
    if trade_direction == "BULLISH":
        if entry_regime == "bearish" and current_regime == "bullish":
            regime_shift_penalty = +15   # trend now in your favour — no penalty
        elif entry_regime == "bullish" and current_regime == "bearish":
            regime_shift_penalty = -30   # trend turned against you
        else:
            regime_shift_penalty = raw_shift_penalty
    elif trade_direction == "BEARISH":
        if entry_regime == "bullish" and current_regime == "bearish":
            regime_shift_penalty = +15   # trend now in your favour
        elif entry_regime == "bearish" and current_regime == "bullish":
            regime_shift_penalty = -30   # trend turned against you
        else:
            regime_shift_penalty = raw_shift_penalty
    else:
        regime_shift_penalty = raw_shift_penalty

    # --- Sector health ---
    instrument = trade.get("instrument") or ""
    sector = trade.get("sector") or INSTRUMENT_SECTORS.get(instrument, "unknown")
    sector_mom = get_sector_momentum(sector)

    sector_penalty = 0
    for threshold, penalty in SECTOR_MOMENTUM_THRESHOLDS:
        if sector_mom < threshold:
            sector_penalty = penalty
            break

    # --- Direction vs current regime (mismatch bonus / penalty) ---
    # Only penalise if direction contradicts the CURRENT regime AND there was no
    # favourable bearish→bullish (or bullish→bearish) shift already rewarded above.
    direction = trade_direction   # already computed in regime block above
    direction_penalty = 0
    if direction == "BULLISH" and current_regime == "bearish":
        direction_penalty = -10
    elif direction == "BEARISH" and current_regime == "bullish":
        direction_penalty = -10

    # --- Current price (shared by trajectory check and SL-aware gate) ---
    current_price = None
    try:
        _price_df = _get_daily_data(ticker, lookback_days=5)
        if _price_df is not None and not _price_df.empty:
            current_price = float(_price_df["Close"].iloc[-1])
    except Exception:
        pass

    # --- Trajectory health (RAG-informed mid-trade intelligence) ---
    trajectory_adjustment = 0
    trajectory_score = 50.0
    trajectory_label = "N/A"
    if HAVE_TRAJECTORY_HEALTH and current_price is not None:
        try:
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
    elif not HAVE_TRAJECTORY_HEALTH:
        # C4 FIX: trajectory module unavailable — apply a small uncertainty penalty
        # rather than silently returning 0 (which overstates confidence).
        trajectory_adjustment = -5
        trajectory_label = "UNAVAILABLE"
        log.warning(f"Trajectory health module not available for {ticker} — applying -5 uncertainty penalty.")

    # --- SL-aware trajectory penalty reduction ---
    # The SL defines the acceptable loss boundary for this trade.
    # If price is still above SL, the position is within designed risk bounds —
    # halve the trajectory penalty. It's underperforming, but not catastrophic.
    if current_price is not None and trajectory_adjustment < 0:
        try:
            sl_val  = float(trade.get("sl_price") or 0)
            dir_val = (trade.get("direction") or "BULLISH").upper()
            above_sl = (
                (dir_val == "BULLISH" and sl_val > 0 and current_price > sl_val) or
                (dir_val == "BEARISH" and sl_val > 0 and current_price < sl_val)
            )
            if above_sl:
                trajectory_adjustment = int(trajectory_adjustment * 0.5)
                trajectory_label = trajectory_label + "(SL-safe)"
        except Exception:
            pass

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

    if "entry_bearish_score" not in columns:
        conn.execute("ALTER TABLE trades ADD COLUMN entry_bearish_score REAL DEFAULT NULL")
        conn.commit()
        log.info("Added entry_bearish_score column to trades table")


# ============================================================
# GLOBAL BEARISH SCORE — INTRADAY TRIM DECISIONS
# ============================================================

# Per-session set: position_ids already processed today (avoids duplicate logs)
_trim_logged_today: set = set()

# Per-session set: SHORT positions already flagged for force-close today
_short_close_logged_today: set = set()


def check_short_force_close(open_trades: List[dict]) -> List[dict]:
    """
    Check if any SHORT_1d positions need force-closing at 15:15 IST.

    Called every poll cycle from run_check(). Stores a PENDING decision in
    bearish_trim_decisions (trim_reason='Short-force-close') for retroactive
    execution on next startup — handles laptop-closed-at-3PM scenario.

    Returns: list of position dicts that were logged for force-close.
    """
    if not SHORT_1D_ENABLED:
        return []
    if not HAVE_GLOBAL_SENTIMENT or _checkpoint is None:
        return []

    now = datetime.now()
    now_str = now.strftime("%H:%M")

    # Only trigger between 15:15 and 15:28 IST (give small window)
    if now_str < SHORT_1D_FORCE_CLOSE_TIME or now_str > "15:28":
        return []

    short_trades = [
        t for t in open_trades
        if t.get("direction") == "BEARISH" and t.get("horizon_label") == "SHORT_1d"
    ]
    if not short_trades:
        return []

    triggered = []
    for trade in short_trades:
        tid = trade.get("id")
        if tid in _short_close_logged_today:
            continue

        ticker = trade.get("ticker", "UNKNOWN")
        try:
            # Fetch current price for retroactive execution record
            data = _get_daily_data(ticker, lookback_days=2)
            if data is not None and len(data) >= 1:
                current_price = float(data["Close"].iloc[-1])
            else:
                current_price = float(trade.get("entry_price", 0))

            if EXECUTE_RETROACTIVE_SHORT_CLOSE:
                _checkpoint.log_trim_decision(
                    position_id=tid,
                    position_ticker=ticker,
                    decision_timestamp=now.isoformat(),
                    decision_price=current_price,
                    decision_bearish_score=100,   # forced close = max urgency
                    entry_bearish_score=0,
                    trim_percentage=100,
                    trim_reason=f"Short-force-close|{SHORT_1D_FORCE_CLOSE_TIME}|intraday-short-must-close",
                )
                _short_close_logged_today.add(tid)
                log.warning(
                    f"[SHORT_1d FORCE-CLOSE] {ticker} @ ₹{current_price:.2f} "
                    f"logged for retroactive execution at startup"
                )
                triggered.append(trade)
        except Exception as e:
            log.warning(f"[SHORT_1d FORCE-CLOSE] Failed to log {ticker}: {e}")

    return triggered


def check_intraday_bearish_trim(
    open_trades: List[dict],
    entry_bearish_scores: Dict[int, float] = None,
) -> List[dict]:
    """
    Check open positions against the current live bearish score.

    Rules:
      - Only runs during NSE market hours (9:15 AM – 3:25 PM IST)
      - BTST_1d: trim 30% on RED_ALERT OR score-delta >= 25
      - Swing_3d/5d/10d: trim 50% on RED_ALERT only (not score-delta)
      - Decision price stored = HIGH of the current 1-minute candle (conservative)
      - Decision is logged to bearish_trim_decisions; execution happens on startup

    Returns list of triggered trim decision dicts.
    """
    if not HAVE_GLOBAL_SENTIMENT or _gsm is None or _checkpoint is None:
        return []

    # NSE market hours guard
    now = datetime.now()
    market_open  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=25, second=0, microsecond=0)
    if not (market_open <= now <= market_close):
        return []

    # Fetch current bearish score
    try:
        current_score, _ = _gsm.calculate_bearish_score()
    except Exception as e:
        log.warning(f"[INTRADAY TRIM] Bearish score fetch failed: {e}")
        return []

    if entry_bearish_scores is None:
        entry_bearish_scores = {}

    triggered = []

    for trade in open_trades:
        trade_id = trade.get("id")
        horizon  = trade.get("horizon_label", "")
        ticker   = trade.get("ticker", "UNKNOWN")

        is_btst  = "BTST" in horizon.upper()
        is_swing = any(h in horizon.upper() for h in ("SWING", "_3D", "_5D", "_10D"))

        # Skip unknown horizons
        if not is_btst and not is_swing:
            continue

        # Skip if already processed today
        if trade_id in _trim_logged_today:
            continue

        entry_score  = entry_bearish_scores.get(trade_id, 30)
        score_delta  = current_score - entry_score

        # Determine trigger reason
        triggered_reason = None
        if current_score >= BEARISH_SCORE_RED_ALERT:
            triggered_reason = (
                f"RED alert: score={current_score} >= {BEARISH_SCORE_RED_ALERT}"
            )
        elif is_btst and score_delta >= BEARISH_SCORE_ENTRY_DELTA_TRIM:
            # Score-delta only fires for BTST, not Swing
            triggered_reason = (
                f"Score delta +{score_delta:.0f} "
                f"(entry={entry_score}, current={current_score}, "
                f"threshold={BEARISH_SCORE_ENTRY_DELTA_TRIM})"
            )

        if triggered_reason is None:
            continue

        # Trim percentage: BTST=30%, Swing=50%
        trim_pct_to_log = TRIM_BTST_PERCENTAGE if is_btst else TRIM_SWING_PERCENTAGE
        decision_price = _gsm.get_minute_high(ticker, now)

        if decision_price is None:
            # Fallback: last daily close (ticker already contains .NS from DB)
            try:
                yf_sym = ticker if (".NS" in ticker or ".BO" in ticker or ticker.startswith("^")) else f"{ticker}.NS"
                df = _get_daily_data(yf_sym, lookback_days=2)
                if df is not None and len(df) > 0:
                    decision_price = float(df["Close"].iloc[-1])
            except Exception:
                pass

        if decision_price is None:
            log.warning(f"[INTRADAY TRIM] No price for {ticker} — skipping")
            continue

        # Log trim decision to DB
        try:
            _checkpoint.ensure_trim_table()
            decision_id = _checkpoint.log_trim_decision(
                position_id=trade_id,
                position_ticker=ticker,
                decision_price=decision_price,
                bearish_score=current_score,
                entry_bearish_score=entry_score,
                trim_reason=triggered_reason,
                trim_percentage=trim_pct_to_log,
            )

            _trim_logged_today.add(trade_id)

            log.warning(
                f"[INTRADAY TRIM] TRIGGERED: {ticker} ({'BTST' if is_btst else 'SWING'}) — "
                f"score={current_score}, delta={score_delta:.0f}, "
                f"trim={trim_pct_to_log}%, price={decision_price:.2f}, "
                f"decision_id={decision_id}"
            )

            triggered.append({
                "trade_id":       trade_id,
                "ticker":         ticker,
                "horizon":        horizon,
                "decision_id":    decision_id,
                "decision_price": decision_price,
                "current_score":  current_score,
                "entry_score":    entry_score,
                "score_delta":    score_delta,
                "trim_pct":       trim_pct_to_log,
                "reason":         triggered_reason,
            })

        except Exception as e:
            log.error(f"[INTRADAY TRIM] Failed to log decision for {ticker}: {e}")

    if triggered:
        log.warning(
            f"[INTRADAY TRIM] {len(triggered)} trim decision(s) logged. "
            f"Will execute retroactively on next startup."
        )

    return triggered


def reset_intraday_trim_cache():
    """Clear per-session duplicate-prevention cache. Call at start of each trading day."""
    global _trim_logged_today
    _trim_logged_today = set()


# ============================================================
# NSE PRE-OPEN GAP CHECK (9:15–9:25 gate)
# ============================================================

_preopen_gap_logged_today: Optional[str] = None  # date string, avoid running twice per day


def check_nse_preopen_gap(open_trades: List[dict]) -> List[dict]:
    """
    Run once per trading day during the 9:15–9:25 window.
    If Nifty opens with a gap-down worse than BEARISH_SCORE_NSE_GAP_THRESHOLD (-0.75%),
    log exit/trim decisions for all open positions before the day unfolds.

      BTST_1d  → 100% exit (full position)
      Swing_*  → 50% trim

    Returns list of decision dicts logged.
    """
    global _preopen_gap_logged_today
    if not HAVE_GLOBAL_SENTIMENT or _checkpoint is None:
        return []

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # Only fire once per calendar day
    if _preopen_gap_logged_today == today_str:
        return []

    gate_open  = now.replace(hour=9, minute=15, second=0, microsecond=0)
    gate_close = now.replace(hour=9, minute=25, second=0, microsecond=0)
    if not (gate_open <= now <= gate_close):
        return []

    try:
        # Previous day close
        prev_data = yf.download('^NSEI', period='2d', progress=False, multi_level_index=False)
        if prev_data is None or len(prev_data) < 2:
            return []
        prev_close = float(prev_data['Close'].iloc[-2])

        # Today's open (first 5-minute candle)
        open_data = yf.download('^NSEI', period='1d', interval='5m', progress=False, multi_level_index=False)
        if open_data is None or len(open_data) == 0:
            return []
        today_open = float(open_data['Open'].iloc[0])

        gap_pct = (today_open - prev_close) / prev_close * 100
        log.info(
            f"[PRE-OPEN GAP] Nifty gap: {gap_pct:+.2f}%"
            f" (prev_close={prev_close:.0f}, open={today_open:.0f})"
        )

        if gap_pct > BEARISH_SCORE_NSE_GAP_THRESHOLD:
            _preopen_gap_logged_today = today_str
            return []  # Gap not severe enough

        triggered = []
        for trade in open_trades:
            tid     = trade.get("id")
            ticker  = trade.get("ticker", "UNKNOWN")
            horizon = trade.get("horizon_label", "")
            is_btst = "BTST" in horizon.upper()
            trim_pct = 100 if is_btst else 50

            try:
                price_df = _get_daily_data(ticker, lookback_days=1)
                decision_price = (
                    float(price_df["Close"].iloc[-1])
                    if price_df is not None and len(price_df) > 0
                    else float(trade.get("entry_price", 0))
                )
            except Exception:
                decision_price = float(trade.get("entry_price", 0))

            reason = (
                f"Pre-open gap: Nifty {gap_pct:+.2f}%"
                f" (threshold={BEARISH_SCORE_NSE_GAP_THRESHOLD}%)"
            )
            did = _checkpoint.log_trim_decision(
                position_id=tid,
                position_ticker=ticker,
                decision_price=decision_price,
                bearish_score=None,
                entry_bearish_score=None,
                trim_reason=reason,
                trim_percentage=trim_pct,
            )
            triggered.append({
                "trade_id": tid, "ticker": ticker,
                "horizon": horizon, "trim_pct": trim_pct, "decision_id": did,
            })
            log.warning(
                f"[PRE-OPEN GAP] {'100% exit' if trim_pct == 100 else '50% trim'}: "
                f"{ticker} ({horizon}) → decision #{did}"
            )

        _preopen_gap_logged_today = today_str
        return triggered

    except Exception as e:
        log.warning(f"[PRE-OPEN GAP] Check failed: {e}")
        return []


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

        # --- GLOBAL BEARISH: NSE pre-open gap check (9:15–9:25 window) ---
        if HAVE_GLOBAL_SENTIMENT:
            try:
                gap_decisions = check_nse_preopen_gap(open_trades)
                if gap_decisions:
                    log.warning(
                        f"[PRE-OPEN GAP] {len(gap_decisions)} position(s) "
                        f"flagged for exit/trim"
                    )
            except Exception as e:
                log.warning(f"[PRE-OPEN GAP] Check failed: {e}")

        # --- GLOBAL BEARISH: Intraday trim check (BTST 30% / Swing 50% on RED_ALERT) ---
        if HAVE_GLOBAL_SENTIMENT:
            try:
                entry_scores = {
                    t["id"]: (t.get("entry_bearish_score") or 30)
                    for t in open_trades
                }
                intraday_trims = check_intraday_bearish_trim(open_trades, entry_scores)
                if intraday_trims:
                    log.warning(
                        f"[GLOBAL BEARISH] {len(intraday_trims)} trim "
                        f"decision(s) logged this cycle"
                    )
            except Exception as e:
                log.warning(f"[GLOBAL BEARISH] Intraday check failed: {e}")

        # --- GLOBAL BEARISH: YELLOW_ALERT — tighten SL on BULLISH positions ---
        if HAVE_GLOBAL_SENTIMENT:
            try:
                yellow_score, _ = _gsm.calculate_bearish_score()
                if BEARISH_SCORE_YELLOW_ALERT <= yellow_score < BEARISH_SCORE_RED_ALERT:
                    tighten_count = 0
                    for trade in open_trades:
                        if trade.get("direction", "").upper() != "BULLISH":
                            continue
                        sl   = trade.get("sl_price") or 0
                        entry = trade.get("entry_price") or 0
                        if not sl or not entry or sl >= entry:
                            continue
                        # Tighten SL by TIGHTEN_SL_YELLOW_ALERT (25%) toward entry price
                        new_sl = sl + (entry - sl) * TIGHTEN_SL_YELLOW_ALERT
                        self.conn.execute(
                            "UPDATE trades SET sl_price=? WHERE id=? AND status='OPEN'",
                            (round(new_sl, 2), trade["id"]),
                        )
                        tighten_count += 1
                    if tighten_count:
                        self.conn.commit()
                        log.warning(
                            f"[YELLOW ALERT] Tightened SL for {tighten_count} "
                            f"BULLISH position(s) (score={yellow_score})"
                        )
            except Exception as e:
                log.warning(f"[YELLOW ALERT] SL tighten failed: {e}")

        # --- INTRADAY EARLY-EXIT: dead-trade force exits (BTST_1d) ---
        if HAVE_INTRADAY_EXIT_MONITOR:
            try:
                early_exits = check_intraday_early_exit(open_trades)
                if early_exits:
                    log.warning(
                        f"[EARLY EXIT] {len(early_exits)} dead-trade decision(s) "
                        f"logged this cycle"
                    )
            except Exception as e:
                log.warning(f"[EARLY EXIT] Intraday early-exit check failed: {e}")

        # --- SHORT_1d: Force-close at 15:15 IST (no overnight shorts allowed) ---
        if SHORT_1D_ENABLED:
            try:
                short_closes = check_short_force_close(open_trades)
                if short_closes:
                    log.warning(
                        f"[SHORT_1d] {len(short_closes)} SHORT position(s) logged "
                        f"for force-close at {SHORT_1D_FORCE_CLOSE_TIME} IST"
                    )
            except Exception as e:
                log.warning(f"[SHORT_1d] Force-close check failed: {e}")

        # Log + persist
        summary = log_risk_report(health_results, check_date)
        persist_health_results(self.conn, health_results, check_date)

        # --- AUTO-EXECUTE: pipe confidence-decay decisions into trim queue ---
        # EXIT IMMEDIATELY → 100% trim (full close on next startup)
        # REDUCE 50%       →  50% trim (half position on next startup)
        if HAVE_GLOBAL_SENTIMENT and _checkpoint is not None:
            try:
                _checkpoint.ensure_trim_table()
                auto_logged = 0
                for h in health_results:
                    action = h.get("action", "HOLD")
                    if action not in ("EXIT IMMEDIATELY", "REDUCE 50%"):
                        continue
                    trade_id = h["trade_id"]
                    ticker   = h["ticker"]

                    # Skip if a decision was already logged today for this position
                    already = self.conn.execute(
                        """SELECT 1 FROM bearish_trim_decisions
                           WHERE position_id = ?
                             AND date(decision_timestamp) = date('now')
                             AND execution_status IN ('PENDING','EXECUTED','EXECUTED_FULL_EXIT')
                           LIMIT 1""",
                        (trade_id,),
                    ).fetchone()
                    if already:
                        continue

                    trim_pct = 100 if action == "EXIT IMMEDIATELY" else 50

                    # With qty=1 (standard paper trade), 50% trim = 0 → treat as full exit
                    try:
                        trade_qty = self.conn.execute(
                            "SELECT quantity FROM trades WHERE id=?", (trade_id,)
                        ).fetchone()
                        if trade_qty and int(trade_qty[0] or 1) == 1:
                            trim_pct = 100
                    except Exception:
                        pass

                    # Use last close as decision price
                    try:
                        yf_sym = (ticker if (".NS" in ticker or ".BO" in ticker
                                  or ticker.startswith("^")) else f"{ticker}.NS")
                        df = _get_daily_data(yf_sym, lookback_days=2)
                        decision_price = (
                            float(df["Close"].iloc[-1])
                            if df is not None and len(df) > 0
                            else float(self.conn.execute(
                                "SELECT entry_price FROM trades WHERE id=?",
                                (trade_id,)
                            ).fetchone()[0] or 0)
                        )
                    except Exception:
                        decision_price = 0.0

                    if not decision_price:
                        continue

                    # --- PRICE-REALITY GATE ---
                    # Never auto-exit a profitable trade based on confidence alone.
                    # If current price > entry price, the trade is making money.
                    # Let the SL / target / expiry handle it naturally.
                    try:
                        entry_row = self.conn.execute(
                            "SELECT entry_price, direction FROM trades WHERE id=?",
                            (trade_id,)
                        ).fetchone()
                        if entry_row:
                            ep        = float(entry_row[0] or 0)
                            direction = (entry_row[1] or "BULLISH").upper()
                            if ep > 0:
                                if direction == "BULLISH" and decision_price > ep:
                                    log.info(
                                        f"[AUTO-QUEUE] SKIPPED {ticker}: profitable "
                                        f"({decision_price:.2f} > entry {ep:.2f}), "
                                        f"let SL/target handle it"
                                    )
                                    continue
                                elif direction == "BEARISH" and decision_price < ep:
                                    log.info(
                                        f"[AUTO-QUEUE] SKIPPED {ticker}: profitable short "
                                        f"({decision_price:.2f} < entry {ep:.2f}), "
                                        f"let SL/target handle it"
                                    )
                                    continue
                    except Exception:
                        pass  # if we can't check, proceed with the exit

                    # Also skip trades entered today (no trajectory data yet — too early to judge)
                    if h.get("days_held", 0) < 1:
                        log.info(
                            f"[AUTO-QUEUE] SKIPPED {ticker}: entered today (age=0d), "
                            f"too early to judge trajectory"
                        )
                        continue

                    reason = (
                        f"confidence-decay {action}: "
                        f"conf={h['adjusted_confidence']:.1f}% "
                        f"(age={h['days_held']}d, regime={h['entry_regime']}"
                        f"→{h['current_regime']}, sector={h['sector_momentum']:+.2f}%)"
                    )
                    _checkpoint.log_trim_decision(
                        position_id=trade_id,
                        position_ticker=ticker,
                        decision_price=decision_price,
                        bearish_score=None,
                        entry_bearish_score=None,
                        trim_reason=reason,
                        trim_percentage=trim_pct,
                    )
                    auto_logged += 1
                    log.warning(
                        f"[AUTO-QUEUE] {action}: {ticker} "
                        f"({trim_pct}% @ {decision_price:.2f}) → PENDING execution"
                    )

                if auto_logged:
                    log.warning(
                        f"[AUTO-QUEUE] {auto_logged} decision(s) queued. "
                        f"Will execute on next paper_trader.py startup."
                    )
            except Exception as e:
                log.warning(f"[AUTO-QUEUE] Failed to log confidence-decay decisions: {e}")

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
