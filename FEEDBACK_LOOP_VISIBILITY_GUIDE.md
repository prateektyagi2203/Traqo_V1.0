"""
FEEDBACK LOOP VISIBILITY ROADMAP
================================
How to gain transparency into your RAG without building a full app

The Problem:
  ✗ feedback/feedback_log.json exists but no UI to read it
  ✗ learned_rules.json has penalties but you can't see them clearly
  ✗ Don't know which patterns are whitelisted vs penalized vs boosted
  ✗ When a signal is rejected, don't know why (which filter killed it?)
  ✗ Can't see the decision chain during a scan

Solution Strategy:
  → Build 3 lightweight dashboards (HTML, no framework needed)
  → Extract decision logic into readable reports
  → Add detailed logging during scans so you can audit decisions

IMPLEMENTATION PRIORITY
======================

LEVEL 1: MINIMUM VIABLE TRANSPARENCY (Today - 2 hours)
────────────────────────────────────────────────────────

1A. Pattern Status Dashboard
  What: HTML file showing pattern penalties/boosts/whitelist status
  Why: Answers "What patterns does RAG trust?"
  Time: 30 minutes
  Output: A single HTML file that lists:
    - All 53 patterns with current status (WHITELISTED/PENALIZED/UNKNOWN)
    - Win rate from paper trading
    - Rejection reason if penalized
  Build: Extract from feedback_log.json + learned_rules.json, render in simple table

1B. Feedback Loop Timeline
  What: HTML log viewer (newest entries first)
  Why: Answers "What happened in the learning loop?"
  Time: 20 minutes
  Output: Searchable/filterable log viewer showing:
    - Each pattern's feedback entry
    - Timestamp
    - Win rate
    - Action taken (reject/boost)
    - Reason
  Build: Read feedback_log.json, render with sort/filter buttons

1C. Scan Decision Audit Log
  What: Add detailed logging to paper_trader.py during scan
  Why: Answers "Why was signal X rejected?"
  Time: 30 minutes
  Output: New file "scan_audit_YYYY-MM-DD.json" showing for each ticker:
    - Patterns detected: [hammer, doji, ...]
    - Patterns tradeable (after whitelist filter): [hammer]
    - Raw win rate from backtest: 65%
    - Horizon-adjusted win rate: 55%
    - RAG penalties applied: "belt_hold_bullish" penalized
    - Final decision: REJECTED (reason: feedback penalty)
  Build: Add logging statements to _analyse_ticker() and scan_date()

LEVEL 2: OPERATIONAL INTELLIGENCE (Day 2-3 - 3 hours)
──────────────────────────────────────────────────────

2A. RAG Rules Explorer
  What: Dashboard showing all learned_rules.json in readable format
  Why: Answers "What rules is RAG enforcing?"
  Output: Grouped by rule type:
    - Pattern penalties (which, how long, reason)
    - Horizon-specific penalties (e.g., "belt_hold in 3-day horizon")
    - Sector-specific rules
    - Market regime rules
  Build: Parse learned_rules.json, group, render in collapsible sections

2B. Trade Performance by Pattern
  What: HTML dashboard showing which patterns actually won/lost
  Why: Answers "Which patterns work vs which don't?"
  Output: Table by pattern:
    - Total trades: 59
    - Wins: 14 (23.7%)
    - Losses: 45 (76.3%)
    - Avg profit per win: +2.1%
    - Avg loss per loss: -1.8%
    - Profit factor: 0.62 (bad)
  Build: Query paper_trades.db, aggregate by pattern, calculate metrics

2C. Feedback Impact Simulator
  What: Interactive tool "What if I change this threshold?"
  Why: Answers "Should I lower penalty threshold from 45% to 30%?"
  Output: Shows which patterns would become tradeable if threshold changes
  Build: Load feedback_log.json, let user slide threshold, see changes

LEVEL 3: PREDICTIVE INTELLIGENCE (Day 4-5 - 4 hours)
──────────────────────────────────────────────────────

3A. Pattern Regime Analyzer
  What: Show pattern performance by market regime (bullish/bearish/neutral)
  Why: Implement Tier 2B from Jefferies analysis
  Output: "Hammer works 65% in bullish regime but 10% in bearish regime"
  Build: Correlate trade dates with regime_detector.py output, slice results

3B. Scan Simulation Tool
  What: "Replay today's scan with different config"
  Why: Test "What if I added pattern X to whitelist? How many signals?"
  Output: Shows signals that would have been generated
  Build: Run _analyse_ticker() with custom config, capture results

═════════════════════════════════════════════════════════════════════════

SPECIFIC IMPLEMENTATION INSTRUCTIONS
════════════════════════════════════════════════════════════════════════

LEVEL 1A: Pattern Status Dashboard (First to Build)
────────────────────────────────────────────────────

Step 1: Create data extraction script
  File: _extract_pattern_status.py
  
  import json
  
  with open('feedback/feedback_log.json') as f:
      log = json.load(f)
  
  with open('feedback/learned_rules.json') as f:
      rules = json.load(f)
  
  with open('trading_config.py') as f:
      # Parse WHITELISTED_PATTERNS and EXCLUDED_PATTERNS
      
  # Create dict:
  patterns = {
      'hammer': {
          'status': 'PENALIZED',  # from learned_rules
          'win_rate': 16.7,
          'trades': 18,
          'reason': 'Win rate 17% below 45% threshold',
          'whitelisted': True,  # from trading_config
          'excluded': False,
      },
      ...
  }
  
  # Export to JSON for dashboard

Step 2: Create HTML viewer
  File: feedback_dashboard.html
  - Load patterns JSON via fetch()
  - Render table with:
    * Pattern name
    * Status badge (green=whitelisted, red=penalized, gray=unknown)
    * Trade count & win rate
    * Reason text
  - Add search/sort/filter buttons
  - Add last updated timestamp

LEVEL 1B: Feedback Loop Timeline
─────────────────────────────────

Step 1: Create list formatter
  File: _format_feedback_log.py
  
  import json
  with open('feedback/feedback_log.json') as f:
      entries = json.load(f)
  
  # Sort by timestamp DESC (newest first)
  entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
  
  # Export to simple JSON for dashboard

Step 2: Create HTML viewer
  File: feedback_log_viewer.html
  - Load JSON via fetch()
  - Render as timeline (vertical list)
  - Each entry shows:
    * Pattern name
    * Timestamp
    * Win rate / trade count
    * Action (reject/boost)
    * Reason text
  - Add filter by pattern: checkbox list
  - Add date range picker


LEVEL 1C: Scan Decision Audit
──────────────────────────────

Step 1: Modify paper_trader.py
  Location: _analyse_ticker() method
  
  Add at the end:
  
  # AUDIT LOGGING
  audit_entry = {
      'ticker': ticker,
      'timestamp': datetime.now().isoformat(),
      'patterns_detected': patterns,
      'patterns_tradeable': tradeable,
      'indicators': indicators,
      'prediction': {
          'direction': prediction.get('predicted_direction'),
          'win_rate_base': prediction.get('win_rate'),
          'confidence': prediction.get('confidence_level'),
      },
      'horizon_results': {}
  }
  
  for days, hz_data in horizon_levels.items():
      audit_entry['horizon_results'][days] = {
          'direction': hz_data.get('direction'),
          'target_pct': hz_data.get('target_pct'),
          'sl_pct': hz_data.get('sl_pct'),
          'rr_ratio': hz_data.get('rr_ratio'),
      }
  
  # Save to daily audit file
  audit_file = f"paper_trades/audit_{date.today().isoformat()}.json"
  with open(audit_file, 'a') as f:
      f.write(json.dumps(audit_entry) + '\n')

Step 2: Enhance scan_date() logging
  Location: scan_date() method, inside the signal rejection logic
  
  Current code:
  ```python
  if hard_reject and skip_reasons:
      # Collect for shadow sampling
      ...
  ```
  
  Add before this:
  ```python
  # DETAILED AUDIT
  rejection_audit = {
      'ticker': ticker,
      'pattern': hz_data.get('direction'),
      'horizon': h_label,
      'detected_patterns': tradeable,
      'win_rate': wr,
      'confidence': conf,
      'rr_ratio': rr,
      'skip_reasons': skip_reasons,
      'timestamp': datetime.now().isoformat(),
  }
  
  audit_file = f"paper_trades/rejections_{date.today().isoformat()}.json"
  with open(audit_file, 'a') as f:
      f.write(json.dumps(rejection_audit) + '\n')
  ```

Step 3: Create audit viewer
  File: scan_audit_viewer.html
  - Load audit JSON files (all rejections from today)
  - Show:
    * Ticker
    * Why rejected (which filter: direction, penalty, confidence, RR, etc.)
    * What would have changed the decision
  - Sort by rejection reason (group similar)


═════════════════════════════════════════════════════════════════════════

QUICK START TEMPLATE: Feedback Dashboard HTML
═════════════════════════════════════════════════════════════════════════

File: feedback_status.html

<!DOCTYPE html>
<html>
<head>
    <title>RAG Pattern Status Dashboard</title>
    <style>
        body { font-family: Arial; margin: 20px; background: #f5f5f5; }
        h1 { color: #333; }
        table { 
            width: 100%; 
            border-collapse: collapse; 
            background: white;
            margin: 20px 0;
        }
        th { 
            background: #2c3e50; 
            color: white; 
            padding: 12px; 
            text-align: left;
        }
        td { 
            padding: 12px; 
            border-bottom: 1px solid #ddd; 
        }
        tr:hover { background: #f9f9f9; }
        .status-whitelisted { 
            background: #d4edda; 
            color: #155724; 
            padding: 4px 8px; 
            border-radius: 3px; 
            font-weight: bold;
        }
        .status-penalized { 
            background: #f8d7da; 
            color: #721c24; 
            padding: 4px 8px; 
            border-radius: 3px; 
            font-weight: bold;
        }
        .status-unknown { 
            background: #e2e3e5; 
            color: #383d41; 
            padding: 4px 8px; 
            border-radius: 3px;
        }
        .stats {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-value {
            font-size: 32px;
            font-weight: bold;
            color: #2c3e50;
        }
        .stat-label {
            font-size: 12px;
            color: #777;
            margin-top: 8px;
        }
        input[type="search"] {
            padding: 10px;
            font-size: 14px;
            width: 300px;
            margin-bottom: 20px;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <h1>🎯 RAG Pattern Status Dashboard</h1>
    <p>Last updated: <span id="last-updated">Loading...</span></p>
    
    <div class="stats">
        <div class="stat-card">
            <div class="stat-value" id="count-whitelisted">0</div>
            <div class="stat-label">Whitelisted Patterns</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="count-penalized">0</div>
            <div class="stat-label">Penalized Patterns</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="count-unknown">0</div>
            <div class="stat-label">Unknown Patterns</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="avg-win-rate">0%</div>
            <div class="stat-label">Avg Win Rate (All)</div>
        </div>
    </div>
    
    <h2>Search Patterns</h2>
    <input type="search" id="search-box" placeholder="Search pattern name...">
    
    <table id="patterns-table">
        <thead>
            <tr>
                <th>Pattern Name</th>
                <th>Status</th>
                <th>Trades</th>
                <th>Win Rate</th>
                <th>Reason/Notes</th>
            </tr>
        </thead>
        <tbody id="table-body">
        </tbody>
    </table>

    <script>
        async function loadPatternStatus() {
            try {
                // Load from the extracted JSON
                const response = await fetch('pattern_status.json');
                const patterns = await response.json();
                
                renderTable(patterns);
                updateStats(patterns);
            } catch(e) {
                console.error('Failed to load pattern status:', e);
                document.getElementById('table-body').innerHTML = 
                    '<tr><td colspan=5>Error loading data</td></tr>';
            }
        }
        
        function renderTable(patterns) {
            const tbody = document.getElementById('table-body');
            tbody.innerHTML = '';
            
            Object.entries(patterns).forEach(([name, data]) => {
                const statusClass = data.status === 'WHITELISTED' ? 'status-whitelisted' :
                                   data.status === 'PENALIZED' ? 'status-penalized' : 
                                   'status-unknown';
                
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td><strong>${name}</strong></td>
                    <td><span class="${statusClass}">${data.status}</span></td>
                    <td>${data.trades || 0}</td>
                    <td>${(data.win_rate || 0).toFixed(1)}%</td>
                    <td>${data.reason || '—'}</td>
                `;
                tbody.appendChild(row);
            });
        }
        
        function updateStats(patterns) {
            let whitelisted = 0, penalized = 0, unknown = 0;
            let totalWR = 0, count = 0;
            
            Object.values(patterns).forEach(p => {
                if (p.status === 'WHITELISTED') whitelisted++;
                else if (p.status === 'PENALIZED') penalized++;
                else unknown++;
                
                if (p.win_rate) {
                    totalWR += p.win_rate;
                    count++;
                }
            });
            
            document.getElementById('count-whitelisted').textContent = whitelisted;
            document.getElementById('count-penalized').textContent = penalized;
            document.getElementById('count-unknown').textContent = unknown;
            document.getElementById('avg-win-rate').textContent = 
                (count > 0 ? (totalWR / count).toFixed(1) : 0) + '%';
        }
        
        // Search filter
        document.getElementById('search-box').addEventListener('input', async (e) => {
            const response = await fetch('pattern_status.json');
            const patterns = await response.json();
            const filtered = Object.fromEntries(
                Object.entries(patterns).filter(([name]) => 
                    name.toLowerCase().includes(e.target.value.toLowerCase())
                )
            );
            renderTable(filtered);
        });
        
        loadPatternStatus();
    </script>
</body>
</html>

═════════════════════════════════════════════════════════════════════════

BUILD ORDER
═══════════

TODAY (2 hours):
  ✓ Create _extract_pattern_status.py 
  ✓ Create feedback_status.html 
  ✓ Run extraction, verify JSON is readable
  → Result: You can see which patterns RAG trusts

TOMORROW (1 hour):
  ✓ Modify paper_trader.py to add scan audit logging
  ✓ Create scan_audit_viewer.html
  → Result: You can see why each signal was rejected

WITHIN 2 DAYS (1 hour):
  ✓ Create feedback_log_viewer.html for timeline
  → Result: You see all RAG learning events with timestamps

═════════════════════════════════════════════════════════════════════════

WHAT YOU'LL GAIN
════════════════

After Level 1 implementation:
  ✓ Can answer "Which patterns does RAG allow?"
  ✓ Can see win rates by pattern
  ✓ Can see rejection reasons for every attempted signal
  ✓ Can track RAG's learning over time
  ✓ Can test "What if I relax threshold?"

This turns your black-box system into transparent, auditable trading.

═════════════════════════════════════════════════════════════════════════
"""

print(__doc__)
