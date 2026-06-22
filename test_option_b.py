#!/usr/bin/env python3
"""
Test Option B Implementation
Run feed_outcomes_to_rag() and verify blending works
"""
import json
import sys
sys.path.insert(0, '.')

from paper_trader import PaperTrader

print("="*100)
print("OPTION B TEST: Running feed_outcomes_to_rag() with shadow trade weighting")
print("="*100)

# Initialize engine
engine = PaperTrader()

# Step 1: Feed outcomes to RAG (includes shadow trades now)
print("\nStep 1: Feeding outcomes (real + shadow trades) to RAG...")
engine.feed_outcomes_to_rag()

# Step 2: Load learned_rules to check results
print("Step 2: Checking learned_rules.json...")
with open('feedback/learned_rules.json', 'r', encoding='utf-8') as f:
    learned = json.load(f)

pattern_adj = learned.get('pattern_adjustments', {})
print(f"\nPattern Adjustments: {len(pattern_adj)} patterns")

# Check bullish_harami
if 'bullish_harami' in pattern_adj:
    bh = pattern_adj['bullish_harami']
    actual_wr = bh.get('actual_win_rate', 0)
    decay_wr = bh.get('decay_weighted_win_rate', 0)
    total = bh.get('total_trades', 0)
    
    print(f"\n✓ BULLISH_HARAMI FOUND in pattern_adjustments:")
    print(f"  - Actual WR: {actual_wr}%")
    print(f"  - Decay-weighted WR: {decay_wr}% (this should be ~56% after shadow blending)")
    print(f"  - Total trades: {total}")
    print(f"  - Note: {bh.get('note', 'N/A')}")
    
    # Validate the blending
    if 50 <= decay_wr <= 62:
        print(f"\n  ✓ BLENDING WORKED: {decay_wr}% is between expected 50-62% range")
        print(f"    (Expected ~56%: blend(31% shadow × 0.6 + 70% RAG × 1.0) / 1.6 ≈ 54%)")
    else:
        print(f"\n  ⚠️ UNEXPECTED WR: {decay_wr}% is outside 50-62% range")
        print(f"    Check if shadow trades were correctly included & weighted")
else:
    print(f"\n✗ BULLISH_HARAMI NOT in pattern_adjustments")
    print(f"  Available patterns: {list(pattern_adj.keys())}")

# Check filters
print("\n" + "="*100)
print("Filter Status:")
penalties = learned.get('filter_penalties', {})
boosts = learned.get('filter_boosts', {})
print(f"Pattern Penalties: {len(penalties)}")
print(f"Pattern Boosts: {len(boosts)}")

if 'bullish_harami' in penalties:
    print(f"\n✓ bullish_harami IS penalized: {penalties['bullish_harami']['reason']}")
else:
    print(f"\n✗ bullish_harami NOT penalized")
    print(f"  Penalized patterns: {list(penalties.keys())}")

# Check feedback log
print("\n" + "="*100)
print("Feedback Log Summary:")
with open('feedback/feedback_log.json', 'r', encoding='utf-8') as f:
    feedback = json.load(f)

total_entries = len(feedback)
real_entries = sum(1 for e in feedback if e.get('source') == 'real_trade')
shadow_entries = sum(1 for e in feedback if e.get('source') == 'shadow_trade')
bh_entries = sum(1 for e in feedback if 'bullish_harami' in e.get('patterns', []))

print(f"Total feedback entries: {total_entries}")
print(f"  Real trades (source='real_trade'): {real_entries}")
print(f"  Shadow trades (source='shadow_trade'): {shadow_entries}")
print(f"  Bullish_harami entries: {bh_entries}")

print("\n" + "="*100)
print("NEXT STEPS:")
print("="*100)
print("""
1. If bullish_harami WR ≈ 56%:
   ✓ Shadow weighting is WORKING
   ✓ Run: python paper_trader.py scan
   ✓ Verify: 30-40 of the 69 trades are filtered out
   ✓ Approve remaining: python paper_trader.py approve

2. If bullish_harami WR is still 68-70%:
   ✗ Shadow trades not being weighted correctly
   ✗ Check: feedback_log.json has shadow entries with source='shadow_trade'
   ✗ Check: _update_learnings() is reading source field
   
3. If bullish_harami is not in pattern_adjustments at all:
   ✗ Shadow trades not being queried
   ✗ Check: self.db.conn.execute query for shadow_trades
   ✗ Verify: shadow_trades table has closed entries (exit_date NOT NULL)
""")
