"""
Intraday Early-Exit Monitor — Dead Trade Detection
====================================================
Detects BTST_1d positions that have no recovery prospects (based on RAG trajectory
health) and are still bleeding out after 1:30 PM IST. Logs early-exit decisions for
retroactive execution when laptop opens.

Triple-AND Exit Rule:
  1. Time >= 1:30 PM IST
  2. Current price < entry * (1 - 0.005) = below -0.5%
  3. RAG trajectory health score <= 40 (CRITICAL or WEAK)

→ Force-exit 100% at decision-time price. Laptop offline? Execute at stored price.
"""

import logging
from datetime import datetime, time
from typing import Dict, List, Optional
import yfinance as yf

log = logging.getLogger("intraday_exit_monitor")


def get_trajectory_score(trade: dict) -> Optional[int]:
    """
    Reuse trajectory_health.py engine to get current trajectory score.
    Returns trajectory_score (0-100) or None if unavailable.
    """
    try:
        from trajectory_health import TrajectoryProfiler, assess_trade_trajectory
        from position_risk_monitor import _get_daily_data
        
        ticker = trade.get("ticker", "UNKNOWN")
        df = _get_daily_data(f"{ticker}.NS", lookback_days=5)
        
        if df is None or len(df) < 2:
            return None
        
        try:
            current_price = float(df["Close"].iloc[-1])
        except (ValueError, IndexError):
            return None
        
        profiler = TrajectoryProfiler()
        traj = assess_trade_trajectory(
            trade=trade,
            current_price=current_price,
            check_date=__import__('datetime').date.today(),
            profiler=profiler,
        )
        
        return traj.get("trajectory_health", {}).get("score", None)
        
    except Exception as e:
        log.warning(f"Failed to get trajectory score for {trade.get('ticker')}: {e}")
        return None


def check_intraday_early_exit(
    open_trades: List[dict],
) -> List[dict]:
    """
    Check all BTST_1d positions for dead-trade patterns.
    
    Triple-AND conditions:
      1. Time >= 1:30 PM IST
      2. Current price < entry * 0.995 (below -0.5%)
      3. Trajectory score <= 40 (CRITICAL/WEAK)
    
    Returns list of triggered early-exit decisions.
    Logs to intraday_exit_decisions table for retroactive execution.
    """
    from trading_config import (
        EARLY_EXIT_CUTOFF_TIME,
        EARLY_EXIT_PRICE_THRESHOLD,
        EARLY_EXIT_TRAJECTORY_MAX,
    )
    
    now = datetime.now()
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    # Parse cutoff time string (e.g., "13:30")
    try:
        cutoff_parts = EARLY_EXIT_CUTOFF_TIME.split(":")
        cutoff_hour = int(cutoff_parts[0])
        cutoff_min = int(cutoff_parts[1]) if len(cutoff_parts) > 1 else 0
        cutoff_time = now.replace(hour=cutoff_hour, minute=cutoff_min, second=0, microsecond=0)
    except Exception:
        cutoff_time = now.replace(hour=13, minute=30, second=0, microsecond=0)
    
    # Guard: market hours only
    if not (market_open <= now <= market_close):
        return []
    
    triggered = []
    
    for trade in open_trades:
        trade_id = trade.get("id")
        horizon = trade.get("horizon_label", "")
        ticker = trade.get("ticker", "UNKNOWN")
        entry_price = trade.get("entry_price", 0)
        
        # Only BTST_1d
        if "BTST" not in horizon.upper() or "1d" not in horizon.lower():
            continue
        
        # Condition 1: Time check
        if now < cutoff_time:
            continue
        
        # Condition 2: Price check — current price vs entry
        try:
            df = yf.download(f"{ticker}.NS", period="1d", progress=False)
            if df is None or len(df) == 0:
                continue
            current_price = float(df["Close"].iloc[-1])
        except Exception as e:
            log.warning(f"Failed to fetch price for {ticker}: {e}")
            continue
        
        pct_change = (current_price - entry_price) / entry_price * 100
        if pct_change >= EARLY_EXIT_PRICE_THRESHOLD:
            # Trade is above -0.5%, not yet triggering
            continue
        
        # Condition 3: Trajectory health check
        traj_score = get_trajectory_score(trade)
        if traj_score is None or traj_score > EARLY_EXIT_TRAJECTORY_MAX:
            # Trajectory is not weak enough, or not available
            continue
        
        # All three conditions met → log early-exit decision
        try:
            from startup_checkpoint import StartupCheckpoint
            cp = StartupCheckpoint()
            cp.ensure_trim_table()  # Ensure table exists
            
            decision_id = cp.log_trim_decision(
                position_id=trade_id,
                position_ticker=ticker,
                decision_price=current_price,
                bearish_score=None,  # N/A for early exit
                entry_bearish_score=None,
                trim_reason=(
                    f"Early-exit dead trade: time={now.strftime('%H:%M')}, "
                    f"price={pct_change:.2f}%, traj_score={traj_score}"
                ),
                trim_percentage=100,  # Always 100% for early exit
            )
            
            log.warning(
                f"[EARLY EXIT] TRIGGERED: {ticker} (BTST_1d) — "
                f"time={now.strftime('%H:%M')}, "
                f"price={pct_change:.2f}% (threshold={EARLY_EXIT_PRICE_THRESHOLD}%), "
                f"traj={traj_score} (threshold={EARLY_EXIT_TRAJECTORY_MAX}), "
                f"decision_id={decision_id}"
            )
            
            triggered.append({
                "trade_id": trade_id,
                "ticker": ticker,
                "decision_id": decision_id,
                "decision_price": current_price,
                "pct_change": pct_change,
                "trajectory_score": traj_score,
                "reason": "dead_trade_detected",
            })
            
        except Exception as e:
            log.error(f"Failed to log early-exit for {ticker}: {e}")
    
    if triggered:
        log.warning(
            f"[INTRADAY EARLY-EXIT] {len(triggered)} dead trade(s) detected. "
            f"Will execute retroactively on startup."
        )
    
    return triggered


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print("Intraday exit monitor module loaded. Call check_intraday_early_exit() during run_check().")
