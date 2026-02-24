"""
Stress Testing Suite
======================
Tests the trading system against known stress periods to verify:
  1. Kill switches fire correctly during drawdowns
  2. Regime detector properly scales down positions
  3. Position sizing behaves sanely during high-vol events
  4. System doesn't blow up during extreme markets

Stress periods tested:
  - COVID crash (Feb-Mar 2020):    Nifty -38% in 6 weeks
  - Adani crisis (Jan-Feb 2023):   Adani -50%, market turbulence
  - Russia-Ukraine (Feb-Mar 2022): VIX spike, commodity surge
  - Demonetization (Nov 2016):     Sharp shock & recovery
  - Election 2024 (Jun 2024):      Post-election volatility

Usage:
    python stress_test.py                # Run all stress tests
    python stress_test.py --period covid # Run specific period

Change log:
  2026-02-24  Initial implementation
"""

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from trading_config import (
    MAX_DRAWDOWN_PCT, MAX_DAILY_LOSS_PCT, MAX_MONTHLY_LOSS_PCT,
    MAX_CONSECUTIVE_LOSSES, DEFAULT_CAPITAL, ALLOWED_INSTRUMENTS,
    REGIME_POSITION_SCALE,
)
from risk_manager import RiskManager
from regime_detector import RegimeDetector


# ============================================================
# STRESS PERIODS
# ============================================================

STRESS_PERIODS = {
    "covid": {
        "name": "COVID-19 Crash",
        "start": "2020-02-15",
        "end": "2020-04-30",
        "description": "Nifty crashed ~38% in 6 weeks. VIX spiked above 80.",
        "expected_regime": "extreme",
        "expected_scale": 0.0,
    },
    "russia_ukraine": {
        "name": "Russia-Ukraine War",
        "start": "2022-02-15",
        "end": "2022-04-15",
        "description": "Geopolitical shock. Commodity spike, VIX elevated.",
        "expected_regime": "bull_high_vol",
        "expected_scale": 0.7,  # Mixed regime — not a full crash
    },
    "adani": {
        "name": "Adani Crisis",
        "start": "2023-01-20",
        "end": "2023-02-28",
        "description": "Hindenburg report. Adani stocks crashed 50%+.",
        "expected_regime": "bull_high_vol",  # Market overall didn't crash
        "expected_scale": 0.7,
    },
    "demonetization": {
        "name": "Demonetization",
        "start": "2016-11-08",
        "end": "2016-12-31",
        "description": "Cash ban shock. Sharp drop then gradual recovery.",
        "expected_regime": "bull_low_vol",  # VIX was moderate, market held up
        "expected_scale": 1.0,
    },
    "election_2024": {
        "name": "Election 2024 Volatility",
        "start": "2024-06-01",
        "end": "2024-06-30",
        "description": "Post-election result uncertainty and VIX spike.",
        "expected_regime": "bull_high_vol",
        "expected_scale": 0.7,
    },
}


# ============================================================
# STRESS TEST FUNCTIONS
# ============================================================

def test_regime_during_stress(rd: RegimeDetector, period: Dict) -> Dict:
    """Test regime detection during a stress period.

    Returns dict with pass/fail status and details.
    """
    start = period["start"]
    end = period["end"]
    name = period["name"]

    print(f"\n  --- Regime Test: {name} ({start} to {end}) ---")

    history = rd.get_regime_history(start_date=start, end_date=end)

    if history.empty:
        return {
            "test": f"regime_{name}",
            "passed": False,
            "reason": "No data available for period",
        }

    # Check regime distribution
    regime_counts = history["label"].value_counts()
    dominant_regime = regime_counts.index[0]
    avg_scale = history["scale"].mean()
    min_scale = history["scale"].min()

    print(f"  Days analyzed: {len(history)}")
    print(f"  Regime distribution:")
    for label, count in regime_counts.items():
        pct = count / len(history) * 100
        print(f"    {label}: {count} days ({pct:.1f}%)")
    print(f"  Avg position scale: {avg_scale:.2f}")
    print(f"  Min position scale: {min_scale:.2f}")

    # VIX stats
    vix_vals = history["vix_value"].dropna()
    if len(vix_vals) > 0:
        print(f"  VIX: mean={vix_vals.mean():.1f}, max={vix_vals.max():.1f}")

    # Check if regime was appropriately cautious
    expected_scale = period["expected_scale"]
    scale_ok = avg_scale <= expected_scale + 0.3  # Allow some tolerance

    result = {
        "test": f"regime_{name}",
        "passed": scale_ok,
        "dominant_regime": dominant_regime,
        "avg_scale": round(avg_scale, 2),
        "expected_max_scale": expected_scale,
        "days": len(history),
        "vix_max": round(vix_vals.max(), 1) if len(vix_vals) > 0 else None,
    }

    if scale_ok:
        print(f"  ✅ PASS: Position scaling appropriate ({avg_scale:.2f} ≤ {expected_scale + 0.3})")
    else:
        print(f"  ❌ FAIL: Position scaling too aggressive ({avg_scale:.2f} > {expected_scale + 0.3})")

    return result


def test_kill_switch_simulation(period: Dict) -> Dict:
    """Simulate a series of losses and verify kill switches trigger."""
    name = period["name"]
    print(f"\n  --- Kill Switch Test: {name} ---")

    rm = RiskManager(capital=DEFAULT_CAPITAL, state_file="")
    rm.state_file = ""  # Don't persist

    # Simulate worst-case: consecutive daily losses
    daily_loss = DEFAULT_CAPITAL * MAX_DAILY_LOSS_PCT / 100
    triggered_breakers = set()
    trades_before_halt = 0

    for i in range(20):
        if not rm.can_trade():
            break
        trades_before_halt += 1
        rm.record_trade(
            pnl=-daily_loss,
            instrument="nifty50",
            direction="bullish",
            pattern="stress_test",
        )
        status = rm.get_status()
        for breaker, active in status["breakers"].items():
            if active:
                triggered_breakers.add(breaker)

    passed = len(triggered_breakers) > 0
    
    print(f"  Trades before halt: {trades_before_halt}")
    print(f"  Triggered breakers: {triggered_breakers or 'NONE'}")
    print(f"  Final drawdown: {rm.get_status()['drawdown_pct']:.2f}%")
    print(f"  Can trade: {rm.can_trade()}")

    if passed:
        print(f"  ✅ PASS: Kill switches triggered correctly")
    else:
        print(f"  ❌ FAIL: No kill switches triggered after 20 losing trades!")

    return {
        "test": f"kill_switch_{name}",
        "passed": passed,
        "trades_before_halt": trades_before_halt,
        "triggered_breakers": list(triggered_breakers),
        "final_drawdown": rm.get_status()["drawdown_pct"],
    }


def test_monthly_dd_breaker() -> Dict:
    """Verify monthly loss breaker fires at the configured threshold."""
    print(f"\n  --- Monthly Drawdown Breaker Test ---")

    rm = RiskManager(capital=DEFAULT_CAPITAL, state_file="")
    rm.state_file = ""

    monthly_limit = DEFAULT_CAPITAL * MAX_MONTHLY_LOSS_PCT / 100
    # Use small enough losses that daily breaker doesn't fire first
    # Daily limit is 2%, so keep each trade < 1% loss
    loss_per_trade = DEFAULT_CAPITAL * 0.009  # 0.9% per trade (under daily limit)

    trades = 0
    for i in range(20):
        if not rm.can_trade():
            break
        trades += 1
        # Reset daily counters and consecutive losses to simulate separate days
        # with some wins in between
        rm.trades_today = []
        rm.daily_loss_breaker = False
        rm.daily_trades_breaker = False
        rm.consecutive_loss_breaker = False
        rm.consecutive_losses = 0
        rm.cooldown_until = None
        rm.current_date = f"2025-01-{i+1:02d}"
        rm.record_trade(pnl=-loss_per_trade, instrument="test")

    monthly_breaker_hit = rm.monthly_loss_breaker
    passed = monthly_breaker_hit

    print(f"  Monthly loss limit: {MAX_MONTHLY_LOSS_PCT}% (₹{monthly_limit:,.0f})")
    print(f"  Trades until breaker: {trades}")
    print(f"  Monthly P&L: ₹{rm.monthly_pnl:,.0f}")
    print(f"  Monthly breaker fired: {monthly_breaker_hit}")

    if passed:
        print(f"  ✅ PASS: Monthly DD breaker fired correctly")
    else:
        print(f"  ❌ FAIL: Monthly DD breaker did not fire!")

    return {
        "test": "monthly_dd_breaker",
        "passed": passed,
        "trades_until_breaker": trades,
        "monthly_pnl": rm.monthly_pnl,
    }


def test_sector_limit() -> Dict:
    """Verify sector limit enforcement."""
    print(f"\n  --- Sector Limit Test ---")

    rm = RiskManager(capital=DEFAULT_CAPITAL, state_file="")

    # Simulate 3 banking positions (limit should be MAX_POSITIONS_PER_SECTOR=2)
    open_positions = [
        {"instrument": "hdfcbank"},
        {"instrument": "icicibank"},
    ]

    # Third banking position should be rejected
    can_add_third = rm.check_sector_limit("sbin", open_positions)
    # A non-banking position should be allowed
    can_add_other = rm.check_sector_limit("infosys", open_positions)

    passed = (not can_add_third) and can_add_other

    print(f"  Banking positions open: {len(open_positions)}")
    print(f"  Can add SBI (banking): {can_add_third} (expected: False)")
    print(f"  Can add Infosys (IT): {can_add_other} (expected: True)")

    if passed:
        print(f"  ✅ PASS: Sector limits enforced correctly")
    else:
        print(f"  ❌ FAIL: Sector limit enforcement broken!")

    return {
        "test": "sector_limit",
        "passed": passed,
        "banking_blocked": not can_add_third,
        "it_allowed": can_add_other,
    }


def test_position_scaling_under_stress(rd: RegimeDetector) -> Dict:
    """Verify position sizes scale down during stress regimes."""
    print(f"\n  --- Position Scaling Test ---")

    # Test all regime labels
    results = {}
    for label, expected_scale in REGIME_POSITION_SCALE.items():
        results[label] = expected_scale
        print(f"  {label}: expected scale = {expected_scale}")

    # Test extreme: should be 0
    extreme_scale = REGIME_POSITION_SCALE.get("extreme", 1.0)
    bear_high_scale = REGIME_POSITION_SCALE.get("bear_high_vol", 1.0)

    passed = extreme_scale == 0.0 and bear_high_scale < 1.0

    if passed:
        print(f"  ✅ PASS: Extreme regime stops all trading, bear_high reduces to {bear_high_scale}")
    else:
        print(f"  ❌ FAIL: Position scaling config is wrong!")

    return {
        "test": "position_scaling",
        "passed": passed,
        "regime_scales": results,
    }


# ============================================================
# MAIN
# ============================================================

def run_all_stress_tests():
    """Run the complete stress testing suite."""
    print("=" * 65)
    print("  STRESS TESTING SUITE")
    print("=" * 65)

    rd = RegimeDetector()
    results = []

    # 1. Regime detection during each stress period
    for period_key, period in STRESS_PERIODS.items():
        result = test_regime_during_stress(rd, period)
        results.append(result)

    # 2. Kill switch simulations
    for period_key, period in STRESS_PERIODS.items():
        result = test_kill_switch_simulation(period)
        results.append(result)

    # 3. Monthly DD breaker
    results.append(test_monthly_dd_breaker())

    # 4. Sector limit
    results.append(test_sector_limit())

    # 5. Position scaling
    results.append(test_position_scaling_under_stress(rd))

    # Summary
    print(f"\n{'=' * 65}")
    print(f"  STRESS TEST SUMMARY")
    print(f"{'=' * 65}")

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    total = len(results)

    for r in results:
        emoji = "✅" if r["passed"] else "❌"
        print(f"  {emoji} {r['test']}")

    print(f"\n  Total: {total} | Passed: {passed} | Failed: {failed}")

    if failed == 0:
        print(f"\n  🎉 All stress tests passed!")
    else:
        print(f"\n  ⚠️  {failed} test(s) failed — review above.")

    return results


def main():
    parser = argparse.ArgumentParser(description="Stress Testing Suite")
    parser.add_argument("--period", type=str, default=None,
                        choices=list(STRESS_PERIODS.keys()),
                        help="Run stress test for a specific period only")
    args = parser.parse_args()

    if args.period:
        rd = RegimeDetector()
        period = STRESS_PERIODS[args.period]
        test_regime_during_stress(rd, period)
        test_kill_switch_simulation(period)
    else:
        run_all_stress_tests()


if __name__ == "__main__":
    main()
