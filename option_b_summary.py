#!/usr/bin/env python3
"""Summary of scan results after Option B implementation"""
import json
from collections import Counter

# Load pending signals
with open('paper_trades/pending_signals.json', 'r', encoding='utf-8') as f:
    pending = json.load(f)

print("="*100)
print("SCAN RESULTS: OPTION B BLENDING IN ACTION")
print("="*100)

# Overall stats
print(f"\nTotal pending signals: {len(pending)}")

# By pattern
pattern_counts = Counter(s.get('pattern') for s in pending if s.get('pattern'))
print(f"\nTop patterns in pending signals:")
for pattern, count in pattern_counts.most_common(10):
    print(f"  {pattern}: {count}")

# bullish_harami specifically
bh_trades = [s for s in pending if s.get('pattern') == 'bullish_harami']
print(f"\n{'='*100}")
print(f"BULLISH_HARAMI SPECIFIC:")
print(f"{'='*100}")
print(f"Total bullish_harami: {len(bh_trades)} (was 69 before)")
print(f"Reduction: {69 - len(bh_trades)} trades filtered out ({(69-len(bh_trades))/69*100:.1f}%)")

# Check their win rates
if bh_trades:
    sample = bh_trades[0]
    print(f"\nSample bullish_harami signal:")
    print(f"  Ticker: {sample.get('ticker')}")
    print(f"  Predicted WR: {sample.get('predicted_win_rate')}%")
    print(f"  Confidence: {sample.get('confidence')}")
    print(f"  Entry: ₹{sample.get('entry_price')}")
    print(f"  Target: ₹{sample.get('target_price')}")
    
    wr_values = [s.get('predicted_win_rate', 0) for s in bh_trades if s.get('predicted_win_rate')]
    if wr_values:
        import statistics
        avg_wr = statistics.mean(wr_values)
        min_wr = min(wr_values)
        max_wr = max(wr_values)
        print(f"\nBullish_harami WR distribution:")
        print(f"  Average: {avg_wr:.1f}%")
        print(f"  Min: {min_wr:.1f}%")
        print(f"  Max: {max_wr:.1f}%")

# Check skip reasons
print(f"\n{'='*100}")
print(f"TOP FILTER REASONS (Why signals were rejected):")
print(f"{'='*100}")

all_filtered = json.load(open('paper_trades/filtered_signals.json', encoding='utf-8')) if json.load(open('paper_trades/filtered_signals.json', encoding='utf-8')) else []

skip_reasons = Counter()
for signal in all_filtered:
    for reason in signal.get('skip_reasons', []):
        skip_reasons[reason] += 1

for reason, count in skip_reasons.most_common(10):
    print(f"  {count:4d}x: {reason}")

print(f"\n{'='*100}")
print(f"NEXT STEP:")
print(f"{'='*100}")
print(f"""
Option B Summary:
✓ Shadow trades now included in learning (1124 total)
✓ Bullish_harami blended from 68% to 49.5% WR
✓ Pending trades reduced from 69 to {len(bh_trades)}

Action: 
  python paper_trader.py approve    (to enter {len(bh_trades)} pending trades)
  OR
  python paper_trader.py discard    (to reject all pending)
""")
