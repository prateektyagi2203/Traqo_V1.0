#!/usr/bin/env python3
"""Deep dive: What characteristics do the 86 qualifying trades have?"""
import json
from collections import defaultdict

with open('paper_trades/pending_signals.json', 'r') as f:
    pending = json.load(f)

signals = pending.get('signals', [])

print("="*80)
print("ANALYSIS: Characteristics of 86 Qualifying Trades")
print("="*80)

# Group by pattern
by_pattern = defaultdict(list)
by_confidence = defaultdict(int)
by_wr = defaultdict(int)
by_rr = []

for sig in signals:
    pattern = sig.get('patterns', 'unknown')
    by_pattern[pattern].append(sig)
    conf = sig.get('confidence', 'UNKNOWN')
    by_confidence[conf] += 1
    wr = sig.get('predicted_win_rate', 0)
    by_wr[wr] += 1
    by_rr.append(sig.get('rr_ratio', 0))

print("\n1. BY PATTERN:")
for pat, sigs in sorted(by_pattern.items(), key=lambda x: -len(x[1]))[:10]:
    avg_wr = sum(s.get('predicted_win_rate', 0) for s in sigs) / len(sigs) if sigs else 0
    print(f"   {pat:<30} : {len(sigs):3} trades (avg WR {avg_wr:.0f}%)")

print(f"\n2. BY CONFIDENCE:")
for conf, cnt in sorted(by_confidence.items(), key=lambda x: -x[1]):
    pct = cnt / len(signals) * 100
    print(f"   {conf:<15} : {cnt:3} trades ({pct:.1f}%)")

print(f"\n3. BY WIN RATE:")
for wr in sorted(set(by_wr.keys())):
    cnt = by_wr[wr]
    pct = cnt / len(signals) * 100
    print(f"   {wr:5.0f}%        : {cnt:3} trades ({pct:.1f}%)")

print(f"\n4. R:R RATIO STATS:")
avg_rr = sum(by_rr) / len(by_rr) if by_rr else 0
min_rr = min(by_rr) if by_rr else 0
max_rr = max(by_rr) if by_rr else 0
print(f"   Min R:R: {min_rr:.1f}x")
print(f"   Avg R:R: {avg_rr:.1f}x")
print(f"   Max R:R: {max_rr:.1f}x")

print(f"\n5. HORIZONS:")
by_horizon = defaultdict(int)
for sig in signals:
    hz = sig.get('horizon_label', 'unknown')
    by_horizon[hz] += 1

for hz, cnt in sorted(by_horizon.items(), key=lambda x: -x[1]):
    pct = cnt / len(signals) * 100
    print(f"   {hz:<15} : {cnt:3} trades ({pct:.1f}%)")

print("\n" + "="*80)
print("RED FLAGS CHECK:")
print("="*80)

# Check if all are same pattern
if len(by_pattern) == 1:
    print("⚠️  ALL 86 TRADES ARE SAME PATTERN! (Suspicious)")
    print(f"   Pattern: {list(by_pattern.keys())[0]}")

# Check if all same confidence
if len(by_confidence) == 1:
    print("⚠️  ALL 86 TRADES HAVE SAME CONFIDENCE! (Suspicious)")

# Check if all same win rate
if len(by_wr) == 1:
    print("⚠️  ALL 86 TRADES HAVE SAME WIN RATE! (ClipboardEvent source)")

# Check unusual patterns
if all(sig.get('predicted_win_rate', 0) >= 70 for sig in signals):
    print("⚠️  ALL 86 TRADES HAVE 70%+ WIN RATE (Unusually high - check if realistic)")

print("\n" + "="*80)
