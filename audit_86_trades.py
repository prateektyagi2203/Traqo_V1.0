#!/usr/bin/env python3
"""Deep audit of what changed - no bias"""
import json
import sqlite3
from collections import defaultdict

print("="*80)
print("CRITICAL AUDIT: Why 86 Trades Suddenly Appear?")
print("="*80)

# 1. Check pending_signals.json
try:
    with open('paper_trades/pending_signals.json', 'r') as f:
        pending = json.load(f)
    
    signals = pending.get('signals', [])
    print(f"\n1. PENDING SIGNALS COUNT: {len(signals)}")
    
    if signals:
        print("\n   Sample signal (first 3):")
        for i, sig in enumerate(signals[:3]):
            print(f"\n   Signal {i+1}:")
            print(f"     Ticker: {sig.get('ticker')}")
            print(f"     Patterns: {sig.get('patterns')}")
            print(f"     Predicted Win Rate: {sig.get('predicted_win_rate')}%")
            print(f"     Confidence: {sig.get('confidence')}")
            print(f"     R:R Ratio: {sig.get('rr_ratio')}")
            print(f"     Skip Reasons: {sig.get('skip_reasons', [])}")
    
    # 2. Check filter breakdown
    print(f"\n2. FILTER BREAKDOWN:")
    reasons = pending.get('skip_reason_summary', {})
    total_signals = pending.get('total_signals', 0)
    print(f"   Total signals found: {total_signals}")
    print(f"   Qualifying: {pending.get('qualifying', 0)}")
    print(f"   Filtered: {pending.get('filtered_out', 0)}")
    
    if reasons:
        print(f"\n   Filtered by (top 10):")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:10]:
            pct = count / total_signals * 100 if total_signals else 0
            print(f"     - {reason}: {count} ({pct:.1f}%)")
    
except Exception as e:
    print(f"ERROR reading pending_signals: {e}")

# 3. Check feedback learning rules
print(f"\n3. FEEDBACK LEARNING RULES:")
try:
    with open('feedback/learned_rules.json', 'r') as f:
        learned = json.load(f)
    
    boosts = learned.get('filter_boosts', {})
    penalties = learned.get('filter_penalties', {})
    
    print(f"   Active Pattern Boosts: {len(boosts)}")
    if boosts:
        print(f"   Boosted patterns (first 5):")
        for pat, info in list(boosts.items())[:5]:
            print(f"     - {pat}: action={info.get('action')}, reason={info.get('reason')}")
    
    print(f"\n   Active Pattern Penalties: {len(penalties)}")
    if penalties:
        print(f"   Penalized patterns (first 5):")
        for pat, info in list(penalties.items())[:5]:
            print(f"     - {pat}: action={info.get('action')}, reason={info.get('reason')}")

except Exception as e:
    print(f"ERROR reading learned_rules: {e}")

# 4. Compare with February baseline
print(f"\n4. FEBRUARY vs MARCH COMPARISON:")
conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

# February trades by day
cur = conn.execute('''
SELECT COUNT(*) as cnt FROM trades WHERE entry_date >= '2026-02-01' AND entry_date < '2026-03-01'
''')
feb_total = cur.fetchone()['cnt']
print(f"   February total trades: {feb_total} ({feb_total/28:.1f} per day average)")

# March trades
cur = conn.execute('''
SELECT COUNT(*) as cnt FROM trades WHERE entry_date >= '2026-03-01'
''')
mar_total = cur.fetchone()['cnt']
print(f"   March total trades (so far): {mar_total} ({mar_total/20:.1f} per day average)")

# Check win rates
cur = conn.execute('''
SELECT 
  CASE WHEN entry_date >= '2026-02-01' AND entry_date < '2026-03-01' THEN 'Feb'
       ELSE 'Mar' END as month,
  AVG(predicted_win_rate) as avg_wr,
  COUNT(*) as cnt
FROM trades 
WHERE status != 'OPEN'
GROUP BY month
''')
for row in cur.fetchall():
    print(f"   {row['month']}: Avg WR {row['avg_wr']:.1f}% ({row['cnt']} closed trades)")

print("\n" + "="*80)
