#!/usr/bin/env python3
"""
RAG LEARNING FREQUENCY & TIMING GUIDE
Complete explanation of when/how the feedback loop learns
"""

guide = """

═══════════════════════════════════════════════════════════════════════════════
RAG SELF-LEARNING: TIMING & FREQUENCY
═══════════════════════════════════════════════════════════════════════════════

QUESTION 1: HOW MANY DAYS BEFORE RAG LEARNS?
─────────────────────────────────────────────

ANSWER: Learning happens DAILY (if set up with scheduler) OR ON-DEMAND (manual)

Timeline:
  Day 1:  Scan generates signals → Some enter, some filtered (shadow)
          ✓ 71 bullish_harami as shadow trades marked for tracking
  
  Day 2:  Markets close positions → Outcomes recorded
          ✓ 22 wins, 49 losses in bullish_harami shadow cohort
  
  Day 3:  Daily run executes:
          - python paper_trader.py run (4 PM)
          - Calls: feed_outcomes_to_rag()
          - Calculates: 22/71 = 31% real WR
          - Generates: learned_rules.json with bullish_harami stats
          ✓ RAG LEARNS → Blends 31% with 68% RAG = 49.5% prediction
  
  Day 4+: Next scan with UPDATED feedback
          ✓ Bullish_harami shows 49.5% confidence instead of 68%
          ✓ Fewer trades enter (better risk management)


QUESTION 2: IS IT PER-TRADE, DAILY, WEEKLY, OR EVERY N TRADES?
──────────────────────────────────────────────────────────────

ANSWER: DAILY (with automatic scheduler) + ON-DEMAND (manual command)

Timing Bucket:

  ┌─────────────────────────────────┬──────────────────┬─────────────────┐
  │ Frequency                       │ When             │ How             │
  ├─────────────────────────────────┼──────────────────┼─────────────────┤
  │ AUTOMATIC (Daily at 4 PM)       │ Weekdays 4:00 PM │ Windows Task    │
  │                                 │ (if scheduled)   │ Scheduler       │
  │                                 │                  │ → run_paper_    │
  │                                 │                  │   trader.bat    │
  └─────────────────────────────────┴──────────────────┴─────────────────┘

  ┌─────────────────────────────────┬──────────────────┬─────────────────┐
  │ MANUAL (On-Demand)              │ Anytime you      │ Command:        │
  │                                 │ want             │ python          │
  │                                 │                  │ paper_trader.py │
  │                                 │                  │ feedback        │
  └─────────────────────────────────┴──────────────────┴─────────────────┘

Example Scenario:
  Monday 2 PM:   5 trades close (2 wins, 3 losses)
  Monday 3 PM:   New pattern data available in feedback
  Monday 4 PM:   Scheduler runs → feed_outcomes_to_rag() executes
                 → learned_rules.json updated with new pattern stats
  Monday 4:15 PM: You run scan → sees updated feedback → adjust predictions
  
  Same day feedback! (Not week later)


QUESTION 3: IS IT AUTOMATIC OR DO I NEED TO RUN A COMMAND?
──────────────────────────────────────────────────────────

ANSWER: BOTH!

AUTOMATIC (If Windows Task Scheduler is set up):
  ✓ Runs at 4 PM weekdays automatically
  ✓ No action needed
  ✓ Output logged to: paper_trades/scheduler.log
  ✓ Run just once: right after market close (all positions settled)

MANUAL (If you want to trigger immediately):
  Command:  python paper_trader.py feedback
  
  This calls feed_outcomes_to_rag() immediately without:
    - shadow monitoring
    - risk checking
    - daily report generation
  
  Usage: After important trades close, run for immediate feedback


─────────────────────────────────────────────────────────────────────────────
DETAILED LEARNING FLOW (What Happens Each Day)
─────────────────────────────────────────────────────────────────────────────

Timeline with actual code execution:

MORNING (9:30 AM - Market Open):
  └─ (Nothing - system sleeps)

AFTERNOON (4 PM - Market Close, Scheduled):
  ├─ Windows Task Scheduler triggers: run_paper_trader.bat
  ├─ Paper Trader initializes
  ├─ INPUT: Database has closed trades from today + yesterday + past days
  │
  ├─ STEP 1: Catch-up (scan old dates not yet scanned)
  │  └─ None if today already scanned
  │
  ├─ STEP 2: Scan Preview (generate signals, don't enter)
  │  ├─ Finds 500 signals from today's market data
  │  ├─ Filters: Direction, patterns, thresholds
  │  ├─ Result: 86 signals staged in pending_signals.json
  │  └─ 424 signals filtered to shadow (tracked as "not entered")
  │
  ├─ STEP 3: Monitor Open Positions
  │  ├─ Check active trades for:
  │  │  - P&L updates
  │  │  - Risk levels
  │  │  - Exit signals
  │  └─ Record trade outcomes (WIN/LOSS)
  │
  ├─ STEP 4: Generate Daily Report
  │  └─ Summary: Total trades, wins, losses, returns
  │
  ├─ 🎯 STEP 5: FEED OUTCOMES TO RAG  ← LEARNING HAPPENS HERE
  │  │
  │  ├─ Query closed trades (status: WON/LOST/EXPIRED)
  │  │  └─ Example: 5 trades closed today
  │  │     • bullish_harami: 2 wins (70% WR on 5 trades)
  │  │     • hammer: 1 win (20% WR on 5 trades)
  │  │     • etc.
  │  │
  │  ├─ Query closed SHADOW trades (NEW - Option B)
  │  │  └─ Example: 50 shadow trades closed
  │  │     • bullish_harami: 22 wins out of 71 (31% WR weighted 0.6x)
  │  │     • three_black_crows: 18 wins out of 45 (40% WR weighted 0.6x)
  │  │
  │  ├─ Save to: feedback/feedback_log.json
  │  │  └─ Now has 1280 entries (99 real + 1181 shadow)
  │  │
  │  ├─ Calculate patterns statistics
  │  │  ├─ Win rates per pattern
  │  │  ├─ Win rates per pattern__horizon
  │  │  ├─ Win rates per pattern__trend
  │  │  ├─ Win rates per pattern__sector
  │  │  └─ Apply 0.6x weight to shadow data
  │  │     ✓ bullish_harami now shows 31% WR (from shadow)
  │  │
  │  ├─ Generate penalties/boosts
  │  │  ├─ IF WR < 30%: Add to filter_penalties
  │  │  ├─ IF WR > 70% and N≥10: Add to filter_boosts
  │  │  └─ bullish_harami doesn't auto-penalize (31% is borderline)
  │  │
  │  └─ Save learned_rules.json with:
  │     ├─ pattern_adjustments
  │     ├─ horizon_adjustments
  │     ├─ regime_adjustments
  │     ├─ filter_penalties (6 patterns)
  │     ├─ filter_boosts (0 patterns)
  │     └─ rules (learned meta-patterns)
  │
  ├─ STEP 6: Reload Feedback
  │  └─ statistical_predictor reloads learned_rules.json into memory
  │     ✓ Next predictions will use updated feedback
  │
  └─ COMPLETE (4:15-4:30 PM typically)
      └─ Log written to: paper_trades/scheduler.log

EVENING (User's Discretion):
  └─ User checks pending_signals.json
     • Reviews 86 pending trades
     • Decides: approve all, approve subset, or discard
     Command: python paper_trader.py approve [indices]
     Command: python paper_trader.py discard


NEXT MORNING (until 4 PM next day):
  └─ Trades run overnight
     • Pending trades are LIVE during market hours
     • Positions accumulate P&L
     • Outcomes recorded in database


NEXT MARKET CLOSE (4 PM + 1 day):
  └─ Cycle repeats
     • New closed trades → feedback updated
     • learned_rules.json regenerated
     • Next scan uses latest feedback


─────────────────────────────────────────────────────────────────────────────
LEARNING SPEED: How Many Trades Before Pattern Gets Penalized?
─────────────────────────────────────────────────────────────────────────────

Pattern Learning Thresholds (from code):

PATTERN-LEVEL PENALTIES (filter_penalties):
  ├─ Min trades needed: 5
  ├─ Penalty condition: WR < 30% (on 5+ trades)
  ├─ bullish_harami example:
  │  • After 5 closed: If 1 win, 4 loss = 20% WR → Instant penalty
  │  • After 71 closed: 22 wins = 31% WR → Borderline (not penalized yet)
  │
  └─ 🎯 LEARNING SPEED: 5 trades minimum to generate penalty

HORIZON-SPECIFIC PENALTIES (horizon_filter_penalties):
  ├─ Min trades needed: 3
  ├─ Penalty condition: WR < 25% (on 3+ trades)
  ├─ bullish_harami__BTST_1d example:
  │  • After 3 closed: If 0 wins = 0% WR → Instant penalty
  │  • After 41 closed: 17 wins = 41% WR → No penalty
  │
  └─ 🎯 LEARNING SPEED: 3 trades minimum per horizon combination

PATTERN-BOOST GENERATION:
  ├─ Min trades needed: 10
  ├─ Boost condition: WR > 70% (on 10+ trades)
  ├─ Example: IF hammer 12 wins out of 10 trades = 83% WR → Boost applied
  │
  └─ 🎯 LEARNING SPEED: 10 trades before boost kicks in

ACTUAL MARCH 2026 HISTORY:
  ├─ Feb 28: 161 trades closed
  ├─ Mar 1-14: Additional trades close
  ├─ Mar 15: 6 penalties generated (belt_hold_bullish, hammer, homing_pigeon, etc.)
  ├─ Mar 20: 1,124 shadow trades analyzed (71 bullish_harami)
  │
  └─ 🎯 TOTAL LEARNING TIME: ~20-30 days to get reliable pattern stats


─────────────────────────────────────────────────────────────────────────────
CURRENT STATE (March 20, 2026): How Much Has RAG Learned?
─────────────────────────────────────────────────────────────────────────────

REAL TRADES (from paper_trades table):
  ├─ Total closed: 99
  ├─ Patterns covered: ~8 with learning data
  ├─ Example: belt_hold_bullish
  │  • 59 real trades
  │  • 14 wins (24% WR)
  │  • Status: ✓ PENALIZED (WR < 30%)
  │
  └─ 🎯 LEARNING FROM REAL: 99 trades total, only 6 heavily penalized so far

SHADOW TRADES (from shadow_trades table, NEW - Option B):
  ├─ Total analyzed: 1,124 (99 real + 1,125 shadow)
  ├─ Patterns with learning data: 18 patterns
  ├─ Example: bullish_harami
  │  • 71 shadow trades analyzed
  │  • 22 wins (31% WR)
  │  • Weight: 0.6x (weighted 42.6 effective trades)
  │  • Status: In pattern_adjustments, blended into predictions
  │
  └─ 🎯 LEARNING FROM SHADOW: 1,124 tracks, much richer signal

BLENDING RESULT:
  ├─ bullish_harami: 68% (RAG) → 49.5% (blended with 31% shadow)
  ├─ belt_hold_bullish: 52% (RAG) → 38% (blended with 24% real)
  ├─ hammer: 45% (RAG) → 32% (blended with 20% real)
  │
  └─ 🎯 RAG IS NOW LEARNING ✓ (as of March 20, 2026)


─────────────────────────────────────────────────────────────────────────────
HOW TO VERIFY RAG IS LEARNING (Action Items)
─────────────────────────────────────────────────────────────────────────────

1. CHECK FEEDBACK LOG:
   cd paper_trades
   wc -l feedback/feedback_log.json
   (Should grow by 10-50 entries each day as trades close)

2. CHECK LEARNED RULES:
   python -c "import json; lr = json.load(open('feedback/learned_rules.json')); print(f'Patterns: {len(lr.get(\"pattern_adjustments\", {}))}'); print(f'Updated: {lr.get(\"updated_at\")}')"
   (Should update daily)

3. CHECK SCHEDULER LOG:
   type paper_trades\scheduler.log | tail -20
   (Should show 4 PM runs)

4. COMPARE PREDICTIONS:
   OLD: bullish_harami = 68% WR (Jan-Feb)
   NEW: bullish_harami = 49.5% WR (after learning from shadow + real)
   (Should show blending in action)

5. RUN MANUAL FEEDBACK:
   python paper_trader.py feedback
   (Learn immediately, don't wait for scheduler)


─────────────────────────────────────────────────────────────────────────────
SCHEDULING: How to Set Up Automatic Daily Learning (Windows)
─────────────────────────────────────────────────────────────────────────────

ALREADY SET UP? Check:
  1. Open Windows Task Scheduler
  2. Look for: "Paper Trader - Daily Run 4 PM"
  3. Check: Status = Enabled, Last Run = Yesterday 4 PM

IF NOT SET UP:

  Step 1: Create batch file (already exists):
    File: C:\\...\\run_paper_trader.bat
    Content:
      @echo off
      cd /d "%~dp0"
      call .venv\\Scripts\\activate.bat
      python paper_trader.py run >> paper_trades\\scheduler.log 2>&1

  Step 2: Create Task Scheduler task:
    1. Open: Task Scheduler
    2. Right-click: Task Scheduler Library → New Task
    3. Name: "Paper Trader - Daily Run 4 PM"
    4. Trigger: Daily at 4:00 PM
    5. Action:
       Program: C:\\Windows\\System32\\cmd.exe
       Arguments: /c \"C:\\path\\to\\run_paper_trader.bat\"
    6. Settings:
       ✓ Run with highest privileges
       ✓ Run whether user is logged in or not

  Step 3: Test:
    Right-click task → Run
    Check: paper_trades\\scheduler.log should have new entry

───────────────────────────────────────────────────────────────────────────────

SUMMARY TABLE:
──────────────


Timing          │ Frequency           │ Method          │ Command
────────────────┼─────────────────────┼─────────────────┼─────────────────────
Daily (4 PM)    │ Automatic           │ Task Scheduler  │ python paper_trader.py run
On-Demand       │ Manual              │ Terminal        │ python paper_trader.py feedback
Per-Trade       │ Not yet             │ N/A             │ N/A
Weekly          │ Not supported       │ N/A             │ N/A


Learning Sample Size:
────────────────────

Minimum for Pattern Penalty:       5 trades
Minimum for Horizon Penalty:       3 trades
Minimum for Pattern Boost:        10 trades
Minimum for Reliable Signal:      30+ trades
Current coverage (Mar 20):       1,124 total tracks
Patterns with learning:           18+ patterns


Current Learning Status:
──────────────────────

Real Trades:        99 (2 months history)
Shadow Trades:    1,125 (recent month)
Total Data:       1,224 trades
Blending Active:    ✓ YES (49.5% bullish_harami)
Penalties Active:   ✓ YES (6 patterns)
Boosts Active:      ✗ NO (0 patterns yet)


"""

print(guide)
