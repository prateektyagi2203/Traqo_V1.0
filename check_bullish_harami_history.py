#!/usr/bin/env python3
"""Check: Did bullish_harami actually work in February?"""
import sqlite3

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

print("="*80)
print("BULLISH_HARAMI PERFORMANCE ANALYSIS")
print("="*80)

# February bullish_harami
print("\nFEBRUARY BULLISH_HARAMI TRADES:")
cur = conn.execute('''
SELECT 
  COUNT(*) as total,
  SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
  AVG(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN actual_return_pct END) as avg_win,
  AVG(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN actual_return_pct END) as avg_loss
FROM trades 
WHERE patterns LIKE '%bullish_harami%' 
  AND entry_date >= '2026-02-01' AND entry_date < '2026-03-01'
  AND status != 'OPEN'
''')

for row in cur.fetchall():
    if row['total']:
        wr = row['wins'] / row['total'] * 100 if row['total'] else 0
        pf = abs(row['avg_win'] * row['wins']) / abs(row['avg_loss'] * row['losses']) if row['losses'] and row['avg_loss'] else 0
        print(f"  Total: {row['total']}")
        print(f"  Wins: {row['wins']}, Losses: {row['losses']}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Avg Win: {row['avg_win']:.2f}% | Avg Loss: {row['avg_loss']:.2f}%")
        print(f"  Profit Factor: {pf:.2f}")
    else:
        print("  NO TRADES FOUND")

# March bullish_harami
print("\nMARCH BULLISH_HARAMI TRADES (so far):")
cur = conn.execute('''
SELECT 
  COUNT(*) as total,
  SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
  SUM(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN 1 ELSE 0 END) as losses,
  AVG(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN actual_return_pct END) as avg_win,
  AVG(CASE WHEN status IN ('LOST','EXPIRED_LOSS') THEN actual_return_pct END) as avg_loss
FROM trades 
WHERE patterns LIKE '%bullish_harami%' 
  AND entry_date >= '2026-03-01'
  AND status != 'OPEN'
''')

for row in cur.fetchall():
    if row['total']:
        wr = row['wins'] / row['total'] * 100 if row['total'] else 0
        pf = abs(row['avg_win'] * row['wins']) / abs(row['avg_loss'] * row['losses']) if row['losses'] and row['avg_loss'] else 0
        print(f"  Total: {row['total']}")
        print(f"  Wins: {row['wins']}, Losses: {row['losses']}")
        print(f"  Win Rate: {wr:.1f}%")
        print(f"  Avg Win: {row['avg_win']:.2f}% | Avg Loss: {row['avg_loss']:.2f}%")
        print(f"  Profit Factor: {pf:.2f}")
    else:
        print("  NO TRADES FOUND (NEW - not yet closed)")

# Check all patterns in February for comparison
print("\n" + "="*80)
print("TOP PERFORMING PATTERNS IN FEBRUARY (for comparison):")
print("="*80)
cur = conn.execute('''
SELECT 
  patterns,
  COUNT(*) as total,
  SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) as wins,
  CAST(SUM(CASE WHEN status IN ('WON','EXPIRED_WIN') THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100 as win_rate
FROM trades 
WHERE entry_date >= '2026-02-01' AND entry_date < '2026-03-01'
  AND status != 'OPEN'
GROUP BY patterns
ORDER BY win_rate DESC
LIMIT 10
''')

for row in cur.fetchall():
    print(f"{row['patterns']:<30} : {row['total']:3} trades, {row['win_rate']:.0f}% WR")

print("\n" + "="*80)
