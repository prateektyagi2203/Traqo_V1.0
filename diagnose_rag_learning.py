import json

# Check if bullish_harami is in pattern_adjustments
lr = json.load(open('feedback/learned_rules.json', encoding='utf-8'))

print("LEARNED_RULES STRUCTURE:")
print("="*80)

# Check pattern_adjustments
pattern_adj = lr.get('pattern_adjustments', {})
print(f"\n1. Pattern Adjustments: {len(pattern_adj)} patterns")
if 'bullish_harami' in pattern_adj:
    bh = pattern_adj['bullish_harami']
    print(f"   ✓ bullish_harami FOUND:")
    print(f"     - Actual WR: {bh.get('actual_win_rate')}%")
    print(f"     - Decay WR: {bh.get('decay_weighted_win_rate')}%")
    print(f"     - Total trades: {bh.get('total_trades')}")
    print(f"     - Note: {bh.get('note')}")
else:
    print(f"   ✗ bullish_harami NOT in pattern_adjustments")
    print(f"     Patterns in adjustments: {list(pattern_adj.keys())}")

# Check horizon-specific
hz_adj = lr.get('horizon_adjustments', {})
bh_entries = [k for k in hz_adj.keys() if 'bullish_harami' in k]
print(f"\n2. Horizon Adjustments: {len(bh_entries)} bullish_harami entries")
for key in bh_entries[:3]:
    val = hz_adj[key]
    print(f"   ✓ {key}: WR={val.get('win_rate')}%, trades={val.get('total_trades')}")

# Check triple-specific
triple_adj = lr.get('triple_adjustments', {})
bh_triple = [k for k in triple_adj.keys() if 'bullish_harami' in k]
print(f"\n3. Triple Adjustments: {len(bh_triple)} bullish_harami entries")
for key in bh_triple[:3]:
    val = triple_adj[key]
    print(f"   ✓ {key}: WR={val.get('win_rate')}%, trades={val.get('total_trades')}")

# Check what the problem is
print("\n" + "="*80)
print("DIAGNOSIS:")
print("="*80)

if 'bullish_harami' in pattern_adj:
    adj = pattern_adj['bullish_harami']
    trades = adj.get('total_trades', 0)
    if trades >= 2:
        print(f"✓ bullish_harami HAS feedback data ({trades} trades)")
        print(f"  Paper WR: {adj.get('actual_win_rate')}%")
        print(f"  SHOULD blend into predictions...")
        print(f"  Weight: min(50%, {trades}/({trades}+20)) = {min(50, trades*100/(trades+20)):.1f}%")
    else:
        print(f"✗ bullish_harami has only {trades} trades - BELOW threshold")
else:
    # Check shadow trades
    horizon_adj = lr.get('horizon_adjustments', {})
    bh_entries = {k:v for k,v in horizon_adj.items() if 'bullish_harami' in k}
    
    if bh_entries:
        print(f"✓ bullish_harami feedback EXISTS but scattered:")
        total_bh_trades = sum(e.get('total_trades', 0) for e in bh_entries.values())
        print(f"  Total distributed across {len(bh_entries)} horizon+sector combos")
        print(f"  Total trades: {total_bh_trades}")
        print(f"  Problem: Fragmented, not aggregated to pattern level")
    else:
        print(f"✗ bullish_harami has NO feedback data!")

print("\n" + "="*80)
print("WHY RAG ISN'T SELF-CORRECTING:")
print("="*80)

print("""
The Infrastructure EXISTS:
  ✓ feed_outcomes_to_rag() calculates performance
  ✓ _apply_feedback() blends paper WR into predictions (up to 50% weight)
  ✓ Confidence scoring influenced by learned rules
  ✓ A/B tracking stores raw vs blended values

But SELF-LEARNING IS ONLY PARTIAL:

1. THRESHOLD PROBLEM:
   - Pattern needs 5+ trades to generate penalty
   - Pattern needs 10+ trades & >70% WR to generate boost
   - bullish_harami has 256 shadow trades but only 71 CLOSED
   - Need enough closed trades in pattern_adjustments bucket

2. CASCADING LOOKUP BREAKS:
   - When blending, code checks:
     * pattern__trend__horizon (most specific)
     * pattern__horizon
     * pattern__sector
     * pattern__trend
     * pattern (base level)
   - If bullish_harami spread across many horizon+sector combos
   - May NOT meet min 2-3 trades at pattern level
   - Falls through to lower-confidence boosts

3. LIMITED FEEDBACK-BASED PENALTIES:
   - Only 6 patterns penalized (blacklist only)
   - bullish_harami not blacklisted yet despite poor performance
   - Penalties are HARD rejections (filter → skip completely)
   - Blending is SOFT adjustment (50% at most)
   - Pattern with 31% real WR but no penalty = still enters at 68-70% confidence!

4. THE DESIGN GAP:
   - RAG WAS designed to be self-learning ✓
   - But confidence in 2016-2023 training >> confidence in March 2026 feedback
   - New feedback only gets 50% weight maximum
   - So: RAG mistrusts its own learning
""")
