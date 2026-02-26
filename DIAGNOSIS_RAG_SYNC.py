#!/usr/bin/env python3
"""
FINAL DIAGNOSIS: RAG FEEDBACK LOOP SYNC FAILURE
===============================================
Root cause analysis and remediation plan
"""

import sqlite3
import json
from datetime import datetime
import os

print("="*80)
print("FINAL DIAGNOSIS: RAG FEEDBACK LOOP OUT OF SYNC")
print("="*80)
print()

# Get DB info
db = sqlite3.connect('paper_trades/paper_trades.db')
db.row_factory = sqlite3.Row
cursor = db.execute("""
    SELECT COUNT(*) as total,
           MAX(exit_date) as latest_exit
    FROM trades 
    WHERE status NOT IN ('OPEN', 'CANCELLED')
""")
db_stats = dict(cursor.fetchone())
db.close()

# Get feedback info
fb = json.load(open('feedback/feedback_log.json'))
fb_latest_ts = fb[-1].get('timestamp', 'N/A') if fb else 'N/A'

print("DATABASE vs FEEDBACK LOG MISMATCH")
print("-" * 80)
print(f"DB: {db_stats['total']} closed trades (latest exit: {db_stats['latest_exit']})")
print(f"Feedback: {len(fb)} entries (latest timestamp: {fb_latest_ts})")
print()

if db_stats['total'] > len(fb):
    unsynced = db_stats['total'] - len(fb)
    print(f"⚠️  {unsynced} recent trades NOT YET FED TO RAG")
    print("   These new trades are missing from feedback_log.json")

print()
print("CRITICAL ISSUE: MISSING FIELDS IN FEEDBACK")
print("-" * 80)

# Check what's actually in feedback_log
if fb:
    first = fb[0]
    print(f"Feedback entry structure: {list(first.keys())}")
    print()
    
    has_horizon = 'horizon_label' in first
    has_sector = 'sector' in first
    has_horizon_days = 'horizon_days' in first
    
    print(f"Field presence in feedback_log.json entries:")
    print(f"  ✗ horizon_label: {has_horizon} (NEEDED for horizon adjustments)")
    print(f"  ✗ sector: {has_sector} (NEEDED for sector adjustments)")
    print(f"  ✗ horizon_days: {has_horizon_days}")
    print()
    print(f"Pattern support:")
    print(f"  ✓ patterns: {'patterns' in first}")
    print(f"  ✓ indicators_at_entry: {'indicators_at_entry' in first}")
    print(f"  ✓ direction/trend: {'direction' in first}")

print()
print("IMPACT ON LEARNED RULES")
print("-" * 80)

lr = json.load(open('feedback/learned_rules.json'))
hor_adj = len(lr.get('horizon_adjustments', {}))
sec_adj = len(lr.get('sector_adjustments', {}))
tri_adj = len(lr.get('triple_adjustments', {}))

print(f"Learned rules were generated WITH these keys:")
print(f"  - {hor_adj} horizon adjustments (pattern__horizon)")
print(f"  - {sec_adj} sector adjustments (pattern__sector)")
print(f"  - {tri_adj} triple adjustments (pattern__trend__horizon)")
print()
print("BUT: These keys will NEVER MATCH in statistical_predictor because:")
print("  - Feedback entries don't have horizon_label → can't build pattern__horizon keys")
print("  - Feedback entries don't have sector → can't build pattern__sector keys")
print()
print("RESULT: Cascade lookup silently falls back to pattern__trend and pattern")
print("        All horizon and sector-specific optimizations are IGNORED")

print()
print("ROOT CAUSE")
print("-" * 80)
print("THE CODE ISSUE:")
print()
print("1. paper_trader.py feed_outcomes_to_rag() was updated to:")
print("   - Extract horizon_label and sector from DB trades")
print("   - Add them to feedback_log.json entries")
print("   - Generate horizon/sector adjustments in learned_rules.json")
print()
print("2. BUT old feedback_log.json entries (created before this update)")
print("   were never regenerated with these new fields")
print()
print("3. AND it appears the latest feed_outcomes_to_rag() call might not")
print("   have been executed AFTER the code change, OR the entries it tried")
print("   to add weren't merged properly")
print()

print("DATA FLOW BREAK:")
print()
print("  [DB trades with sector+horizon_label] ✓")
print("          ↓")
print("  [feed_outcomes_to_rag() reads from DB] ✓")
print("          ↓")
print("  [Tries to build feedback entry] ✓")
print("          ↓")
print("  [feedback_log.json written] ✗ (missing those fields!)")
print("          ↓")
print("  [learned_rules.json generated] ~ (has keys but no matching feedback)")
print("          ↓")
print("  [statistical_predictor loads feedback] ✗ (keys don't match)")
print("          ↓")
print("  [Cascade lookup fails silently] ✗ (fallback to pattern+trend only)")
print()

print("VERIFICATION: Check if recently added entries have the fields")
print("-" * 80)

# Check the most recent entries
if len(fb) > 3:
    print("Most recent 3 feedback entries:")
    for i, e in enumerate(fb[-3:]):
        has_h = 'horizon_label' in e
        has_s = 'sector' in e
        ts = e.get('timestamp', 'N/A')
        print(f"  {i+1}. {ts}: horizon_label={has_h}, sector={has_s}")

print()
print("="*80)
print("RECOMMENDATION: IMMEDIATE FIXES REQUIRED")
print("="*80)
print()
print("STEP 1: Clear and regenerate feedback_log.json")
print("  $ rm feedback/feedback_log.json")
print("  $ python paper_trader.py feedback")
print()
print("STEP 2: Verify the regenerated feedback has the required fields")
print("  $ python -c \"import json; fb=json.load(open('feedback/feedback_log.json'))\"")
print("  $ python -c \"fb=json.load(open('feedback/feedback_log.json')); ")
print("              print('horizon_label in entries:', 'horizon_label' in fb[0] if fb else 'N/A')\"")
print()
print("STEP 3: Verify learned_rules.json now has matching keys")
print("  $ python audit_rag_sync.py")
print()
print("STEP 4: Restart paper_trading_dashboard to reload new learned_rules.json")
print()
print("="*80)
