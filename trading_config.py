"""
Trading Configuration — Centralized Production Filters
========================================================
All production-level filters in one place. Every module (statistical_predictor,
backtest_walkforward, backtest_ab, app_ollama) imports from here.

Based on walk-forward OOS analysis (2024-2025 test, 2016-2023 train):
  - 15-min timeframe: PF 0.79 → DROPPED
  - FX / poor instruments: PF 0.28-0.47 → DROPPED
  - Tier_4 predictions: PF 0.79 → REJECTED
  - 8 profitable patterns whitelisted, 6 harmful patterns excluded
  - Daily timeframe + good patterns: PF 1.19, 3,103 trades

Updates (March 2026):
  - OOS retest reveals market regime change since Feb 24
  - doji: 0.41 → 3.41 PF (exceptional out-of-sample)
  - stick_sandwich: newly added to whitelist
  - three_inside_up: re-evaluated (1.16 PF test, monitor status)

Change log:
  2026-03-XX  OOS retest on 17 untested patterns — 4 promotions
  2026-02-24  Initial production config based on OOS diagnostics
"""

# ============================================================
# ITEM 1: TIMEFRAME FILTER
# ============================================================
# 15-min patterns are near-random noise (OOS PF 0.79, -1,686% total return).
# Configurable: add "15min" back if intraday signal quality improves.
ALLOWED_TIMEFRAMES = {"daily"}


# ============================================================
# ITEM 1b: DIRECTION FILTER (Cash Equity)
# ============================================================
# Indian cash equity segment does NOT allow overnight short positions.
# BEARISH signals are only actionable intraday or in F&O.
# Set to {"BULLISH"} for cash-only trading; add "BEARISH" if trading F&O.
ALLOWED_DIRECTIONS = {"BULLISH"}


# ============================================================
# ITEM 2: INSTRUMENT UNIVERSE
# ============================================================
# Only trade instruments with proven OOS edge.
# FX pairs (eurusd, usdinr, dxy) destroy performance (PF 0.28-0.47).
# Crypto/commodity instruments without enough training data excluded.

# Indian equities + major global indices that showed OOS PF > 0.9
# Expanded to Top 250 NSE stocks (Feb 2026)
ALLOWED_INSTRUMENTS = {
    # --- Indian Equities: Nifty 50 (50 stocks) ---
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

    # --- Indian Equities: Nifty Next 50 (50 stocks) ---
    "abb", "acc", "adanigreen", "adanipower", "ambujacem",
    "atgl", "auropharma", "bajajhldng", "bankbaroda", "bel",
    "bergepaint", "biocon", "boschltd", "canbk", "cholafin",
    "colpal", "dabur", "dlf", "gail", "godrejcp",
    "hal", "havells", "icicipruli", "indigo", "ioc",
    "irctc", "irfc", "jindalstel", "jiofin", "lici",
    "ltim", "ltts", "lupin", "maxhealth", "motherson",
    "naukri", "nhpc", "oberoirlty", "ofss", "paytm",
    "pfc", "pidilitind", "pnb", "polycab", "recltd",
    "sbicard", "siemens", "srf", "tataconsum", "tatapower",

    # --- Indian Equities: Nifty Midcap 150 (148 stocks) ---
    "aartiind", "abcapital", "abfrl", "aiaeng", "ajantpharm",
    "alkem", "angelone", "aplapollo", "aplltd", "ashokley",
    "astral", "atul", "aubank", "balkrisind", "bankindia",
    "bataindia", "bharatforg", "bhel", "bse", "canfinhome",
    "carboruniv", "castrolind", "cdsl", "cesc", "cgpower",
    "chamblfert", "clean", "cochinship", "coforge", "coromandel",
    "crompton", "cub", "cumminsind", "cyient", "dalbharat",
    "deepakntr", "delhivery", "devyani", "dixon", "emamiltd",
    "endurance", "escorts", "exideind", "fact", "federalbnk",
    "fineorg", "fluorochem", "fortis", "gillette", "glenmark",
    "glaxo", "gmrairport", "gnfc", "godrejind", "godrejprop",
    "granules", "graphite", "grindwell", "gujgasltd", "hatsun",
    "hindpetro", "hindzinc", "honaut", "hudco", "idfcfirstb", "iex", "iifl",
    "indianb", "indianhotels", "indiamart", "industower", "intellect",
    "ipcalab", "jkcement", "jswenergy", "jswinfra", "jublfood",
    "kalyankjil", "kei", "kims", "kpittech", "lalpathlab",
    "lauruslabs", "lichsgfin", "manappuram", "mankind", "marico",
    "mazdock", "metrobrand", "mfsl", "mgl", "mphasis",
    "mrf", "muthootfin", "namindia", "natcopharm", "navinfluor",
    "nmdc", "oil", "pageind", "patanjali", "persistent",
    "petronet", "pghh", "phoenixltd", "piind", "polymed",
    "poonawalla", "prestige", "pvrinox", "radico", "rain",
    "rajeshexpo", "ramcocem", "ratnamani", "rblbank", "sail",
    "schaeffler", "shreecem", "sonacoms", "starhealth", "sumichem",
    "sundarmfin", "sundrmfast", "sunteck", "suntv", "supremeind",
    "syngene", "tatachem", "tatacomm", "tataelxsi", "tatatech",
    "tiindia", "timken", "torntpharm", "torntpower", "trident",
    "tvsmotor", "ubl", "unionbank", "unitdspr", "upl",
    "vbl", "vedl", "voltas", "whirlpool", "yesbank",
    "zeel", "zyduslife", "3mindia",

    # --- Indian Indices ---
    "nifty50", "banknifty", "niftyit", "niftypharma",
    "niftyauto", "niftymetal", "niftyfmcg", "niftyenergy",
    "niftyinfra", "niftymedia", "niftypsubank", "niftyrealty",
    # --- Global Indices (with sufficient cross-market data) ---
    "dowjones", "nasdaq", "nikkei225", "hangseng",
    "ftse100", "eurostoxx50",
    # --- Commodities (proven OOS) ---
    "gold", "silver", "crude_oil",
}

# Safety guard: prevent accidental consolidation of production universe.
# Baseline is the pre-consolidation production scope.
MIN_ALLOWED_INSTRUMENTS = 269
if len(ALLOWED_INSTRUMENTS) < MIN_ALLOWED_INSTRUMENTS:
    raise ValueError(
        f"ALLOWED_INSTRUMENTS shrank to {len(ALLOWED_INSTRUMENTS)}; "
        f"minimum required is {MIN_ALLOWED_INSTRUMENTS}."
    )

# Instruments to always exclude (inverse/VIX move oppositely to stocks)
EXCLUDED_INSTRUMENTS = {"vix", "indiavix"}

# FX pairs explicitly excluded (OOS PF 0.28-0.47)
EXCLUDED_FX = {"eurusd", "usdinr", "dxy"}


# ============================================================
# ITEM 3: PATTERN FILTERS
# ============================================================
# Patterns with historically negative edge (PF < 0.5) — never trade
EXCLUDED_PATTERNS = {
    "hanging_man",        # PF 0.34
    # "doji",             # PROMOTED: PF 0.41 (old) → 3.41 (OOS 2024-2025)
    "three_outside_up",   # PF 0.26 (still underperforming: 1.06 test PF)
    # "three_inside_up",  # Re-evaluated: 1.16 PF test (monitor status)
    "three_outside_down", # PF 0.15
    "bearish_harami",     # PF 0.42
}

# Patterns whitelisted based on OOS profitability (PF > 1.0 out-of-sample)
# Only these patterns generate a trade signal.
# Other patterns → neutral (no trade).
WHITELISTED_PATTERNS = {
    "belt_hold_bullish",
    "bullish_counterattack",
    "bullish_harami",
    "bullish_kicker",
    "doji",               # NEWLY PROMOTED: OOS test 3.41 PF, 62.4% win%
    "dragonfly_doji",
    "hammer",
    "harami_cross",
    "homing_pigeon",
    "inverted_hammer",
    "mat_hold",
    "matching_low",
    "rising_three_methods",
    "separating_lines",
    "stick_sandwich",     # NEWLY PROMOTED: OOS test 1.39 PF, 54.0% win%
    "three_black_crows",
    "three_inside_down",
    "three_inside_up",    # Re-added: OOS test 1.16 PF (monitor threshold)
    "three_stars_south",
    "tri_star_bullish",
    "unique_three_river",
    # CIO PATTERN PROMOTIONS (OOS-validated dormant patterns)
    "morning_doji_star",   # OOS 1.19 PF, 49.1% WR, 277 trades — institutional gap-down indecision signal
    "tweezer_bottom",      # OOS 1.04 PF, 47.1% WR, 635 trades — support exhaustion, reversion to mean
    "long_legged_doji",    # OOS 1.05 PF, 49.2% WR, high-volatility indecision breakout signal
}

# Tier A patterns: high-PF patterns where tight SL kills winners
# Use structural (wider) stop-loss — 2.0x ATR instead of 1.5x
STRUCTURAL_SL_PATTERNS = {
    "bullish_harami",      # PF 2.31 → SL below mother candle
    "belt_hold_bearish",   # PF 1.93 → SL above belt candle open
    "bullish_kicker",      # PF 1.58 → strong reversal needs room
    "ladder_bottom",       # PF 1.57 → multi-candle pattern
    "mat_hold",            # PF 1.70 → continuation pattern
}

# Patterns valid only in bullish regime (continuation signals require trend context)
# These patterns have edge only when market trend_short == "bullish"
PATTERN_BULL_REGIME_ONLY = {
    "rising_three_methods",  # Bullish continuation: three small candles pause inside two larger bullish candles
}

# ============================================================
# PER-HORIZON PATTERN WHITELIST
# ============================================================
# Some patterns work better at specific holding periods.
# If a horizon is not listed, falls back to the flat WHITELISTED_PATTERNS.
HORIZON_PATTERN_WHITELIST = {
    "BTST_1d": {
        # Fast reversal patterns that resolve in 1 day
        "hammer", "bullish_kicker", "belt_hold_bullish",
        "harami_cross", "homing_pigeon",
    },
    "Swing_3d": {
        # Short swing — classic reversal & continuation
        "hammer", "three_black_crows", "bullish_kicker",
        "belt_hold_bullish", "homing_pigeon", "harami_cross",
        "three_inside_down",
    },
    "Swing_5d": WHITELISTED_PATTERNS,  # Primary horizon: use full whitelist
    "Swing_10d": {
        # Medium swing — multi-candle patterns that need time
        "three_black_crows", "rising_three_methods", "bullish_kicker",
        "belt_hold_bullish", "homing_pigeon", "three_inside_down",
        "harami_cross", "hammer",
    },
    # Swing_25d removed from scope
}

# Per-horizon allowed tiers (shorter horizons need higher-quality matches)
HORIZON_ALLOWED_TIERS = {
    "BTST_1d":   {"tier_1"},                    # BTST: only top tier
    "Swing_3d":  {"tier_1", "tier_2"},           # Short swing: top 2 tiers
    "Swing_5d":  {"tier_1", "tier_2"},           # Primary: default
    "Swing_10d": {"tier_1", "tier_2"},           # Medium swing
    # Swing_25d removed from scope
}


# ============================================================
# ITEM 4: TIER / CONFIDENCE FILTERS
# ============================================================
# Tier_4 (pattern-only match) has OOS PF 0.79 → reject.
# Tier_1 OOS PF 0.96, Tier_2 ~0.9 — accept tier_1 and tier_2 only.
ALLOWED_TIERS = {"tier_1", "tier_2"}

# NEW (Improvement #2): Allow tier_3 in ensemble signals only
# Tier_3 (pattern + timeframe) with 2+ patterns + confidence penalty
ALLOWED_TIERS_ENSEMBLE = {"tier_1", "tier_2", "tier_3"}  # tier_3 allowed in ensembles
ENSEMBLE_TIER3_CONFIDENCE_PENALTY = 0.5  # Halve confidence for tier_3 members
MIN_ENSEMBLE_PATTERNS = 2  # Need at least 2 patterns to allow tier_3

# Minimum match threshold (lowered from 10 to improve tier_1/tier_2 hit rate)
MIN_MATCHES = 5

# Top-K matches to use for prediction
TOP_K = 50

# Maximum matches from any single instrument
MAX_PER_INSTRUMENT = 5

# Primary prediction horizon (candles)
PRIMARY_HORIZON = 5


# ============================================================
# STOP-LOSS CONFIGURATION
# ============================================================
STRUCTURAL_SL_MULTIPLIER = 2.0   # Tier A: wider SL for high-PF patterns
STANDARD_SL_MULTIPLIER = 1.5     # Tier B: default
SL_FLOOR_PCT = 0.3               # minimum SL (prevents over-tight)
SL_CAP_PCT = 5.0                 # maximum SL (prevents absurdly wide)

# Per-horizon SL scaling (mirrors paper_trader.py HORIZON_CONFIG)
# sl_mult_scale: multiplied with the base SL multiplier
# sl_cap: max SL% for that horizon
# rr_min: minimum reward-to-risk ratio required
HORIZON_SL_CONFIG = {
    1:  {"sl_mult_scale": 0.7,  "sl_cap": 2.5, "rr_min": 1.5},
    3:  {"sl_mult_scale": 0.8,  "sl_cap": 3.5, "rr_min": 1.8},
    5:  {"sl_mult_scale": 1.0,  "sl_cap": 5.0, "rr_min": 2.0},
    10: {"sl_mult_scale": 1.2,  "sl_cap": 5.0, "rr_min": 2.0},
    # 25d removed from scope
}

# Horizons disabled in production (PF < 1.0 OOS after costs)
# Set to empty to enable all horizons.
DISABLED_HORIZONS = frozenset()  # 25d fully removed from scope — not relevant to RAG analysis


# ============================================================
# TRADING COST MODEL
# ============================================================
# Indian intraday: ~0.05% round-trip
# Covers brokerage + STT + exchange txn + GST + stamp duty + SEBI turnover
SLIPPAGE_COMMISSION_PCT = 0.05


# ============================================================
# PRODUCTION FILTERS (R3: unified for backtest & paper_trader)
# ============================================================
# These must be used identically in both backtest_walkforward.py and
# paper_trader.py so that OOS results predict live performance.
PRODUCTION_FILTERS = {
    "min_win_rate": 45.0,       # minimum predicted win rate %
    "min_confidence": "MEDIUM", # minimum confidence level
    "min_rr_ratio": 1.5,       # minimum reward-to-risk
    "min_edge_pct": 8.5,       # minimum absolute edge %
}

# Per-horizon edge thresholds (R4: longer horizons need bigger edge)
# Replaces the flat 3% neutral zone.
HORIZON_EDGE_THRESHOLDS = {
    1:  {"neutral_zone": 2.0, "prod_min_edge": 6.0},   # BTST: fast, small edge OK
    3:  {"neutral_zone": 2.5, "prod_min_edge": 7.0},
    5:  {"neutral_zone": 3.0, "prod_min_edge": 8.5},   # Primary horizon (baseline)
    10: {"neutral_zone": 4.0, "prod_min_edge": 10.0},  # Needs more edge to cover noise
    25: {"neutral_zone": 5.0, "prod_min_edge": 12.0},  # Highest bar
}


# ============================================================
# ITEM 8: POSITION SIZING (Kelly Criterion)
# ============================================================
# Kelly fraction = (win_rate * avg_win / avg_loss - (1 - win_rate)) / (avg_win / avg_loss)
# We use fractional Kelly (half-Kelly) for safety.
KELLY_FRACTION = 0.5              # Use half-Kelly for safety
MAX_POSITION_PCT = 3.0            # Max 3% of capital per trade (was 5% — too aggressive)
MIN_POSITION_PCT = 0.5            # Min 0.5% of capital per trade
DEFAULT_CAPITAL = 1_000_000       # Default ₹10L capital for sizing


# ============================================================
# ITEM 9: KILL SWITCHES & CIRCUIT BREAKERS
# ============================================================
MAX_DAILY_LOSS_PCT = 2.0          # Stop trading if daily loss > 2%
MAX_CONSECUTIVE_LOSSES = 5        # Pause after 5 consecutive losses
MAX_DRAWDOWN_PCT = 10.0           # Kill switch: stop all trading if DD > 10%
MAX_MONTHLY_LOSS_PCT = 5.0        # Stop trading if monthly loss > 5%
MAX_DAILY_TRADES = 10             # Max trades per day
COOLDOWN_AFTER_KILL_MINUTES = 60  # Cooldown period after circuit breaker trips


# ============================================================
# ITEM 10: PAPER TRADING
# ============================================================
PAPER_TRADE_LOG = "paper_trades/trade_log.json"
PAPER_TRADE_CAPITAL = 1_000_000   # ₹10L paper capital
MAX_CONCURRENT_POSITIONS = 10     # Max simultaneous open positions


# ============================================================
# SECTOR CLASSIFICATION & CORRELATION LIMITS
# ============================================================
# Max positions from the same sector (prevents correlated blowup)
MAX_POSITIONS_PER_SECTOR = 2

INSTRUMENT_SECTORS = {
    # --- Banking / BFSI ---
    "axisbank": "banking", "hdfcbank": "banking", "icicibank": "banking",
    "kotakbank": "banking", "sbi": "banking", "banknifty": "banking",
    "niftypsubank": "banking", "indusindbk": "banking", "bankbaroda": "banking",
    "canbk": "banking", "pnb": "banking", "idfcfirstb": "banking",
    "federalbnk": "banking", "aubank": "banking", "cub": "banking",
    "indianb": "banking", "rblbank": "banking", "yesbank": "banking",
    "bankindia": "banking", "unionbank": "banking",
    # --- NBFC / Financial Services ---
    "bajfinance": "finance", "bajajfinsv": "finance", "bajajhldng": "finance",
    "cholafin": "finance", "muthootfin": "finance", "shriramfin": "finance",
    "hdfclife": "finance", "sbilife": "finance", "sbicard": "finance",
    "icicipruli": "finance", "lici": "finance", "pfc": "finance",
    "recltd": "finance", "irfc": "finance", "jiofin": "finance",
    "abcapital": "finance", "canfinhome": "finance", "lichsgfin": "finance",
    "manappuram": "finance", "mfsl": "finance", "angelone": "finance",
    "starhealth": "finance", "sundarmfin": "finance", "namindia": "finance",
    "poonawalla": "finance", "cdsl": "finance", "bse": "finance",
    "iifl": "finance",
    # --- IT ---
    "hcltech": "it", "infosys": "it", "tcs": "it", "wipro": "it",
    "niftyit": "it", "techm": "it", "ltim": "it", "ltts": "it",
    "persistent": "it", "coforge": "it", "mphasis": "it", "naukri": "it",
    "ofss": "it", "cyient": "it", "kpittech": "it", "tataelxsi": "it",
    "intellect": "it", "indiamart": "it", "tatatech": "it",
    # --- Auto ---
    "maruti": "auto", "tatamotors": "auto", "niftyauto": "auto",
    "bajajauto": "auto", "eichermot": "auto", "heromotoco": "auto",
    "mahindra": "auto", "tvsmotor": "auto", "ashokley": "auto",
    "escorts": "auto", "motherson": "auto", "boschltd": "auto",
    "balkrisind": "auto", "endurance": "auto", "exideind": "auto",
    "mrf": "auto", "schaeffler": "auto", "sonacoms": "auto",
    "sundrmfast": "auto", "bharatforg": "auto",
    # --- Metals / Mining ---
    "tatasteel": "metals", "niftymetal": "metals", "jswsteel": "metals",
    "hindalco": "metals", "jindalstel": "metals", "vedl": "metals",
    "nmdc": "metals", "sail": "metals", "coalindia": "metals",
    # --- FMCG ---
    "hindunilvr": "fmcg", "itc": "fmcg", "niftyfmcg": "fmcg",
    "nestleind": "fmcg", "britannia": "fmcg", "colpal": "fmcg",
    "dabur": "fmcg", "godrejcp": "fmcg", "marico": "fmcg",
    "emamiltd": "fmcg", "hatsun": "fmcg", "vbl": "fmcg",
    "rajeshexpo": "fmcg", "gillette": "fmcg", "pghh": "fmcg",
    "patanjali": "fmcg",
    # --- Pharma / Healthcare ---
    "sunpharma": "pharma", "niftypharma": "pharma", "cipla": "pharma",
    "drreddy": "pharma", "divislab": "pharma", "apollohosp": "pharma",
    "auropharma": "pharma", "biocon": "pharma", "lupin": "pharma",
    "alkem": "pharma", "torntpharm": "pharma", "ipcalab": "pharma",
    "glenmark": "pharma", "glaxo": "pharma", "lauruslabs": "pharma",
    "natcopharm": "pharma", "zyduslife": "pharma", "syngene": "pharma",
    "granules": "pharma", "ajantpharm": "pharma", "aplltd": "pharma",
    "lalpathlab": "pharma", "mankind": "pharma",
    "fortis": "pharma", "maxhealth": "pharma", "kims": "pharma",
    # --- Telecom ---
    "bhartiartl": "telecom", "industower": "telecom", "tatacomm": "telecom",
    # --- Energy / Oil & Gas ---
    "reliance": "energy", "niftyenergy": "energy", "crude_oil": "energy",
    "bpcl": "energy", "ongc": "energy", "ioc": "energy", "gail": "energy",
    "ntpc": "energy", "powergrid": "energy", "adanigreen": "energy",
    "adanipower": "energy", "tatapower": "energy", "nhpc": "energy",
    "atgl": "energy", "oil": "energy", "petronet": "energy",
    "hindpetro": "energy", "gujgasltd": "energy", "mgl": "energy",
    "castrolind": "energy", "cesc": "energy", "jswenergy": "energy",
    "torntpower": "energy",
    # --- Chemicals ---
    "aartiind": "chemicals", "pidilitind": "chemicals", "srf": "chemicals",
    "bergepaint": "chemicals", "deepakntr": "chemicals", "piind": "chemicals",
    "navinfluor": "chemicals", "fluorochem": "chemicals", "atul": "chemicals",
    "chamblfert": "chemicals", "coromandel": "chemicals", "clean": "chemicals",
    "fineorg": "chemicals", "gnfc": "chemicals", "sumichem": "chemicals",
    "tatachem": "chemicals", "upl": "chemicals", "fact": "chemicals",
    "rain": "chemicals", "graphite": "chemicals",
    # --- Capital Goods / Engineering ---
    "lt": "capital_goods", "abb": "capital_goods", "siemens": "capital_goods",
    "havells": "capital_goods", "polycab": "capital_goods", "bhel": "capital_goods",
    "cgpower": "capital_goods", "cumminsind": "capital_goods",
    "aplapollo": "capital_goods", "astral": "capital_goods",
    "honaut": "capital_goods", "timken": "capital_goods",
    "carboruniv": "capital_goods", "grindwell": "capital_goods",
    "kei": "capital_goods", "iex": "capital_goods",
    "ratnamani": "capital_goods", "supremeind": "capital_goods",
    "tiindia": "capital_goods", "aiaeng": "capital_goods",
    "crompton": "capital_goods",
    # --- Cement ---
    "ultracemco": "cement", "acc": "cement", "ambujacem": "cement",
    "shreecem": "cement", "dalbharat": "cement", "jkcement": "cement",
    "ramcocem": "cement",
    # --- Infra / Conglomerate ---
    "adanient": "infra", "niftyinfra": "infra", "adaniports": "infra",
    "grasim": "infra", "gmrairport": "infra", "jswinfra": "infra",
    # --- Realty ---
    "dlf": "realty", "oberoirlty": "realty", "godrejprop": "realty",
    "prestige": "realty", "phoenixltd": "realty", "niftyrealty": "realty",
    "sunteck": "realty",
    # --- Consumer Durables / Retail ---
    "titan": "consumer", "trent": "consumer", "bataindia": "consumer",
    "pageind": "consumer", "asianpaint": "consumer", "dixon": "consumer",
    "voltas": "consumer", "whirlpool": "consumer", "metrobrand": "consumer",
    "abfrl": "consumer", "kalyankjil": "consumer",
    # --- Defence ---
    "hal": "defence", "bel": "defence", "cochinship": "defence",
    "mazdock": "defence",
    # --- Media ---
    "niftymedia": "media", "suntv": "media", "zeel": "media",
    "pvrinox": "media",
    # --- Consumer Tech / Services ---
    "eternal": "consumer_tech", "paytm": "consumer_tech",
    "irctc": "consumer_tech", "indigo": "consumer_tech",
    "jublfood": "consumer_tech",
    "devyani": "consumer_tech", "indianhotels": "consumer_tech",
    # --- Logistics ---
    "delhivery": "logistics",
    # --- Textiles ---
    "trident": "textiles",
    # --- Diversified ---
    "godrejind": "diversified", "3mindia": "diversified",
    "polymed": "diversified", "radico": "diversified",
    "ubl": "diversified", "unitdspr": "diversified",
    # --- Indian Indices (broad) ---
    "nifty50": "index_in",
    # --- Global Indices ---
    "dowjones": "index_us", "nasdaq": "index_us",
    "nikkei225": "index_asia", "hangseng": "index_asia",
    "ftse100": "index_eu", "eurostoxx50": "index_eu",
    # --- Commodities ---
    "gold": "commodity", "silver": "commodity",
}


# ============================================================
# ENTRY / EXIT TIMING
# ============================================================
# All signals generated after market close using daily candle data.
# Entry at next day's open (market order within first 5 minutes).
# Exit conditions (whichever comes first):
#   1. Stop-loss hit (intraday monitoring)
#   2. Target hit (MFE-based)
#   3. Time exit: 5 trading days after entry
ENTRY_TIMING = "next_day_open"    # Enter at next trading day's market open
EXIT_HORIZON_DAYS = 5             # Max hold period = 5 trading days
EXIT_PRIORITY = ["stop_loss", "target", "time_exit"]  # Exit priority order


# ============================================================
# ALERTING & LOGGING
# ============================================================
ALERT_LOG_DIR = "logs"
TRADE_LOG_FILE = "logs/trade_log.jsonl"      # Append-only trade audit trail
SYSTEM_LOG_FILE = "logs/system.log"          # System events, errors, breakers

# Telegram alerts (set your bot token and chat ID to enable)
# Create a bot via @BotFather on Telegram, get the token.
# Send a message to your bot, then visit:
#   https://api.telegram.org/bot<TOKEN>/getUpdates
# to find your chat_id.
TELEGRAM_BOT_TOKEN = ""           # e.g. "7123456789:AAH..."
TELEGRAM_CHAT_ID = ""             # e.g. "123456789"
ALERT_ON_SIGNAL = True             # Alert on new trade signals
ALERT_ON_EXIT = True               # Alert on trade exits
ALERT_ON_BREAKER = True            # Alert on circuit breaker trips


# ============================================================
# REGIME DETECTION
# ============================================================
# Nifty 50 200-DMA regime: avoid heavy long exposure below 200 DMA.
# VIX-based regime: high VIX (>20) → reduce position sizes.
REGIME_INDEX = "nifty50"           # Index to check for regime
REGIME_DMA_PERIOD = 200            # 200-day moving average
VIX_INSTRUMENT = "indiavix"        # VIX instrument for volatility regime
VIX_HIGH_THRESHOLD = 20.0          # VIX > 20 = high volatility regime
VIX_EXTREME_THRESHOLD = 30.0       # VIX > 30 = extreme volatility
REGIME_POSITION_SCALE = {          # Scale position size by regime
    "bull_low_vol": 1.0,           # Above 200DMA + VIX < 20
    "bull_high_vol": 0.7,          # Above 200DMA + VIX >= 20
    "bear_low_vol": 0.5,           # Below 200DMA + VIX < 20
    "bear_high_vol": 0.3,          # Below 200DMA + VIX >= 20
    "extreme": 0.0,                # VIX > 30 — no trading
}


# ============================================================
# ITEM 9b: GLOBAL BEARISH SENTIMENT THRESHOLDS
# ============================================================
# Pre-market and intraday bearish sentiment monitoring.
# Based on Jefferies institutional practice (June 2026 analysis).

BEARISH_SCORE_RED_ALERT = 70           # Liquidate all BTST positions
BEARISH_SCORE_YELLOW_ALERT = 40        # Trim 30%, tighten SL 25%
BEARISH_SCORE_NSE_GAP_THRESHOLD = -0.75  # NSE gap-down threshold for trim gate
BEARISH_SCORE_ENTRY_DELTA_TRIM = 25    # Trim if intraday score worsens by 25+ pts

TRIM_BTST_PERCENTAGE = 30              # % of BTST position to trim on yellow/red
TRIM_SWING_PERCENTAGE = 50             # % of Swing to trim if ever enabled
TIGHTEN_SL_YELLOW_ALERT = 0.25         # Tighten SL by 25% on yellow alert
TIGHTEN_SL_RED_ALERT = 0.35            # Tighten SL by 35% on red alert

MONITOR_PRICE_INTERVAL_MINUTES = 1     # Intraday bearish check frequency
STORE_DECISION_PRICE_AS = "HIGH"       # Use HIGH of minute candle for decisions
EXECUTE_RETROACTIVE_TRIMS = True       # Execute pending trims on startup

# ============================================================
# ITEM 9c: INTRADAY EARLY-EXIT (DEAD TRADE DETECTION)
# ============================================================
# BTST_1d positions that are red + weak trajectory past cutoff time.
# Retroactive execution: laptop offline? Execute at stored decision-time price.

EARLY_EXIT_CUTOFF_TIME = "13:30"       # 1:30 PM IST cutoff
EARLY_EXIT_PRICE_THRESHOLD = -0.5      # Below -0.5% triggers exit
EARLY_EXIT_TRAJECTORY_MAX = 40         # Trajectory score <= 40 (CRITICAL/WEAK)
EARLY_EXIT_POLL_MINUTES = 5            # Poll every 5 min during market hours
EXIT_FULL_POSITION = True              # Exit 100% (not partial trim)
EXECUTE_RETROACTIVE_EXITS = True       # Execute pending exits on startup

# ============================================================
# ITEM 9e: MINUTE-LEVEL REPLAY ENGINE (OFFLINE RECOVERY)
# ============================================================
# When laptop is closed for up to 5 trading days, replays all intraday
# exit/trim logic against 1-minute OHLC data on next startup.
# yfinance 1m data limit: last 5 trading days (~7 calendar days).

NIFTY_CRASH_TRIM_THRESHOLD  = -1.5   # Nifty% from 9:15 day open → log 30% trim
NIFTY_CRASH_EXIT_THRESHOLD  = -2.5   # Nifty% from 9:15 day open → log 100% exit
MINUTE_REPLAY_MAX_DAYS_BACK = 5      # Max trading days to replay (yfinance 1m limit)
MINUTE_REPLAY_ENABLED       = True   # Master switch — set False to disable entirely

# ============================================================
# ITEM 9f: INDIA VIX
# ============================================================
INDIA_VIX_HIGH_THRESHOLD    = 16     # India VIX > 16 → growing fear
INDIA_VIX_PANIC_THRESHOLD   = 25     # India VIX > 25 → panic territory

# ============================================================
# ITEM 9g: NSE CIRCUIT BREAKER
# ============================================================
NSE_CIRCUIT_BREAKER_DROP    = -10.0  # Nifty intraday drop % that signals L1 circuit

# ============================================================
# ITEM 9d: SHORT_1d — 1-DAY INTRADAY SHORT SELLING
# ============================================================
# India allows intraday short selling in cash equity (sell today, buy back same day).
# SHORT_1d runs PARALLEL to BTST_1d but in bearish direction.
#
# Two deployment gates (both must pass):
#   Gate 1 — Profit-exit raised to +1.5% so winners aren't capped too early
#   Gate 2 — RED_ALERT gate: only enter SHORT if global bearish score >= 70
#
# Retroactive execution: force-close at 15:15 IST stored to bearish_trim_decisions
# table with reason "Short-force-close". Executed on next startup like trims.

SHORT_1D_ENABLED              = True    # Master switch for SHORT_1d horizon
SHORT_1D_SL_MULTIPLIER        = 1.1     # ATR multiplier for SL (above entry)
SHORT_1D_RR_RATIO             = 2.0     # 2:1 R:R — TP = SL_dist * 2.0 below entry
SHORT_1D_CONFIDENCE_MIN       = 0.60    # 60% confidence threshold (higher than BTST longs)
SHORT_1D_PROFIT_EXIT_PCT      = 1.5     # Lock in at +1.5% (backtest showed +0.5% caps wins)
SHORT_1D_FORCE_CLOSE_TIME     = "15:15" # Force-close all shorts at 3:15 PM IST
SHORT_1D_RED_ALERT_GATE       = True    # GATE 2: Only SHORT when global sentiment >= RED_ALERT
SHORT_1D_MIN_BEARISH_SCORE    = BEARISH_SCORE_RED_ALERT  # Default: 70 (RED_ALERT)
SHORT_1D_SHADOW_TRACKING      = True    # Track filtered shorts as shadow trades
SHORT_1D_MAX_POSITIONS        = 3       # Max concurrent SHORT_1d positions
EXECUTE_RETROACTIVE_SHORT_CLOSE = True  # Execute pending short force-closes on startup

# Bearish patterns eligible for SHORT_1d (subset from pattern_detector._BEARISH_REVERSAL)
# Only high-reliability patterns; add more as feedback data accumulates
SHORT_1D_ELIGIBLE_PATTERNS = {
    "bearish_engulfing", "three_black_crows", "evening_star", "evening_doji_star",
    "dark_cloud_cover", "shooting_star", "bearish_harami", "tweezer_top",
    "bearish_kicker", "gravestone_doji", "advance_block", "bearish_counterattack",
    "three_inside_down", "three_outside_down",
    "falling_three_methods",  # CIO: Bearish continuation — downtrend pause signals resume; short confirmation
}


# ============================================================
# ITEM 5: ML CLASSIFIER CONFIG
# ============================================================
ML_MODEL_PATH = "models/xgb_classifier.pkl"
ML_FEATURE_COLS = [
    "rsi_14", "atr_14_pct", "vol_ratio", "trend_short_encoded",
    "rsi_zone_encoded", "price_vs_vwap_encoded", "pattern_encoded",
    "hour_of_day", "day_of_week", "body_pct", "upper_shadow_pct",
    "lower_shadow_pct", "gap_pct",
]
ML_MIN_TRAIN_SAMPLES = 1000
ML_RETRAIN_INTERVAL_DAYS = 30


# ============================================================
# VALIDATION HELPERS
# ============================================================

def is_tradeable_instrument(instrument: str) -> bool:
    """Check if an instrument is in the allowed universe."""
    if instrument in EXCLUDED_INSTRUMENTS:
        return False
    if instrument in EXCLUDED_FX:
        return False
    return instrument in ALLOWED_INSTRUMENTS


def is_tradeable_timeframe(timeframe: str) -> bool:
    """Check if a timeframe is allowed for trading."""
    return timeframe in ALLOWED_TIMEFRAMES


def is_tradeable_pattern(pattern: str) -> bool:
    """Check if a pattern is in the whitelist and not excluded."""
    if pattern in EXCLUDED_PATTERNS:
        return False
    return pattern in WHITELISTED_PATTERNS


def is_tradeable_tier(tier: str) -> bool:
    """Check if a match tier is acceptable for production.
    Tier names may have suffixes (e.g., tier_1_exact, tier_2_relax_rsi_vwap).
    We check the prefix."""
    for allowed in ALLOWED_TIERS:
        if tier.startswith(allowed):
            return True
    return False


def get_sl_multiplier(patterns: set) -> float:
    """Return the appropriate SL multiplier for a set of patterns."""
    if patterns & STRUCTURAL_SL_PATTERNS:
        return STRUCTURAL_SL_MULTIPLIER
    return STANDARD_SL_MULTIPLIER


def filter_doc_for_trading(doc: dict) -> bool:
    """Full production filter: is this doc eligible for a trade signal?
    Returns True if the doc passes ALL filters."""
    # Instrument filter
    instrument = doc.get("instrument", "")
    if not is_tradeable_instrument(instrument):
        return False

    # Timeframe filter
    timeframe = doc.get("timeframe", "")
    if not is_tradeable_timeframe(timeframe):
        return False

    # Pattern filter (at least one whitelisted pattern)
    patterns = [p.strip() for p in doc.get("patterns", "").split(",") if p.strip()]
    if not any(is_tradeable_pattern(p) for p in patterns):
        return False

    return True
