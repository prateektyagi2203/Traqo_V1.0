"""
Position Sizing — Kelly Criterion + Risk Management
=====================================================
Calculates optimal position size based on edge and win rate.

Uses fractional Kelly (half-Kelly by default) for safety.
Integrates with kill switches/circuit breakers.

Usage:
    from position_sizing import PositionSizer
    sizer = PositionSizer(capital=1_000_000)
    size = sizer.calculate_size(win_rate=53.5, profit_factor=1.14, sl_pct=1.5)

Change log:
  2026-02-24  Initial implementation (Item 8)
"""

import numpy as np
from typing import Optional, Dict

from trading_config import (
    KELLY_FRACTION, MAX_POSITION_PCT, MIN_POSITION_PCT,
    DEFAULT_CAPITAL,
)

# Horizon multipliers — shorter horizons get slightly larger sizes (faster
# compounding), longer horizons reduce to manage overnight/swing risk.
HORIZON_SIZE_MULTIPLIER = {
    "BTST_1d":   1.2,
    "Swing_3d":  1.0,
    "Swing_5d":  0.9,  # primary horizon
    "Swing_10d": 0.8,
    # "Swing_25d" removed from scope
}

# Sector volatility adjustment — high-beta sectors get smaller sizes.
# Values represent *multipliers* on position size (lower = smaller position).
SECTOR_VOL_MULTIPLIER = {
    "banking":       0.85,  # high beta
    "finance":       0.85,
    "metals":        0.80,  # very cyclical
    "realty":        0.75,  # high volatility
    "energy":        0.90,
    "it":            0.95,
    "pharma":        1.00,  # defensive
    "fmcg":          1.05,  # low vol, defensive
    "auto":          0.90,
    "chemicals":     0.90,
    "capital_goods":  0.90,
    "cement":        0.95,
    "infra":         0.85,
    "consumer":      0.95,
    "defence":       0.90,
    "telecom":       0.95,
    "media":         0.85,
    "consumer_tech": 0.90,
    "logistics":     0.90,
    "textiles":      0.85,
    "diversified":   0.90,
    "commodity":     0.80,  # very volatile
    "index_in":      1.00,
    "index_us":      1.00,
    "index_asia":    0.90,
    "index_eu":      0.95,
}


class PositionSizer:
    """Calculate position sizes using Kelly Criterion with safety bounds."""

    def __init__(self, capital: float = DEFAULT_CAPITAL,
                 kelly_fraction: float = KELLY_FRACTION,
                 max_position_pct: float = MAX_POSITION_PCT,
                 min_position_pct: float = MIN_POSITION_PCT):
        self.capital = capital
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.min_position_pct = min_position_pct

    def kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Calculate the Kelly fraction.
        
        Kelly % = W - (1-W) / R
        Where W = win probability, R = win/loss ratio
        
        Args:
            win_rate: Win probability (0-1), e.g. 0.535
            avg_win: Average winning trade return (positive)
            avg_loss: Average losing trade return (positive absolute)
        
        Returns:
            Kelly fraction (0-1), capped at safety bounds
        """
        if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0
        
        R = avg_win / avg_loss  # win/loss ratio
        kelly = win_rate - (1 - win_rate) / R
        
        # Apply fractional Kelly
        kelly *= self.kelly_fraction
        
        # Cap to safety bounds
        kelly = max(0.0, min(kelly, self.max_position_pct / 100))
        
        return kelly

    def calculate_size(self, win_rate: float, profit_factor: float,
                       sl_pct: float, confidence_level: str = "MEDIUM",
                       avg_return: float = None,
                       horizon_label: str = None,
                       sector: str = None) -> Dict[str, float]:
        """Calculate position size for a trade.
        
        Args:
            win_rate: Historical win rate (0-100%)
            profit_factor: Historical PF
            sl_pct: Stop-loss percentage for this trade
            confidence_level: HIGH/MEDIUM/LOW from predictor
            avg_return: Average return per trade (optional)
            horizon_label: e.g. "BTST_1d", "Swing_5d" — scales size by horizon
            sector: e.g. "banking", "pharma" — scales size by sector volatility
        
        Returns:
            Dict with position_pct, position_value, shares, kelly_raw, etc.
        """
        # Convert win_rate to probability
        w = win_rate / 100
        
        # Estimate avg_win and avg_loss from PF and win_rate
        # PF = (w * avg_win) / ((1-w) * avg_loss)
        # Assume avg_loss ≈ sl_pct
        avg_loss = sl_pct
        if w > 0 and (1 - w) > 0:
            avg_win = profit_factor * (1 - w) * avg_loss / w
        else:
            avg_win = avg_loss  # no edge
        
        # Kelly calculation
        kelly_raw = self.kelly_criterion(w, avg_win, avg_loss)
        
        # Confidence adjustment
        conf_multiplier = {
            "HIGH": 1.0,
            "MEDIUM": 0.7,
            "LOW": 0.4,
        }.get(confidence_level, 0.5)
        
        adjusted_pct = kelly_raw * conf_multiplier * 100  # convert to %
        
        # Horizon-based scaling
        hz_mult = HORIZON_SIZE_MULTIPLIER.get(horizon_label, 1.0) if horizon_label else 1.0
        adjusted_pct *= hz_mult
        
        # Sector volatility scaling
        sec_mult = SECTOR_VOL_MULTIPLIER.get(sector, 1.0) if sector else 1.0
        adjusted_pct *= sec_mult
        
        # Enforce bounds
        if adjusted_pct < self.min_position_pct:
            adjusted_pct = 0  # Below minimum = no trade
        adjusted_pct = min(adjusted_pct, self.max_position_pct)
        
        position_value = self.capital * adjusted_pct / 100
        
        return {
            "kelly_raw_pct": round(kelly_raw * 100, 2),
            "position_pct": round(adjusted_pct, 2),
            "position_value": round(position_value, 2),
            "confidence_multiplier": conf_multiplier,
            "horizon_multiplier": hz_mult,
            "sector_multiplier": sec_mult,
            "risk_per_trade": round(position_value * sl_pct / 100, 2),
            "risk_pct_capital": round(adjusted_pct * sl_pct / 100, 4),
            "avg_win_est": round(avg_win, 4),
            "avg_loss_est": round(avg_loss, 4),
        }

    def update_capital(self, pnl: float):
        """Update capital after a trade closes."""
        self.capital += pnl

    def get_capital(self) -> float:
        """Return current capital."""
        return self.capital


# Quick test
if __name__ == "__main__":
    sizer = PositionSizer(capital=1_000_000)
    
    print("=" * 60)
    print("  POSITION SIZING — KELLY CRITERION")
    print("=" * 60)
    
    # Based on our OOS results
    test_cases = [
        {"win_rate": 49.8, "profit_factor": 1.14, "sl_pct": 1.5, "confidence_level": "HIGH"},
        {"win_rate": 50.4, "profit_factor": 1.17, "sl_pct": 1.5, "confidence_level": "HIGH"},
        {"win_rate": 53.5, "profit_factor": 1.24, "sl_pct": 2.0, "confidence_level": "HIGH"},
        {"win_rate": 45.0, "profit_factor": 0.90, "sl_pct": 1.5, "confidence_level": "MEDIUM"},
        {"win_rate": 55.0, "profit_factor": 1.30, "sl_pct": 1.0, "confidence_level": "LOW"},
    ]
    
    for tc in test_cases:
        result = sizer.calculate_size(**tc)
        print(f"\n  WR={tc['win_rate']:.1f}% PF={tc['profit_factor']:.2f} SL={tc['sl_pct']:.1f}% "
              f"Conf={tc['confidence_level']}")
        print(f"    Kelly raw:    {result['kelly_raw_pct']:.2f}%")
        print(f"    Position:     {result['position_pct']:.2f}% = ₹{result['position_value']:,.0f}")
        print(f"    Risk/trade:   ₹{result['risk_per_trade']:,.0f} ({result['risk_pct_capital']:.4f}% of capital)")
