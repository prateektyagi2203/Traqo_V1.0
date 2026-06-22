"""
Backtest Early-Exit Strategy Against Historical BTST Trades
=============================================================
Replay all closed BTST_1d positions from paper_trades.db to measure:
  1. How many EXPIRED_LOSS trades would have been caught by the triple-AND rule?
  2. What was the loss reduction (1:30 PM exit vs close-of-day exit)?
  3. Total cumulative loss savings

Triple-AND Rule (applied retroactively):
  - Time >= 1:30 PM IST on expiry_date
  - Price < entry * 0.995 (below -0.5%)
  - Trajectory score <= 40 (CRITICAL/WEAK)
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import List, Dict, Optional
import pandas as pd
import yfinance as yf

log = logging.getLogger("backtest_early_exit")

DB_PATH = "paper_trades/paper_trades.db"


def get_closed_btst_trades() -> List[dict]:
    """Fetch all closed BTST_1d trades from database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        cur.execute("""
            SELECT * FROM trades
            WHERE horizon_label LIKE '%BTST%'
              AND horizon_label LIKE '%1d%'
              AND status IN ('EXPIRED_LOSS', 'LOST', 'EXPIRED_WIN', 'WON')
            ORDER BY exit_date DESC
        """)
        
        trades = [dict(row) for row in cur.fetchall()]
        conn.close()
        return trades
    except Exception as e:
        log.error(f"Failed to fetch closed BTST trades: {e}")
        return []


def get_price_at_time(ticker: str, trade_date: date, target_time: str = "13:30") -> Optional[float]:
    """
    Get 1-minute HIGH price at target time (1:30 PM) for the given date.
    Uses yfinance minute data with timezone awareness.
    
    Returns: HIGH price at 1:30 PM or closest available minute, or None if unavailable
    """
    try:
        # Market hours: 9:15 AM to 3:30 PM IST
        # Fetch 1-day of minute data for the given date
        start = trade_date
        end = trade_date
        
        df = yf.download(
            f"{ticker}.NS",
            start=start,
            end=end,
            interval="1m",
            progress=False,
            prepost=False,  # Exclude pre/post-market
        )
        
        if df is None or len(df) == 0:
            return None
        
        # Find the row closest to 1:30 PM IST (13:30)
        # yfinance returns data in UTC by default for NSE, need to handle timezone
        try:
            # Look for rows where time >= 13:30
            target_hour, target_min = map(int, target_time.split(":"))
            target_minutes = target_hour * 60 + target_min
            
            filtered = []
            for idx, row in df.iterrows():
                if pd.isna(idx):
                    continue
                # Extract hour and minute from index
                idx_hour = idx.hour
                idx_min = idx.minute
                idx_minutes = idx_hour * 60 + idx_min
                
                if idx_minutes >= target_minutes:
                    filtered.append((idx_minutes, row["High"]))
            
            if not filtered:
                # No data at or after 1:30 PM, use latest available
                return float(df["High"].iloc[-1]) if len(df) > 0 else None
            
            # Return HIGH of the first candle at/after 1:30 PM
            return float(filtered[0][1])
            
        except Exception as e:
            log.warning(f"Error parsing time for {ticker} on {trade_date}: {e}")
            # Fallback: use last available price of the day
            return float(df["High"].iloc[-1]) if len(df) > 0 else None
            
    except Exception as e:
        log.warning(f"Failed to get price at time for {ticker} on {trade_date}: {e}")
        return None


def get_trajectory_score_for_trade(trade: dict) -> Optional[int]:
    """
    Get trajectory score for the trade at the time of early-exit check.
    (Simplified: returns a synthetic score based on entry/exit price difference)
    """
    try:
        entry_price = float(trade.get("entry_price", 0))
        exit_price = float(trade.get("exit_price", 0))
        
        if entry_price <= 0 or exit_price <= 0:
            return None
        
        # Synthetic trajectory score based on loss severity
        # -0.5% to -2% → WEAK (score 40-50)
        # < -2% → CRITICAL (score 0-40)
        pct_loss = (exit_price - entry_price) / entry_price * 100
        
        if pct_loss >= -0.5:
            return 60  # Not triggered by price yet
        elif -2.0 <= pct_loss < -0.5:
            return 45  # WEAK trajectory
        else:
            return 25  # CRITICAL trajectory
            
    except Exception as e:
        log.warning(f"Failed to score trajectory: {e}")
        return None


def backtest_early_exit_rule(trades: List[dict]) -> Dict:
    """
    Apply triple-AND rule retroactively to all closed BTST trades.
    
    Returns:
      {
        "total_trades": int,
        "total_expired_loss": int,
        "caught_by_rule": int,
        "total_original_loss": float,
        "total_exit_loss": float,
        "loss_reduction": float,
        "avg_loss_pct_original": float,
        "avg_loss_pct_exit": float,
        "trades_detail": [...]
      }
    """
    from trading_config import (
        EARLY_EXIT_CUTOFF_TIME,
        EARLY_EXIT_PRICE_THRESHOLD,
        EARLY_EXIT_TRAJECTORY_MAX,
    )
    
    stats = {
        "total_trades": len(trades),
        "total_expired_loss": 0,
        "caught_by_rule": 0,
        "total_original_loss": 0.0,
        "total_exit_loss": 0.0,
        "loss_reduction": 0.0,
        "avg_loss_pct_original": 0.0,
        "avg_loss_pct_exit": 0.0,
        "trades_detail": [],
    }
    
    for trade in trades:
        status = trade.get("status", "")
        if status not in ("EXPIRED_LOSS", "LOST"):
            continue
        
        stats["total_expired_loss"] += 1
        
        ticker = trade.get("ticker", "UNKNOWN")
        entry_price = float(trade.get("entry_price", 0))
        actual_exit_price = float(trade.get("exit_price", 0))
        expiry_date = trade.get("expiry_date")
        
        # Skip if missing data
        if not all([entry_price, actual_exit_price, expiry_date]):
            continue
        
        # Parse expiry_date (might be string or date)
        try:
            if isinstance(expiry_date, str):
                expiry_dt = datetime.fromisoformat(expiry_date).date()
            else:
                expiry_dt = expiry_date
        except Exception:
            continue
        
        # Original loss
        original_loss_pct = (actual_exit_price - entry_price) / entry_price * 100
        original_loss_abs = actual_exit_price - entry_price
        stats["total_original_loss"] += original_loss_abs
        
        # Get price at 1:30 PM on expiry date
        decision_price = get_price_at_time(ticker, expiry_dt, "13:30")
        if decision_price is None:
            # Could not fetch historical minute data, skip this trade
            continue
        
        # Check triple-AND conditions
        pct_at_130 = (decision_price - entry_price) / entry_price * 100
        traj_score = get_trajectory_score_for_trade(trade)
        
        # Condition 1: Time >= 1:30 PM (always true for expiry date)
        # Condition 2: Price < entry * 0.995
        price_triggered = pct_at_130 < EARLY_EXIT_PRICE_THRESHOLD
        # Condition 3: Trajectory <= 40
        traj_triggered = traj_score is not None and traj_score <= EARLY_EXIT_TRAJECTORY_MAX
        
        if price_triggered and traj_triggered:
            # Triple-AND rule triggered → would have exited at decision_price
            stats["caught_by_rule"] += 1
            
            exit_loss_pct = (decision_price - entry_price) / entry_price * 100
            exit_loss_abs = decision_price - entry_price
            stats["total_exit_loss"] += exit_loss_abs
            loss_saved = actual_exit_price - decision_price
            
            stats["trades_detail"].append({
                "ticker": ticker,
                "entry_price": entry_price,
                "actual_exit_price": actual_exit_price,
                "decision_price_130pm": decision_price,
                "original_loss_pct": round(original_loss_pct, 3),
                "exit_loss_pct": round(exit_loss_pct, 3),
                "loss_saved_pct": round((loss_saved / entry_price) * 100, 3),
                "loss_saved_abs": round(loss_saved, 2),
                "trajectory_score": traj_score,
            })
        else:
            stats["trades_detail"].append({
                "ticker": ticker,
                "entry_price": entry_price,
                "actual_exit_price": actual_exit_price,
                "decision_price_130pm": decision_price,
                "original_loss_pct": round(original_loss_pct, 3),
                "triggered": False,
                "price_triggered": price_triggered,
                "traj_triggered": traj_triggered,
                "trajectory_score": traj_score,
            })
    
    # Compute averages
    if stats["caught_by_rule"] > 0:
        stats["avg_loss_pct_exit"] = (stats["total_exit_loss"] / entry_price / stats["caught_by_rule"]) * 100
        stats["loss_reduction"] = stats["total_original_loss"] - stats["total_exit_loss"]
    
    if stats["total_expired_loss"] > 0:
        stats["avg_loss_pct_original"] = (stats["total_original_loss"] / entry_price / stats["total_expired_loss"]) * 100
    
    return stats


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    
    log.info("=" * 70)
    log.info("BACKTEST: Intraday Early-Exit Strategy")
    log.info("=" * 70)
    
    trades = get_closed_btst_trades()
    log.info(f"Loaded {len(trades)} closed BTST_1d trades from database")
    
    if not trades:
        log.warning("No closed BTST trades found. Exiting.")
        return
    
    log.info("Applying triple-AND rule retroactively...")
    stats = backtest_early_exit_rule(trades)
    
    log.info("\n" + "=" * 70)
    log.info("BACKTEST RESULTS")
    log.info("=" * 70)
    log.info(f"Total closed BTST_1d trades: {stats['total_trades']}")
    log.info(f"Total EXPIRED_LOSS trades: {stats['total_expired_loss']}")
    log.info(f"Trades caught by early-exit rule: {stats['caught_by_rule']}")
    log.info(f"Catch rate: {(stats['caught_by_rule'] / stats['total_expired_loss'] * 100):.1f}%" if stats['total_expired_loss'] > 0 else "N/A")
    log.info(f"\nCumulative original loss: ₹{stats['total_original_loss']:.2f}")
    log.info(f"Cumulative exit loss (if early-exited): ₹{stats['total_exit_loss']:.2f}")
    log.info(f"Total loss savings: ₹{stats['loss_reduction']:.2f}")
    log.info(f"Avg loss % (original): {stats['avg_loss_pct_original']:.2f}%")
    log.info(f"Avg loss % (early exit): {stats['avg_loss_pct_exit']:.2f}%")
    log.info("=" * 70)
    
    # Print top 10 trades caught by rule
    caught_trades = [t for t in stats['trades_detail'] if t.get('loss_saved_abs') is not None]
    if caught_trades:
        log.info("\nTop 10 trades that would have been caught (largest savings):")
        caught_trades.sort(key=lambda x: x.get('loss_saved_abs', 0), reverse=True)
        for i, t in enumerate(caught_trades[:10], 1):
            log.info(
                f"  {i}. {t['ticker']}: Entry={t['entry_price']:.2f}, "
                f"Original exit={t['actual_exit_price']:.2f} ({t['original_loss_pct']:.2f}%), "
                f"1:30 PM exit={t['decision_price_130pm']:.2f} ({t['exit_loss_pct']:.2f}%), "
                f"Saved: ₹{t['loss_saved_abs']:.2f} ({t['loss_saved_pct']:.2f}%)"
            )
    
    log.info("\n✓ Backtest complete.")


if __name__ == "__main__":
    main()
