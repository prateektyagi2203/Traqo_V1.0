#!/usr/bin/env python3
"""Check shadow trade feedback for bullish_harami pattern"""
import sqlite3

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

print("="*80)
print("SHADOW TRADE FEEDBACK: bullish_harami Analysis")
print("="*80)

# Check if shadow_trades table exists
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shadow_trades'")
if not cur.fetchone():
    print("❌ No shadow_trades table found")
    print("\nLet me check what tables exist:")
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    for row in cur.fetchall():
        print(f"   - {row['name']}")
else:
    print("✓ shadow_trades table found\n")
    
    # Check schema
    cur = conn.execute("PRAGMA table_info(shadow_trades)")
    cols = [row['name'] for row in cur.fetchall()]
    print(f"Columns: {', '.join(cols)}\n")
    
    # February shadow bullish_harami
    print("FEBRUARY SHADOW TRADES - bullish_harami:")
    cur = conn.execute('''
    SELECT 
      COUNT(*) as total,
      SUM(CASE WHEN status IN ('SHADOW_WIN','CLOSED_WIN') THEN 1 ELSE 0 END) as wins,
      SUM(CASE WHEN status IN ('SHADOW_LOSS','CLOSED_LOSS') THEN 1 ELSE 0 END) as losses,
      AVG(CASE WHEN status IN ('SHADOW_WIN','CLOSED_WIN') THEN actual_return_pct END) as avg_win,
      AVG(CASE WHEN status IN ('SHADOW_LOSS','CLOSED_LOSS') THEN actual_return_pct END) as avg_loss
    FROM shadow_trades 
    WHERE patterns LIKE '%bullish_harami%' 
      AND entry_date >= '2026-02-01' AND entry_date < '2026-03-01'
      AND status NOT LIKE 'SHADOW_OPEN%'
    ''')
    
    for row in cur.fetchall():
        if row['total']:
            wr = row['wins'] / row['total'] * 100 if row['total'] else 0
            pf = abs(row['avg_win'] * row['wins']) / abs(row['avg_loss'] * row['losses']) if row['losses'] and row['avg_loss'] else 0
            print(f"  Total Shadow: {row['total']}")
            print(f"  Wins: {row['wins']}, Losses: {row['losses']}")
            print(f"  Shadow Win Rate: {wr:.1f}%")
            print(f"  Avg Win: {row['avg_win']:.2f}% | Avg Loss: {row['avg_loss']:.2f}%")
            print(f"  Shadow Profit Factor: {pf:.2f}")
        else:
            print("  NO SHADOW TRADES FOUND")
    
    # All shadow patterns in February
    print("\n" + "="*80)
    print("TOP SHADOW TRADES BY WIN RATE (February):")
    print("="*80)
    cur = conn.execute('''
    SELECT 
      patterns,
      COUNT(*) as total,
      SUM(CASE WHEN status IN ('SHADOW_WIN','CLOSED_WIN') THEN 1 ELSE 0 END) as wins,
      CAST(SUM(CASE WHEN status IN ('SHADOW_WIN','CLOSED_WIN') THEN 1 ELSE 0 END) AS FLOAT) / 
        NULLIF(COUNT(*), 0) * 100 as shadow_wr
    FROM shadow_trades 
    WHERE entry_date >= '2026-02-01' AND entry_date < '2026-03-01'
      AND status NOT LIKE 'SHADOW_OPEN%'
    GROUP BY patterns
    HAVING COUNT(*) >= 3
    ORDER BY shadow_wr DESC
    LIMIT 15
    ''')
    
    found = False
    for row in cur.fetchall():
        found = True
        emoji = "✓" if "bullish_harami" in row['patterns'] else " "
        print(f"{emoji} {row['patterns']:<35} : {row['total']:3} shadow, {row['shadow_wr']:.0f}% WR")
    
    if not found:
        print("No shadow trades with 3+ occurrences found")

print("\n" + "="*80)
