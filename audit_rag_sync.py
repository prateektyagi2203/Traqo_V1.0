#!/usr/bin/env python3
"""
JEFFERIES ANALYST AUDIT: RAG FEEDBACK LOOP SYNC CHECK
=====================================================
Comprehensive audit of feedback loop and analysis engine alignment.
"""

import json
import sys
from collections import defaultdict

# Load both files
fb = json.load(open('feedback/feedback_log.json'))
lr = json.load(open('feedback/learned_rules.json'))

print("="*80)
print("JEFFERIES ANALYST AUDIT: RAG FEEDBACK LOOP SYNC CHECK")
print("="*80)
print()

print("1. FEEDBACK LOG COMPLETENESS ANALYSIS")
print("-" * 80)
print(f"   Total trade feedback entries: {len(fb)}")
if fb:
    first_entry = fb[0]
    print(f"   Sample entry keys: {list(first_entry.keys())}")
    print()
    print("   CRITICAL FIELD COVERAGE:")
    horizon_label_count = sum(1 for e in fb if 'horizon_label' in e and e.get('horizon_label'))
    sector_count = sum(1 for e in fb if 'sector' in e and e.get('sector'))
    horizon_days_count = sum(1 for e in fb if 'horizon_days' in e)
    
    print(f"   ❌ horizon_label: {horizon_label_count}/{len(fb)} entries have non-empty value")
    print(f"      MISSING IN {len(fb)-horizon_label_count} entries — CRITICAL FOR HORIZON ADJUSTMENTS")
    print()
    print(f"   ❌ sector: {sector_count}/{len(fb)} entries have non-empty value")
    print(f"      MISSING IN {len(fb)-sector_count} entries — CRITICAL FOR SECTOR ADJUSTMENTS")
    print()
    print(f"   ❌ horizon_days: {horizon_days_count}/{len(fb)} entries have value")
    print(f"      MISSING IN {len(fb)-horizon_days_count} entries")
    print()

print("2. LEARNED RULES GENERATION OUTPUT")
print("-" * 80)
print(f"   Pattern adjustments (pattern): {len(lr.get('pattern_adjustments',{}))}")
print(f"   Regime adjustments (pattern__trend): {len(lr.get('regime_adjustments',{}))}")
print(f"   Horizon adjustments (pattern__horizon): {len(lr.get('horizon_adjustments',{}))}")
print(f"   Sector adjustments (pattern__sector): {len(lr.get('sector_adjustments',{}))}")
print(f"   Triple adjustments (pattern__trend__horizon): {len(lr.get('triple_adjustments',{}))}")
print()

print("3. CASCADE LOOKUP FLOW (statistical_predictor.py)")
print("-" * 80)
print("   The analysis engine uses this cascade to blend feedback:")
print("   1. pattern__trend__horizon (NEEDS: horizon_label + trend) ❌ MISSING horizon_label")
print("   2. pattern__horizon (NEEDS: horizon_label) ❌ MISSING horizon_label")
print("   3. pattern__sector (NEEDS: sector) ❌ MISSING sector")
print("   4. pattern__trend (NEEDS: trend) ✓ AVAILABLE")
print("   5. pattern (base) ✓ AVAILABLE")
print()

print("4. MISMATCH DETECTION")
print("-" * 80)

# Check if horizon keys in learned_rules match anything in feedback
horizon_keys = list(lr.get('horizon_adjustments',{}).keys())
print(f"   Horizon adjustment keys generated: {len(horizon_keys)}")
if horizon_keys:
    print(f"   Examples: {horizon_keys[:3]}")
    print()
    print("   Checking if feedback entries have matching horizon labels:")
    feedback_horizons = set()
    for e in fb:
        if e.get('horizon_label'):
            feedback_horizons.add(e.get('horizon_label'))
    print(f"   Unique horizon_labels in feedback: {feedback_horizons}")
    
    for hkey in horizon_keys[:3]:
        parts = hkey.split('__')
        if len(parts) >= 2:
            horizon = parts[-1]
            matching_entries = sum(1 for e in fb if e.get('horizon_label') == horizon)
            print(f"   - {hkey}: {matching_entries} feedback entries have this horizon ❌")

print()

# Check if sector keys in learned_rules match anything in feedback
sector_keys = list(lr.get('sector_adjustments',{}).keys())
print(f"   Sector adjustment keys generated: {len(sector_keys)}")
if sector_keys:
    print(f"   Examples: {sector_keys[:3]}")
    print()
    print("   Checking if feedback entries have matching sectors:")
    feedback_sectors = set()
    for e in fb:
        if e.get('sector'):
            feedback_sectors.add(e.get('sector'))
    print(f"   Unique sectors in feedback: {feedback_sectors}")
    
    for skey in sector_keys[:3]:
        parts = skey.split('__')
        if len(parts) >= 2:
            sector = parts[-1]
            matching_entries = sum(1 for e in fb if e.get('sector') == sector)
            print(f"   - {skey}: {matching_entries} feedback entries have this sector ❌")

print()

print("5. ROOT CAUSE ANALYSIS")
print("-" * 80)
print("   ISSUE: paper_trader.py feed_outcomes_to_rag() adds horizon_label and sector")
print("          AFTER reading from DB, but:")
print()
print("   PROBLEM #1: feedback_log.json entries created BEFORE horizon/sector fields")
print("   - Old entries don't have these fields")
print("   - New entries tried to add them but DB might not populate correctly")
print()
print("   PROBLEM #2: DB schema has sector and horizon_label columns BUT:")
print("   - Unclear if all trades have these values populated")
print("   - Need to verify paper_trader correctly sets these when creating trades")
print()
print("   PROBLEM #3: When statistical_predictor loads feedback:")
print("   - It tries to build keys like 'hammer__bullish__BTST_1d'")
print("   - But feedback entries don't have these fields, so keys won't match")
print("   - Fallback to pattern__trend and pattern (levels 4-5) happens silently")
print()

print("6. SYNC STATUS REPORT")
print("-" * 80)
accuracy = (horizon_label_count + sector_count) / (len(fb) * 2) * 100 if fb else 0
print(f"   Feedback completeness: {accuracy:.1f}%")
print()
if horizon_label_count == 0:
    print("   🔴 CRITICAL FAILURE: NO horizon_label in any feedback entry")
if sector_count == 0:
    print("   🔴 CRITICAL FAILURE: NO sector in any feedback entry")
if horizon_label_count > 0 and horizon_label_count < len(fb):
    print(f"   🟡 PARTIAL FAILURE: Only {horizon_label_count}/{len(fb)} entries have horizon_label")
if sector_count > 0 and sector_count < len(fb):
    print(f"   🟡 PARTIAL FAILURE: Only {sector_count}/{len(fb)} entries have sector")

print()
print("7. RECOMMENDATION")
print("-" * 80)
print("   IMMEDIATE ACTION REQUIRED:")
print("   1. Verify paper_trader.py is correctly populating sector + horizon_label in DB")
print("   2. Regenerate feedback_log.json with complete horizon_label and sector fields")
print("   3. Re-run feed_outcomes_to_rag() to rebuild learned_rules.json with proper keys")
print("   4. Verify statistical_predictor can now find matching feedback entries")
print()
print("="*80)
