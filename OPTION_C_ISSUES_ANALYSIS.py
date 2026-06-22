#!/usr/bin/env python3
"""
ISSUES ANALYSIS: Option C Implementation
Before we code, let's identify all potential problems
"""

print("="*100)
print("OPTION C: INSTITUTIONAL-GRADE FEEDBACK ARCHITECTURE - ISSUES ANALYSIS")
print("="*100)

issues = """

CRITICAL ISSUES TO ADDRESS BEFORE IMPLEMENTATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ISSUE #1: SCHEMA MISMATCH (High Severity)
─────────────────────────────────────────

Problem:
  • trades table has: patterns, sector, indicators_json, entry_regime
  • shadow_trades table is MISSING: sector, indicators_json, entry_regime
  
  When joining shadow trade data:
    feedback_log entry = {
      "patterns": "bullish_harami",
      "sector": NULL or undefined  ← PROBLEM
      "indicators_at_entry": {...}  ← PROBLEM (not in shadow table)
    }

Impact:
  ✗ Sector-specific feedback can't be calculated for shadow trades
  ✗ Regime-aware decay can't work (entry_regime missing)
  ✗ Results in incomplete aggregation

Solution:
  Option 1: Backfill shadow_trades with sector + indicators_json
    - Complex: need to lookup sector from instrument
    - Need to reconstruct indicators from what?
    - Time-consuming
  
  Option 2: Query trades + shadow_trades separately, handle schema diff
    - Shadow trades: mark source = "shadow"
    - Real trades: mark source = "real"
    - Aggregate separately, then blend
    - Clean, but more code paths
    
  RECOMMENDATION: Go with Option 2 (separate aggregation)


ISSUE #2: BACKWARD COMPATIBILITY (High Severity)
───────────────────────────────────────────────

Problem:
  Current learned_rules.json structure:
  {
    "pattern_adjustments": {
      "bullish_harami": {
        "actual_win_rate": 31.0,
        "decay_weighted_win_rate": 31.0,  ← Single WR field
        "total_trades": 71
      }
    }
  }

  Option C wants to change to:
  {
    "pattern_adjustments": {
      "bullish_harami": {
        "feedback_sources": {
          "real_trades": {"wr": 31%, "n": 5},
          "shadow_trades": {"wr": 31%, "n": 71},
          "rag_raw": {"wr": 68%, "n": 147000}
        },
        "blended_wr": 56%,
        "confidence_attribution": {...}
      }
    }
  }

Impact on existing code:
  ✗ _apply_feedback() tries to read decay_weighted_win_rate → MISSING
  ✗ All cascade lookups fail gracefully but return None
  ✗ No blending happens (raw RAG prediction used)
  ✗ System silently breaks without error

Locations that will break:
  • statistical_predictor.py line 446: adj.get("decay_weighted_win_rate")
  • statistical_predictor.py line 445: decay_wr = adj.get("decay_weighted_win_rate")
  • paper_trader.py line ~2580: pattern adjustment fields in learnings

Solution:
  MUST maintain BACKWARD COMPATIBILITY layer:
  {
    "pattern_adjustments": {
      "bullish_harami": {
        # Old format (for existing code)
        "actual_win_rate": 56.0,
        "decay_weighted_win_rate": 56.0,
        "total_trades": 76,
        
        # New format (Option C enhancements)
        "feedback_sources": {...},
        "confidence_attribution": {...}
      }
    }
  }
  
  Then in _apply_feedback():
    # Try new format first
    if "feedback_sources" in adj:
      wr = adj["blended_wr"]
    else:
      # Fallback to old format
      wr = adj.get("decay_weighted_win_rate", 50)


ISSUE #3: AGGREGATION LOGIC COMPLEXITY (Medium-High Severity)
──────────────────────────────────────────────────────────────

Problem:
  Current logic (simple):
    for each trade in feedback:
      pattern_stats[pattern].append(outcome)
      patterns_stats[pattern].win_rate = wins / total

  Option C logic (complex):
    for each trade in feedback:
      if trade.source == "real":
        real_stats[pattern].append(outcome)
      elif trade.source == "shadow":
        shadow_stats[pattern].append(outcome)
    
    # Then blend separately:
    real_wr = real_stats["bullish_harami"].win_rate
    shadow_wr = shadow_stats["bullish_harami"].win_rate
    blended = blend(real_wr, shadow_wr, weights=[1.0, 0.6])

Questions:
  1. What if real_wr = 70% (5 trades), shadow_wr = 31% (71 trades)?
     Blend = (70 × 1.0 + 31 × 0.6) / 1.6 = 54.375%
     Is THIS the right order? Should we weighted-average by sample size too?
  
  2. Do we use decay_weighted_win_rate or actual_win_rate?
     Real trades: older data, should use decay
     Shadow trades: mostly recent, less decay?
  
  3. Horizon/regime/sector stats: blend them per-tier?
     pattern__horizon__shadow vs pattern__horizon__real?
     That's 3 aggregations per dimension = 9x more complexity

  4. Triple-key stats: pattern__trend__horizon
     Now: pattern__trend__horizon__real + pattern__trend__horizon__shadow
     Result: More fragmented, may not meet min sample thresholds

Solution:
  ✓ Keep simple: Aggregate all (real + shadow) in single bucket
  ✓ Track SOURCE label but don't separate aggregations
  ✓ At end, STORE attribution (% from real, % from shadow) separately
  ✓ Example:
    {
      "pattern": "bullish_harami",
      "all_trades_wr": 35%,  # Blended in single aggregation
      "real_trades_breakdown": {"n": 5, "wr": 70%},
      "shadow_trades_breakdown": {"n": 71, "wr": 31%},
      "attribution": {
        "real": 0.25,
        "shadow": 0.60,
        "rag_historical": 0.15
      }
    }


ISSUE #4: CASCADE LOOKUP BREAKAGE (Medium Severity)
───────────────────────────────────────────────────

Problem:
  Current cascade (specific to general):
    1. pattern__trend__horizon  (triple) 
    2. pattern__horizon         (horizon)
    3. pattern__sector          (sector)
    4. pattern__trend           (regime)
    5. pattern                  (base)

  Option C wants to add feedback_sources to EACH level.
  So now each level has: {real_wr, shadow_wr, blended_wr, attribution}

  Code path:
    if triple_adj and triple_adj.get("total_trades") >= 3:
      paper_wr = triple_adj.get("decay_weighted_win_rate")  ← Old field
      # But now structure is:
      triple_adj = {
        "feedback_sources": {
          "real": {...},
          "shadow": {...}
        },
        "blended_wr": 54.3
      }
  
  Fix needed:
    # New version:
    if triple_adj and triple_adj.get("total_trades") >= 3:
      if "feedback_sources" in triple_adj:
        paper_wr = triple_adj.get("blended_wr")
      else:
        paper_wr = triple_adj.get("decay_weighted_win_rate")  # Backward compat

Solution:
  Create wrapper function:
    def _get_wr_from_feedback(adj_dict):
      \"\"\"Extract WR from new or old format\"\"\"
      if "feedback_sources" in adj_dict:
        return adj_dict["blended_wr"]
      else:
        return adj_dict.get("decay_weighted_win_rate", 50)
  
  Use everywhere in _apply_feedback()


ISSUE #5: ATTRIBUTION CALCULATION ERRORS (Medium Severity)
──────────────────────────────────────────────────────────

Problem:
  Attribution needs to be mathematically consistent:
    confidence_attribution[real] + [shadow] + [rag] = 1.0
  
  But how do you calculate it?
  
  Option A: By sample size
    real_weight = n_real / (n_real + n_shadow + n_rag_synthetic)
    shadow_weight = n_shadow / (...)
    rag_weight = n_rag / (...)
    Problem: n_rag_synthetic is subjective (how many "synthetic" RAG samples?)
  
  Option B: By prediction accuracy (decay-weighted)
    real uses confidence 1.0
    shadow uses confidence 0.6
    rag uses confidence 0.5 (default)
    total_conf = 1.0 + 0.6 + 0.5 = 2.1
    real_attr = 1.0 / 2.1 = 0.476
    shadow_attr = 0.6 / 2.1 = 0.286
    rag_attr = 0.5 / 2.1 = 0.238
    Problem: Weights feel arbitrary
  
  Option C: By contribution to final WR
    Contribution = (source_wr - blend_wr) × weight
    If real_wr=70%, shadow_wr=31%, blended=54%:
      real contribution = (70-54) × 1.0 = 16pp
      shadow contribution = (31-54) × 0.6 = -13.8pp
      net = 2.2pp (doesn't add up)
    Problem: Can't get components to sum to 100%

Solution:
  SIMPLEST: Just track the inputs, not strict attribution
  {
    "win_rate": 54.3,
    "sources": {
      "real_trades": {"wr": 70%, "n": 5, "weight": 1.0},
      "shadow_trades": {"wr": 31%, "n": 71, "weight": 0.6},
      "rag_raw": {"wr": 68%, "n": 147000, "weight": default}
    },
    "blending": "real_wr × 1.0 + shadow_wr × 0.6 → 54.3%"
  }
  Let dashboard show the algorithm, not fake attribution percentages


ISSUE #6: DASHBOARD COMPATIBILITY (Low-Medium Severity)
───────────────────────────────────────────────────────

Problem:
  paper_trading_dashboard.py reads learned_rules.json to display:
    - Pattern adjustments
    - Win rates
    - Confidence levels
  
  If learned_rules structure changes, dashboard fields break:
    pattern_adj["actual_win_rate"]  ← Still needed
    pattern_adj["decay_weighted_win_rate"]  ← Still needed

  New fields won't display unless dashboard code updates:
    pattern_adj["feedback_sources"]["shadow_trades"]["wr"]  ← Not queried

Solution:
  1. Keep old fields for backward compat (Issue #2)
  2. ADD new display widget in dashboard for feedback_sources
  3. Create separate endpoint: /api/pattern/{name}/feedback-breakdown
  4. Dashboard renders both old + new format


ISSUE #7: TESTING COMPLEXITY (Low-Medium Severity)
──────────────────────────────────────────────────

Problem:
  Option C introduces 3 data sources (real, shadow, rag) + weights
  Test matrix explodes:
    - Real WR high, shadow WR low
    - Real WR low, shadow WR high
    - Real WR absent (< 2 trades)
    - Shadow WR absent (< 2 trades)
    - At each cascade level (5 levels)
    - For each time window (decay weights)
  
  That's 4 × 4 × 5 × 3 = 240 test cases

Solution:
  Minimal tests:
    ✓ Real high, shadow low → blended between (54%)
    ✓ Real absent, shadow low → use shadow (31%)
    ✓ Both absent → use RAG (68%)
    ✓ Backward compat: old learned_rules works (no errors)


ISSUE #8: MIGRATION PATH (Low-Medium Severity)
───────────────────────────────────────────────

Problem:
  You have historical learned_rules.json files from:
    - Feb 28
    - Mar 7
    - Mar 14
    - Mar 20 (current)
  
  If you change the schema, old files won't load correctly into new viewer.

Solution:
  1. Keep backward compat layer (Issue #2)
  2. Add migration function: migrate_old_schema(old_learned_rules) → new_schema
  3. On _apply_feedback() load, detect version and auto-migrate
  4. Optional: Batch-migrate all old files at startup


ISSUE #9: REAL vs SHADOW DEFINITION (Conceptual)
────────────────────────────────────────────────

Problem:
  In Option C, we distinguish:
    "real_trades" = trades in paper_trades table (entered the system)
    "shadow_trades" = trades filtered out (never entered, but tracked)
  
  But bullish_harami never entered as real trade!
    • 256 shadow entries
    • 0 real entries
  
  So when calculating "real_wr": 
    - If no real trades, do we use shadow approximation?
    - Or do we force a distinction: real_wr = "N/A"?
  
  For attribution, if real_trades=0:
    "sources": {
      "real_trades": {"wr": "N/A", "n": 0},
      "shadow_trades": {"wr": 31%, "n": 71},
      "rag_raw": {"wr": 68%, "n": 147000}
    }
  
  What % to give to shadow then? 60/168 ≈ 36%? Or use shadow_weight directly?

Solution:
  Be explicit:
    {
      "sources": {
        "real_trades": {"n": 0, "status": "no_real_trades_yet"},
        "shadow_trades": {"wr": 31%, "n": 71, "weight": 0.6},
        "rag_raw": {"wr": 68%, "weight": variable},
      },
      "note": "Blended from shadow only (no real trades; using 31% shadow + RAG)",
      "blended_wr": 54.3%
    }


SUMMARY: HIGH-PRIORITY FIXES NEEDED BEFORE CODING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Priority | Issue | Solution | Impact
---------|-------|----------|--------
🔴 HIGH  | Schema mismatch | Query trades + shadows separately | Requires separate aggregation logic
🔴 HIGH  | Backward compat | Keep old fields + new fields | Doubles structure size, adds version checking
🟡 MED   | Aggregation logic | Simple blending after aggregation | Cleaner than separate per-source buckets
🟡 MED   | Cascade lookup | Wrapper function _get_wr_from_feedback() | Minor refactor
🟡 MED   | Attribution calc | Track inputs, not fake percentages | Honest about uncertainty
🟡 MED   | Dashboard compat | Keep old fields + new endpoint | Some display code changes
🟢 LOW   | Testing | Write 12-15 focused tests | Worth doing
🟢 LOW   | Migration | Auto-detect + migrate old schema | Background process
🟡 MED   | Conceptual | Define real vs shadow classification | Documentation + validation

"""

print(issues)

print("\n" + "="*100)
print("RECOMMENDATION: IMPLEMENTATION APPROACH")
print("="*100)

approach = """

PROCEED WITH OPTION C BUT:
━━━━━━━━━━━━━━━━━━━━━━━

1. START WITH FOUNDATION (Option B equivalent):
   • Include shadow_trades in feed_outcomes_to_rag()
   • Use 0.6x weight for shadow trades
   • Verify blending works before adding complexity

2. THEN ADD ATTRIBUTION LAYER:
   • Keep backward compat structure
   • Add "feedback_sources" section (new)
   • Add "blending" explanation (new)
   • Dashboard queries both old + new fields

3. AVOID FRAGMENTATION:
   • DON'T create separate aggregations per-tier
   • Keep single bucket, track source labels
   • Blend at aggregation time, not at lookup time

4. TESTING FIRST:
   • Before touching code, write tests for:
     ✓ real_trades only
     ✓ shadow_trades only
     ✓ blending formula
     ✓ backward compat loading
     ✓ cascade lookup with new structure
   
5. PHASED ROLLOUT:
   • Phase 1: Shadow + weight blending (foundation)
   • Phase 2: Attribution tracking (reporting)
   • Phase 3: Dashboard integration (visualization)


REVISED TIMELINE:
   Phase 1: 2-3 hours (tomorrow)
   Phase 2: 1-2 hours (next day)
   Phase 3: 1-2 hours (before Friday)
   Total: 4-7 hours
"""

print(approach)
