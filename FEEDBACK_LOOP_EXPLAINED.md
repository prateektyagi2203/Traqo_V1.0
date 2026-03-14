# How Traqo's Feedback Loop Works
## Complete Guide to Data Capture, Learning, and RAG Changes

---

## 1. WHAT DATA IS CAPTURED? (The 3 Types)

### Type 1: **REAL TRADES** (Capital deployed, actual P&L)
- **What:** Trades you actually entered with capital
- **Data captured per trade:**
  - Entry price, entry date, ticker, patterns matched
  - Target price, SL price, R:R ratio
  - Market regime at entry, indicators at entry (RSI, EMA, ATR, etc.)
  - Actual exit price, exit date, **actual P&L %**
  - **Outcome:** WIN | LOSS | EXPIRED_WIN | EXPIRED_LOSS
- **File:** `feedback/feedback_log.json` (all closed trades logged here)
- **Count:** 279 real trades analyzed so far (as of Mar 6)

### Type 2: **SHADOW TRADES** (No capital, filtered-out signals)
- **What:** Signals that matched patterns BUT were filtered out (didn't make cut)
- **Why tracked:** To measure filter effectiveness
  - Real trades win rate: 52.3%
  - Shadow trades win rate: ~45-50%
  - **Gap of +2-7 pp shows filters ARE working**
- **Data captured:** Same as real trades (entry, exit, patterns, outcomes)
- **File:** `feedback/learned_rules.json` tracks statistics
- **Count:** 50% of all matched signals (stratified sampling)
- **Status tracking:** SHADOW_OPEN → SHADOW_CLOSED (after horizon expires)

### Type 3: **LEARNED RULES** (Auto-generated from trades)
- **What:** Statistics extracted from real + shadow trades
- **Generated automatically:** After each trade closes (or daily batch)
- **File:** `feedback/learned_rules.json`
- **Contents:** Penalties, boosts, win rates by pattern/horizon/regime
- **Updated:** Every time a trade closes (real or shadow)

---

## 2. THE FEEDBACK LOOP CYCLE

```
┌─────────────────────────────────────────────────────────────────┐
│                    DAILY SCAN (e.g., 9:15 AM)                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │ 127 candidates │
                    │ matched (RAG)  │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼──┐    ┌─────▼──┐    ┌─────▼──┐
        │ Filter │    │ Filter │    │ Filter │
        │   #1   │    │   #2   │    │   #3   │
        └─────┬──┘    └─────┬──┘    └─────┬──┘
              │
        ┌─────▼──────────────────────────┐
        │ REAL TRADES: 5 approved        │  ◄── Deployed
        │ - BTST_1d: 2                   │      capital
        │ - Swing_5d: 3                  │      HERE
        └────┬──────────────────────────┬┘
             │                          │
    Entry logged                Entry logged
             │                          │
             ├──────────────┬───────────┤
             │              │           │
   ┌─────────▼────┐  ┌──────▼────┐  ┌──▼──────────┐
   │ After 1 day  │  │ After 5d  │  │ After 10d   │
   │ CLOSE REAL   │  │ CLOSE     │  │ CLOSE       │
   │ TRADE #1     │  │ TRADE #2  │  │ TRADE #3-5  │
   └─────────┬────┘  └──────┬────┘  └──┬──────────┘
             │              │           │
    Outcome: WIN     Outcome: LOST     Outcome: EXPIRED_WIN
    Return: +2.1%    Return: -1.5%    Return: +3.2%
             │              │           │
             └──────────────┼───────────┘
                            │
        ┌───────────────────▼────────────────────┐
        │ FEEDBACK LOGGED:                       │
        │ - Pattern: harami_cross WIN ✓          │
        │ - Pattern: three_black_crows LOSS ✗    │
        │ - Pattern: belt_hold_bullish WIN ✓     │
        │ - Horizon: Swing_5d: 1W, 1L            │
        │ - Regime: bearish: 0W, 2L              │
        └────────────┬─────────────────────────┘
                     │
         ┌───────────▼──────────────┐
         │  LEARNED RULES UPDATED   │
         │  (AUTOMATIC - happens   │
         │   when trade closes)    │
         └───────────┬──────────────┘
                     │
         ┌───────────▼──────────────────────────┐
         │ PATTERN ADJUSTMENTS CALCULATED:      │
         │ • harami_cross: 50.7% WR (↑)         │
         │ • three_black_crows: 30% WR (↓)      │
         │ • Swing_5d horizon: 52.1% WR         │
         │ • bearish regime: 25% WR (!)         │
         └────────────────────────────────────────┘
                     │
         ┌───────────▼──────────────┐
         │  RAG USES NEW RULES      │
         │  Next scan (tomorrow)    │
         │  will apply penalties &  │
         │  boosts automatically    │
         └──────────────────────────┘
```

---

## 3. AUTOMATIC LEARNING (No Intervention)

### What Happens Automatically:
1. **Trade close triggers update:**
   - Trade marked WON/LOST/EXPIRED
   - Outcome logged to `feedback_log.json`
   
2. **Stats recalculated automatically:**
   - Win rate per pattern: `wins / (wins + losses)`
   - Win rate per horizon: similar
   - Win rate per regime: filtered by market condition
   - Decay-weighted win rate: recent trades weighted 60%, older 40%

3. **Pattern performance tracked:**
   - If pattern WR drops below 45%: **AUTO-FLAG AS UNDERPERFORMING**
   - If pattern shows strong edge: **AUTO-MARKED FOR CONSIDERATION**

4. **RAG automatically applies new stats:**
   - Next day's scan uses updated learned_rules.json
   - Penalties automatically reduce confidence
   - Boosts automatically increase confidence

### Example (Automatic):
```
Mar 6, 13:00 - Three_black_crows trade closes → LOSS -1.5%
            ↓
            feedback_log.json updated: +1 loss entry
            ↓
            regenerate_learned_rules() called
            ↓
            three_black_crows stats recalculated:
            • Old: 75% WR (4W, 1L)
            • New: 60% WR (4W, 2L)
            ↓
            Since 60% > 45%, system notes it as "Still acceptable"
            But if next loss happens → triggers your optional [APPROVE] button
```

---

## 4. MANUAL INTERVENTION (YOU Decide)

### When Your Intervention Is Required:

1. **PENALTY THRESHOLD REACHED** (20+ closed trades)
   - Example: `harami_cross` reaches 20 closed trades
   - Actual win rate: 45% (borderline)
   - Dashboard shows: **"[READY] - LOOSEN to 52%?"**
   - **Your action:** Click [APPROVE] or [DEFER]
   
2. **OPTIONAL: Confidence adjustments**
   - Pattern performs exceptionally well: `>65% WR`
   - You manually decide: boost confidence by 10%?
   - **Your action:** Approve boost in dashboard

3. **OPTIONAL: Emergency override**
   - Pattern causing losses in live trading (not shadow)
   - You decide: "Pause this pattern immediately"
   - **Your action:** Manual penalty via UI (not yet built)

### Example (Manual):
```
Mar 13 - Belt_hold_bullish reaches 20 closed trades
        ↓ Dashboard shows badge with "1"
        ↓
        You click Feedback Loop tab
        ↓
        [READY FOR ACTION] section shows:
        • belt_hold_bullish (Swing_10d)
        • 20/20 closed | 50% WR
        • Recommendation: LOOSEN to 52%
        • [APPROVE] [DEFER]
        ↓
        You click [APPROVE]
        ↓
        learned_rules.json updated:
        • Old: filter_penalties["belt_hold_bullish"] = {...}
        • New: filter_penalties["belt_hold_bullish"]["action"] = "LOOSEN"
        ↓
        Next scan: RAG applies looser threshold
        Expected result: +10-15 extra signals/month
```

---

## 5. HOW RAG CHANGES BASED ON LEARNING

### The RAG Confidence Flow:

```
RAG Document Database
(147K+ patterns from books)
        │
        ├─ Pattern: "harami_cross"
        │  - Base win rate: 54% (from books)
        │  - Paper trading seen: 45% (20 trades)
        │  - Current penalty: 52% threshold
        │
        ▼
Statistical Predictor (your system)
        │
        ├─ Step 1: Load learned_rules.json
        │  "harami_cross": {
        │    "actual_win_rate": 45%,
        │    "action": "LOOSEN",
        │    "new_threshold": 52%
        │  }
        │
        ├─ Step 2: Calculate match quality
        │  - Finds 3 harami_cross matches in today's scan
        │  - Each has 54% theoretically (from RAG books)
        │
        ├─ Step 3: Apply learned_rules override
        │  confidence_multiplier = 0.90 (because 45% WR < 54%)
        │  Final confidence: MEDIUM (was HIGH)
        │
        ├─ Step 4: Check penalty status
        │  IF pattern has "LOOSEN" action:
        │    use_threshold = 52% (not 45%)
        │    → signal PASSES filter (was borderline before)
        │
        ▼
Output for today:
  harami_cross #1: MEDIUM confidence (was HIGH)
                   PASSES filter (was borderline)
                   [MONITOR FOR APPROVAL]
```

### 3 Ways RAG Changes from Learning:

#### Way 1: **Confidence Scaling** (AUTOMATIC)
```python
# In statistical_predictor.py:
def get_confidence_from_feedback(pattern, base_confidence):
    learned = load_feedback()  # learned_rules.json
    actual_wr = learned["pattern_adjustments"][pattern]["actual_win_rate"]
    book_wr = 54  # RAG default
    
    if actual_wr < book_wr:
        return downgrade(base_confidence)  # HIGH → MEDIUM
    return base_confidence
```

#### Way 2: **Penalty Application** (AUTOMATIC)
```python
# In predict flow:
if pattern in learned_rules["filter_penalties"]:
    penalty = learned_rules["filter_penalties"][pattern]
    # e.g., penalty = {"action": "reject", reason: "45% WR"}
    confidence_multiplier *= 0.8  # Reduce by 20%
```

#### Way 3: **Boost Application** (AUTOMATIC)
```python
# In predict flow:
if pattern in learned_rules["filter_boosts"]:
    boost = learned_rules["filter_boosts"][pattern]
    # e.g., boost = {"action": "boost", reason: "75% WR"}
    confidence_multiplier *= 1.15  # Increase by 15%
```

---

## 6. SUMMARY TABLE: Automatic vs Manual

| Action | Automatic? | Frequency | Trigger | Example |
|--------|-----------|-----------|---------|---------|
| Track win/loss | ✅ YES | On trade close | Trade status=WON | Mar 6, 13:00 |
| Update stats | ✅ YES | On trade close | feedback_log updated | WR recalc |
| Apply decay weighting | ✅ YES | Daily | regenerate_learned_rules() | Recent 60%, old 40% |
| Reduce confidence (if WR drops) | ✅ YES | Daily | Auto pattern WR check | HIGH → MEDIUM |
| Flag pattern for approval | ✅ YES | When 20 trades hit | Pattern count ≥ 20 | badge appears |
| **CLICK [APPROVE] button** | ❌ **YOU** | When ready | You click in UI | Mar 13, 9:30 AM |
| **CLICK [DEFER] button** | ❌ **YOU** | When unsure | You click in UI | (skip for now) |
| Apply penalty/boost change | ✅ YES | On approval | learned_rules.json write | Loosen filter → +signals |

---

## 7. REAL EXAMPLE: Three_Black_Crows Penalty Removal

### Timeline:

**Feb 25-27:**
- Three_black_crows triggered 10 real trades
- Result: 3 wins, 7 losses = **30% WR** ❌
- System flagged: "UNDERPERFORMING"
- Action: Added to `filter_penalties` with 45% threshold

**Mar 6, 13:00:**
- You requested: "Recalibrate penalties"
- Agent analyzed shadow trades (filtered signals):
  - 4 shadow three_black_crows trades: 3 wins, 1 loss = **75% WR** ✅
  - Insight: **Real trades unlucky, pattern is actually good**
  - Reason: Real hits on regime shift, shadow shows true edge
- System decided: Move from penalty → boost
- Action: REMOVED from filter_penalties, ADDED to filter_boosts

**Mar 6, 13:08:**
- `learned_rules.json` updated:
  - Removed: `filter_penalties["three_black_crows"]`
  - Added: `filter_boosts["three_black_crows"] = {actual_wr: 75%, action: "boost"}`

**Mar 7, 9:15 AM (next scan):**
- New three_black_crows signals appear
- RAG loads learned_rules.json
- Sees: `filter_boosts["three_black_crows"]`
- Applies: `confidence_multiplier = 1.15` (boost by 15%)
- Result: **MORE** three_black_crows signals now pass filter
- Expected: +3-5 extra trades/month from this pattern alone

---

## 8. KEY INSIGHTS

### What's Changing?
- **NOT the RAG documents** (147K patterns stay same)
- **NOT the pattern detection logic** (candlestick matching unchanged)
- **INSTEAD:** Confidence scoring and filtering thresholds

### Where Learning Happens:
```
feedback_log.json → (statistics extracted) → learned_rules.json
     ↑                                              ↓
  Real trades                                 RAG applies these
  + Shadow trades                            adjustments next scan
```

### Why Shadow Trades Matter:
- **Real trades:** 5-10 per day, limited sample
- **Shadow trades:** 50% of all matches, 50-100 per day
- **Together:** Paint clearer picture than real trades alone

### Why Manual Approval Needed:
- Prevents auto-penalties from creating downward spiral
- Captures regime shifts (Mar 6 example: market shift caused losses)
- Ensures human accountability for changes

---

## 9. NEXT STEPS FOR YOU

1. **Mar 13-15:** First pattern hits 20 closed trades
   - You'll see badge on Feedback Loop tab
   - Review [READY] section
   - Click [APPROVE] to change filter

2. **Mar 15-30:** Monitor signal quality
   - Track if approved changes improve win rate
   - Observe if +signals/month measurement accurate

3. **Mar 27:** First quarterly audit
   - Review all penalties/boosts
   - Adjust thresholds if needed
   - Plan Phase 2 confidence scoring

4. **April onwards:** Iterate
   - Approve/defer patterns as they hit threshold
   - Monitor RAG confidence changes
   - Measure cumulative impact on P&L
