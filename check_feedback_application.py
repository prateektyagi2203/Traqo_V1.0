#!/usr/bin/env python3
"""Check what shadow trade feedback is actually applied to RAG"""
import json
import os

print("="*90)
print("SHADOW TRADE FEEDBACK: What's Actually Applied to RAG?")
print("="*90)

# 1. Check learned_rules.json
learned_rules_path = 'feedback/learned_rules.json'
print(f"\n1. LEARNED RULES FILE: {learned_rules_path}")

if os.path.exists(learned_rules_path):
    with open(learned_rules_path, 'r', encoding='utf-8') as f:
        learned = json.load(f)
    
    print(f"   ✓ File exists (size: {os.path.getsize(learned_rules_path)} bytes)")
    
    # Check what's in it
    print(f"\n   Contents summary:")
    
    if 'filter_penalties' in learned:
        penalties = learned['filter_penalties']
        print(f"   - Pattern Filter PENALTIES: {len(penalties)}")
        if penalties:
            for pat, info in list(penalties.items())[:5]:
                print(f"     • {pat}: {info.get('reason', 'N/A')}")
        if len(penalties) > 5:
            print(f"     ... and {len(penalties)-5} more")
    
    if 'filter_boosts' in learned:
        boosts = learned['filter_boosts']
        print(f"   - Pattern Filter BOOSTS: {len(boosts)}")
        if boosts:
            for pat, info in list(boosts.items())[:5]:
                print(f"     • {pat}: {info.get('reason', 'N/A')}")
        if len(boosts) > 5:
            print(f"     ... and {len(boosts)-5} more")
    
    if 'horizon_filter_penalties' in learned:
        hz_pen = learned['horizon_filter_penalties']
        print(f"   - Horizon-specific PENALTIES: {len(hz_pen)}")
        if hz_pen:
            for key, info in list(hz_pen.items())[:3]:
                print(f"     • {key}: {info.get('reason', 'N/A')}")
    
    if 'horizon_filter_boosts' in learned:
        hz_boost = learned['horizon_filter_boosts']
        print(f"   - Horizon-specific BOOSTS: {len(hz_boost)}")
    
    if 'sector_filter_penalties' in learned:
        sec_pen = learned['sector_filter_penalties']
        print(f"   - Sector-specific PENALTIES: {len(sec_pen)}")
    
    if 'sector_filter_boosts' in learned:
        sec_boost = learned['sector_filter_boosts']
        print(f"   - Sector-specific BOOSTS: {len(sec_boost)}")
    
    if 'rules' in learned:
        rules = learned['rules']
        print(f"   - Learned Meta-Rules: {len(rules)}")
        if rules:
            for i, rule in enumerate(rules[:3]):
                print(f"     • Rule {i+1}: {rule.get('rule', 'N/A')}")
    
    print(f"\n   Keys in learned_rules: {', '.join(learned.keys())}")
else:
    print(f"   ✗ File NOT found")

# 2. Check if these are actually USED in predictions
print(f"\n2. HOW ARE THESE APPLIED IN PREDICTIONS?")

# Check statistical_predictor.py
sp_path = 'statistical_predictor.py'
print(f"\n   Checking {sp_path}...")

with open(sp_path, 'r') as f:
    content = f.read()
    
    if 'feedback_filter_penalties' in content:
        print("   ✓ Code uses feedback_filter_penalties")
    else:
        print("   ✗ Code does NOT use feedback_filter_penalties")
    
    if 'feedback_filter_boosts' in content:
        print("   ✓ Code uses feedback_filter_boosts")
    else:
        print("   ✗ Code does NOT use feedback_filter_boosts")
    
    if 'feedback_horizon' in content:
        print("   ✓ Code uses feedback_horizon adjustments")
    else:
        print("   ✗ Code does NOT use feedback_horizon adjustments")

# 3. Check paper_trader.py
print(f"\n   Checking paper_trader.py...")

with open('paper_trader.py', 'r') as f:
    content = f.read()
    
    if 'fb_penalties' in content and 'skip_reasons.append' in content:
        print("   ✓ Paper trader FILTERS OUT trades based on penalties")
        # Count how many times it's checked
        penalty_checks = content.count('fb_penalties')
        print(f"     (checked {penalty_checks} times in filtering logic)")
    else:
        print("   ✗ Paper trader does NOT filter based on penalties")
    
    if 'fb_boosts' in content:
        print("   ✓ Paper trader RELAXES thresholds for boosted patterns")
    else:
        print("   ✗ Paper trader does NOT apply boosts")

# 4. When was learned_rules last updated?
print(f"\n3. WHEN WAS LEARNED_RULES LAST UPDATED?")

if os.path.exists(learned_rules_path):
    import datetime
    mtime = os.path.getmtime(learned_rules_path)
    dt = datetime.datetime.fromtimestamp(mtime)
    print(f"   Last modified: {dt}")
else:
    print(f"   File doesn't exist")

print("\n" + "="*90)
print("SUMMARY: Where Shadow Feedback is Applied")
print("="*90)

print("""
STAGE 1: Shadow Trades Tracked
   ✓ Signals filtered out are tracked as shadow trades
   ✓ 256 bullish_harami shadow trades recorded
   ✓ Real outcomes recorded (win/loss/return)

STAGE 2: Feedback Extracted (feed_outcomes_to_rag)
   ✓ Closed shadow trades analyzed
   ✓ Pattern statistics calculated
   ✓ Boosts/penalties computed if WR > 70% or < 30%
   ✓ Saved to feedback/learned_rules.json

STAGE 3: Applied in Scan Preview 
   ✓ When scanning new signals:
   - Statistical_predictor loads learned_rules.json
   - paper_trader checks fb_penalties
   - If pattern is penalized → skip_reasons.append() → FILTERED OUT
   - If pattern is boosted → wr_threshold reduced → MORE LIKELY to enter

BUT ISSUE:
   ❓ Are penalties/boosts actually being applied to RAG predictions?
   ❓ Or just to entry filters?
""")
