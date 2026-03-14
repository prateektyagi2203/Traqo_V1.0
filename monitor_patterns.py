"""
Pattern Monitoring System — Track borderline patterns for promotion/demotion
============================================================================
Monitors 8 patterns in "MONITOR" status (1.0 < PF < 1.3, Win% >= 48%).

These patterns didn't pass OOS promotion threshold but show promise:
  1. belt_hold_bullish  (PF=1.29, Win%=52.7%) — closest to 1.3 threshold
  2. harami_cross       (PF=1.23, Win%=50.9%)
  3. in_neck            (PF=1.17, Win%=49.1%)
  4. three_inside_up    (PF=1.16, Win%=52.9%)
  5. falling_three_methods (PF=1.15, Win%=53.8%)
  6. long_legged_doji   (PF=1.05, Win%=49.2%)
  7. spinning_top       (PF=1.04, Win%=49.2%)
  8. high_wave          (PF=1.03, Win%=48.6%)

MONITORING STRATEGY:
  - Track live performance on paper trading account
  - Promote if: PF >= 1.3 over 20+ trades in live data
  - Demote if: PF < 1.0 over any 10-trade window
  - Re-evaluate: Monthly using OOS backtest on new quarterly data
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import sqlite3

# ============================================================
# PATTERNS IN MONITOR STATUS (OOS Test Results)
# ============================================================
MONITOR_PATTERNS = {
    "belt_hold_bullish": {
        "train_pf": 1.23,
        "test_pf": 1.29,
        "test_win_pct": 52.7,
        "test_count": 0,  # Will track live trades
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 20,
        "reason": "Closest to promotion threshold (1.29 vs 1.30 limit)"
    },
    "harami_cross": {
        "train_pf": 1.18,
        "test_pf": 1.23,
        "test_win_pct": 50.9,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 20,
        "reason": "Solid win rate (50.9%), consistent across train/test"
    },
    "in_neck": {
        "train_pf": 1.18,
        "test_pf": 1.17,
        "test_win_pct": 49.1,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 25,  # Higher due to low win rate
        "reason": "Decent PF but below 50% win rate (49.1%)"
    },
    "three_inside_up": {
        "train_pf": "N/A (was excluded)",
        "test_pf": 1.16,
        "test_win_pct": 52.9,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 20,
        "reason": "Re-added to whitelist — was excluded, now 1.16 PF"
    },
    "falling_three_methods": {
        "train_pf": 1.21,
        "test_pf": 1.15,
        "test_win_pct": 53.8,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 20,
        "reason": "High win rate (53.8%) but PF below threshold"
    },
    "long_legged_doji": {
        "train_pf": 1.12,
        "test_pf": 1.05,
        "test_win_pct": 49.2,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 25,  # Risky pattern, need more data
        "reason": "Training degradation (1.12→1.05), watch closely"
    },
    "spinning_top": {
        "train_pf": 1.19,
        "test_pf": 1.04,
        "test_win_pct": 49.2,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 25,
        "reason": "Significant train/test drop (1.19→1.04), regime-dependent"
    },
    "high_wave": {
        "train_pf": 1.19,
        "test_pf": 1.03,
        "test_win_pct": 48.6,
        "test_count": 0,
        "promotion_threshold": 1.30,
        "demotion_threshold": 1.00,
        "min_samples": 30,  # Riskiest, need large sample
        "reason": "Marginal PF (1.03), below 50% win rate (48.6%)"
    }
}


class PatternMonitor:
    """Track live performance of monitor-status patterns."""
    
    def __init__(self, db_path="paper_trades/paper_trades.db"):
        self.db_path = db_path
        self.monitor_file = "pattern_monitor_performance.json"
        self.load_monitor_data()
    
    def load_monitor_data(self):
        """Load existing monitor data or create new."""
        if os.path.exists(self.monitor_file):
            with open(self.monitor_file, 'r') as f:
                self.monitor_data = json.load(f)
        else:
            self.monitor_data = {
                "last_updated": None,
                "patterns": {},
                "monthly_logs": []
            }
            for pattern_name in MONITOR_PATTERNS.keys():
                self.monitor_data["patterns"][pattern_name] = {
                    "live_trades": 0,
                    "live_wins": 0,
                    "live_pf": 0.0,
                    "status": "MONITOR",
                    "first_trade_date": None,
                    "last_update": None,
                    "decision_made": False,
                    "decision_date": None,
                    "decision_reason": ""
                }
    
    def get_trades_for_pattern(self, pattern_name, days_back=30):
        """Query paper_trades.db for trades matching this pattern in last N days."""
        if not os.path.exists(self.db_path):
            print(f"Database not found: {self.db_path}")
            return []
        
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cutoff_date = (datetime.now() - timedelta(days=days_back)).isoformat()
            
            # Query trades with this pattern
            cursor.execute("""
                SELECT 
                    trade_id, pattern_name, entry_date, exit_date,
                    entry_price, exit_price, profit_loss, profit_pct,
                    status, instrument
                FROM trades
                WHERE pattern_name = ?
                  AND entry_date >= ?
                ORDER BY entry_date DESC
            """, (pattern_name, cutoff_date))
            
            trades = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return trades
        except Exception as e:
            print(f"Error querying database: {e}")
            return []
    
    def calculate_pattern_metrics(self, pattern_name, trades):
        """Calculate PF, win%, trade count from trades list."""
        if len(trades) == 0:
            return None
        
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.get('profit_loss', 0) > 0)
        losing_trades = total_trades - winning_trades
        
        win_pct = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        
        gross_profit = sum(t.get('profit_loss', 0) for t in trades if t.get('profit_loss', 0) > 0)
        gross_loss = abs(sum(t.get('profit_loss', 0) for t in trades if t.get('profit_loss', 0) < 0))
        
        pf = gross_profit / gross_loss if gross_loss > 0 else (1.0 if gross_profit > 0 else 0.0)
        
        return {
            "trades": total_trades,
            "wins": winning_trades,
            "losses": losing_trades,
            "pf": round(pf, 2),
            "win_pct": round(win_pct, 1)
        }
    
    def check_promotion_criteria(self, pattern_name, metrics):
        """Determine if pattern should be promoted to whitelist."""
        if metrics is None or metrics["trades"] < MONITOR_PATTERNS[pattern_name]["min_samples"]:
            return "MONITOR", "Insufficient sample size"
        
        config = MONITOR_PATTERNS[pattern_name]
        
        # Promotion: PF >= 1.3 AND Win% >= 50%
        if metrics["pf"] >= config["promotion_threshold"] and metrics["win_pct"] >= 50:
            return "PROMOTE", f"Live PF {metrics['pf']} >= {config['promotion_threshold']}, Win% {metrics['win_pct']}%"
        
        # Demotion: PF < 1.0
        if metrics["pf"] < config["demotion_threshold"]:
            return "REJECT", f"Live PF {metrics['pf']} < {config['demotion_threshold']}"
        
        # Still monitoring: 1.0 <= PF < 1.3
        return "MONITOR", f"Live PF {metrics['pf']}, {metrics['trades']}/{config['min_samples']} samples"
    
    def update_pattern_monitor(self, pattern_name):
        """Update live metrics for a pattern."""
        trades = self.get_trades_for_pattern(pattern_name, days_back=90)
        metrics = self.calculate_pattern_metrics(pattern_name, trades)
        
        if metrics is None:
            print(f"  {pattern_name:25s} No trades found in last 90 days")
            return None
        
        status, reason = self.check_promotion_criteria(pattern_name, metrics)
        
        # Update monitor data
        self.monitor_data["patterns"][pattern_name].update({
            "live_trades": metrics["trades"],
            "live_wins": metrics["wins"],
            "live_pf": metrics["pf"],
            "live_win_pct": metrics["win_pct"],
            "status": status,
            "last_update": datetime.now().isoformat(),
            "decision_reason": reason
        })
        
        print(f"  {pattern_name:25s} PF={metrics['pf']:5.2f} W%={metrics['win_pct']:5.1f}% "
              f"Trades={metrics['trades']:3d}/{MONITOR_PATTERNS[pattern_name]['min_samples']:2d} → {status}")
        
        return status
    
    def run_monitoring_check(self):
        """Check all monitor patterns for promotion/demotion."""
        print("\n" + "="*100)
        print("PATTERN MONITOR CHECK — Live Performance Analysis")
        print("="*100 + "\n")
        print("Pattern Name              Live PF  Live W%  Trades/Min  Status   Reason")
        print("-" * 100)
        
        self.monitor_data["last_updated"] = datetime.now().isoformat()
        promotions = []
        demotions = []
        
        for pattern_name in MONITOR_PATTERNS.keys():
            status = self.update_pattern_monitor(pattern_name)
            
            if status == "PROMOTE":
                promotions.append(pattern_name)
            elif status == "REJECT":
                demotions.append(pattern_name)
        
        # Summary
        print("\n" + "="*100)
        print("SUMMARY")
        print("="*100)
        
        if promotions:
            print(f"\n[+] PROMOTE TO WHITELIST ({len(promotions)} patterns):")
            for p in promotions:
                m = self.monitor_data["patterns"][p]
                print(f"    {p:25s} Live PF={m['live_pf']:.2f} Win%={m['live_win_pct']:.1f}%")
        
        if demotions:
            print(f"\n[-] DEMOTE FROM MONITOR ({len(demotions)} patterns):")
            for p in demotions:
                m = self.monitor_data["patterns"][p]
                print(f"    {p:25s} Live PF={m['live_pf']:.2f} (below 1.0)")
        
        stillmon = [p for p in MONITOR_PATTERNS.keys() if p not in promotions and p not in demotions]
        if stillmon:
            print(f"\n[=] CONTINUE MONITORING ({len(stillmon)} patterns):")
            for p in stillmon:
                m = self.monitor_data["patterns"][p]
                cfg = MONITOR_PATTERNS[p]
                print(f"    {p:25s} Live PF={m['live_pf']:.2f} ({m['live_trades']}/{cfg['min_samples']} samples)")
        
        self.save_monitor_data()
        
        return {
            "promotions": promotions,
            "demotions": demotions,
            "monitoring": stillmon
        }
    
    def save_monitor_data(self):
        """Save monitor data to JSON file."""
        with open(self.monitor_file, 'w') as f:
            json.dump(self.monitor_data, f, indent=2)
        print(f"\nMonitor data saved to {self.monitor_file}")
    
    def get_promotion_checklist(self):
        """Generate checklist for manually promoting a pattern."""
        print("\n" + "="*100)
        print("PATTERN PROMOTION CHECKLIST")
        print("="*100 + "\n")
        print("When a MONITOR pattern reaches promotion criteria, add to trading_config.py:\n")
        print("STEP 1: Update WHITELISTED_PATTERNS")
        print('    WHITELISTED_PATTERNS = {')
        print('        ...,')
        print('        "new_pattern_name",  # PROMOTED from MONITOR status')
        print('        ...,')
        print('    }\n')
        print("STEP 2: Verify pattern detection in pattern_detector.py")
        print("        - Check pattern detection logic is correct")
        print("        - Confirm signal quality > 50% win rate")
        print("        - Review entry price logic\n")
        print("STEP 3: Test in dashboard")
        print("        - Run paper_trading_dashboard.py")
        print("        - Verify pattern shows in scan results")
        print("        - Confirm position sizing applies correctly\n")
        print("STEP 4: Monitor first 5-10 trades")
        print("        - Watch actual paper trading execution")
        print("        - Track PF on live data (should maintain >= 1.3)")
        print("        - Alert if PF drops below 1.0 (automatic demotion)\n"
        print("STEP 5: Document decision")
        print("        - Add timestamp and reason to this file")
        print("        - Update pattern_monitor_performance.json with decision_made=True")
        print("        - Create entry in change log")


def main():
    """Run monitoring check."""
    monitor = PatternMonitor()
    results = monitor.run_monitoring_check()
    
    print("\n\nRECOMMENDED ACTIONS:")
    print("-" * 100)
    
    if results["promotions"]:
        print(f"\n✓ IMMEDIATE: Promote {results['promotions']} to WHITELISTED_PATTERNS")
        monitor.get_promotion_checklist()
    
    if results["demotions"]:
        print(f"\n✗ IMMEDIATE: Remove {results['demotions']} from monitor (PF < 1.0)")
        print("   Update pattern_monitor_performance.json with decision_date")
    
    if results["monitoring"]:
        print(f"\n= CONTINUE MONITORING: {len(results['monitoring'])} patterns")
        print("   Run this script weekly to track progress")
        print("   Target: Gather 20-30 trades per pattern before promotion decision")


if __name__ == "__main__":
    main()
