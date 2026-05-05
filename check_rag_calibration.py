#!/usr/bin/env python3
"""Check: Is this RAG overfitting across ALL patterns or just bullish_harami?"""
import sqlite3
from collections import defaultdict

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

print("="*90)
print("RAG CALIBRATION CHECK: Across All Patterns")
print("="*90)

# Get ALL patterns with HIGH confidence + shadow trades
cur = conn.execute('''
SELECT patterns, 
       AVG(predicted_win_rate) as predicted_wr,
       COUNT(*) as shadow_count,
       SUM(CASE WHEN actual_return_pct > 0 THEN 1 ELSE 0 END) as wins,
       AVG(actual_return_pct) as avg_ret
FROM shadow_trades 
WHERE confidence = 'HIGH'
  AND entry_date >= '2026-03-01'
  AND status NOT LIKE 'SHADOW_OPEN%'
GROUP BY patterns
HAVING COUNT(*) >= 10
ORDER BY predicted_wr DESC
''')

print("\nPATTERN CALIBRATION (HIGH confidence, March shadow trades, 10+ samples):\n")
print(f"{'Pattern':<40} {'Pred WR':<10} {'Real WR':<10} {'Gap':<10} {'Avg Ret':<10} {'Sample':<8}")
print("-" * 90)

calibration_gaps = []
for row in cur.fetchall():
    pat = row['patterns']
    pred_wr = row['predicted_wr']
    real_wr = row['wins'] / row['shadow_count'] * 100 if row['shadow_count'] else 0
    gap = pred_wr - real_wr
    avg_ret = row['avg_ret']
    
    calibration_gaps.append({
        'pattern': pat,
        'pred_wr': pred_wr,
        'real_wr': real_wr,
        'gap': gap,
        'avg_ret': avg_ret,
        'count': row['shadow_count']
    })
    
    gap_emoji = "⚠️" if abs(gap) > 20 else "✓"
    print(f"{pat:<40} {pred_wr:>6.0f}%{'':<3} {real_wr:>6.0f}%{'':<3} {gap:>6.0f}pp{'':<3} {avg_ret:>6.2f}%   {row['shadow_count']:>5}")

# Statistics on the gap
avg_gap = sum(c['gap'] for c in calibration_gaps) / len(calibration_gaps) if calibration_gaps else 0
max_gap = max(c['gap'] for c in calibration_gaps) if calibration_gaps else 0
min_gap = min(c['gap'] for c in calibration_gaps) if calibration_gaps else 0
bullish_harami_gap = next((c['gap'] for c in calibration_gaps if 'bullish_harami' in c['pattern']), None)

print("\n" + "="*90)
print("CALIBRATION ANALYSIS:")
print("="*90)
print(f"\nAverage prediction gap: {avg_gap:+.1f}pp")
print(f"Max gap (most overestimated): {max_gap:+.1f}pp")
print(f"Min gap (most conservative): {min_gap:+.1f}pp")
print(f"\nBullish_harami gap: {bullish_harami_gap:+.1f}pp (vs average {avg_gap:+.1f}pp)")

# Conclusion
print("\n" + "="*90)
print("VERDICT:")
print("="*90)

if abs(avg_gap) > 15:
    print(f"🔴 SYSTEMIC PROBLEM: RAG is overestimating across ALL patterns by ~{abs(avg_gap):.0f}pp")
    print(f"   - Not specific to bullish_harami")
    print(f"   - Indicates market regime shift since training data (2016-2023)")
    print(f"   - Should apply ~15-20pp discount to ALL RAG predictions")
elif abs(bullish_harami_gap) > 20 and abs(avg_gap) < 15:
    print(f"⚠️ LOCALIZED PROBLEM: bullish_harami is {abs(bullish_harami_gap):.0f}pp worse than other patterns")
    print(f"   - Could be pattern-specific degradation")
    print(f"   - Other patterns are reasonably calibrated")
else:
    print(f"✓ ACCEPTABLE: RAG calibration is reasonable")

print("\n" + "="*90)
