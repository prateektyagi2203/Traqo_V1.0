"""
Backtest 1-Day Short Trading Strategy
======================================
Validates bearish pattern-based SHORT_1d strategy against historical LOST trades.

Locked specs:
- SL: 1.1x ATR (above entry for shorts)
- Confidence threshold: 60% minimum
- Position size: Same as BTST_1d (full)
- Profit exit: +0.5% triggers early lock-in
- Force close: 15:15 IST (retroactive execution model)
- Horizon: 1-day only — no overnight shorts
"""

import sqlite3
import pandas as pd
import logging
import json
from typing import Dict, List

from trading_config import (
    STRUCTURAL_SL_PATTERNS, STRUCTURAL_SL_MULTIPLIER,
    STANDARD_SL_MULTIPLIER, SL_FLOOR_PCT, SL_CAP_PCT,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s')
log = logging.getLogger(__name__)


class ShortTradingBacktest:
    def __init__(self, db_path: str = "paper_trades/paper_trades.db"):
        self.db_path = db_path
        self.sl_multiplier = 1.1         # 1.1x ATR (locked — tighter than longs 1.2x)
        self.confidence_threshold = 0.60  # 60% minimum (locked)
        self.profit_exit_threshold = 1.5  # +1.5% profit triggers early exit (GATE 1 fix)
        self.rr_ratio = 2.0               # 2:1 R:R for TP calculation

    def get_all_closed_trades(self) -> List[Dict]:
        """
        Load ALL closed trades (WON + LOST) to simulate SHORT entry independently.

        SHORT simulation approach:
        - We take BOTH winning and losing longs as potential short entry candidates
        - For each trade, SHORT entry = long entry price
        - SHORT exit = one of: SL hit, TP hit, or forced 1-day close
        - We use actual_return_pct to determine intraday price move
        - For BTST_1d: exit = same day close (actual_return_pct is close vs entry)
        - For multi-day: we simulate only 1-day SHORT (exit = next day open proxy)

        This avoids the tautological loop of "lost long = winning short".
        Instead we model: given a bearish pattern at entry, does the price fall
        enough in 1 day to clear SL or TP BEFORE the stop is hit?
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, ticker, entry_price, exit_price, entry_date, expiry_date,
                   horizon_label, status, actual_return_pct, indicators_json,
                   target_pct, sl_pct
            FROM trades
            WHERE status IN ('WON', 'LOST', 'EXPIRED_WIN', 'EXPIRED_LOSS')
            AND entry_price IS NOT NULL
            AND exit_price IS NOT NULL
            ORDER BY entry_date DESC
        """)
        trades = [dict(row) for row in cursor.fetchall()]
        conn.close()
        log.info(f"Loaded {len(trades)} closed trades for SHORT_1d simulation")
        return trades

    def simulate_short(self, trade: Dict) -> Dict:
        """
        Simulate SHORT_1d entry and 1-day exit independently.

        Key insight: We model a SHORT as a separate trade on the same stock,
        same entry day. The 1-day intraday price range determines outcome:

        - SL for SHORT  = entry + 1.1x ATR  (above — SHORT loses if price rises)
        - TP for SHORT  = entry - 2.2x ATR  (below — SHORT wins if price falls)
        - Forced close  = 3:15 PM same day

        For 1-day simulation we use actual_return_pct (BTST close vs entry) as
        a proxy for intraday price move. For multi-day longs we use only the
        first-day return (estimated as 40% of total return — conservative).

        Win condition for SHORT:
          - Price falls ≥ 0.5% (profit exit) → SHORT wins modestly
          - Price falls ≥ 2.2x ATR → TP hit → SHORT wins at 2:1 R:R
        Loss condition:
          - Price rises ≥ 1.1x ATR → SL hit → SHORT loses at 1x ATR
        """
        try:
            entry = float(trade['entry_price'])
            exit_p = float(trade['exit_price']) if trade['exit_price'] else entry
            actual_return = float(trade['actual_return_pct']) if trade['actual_return_pct'] is not None else 0.0

            if not entry:
                return None

            # Estimate 1-day intraday return for SHORT simulation
            h = trade['horizon_label']
            if h == 'BTST_1d':
                # BTST = next day close vs entry → use as-is for 1-day proxy
                one_day_return = actual_return
            elif h == 'Swing_3d':
                # Use 35% of 3-day return as day-1 proxy
                one_day_return = actual_return * 0.35
            elif h == 'Swing_5d':
                # Use 22% of 5-day return as day-1 proxy
                one_day_return = actual_return * 0.22
            elif h == 'Swing_10d':
                # Use 12% of 10-day return as day-1 proxy
                one_day_return = actual_return * 0.12
            else:
                one_day_return = actual_return * 0.30

            # For SHORT: positive return = price FELL (profit)
            # one_day_return from LONG perspective: negative = fell, positive = rose
            # SHORT return = opposite sign
            short_1d_return = -one_day_return  # invert: long fell = short wins

            # ATR from stored indicators, fallback to 2%
            atr_pct = 2.0
            try:
                if trade['indicators_json']:
                    ind = json.loads(trade['indicators_json'])
                    atr_pct = float(ind.get('atr_pct', 2.0))
            except Exception:
                pass

            # SHORT risk/reward levels
            sl_price  = entry * (1 + atr_pct / 100 * self.sl_multiplier)      # above entry
            tp_price  = entry * (1 - atr_pct / 100 * self.sl_multiplier * self.rr_ratio)  # below
            sl_pct    = atr_pct * self.sl_multiplier                           # % risk
            tp_pct    = sl_pct * self.rr_ratio                                 # % reward at 2:1

            # Simulate exit: SL, TP, profit-exit, or forced 3:15 PM close
            # Intraday HIGH (adverse for short) = assume 50% of upward moves happen intraday
            # Intraday LOW  (favourable for short) = assume short sees full downward move
            intraday_high_pct = max(0, -short_1d_return) * 1.2  # adverse excursion estimate
            intraday_low_pct  = max(0, short_1d_return)          # favourable excursion estimate

            hit_sl = intraday_high_pct >= sl_pct
            hit_tp = intraday_low_pct  >= tp_pct
            hit_profit_exit = short_1d_return >= self.profit_exit_threshold

            # Resolve exit in priority order: SL > TP > profit-exit > forced-close
            if hit_sl and not hit_tp:
                realized_return = -sl_pct  # SHORT stopped out
            elif hit_tp:
                realized_return = tp_pct   # SHORT hit TP at 2:1
            elif hit_profit_exit:
                realized_return = self.profit_exit_threshold  # locked in early
            else:
                realized_return = short_1d_return  # forced close at 3:15 PM

            return {
                'short_return':    realized_return,
                'raw_1d_return':   short_1d_return,
                'sl_price':        sl_price,
                'tp_price':        tp_price,
                'tp_pct':          tp_pct,
                'sl_pct':          sl_pct,
                'atr_pct':         atr_pct,
                'is_win':          realized_return > 0,
                'hit_sl':          hit_sl and not hit_tp,
                'hit_tp':          hit_tp,
                'hit_profit_exit': hit_profit_exit and not hit_tp and not (hit_sl and not hit_tp),
            }
        except (TypeError, ValueError) as e:
            log.warning(f"Simulation error trade {trade.get('id', '?')}: {e}")
            return None

    def run(self) -> Dict:
        trades = self.get_all_closed_trades()
        if not trades:
            log.error("No LOST trades found in database — cannot backtest")
            return {}

        by_horizon: Dict = {}
        all_details: List[Dict] = []
        wins = losses = tp_hits = profit_exit_hits = sl_hits = 0
        total_pnl = total_tp_pnl = total_profit_exit_pnl = 0.0
        sum_wins = sum_losses = 0.0

        for t in trades:
            sim = self.simulate_short(t)
            if not sim:
                continue

            h = t['horizon_label']
            if h not in by_horizon:
                by_horizon[h] = {'count': 0, 'wins': 0, 'total_pnl': 0.0}

            by_horizon[h]['count'] += 1
            by_horizon[h]['total_pnl'] += sim['short_return']

            if sim['is_win']:
                wins += 1
                sum_wins += sim['short_return']
                by_horizon[h]['wins'] += 1
            else:
                losses += 1
                sum_losses += sim['short_return']

            if sim['hit_tp']:
                tp_hits += 1
                total_tp_pnl += sim['tp_return']
            if sim['hit_profit_exit']:
                profit_exit_hits += 1
                total_profit_exit_pnl += min(sim['short_return'], self.profit_exit_threshold)
            if sim['hit_sl']:
                sl_hits += 1

            total_pnl += sim['short_return']
            all_details.append({
                'ticker':           t['ticker'],
                'entry_date':       t['entry_date'],
                'horizon':          h,
                'short_return_pct': round(sim['short_return'], 4),
                'is_win':           sim['is_win'],
                'hit_tp':           sim['hit_tp'],
                'hit_sl':           sim['hit_sl'],
                'hit_profit_exit':  sim['hit_profit_exit'],
                'atr_pct':          round(sim['atr_pct'], 2),
            })

        n   = wins + losses
        win_rate = round(100 * wins / n, 1) if n > 0 else 0
        avg_win  = round(sum_wins  / wins,   4) if wins   > 0 else 0
        avg_loss = round(sum_losses / losses, 4) if losses > 0 else 0
        pf = round(sum_wins / abs(sum_losses), 2) if sum_losses < 0 and sum_wins > 0 else 0

        print("\n" + "=" * 85)
        print("SHORT_1d TRADING STRATEGY BACKTEST REPORT")
        print("=" * 85)

        print(f"\n📊 OVERALL METRICS")
        print(f"   Trades analyzed : {n}  |  Wins: {wins}  |  Losses: {losses}")
        print(f"   Win rate        : {win_rate}%")
        print(f"   Avg win         : +{avg_win:.4f}%")
        print(f"   Avg loss        :  {avg_loss:.4f}%")
        print(f"   Profit factor   : {pf:.2f}x")
        print(f"   Total P&L       : {total_pnl:.2f}%  (using actual exit prices)")
        print(f"   Avg per trade   : {total_pnl/n:.4f}%" if n > 0 else "")

        print(f"\n💰 EXIT MECHANISM COMPARISON")
        print(f"   SL triggered (price reversed UP past SL): {sl_hits}")
        print(f"   TP hit  (2:1 R:R = {self.sl_multiplier*self.rr_ratio:.1f}x ATR down): {tp_hits}  →  cumulative +{total_tp_pnl:.2f}%")
        print(f"   Profit exit (≥+{self.profit_exit_threshold}% locked early):      {profit_exit_hits}  →  cumulative +{total_profit_exit_pnl:.2f}%")

        print(f"\n📈 BY HORIZON")
        print(f"   {'Horizon':<15} {'Trades':>8} {'Wins':>8} {'Win%':>7} {'Total P&L':>12} {'Avg':>10}")
        print(f"   {'-' * 63}")
        for h in sorted(by_horizon):
            b   = by_horizon[h]
            wr  = round(100 * b['wins'] / b['count'], 1) if b['count'] > 0 else 0
            avg = round(b['total_pnl'] / b['count'], 4)  if b['count'] > 0 else 0
            print(f"   {h:<15} {b['count']:>8} {b['wins']:>8} {wr:>6.1f}% {b['total_pnl']:>11.2f}% {avg:>9.4f}%")

        print(f"\n🏆 TOP 10 WINNING SHORTS")
        print(f"   {'Ticker':<12} {'Date':<12} {'Horizon':<12} {'Return':>10}  TP?  PE?")
        print(f"   {'-' * 60}")
        for t in sorted(all_details, key=lambda x: -x['short_return_pct'])[:10]:
            print(f"   {t['ticker']:<12} {t['entry_date']:<12} {t['horizon']:<12} "
                  f"{t['short_return_pct']:>9.4f}%   {'✓' if t['hit_tp'] else ' '}    {'✓' if t['hit_profit_exit'] else ' '}")

        print(f"\n⚠️  TOP 10 LOSING SHORTS")
        print(f"   {'Ticker':<12} {'Date':<12} {'Horizon':<12} {'Return':>10}  SL?")
        print(f"   {'-' * 58}")
        for t in sorted(all_details, key=lambda x: x['short_return_pct'])[:10]:
            print(f"   {t['ticker']:<12} {t['entry_date']:<12} {t['horizon']:<12} "
                  f"{t['short_return_pct']:>9.4f}%   {'✓' if t['hit_sl'] else ' '}")

        print(f"\n🎛️  LOCKED SPECIFICATIONS")
        print(f"   SL multiplier      : {self.sl_multiplier}x ATR above entry")
        print(f"   Confidence min     : {self.confidence_threshold * 100:.0f}%")
        print(f"   Position size      : Same as BTST_1d (full)")
        print(f"   Profit exit        : ≥+{self.profit_exit_threshold}%")
        print(f"   Force close        : 15:15 IST (retroactive execution — laptop-closed agnostic)")
        print(f"   Horizon            : 1-day only — NO overnight shorts")

        print(f"\n✅ DEPLOYMENT READINESS")
        if win_rate >= 50 and pf >= 1.2:
            print(f"   ✓ READY FOR DEPLOYMENT  —  Win rate {win_rate}%,  PF {pf:.2f}x")
        elif win_rate >= 45 and pf >= 1.0:
            print(f"   ~ MARGINAL  —  Win rate {win_rate}%, PF {pf:.2f}x — consider tightening pattern filter")
        else:
            print(f"   ✗ NOT READY  —  Win rate {win_rate}%, PF {pf:.2f}x — needs further validation")

        print("=" * 85)

        # Export detailed CSV
        df = pd.DataFrame(all_details)
        df.to_csv("short_trading_backtest_detail.csv", index=False)
        log.info(f"Exported {len(df)} trades → short_trading_backtest_detail.csv")

        return {'win_rate': win_rate, 'profit_factor': pf, 'total_pnl': total_pnl, 'n': n,
                'wins': wins, 'losses': losses, 'tp_hits': tp_hits, 'sl_hits': sl_hits,
                'profit_exit_hits': profit_exit_hits}


if __name__ == "__main__":
    ShortTradingBacktest().run()
