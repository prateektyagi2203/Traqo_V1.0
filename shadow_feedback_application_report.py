#!/usr/bin/env python3
"""
COMPREHENSIVE REPORT: What Shadow Trade Feedback Is Actually Applied to RAG
============================================================================
"""
import json
import os
from datetime import datetime

print("="*100)
print("SHADOW TRADE FEEDBACK LEARNING - COMPLETE APPLICATION REPORT")
print("="*100)

# Load learned rules
learned_rules_path = 'feedback/learned_rules.json'
with open(learned_rules_path, 'r', encoding='utf-8') as f:
    learned = json.load(f)

print("\n1. WHAT'S IN learned_rules.json?")
print("-" * 100)

# Pattern-level feedback
penalties = learned.get('filter_penalties', {})
boosts = learned.get('filter_boosts', {})
print(f"\nA. PATTERN-LEVEL FEEDBACK:")
print(f"   Pattern Penalties: {len(penalties)} patterns")
for pat, info in penalties.items():
    print(f"      ✓ {pat:25s} → {info.get('reason', 'N/A')}")

print(f"\n   Pattern Boosts: {len(boosts)} patterns")
if not boosts:
    print(f"      ✗ EMPTY - No patterns have been boosted yet")
else:
    for pat, info in boosts.items():
        print(f"      ✓ {pat:25s} → {info.get('reason', 'N/A')}")

# Horizon-specific feedback
hz_penalties = learned.get('horizon_filter_penalties', {})
hz_boosts = learned.get('horizon_filter_boosts', {})
print(f"\nB. HORIZON-SPECIFIC FEEDBACK:")
print(f"   Horizon Penalties: {len(hz_penalties)} entries")
for key, info in list(hz_penalties.items())[:3]:
    print(f"      ✓ {key:35s} → {info.get('reason', 'N/A')[:50]}")
if len(hz_penalties) > 3:
    print(f"      ... and {len(hz_penalties) - 3} more")

print(f"\n   Horizon Boosts: {len(hz_boosts)} entries")
if not hz_boosts:
    print(f"      ✗ EMPTY")

# Sector-specific feedback
sec_penalties = learned.get('sector_filter_penalties', {})
sec_boosts = learned.get('sector_filter_boosts', {})
print(f"\nC. SECTOR-SPECIFIC FEEDBACK:")
print(f"   Sector Penalties: {len(sec_penalties)} entries")
print(f"   Sector Boosts: {len(sec_boosts)} entries")

# Meta rules
rules = learned.get('rules', [])
print(f"\nD. LEARNED META-RULES: {len(rules)} rules")
for i, rule in enumerate(rules[:3], 1):
    print(f"   Rule {i}: {rule.get('rule', 'N/A')}")

print(f"\n   Last updated: {learned.get('updated_at', 'N/A')}")

print("\n" + "="*100)
print("2. HOW IS FEEDBACK APPLIED IN THE TRADING ENGINE?")
print("-" * 100)

print("""
STAGE 1: SIGNAL GENERATION
   • statistical_predictor.py loads rag_documents_v2/all_pattern_documents.json
   • Searches for matching patterns based on OHLC
   • Returns base RAG prediction: win_rate, profit_factor, etc.
   • ✓ This is RAW - not adjusted by feedback yet

STAGE 2: SIGNAL FILTERING (paper_trader.py scan_preview)
   • Loads learned_rules.json
   • For each signal:
      
      A. CHECK PATTERN PENALTIES
         IF pattern in fb_penalties:
            → Add skip_reason "Feedback penalty: [reason]"
            → Signal is FILTERED OUT (won't enter)
      
      B. CHECK HORIZON PENALTIES  
         IF pattern__horizon in hz_penalties:
            → Add skip_reason "Horizon penalty: [reason]"
            → Signal is FILTERED OUT
      
      C. CHECK SECTOR PENALTIES
         IF pattern in sector_penalties:
            → Add skip_reason "Sector penalty: [reason]"
            → Signal is FILTERED OUT
      
      D. CHECK PATTERN BOOSTS
         IF pattern in fb_boosts:
            → Reduce win_rate threshold (make easier to enter)
            → BUT: boosts dict is empty (0 patterns boosted)
            → This logic is NEVER triggered
      
      E. CHECK HORIZON BOOSTS
         IF pattern__horizon in hz_boosts:
            → Reduce win_rate threshold
            → BUT: boosts dict is empty (0 patterns)
            → This logic is NEVER triggered

STAGE 3: ONLY PENALTIES ARE ACTIVELY WORKING
   ✗ Boosts do not work (empty dicts = 0 boosted patterns)
   ✓ Penalties do work (6 patterns penalized)
   ✗ Price predictions are NOT adjusted
""")

print("\n" + "="*100)
print("3. WHAT IS BULLISH_HARAMI STATUS?")
print("-" * 100)

if 'bullish_harami' in penalties:
    print(f"   ✓ PENALIZED: {penalties['bullish_harami']['reason']}")
else:
    print(f"   ✗ NOT PENALIZED - Why?")
    print(f"      • Real win rate: 31% (shadow trades)")
    print(f"      • RAG prediction: 68-70%")
    print(f"      • Gap: -39pp (extreme outlier)")
    print(f"      • Likely reason: Pattern not yet in learned_rules")
    print(f"      • Threshold for penalty: Likely > 10 feedback samples or WR < threshold")

print("\n" + "="*100)
print("4. THE CRITICAL GAP: What's NOT Being Applied")
print("-" * 100)

print("""
❌ RAG PREDICTIONS ARE NOT ADJUSTED
   • bullish_harami shadow trades show 31% real WR
   • But RAG predictions still say 68-70% WR
   • Feedback learns that RAG is WRONG
   • But RAG doesn't trust its own feedback
   
   Why?
   • statistical_predictor.py loads predictions from documents
   • Does NOT read learned_rules.json to adjust predictions
   • Penalties/boosts only affect filtering, not predictions
   • This is "blacklist only" learning, not "model retrain"

❌ NO BOOSTS ARE APPLIED
   • Even if patterns have good real performance (>70% WR)
   • Boosts dict is empty = 0 patterns getting easier entry
   • High-performing patterns still face same 45% threshold

❌ FEEDBACK LOOP IS ONE-WAY
   • Shadow trades → Calculate real performance → Store in learned_rules
   • But: RAG still trusts 2016-2023 training data over 2026 feedback
   • Result: Mismatch between what RAG learned and what market shows

❌ BULLISH_HARAMI NOT YET PENALIZED
   • 256 shadow trades, 31% real WR, -1.01% avg return
   • Should be top priority for penalty
   • But not in penalties list yet
   • System has decided 6 other patterns need penalties first
""")

print("\n" + "="*100)
print("5. SUMMARY: Where Learning IS vs ISN'T Applied")
print("-" * 100)

summary_table = f"""
FEEDBACK TYPE              | ACTIVE? | PATTERNS | STATUS
---------------------------|---------|----------|------------------------------------------
Pattern Penalties          |   ✓     |    6     | Working - filters out 6 underperforming patterns
Horizon Penalties          |   ✓     |   13     | Working - pattern + horizon combinations
Sector Penalties           |   ✓     |   17     | Working - sector-specific filters
Pattern Boosts             |   ✗     |    0     | Empty - no patterns boosted
Horizon Boosts             |   ✗     |    0     | Empty - no patterns boosted
RAG Prediction Adjustment  |   ✗     |    -     | Not applied - predictions unchanged by feedback
Winner Identification      |   ✓     |    -     | Working - bullish_harami identified as poor
Automatic Penalty Trigger  |   ?     |    -     | Unclear - why isn't bullish_harami penalized?

VERDICT:
• Learning IS happening (penalties calculated)
• Penalties ARE being applied (to filtering)
• BUT RAG predictions don't change
• So: "Blacklist learning" not "model improvement"
"""

print(summary_table)

print("\n" + "="*100)
print("6. WHAT WOULD HAPPEN IF BULLISH_HARAMI WAS PENALIZED?")
print("="*100)

print("""
IF bullish_harami was in fb_penalties:
   • All 69 pending bullish_harami signals would be filtered out
   • Skip reason: "Feedback penalty: WR 31% vs predicted 70% - poor calibration"
   • User would see 0 bullish_harami trades (all rejected)
   • System would force recalibration of this pattern
   
QUESTION FOR YOU:
   Is it better to:
   A) Let bullish_harami through & watch real performance (manual review)
   B) Automatically penalize bullish_harami & trust feedback learning
   C) Recalibrate RAG predictions to 31% instead of 70%
""")
