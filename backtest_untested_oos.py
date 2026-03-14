"""
Walk-Forward OOS Backtest for 17 Untested Patterns
===================================================
Methodology: 2016-2023 train, 2024-2025 test (same as Feb 2026 test)

17 patterns: belt_hold_bullish, bullish_kicker, doji, downside_tasuki_gap,
             falling_three_methods, hammer, harami_cross, high_wave, homing_pigeon,
             in_neck, long_legged_doji, on_neck, rising_three_methods, spinning_top,
             stick_sandwich, three_inside_up, three_outside_up
"""

import os
import json
import glob
import pandas as pd
import numpy as np
from datetime import datetime
from collections import defaultdict

from trading_config import STANDARD_SL_MULTIPLIER, STRUCTURAL_SL_MULTIPLIER

# ============================================================
# WALK-FORWARD OOS BACKTEST ENGINE
# ============================================================

class WalkForwardOOS:
    """Walk-forward OOS test: train 2016-2023, test 2024-2025."""
    
    def __init__(self, data_dir="enriched_v2/daily"):
        self.data_dir = data_dir
        self.all_results = {}
    
    def load_instrument_data(self, instrument):
        """Load enriched CSV for instrument."""
        pattern_file = f"{self.data_dir}/{instrument}_daily_enriched.csv"
        
        if not os.path.exists(pattern_file):
            return None
        
        df = pd.read_csv(pattern_file)
        
        # Convert date column to datetime
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
        
        return df
    
    def backtest_oos_patterns(self, instruments, patterns_to_test):
        """
        Walk-forward OOS: train on 2016-2023, test on 2024-2025.
        Returns performance metrics for each pattern.
        """
        
        print(f"\nWalk-Forward OOS Backtest (2016-2023 train, 2024-2025 test)")
        print(f"Testing {len(patterns_to_test)} patterns...")
        print(f"Instruments: {len(instruments)}\n")
        
        # Initialize results
        for pattern in patterns_to_test:
            self.all_results[pattern] = {
                "train_trades": [],
                "test_trades": [],
                "train_pf": 0.0,
                "test_pf": 0.0,
                "train_win_pct": 0.0,
                "test_win_pct": 0.0,
                "train_count": 0,
                "test_count": 0,
            }
        
        debug_count = 0
        debug_instruments = 0
        
        # Test each instrument
        for instrument in instruments:
            df = self.load_instrument_data(instrument)
            if df is None or len(df) == 0:
                continue
            
            # Split into train (2016-2023) and test (2024-2025)
            if 'Date' in df.columns:
                df['Year'] = pd.to_datetime(df['Date']).dt.year
                train_df = df[df['Year'] <= 2023].copy().reset_index(drop=True)
                test_df = df[df['Year'] >= 2024].copy().reset_index(drop=True)
            else:
                # Fallback: use row count
                split_idx = int(len(df) * 0.8)
                train_df = df.iloc[:split_idx].copy().reset_index(drop=True)
                test_df = df.iloc[split_idx:].copy().reset_index(drop=True)
            
            # Test each pattern on both train and test sets
            for pattern in patterns_to_test:
                # Train set
                if len(train_df) > 0:
                    train_trades = self._backtest_on_set(train_df, pattern, instrument)
                    self.all_results[pattern]["train_trades"].extend(train_trades)
                
                # Test set (OOS)
                if len(test_df) > 0:
                    test_trades = self._backtest_on_set(test_df, pattern, instrument)
                    self.all_results[pattern]["test_trades"].extend(test_trades)
        
        # Calculate metrics
        self._calculate_metrics()
        
        return self.all_results
    
    def _backtest_on_set(self, df, pattern_name, instrument):
        """Extract trades from a dataset where pattern is detected."""
        trades = []
        
        # Pattern detection is in patterns_all column (comma-separated)
        if "patterns_all" not in df.columns:
            return trades
        
        # Find rows where this specific pattern appears in patterns_all
        df_copy = df.copy()
        df_copy['has_pattern'] = df_copy['patterns_all'].fillna('').str.contains(
            f'\\b{pattern_name}\\b', 
            regex=True, 
            case=False
        )
        
        signal_indices = df_copy[df_copy['has_pattern']].index.tolist()
        
        for sig_idx in signal_indices:
            if sig_idx + 1 >= len(df):
                continue
            
            entry_row = df.iloc[sig_idx]
            exit_row = df.iloc[sig_idx + 1]
            
            entry_price = entry_row.get("Close", 0)
            exit_price = exit_row.get("Close", 0)
            
            if entry_price == 0:
                continue
            
            profit_pct = ((exit_price - entry_price) / entry_price) * 100
            
            trades.append({
                "instrument": instrument,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "profit_pct": profit_pct,
                "is_win": profit_pct > 0
            })
        
        return trades
    
    def _calculate_metrics(self):
        """Calculate PF and win% for train and test sets."""
        for pattern in self.all_results.keys():
            data = self.all_results[pattern]
            
            # Train metrics
            if len(data["train_trades"]) > 0:
                train_trades = data["train_trades"]
                data["train_count"] = len(train_trades)
                
                wins = sum(1 for t in train_trades if t["is_win"])
                losses = len(train_trades) - wins
                
                gross_profit = sum(t["profit_pct"] for t in train_trades if t["is_win"])
                gross_loss = abs(sum(t["profit_pct"] for t in train_trades if not t["is_win"]))
                
                data["train_pf"] = gross_profit / max(gross_loss, 0.001)
                data["train_win_pct"] = (wins / len(train_trades) * 100) if len(train_trades) > 0 else 0
            
            # Test metrics (OOS)
            if len(data["test_trades"]) > 0:
                test_trades = data["test_trades"]
                data["test_count"] = len(test_trades)
                
                wins = sum(1 for t in test_trades if t["is_win"])
                losses = len(test_trades) - wins
                
                gross_profit = sum(t["profit_pct"] for t in test_trades if t["is_win"])
                gross_loss = abs(sum(t["profit_pct"] for t in test_trades if not t["is_win"]))
                
                data["test_pf"] = gross_profit / max(gross_loss, 0.001)
                data["test_win_pct"] = (wins / len(test_trades) * 100) if len(test_trades) > 0 else 0


def print_results(results):
    """Print OOS backtest results with train/test comparison."""
    
    # Filter patterns with trades
    valid_patterns = {k: v for k, v in results.items() if v["test_count"] > 0}
    
    if not valid_patterns:
        print("No trades found for any patterns.")
        return
    
    # Sort by test PF
    sorted_patterns = sorted(
        valid_patterns.items(),
        key=lambda x: x[1]["test_pf"],
        reverse=True
    )
    
    print("\n" + "="*100)
    print("OOS WALK-FORWARD RESULTS (Train: 2016-2023, Test: 2024-2025)")
    print("="*100 + "\n")
    
    print(f"{'Pattern':<25} {'Train PF':>10} {'Train W%':>10} {'Test PF':>10} {'Test W%':>10} {'Status':<15}")
    print("-" * 100)
    
    for pattern, metrics in sorted_patterns:
        test_pf = metrics["test_pf"]
        test_win = metrics["test_win_pct"]
        
        # Decision matrix
        if test_pf >= 1.3 and test_win >= 50:
            status = "PROMOTE"
        elif test_pf >= 1.0 and test_win >= 48:
            status = "MONITOR"
        else:
            status = "REJECT"
        
        print(f"{pattern:<25} {metrics['train_pf']:>10.2f} {metrics['train_win_pct']:>10.1f}% "
              f"{test_pf:>10.2f} {test_win:>10.1f}% {status:<15}")
    
    print("\n" + "="*100)
    print("DECISION MATRIX")
    print("="*100 + "\n")
    
    promoted = [(p, v) for p, v in sorted_patterns if v["test_pf"] >= 1.3 and v["test_win_pct"] >= 50]
    monitor = [(p, v) for p, v in sorted_patterns if 1.0 <= v["test_pf"] < 1.3 and v["test_win_pct"] >= 48]
    reject = [(p, v) for p, v in sorted_patterns if v["test_pf"] < 1.0 or v["test_win_pct"] < 48]
    
    print("[+] PROMOTE (PF >= 1.3, Win% >= 50%):")
    if promoted:
        for p, v in promoted:
            print(f"    {p:25s} Test PF={v['test_pf']:.2f} Win%={v['test_win_pct']:.1f}%")
    else:
        print("    None")
    
    print("\n[=] MONITOR (PF >= 1.0, Win% >= 48%):")
    if monitor:
        for p, v in monitor:
            print(f"    {p:25s} Test PF={v['test_pf']:.2f} Win%={v['test_win_pct']:.1f}%")
    else:
        print("    None")
    
    print("\n[-] REJECT (PF < 1.0 or Win% < 48%):")
    if reject:
        for p, v in reject[:10]:
            print(f"    {p:25s} Test PF={v['test_pf']:.2f} Win%={v['test_win_pct']:.1f}%")
        if len(reject) > 10:
            print(f"    ... and {len(reject) - 10} more")
    else:
        print("    None")


def main():
    # 17 untested patterns
    patterns_untested = [
        "belt_hold_bullish", "bullish_kicker", "doji", "downside_tasuki_gap",
        "falling_three_methods", "hammer", "harami_cross", "high_wave", "homing_pigeon",
        "in_neck", "long_legged_doji", "on_neck", "rising_three_methods", "spinning_top",
        "stick_sandwich", "three_inside_up", "three_outside_up"
    ]
    
    # Nifty 50 instruments
    nifty_50 = [
        "adanient", "adaniports", "apollohosp", "asianpaint", "axisbank",
        "bajajauto", "bajajfinsv", "bajfinance", "bhartiartl", "bpcl",
        "britannia", "cipla", "coalindia", "divislab", "drreddy",
        "eichermot", "eternal", "grasim", "hcltech", "hdfcbank",
        "hdfclife", "heromotoco", "hindalco", "hindunilvr", "icicibank",
        "indusindbk", "infosys", "itc", "jswsteel", "kotakbank",
        "lt", "mahindra", "maruti", "nestleind", "ntpc",
        "ongc", "powergrid", "reliance", "sbi", "sbilife",
        "shriramfin", "sunpharma", "tatamotors", "tatasteel", "tcs",
        "techm", "titan", "trent", "ultracemco", "wipro",
        "nifty50", "banknifty"
    ]
    
    # Run walk-forward OOS backtest
    wf = WalkForwardOOS(data_dir="enriched_v2/daily")
    results = wf.backtest_oos_patterns(nifty_50, patterns_untested)
    
    # Print results
    print_results(results)
    
    # Save results
    output = {
        "timestamp": datetime.now().isoformat(),
        "methodology": "Walk-Forward OOS (2016-2023 train, 2024-2025 test)",
        "patterns_tested": len(patterns_untested),
        "results": {
            p: {
                "train_pf": v["train_pf"],
                "train_win_pct": v["train_win_pct"],
                "train_count": v["train_count"],
                "test_pf": v["test_pf"],
                "test_win_pct": v["test_win_pct"],
                "test_count": v["test_count"],
            }
            for p, v in results.items()
            if v["test_count"] > 0
        }
    }
    
    with open("backtest_untested_oos_results.json", "w") as f:
        json.dump(output, f, indent=2, default=str)
    
    print(f"\n\nResults saved to backtest_untested_oos_results.json")


if __name__ == "__main__":
    main()
