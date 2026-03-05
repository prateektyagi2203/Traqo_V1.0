# TRAQO 2: Goldman Sachs Report Structure Analysis

## Executive Summary
Goldman Sachs' "India Top 15 Conviction Picks" report reveals a **sophisticated dual-layer stock selection framework** that we should replicate for TRAQO 2.

---

## 📊 Report Structure Breakdown

### **LAYER 1: MACROECONOMIC THEME SELECTION** 
GS identifies **6 high-conviction India themes** for 2026-2028:

1. **Life Insurance Decadal Growth** - LIC structural underinsurance premium
2. **FMCG Conglomerate De-Rating** - ITC hotels demerger arbitrage
3. **Commodity Commodity Supercycle** - Zinc supply deficit + silver demand
4. **Digital Infrastructure** - AI traffic explosion on IP networks (Tata Comms)
5. **Wealth Management Megatrend** - SIP economy + AMC AUM growth
6. **India Manufacturing Capex Cycle** - PLI schemes, green energy, e-waste, pumps

#### **Key Insight**: Macroeconomic screening PRECEDES stock picking. This is bottom-up + top-down fusion.

---

## 🔍 LAYER 2: QUANTITATIVE SCREENING METHODOLOGY

### **GS Quality-Value-Momentum Composite Weighting:**
```
ROE (Quality)           = 40%
Earnings Yield (Value)  = 30%  
Asset Efficiency        = 15%
Momentum (1M return)    = 15%
------------------------
Total                   = 100%
```

### **Universe**: 4,870 NSE/BSE securities with complete financial data

### **Selection Criteria by Market Cap Segment**:
| Criteria | Large Cap | Mid Cap | Small Cap |
|----------|-----------|---------|-----------|
| Min Market Cap | >Rs.20,000 Cr | Rs.5,000-20,000 Cr | Rs.500-5,000 Cr |
| PE Valuation Range | 11-57x | 19-46x | 7.8-29x |
| ROE Sweet Spot | 45-82% | 45-65% | 58-93% |
| Recommended Position Size | Core holding | 8-15% portfolio | 3-6% portfolio |

---

## 💡 LAYER 3: INVESTMENT THESIS ARCHITECTURE

Each stock has a **4-part investment thesis**:

### **Part A: Structural Thesis**
- Long-term secular trend (3-10 year)
- Why market is mispricing the opportunity
- Example: "India insurance penetration at 3.2% of GDP vs 6.8% global average"

### **Part B: Valuation Arbitrage**
- Current valuation metric (PE, EV, ROE mismatch)
- Comparable peer pricing
- Re-rating catalyst
- **Example Formula**: "11x PE on 46% ROE is starkly undervalued vs Ping An at 25x PE on lower ROE"

### **Part C: Growth/Operational Catalyst**
- Near-term earnings driver (1-3 months)
- Momentum signal
- Example: "+17% 1-month momentum = institutional discovery phase"

### **Part D: Portfolio Role**
- Why it fits a specific mandate
- Risk profile
- Typical investor suitability

---

## 📈 PRICE TARGET METHODOLOGY

### **Base Case (12-Month Target)**:
```
= CMP × [Sector Median PE × (1 + EPS Growth Rate)]
+ Momentum Signal Overlay (+10-15% for positive momentum)
```

### **Bull Case** (12-month, +1 SD):
- Large Cap: +12%
- Mid Cap: +18%
- Small Cap: +25%

### **Bear Case** (12-month, -1 SD):
- Stop-loss at 88% for Large, 82% for Mid, 75% for Small

### **Extended Case (24-month target)**:
- Usually implies additional structural re-rating
- Example: LICI from 0.9x to 1.3-1.5x EV

---

## 🎯 15-STOCK PORTFOLIO COMPOSITION

### **By Market Cap:**
- **Large Cap (5)**: LIC, ITC, HZNL, TATACOMS, ICICIPRUME
- **Mid Cap (6)**: IGI, IRFC, CASTROL, CAMS, WAAREE, + (6th open slot)
- **Small Cap (5)**: SAATVIK, MSTC, ECORECYCL, OSWALP, WANBURY

### **By Theme:**
| Theme | Stocks | Rationale |
|-------|--------|-----------|
| Insurance/Wealth | LIC, ICICIPRUME | Decadal AUM growth |
| Conglomerate Arbitrage | ITC, CASTROL | De-rating + demerger|
| Manufacturing Capex | IRFC, OSWALP, WAAREE | PLI schemes |
| Digital/Commodity | TATACOMS, HZNL | Infrastructure moat |
| Quality-at-Discount | IGI, MSTC, ECORECYCL | ESG + formalisation |
| Micro-Cap Alpha | SAATVIK, WANBURY | 93-70% ROE surprise |

---

## 🚨 KEY SCORING PATTERNS TO REPLICATE FOR TRAQO 2

### **Red Flags (Avoid)**:
1. ❌ PE > 60x without >70% ROE
2. ❌ Negative 3M momentum on >40x PE
3. ❌ ROE <40% with PE >35x
4. ❌ Deteriorating asset efficiency

### **Green Flags (Prioritize)**:
1. ✅ ROE 40%+ with PE <30x (value-quality overlap)
2. ✅ Positive momentum + fundamental catalyst
3. ✅ Structural secular theme with 5+ year tailwind
4. ✅ Regulatory/government mandate behind growth
5. ✅ Revenue/EBITDA visibility from order books

---

## 📋 DATA FIELDS NEEDED FOR DAILY SCREENING

To replicate GS's methodology, you need **daily updates** of:

### **Fundamental Data**:
- ROE (Return on Equity)
- PE Ratio (Price-to-Earnings)
- EV/EBITDA (for mining, telecom)
- P/B Ratio (Price-to-Book)
- Debt-to-Equity
- Current Ratio / Quick Ratio
- Free Cash Flow
- EBITDA Margin
- Net Margin
- Asset Turnover

### **Momentum Data**:
- 1M, 3M, 6M price returns
- Volume trends
- Institutional buying/selling

### **Market Cap**:
- Segment classification (Large/Mid/Small)

### **Qualitative Overlay**:
- Government order visibility
- Sector momentum
- Analyst consensus (if available)

---

## 🔄 TRAQO 2 RECOMMENDED WORKFLOW

```
DAILY PROCESS:
├─ 9:15 AM: Fetch fundamental + momentum data from NSE/yfinance
├─ 10:00 AM: Run screening algorithm (GS composite)
│            └─ Apply Quality-Value-Momentum weights
│            └─ Filter by theme + market cap
├─ 11:00 AM: Rank by score, generate top 15-20
├─ 12:00 PM: Add qualitative overlays (catalysts, orders)
├─ 1:00 PM:  Generate Goldman Sachs-style report
│            ├─ Investment thesis per stock
│            ├─ Price targets (6M, 12M, 24M)
│            ├─ Bull/Bear ranges
│            └─ Portfolio construction role
└─ 4:00 PM:  Feed top 15 into TRAQO 1 (candlestick patterns)
             └─ Trade only from this filtered universe
```

---

## 💼 INTEGRATION WITH TRAQO 1

```
STAGE 1 (TRAQO 2 - Fundamental RAG)
├─ Input: Financial filters
├─ Output: Top 15-20 screened stocks (quality-value)
└─ ROE, PE, Catalysts logged to RAG

         ↓

STAGE 2 (TRAQO 1 - Pattern RAG)
├─ Input: Top 15-20 from Stage 1
├─ Pattern detection on curated universe
└─ Entry/Exit signals + risk management
```

### **Benefits**:
1. **Signal purity**: Only fundamental-quality stocks enter pattern detection
2. **Fewer false signals**: Patterns on strong fundamentals = higher win rate
3. **Better risk**: Stop-losses applied to quality, not speculative picks
4. **Explainability**: Why a stock + When to trade it

---

## 📊 SAMPLE OUTPUT FORMAT

```json
{
  "rank": 1,
  "symbol": "LIC",
  "company_name": "Life Insurance Corp of India",
  "theme": "Insurance Decadal Growth",
  "market_cap_segment": "Large Cap",
  "cmp": 842,
  "pe": 11.0,
  "roe": 45.9,
  "quality_score": 92,
  "value_score": 95,
  "momentum_score": 78,
  "composite_score": 90,
  "six_month_target": 1075,
  "twelve_month_target": 1265,
  "bull_case": 1417,
  "bear_case": 1114,
  "rating": "CONVICTION BUY",
  "investment_thesis": "India life insurance penetration 3.2% GDP vs 6.8% global. LIC 60%+ market share = singular vehicle for decadal convergence. Trades 0.9x EV vs peers 2-3x EV. Re-rating to 1.3-1.5x EV = 35-50% upside.",
  "catalyst": "EV disclosure maturity + analyst coverage post-listing",
  "risk_factors": ["Regulatory risk", "Competition from private players"],
  "portfolio_role": "Core defensive large-cap anchor position"
}
```

---

## 🎓 Key Takeaways for TRAQO 2 Design

1. **Use 6+ macroeconomic themes** to organize stocks (not random screening)
2. **Weight ROE 40%** - this is the foundation of long-term wealth creation
3. **PE-to-ROE mismatch** is your arbitrage source
4. **Momentum 15%** - timing matters, but only after fundamental quality
5. **Always provide 4-part thesis** - structural + valuation + catalyst + portfolio role
6. **Generate price targets** with methodology, not guesses
7. **Categorize by market cap** - different rules for large/mid/small
8. **Regulatory tailwinds** are gold (government mandates = revenue visibility)
9. **Vertical integration + pricing power** = sustainable ROE
10. **Information asymmetry** = re-rating opportunity (micro-caps overlooked)

---

## Next Steps
- Build `fundamental_screener.py` with GS methodology
- Create RAG documents for each theme
- Integrate with `paper_trader.py` Stage 1
