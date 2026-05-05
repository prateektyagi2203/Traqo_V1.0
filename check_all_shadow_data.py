#!/usr/bin/env python3
"""Check all shadow trade data available"""
import sqlite3

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

print("="*80)
print("SHADOW TRADES: Complete Data Inventory")
print("="*80)

# Total shadow trades by month
print("\nSHADOW TRADES COUNT BY MONTH:")
cur = conn.execute('''
SELECT 
  SUBSTR(entry_date, 1, 7) as month,
  COUNT(*) as total,
  SUM(CASE WHEN status LIKE 'SHADOW_OPEN%' THEN 1 ELSE 0 END) as still_open,
  SUM(CASE WHEN status NOT LIKE 'SHADOW_OPEN%' THEN 1 ELSE 0 END) as closed
FROM shadow_trades 
GROUP BY month
ORDER BY month DESC
''')

for row in cur.fetchall():
    print(f"  {row['month']}: {row['total']:4} total ({row['closed']:3} closed, {row['still_open']:3} still open)")

# Check if bullish_harami exists in shadow trades at all
print("\nBULLISH_HARAMI IN SHADOW TRADES:")
cur = conn.execute('''
SELECT COUNT(*) as cnt FROM shadow_trades WHERE patterns LIKE '%bullish_harami%'
''')
cnt = cur.fetchone()['cnt']
print(f"  Total bullish_harami shadow trades: {cnt}")

if cnt > 0:
    print("\n  Breakdown by status:")
    cur = conn.execute('''
    SELECT status, COUNT(*) as cnt FROM shadow_trades 
    WHERE patterns LIKE '%bullish_harami%'
    GROUP BY status
    ''')
    for row in cur.fetchall():
        print(f"    {row['status']:<20}: {row['cnt']}")
    
    print("\n  Performance (if any closed):")
    cur = conn.execute('''
    SELECT 
      COUNT(*) as total,
      SUM(CASE WHEN actual_return_pct > 0 THEN 1 ELSE 0 END) as wins,
      AVG(actual_return_pct) as avg_ret
    FROM shadow_trades 
    WHERE patterns LIKE '%bullish_harami%'
      AND status NOT LIKE 'SHADOW_OPEN%'
    ''')
    for row in cur.fetchall():
        if row['total']:
            wr = row['wins'] / row['total'] * 100 if row['wins'] else 0
            print(f"    Win Rate: {wr:.0f}% ({row['wins']}/{row['total']} wins)")
            print(f"    Avg Return: {row['avg_ret']:.2f}%")
        else:
            print(f"    No closed shadow trades yet")
else:
    print("  ❌ NO bullish_harami shadow trades found")

# Check what patterns HAVE shadow data
print("\n" + "="*80)
print("PATTERNS WITH MOST SHADOW TRADES:")
cur = conn.execute('''
SELECT patterns, COUNT(*) as cnt FROM shadow_trades 
GROUP BY patterns
ORDER BY cnt DESC
LIMIT 10
''')

for row in cur.fetchall():
    print(f"  {row['patterns']:<40}: {row['cnt']:4}")

print("\n" + "="*80)
