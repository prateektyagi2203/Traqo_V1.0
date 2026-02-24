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

Change log:
  2026-02-24  Initial production config based on OOS diagnostics
"""

# ============================================================
# ITEM 1: TIMEFRAME FILTER
# ============================================================
# 15-min patterns are near-random noise (OOS PF 0.79, -1,686% total return).
# Configurable: add "15min" back if intraday signal quality improves.
ALLOWED_TIMEFRAMES = {"daily"}


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
    "hindpetro", "honaut", "idfcfirstb", "iex", "iifl",
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
    "doji",               # PF 0.41
    "three_outside_up",   # PF 0.26
    "three_inside_up",    # PF 0.30
    "three_outside_down", # PF 0.15
    "bearish_harami",     # PF 0.42
}

# Patterns whitelisted based on OOS profitability (PF > 1.0 out-of-sample)
# Only these patterns generate a trade signal.
# Other patterns → neutral (no trade).
WHITELISTED_PATTERNS = {
    "homing_pigeon",         # OOS profitable
    "hammer",                # OOS profitable, classic reversal
    "three_black_crows",     # OOS profitable, strong reversal
    "belt_hold_bullish",     # OOS profitable
    "three_inside_down",     # OOS profitable
    "harami_cross",          # OOS profitable
    "bullish_kicker",        # OOS profitable, strong reversal
    "rising_three_methods",  # OOS profitable, continuation
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


# ============================================================
# ITEM 4: TIER / CONFIDENCE FILTERS
# ============================================================
# Tier_4 (pattern-only match) has OOS PF 0.79 → reject.
# Tier_1 OOS PF 0.96, Tier_2 ~0.9 — accept tier_1 and tier_2 only.
ALLOWED_TIERS = {"tier_1", "tier_2"}

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


# ============================================================
# TRADING COST MODEL
# ============================================================
# Indian intraday: ~0.05% round-trip
# Covers brokerage + STT + exchange txn + GST + stamp duty + SEBI turnover
SLIPPAGE_COMMISSION_PCT = 0.05


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
