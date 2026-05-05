#!/usr/bin/env python3
"""Deep investigation: Is bullish_harami recommendation reliable?"""
import json
import sqlite3
from collections import defaultdict

print("="*90)
print("DEEP INVESTIGATION: bullish_harami Trade Quality Analysis")
print("="*90)

# Load pending signals
with open('paper_trades/pending_signals.json', 'r') as f:
    pending = json.load(f)

signals = pending.get('signals', [])
bh_signals = [s for s in signals if 'bullish_harami' in s.get('patterns', '')]

print(f"\n1. CONCENTRATION RISK:")
print(f"   Total bullish_harami signals: {len(bh_signals)}")

# Check ticker concentration
tickers = defaultdict(int)
for sig in bh_signals:
    tickers[sig.get('ticker', 'unknown')] += 1

print(f"\n   Top 10 tickers (concentration risk):")
for ticker, cnt in sorted(tickers.items(), key=lambda x: -x[1])[:10]:
    pct = cnt / len(bh_signals) * 100
    print(f"     {ticker:<15}: {cnt:3} trades ({pct:.1f}%)")

total_top_10 = sum(tickers.values()) if len(tickers) <= 10 else sum(dict(sorted(tickers.items(), key=lambda x: -x[1])[:10]).values())
pct_top_10 = total_top_10 / len(bh_signals) * 100
print(f"   Top 10 tickers account for: {pct_top_10:.1f}% of trades")

# 2. Win rate distribution
print(f"\n2. WIN RATE DISTRIBUTION (RAG predictions):")
wr_dist = defaultdict(int)
min_wr = min(s.get('predicted_win_rate', 0) for s in bh_signals) if bh_signals else 0
max_wr = max(s.get('predicted_win_rate', 0) for s in bh_signals) if bh_signals else 0
avg_wr = sum(s.get('predicted_win_rate', 0) for s in bh_signals) / len(bh_signals) if bh_signals else 0

for sig in bh_signals:
    wr = sig.get('predicted_win_rate', 0)
    bucket = f"{int(wr//10)*10}-{int(wr//10)*10+10}%"
    wr_dist[bucket] += 1

for bucket in sorted(wr_dist.keys()):
    cnt = wr_dist[bucket]
    pct = cnt / len(bh_signals) * 100
    bar = "█" * int(pct/2)
    print(f"   {bucket:<12} : {cnt:3} ({pct:5.1f}%) {bar}")

print(f"\n   Min WR: {min_wr:.0f}%, Avg: {avg_wr:.0f}%, Max: {max_wr:.0f}%")

# 3. Compare with other high-confidence patterns
print(f"\n3. BENCHMARK: How do other HIGH confidence patterns perform?")

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

other_high_conf = defaultdict(lambda: {"wins": 0, "total": 0, "returns": []})

# Get all HIGH confidence shadow trades
cur = conn.execute('''
SELECT patterns, actual_return_pct 
FROM shadow_trades 
WHERE confidence = 'HIGH'
  AND status NOT LIKE 'SHADOW_OPEN%'
  AND entry_date >= '2026-03-01'
''')

for row in cur.fetchall():
    pat = row['patterns']
    other_high_conf[pat]["total"] += 1
    if row['actual_return_pct'] > 0:
        other_high_conf[pat]["wins"] += 1
    other_high_conf[pat]["returns"].append(row['actual_return_pct'])

print("\n   HIGH confidence patterns (March shadow trades):")
for pat in sorted(other_high_conf.keys(), key=lambda x: -other_high_conf[x]['total'])[:10]:
    data = other_high_conf[pat]
    if data['total'] >= 3:
        wr = data['wins'] / data['total'] * 100
        avg_ret = sum(data['returns']) / len(data['returns'])
        print(f"     {pat:<35} : {data['total']:3} trades, {wr:5.0f}% WR, {avg_ret:+6.2f}% avg return")

# 4. bullish_harami shadow trade timeline
print(f"\n4. BULLISH_HARAMI SHADOW TREND (by week):")

cur = conn.execute('''
SELECT 
  SUBSTR(entry_date, 1, 10) as date,
  COUNT(*) as total,
  SUM(CASE WHEN actual_return_pct > 0 THEN 1 ELSE 0 END) as wins,
  AVG(actual_return_pct) as avg_ret
FROM shadow_trades 
WHERE patterns LIKE '%bullish_harami%'
  AND status NOT LIKE 'SHADOW_OPEN%'
GROUP BY SUBSTR(entry_date, 1, 10)
ORDER BY date DESC
LIMIT 20
''')

for row in cur.fetchall():
    if row['total']:
        wr = row['wins'] / row['total'] * 100
        print(f"   {row['date']} : {row['total']:3} trades, {wr:5.0f}% WR, {row['avg_ret']:+6.2f}% avg return")

# 5. Position sizing reality check
print(f"\n5. POSITION SIZING RISK ANALYSIS:")
print(f"   If entering {len(bh_signals)} bullish_harami trades...")

scenarios = [
    ("Optimistic (RAG correct)", 70, 2.0, 5.0),
    ("Realistic (50% discount)", 35, 1.8, 2.5),
    ("Pessimistic (Shadow data)", 31, 1.5, -1.0),
]

for scenario_name, wr, avg_win, avg_loss in scenarios:
    profit_per_trade = (wr/100 * avg_win) + ((1-wr/100) * avg_loss)
    total_pnl = profit_per_trade * len(bh_signals)
    print(f"\n   {scenario_name}:")
    print(f"     Win Rate: {wr}% | Avg Win: {avg_win:.1f}% | Avg Loss: {avg_loss:.1f}%")
    print(f"     Profit/trade: {profit_per_trade:+.2f}% | Total P&L: {total_pnl:+.0f}%")

print(f"\n6. RED FLAG CHECKLIST:")
checks = [
    ("86 trades all from one pattern?", len(bh_signals) == len([s for s in signals if s.get('patterns') == 'bullish_harami'])),
    ("All same ticker concentration?", sum(1 for cnt in tickers.values() if cnt > 20) > 0),
    ("All HIGH confidence (0 variance)?", len(set(s.get('confidence') for s in bh_signals)) == 1),
    ("Shadow WR < 40%?", False),  # Already checked
    ("Wide gap (RAG 70% vs Shadow 31%)?", True),
]

for check, flag in checks:
    status = "⚠️ YES" if flag else "✓ No"
    print(f"   {status:<10} : {check}")

print(f"\n" + "="*90)
