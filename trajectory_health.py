"""
Trajectory Health — RAG-Informed Mid-Trade Exit Intelligence
=============================================================
Compares a live position's actual progress against the historical
return curve for the same pattern+context, as stored in the RAG's
147K+ enriched documents.

The RAG already stores forward returns at multiple horizons for every
historical pattern occurrence:
    fwd_1_return_pct, fwd_3_return_pct, fwd_5_return_pct,
    fwd_10_return_pct, fwd_25_return_pct
and the corresponding MFE (Max Favourable Excursion) at each:
    mfe_1, mfe_3, mfe_5, mfe_10, mfe_25

This module builds an *expected return trajectory* from those fields,
then scores a live trade's actual progress against it.

Outputs a **trajectory_health_score** (0–100) that feeds directly into
the Tier-1 position risk monitor's confidence formula.

Example:
    A Bullish Engulfing was entered 5 days ago.  The RAG says the median
    cumulative return by day 5 for this pattern is +2.3%.  The trade is
    currently at -0.8%.  That puts it in the bottom quartile of historical
    outcomes → trajectory_health_score = 25 → Tier-1 confidence drops →
    EXIT or REDUCE triggered.

Reference: POSITION_RISK_MANAGEMENT_FRAMEWORK.md (Tier 1 enhancement)
"""

import logging
import json
import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd

log = logging.getLogger("trajectory_health")

# Horizons the RAG stores (in trading days / candles)
RAG_HORIZONS = [1, 3, 5, 10, 25]

# Trajectory health thresholds
TRAJECTORY_EXCELLENT = 75   # above median + strong follow-through
TRAJECTORY_HEALTHY   = 50   # around median — on track
TRAJECTORY_WEAK      = 25   # bottom quartile — underperforming
TRAJECTORY_CRITICAL  = 10   # bottom decile — likely failure

# Score → confidence penalty mapping (fed into Tier-1)
# score 0-25  → heavy penalty, score 75-100 → no penalty (slight bonus)
TRAJECTORY_PENALTY_MAP = [
    (25,  -20),   # critical/weak: -20 to confidence
    (40,  -12),   # below-average: -12
    (55,   -5),   # slightly below median: -5
    (70,    0),   # on track: neutral
    (100,  +5),   # outperforming: slight confidence boost
]


# ============================================================
# TRAJECTORY PROFILE BUILDER
# ============================================================
class TrajectoryProfiler:
    """Builds expected return trajectories from RAG pattern matches."""

    def __init__(self, statistical_predictor=None):
        """
        Parameters
        ----------
        statistical_predictor : StatisticalPredictor, optional
            If provided, uses its in-memory docs + indexes for match
            retrieval.  If None, attempts to import and create one.
        """
        self.sp = statistical_predictor
        if self.sp is None:
            try:
                from statistical_predictor import StatisticalPredictor
                self.sp = StatisticalPredictor()
            except Exception as e:
                log.error(f"Failed to load StatisticalPredictor: {e}")

    def build_expected_trajectory(
        self,
        pattern: str,
        direction: str,
        timeframe: str = "daily",
        trend_short: str = None,
        rsi_zone: str = None,
        instrument: str = None,
    ) -> Optional[Dict]:
        """Build the expected return trajectory for a pattern+context.

        Returns a dict keyed by horizon (1,3,5,10,25) with:
            median_return, mean_return, p25, p75, p10, p90,
            median_mfe, count
        Or None if insufficient data.
        """
        if self.sp is None:
            return None

        # Retrieve matching documents using the same tiered logic as entry
        indices, tier = self.sp._retrieve_matches(
            pattern=pattern,
            timeframe=timeframe,
            trend_short=trend_short,
            rsi_zone=rsi_zone,
            instrument=instrument,
        )

        if len(indices) < 5:
            log.debug(f"Insufficient matches for {pattern} trajectory: {len(indices)}")
            return None

        matches = [self.sp.docs[i] for i in indices]
        # Sort by datetime descending, cap to TOP_K
        matches.sort(key=lambda d: d.get("datetime", ""), reverse=True)
        from trading_config import TOP_K
        matches = matches[:TOP_K]

        trajectory = {}
        is_bearish = direction.upper() == "BEARISH"

        for n in RAG_HORIZONS:
            ret_key = f"fwd_{n}_return_pct"
            mfe_key = f"mfe_{n}"
            mae_key = f"mae_{n}"

            returns = []
            mfes = []
            maes = []

            for m in matches:
                ret = m.get(ret_key)
                if ret is not None:
                    r = float(ret)
                    # For bearish trades, negate returns (positive = good for short)
                    returns.append(-r if is_bearish else r)

                mfe = m.get(mfe_key)
                if mfe is not None:
                    mfes.append(float(mfe))

                mae = m.get(mae_key)
                if mae is not None:
                    maes.append(float(mae))

            if len(returns) < 5:
                continue

            arr = np.array(returns)
            trajectory[n] = {
                "median_return": round(float(np.median(arr)), 4),
                "mean_return": round(float(np.mean(arr)), 4),
                "p10": round(float(np.percentile(arr, 10)), 4),
                "p25": round(float(np.percentile(arr, 25)), 4),
                "p75": round(float(np.percentile(arr, 75)), 4),
                "p90": round(float(np.percentile(arr, 90)), 4),
                "std": round(float(np.std(arr)), 4),
                "median_mfe": round(float(np.median(mfes)), 4) if mfes else 0.0,
                "median_mae": round(float(np.median(maes)), 4) if maes else 0.0,
                "count": len(returns),
            }

        if not trajectory:
            return None

        return {
            "pattern": pattern,
            "direction": direction.upper(),
            "tier": tier,
            "n_matches": len(matches),
            "horizons": trajectory,
        }


# ============================================================
# TRAJECTORY HEALTH SCORER
# ============================================================
def _interpolate_expected(trajectory_horizons: dict, days_held: int) -> Optional[dict]:
    """Interpolate expected returns at an arbitrary days_held value.

    The RAG has data at horizons [1, 3, 5, 10, 25].  If the trade is at
    day 4, we linearly interpolate between the day-3 and day-5 profiles.

    Returns dict with: median_return, p25, p75, p10
    Or None if interpolation is not possible.
    """
    available = sorted(trajectory_horizons.keys())
    if not available:
        return None

    # Exact match
    if days_held in trajectory_horizons:
        h = trajectory_horizons[days_held]
        return {"median": h["median_return"], "p25": h["p25"],
                "p75": h["p75"], "p10": h["p10"]}

    # Clamp to range
    if days_held <= available[0]:
        h = trajectory_horizons[available[0]]
        return {"median": h["median_return"], "p25": h["p25"],
                "p75": h["p75"], "p10": h["p10"]}
    if days_held >= available[-1]:
        h = trajectory_horizons[available[-1]]
        return {"median": h["median_return"], "p25": h["p25"],
                "p75": h["p75"], "p10": h["p10"]}

    # Find bounding horizons
    lower = max(h for h in available if h < days_held)
    upper = min(h for h in available if h > days_held)

    # Linear interpolation weight
    w = (days_held - lower) / (upper - lower)

    lo = trajectory_horizons[lower]
    hi = trajectory_horizons[upper]

    return {
        "median": lo["median_return"] + w * (hi["median_return"] - lo["median_return"]),
        "p25":    lo["p25"]           + w * (hi["p25"]           - lo["p25"]),
        "p75":    lo["p75"]           + w * (hi["p75"]           - lo["p75"]),
        "p10":    lo["p10"]           + w * (hi["p10"]           - lo["p10"]),
    }


def score_trajectory_health(
    actual_return_pct: float,
    trajectory_horizons: dict,
    days_held: int,
) -> dict:
    """Score how well a trade is tracking vs. its historical trajectory.

    Parameters
    ----------
    actual_return_pct : float
        The trade's current unrealised return (directionally adjusted:
        positive = good for the trade direction).
    trajectory_horizons : dict
        Output of TrajectoryProfiler.build_expected_trajectory()["horizons"]
    days_held : int
        Number of trading days the position has been open.

    Returns
    -------
    dict with:
        score (0-100), percentile_vs_history, expected_median,
        actual_return, gap_pct, confidence_adjustment, label
    """
    expected = _interpolate_expected(trajectory_horizons, days_held)
    if expected is None:
        return {
            "score": 50, "percentile_vs_history": 50,
            "expected_median": 0, "actual_return": actual_return_pct,
            "gap_pct": 0, "confidence_adjustment": 0,
            "label": "NO_DATA",
        }

    median = expected["median"]
    p25 = expected["p25"]
    p75 = expected["p75"]
    p10 = expected["p10"]

    # Compute where actual_return sits in the historical distribution
    # Map actual return to a 0-100 score using the percentile brackets
    if actual_return_pct >= p75:
        # Top quartile → score 75-100
        range_width = max(p75 * 1.5 - p75, 0.5)  # avoid div-by-zero
        score = 75 + min(25, (actual_return_pct - p75) / range_width * 25)
    elif actual_return_pct >= median:
        # 50th-75th percentile → score 50-75
        range_width = max(p75 - median, 0.01)
        score = 50 + (actual_return_pct - median) / range_width * 25
    elif actual_return_pct >= p25:
        # 25th-50th percentile → score 25-50
        range_width = max(median - p25, 0.01)
        score = 25 + (actual_return_pct - p25) / range_width * 25
    elif actual_return_pct >= p10:
        # 10th-25th percentile → score 10-25
        range_width = max(p25 - p10, 0.01)
        score = 10 + (actual_return_pct - p10) / range_width * 15
    else:
        # Below 10th percentile → score 0-10
        score = max(0, 10 + (actual_return_pct - p10) / max(abs(p10), 0.5) * 10)

    score = max(0, min(100, score))

    # Gap from median
    gap_pct = round(actual_return_pct - median, 4)

    # Compute confidence adjustment from score
    conf_adj = 0
    for threshold, penalty in TRAJECTORY_PENALTY_MAP:
        if score <= threshold:
            conf_adj = penalty
            break

    # Label
    if score >= TRAJECTORY_EXCELLENT:
        label = "OUTPERFORMING"
    elif score >= TRAJECTORY_HEALTHY:
        label = "ON_TRACK"
    elif score >= TRAJECTORY_WEAK:
        label = "UNDERPERFORMING"
    elif score >= TRAJECTORY_CRITICAL:
        label = "WEAK"
    else:
        label = "CRITICAL"

    return {
        "score": round(score, 1),
        "percentile_vs_history": round(score, 1),
        "expected_median": round(median, 4),
        "actual_return": round(actual_return_pct, 4),
        "gap_pct": gap_pct,
        "confidence_adjustment": conf_adj,
        "label": label,
    }


# ============================================================
# HIGH-LEVEL API: ASSESS ONE TRADE
# ============================================================
def assess_trade_trajectory(
    trade: dict,
    current_price: float,
    check_date: date = None,
    profiler: "TrajectoryProfiler" = None,
) -> dict:
    """Full trajectory health assessment for a single open trade.

    Parameters
    ----------
    trade : dict
        Row from the trades table (must have: entry_price, entry_date,
        direction, patterns, indicators_json, ticker, instrument).
    current_price : float
        The stock's current / latest close price.
    check_date : date, optional
        Date to assess against.  Defaults to today.
    profiler : TrajectoryProfiler, optional
        Reusable profiler instance (avoids re-loading the predictor).

    Returns
    -------
    dict with trajectory_health, expected_curve, and confidence_adjustment
    """
    if check_date is None:
        check_date = date.today()

    entry_price = trade["entry_price"]
    direction = (trade.get("direction") or "BULLISH").upper()

    # Compute actual return (direction-adjusted)
    if direction == "BULLISH":
        actual_return_pct = (current_price - entry_price) / entry_price * 100
    else:
        actual_return_pct = (entry_price - current_price) / entry_price * 100

    entry_date = date.fromisoformat(trade["entry_date"])
    days_held = (check_date - entry_date).days
    # Approximate trading days (exclude weekends)
    trading_days_held = max(1, int(days_held * 5 / 7))

    # Extract context from trade
    patterns = (trade.get("patterns") or "").split(",")
    pattern = patterns[0].strip() if patterns else ""
    if not pattern:
        return _no_data_result(actual_return_pct, trading_days_held)

    # Get indicator context from entry
    indicators = {}
    ind_json = trade.get("indicators_json")
    if ind_json:
        try:
            indicators = json.loads(ind_json) if isinstance(ind_json, str) else (ind_json or {})
        except (json.JSONDecodeError, TypeError):
            indicators = {}

    trend_short = indicators.get("trend_short")
    rsi_zone = indicators.get("rsi_zone")
    instrument = trade.get("instrument")

    # Build expected trajectory
    if profiler is None:
        profiler = TrajectoryProfiler()

    trajectory = profiler.build_expected_trajectory(
        pattern=pattern,
        direction=direction,
        timeframe="daily",
        trend_short=trend_short,
        rsi_zone=rsi_zone,
        instrument=instrument,
    )

    if trajectory is None:
        return _no_data_result(actual_return_pct, trading_days_held)

    # Score
    health = score_trajectory_health(
        actual_return_pct=actual_return_pct,
        trajectory_horizons=trajectory["horizons"],
        days_held=trading_days_held,
    )

    return {
        "trade_id": trade.get("id"),
        "ticker": trade.get("ticker"),
        "pattern": pattern,
        "direction": direction,
        "days_held": days_held,
        "trading_days_held": trading_days_held,
        "entry_price": entry_price,
        "current_price": current_price,
        "actual_return_pct": round(actual_return_pct, 2),
        "trajectory_health": health,
        "expected_curve": trajectory["horizons"],
        "confidence_adjustment": health["confidence_adjustment"],
        "n_rag_matches": trajectory["n_matches"],
        "match_tier": trajectory["tier"],
    }


def _no_data_result(actual_return_pct: float, trading_days_held: int) -> dict:
    """Return a neutral result when no trajectory data is available."""
    return {
        "trajectory_health": {
            "score": 50, "percentile_vs_history": 50,
            "expected_median": 0, "actual_return": round(actual_return_pct, 4),
            "gap_pct": 0, "confidence_adjustment": 0, "label": "NO_DATA",
        },
        "confidence_adjustment": 0,
        "expected_curve": {},
    }


# ============================================================
# BATCH API: ASSESS ALL OPEN TRADES
# ============================================================
def assess_all_trajectories(
    trades: list,
    check_date: date = None,
    profiler: "TrajectoryProfiler" = None,
) -> List[dict]:
    """Assess trajectory health for a list of open trades.

    Fetches current prices via yfinance in a single batch, then scores
    each trade against its historical trajectory.

    Returns list of assessment dicts sorted by health score (worst first).
    """
    if not trades:
        return []

    if check_date is None:
        check_date = date.today()
    if profiler is None:
        profiler = TrajectoryProfiler()

    # Batch-fetch current prices
    tickers = list(set(t["ticker"] for t in trades))
    prices = _batch_fetch_prices(tickers)

    results = []
    for trade in trades:
        ticker = trade["ticker"]
        current_price = prices.get(ticker)
        if current_price is None:
            continue

        try:
            assessment = assess_trade_trajectory(
                trade=trade,
                current_price=current_price,
                check_date=check_date,
                profiler=profiler,
            )
            assessment["trade_id"] = trade.get("id")
            assessment["ticker"] = ticker
            results.append(assessment)
        except Exception as e:
            log.warning(f"Trajectory assessment failed for {ticker}: {e}")

    # Sort by health score ascending (worst first)
    results.sort(key=lambda r: r.get("trajectory_health", {}).get("score", 50))
    return results


def _batch_fetch_prices(tickers: list) -> dict:
    """Fetch latest close prices for a list of tickers.

    Returns dict: ticker -> latest_close_price
    """
    prices = {}
    try:
        import yfinance as yf
        for ticker in tickers:
            try:
                df = yf.download(ticker, period="5d", progress=False, interval="1d")
                if df is not None and not df.empty:
                    close_col = df["Close"]
                    if hasattr(close_col, "columns"):
                        close_col = close_col.iloc[:, 0]
                    prices[ticker] = float(close_col.iloc[-1])
            except Exception as e:
                log.debug(f"Price fetch failed for {ticker}: {e}")
    except ImportError:
        log.warning("yfinance not available — cannot fetch prices")
    return prices


# ============================================================
# CLI
# ============================================================
if __name__ == "__main__":
    import sqlite3
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "paper_trades/paper_trades.db"
    if not os.path.exists(db_path):
        print(f"DB not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM trades WHERE status='OPEN' ORDER BY entry_date"
    ).fetchall()
    conn.close()

    trades = [dict(r) for r in rows]
    if not trades:
        print("No open trades found.")
        sys.exit(0)

    print(f"Assessing trajectory health for {len(trades)} open trade(s)...\n")
    profiler = TrajectoryProfiler()
    results = assess_all_trajectories(trades, profiler=profiler)

    for r in results:
        h = r.get("trajectory_health", {})
        print(f"  {r['ticker']:<16} {r.get('pattern',''):<25} "
              f"days={r.get('days_held',0):>3}  "
              f"actual={r.get('actual_return_pct',0):>+6.2f}%  "
              f"expected={h.get('expected_median',0):>+6.4f}%  "
              f"score={h.get('score',50):>5.1f}  "
              f"adj={h.get('confidence_adjustment',0):>+3}  "
              f"[{h.get('label','?')}]")
    print()
    print("Done.")
