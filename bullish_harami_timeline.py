#!/usr/bin/env python3
"""When did bullish_harami stop working? Timeline analysis"""
import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

print("="*80)
print("BULLISH_HARAMI DEGRADATION TIMELINE")
print("="*80)

# Get timeline by date
cur = conn.execute('''
SELECT 
  entry_date,
  COUNT(*) as trades,
  SUM(CASE WHEN actual_return_pct > 0 THEN 1 ELSE 0 END) as wins,
  AVG(actual_return_pct) as avg_ret,
  MIN(actual_return_pct) as worst,
  MAX(actual_return_pct) as best
FROM shadow_trades 
WHERE patterns LIKE '%bullish_harami%'
  AND status NOT LIKE 'SHADOW_OPEN%'
GROUP BY entry_date
ORDER BY entry_date DESC
LIMIT 30
''')

print(f"\n{'Date':<12} {'Trades':<8} {'Win%':<8} {'Avg Ret':<10} {'Best':<8} {'Worst':<8}")
print("-" * 65)

best_date = None
worst_date = None
best_wr = 100
worst_wr = 0

for row in cur.fetchall():
    wr = row['wins'] / row['trades'] * 100 if row['trades'] else 0
    print(f"{row['entry_date']:<12} {row['trades']:<8} {wr:>5.0f}%{'':<2} {row['avg_ret']:>7.2f}%{'':<2} {row['best']:>6.2f}% {row['worst']:>6.2f}%")
    
    if wr < worst_wr:
        worst_wr = wr
        worst_date = row['entry_date']
    if wr > best_wr:
        best_wr = wr
        best_date = row['entry_date']

# Check February vs March
print("\n" + "="*80)
print("FEBRUARY vs MARCH COMPARISON:")
print("="*80)

for month, start, end in [("February", "2026-02-01", "2026-02-28"), ("March", "2026-03-01", "2026-03-20")]:
    cur = conn.execute('''
    SELECT 
      COUNT(*) as total,
      SUM(CASE WHEN actual_return_pct > 0 THEN 1 ELSE 0 END) as wins,
      AVG(actual_return_pct) as avg_ret,
      AVG(predicted_win_rate) as avg_pred
    FROM shadow_trades 
    WHERE patterns LIKE '%bullish_harami%'
      AND entry_date >= ? AND entry_date <= ?
      AND status NOT LIKE 'SHADOW_OPEN%'
    ''', (start, end))
    
    for row in cur.fetchall():
        if row['total']:
            wr = row['wins'] / row['total'] * 100
            print(f"\n{month}:")
            print(f"  Shadow trades: {row['total']}")
            print(f"  Real WR: {wr:.0f}%")
            print(f"  Predicted WR: {row['avg_pred']:.0f}%")
            print(f"  Gap: {row['avg_pred'] - wr:.0f}pp")
            print(f"  Avg return: {row['avg_ret']:.2f}%")

# Check by horizon
print("\n" + "="*80)
print("BY HORIZON (March):")
print("="*80)

cur = conn.execute('''
SELECT 
  horizon_label,
  COUNT(*) as trades,
  SUM(CASE WHEN actual_return_pct > 0 THEN 1 ELSE 0 END) as wins,
  AVG(actual_return_pct) as avg_ret,
  AVG(predicted_win_rate) as pred_wr
FROM shadow_trades 
WHERE patterns LIKE '%bullish_harami%'
  AND entry_date >= '2026-03-01'
  AND status NOT LIKE 'SHADOW_OPEN%'
GROUP BY horizon_label
ORDER BY trades DESC
''')

for row in cur.fetchall():
    if row['trades']:
        wr = row['wins'] / row['trades'] * 100
        gap = row['pred_wr'] - wr
        print(f"\n{row['horizon_label']}:")
        print(f"  Trades: {row['trades']}")
        print(f"  Real WR: {wr:.0f}%")
        print(f"  Predicted: {row['pred_wr']:.0f}%")
        print(f"  Gap: {gap:.0f}pp")
        print(f"  Avg return: {row['avg_ret']:.2f}%")

print("\n" + "="*80)
