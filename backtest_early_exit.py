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

NOTE: Since minute-level historical data is unavailable, uses heuristic estimate for 1:30 PM price:
      estimated_130pm = entry + 2/3 * (actual_close - entry)
      This assumes 2/3 of the intraday move has completed by 1:30 PM.
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import List, Dict, Optional

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


def estimate_130pm_price(entry_price: float, actual_exit_price: float) -> float:
    """
    Estimate price at 1:30 PM given entry and actual close prices.
    
    Heuristic: Assume intraday movement from entry to close follows a 2/3 taper.
    Price at 1:30 PM ≈ entry + 2/3 * (close - entry)
    
    This conservative assumption means most intraday weakness is already captured by 1:30 PM,
    with final 1/3 of the move happening in the last 2 hours before close.
    """
    try:
        estimated_130pm = entry_price + (2/3) * (actual_exit_price - entry_price)
        return estimated_130pm
    except Exception:
        return actual_exit_price


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
    """Apply triple-AND rule retroactively to all closed BTST trades."""
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
        "avg_loss_abs_original": 0.0,
        "avg_loss_abs_exit": 0.0,
        "trades_detail": [],
    }
    
    for trade in trades:
        status = trade.get("status", "")
        if status not in ("EXPIRED_LOSS", "LOST"):
            continue
        
        stats["total_expired_loss"] += 1
        
        ticker = trade.get("ticker", "UNKNOWN")
        entry_price_raw = trade.get("entry_price")
        actual_exit_price_raw = trade.get("exit_price")
        
        if not all([entry_price_raw, actual_exit_price_raw]):
            continue
        
        try:
            entry_price = float(entry_price_raw)
            actual_exit_price = float(actual_exit_price_raw)
        except (ValueError, TypeError):
            continue
        
        if entry_price <= 0:
            continue
        
        # Original loss
        original_loss_pct = (actual_exit_price - entry_price) / entry_price * 100
        original_loss_abs = actual_exit_price - entry_price
        stats["total_original_loss"] += original_loss_abs
        
        # Estimate price at 1:30 PM
        decision_price = estimate_130pm_price(entry_price, actual_exit_price)
        
        # Check triple-AND conditions
        pct_at_130 = (decision_price - entry_price) / entry_price * 100
        traj_score = get_trajectory_score_for_trade(trade)
        
        price_triggered = pct_at_130 < EARLY_EXIT_PRICE_THRESHOLD
        traj_triggered = traj_score is not None and traj_score <= EARLY_EXIT_TRAJECTORY_MAX
        
        if price_triggered and traj_triggered:
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
                "triggered": True,
            })
    
    # Compute averages
    if stats["total_expired_loss"] > 0:
        stats["avg_loss_abs_original"] = stats["total_original_loss"] / stats["total_expired_loss"]
    
    if stats["caught_by_rule"] > 0:
        stats["avg_loss_abs_exit"] = stats["total_exit_loss"] / stats["caught_by_rule"]
        stats["loss_reduction"] = stats["total_original_loss"] - stats["total_exit_loss"]
    
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
    log.info("(Using heuristic: estimated 1:30 PM price = entry + 2/3 * (close - entry))")
    stats = backtest_early_exit_rule(trades)
    
    log.info("\n" + "=" * 70)
    log.info("BACKTEST RESULTS")
    log.info("=" * 70)
    log.info(f"Total closed BTST_1d trades: {stats['total_trades']}")
    log.info(f"Total EXPIRED_LOSS trades: {stats['total_expired_loss']}")
    log.info(f"Trades caught by early-exit rule: {stats['caught_by_rule']}")
    if stats['total_expired_loss'] > 0:
        catch_rate = (stats['caught_by_rule'] / stats['total_expired_loss'] * 100)
        log.info(f"Catch rate: {catch_rate:.1f}%")
    
    log.info(f"\n💰 Loss Reduction Analysis:")
    log.info(f"   Cumulative loss (holding to close): ₹{stats['total_original_loss']:.2f}")
    log.info(f"   Cumulative loss (early exit at 1:30 PM): ₹{stats['total_exit_loss']:.2f}")
    log.info(f"   Total savings: ₹{stats['loss_reduction']:.2f}")
    log.info(f"   Avg loss per trade (original): ₹{stats['avg_loss_abs_original']:.2f}")
    log.info(f"   Avg loss per trade (early exit): ₹{stats['avg_loss_abs_exit']:.2f}")
    log.info("=" * 70)
    
    # Print top 10 trades caught by rule
    caught_trades = [t for t in stats['trades_detail'] if t.get('triggered')]
    if caught_trades:
        log.info(f"\n✅ Top {min(10, len(caught_trades))} trades caught (largest ₹ savings):")
        caught_trades.sort(key=lambda x: x.get('loss_saved_abs', 0), reverse=True)
        for i, t in enumerate(caught_trades[:10], 1):
            log.info(
                f"  {i}. {t['ticker']}: Entry ₹{t['entry_price']:.2f} → "
                f"Hold to close ₹{t['actual_exit_price']:.2f} ({t['original_loss_pct']:.2f}%) → "
                f"Exit at 1:30 PM ₹{t['decision_price_130pm']:.2f} ({t['exit_loss_pct']:.2f}%), "
                f"Saved ₹{t['loss_saved_abs']:.2f} ({t['loss_saved_pct']:.2f}%)"
            )
    else:
        log.info("\n⚠️  No trades caught by the early-exit rule.")
        log.info("   (This may be due to synthetic trajectory scoring. In production,")
        log.info("    real trajectory scores from RAG engine will be used.)")
    
    log.info("\n✓ Backtest complete.")


if __name__ == "__main__":
    main()
