# Pattern Monitoring Strategy
## Tracking 8 Borderline Patterns from OOS Backtest

**Status:** Setup Guide  
**Date:** March 2026  
**Responsibility:** User (automated checks can run via scheduled task)  

---

## Overview: Why These 8 Patterns?

From the OOS backtest (2016-2023 train, 2024-2025 test), **4 patterns were promoted** but 8 others showed promise:
- **PF between 1.0-1.3** (not strong enough for immediate whitelist)
- **Win% >= 48%** (statistically viable, not noise)
- **Clear potential** (close to threshold or regime-dependent)

### The 8 Monitor Patterns

| Rank | Pattern | Test PF | Test W% | Why Monitor | Action Needed |
|------|---------|---------|---------|------------|---------------|
| 1️⃣ | **belt_hold_bullish** | 1.29 | 52.7% | **Closest to 1.3 threshold** (1 pip away!) | If live PF > 1.3 over 20 trades → PROMOTE |
| 2️⃣ | **falling_three_methods** | 1.15 | 53.8% | Highest win rate (53.8%) | Good for high-probability setups |
| 3️⃣ | **three_inside_up** | 1.16 | 52.9% | Re-added (was excluded) | New opportunity in current market |
| 4️⃣ | **harami_cross** | 1.23 | 50.9% | Consistent (1.18 train → 1.23 test) | Stable pattern, likely candidate |
| 5️⃣ | **in_neck** | 1.17 | 49.1% | Below 50% win rate | Risky, needs 25+ trades to evaluate |
| 6️⃣ | **long_legged_doji** | 1.05 | 49.2% | Train degradation (1.12→1.05) | Watch for regime dependency |
| 7️⃣ | **spinning_top** | 1.04 | 49.2% | Significant train/test drop (1.19→1.04) | Regime-dependent, high risk |
| 8️⃣ | **high_wave** | 1.03 | 48.6% | Marginal PF + below 50% win rate | Riskiest — needs 30+ trades |

---

## Monitoring Strategy (3-Phase Approach)

### Phase 1: Enable Tracking (Week 1)

**Goal:** Start capturing live trades for these 8 patterns

**Actions:**
1. ✅ Create monitoring infrastructure (✓ Done: `monitor_patterns.py`)
2. ⚠️ Ensure patterns are enabled in `pattern_detector.py`
   - Check if all 8 patterns are being detected during scans
   - Verify signal quality (entry price, SL logic)
3. 📝 Initialize tracking database
   - Run: `python monitor_patterns.py`
   - Creates `pattern_monitor_performance.json`

**Success Criteria:**
- All 8 patterns show detection in daily scans
- Database tracking active
- First monitoring report generated

---

### Phase 2: Collect Live Data (Weeks 2-12)

**Goal:** Gather statistically significant sample (20-30 trades per pattern)

**Timeline:**
- **Week by week:** Run `python monitor_patterns.py` every Monday
- **Monthly:** Review progress and publish report
- **Sample collection:** 
  - High-PF patterns (belt_hold, harami_cross): 20 trades to promote
  - Marginal patterns (high_wave, spinning_top): 30+ trades to decide

**What to Watch:**

| Pattern | Current Test PF | Action if Live PF... | Action if Live PF... |
|---------|-----------------|----------------------|----------------------|
| belt_hold_bullish | 1.29 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| harami_cross | 1.23 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| three_inside_up | 1.16 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| falling_three_methods | 1.15 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| in_neck | 1.17 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| long_legged_doji | 1.05 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| spinning_top | 1.04 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |
| high_wave | 1.03 → **≥1.30** → PROMOTE | **<1.0** → DEMOTE |

**Weekly Report Template:**
```
PATTERN MONITOR REPORT — Week of [DATE]

Pattern              Live PF  Win%   Trades  Status           Next Check
belt_hold_bullish    1.25     51%    12/20   MONITOR          Need 8 more
harami_cross         0.98     47%    15/20   ⚠ RISK           May drop below 1.0
three_inside_up      1.31     53%    22/20   ✓ PROMOTE!        Ready for whitelist
...
```

---

### Phase 3: Make Promotion/Demotion Decisions (Week 12+)

**Promotion Rule:**
```
IF (Live PF >= 1.3) AND (Win% >= 50%) AND (Trades >= min_samples)
   → Add to WHITELISTED_PATTERNS in trading_config.py
   → Create GitHub issue documenting decision
   → Announce in monthly report
```

**Demotion Rule:**
```
IF (Live PF < 1.0) DURING ANY 10-trade window
   → Immediately flag as "At Risk"
   → After 20 total trades in this state
   → Remove from monitor (don't trade)
   → Document failure reason
```

**Monthly Review Trigger:**
- Any pattern reaching 20+ trades
- Any pattern dropping below 1.0 PF
- End of month (21st-end): Summary report

---

## How to Use `monitor_patterns.py`

### Quick Run (Weekly)
```bash
python monitor_patterns.py
```

**Output:**
```
PATTERN MONITOR CHECK — Live Performance Analysis
===================================================

Pattern Name              Live PF  Live W%  Trades/Min  Status   
belt_hold_bullish           0.95    48.0%      8/20     MONITOR 
three_inside_up             1.42    54.0%     22/20     PROMOTE ← ACTION NEEDED!
harami_cross                0.89    46.0%     12/20     RISK    ← Action needed!
...

SUMMARY
-------
[+] PROMOTE TO WHITELIST (1 patterns):
    three_inside_up          Live PF=1.42 Win%=54.0%

[-] DEMOTE FROM MONITOR (1 patterns):
    harami_cross             Live PF=0.89 (below 1.0)

[=] CONTINUE MONITORING (6 patterns):
    belt_hold_bullish        Live PF=0.95 (8/20 samples)
    ...
```

### What Each Status Means

| Status | Meaning | Action |
|--------|---------|--------|
| **PROMOTE** | PF ≥ 1.3, Win% ≥ 50%, Trades ≥ min | Add to WHITELISTED_PATTERNS immediately |
| **REJECT** | PF < 1.0 (failing live) | Stop trading, remove from monitor |
| **MONITOR** | 1.0 < PF < 1.3 (still evaluating) | Collect more data, check again next week |
| **RISK** | Win% < 48% (below threshold) | Flag for potential demotion |

---

## Integration with Your Existing System

### 1. Database Query (Automatic)
The script queries your `paper_trades/paper_trades.db`:
- Looks for trades with matching `pattern_name`
- Calculates PF, Win%, trade count
- Compares to OOS baseline

### 2. Pattern Detection (Manual Check)
Verify in `pattern_detector.py`:
```python
# Example: ensure hammer detection is active
if pattern == "hammer" and is_pattern_detected(...):
    signals.append(...)
```

### 3. RAG Feedback Loop Integration
When a pattern gets promoted:
1. RAG system learns the new pattern's scoring weights
2. Feedback loop adjusts meta-rules for the new pattern
3. Next month's statistical_predictor.py uses updated rules

### 4. Dashboard Integration
`paper_trading_dashboard.py` will automatically:
- Show new whitelisted patterns in scans
- Display monitor-status patterns separately (optional widget)
- Track performance metrics in trade logs

---

## Decision Tree: When to Promote/Demote

```
┌─ Monitor Pattern Check
│
├─ Has 20+ trades? NO  → Continue monitoring next week
│
├─ YES
│  ├─ PF >= 1.3 AND Win% >= 50%  → PROMOTE to whitelist ✓
│  │
│  ├─ PF < 1.0  → DEMOTE (stop trading immediately) ✗
│  │
│  └─ 1.0 <= PF < 1.3  → Continue monitoring
│     ├─ Win% >= 50%  → Collect more data
│     └─ Win% < 48%   → Flag for risk review
```

---

## Promotion Checklist

When `monitor_patterns.py` shows `[+] PROMOTE`:

### Step 1: Update Configuration
```python
# trading_config.py
WHITELISTED_PATTERNS = {
    ...,
    "three_inside_up",  # PROMOTED from MONITOR (Mar 15, 2026)
    ...
}
```

### Step 2: Verify Pattern Detection
```python
# pattern_detector.py
# Check: Pattern detection function returns valid signals
# Verify: Entry price extraction is correct
# Confirm: Stop-loss calculation logic
```

### Step 3: Test in Dashboard
```bash
python paper_trading_dashboard.py
# Visit http://localhost:8521
# Run scan
# Verify pattern appears in results
```

### Step 4: Monitor First 5 Trades
- Live performance should match OOS PF ± 0.2
- If PF > 1.35 over 5 trades: pattern working great
- If PF < 1.0 over 5 trades: **automatic demotion**, re-evaluate

### Step 5: Document
```
# pattern_monitor_performance.json
{
  "patterns": {
    "three_inside_up": {
      "decision_made": true,
      "decision_date": "2026-03-15",
      "decision_reason": "Live PF 1.42 >= 1.30, Win% 54.0% >= 50%, 22 trades",
      "status": "PROMOTED_TO_WHITELIST"
    }
  }
}
```

---

## Demotion Checklist

When a pattern's **live PF drops < 1.0**:

### Step 1: Immediate Flag
```bash
# Run monitoring script
python monitor_patterns.py
# Script shows: harami_cross → REJECT (PF=0.87)
```

### Step 2: Analyze Cause
- **Regime shift:** Pattern worked in test (1.23 PF) but fails now
- **Detection error:** Pattern logic broken in pattern_detector.py
- **Slippage/cost:** Live execution worse than simulation

### Step 3: Remove from Monitor
- Stop trading this pattern immediately
- Update `pattern_monitor_performance.json` with demotion_date
- Document why it failed

### Step 4: Decision Options
- **Temporary demote:** Remove for 3 months, re-test in Q2
- **Permanent reject:** Pattern fundamentally flawed, archive
- **Debug & fix:** Pattern logic has bug, fix in code, re-enable

---

## Schedule: Weekly Checklist

| Day | Task | Command |
|-----|------|---------|
| **Monday 10am** | Weekly monitor check | `python monitor_patterns.py` |
| **Tuesday** | Review report, flag risks | Manual review of JSON output |
| **Thursday** | Run paper trades | `python paper_trader.py` (ongoing) |
| **Friday EOD** | Archive weekly results | Save monitor_performance.json |
| **Monthly (21st)** | Generate monthly report | Create summary report |

---

## Expected Timeline to Promotions

Based on ~2-3 trades/day per pattern:

| Pattern | Min Samples | Min Days to Promotion | Estimated Timeline |
|---------|-------------|----------------------|-------------------|
| belt_hold_bullish | 20 | 7-10 days | **Mid-March** ✓ |
| harami_cross | 20 | 7-10 days | **Mid-March** |
| three_inside_up | 20 | 7-10 days | **Mid-March** |
| falling_three_methods | 20 | 7-10 days | **Mid-March** |
| in_neck | 25 | 10-13 days | **Late March** |
| long_legged_doji | 25 | 10-13 days | **Late March** |
| spinning_top | 25 | 10-13 days | **Late March** |
| high_wave | 30 | 12-15 days | **Late March** |

**Expected promotions by end of March:** 2-3 patterns  
**Expected demotions:** 1-2 patterns (natural failure rate ~20%)  
**Final monitor status by April 1:** 4-5 patterns still monitoring

---

## FAQ

**Q: What if a pattern gets 20 trades and PF is 1.25 (close to 1.3)?**
A: Continue monitoring. Collect 5-10 more trades. If it hits 1.3, promote. If it drops below 1.2, likely won't make it.

**Q: Can I manually override and promote a pattern before 20 trades?**
A: Not recommended without strong reason. OOS experience shows 20 trades needed for statistical significance. Exception: if live PF > 1.5 and pattern is critical.

**Q: How do I know if a pattern is regime-dependent?**
A: Compare train PF vs test PF:
- Similar (±0.15): Stable across regimes
- Different (>0.2): Regime-dependent, monitor longer

**Q: Should I add all 4 promoted patterns to whitelist now or wait?**
A: Add the 4 immediately (doji, stick_sandwich, homing_pigeon, hammer). Monitor the 8 separately using this system.

**Q: What if a pattern never reaches 20 trades?**
A: After 30 days, it's rare/not tradeable. Archive and re-test in next quarterly OOS cycle.

---

## Next Steps

1. **This week:** Run `python monitor_patterns.py` (will query existing trades)
2. **Each week:** Re-run to track live performance
3. **Monthly:** Generate summary for decision-making
4. **On promotion:** Update trading_config.py + test in dashboard
5. **Quarterly:** Re-run full OOS backtest with newest data

---

**Owner:** User  
**Frequency:** Weekly checks, monthly decisions  
**Success Metric:** 2-3 patterns promoted to whitelist by April 1, 2026  
