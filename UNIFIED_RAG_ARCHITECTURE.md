# UNIFIED RAG ARCHITECTURE: TRAQO 1 + TRAQO 2 Integration

## Overview

Instead of maintaining two separate RAG systems, we can **unify them into a single hierarchical RAG** that combines fundamental intelligence with pattern intelligence:

```
UNIFIED TRAQO RAG
│
├── LAYER 1: Fundamental Documents (TRAQO 2)
│   ├── Insurance/Wealth Theme Docs
│   ├── Conglomerate Arbitrage Docs
│   ├── Manufacturing Capex Docs
│   ├── Digital Infrastructure Docs
│   ├── Commodity Supercycle Docs
│   └── Quality-at-Discount Docs
│
├── LAYER 2: Pattern Documents (TRAQO 1 - Existing)
│   ├── Bullish Candlestick Patterns
│   ├── Bearish Candlestick Patterns
│   ├── Continuation Patterns
│   ├── Momentum Indicators
│   └── Risk Management Rules
│
├── LAYER 3: Integration Rules (New)
│   ├── Universe Filtering (Fundamental → Pattern)
│   ├── Confidence Calibration (Both signals aligned?)
│   ├── Risk Adjustment (Theme-aware stop-losses)
│   └── Thesis Generation (Why to hold + when to exit)
│
└── LAYER 4: Feedback Loop
    ├── Trade outcomes vs fundamental thesis
    ├── Pattern effectiveness by theme
    ├── ROE sustainability tracking
    └── Catalyst realization monitoring
```

---

## Layer 1: Fundamental Intelligence Documents (TRAQO 2)

### **Document Structure for Each Theme**

Each theme folder contains:

```
rag_documents_v2/
├── insurance_wealth_theme/
│   ├── 001_life_insurance_sop.json
│   │   └─ "India insurance penetration at 3.2% GDP vs 6.8% global.
│   │      Decadal convergence opportunity. LIC = singular vehicle
│   │      due to 60%+ market share and government backing."
│   │
│   ├── 002_lic_ev_rerating.json
│   │   └─ "LIC currently trades at 0.9x EV vs comparable peers
│   │      (Ping An 2.5x, AIA 2.8x, Prudential 2.1x). As EV
│   │      disclosure matures post-IPO, re-rating to 1.3-1.5x EV
│   │      is 35-50% upside catalyst."
│   │
│   ├── 003_lic_distribution_moat.json
│   │   └─ "Unreplicable 1.3M+ agent network with deep Tier-3/4
│   │      presence. Government backing delivers rural trust."
│   │
│   └── 004_iciciprume_sip_ecosystem.json
│       └─ "SIP economy at Rs.26,000 Cr/month creates recurring
│          AUM base. 18% of GDP penetration vs 130%+ in US."
│
├── conglomerate_arbitrage_theme/
│   ├── 001_itc_demerger_catalyst.json
│   ├── 002_itc_cigarette_fcf.json
│   ├── 003_itc_fmcg_valuation.json
│   └── 004_castrol_ev_lubricants.json
│
├── manufacturing_capex_theme/
│   ├── 001_pli_scheme_overview.json
│   ├── 002_waaree_solar_capacity.json
│   ├── 003_saatvik_plc2_approval.json
│   ├── 004_oswalp_kusum_govt_mandate.json
│   └── 005_ingersoll_rand_plant_factory.json
│
├── digital_infrastructure_theme/
│   ├── 001_tatacoms_ip_backbone.json
│   ├── 002_ai_traffic_supercycle.json
│   └── 003_cross_border_data_growth.json
│
├── commodity_supercycle_theme/
│   ├── 001_zinc_supply_deficit.json
│   ├── 002_hznl_silver_revenue.json
│   └── 003_china_plus_one_sourcing.json
│
└── quality_at_discount_theme/
    ├── 001_igi_diamond_certification_moat.json
    ├── 002_mstc_govt_eauction_monopoly.json
    ├── 003_ecorecycl_ewaste_formalisation.json
    ├── 004_cams_mutual_fund_duopoly.json
    └── 005_regulatory_tailwinds.json
```

### **Sample Fundamental RAG Document Format**

```json
{
  "doc_id": "insurance_wealth_001_lic_sop",
  "theme": "insurance_wealth",
  "stock": "LIC",
  "document_type": "structural_opportunity",
  "title": "India Life Insurance Penetration Decadal Growth",
  "content": "India's life insurance penetration stands at 3.2% of GDP, significantly below the global average of 6.8%. This represents a decadal structural opportunity. Life Insurance Corporation of India (LIC), the nation's largest insurer with 60%+ market share in new business premium, is the singular vehicle to capture this convergence due to its (1) unreplicable 1.3M+ agent distribution network with deep Tier-3/4 rural presence, (2) sovereign backing providing brand trust in conservative investor segments, (3) embedded value currently underpriced at 0.9x vs private peers at 2-3x EV.",
  "keywords": ["insurance", "penetration", "convergence", "distribution_moat", "embedded_value"],
  "valuation_metric": {
    "current_ev": 0.9,
    "peer_avg_ev": 2.5,
    "target_ev": 1.35,
    "implied_upside_pct": 50
  },
  "catalyst": {
    "timeline": "12-18 months",
    "description": "EV disclosure maturity post-listing + analyst coverage deepening",
    "trigger": "Consecutive quarters of 18%+ premium growth + EV re-rating announcement"
  },
  "risk_factors": [
    "Regulatory: Government changes insurance policy or market share caps",
    "Competitive: Private insurers capture higher share than modeled",
    "Macro: Economic slowdown reduces insurance demand growth"
  ],
  "confidence_score": 95,
  "sources": ["Goldman Sachs India Equity Research", "NSE Filings", "IRDA Reports"],
  "last_updated": "2026-03-04"
}
```

---

## Layer 2: Pattern Intelligence Documents (TRAQO 1 - Existing)

### **Existing Structure** (No Changes)

Your current `rag_documents_v2/all_pattern_documents.json` remains intact with:
- 147K+ candlestick pattern documents
- Bullish, bearish, continuation patterns
- Historical success rates
- Context-specific triggers

**Key Addition**: Add **theme context** to existing pattern documents:

```json
{
  "pattern_id": "bullish_engulfing_001",
  "pattern_name": "Bullish Engulfing",
  "applicable_themes": [
    "insurance_wealth",     // Long-term structural theme = hold through volatility
    "manufacturing_capex",  // Cyclical theme = time exits to earnings cycles
    "digital_infrastructure" // Growth theme = extend holds on positive patterns
  ],
  "historical_success_rate_by_theme": {
    "insurance_wealth": 68,
    "manufacturing_capex": 72,
    "digital_infrastructure": 75
  },
  "hold_duration_by_theme_days": {
    "insurance_wealth": 60,
    "manufacturing_capex": 30,
    "digital_infrastructure": 45
  }
}
```

---

## Layer 3: Integration Rules (NEW - The Secret Sauce)

### **Architecture: Multi-Stage Decision Tree**

```
UNIFIED RAG LOGIC FLOW:
│
├─ INPUT: Stock from TRAQO 2 top 15 picks
│
├─ STAGE 1: Load Fundamental Context
│   │
│   ├─ Query: "What is the investment thesis for this stock?"
│   │   └─ RAG returns all theme documents for stock
│   │
│   ├─ Extract: ROE, PE, valuation metric, catalysts
│   │   └─ Store in memory for later risk adjustment
│   │
│   └─ Confidence: How strong is fundamental case?
│       └─ Score 1-100 based on document alignment
│
├─ STAGE 2: Load Pattern Context
│   │
│   ├─ Query: "What candlestick patterns appear in this stock?"
│   │   └─ RAG returns pattern documents + success rates
│   │
│   ├─ Filter: Apply theme-specific pattern weightings
│   │   └─ Long-term structural stocks weight slow patterns higher
│   │   └─ Cyclical stocks weight momentum patterns higher
│   │
│   └─ Confidence: How strong is technical signal?
│       └─ Score 1-100 based on pattern confidence
│
├─ STAGE 3: Alignment Check
│   │
│   ├─ Both signals positive?
│       ├─ YES: HIGH CONVICTION → Execute trade
│       ├─ PARTIAL: MEDIUM CONVICTION → Reduce position size
│       └─ NO: SKIP or wait for alignment
│   │
│   └─ Generate combined thesis: Why + When
│
├─ STAGE 4: Risk Adjustment
│   │
│   ├─ Fundamental stop-loss: 88% for large-cap, 82% mid, 75% small
│   │   (Theme-aware: insurance stocks hold longer, cyclicals exit faster)
│   │
│   └─ Pattern stop-loss: Candlestick break of pattern low
│       └─ Use stricter stop for high-beta stocks
│
└─ OUTPUT: Trade ticket + integrated thesis
```

### **Code Implementation Location**

Create new file: `rag_integration_engine.py`

```python
"""
RAG Integration Engine
Combines Fundamental + Pattern Intelligence
"""

class RAGIntegrationEngine:
    
    def query_fundamental_thesis(self, stock_symbol: str) -> Dict:
        """Query all fundamental RAG docs for this stock"""
        query = f"What is the investment thesis for {stock_symbol}?"
        results = self.fundamental_rag.query(query)
        
        return {
            'theme': results['theme'],
            'roe': results['roe'],
            'pe': results['pe'],
            'catalysts': results['catalysts'],
            'risk_factors': results['risk_factors'],
            'fundamental_confidence': self._score_thesis_strength(results)
        }
    
    def query_pattern_signals(self, stock_symbol: str, timeframe: str) -> Dict:
        """Query pattern RAG for candlestick signals"""
        query = f"What candlestick patterns appear in {stock_symbol} on {timeframe}?"
        results = self.pattern_rag.query(query)
        
        # Apply theme-aware weighting
        theme = self.fundamental_context['theme']
        weighted_patterns = self._apply_theme_weights(results, theme)
        
        return {
            'patterns': weighted_patterns,
            'pattern_confidence': self._score_pattern_strength(weighted_patterns),
            'suggested_entry': self._calculate_entry_price(weighted_patterns),
            'suggested_stop_loss': self._calculate_stop_loss(weighted_patterns, theme)
        }
    
    def generate_integrated_signal(self, stock_symbol: str) -> Dict:
        """Combine fundamental + pattern signals"""
        fundamental = self.query_fundamental_thesis(stock_symbol)
        pattern = self.query_pattern_signals(stock_symbol, 'daily')
        
        # Alignment score (0-100)
        alignment_score = (
            fundamental['fundamental_confidence'] * 0.6 +
            pattern['pattern_confidence'] * 0.4
        )
        
        # Generate combined thesis
        thesis = self._generate_combined_thesis(
            fundamental=fundamental,
            pattern=pattern,
            alignment_score=alignment_score
        )
        
        # Trading signal
        if alignment_score >= 75:
            signal = 'BUY'
        elif alignment_score >= 50:
            signal = 'SETUP' # Wait for better alignment
        else:
            signal = 'SKIP'
        
        return {
            'stock': stock_symbol,
            'signal': signal,
            'alignment_score': alignment_score,
            'fundamental_confidence': fundamental['fundamental_confidence'],
            'technical_confidence': pattern['pattern_confidence'],
            'thesis': thesis,
            'entry_price': pattern['suggested_entry'],
            'stop_loss': pattern['suggested_stop_loss'],
            'theme': fundamental['theme'],
            'catalysts': fundamental['catalysts']
        }
```

---

## Layer 4: Feedback Loop (Learning System)

### **Structure: RAG Learning Database**

```
feedback/
├── fundamental_accuracy/
│   ├── 2026-03-04_lic_thesis.json
│   │   {
│   │     "prediction_date": "2026-03-04",
│   │     "thesis": "ROE 45%, PE 11x, EV 0.9x → will re-rate to 1.35x",
│   │     "predicted_price": 1265,
│   │     "actual_price_on_target_date": 1185,
│   │     "accuracy_pct": 93.7,
│   │     "lesson": "EV re-rating slower than expected, but fundamental holding",
│   │     "confidence_adjustment": -5
│   │   }
│   │
│   └── 2026-03-04_itc_thesis.json
│
├── pattern_effectiveness_by_theme/
│   ├── insurance_wealth_bullish_engulfing_2026.json
│   │   {
│   │     "theme": "insurance_wealth",
│   │     "pattern": "bullish_engulfing",
│   │     "sample_size": 12,
│   │     "win_rate": 68,
│   │     "avg_hold_days": 45,
│   │     "avg_profit_pct": 8.2,
│   │     "lesson": "Insurance stocks hold longer than avg - extend targets"
│   │   }
│   │
│   └── manufacturing_capex_hammer_2026.json
│
└── catalyst_realization_tracking/
    ├── lic_ev_rerate_catalyst_2026.json
    │   {
    │     "catalyst": "EV disclosure maturity post-listing",
    │     "expected_timeline": "12-18 months",
    │     "actual_realization_date": "2026-Q4",
    │     "impact_magnitude": "Actual 1.32x EV vs predicted 1.35x",
    │     "lesson": "Catalyst timing 25% slower than modeled"
    │   }
    │
    └── itc_demerger_catalyst_2026.json
```

---

## Integration with Existing Code

### **Modification: `paper_trader.py`**

```python
# Add to paper_trader.py imports
from rag_integration_engine import RAGIntegrationEngine
from fundamental_screener import FundamentalScreener

# In main trading loop:

class PaperTrader:
    def __init__(self):
        self.screener = FundamentalScreener()
        self.rag_engine = RAGIntegrationEngine()
        
    def daily_workflow(self):
        """Unified TRAQO 1+2 workflow"""
        
        # STAGE 1: Generate universe (TRAQO 2)
        picks_15 = self.screener.run_screening()  # Top 15 fundamental picks
        
        # STAGE 2: For each pick, generate integrated signal (TRAQO 1+2)
        for stock in picks_15:
            integrated_signal = self.rag_engine.generate_integrated_signal(stock['symbol'])
            
            # Only trade if BOTH fundamental + pattern aligned
            if integrated_signal['signal'] == 'BUY':
                self.execute_trade(
                    symbol=stock['symbol'],
                    entry=integrated_signal['entry_price'],
                    stop_loss=integrated_signal['stop_loss'],
                    thesis=integrated_signal['thesis'],
                    alignment_score=integrated_signal['alignment_score']
                )
            
            # Log for RAG feedback
            self.log_signal(integrated_signal)
        
        # STAGE 3: Monitor existing trades
        self.monitor_catalysts_and_update_rag()
```

---

## RAG Document Inventory Required

### **Total Documents to Create:**

| Layer | Category | Est. Docs | Total |
|-------|----------|-----------|-------|
| 1 | Insurance/Wealth Theme | 25 | 25 |
| 1 | Conglomerate Arbitrage | 20 | 45 |
| 1 | Manufacturing Capex | 30 | 75 |
| 1 | Digital Infrastructure | 15 | 90 |
| 1 | Commodity Supercycle | 20 | 110 |
| 1 | Quality-at-Discount | 25 | 135 |
| 2 | Existing Pattern Docs | 147,000 | 147,135 |
| 3 | Integration Rules | 50 | 147,185 |
| 4 | Feedback Logs | 100/year | 147,285 |

---

## Implementation Roadmap

### **Phase 1: Foundation (Week 1-2)**
- [ ] Create fundamental RAG document structure
- [ ] Write 135 fundamental documents (6 themes × 20-30 docs each)
- [ ] Deploy `fundamental_screener.py`
- [ ] Test TRAQO 2 screening output

### **Phase 2: Integration (Week 3)**
- [ ] Build `rag_integration_engine.py`
- [ ] Enhance pattern RAG docs with theme context
- [ ] Create integration rules (Stage 3 logic)
- [ ] Integrate with `paper_trader.py`

### **Phase 3: Learning (Week 4+)**
- [ ] Set up feedback logging
- [ ] Track thesis accuracy monthly
- [ ] Update pattern success rates by theme
- [ ] Refine RAG document quality based on outcomes

---

## Key Advantages of Unified Approach

1. **Higher Win Rate**: Only trade stocks with both fundamental strength + technical setup
2. **Better Risk**: Theme-aware stop-losses (insurance stocks hold longer, cyclicals exit faster)
3. **Explainability**: Every trade has both "why" (fundamental) + "when" (pattern)
4. **Learning Feedback**: Continuously improve both RAGs based on actual outcomes
5. **Reduced False Signals**: Candlestick patterns filtered to high-quality universe
6. **Scalability**: Easy to add new themes and stocks without rewriting core logic
7. **Production Quality**: Mimics professional quant fund workflows

---

## Next Steps

1. ✅ Approve unified architecture
2. Build fundamental RAG documents (6 themes)
3. Deploy `fundamental_screener.py` + test screening
4. Build and integrate `rag_integration_engine.py`
5. Start daily screening → pattern detection → execution
6. Monitor feedback loop monthly

Would you like me to:
- Generate all 135 fundamental RAG documents for the 6 themes?
- Deploy and test `fundamental_screener.py` first?
- Create sample integrated trading signals?
