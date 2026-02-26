"""
Risk Manager — Kill Switches & Circuit Breakers
=================================================
Real-time risk management for the trading system.

Kill switches:
  - Max daily loss → stop trading for the day
  - Max consecutive losses → pause and reassess
  - Max drawdown → kill all trading
  - Max daily trades → prevent overtrading

Circuit breakers:
  - Automatic cooldown after trigger
  - State persistence across restarts
  - Alert notifications

Usage:
    from risk_manager import RiskManager
    rm = RiskManager(capital=1_000_000)
    if rm.can_trade():
        # execute trade
        rm.record_trade(pnl=+1500)
    else:
        rm.get_status()  # shows which breaker tripped

Change log:
  2026-02-24  Initial implementation (Item 9)
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from trading_config import (
    MAX_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSSES, MAX_DRAWDOWN_PCT,
    MAX_DAILY_TRADES, COOLDOWN_AFTER_KILL_MINUTES, DEFAULT_CAPITAL,
    MAX_MONTHLY_LOSS_PCT, MAX_POSITIONS_PER_SECTOR, INSTRUMENT_SECTORS,
)


STATE_FILE = "risk_state.json"


class RiskManager:
    """Real-time risk management with kill switches and circuit breakers."""

    def __init__(self, capital: float = DEFAULT_CAPITAL, state_file: str = STATE_FILE):
        self.initial_capital = capital
        self.capital = capital
        self.state_file = state_file
        
        # Session state
        self.trades_today: List[Dict] = []
        self.all_trades: List[Dict] = []
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self.consecutive_losses = 0
        self.peak_capital = capital
        
        # Kill switch states
        self.daily_loss_breaker = False
        self.consecutive_loss_breaker = False
        self.drawdown_breaker = False
        self.daily_trades_breaker = False
        self.monthly_loss_breaker = False
        self.cooldown_until: Optional[datetime] = None

        # Monthly tracking
        self.current_month = datetime.now().strftime("%Y-%m")
        self.monthly_pnl = 0.0
        
        # Load persisted state
        self._load_state()

    def _load_state(self):
        """Load persisted risk state."""
        if not self.state_file or not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            self.capital = state.get("capital", self.capital)
            self.peak_capital = state.get("peak_capital", self.peak_capital)
            self.consecutive_losses = state.get("consecutive_losses", 0)
            self.all_trades = state.get("all_trades", [])
            
            # Check if we need to reset daily counters
            saved_date = state.get("current_date", "")
            if saved_date == self.current_date:
                self.trades_today = state.get("trades_today", [])
                self.daily_loss_breaker = state.get("daily_loss_breaker", False)
                self.daily_trades_breaker = state.get("daily_trades_breaker", False)
            
            # Check cooldown
            cooldown_str = state.get("cooldown_until")
            if cooldown_str:
                self.cooldown_until = datetime.fromisoformat(cooldown_str)
            
            # Persistent breakers
            self.drawdown_breaker = state.get("drawdown_breaker", False)
            self.consecutive_loss_breaker = state.get("consecutive_loss_breaker", False)
            self.monthly_loss_breaker = state.get("monthly_loss_breaker", False)

            # Monthly tracking
            saved_month = state.get("current_month", "")
            if saved_month == self.current_month:
                self.monthly_pnl = state.get("monthly_pnl", 0.0)
            else:
                # New month — reset monthly counters
                self.monthly_pnl = 0.0
                self.monthly_loss_breaker = False
            
        except (json.JSONDecodeError, KeyError):
            pass

    def _save_state(self):
        """Persist risk state to disk."""
        if not self.state_file:
            return  # No persistence (e.g., stress tests)
        state = {
            "capital": self.capital,
            "peak_capital": self.peak_capital,
            "initial_capital": self.initial_capital,
            "consecutive_losses": self.consecutive_losses,
            "current_date": self.current_date,
            "trades_today": self.trades_today[-50:],  # keep last 50
            "all_trades": self.all_trades[-500:],  # keep last 500
            "daily_loss_breaker": self.daily_loss_breaker,
            "daily_trades_breaker": self.daily_trades_breaker,
            "consecutive_loss_breaker": self.consecutive_loss_breaker,
            "drawdown_breaker": self.drawdown_breaker,
            "monthly_loss_breaker": self.monthly_loss_breaker,
            "current_month": self.current_month,
            "monthly_pnl": self.monthly_pnl,
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
        }
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _check_date_reset(self):
        """Reset daily counters if date changed."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.current_date:
            self.current_date = today
            self.trades_today = []
            self.daily_loss_breaker = False
            self.daily_trades_breaker = False

    # ============================================================
    # KILL SWITCHES
    # ============================================================

    def _check_daily_loss(self) -> bool:
        """Check if daily loss limit is exceeded."""
        if not self.trades_today:
            return False
        daily_pnl = sum(t["pnl"] for t in self.trades_today)
        daily_loss_pct = abs(daily_pnl) / self.capital * 100 if daily_pnl < 0 else 0
        if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
            self.daily_loss_breaker = True
            self._trigger_cooldown(f"Daily loss limit hit: {daily_loss_pct:.2f}%")
            return True
        return False

    def _check_consecutive_losses(self) -> bool:
        """Check if consecutive loss limit is exceeded."""
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            self.consecutive_loss_breaker = True
            self._trigger_cooldown(f"Consecutive losses: {self.consecutive_losses}")
            return True
        return False

    def _check_drawdown(self) -> bool:
        """Check if max drawdown limit is exceeded."""
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital
        
        drawdown = (self.peak_capital - self.capital) / self.peak_capital * 100
        if drawdown >= MAX_DRAWDOWN_PCT:
            self.drawdown_breaker = True
            self._trigger_cooldown(f"Max drawdown hit: {drawdown:.2f}%")
            return True
        return False

    def _check_daily_trades(self) -> bool:
        """Check if max daily trades limit is exceeded."""
        if len(self.trades_today) >= MAX_DAILY_TRADES:
            self.daily_trades_breaker = True
            return True
        return False

    def _check_monthly_loss(self) -> bool:
        """Check if monthly loss limit is exceeded."""
        self._check_month_reset()
        monthly_loss_pct = abs(self.monthly_pnl) / self.initial_capital * 100 if self.monthly_pnl < 0 else 0
        if monthly_loss_pct >= MAX_MONTHLY_LOSS_PCT:
            self.monthly_loss_breaker = True
            self._trigger_cooldown(f"Monthly loss limit hit: {monthly_loss_pct:.2f}% (max {MAX_MONTHLY_LOSS_PCT}%)")
            return True
        return False

    def _check_month_reset(self):
        """Reset monthly counters if month changed."""
        current_month = datetime.now().strftime("%Y-%m")
        if current_month != self.current_month:
            self.current_month = current_month
            self.monthly_pnl = 0.0
            self.monthly_loss_breaker = False

    def check_sector_limit(self, instrument: str, open_positions: List[Dict]) -> bool:
        """Check if adding a position in this instrument would violate sector limits.

        Args:
            instrument: The instrument to trade.
            open_positions: List of currently open position dicts with 'instrument' key.

        Returns:
            True if the trade is ALLOWED (sector limit not breached).
            False if the sector already has MAX_POSITIONS_PER_SECTOR positions.
        """
        target_sector = INSTRUMENT_SECTORS.get(instrument.lower(), "other")
        sector_count = sum(
            1 for pos in open_positions
            if INSTRUMENT_SECTORS.get(pos.get("instrument", "").lower(), "other") == target_sector
        )
        if sector_count >= MAX_POSITIONS_PER_SECTOR:
            print(f"  [RISK] Sector limit: {target_sector} already has "
                  f"{sector_count}/{MAX_POSITIONS_PER_SECTOR} positions. "
                  f"Rejecting {instrument}.")
            return False
        return True

    def check_horizon_position_limit(self, horizon_days: int,
                                     open_positions: List[Dict],
                                     max_concurrent: int = None) -> bool:
        """Check if adding a position at this horizon would exceed weighted limits.

        Longer-horizon trades consume more 'slot weight' because capital is
        locked longer.  Weight = horizon_days / 5 (normalised to primary).

        Args:
            horizon_days: Holding period (1/3/5/10/25).
            open_positions: Currently open position dicts with optional
                            'horizon_days' key.
            max_concurrent: Override for MAX_CONCURRENT_POSITIONS (default from config).

        Returns:
            True if the trade is ALLOWED.
        """
        from trading_config import MAX_CONCURRENT_POSITIONS
        cap = max_concurrent or MAX_CONCURRENT_POSITIONS

        # Weighted slot usage of existing positions
        total_weight = sum(
            pos.get("horizon_days", 5) / 5.0 for pos in open_positions
        )
        # Weight of the proposed trade
        new_weight = horizon_days / 5.0

        if total_weight + new_weight > cap:
            print(f"  [RISK] Horizon-weighted position limit: "
                  f"current weight {total_weight:.1f} + new {new_weight:.1f} "
                  f"> cap {cap}. Rejecting.")
            return False
        return True

    def _trigger_cooldown(self, reason: str):
        """Activate cooldown period."""
        self.cooldown_until = datetime.now() + timedelta(minutes=COOLDOWN_AFTER_KILL_MINUTES)
        print(f"  [RISK] ⚠️ CIRCUIT BREAKER: {reason}")
        print(f"  [RISK] Cooldown until: {self.cooldown_until.strftime('%H:%M:%S')}")

    def _is_in_cooldown(self) -> bool:
        """Check if currently in cooldown period."""
        if self.cooldown_until is None:
            return False
        if datetime.now() < self.cooldown_until:
            return True
        # Cooldown expired
        self.cooldown_until = None
        self.consecutive_loss_breaker = False  # Reset after cooldown
        return False

    # ============================================================
    # PUBLIC API
    # ============================================================

    def can_trade(self) -> bool:
        """Check if trading is allowed right now.
        
        Returns True if ALL circuit breakers are clear.
        """
        self._check_date_reset()
        
        if self.drawdown_breaker:
            return False
        if self._is_in_cooldown():
            return False
        if self.daily_loss_breaker:
            return False
        if self.daily_trades_breaker:
            return False
        if self.consecutive_loss_breaker:
            return False
        if self.monthly_loss_breaker:
            return False
        
        return True

    def record_trade(self, pnl: float, instrument: str = "",
                     direction: str = "", pattern: str = "",
                     sl_pct: float = 0, position_pct: float = 0,
                     horizon_days: int = 5):
        """Record a completed trade and check all circuit breakers.
        
        Args:
            pnl: Profit/loss of the trade in currency units
            instrument: Ticker/symbol
            direction: bullish/bearish
            pattern: Pattern name
            sl_pct: Stop loss percentage used
            position_pct: Position size as % of capital
            horizon_days: Holding period in days (1/3/5/10/25)
        
        Returns:
            Dict with updated status.
        """
        self._check_date_reset()
        
        trade = {
            "timestamp": datetime.now().isoformat(),
            "pnl": pnl,
            "instrument": instrument,
            "direction": direction,
            "pattern": pattern,
            "sl_pct": sl_pct,
            "position_pct": position_pct,
            "horizon_days": horizon_days,
        }
        
        self.trades_today.append(trade)
        self.all_trades.append(trade)
        
        # Update capital
        self.capital += pnl
        
        # Update consecutive losses
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        # Update peak
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital
        
        # Track monthly P&L
        self._check_month_reset()
        self.monthly_pnl += pnl

        # Check all breakers
        self._check_daily_loss()
        self._check_consecutive_losses()
        self._check_drawdown()
        self._check_daily_trades()
        self._check_monthly_loss()
        
        # Save state
        self._save_state()
        
        return self.get_status()

    def get_status(self) -> Dict:
        """Get current risk management status."""
        self._check_date_reset()
        
        daily_pnl = sum(t["pnl"] for t in self.trades_today) if self.trades_today else 0
        drawdown = (self.peak_capital - self.capital) / self.peak_capital * 100 if self.peak_capital > 0 else 0
        
        monthly_loss_pct = abs(self.monthly_pnl) / self.initial_capital * 100 if self.monthly_pnl < 0 else 0

        return {
            "can_trade": self.can_trade(),
            "capital": self.capital,
            "initial_capital": self.initial_capital,
            "peak_capital": self.peak_capital,
            "drawdown_pct": round(drawdown, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round(daily_pnl / self.capital * 100, 4) if self.capital > 0 else 0,
            "monthly_pnl": round(self.monthly_pnl, 2),
            "monthly_loss_pct": round(monthly_loss_pct, 2),
            "trades_today": len(self.trades_today),
            "consecutive_losses": self.consecutive_losses,
            "breakers": {
                "daily_loss": self.daily_loss_breaker,
                "consecutive_losses": self.consecutive_loss_breaker,
                "max_drawdown": self.drawdown_breaker,
                "max_daily_trades": self.daily_trades_breaker,
                "monthly_loss": self.monthly_loss_breaker,
                "in_cooldown": self._is_in_cooldown(),
            },
            "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
        }

    def reset_breakers(self, confirm: bool = False):
        """Manually reset all circuit breakers (emergency override).
        
        Only use when you've reviewed the situation and decided to continue.
        """
        if not confirm:
            print("  [RISK] Call reset_breakers(confirm=True) to confirm reset.")
            return
        
        self.daily_loss_breaker = False
        self.consecutive_loss_breaker = False
        self.drawdown_breaker = False
        self.daily_trades_breaker = False
        self.monthly_loss_breaker = False
        self.cooldown_until = None
        self.consecutive_losses = 0
        self.monthly_pnl = 0.0
        self._save_state()
        print("  [RISK] All circuit breakers reset.")

    def reset_daily(self):
        """Reset daily counters (for new trading day)."""
        self.trades_today = []
        self.daily_loss_breaker = False
        self.daily_trades_breaker = False
        self.current_date = datetime.now().strftime("%Y-%m-%d")
        self._save_state()

    def print_status(self):
        """Print formatted risk status."""
        s = self.get_status()
        print(f"\n  {'=' * 50}")
        print(f"  RISK MANAGER STATUS")
        print(f"  {'=' * 50}")
        print(f"  Can trade:         {'✅ YES' if s['can_trade'] else '❌ NO'}")
        print(f"  Capital:           ₹{s['capital']:,.0f} (peak: ₹{s['peak_capital']:,.0f})")
        print(f"  Drawdown:          {s['drawdown_pct']:.2f}% (max: {MAX_DRAWDOWN_PCT}%)")
        print(f"  Daily P&L:         ₹{s['daily_pnl']:,.0f} ({s['daily_pnl_pct']:+.4f}%)")
        print(f"  Monthly P&L:       ₹{s['monthly_pnl']:,.0f} (loss limit: {MAX_MONTHLY_LOSS_PCT}%)")
        print(f"  Trades today:      {s['trades_today']}/{MAX_DAILY_TRADES}")
        print(f"  Consecutive losses: {s['consecutive_losses']}/{MAX_CONSECUTIVE_LOSSES}")
        
        breakers = s["breakers"]
        if any(breakers.values()):
            print(f"\n  ⚠️ ACTIVE BREAKERS:")
            for name, active in breakers.items():
                if active:
                    print(f"    🔴 {name}")
        else:
            print(f"\n  ✅ All circuit breakers clear")


# Quick test
if __name__ == "__main__":
    rm = RiskManager(capital=1_000_000)
    
    print("=" * 60)
    print("  RISK MANAGER — CIRCUIT BREAKER TEST")
    print("=" * 60)
    
    rm.print_status()
    
    # Simulate trades
    print("\n  Simulating trades...")
    
    # Winning trade
    rm.record_trade(pnl=+2000, instrument="RELIANCE", direction="bullish")
    print(f"  Trade 1: +₹2,000 | Can trade: {rm.can_trade()}")
    
    # Series of losses
    for i in range(5):
        rm.record_trade(pnl=-3000, instrument="HDFCBANK", direction="bearish")
        print(f"  Trade {i+2}: -₹3,000 | Consecutive: {rm.consecutive_losses} | Can trade: {rm.can_trade()}")
    
    rm.print_status()
    
    # Cleanup test state
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    print("\n  Test state cleaned up.")
