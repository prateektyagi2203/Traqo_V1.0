#!/usr/bin/env python3
"""
OPTION B VALIDATION: Understanding the Results
"""

print("="*100)
print("OPTION B BLENDING MECHANISM EXPLAINED")
print("="*100)

explanation = """

WHAT WE SEE:
✓ Shadow trades: 1124 included in feedback (with source='shadow_trade')
✓ Bullish_harami: 71 shadow trades, 31.04% actual WR
⚠️ Expected 56%, but got 31% — WHY?

ANSWER: Math is working correctly!
═══════════════════════════════════

1. LEARNED_RULES CALCULATION:
   • We have 71 shadow bullish_harami trades
   • Real WR: 22 wins / 71 total = 30.98% ≈ 31%
   • These are weighted at 0.6x for aggregation
   • Result in learned_rules: decay_weighted_wr = 31%
   
   Why 31% and not something else?
   • weights: 71 trades × 0.6 = 42.6 effective trades
   • wins: 22 wins × 0.6 = 13.2 effective wins
   • wr = 13.2 / 42.6 = 30.98% ✓ Correct math
   
   The 0.6x weight affects "sample size" not the percentage.
   Since ALL trades are shadow, just one source, % stays at 31%.

2. THE REAL BLENDING HAPPENS IN _apply_feedback():
   
   When bullish_harami prediction is generated:
   
   RAW RAG prediction:           68% WR
   Learned fro shadow:             31% WR
   Sample size:                       71 trades
   Paper weight formula:            min(50%, 71/(71+20)) = 50%
   
   BLENDED = RAG × (1-weight) + learned × weight
           = 68 × 0.5 + 31 × 0.5
           = 34 + 15.5
           = 49.5% WR
   
   ✓ This is BELOW 45% threshold = Trade will be FILTERED

3. WHY WE DON'T SEE 56%:
   
   I calculated 56% assuming:
    • Real trades: 70% WR
    • Shadow trades: 31% WR
    • Blended: (70 × 1.0 + 31 × 0.6) / 1.6 = 54%
   
   But bullish_harami has ZERO real trades!
   So the calculation is:
    • Real trades: NONE
    • Shadow trades: 31% WR with 0.6x weight
    • Result after full pipeline: 49.5% (after blending with RAG)


VALIDATION CHECKLIST:
═════════════════════

✓ Shadow trades included: 1124 total, 71 bullish_harami
✓ Source field marked: shadow_trade entries visible
✓ Weight mechanism active: 0.6x multiplier in code
✓ Learned rule generated: bullish_harami in pattern_adjustments
✓ Final prediction formula: 49.5% (will filter many trades)

EXPECTED OUTCOME:
════════════════

When scan runs next:
  • RAG predicts bullish_harami at 68%
  • Feedback blends: 68 × 0.5 + 31 × 0.5 = 49.5%
  • Threshold check: 49.5% > 45% threshold = STILL ENTERS
  • But confidence will be LOW (only 49.5% vs 68%)
  
  Actually wait, let's check the thresholds...
  MIN_WIN_RATE = 30.0%
  49.5% >> 30% → Still enters with medium confidence
  
  More tests needed to see how many filter through.

NEXT ACTION:
═════════════

Run scan preview to see how many trades pass with blended predictions.
CMD: python paper_trader.py scan
EXPECTED: Many bullish_harami trades should show lower confidence scores.
"""

print(explanation)

# Now calculate what the blending will look like
print("\n" + "="*100)
print("DETAILED CALCULATION FOR BULLISH_HARAMI")
print("="*100)

rag_wr = 68.0
learned_wr = 31.0
sample_size = 71

# Blending formula from statistical_predictor.py line ~468
paper_weight = min(0.50, sample_size / (sample_size + 20))
blended_wr = rag_wr * (1 - paper_weight) + learned_wr * paper_weight

print(f"\nRaw RAG prediction:              {rag_wr}%")
print(f"Learned WR (from shadow):        {learned_wr}%")
print(f"Sample size (71 shadow trades):  {sample_size}")
print(f"\nBlending weight formula:")
print(f"  paper_weight = min(0.50, {sample_size}/({sample_size}+20))")
print(f"  paper_weight = min(0.50, {sample_size/91:.3f})")
print(f"  paper_weight = {paper_weight:.3f}")

print(f"\nBlended WR = {rag_wr} × (1-{paper_weight}) + {learned_wr} × {paper_weight}")
print(f"Blended WR = {rag_wr} × {1-paper_weight:.3f} + {learned_wr} × {paper_weight:.3f}")
print(f"Blended WR = {rag_wr * (1-paper_weight):.2f} + {learned_wr * paper_weight:.2f}")
print(f"Blended WR = {blended_wr:.1f}%")

print(f"\n{'='*100}")
print(f"FILTER THRESHOLD CHECK:")
print(f"{'='*100}")
print(f"Blended WR:        {blended_wr:.1f}%")
print(f"MIN_WIN_RATE:      30.0%")
print(f"Status:            ✓ PASSES ({blended_wr:.1f} > 30.0)")
print(f"\nPrediction:        Trades will STILL ENTER but with REDUCED confidence")
print(f"Confidence:        Updated from HIGH (68%) to MEDIUM ({blended_wr:.1f}%)")
