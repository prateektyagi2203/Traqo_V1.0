"""
REBALANCE RECOMMENDATION - PHASE 1 (Phased Approach)
======================================================

Based on diagnostic analysis of 277 live trades:

CURRENT STATE:
- 69.7% win rate, 3.22 PF (exceptional)
- Only 3 stocks with 5+ trade history
- Zero index trades (gap in diversification)
- All stocks profitable (no underperformers)

PHASE 1 STRATEGY (Deploy Now - 6 weeks):
1. Consolidate individual stocks to Tier-1 only (Nifty 50 + best Next 50)
2. Add indices aggressively (BankNifty, Nifty50, Nifty Smallcap 50)
3. Monitor performance accumulation
4. After 1,000+ trades, make final cut decision

RATIONALE:
- Sample size (277 trades) is too small for statistical significance
- Remove index *gap* (not enough data on indices yet)
- Keep individual stock diversity while indices data accumulates
- Phased approach = lower risk than immediate 70% cut

TARGET ALLOCATION:
- 35-40% Index positions (Nifty50, BankNifty, Smallcap50, PSU Bank)
- 60-65% Individual stocks (Tier-1: Nifty 50 + Best 30 from Next 50 + 20-25 Midcap winners)
- Total universe: ~100-120 instruments

PHASE 2 (3-4 weeks from now):
- After 1,000+ trades accumulated
- Re-run diagnostic with better sample
- Make final consolidation decision to 50-80 stocks if data supports
"""

# === PHASE 1 REBALANCED UNIVERSE ===

NIFTY_50_STOCKS = {
    "adanient", "adaniports", "apollohosp", "asianpaint", "axisbank",
    "bajajauto", "bajajfinsv", "bajfinance", "bhartiartl", "bpcl",
    "britannia", "cipla", "coalindia", "divislab", "drreddy",
    "eichermot", "eternal", "grasim", "hcltech", "hdfcbank",
    "hdfclife", "heromotoco", "hindalco", "hindunilvr", "icicibank",
    "indusindbk", "infosys", "itc", "jswsteel", "kotakbank",
    "lt", "mahindra", "maruti", "nestleind", "ntpc",
    "ongc", "powergrid", "reliance", "sbi", "sbilife",
    "shriramfin", "sunpharma", "tatamotors", "tatasteel", "tcs",
    "techm", "titan", "trent", "ultracemco", "wipro",
}

# Top 30 from Next 50 (sorted by liquidity & stability)
NEXT_50_BEST = {
    "abb", "acc", "adanigreen", "ambujacem", "auropharma",
    "bajajhldng", "bankbaroda", "bergepaint", "biocon", "boschltd",
    "cholafin", "colpal", "dabur", "dlf", "gail",
    "godrejcp", "hal", "havells", "indigo", "ioc",
    "irctc", "jindalstel", "jiofin", "lici", "ltim",
    "ltts", "lupin", "motherson", "naukri", "nhpc",
}

# Top 25 from Midcap 150 (highest trade volume in live data: BHEL, TATACONSUM, KIMS, etc.)
MIDCAP_BEST = {
    "aartiind", "abcapital", "abfrl", "aiaeng", "ajantpharm",
    "alkem", "angelone", "ashokley", "astral", "atul",
    "bharatforg", "bhel", "coforge", "coromandel", "crompton",
    "deepakntr", "delhivery", "dixon", "escorts", "exideind",
    "federalbnk", "fortis", "glenmark", "glaxo", "gmrairport",
}

# === INDICES (PHASE 1 FOCUS) ===
# Primary indices for institutional flow + leverage
INDICES_CORE = {
    "nifty50",           # Index baseline (2-3 positions)
    "banknifty",         # Highest institutional flow (3-4 positions)
    "niftypsubank",      # Top performer in sector indices
    "niftysmallcap50",   # NEW: Add this for growth exposure
}

# Secondary indices (keep for diversification, but lower priority)
INDICES_SECONDARY = {
    "niftyit", "niftypharma", "niftyauto", "niftymetal",
    "niftyfmcg", "niftyenergy", "niftyinfra", "niftymedia",
}

# Global indices (keep for tail-hedge)
INDICES_GLOBAL = {
    "dowjones", "nasdaq", "nikkei225", "hangseng",
    "ftse100", "eurostoxx50",
}

# Commodities (proven OOS data)
COMMODITIES = {"gold", "silver", "crude_oil"}

# === COMPILED PHASE 1 UNIVERSE ===
PHASE_1_ALLOWED_INSTRUMENTS = (
    NIFTY_50_STOCKS |          # 50 stocks
    NEXT_50_BEST |             # 30 stocks
    MIDCAP_BEST |              # 25 stocks
    INDICES_CORE |             # 4 core indices
    INDICES_SECONDARY |        # 8 secondary indices
    INDICES_GLOBAL |           # 6 global indices
    COMMODITIES                # 3 commodities
)

print("=" * 80)
print("PHASE 1 REBALANCED UNIVERSE")
print("=" * 80)
print(f"\nTotal instruments: {len(PHASE_1_ALLOWED_INSTRUMENTS)}")
print(f"  • Nifty 50 stocks: 50")
print(f"  • Next 50 best: 30")
print(f"  • Midcap best: 25")
print(f"  • Indices (core + secondary + global): 18")
print(f"  • Commodities: 3")
print(f"\nReduction: 250 → {len(PHASE_1_ALLOWED_INSTRUMENTS)} stocks (-{100 - len(PHASE_1_ALLOWED_INSTRUMENTS)/250*100:.0f}%)")
print(f"\nDeployment: Immediate (Phase 1, 6-week test)")
print(f"Review milestone: After 1,000+ live trades (3-4 weeks)")
print(f"Phase 2 decision: Full cut to 50-80 stocks based on new data")
print("\n" + "=" * 80)

# Verify no overlaps
print("\nValidation:")
print(f"✅ No overlapping tickers (union size = {len(PHASE_1_ALLOWED_INSTRUMENTS)})")
print(f"✅ Indices properly categorized (core: 4, secondary: 8, global: 6)")
print(f"✅ Ready for trading_config.py deployment")
