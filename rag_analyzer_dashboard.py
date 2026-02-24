"""
Traqo — RAG Analyzer Dashboard
================================================
Pure Python HTTP server with server-rendered HTML + Tailwind CSS.
No Streamlit. No React. No build step.

Run:
    python rag_analyzer_dashboard.py
    → Opens http://localhost:8522
"""

import os
import sys
import re
import json
import time
import threading
import webbrowser
import urllib.parse
import warnings
import traceback
import pandas as pd
import yfinance as yf
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

try:
    import ollama as _ollama_mod
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    _ollama_mod = None

from candlestick_knowledge_base import get_pattern_context_text
from pattern_detector import detect_live_patterns, detect_market_regime
from statistical_predictor import StatisticalPredictor
from trading_config import (
    STRUCTURAL_SL_PATTERNS, STRUCTURAL_SL_MULTIPLIER, STANDARD_SL_MULTIPLIER,
    ALLOWED_TIMEFRAMES,
    is_tradeable_pattern,
)

warnings.filterwarnings("ignore")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_FILE = os.path.join(SCRIPT_DIR, "feedback/feedback_log.json")
LEARNING_FILE = os.path.join(SCRIPT_DIR, "feedback/learned_rules.json")
TOP_K = 25
OLLAMA_MODEL = "qwen2.5:7b"
PORT = 8522

os.makedirs(os.path.join(SCRIPT_DIR, "feedback"), exist_ok=True)


# ============================================================
# NIFTY 250 STOCK GROUPS (Ordered)
# ============================================================
_NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJAUTO", "BAJAJFINSV", "BAJFINANCE", "BHARTIARTL", "BPCL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB", "DRREDDY",
    "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
    "INDUSINDBK", "INFOSYS", "ITC", "JSWSTEEL", "KOTAKBANK",
    "LT", "MAHINDRA", "MARUTI", "NESTLEIND", "NTPC",
    "ONGC", "POWERGRID", "RELIANCE", "SBI", "SBILIFE",
    "SHRIRAMFIN", "SUNPHARMA", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

_NIFTY_NEXT_50 = [
    "ABB", "ACC", "ADANIGREEN", "ADANIPOWER", "AMBUJACEM",
    "ATGL", "AUROPHARMA", "BAJAJHLDNG", "BANKBARODA", "BEL",
    "BERGEPAINT", "BIOCON", "BOSCHLTD", "CANBK", "CHOLAFIN",
    "COLPAL", "DABUR", "DLF", "GAIL", "GODREJCP",
    "HAL", "HAVELLS", "ICICIPRULI", "INDIGO", "IOC",
    "IRCTC", "IRFC", "JINDALSTEL", "JIOFIN", "LICI",
    "LTIM", "LTTS", "LUPIN", "MAXHEALTH", "MOTHERSON",
    "NAUKRI", "NHPC", "OBEROIRLTY", "OFSS", "PAYTM",
    "PFC", "PIDILITIND", "PNB", "POLYCAB", "RECLTD",
    "SBICARD", "SIEMENS", "SRF", "TATACONSUM", "TATAPOWER",
]

_NIFTY_MIDCAP_150 = [
    "AARTIIND", "ABCAPITAL", "ABFRL", "AIAENG", "AJANTPHARM",
    "ALKEM", "ANGELONE", "APLAPOLLO", "APLLTD", "ASHOKLEY",
    "ASTRAL", "ATUL", "AUBANK", "BALKRISIND", "BANKINDIA",
    "BATAINDIA", "BHARATFORG", "BHEL", "BSE", "CANFINHOME",
    "CARBORUNIV", "CASTROLIND", "CDSL", "CESC", "CGPOWER",
    "CHAMBLFERT", "CLEAN", "COCHINSHIP", "COFORGE", "COROMANDEL",
    "CROMPTON", "CUB", "CUMMINSIND", "CYIENT", "DALBHARAT",
    "DEEPAKNTR", "DELHIVERY", "DEVYANI", "DIXON", "EMAMILTD",
    "ENDURANCE", "ESCORTS", "EXIDEIND", "FACT", "FEDERALBNK",
    "FINEORG", "FLUOROCHEM", "FORTIS", "GILLETTE", "GLENMARK",
    "GLAXO", "GMRAIRPORT", "GNFC", "GODREJIND", "GODREJPROP",
    "GRANULES", "GRAPHITE", "GRINDWELL", "GUJGASLTD", "HATSUN",
    "HINDPETRO", "HONAUT", "IDFCFIRSTB", "IEX", "IIFL",
    "INDIANB", "INDIANHOTELS", "INDIAMART", "INDUSTOWER", "INTELLECT",
    "IPCALAB", "JKCEMENT", "JSWENERGY", "JSWINFRA", "JUBLFOOD",
    "KALYANKJIL", "KEI", "KIMS", "KPITTECH", "LALPATHLAB",
    "LAURUSLABS", "LICHSGFIN", "MANAPPURAM", "MANKIND", "MARICO",
    "MAZDOCK", "METROBRAND", "MFSL", "MGL", "MPHASIS",
    "MRF", "MUTHOOTFIN", "NAMINDIA", "NATCOPHARM", "NAVINFLUOR",
    "NMDC", "OIL", "PAGEIND", "PATANJALI", "PERSISTENT",
    "PETRONET", "PGHH", "PHOENIXLTD", "PIIND", "POLYMED",
    "POONAWALLA", "PRESTIGE", "PVRINOX", "RADICO", "RAIN",
    "RAJESHEXPO", "RAMCOCEM", "RATNAMANI", "RBLBANK", "SAIL",
    "SCHAEFFLER", "SHREECEM", "SONACOMS", "STARHEALTH", "SUMICHEM",
    "SUNDARMFIN", "SUNDRMFAST", "SUNTECK", "SUNTV", "SUPREMEIND",
    "SYNGENE", "TATACHEM", "TATACOMM", "TATAELXSI", "TATATECH",
    "TIINDIA", "TIMKEN", "TORNTPHARM", "TORNTPOWER", "TRIDENT",
    "TVSMOTOR", "UBL", "UNIONBANK", "UNITDSPR", "UPL",
    "VBL", "VEDL", "VOLTAS", "WHIRLPOOL", "YESBANK",
    "ZEEL", "ZYDUSLIFE", "3MINDIA",
]

# Build the 5 groups of 50 each
_ALL_STOCKS = _NIFTY_50 + _NIFTY_NEXT_50 + _NIFTY_MIDCAP_150
NIFTY_GROUPS = {
    "1-50":    _ALL_STOCKS[0:50],
    "51-100":  _ALL_STOCKS[50:100],
    "101-150": _ALL_STOCKS[100:150],
    "151-200": _ALL_STOCKS[150:200],
    "201-248": _ALL_STOCKS[200:],
}
NIFTY_GROUP_LABELS = {
    "1-50":    "Nifty 1–50",
    "51-100":  "Nifty 51–100",
    "101-150": "Nifty 101–150",
    "151-200": "Nifty 151–200",
    "201-248": f"Nifty 201–{len(_ALL_STOCKS)}",
}
# JSON for JavaScript
_NIFTY_GROUPS_JSON = json.dumps({k: v for k, v in NIFTY_GROUPS.items()})


# ============================================================
# SYSTEM PROMPTS
# ============================================================
SYSTEM_PROMPT_ANALYSIS = """You are an expert intraday trading analyst specializing in candlestick pattern analysis for Indian markets (NSE). You have two sources of knowledge:

1. PATTERN THEORY (Knowledge Base): Deep understanding of candlestick pattern psychology — why buyers/sellers create each pattern shape, when patterns are reliable vs weak, contextual modifiers (volume, RSI, trend alignment, session timing), and reliability ratings based on Bulkowski and Nison research.

2. EMPIRICAL DATA (RAG): 147,000+ historical candlestick pattern documents spanning 10 years and 47 instruments with actual forward returns, showing what really happened after each pattern appeared.

When both sources agree, you have high conviction. When they disagree, explain the conflict.

Your role:
1. Use the PATTERN KNOWLEDGE BASE context provided to explain the psychology behind detected patterns
2. Cross-reference with the EMPIRICAL RAG data — do the historical outcomes match what theory predicts?
3. Apply contextual modifiers (volume, RSI, trend, session) to adjust reliability scores
4. Provide clear Entry, Target, and Stop Loss levels with double justification (theory + data)
5. Assess risk honestly — call out when theory and data diverge

Communication style:
- Be direct and data-driven
- Explain the psychology behind patterns
- Reference specific reliability ratings and contextual modifiers
- Use specific numbers from the retrieved historical data
- Think like a professional trader who understands both theory and statistics
- Acknowledge uncertainty when data is conflicting

IMPORTANT: You have expert-level pattern knowledge AND real historical data. Use BOTH."""

SYSTEM_PROMPT_CONVERSATION = """You are a trading assistant continuing a conversation about a stock analysis. You have deep knowledge of candlestick pattern theory (Nison, Bulkowski) and access to the original analysis data. Answer follow-up questions about pattern psychology, entry/exit reasoning, what-if scenarios, risk management adjustments, alternative setups, and how volume/trend/session affect pattern reliability. Keep responses focused on the specific trade being discussed."""

SYSTEM_PROMPT_LEARNING = """You are reviewing trading feedback data to extract actionable rules. Based on the feedback history (what predictions were correct vs incorrect), generate concise trading rules. Focus on:
1. Which patterns + context combinations are reliable vs unreliable
2. Common failure modes to avoid
3. Adjustments to target/stop loss levels based on actual outcomes
4. Time-of-day or day-of-week patterns in accuracy

Output rules as a JSON array: {"rule": "description", "confidence": 0.0-1.0, "type": "avoid|prefer|adjust", "context": "when this applies"}"""


# ============================================================
# GLOBAL STATE
# ============================================================
_analysis = {
    "results": None,
    "chat_history": [],
    "analysis_context": "",
}
_active_model_name = OLLAMA_MODEL
_stat_predictor = None
_ollama_cache = {"ok": None, "models": [], "checked_at": 0}


def _get_sp():
    global _stat_predictor
    if _stat_predictor is None:
        _stat_predictor = StatisticalPredictor()
    return _stat_predictor


def _get_ollama_status():
    if not OLLAMA_AVAILABLE:
        return False, []
    now = time.time()
    if now - _ollama_cache["checked_at"] < 30:
        return _ollama_cache["ok"], _ollama_cache["models"]
    try:
        models = _ollama_mod.list()
        names = [m.model for m in models.models] if hasattr(models, "models") else []
        _ollama_cache.update(ok=True, models=names, checked_at=now)
    except Exception:
        _ollama_cache.update(ok=False, models=[], checked_at=now)
    return _ollama_cache["ok"], _ollama_cache["models"]


# ============================================================
# BUSINESS LOGIC (ported from app_ollama.py, no Streamlit deps)
# ============================================================

def detect_patterns_on_df(df):
    result = detect_live_patterns(df)
    if isinstance(result, dict):
        pats = result.get("patterns", "none")
        pattern_list = [p.strip() for p in pats.split(",") if p.strip()] if pats != "none" else ["none"]
        pattern_list = [p for p in pattern_list if is_tradeable_pattern(p)]
        if not pattern_list:
            pattern_list = ["none"]
        return {"patterns": pattern_list, "confidence": result.get("confidence", 0.0),
                "volume_confirmed": result.get("volume_confirmed", False)}
    if result == "none":
        return {"patterns": ["none"], "confidence": 0.0, "volume_confirmed": False}
    return {"patterns": [p.strip() for p in result.split(",") if p.strip()],
            "confidence": 0.5, "volume_confirmed": False}


def compute_live_indicators(df):
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else None
    ind = {}
    for period in [9, 21, 50]:
        if len(close) >= period:
            ind[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean().iloc[-1]
    if len(close) >= 15:
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        ind["rsi_14"] = float(100 - (100 / (1 + rs)).iloc[-1])
    if len(close) >= 15:
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        ind["atr_14"] = float(tr.rolling(14).mean().iloc[-1])
    if volume is not None and len(volume) >= 21 and volume.sum() > 0:
        vol_ma = volume.rolling(20).mean().iloc[-1]
        if vol_ma > 0:
            ind["vol_ratio"] = float(volume.iloc[-1] / vol_ma)
    if volume is not None and volume.sum() > 0 and len(close) >= 2:
        try:
            tp = (high + low + close) / 3
            vwap_val = float((tp * volume).cumsum().iloc[-1] / volume.cumsum().iloc[-1])
            if pd.notna(vwap_val) and vwap_val > 0:
                ind["vwap"] = vwap_val
                ind["price_vs_vwap"] = "above" if close.iloc[-1] > vwap_val else "below"
        except Exception:
            pass
    if "ema_9" in ind and "ema_21" in ind:
        ind["trend_short"] = "bullish" if ind["ema_9"] > ind["ema_21"] else "bearish"
    if "ema_21" in ind and "ema_50" in ind:
        ind["trend_medium"] = "bullish" if ind["ema_21"] > ind["ema_50"] else "bearish"
    if "rsi_14" in ind:
        rv = ind["rsi_14"]
        ind["rsi_zone"] = "oversold" if rv < 30 else "overbought" if rv > 70 else "neutral"
    if len(close) >= 2:
        ind["gap_pct"] = float((df["Open"].iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
    return ind


def stat_predict_and_adapt(sp, patterns, timeframe=None, trend_short=None,
                           rsi_zone=None, price_vs_vwap=None,
                           market_regime=None, instrument=None):
    tf_map = {"15m": "15min", "1d": "daily"}
    tf_db = tf_map.get(timeframe, timeframe)
    patterns_str = ",".join(patterns) if isinstance(patterns, list) else patterns
    pred = sp.predict_multi_pattern(
        patterns_str, timeframe=tf_db, trend_short=trend_short,
        rsi_zone=rsi_zone, price_vs_vwap=price_vs_vwap,
        market_regime=market_regime, instrument=instrument,
    )
    if pred is None:
        return None
    adapted_horizons = {}
    for hkey, hdata in pred.get("horizons", {}).items():
        direction_upper = hdata["direction"].upper()
        adapted_horizons[hkey] = {
            "avg_return_pct": hdata["avg_return"], "median_return_pct": hdata["median_return"],
            "std_return_pct": hdata["std_return"], "bullish_pct": hdata["bullish_pct"],
            "bearish_pct": hdata["bearish_pct"], "direction": direction_upper,
            "count": hdata["count"], "bullish_edge": hdata["bullish_edge"],
            "bearish_edge": hdata["bearish_edge"],
        }
    return {
        "n_matches": pred["n_matches"],
        "avg_similarity": pred["confidence_score"],
        "horizons": adapted_horizons,
        "risk_reward": {"avg_mfe_pct": pred["avg_mfe"], "avg_mae_pct": pred["avg_mae"],
                        "risk_reward_ratio": pred["rr_ratio"]},
        "confidence": {"score": pred["confidence_score"], "level": pred["confidence_level"]},
        "matches": [], "pattern_breakdown": {pred["pattern"]: pred["n_matches"]},
        "retrieved_documents": [],
        "stat_extras": {
            "win_rate": pred["win_rate"], "profit_factor": pred["profit_factor"],
            "match_tier": pred["match_tier"], "bullish_edge": pred["bullish_edge"],
            "bearish_edge": pred["bearish_edge"],
            "instrument_diversity": pred.get("instrument_diversity", 0),
            "top_instruments": pred.get("top_instruments", {}),
            "predicted_direction": pred["predicted_direction"],
            "sl_win_rate": pred.get("sl_win_rate", pred["win_rate"]),
            "sl_profit_factor": pred.get("sl_profit_factor", pred["profit_factor"]),
            "sl_triggers_pct": pred.get("sl_triggers_pct", 0),
        },
    }


def compute_trade_levels(current_price, prediction, atr, direction, patterns=None, df=None):
    rr = prediction.get("risk_reward", {})
    avg_mfe = rr.get("avg_mfe_pct", 0.5)
    avg_mae = rr.get("avg_mae_pct", -0.3)
    pat_set = set(patterns) if patterns else set()
    is_structural = bool(pat_set & STRUCTURAL_SL_PATTERNS)
    sl_multiplier = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
    if atr and atr > 0:
        atr_sl_pct = sl_multiplier * atr / current_price * 100
        atr_sl_pct = max(0.3, min(5.0, atr_sl_pct))
    else:
        atr_sl_pct = abs(avg_mae) if avg_mae else 1.0
    structural_sl_price = None
    if df is not None and len(df) >= 2 and is_structural:
        if "bullish_harami" in pat_set:
            structural_sl_price = float(df["Low"].iloc[-2])
        elif "belt_hold_bearish" in pat_set:
            structural_sl_price = float(df["Open"].iloc[-1])
        elif any(p in pat_set for p in {"bullish_kicker", "ladder_bottom", "mat_hold"}):
            structural_sl_price = float(df["Low"].iloc[-2])
    if direction == "BULLISH":
        entry = current_price
        target_data = round(current_price * (1 + avg_mfe / 100), 2)
        sl_data = round(current_price * (1 + avg_mae / 100), 2)
        target_atr = round(current_price + 1.5 * atr, 2) if atr else target_data
        sl_atr = round(current_price * (1 - atr_sl_pct / 100), 2)
    else:
        entry = current_price
        target_data = round(current_price * (1 - abs(avg_mfe) / 100), 2)
        sl_data = round(current_price * (1 - avg_mae / 100), 2)
        target_atr = round(current_price - 1.5 * atr, 2) if atr else target_data
        sl_atr = round(current_price * (1 + atr_sl_pct / 100), 2)
    if structural_sl_price is not None:
        sl_recommended = structural_sl_price
        sl_pct_actual = abs(current_price - structural_sl_price) / current_price * 100
        sl_pct_actual = max(0.3, min(5.0, sl_pct_actual))
        sl_type = "structural"
    else:
        sl_recommended = sl_atr
        sl_pct_actual = atr_sl_pct
        sl_type = "atr"
    return {
        "entry": entry, "target_data": target_data, "stop_loss_data": sl_data,
        "target_atr": target_atr, "stop_loss_atr": sl_atr,
        "target_recommended": round((target_data * 0.6 + target_atr * 0.4), 2),
        "stop_loss_recommended": round(sl_recommended, 2),
        "sl_pct": round(sl_pct_actual, 2), "sl_type": sl_type,
        "sl_multiplier": sl_multiplier,
    }


def get_ollama_analysis(ticker, current_price, patterns, indicators, prediction,
                        trade_levels, direction, feedback_context=""):
    rr = prediction.get("risk_reward", {})
    h5 = prediction["horizons"].get("+5_candles", {})
    confidence = prediction.get("confidence", {})
    stat_extras = prediction.get("stat_extras", {})
    learned_rules = load_learned_rules()
    rules_context = ""
    if learned_rules:
        rules_context = "\n\nLEARNED RULES FROM PAST FEEDBACK:\n"
        for rule in learned_rules[:10]:
            rules_context += f"  - [{rule.get('type', 'info')}] {rule.get('rule', '')} (confidence: {rule.get('confidence', 'N/A')})\n"
    kb_indicators = {
        "rsi_14": indicators.get("rsi_14"), "vol_ratio": indicators.get("vol_ratio"),
        "trend_short": indicators.get("trend_short"), "session": indicators.get("session"),
        "day_name": indicators.get("day_name"),
    }
    pattern_knowledge = get_pattern_context_text(patterns, kb_indicators)
    pf_value = stat_extras.get("profit_factor")
    try:
        pf_value = float(pf_value)
    except (TypeError, ValueError):
        pf_value = None
    if pf_value is not None and pf_value >= 1.5:
        pattern_tier = f"TIER A — EXCEPTIONAL (PF {pf_value:.2f}). High-conviction signal."
    elif pf_value is not None and pf_value >= 1.0:
        pattern_tier = f"TIER B — MODERATE (PF {pf_value:.2f}). Requires confirmation."
    else:
        pattern_tier = f"TIER C — WEAK (PF {pf_value}). Low confidence."

    def _fv(v, fmt=".1f"):
        try:
            return f"{float(v):{fmt}}"
        except (TypeError, ValueError):
            return "N/A"

    prompt = f"""Analyze this trading setup:

TICKER: {ticker} | PRICE: ₹{current_price:,.2f}
PATTERNS: {', '.join(patterns)}
PATTERN QUALITY: {pattern_tier}

{pattern_knowledge}

INDICATORS: RSI {_fv(indicators.get('rsi_14'))} ({indicators.get('rsi_zone','N/A')}), Trend: {indicators.get('trend_short','N/A')}/{indicators.get('trend_medium','N/A')}, ATR: {_fv(indicators.get('atr_14'),'.2f')}, Vol: {_fv(indicators.get('vol_ratio'),'.2f')}x, VWAP: {_fv(indicators.get('vwap'),'.2f')} ({indicators.get('price_vs_vwap','N/A')})

RAG RESULTS ({prediction['n_matches']} matches, tier: {stat_extras.get('match_tier','N/A')}):
- 5-candle: {h5.get('bullish_pct','N/A')}% bullish, edge: bull {_fv(h5.get('bullish_edge',0),'+.1f')}% / bear {_fv(h5.get('bearish_edge',0),'+.1f')}%
- Win rate: {_fv(stat_extras.get('win_rate'))}% (w/ SL: {_fv(stat_extras.get('sl_win_rate'))}%), PF: {_fv(stat_extras.get('profit_factor'),'.2f')} (w/ SL: {_fv(stat_extras.get('sl_profit_factor'),'.2f')})
- MFE: {_fv(rr.get('avg_mfe_pct'))}%, MAE: {_fv(rr.get('avg_mae_pct'))}%, R:R 1:{_fv(rr.get('risk_reward_ratio'),'.2f')}

TRADE LEVELS: Entry ₹{trade_levels['entry']:,.2f} | Target ₹{trade_levels['target_recommended']:,.2f} | SL ₹{trade_levels['stop_loss_recommended']:,.2f} ({trade_levels.get('sl_type','atr')}, {trade_levels.get('sl_pct','?')}%)

HORIZONS: {json.dumps(prediction['horizons'], indent=2)}
{rules_context}{feedback_context}

Provide: 1) TRADE CALL (BUY/SELL/AVOID) 2) Entry/Target/SL reasoning 3) Risk assessment 4) Key insight. Be concise, use numbers."""

    try:
        response = _ollama_mod.chat(
            model=_active_model_name,
            messages=[{"role": "system", "content": SYSTEM_PROMPT_ANALYSIS},
                      {"role": "user", "content": prompt}],
            options={"temperature": 0.3, "num_predict": 1500},
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Ollama analysis unavailable: {e}\n\nFalling back to statistical analysis only."


def ollama_chat_followup(chat_history, analysis_context):
    messages = [{"role": "system", "content": SYSTEM_PROMPT_CONVERSATION + f"\n\nCONTEXT:\n{analysis_context}"}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    try:
        response = _ollama_mod.chat(
            model=_active_model_name, messages=messages,
            options={"temperature": 0.4, "num_predict": 1000},
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Error communicating with Ollama: {e}"


def ollama_learn_from_feedback(feedback_data):
    if not feedback_data or len(feedback_data) < 3:
        return []
    correct = [f for f in feedback_data if f.get("was_correct")]
    incorrect = [f for f in feedback_data if not f.get("was_correct")]
    summary = f"Total: {len(feedback_data)}, Correct: {len(correct)}, Wrong: {len(incorrect)}\n\nCORRECT:\n"
    for fb in correct[-15:]:
        summary += f"  - {fb.get('ticker','?')} | {fb.get('patterns','?')} | {fb.get('direction','?')}\n"
    summary += "\nINCORRECT:\n"
    for fb in incorrect[-15:]:
        summary += f"  - {fb.get('ticker','?')} | {fb.get('patterns','?')} | Reason: {fb.get('wrong_reason','?')}\n"
    try:
        response = _ollama_mod.chat(
            model=_active_model_name,
            messages=[{"role": "system", "content": SYSTEM_PROMPT_LEARNING},
                      {"role": "user", "content": summary}],
            options={"temperature": 0.2, "num_predict": 2000},
        )
        content = response["message"]["content"]
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
        return [{"rule": content[:500], "confidence": 0.5, "type": "info", "context": "general"}]
    except Exception as e:
        return [{"rule": f"Learning failed: {e}", "confidence": 0, "type": "info", "context": "error"}]


# ── Feedback CRUD ──
def load_feedback():
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "r") as f:
            return json.load(f)
    return []

def save_feedback(fb):
    with open(FEEDBACK_FILE, "w") as f:
        json.dump(fb, f, indent=2, default=str)

def load_learned_rules():
    if os.path.exists(LEARNING_FILE):
        with open(LEARNING_FILE, "r") as f:
            return json.load(f)
    return []

def save_learned_rules(rules):
    with open(LEARNING_FILE, "w") as f:
        json.dump(rules, f, indent=2, default=str)

def add_feedback(ticker, pred_data, trade_data, was_correct, wrong_reason=None, notes=None):
    fb = load_feedback()
    fb.append({
        "timestamp": datetime.now().isoformat(), "ticker": ticker,
        "patterns": pred_data.get("patterns", []),
        "direction": pred_data.get("direction", ""),
        "entry_price": trade_data.get("entry"),
        "target": trade_data.get("target_recommended"),
        "stop_loss": trade_data.get("stop_loss_recommended"),
        "confidence": pred_data.get("confidence_level", ""),
        "was_correct": was_correct, "wrong_reason": wrong_reason, "notes": notes,
        "n_matches": pred_data.get("n_matches"),
    })
    save_feedback(fb)
    if len(fb) % 5 == 0 and OLLAMA_AVAILABLE:
        rules = ollama_learn_from_feedback(fb)
        if rules:
            save_learned_rules(rules)
    return len(fb)

def get_feedback_stats():
    fb = load_feedback()
    if not fb:
        return None
    total = len(fb)
    correct = sum(1 for f in fb if f.get("was_correct"))
    wrong_reasons = {}
    for f in fb:
        if not f.get("was_correct") and f.get("wrong_reason"):
            r = f["wrong_reason"].split(" | Notes:")[0]
            wrong_reasons[r] = wrong_reasons.get(r, 0) + 1
    return {"total": total, "correct": correct,
            "accuracy": round(correct / total * 100, 1) if total else 0,
            "wrong_reasons": wrong_reasons}


def fetch_live_data(ticker, interval="15m"):
    ticker_yf = ticker
    if not ticker.endswith(".NS") and not ticker.startswith("^") and "=" not in ticker:
        ticker_yf = f"{ticker}.NS"
    period = "60d" if interval == "15m" else "1y"
    df = yf.download(ticker_yf, period=period, interval=interval, progress=False)
    if df.empty:
        return None, ticker_yf
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    col_map = {}
    for c in df.columns:
        cl = str(c).lower().strip()
        if "open" in cl and "Open" not in col_map.values(): col_map[c] = "Open"
        elif "high" in cl and "High" not in col_map.values(): col_map[c] = "High"
        elif "low" in cl and "Low" not in col_map.values(): col_map[c] = "Low"
        elif "close" in cl and "adj" not in cl and "Close" not in col_map.values(): col_map[c] = "Close"
        elif "volume" in cl and "Volume" not in col_map.values(): col_map[c] = "Volume"
    df = df.rename(columns=col_map)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df, ticker_yf


# ── Full Analysis Pipeline ──
def run_analysis(ticker_raw, timeframe):
    """Run full analysis. Returns dict with all results or {'error': msg}."""
    ticker = ticker_raw.strip().upper()

    # Check cache first (1-hour TTL)
    cached = _get_cached(ticker, timeframe)
    if cached:
        return cached

    ticker_map = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK",
                  "BANK NIFTY": "^NSEBANK", "SENSEX": "^BSESN"}
    ticker_resolved = ticker_map.get(ticker, ticker)

    df, ticker_yf = fetch_live_data(ticker_resolved, interval=timeframe)
    if df is None or len(df) < 20:
        return {"error": f"Could not fetch data for {ticker_yf}. Check the ticker symbol.", "ticker": ticker}

    last = df.iloc[-1]
    current_price = float(last["Close"])
    prev_close = float(df["Close"].iloc[-2])
    change_pct = (current_price - prev_close) / prev_close * 100

    pat_result = detect_patterns_on_df(df)
    patterns = pat_result["patterns"]
    indicators = compute_live_indicators(df)
    regime = detect_market_regime(df)
    indicators["market_regime"] = regime
    indicators["pattern_confidence"] = pat_result["confidence"]
    indicators["volume_confirmed"] = pat_result["volume_confirmed"]

    sp = _get_sp()
    prediction = stat_predict_and_adapt(
        sp, patterns=patterns if patterns[0] != "none" else ["spinning_top"],
        timeframe=timeframe, trend_short=indicators.get("trend_short"),
        rsi_zone=indicators.get("rsi_zone"), price_vs_vwap=indicators.get("price_vs_vwap"),
        market_regime=indicators.get("market_regime"), instrument=ticker_resolved,
    )
    if not prediction:
        return {"error": "No similar patterns found in database.", "ticker": ticker}

    h5 = prediction["horizons"].get("+5_candles", prediction["horizons"].get("+3_candles", {}))
    direction = h5.get("direction", "NEUTRAL") if h5 else "NEUTRAL"
    stat_extras = prediction.get("stat_extras", {})
    confidence = prediction.get("confidence", {})
    atr = indicators.get("atr_14", current_price * 0.005)
    edge = max(abs(stat_extras.get("bullish_edge", 0)), abs(stat_extras.get("bearish_edge", 0)))
    is_no_trade = direction == "NEUTRAL" or edge < 8.5

    if not is_no_trade:
        trade = compute_trade_levels(current_price, prediction, atr, direction, patterns=patterns, df=df)
    else:
        trade = {"entry": current_price, "target_data": current_price,
                 "stop_loss_data": current_price, "target_atr": current_price,
                 "stop_loss_atr": current_price, "target_recommended": current_price,
                 "stop_loss_recommended": current_price, "sl_pct": 0,
                 "sl_type": "none", "sl_multiplier": 0}

    llm_analysis = ""
    if OLLAMA_AVAILABLE:
        fb_ctx = ""
        fb = load_feedback()
        rfb = [f for f in fb if f.get("ticker") == ticker]
        if rfb:
            fb_ctx = f"\nPAST FEEDBACK FOR {ticker}:\n"
            for r in rfb[-5:]:
                s = "CORRECT" if r["was_correct"] else f"WRONG ({r.get('wrong_reason','')})"
                fb_ctx += f"  - {r['timestamp'][:10]} | {r.get('direction','?')} | {s}\n"
        try:
            llm_analysis = get_ollama_analysis(
                ticker, current_price, patterns, indicators,
                prediction, trade, direction, fb_ctx)
        except Exception as e:
            llm_analysis = f"Ollama error: {e}"
    else:
        llm_analysis = "Ollama not available. Showing statistical analysis only."

    conf_level = confidence.get("level", "MEDIUM")
    analysis_context = f"""TICKER: {ticker} at ₹{current_price:,.2f}
PATTERNS: {', '.join(patterns)} | DIRECTION: {direction}
ENTRY: ₹{trade['entry']:,.2f} | TARGET: ₹{trade['target_recommended']:,.2f} | SL: ₹{trade['stop_loss_recommended']:,.2f}
RSI: {indicators.get('rsi_14','N/A')} | TREND: {indicators.get('trend_short','N/A')}
MATCHES: {prediction['n_matches']} | WR: {stat_extras.get('win_rate','N/A')}% | PF: {stat_extras.get('profit_factor','N/A')}
CONFIDENCE: {conf_level}
AI ANALYSIS: {llm_analysis[:1000]}"""

    result = {
        "ticker": ticker, "ticker_yf": ticker_yf, "timeframe": timeframe,
        "timestamp": datetime.now().strftime("%H:%M on %d %b %Y"),
        "current_price": current_price, "prev_close": prev_close,
        "change_pct": change_pct, "high": float(last["High"]),
        "low": float(last["Low"]), "volume": int(last.get("Volume", 0)),
        "patterns": patterns, "pattern_confidence": pat_result["confidence"],
        "volume_confirmed": pat_result["volume_confirmed"],
        "indicators": indicators, "prediction": prediction,
        "direction": direction, "is_no_trade": is_no_trade, "edge": edge,
        "trade": trade, "stat_extras": stat_extras, "confidence": confidence,
        "llm_analysis": llm_analysis, "analysis_context": analysis_context,
        "confidence_level": conf_level,
    }
    _set_cache(ticker, timeframe, result)
    return result


# ── Analysis Cache (1-hour TTL) ──
CACHE_TTL = 3600  # seconds
_analysis_cache = {}  # key: "TICKER|timeframe" → {"result": dict, "ts": float}

def _cache_key(ticker, timeframe):
    return f"{ticker.upper()}|{timeframe}"

def _get_cached(ticker, timeframe):
    key = _cache_key(ticker, timeframe)
    entry = _analysis_cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        result = entry["result"].copy()
        result["_cached"] = True
        age_min = int((time.time() - entry["ts"]) / 60)
        result["_cache_age"] = f"{age_min}m ago"
        return result
    return None

def _set_cache(ticker, timeframe, result):
    if result and not result.get("error"):
        _analysis_cache[_cache_key(ticker, timeframe)] = {"result": result, "ts": time.time()}

def _clear_cache(ticker=None):
    if ticker:
        keys = [k for k in _analysis_cache if k.startswith(ticker.upper() + "|")]
        for k in keys:
            del _analysis_cache[k]
    else:
        _analysis_cache.clear()

# ── Batch Analysis ──
_batch_results = {"group": None, "results": [], "running": False, "progress": 0, "total": 0}


# ============================================================
# HTML HELPERS
# ============================================================
def _e(s):
    if s is None: return "—"
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def _price(v):
    if v is None: return "—"
    return f"₹{float(v):,.2f}"

def _pct(v, sign=True):
    if v is None: return "—"
    v = float(v)
    return f"+{v:.2f}%" if sign and v > 0 else f"{v:.2f}%"

def _md(text):
    """Basic Markdown → HTML for Ollama output."""
    h = _e(text)
    h = re.sub(r'\*\*(.+?)\*\*', r'<strong class="font-semibold text-gray-900">\1</strong>', h)
    h = re.sub(r'^### (.+)$', r'<h4 class="text-base font-semibold text-gray-800 mt-4 mb-1">\1</h4>', h, flags=re.M)
    h = re.sub(r'^## (.+)$', r'<h3 class="text-lg font-semibold text-gray-800 mt-5 mb-2">\1</h3>', h, flags=re.M)
    h = re.sub(r'^# (.+)$', r'<h2 class="text-xl font-bold text-gray-800 mt-5 mb-2">\1</h2>', h, flags=re.M)
    h = re.sub(r'^[-•] (.+)$', r'<div class="flex gap-2 ml-4 my-0.5"><span class="text-blue-400">•</span><span>\1</span></div>', h, flags=re.M)
    h = re.sub(r'^(\d+)\. (.+)$', r'<div class="flex gap-2 ml-4 my-0.5"><span class="text-blue-500 font-medium">\1.</span><span>\2</span></div>', h, flags=re.M)
    h = h.replace('\n', '<br>\n')
    return h


def stat_card(label, value, subtitle="", color="indigo"):
    border_map = {"indigo": "border-gray-200", "green": "border-emerald-200",
                  "red": "border-red-200", "amber": "border-amber-200", "cyan": "border-blue-200"}
    label_map = {"indigo": "text-blue-600", "green": "text-emerald-600",
                 "red": "text-red-600", "amber": "text-amber-600", "cyan": "text-blue-600"}
    sub = f'<p class="mt-1 text-xs text-gray-400">{_e(subtitle)}</p>' if subtitle else ""
    return f'''<div class="rounded-xl bg-white {border_map.get(color,"border-gray-200")} border p-5 shadow-sm">
      <p class="text-xs font-medium uppercase tracking-wider {label_map.get(color,"text-blue-600")}">{_e(label)}</p>
      <p class="mt-2 text-2xl font-bold text-gray-800">{_e(str(value))}</p>{sub}</div>'''


def badge(text, variant="default"):
    styles = {"default": "bg-gray-100 text-gray-600 border-gray-200",
              "success": "bg-emerald-50 text-emerald-700 border-emerald-200",
              "danger": "bg-red-50 text-red-700 border-red-200",
              "warning": "bg-amber-50 text-amber-700 border-amber-200",
              "info": "bg-blue-50 text-blue-700 border-blue-200",
              "bullish": "bg-emerald-50 text-emerald-600 border-emerald-100",
              "bearish": "bg-red-50 text-red-600 border-red-100"}
    return f'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border {styles.get(variant,styles["default"])}">{_e(text)}</span>'


# ============================================================
# PAGE SHELL (matching paper_trading_dashboard.py style)
# ============================================================
LOGO_B64 = "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"


def page_shell(title, active_tab, body_html):
    tabs = [
        ("analyze", "Analyze", "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"),
        ("feedback", "Feedback", "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"),
        ("learning", "Learning", "M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"),
        ("settings", "Settings", "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"),
    ]
    nav_items = ""
    for key, label, icon_path in tabs:
        is_active = key == active_tab
        cls = "bg-blue-50 text-blue-700 border border-blue-100" if is_active else "text-gray-500 hover:text-gray-800 hover:bg-gray-50"
        extra = ""
        if key == "settings":
            extra = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />'
        nav_items += f'''
        <a href="/{key}" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all {cls}">
          <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="{icon_path}" />{extra}
          </svg>{label}</a>'''

    ollama_ok, _ = _get_ollama_status()
    ollama_dot = "bg-emerald-500 pulse-dot" if ollama_ok else "bg-red-400"
    ollama_text = "Ollama Connected" if ollama_ok else "Ollama Offline"

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{_e(title)} — Traqo RAG Analyzer</title>
  <link rel="icon" type="image/png" href="data:image/png;base64,{LOGO_B64}">
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <script>tailwind.config = {{ darkMode: 'class', theme: {{ extend: {{ fontFamily: {{ sans: ['Inter', 'sans-serif'] }} }} }} }}</script>
  <style>
    body {{ font-family: 'Inter', sans-serif; }}
    .scrollbar-thin::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    .scrollbar-thin::-webkit-scrollbar-track {{ background: transparent; }}
    .scrollbar-thin::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 3px; }}
    .glass {{ background: #ffffff; border: 1px solid #e2e8f0; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
    @keyframes fade-in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    .fade-in {{ animation: fade-in 0.25s ease-out; }}
    @keyframes pulse-dot {{ 0%,100% {{ box-shadow: 0 0 0 0 rgba(16,185,129,0.4); }} 50% {{ box-shadow: 0 0 0 6px rgba(16,185,129,0); }} }}
    .pulse-dot {{ animation: pulse-dot 2s infinite; }}
  </style>
</head>
<body class="bg-gray-50 text-gray-800 min-h-screen">
  <aside class="fixed top-0 left-0 h-screen w-60 bg-white border-r border-gray-200 flex flex-col z-50 shadow-sm">
    <div class="px-5 py-5 border-b border-gray-200">
      <div class="flex items-center gap-3">
        <img src="data:image/png;base64,{LOGO_B64}" alt="Traqo" class="w-9 h-9 rounded-xl">
        <div>
          <div class="text-base font-bold text-gray-800">Traqo</div>
          <div class="text-[10px] text-blue-500 font-medium tracking-wide uppercase">RAG Analyzer</div>
        </div>
      </div>
    </div>
    <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto scrollbar-thin">{nav_items}</nav>
    <div class="px-4 py-4 border-t border-gray-200">
      <div class="flex items-center gap-2 text-xs text-gray-400 mb-2">
        <div class="w-2 h-2 rounded-full {ollama_dot}"></div>{ollama_text}
      </div>
      <div class="text-[10px] text-gray-300">by Prateek Tyagi</div>
    </div>
  </aside>
  <main class="ml-60 min-h-screen flex flex-col">
    <div class="p-8 max-w-[1400px] mx-auto fade-in flex-1 w-full">{body_html}</div>
    <footer class="border-t border-gray-200 py-4 px-8 text-center">
      <p class="text-sm text-blue-400"><span class="font-bold text-blue-600">TRAQO</span> &mdash; RAG Powered Quantitative Candlestick Intelligence by <span class="font-medium text-blue-500">Prateek Tyagi</span></p>
    </footer>
  </main>
</body>
</html>'''


# ============================================================
# FLASH MESSAGE HELPER
# ============================================================
def _flash_html(params):
    msg_key = params.get("msg", [None])[0]
    if not msg_key:
        return ""
    messages = {
        "correct": ("Feedback recorded as CORRECT!", "emerald"),
        "wrong": ("Feedback recorded as INCORRECT. Model will learn from this!", "amber"),
        "chat_ok": ("", ""),  # no flash for chat
        "model_saved": ("Ollama model updated!", "blue"),
        "learned": ("Rules re-learned from feedback!", "blue"),
        "learn_err": ("Need at least 3 feedback entries to learn.", "amber"),
    }
    text, color = messages.get(msg_key, (msg_key, "gray"))
    if not text:
        return ""
    bg = f"bg-{color}-50 border-{color}-200 text-{color}-700"
    return f'<div class="rounded-lg border p-4 mb-6 {bg} text-sm font-medium">{_e(text)}</div>'


# ============================================================
# PAGE: ANALYZE
# ============================================================
def render_analyze(params=None):
    params = params or {}
    flash = _flash_html(params)
    r = _analysis["results"]

    # Timeframe options
    tf_options = '<option value="1d" selected>Daily</option>'
    if "15min" in ALLOWED_TIMEFRAMES:
        tf_options = '<option value="15m">15-min</option>' + tf_options

    # Ticker input form
    ticker_val = ""
    if r and isinstance(r, dict) and "ticker" in r:
        ticker_val = _e(str(r["ticker"]))

    # Build group buttons (JS-only, no form submit)
    group_btns = ""
    for gk, gl in NIFTY_GROUP_LABELS.items():
        count = len(NIFTY_GROUPS[gk])
        group_btns += f'''<button type="button" onclick="pasteGroup('{gk}')"
          class="group-btn px-4 py-2.5 bg-indigo-50 hover:bg-indigo-600 hover:text-white text-indigo-700 font-medium rounded-lg transition shadow-sm text-sm border border-indigo-200">
          {gl} <span class="text-xs opacity-70">({count})</span></button>'''

    form = f'''
    <div class="glass rounded-xl p-5 mb-4">
      <p class="text-xs font-medium text-gray-500 uppercase tracking-wider mb-3">Quick Fill — NIFTY 250 Groups</p>
      <div class="flex gap-2 flex-wrap">{group_btns}</div>
    </div>
    <div class="glass rounded-xl p-6 mb-6">
      <form id="analyze-form" method="POST" action="/analyze">
        <div class="flex gap-4 items-start">
          <div class="flex-1">
            <label class="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">NSE Symbols <span class="text-gray-400 normal-case">(comma-separated for batch)</span></label>
            <textarea id="ticker-input" name="ticker" rows="3" placeholder="e.g. RELIANCE, HDFCBANK, INFY — or click a group above to fill"
                   class="w-full px-4 py-3 rounded-lg border border-gray-300 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 outline-none text-gray-800 font-medium text-sm resize-y">{ticker_val}</textarea>
          </div>
          <div class="pt-6">
            <label class="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Timeframe</label>
            <select name="timeframe" class="px-4 py-3 rounded-lg border border-gray-300 focus:border-blue-400 outline-none text-gray-700">{tf_options}</select>
          </div>
          <div class="pt-6">
            <button id="analyze-btn" type="submit"
                    class="px-8 py-3 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg transition shadow-sm mt-5">
              Analyze
            </button>
          </div>
        </div>
      </form>
    </div>
    <div id="loading-overlay" class="fixed inset-0 bg-white/80 z-[100] flex items-center justify-center hidden">
      <div class="text-center">
        <div class="animate-spin h-12 w-12 border-4 border-blue-500 border-t-transparent rounded-full mx-auto mb-4"></div>
        <p id="loading-text" class="text-lg font-semibold text-gray-700">Analyzing...</p>
        <p id="loading-sub" class="text-sm text-gray-500 mt-1">Fetching data, detecting patterns, running AI analysis</p>
      </div>
    </div>
    <script>
    var NIFTY_GROUPS = {_NIFTY_GROUPS_JSON};
    function pasteGroup(key) {{
      var ta = document.getElementById('ticker-input');
      ta.value = NIFTY_GROUPS[key].join(', ');
      ta.focus();
      ta.scrollIntoView({{behavior:'smooth', block:'center'}});
      // highlight the clicked button
      document.querySelectorAll('.group-btn').forEach(function(b) {{ b.classList.remove('bg-indigo-600','text-white'); b.classList.add('bg-indigo-50','text-indigo-700'); }});
      event.target.closest('.group-btn').classList.add('bg-indigo-600','text-white');
      event.target.closest('.group-btn').classList.remove('bg-indigo-50','text-indigo-700');
    }}
    document.getElementById('analyze-form').addEventListener('submit', function(e) {{
      var ticker = document.getElementById('ticker-input').value.trim();
      if (!ticker) {{ e.preventDefault(); return; }}
      var count = ticker.split(',').filter(function(s){{ return s.trim(); }}).length;
      document.getElementById('loading-overlay').classList.remove('hidden');
      if (count > 1) {{
        document.getElementById('loading-text').textContent = 'Batch Analysis: ' + count + ' stocks...';
        document.getElementById('loading-sub').textContent = 'Analyzing multiple stocks — this may take several minutes. Please wait.';
      }} else {{
        document.getElementById('loading-text').textContent = 'Analyzing ' + ticker + '...';
        document.getElementById('loading-sub').textContent = 'Fetching data, detecting patterns, running AI analysis';
      }}
      var btn = document.getElementById('analyze-btn');
      btn.disabled = true; btn.textContent = 'Analyzing...';
      btn.classList.add('opacity-60', 'cursor-not-allowed');
    }});
    </script>'''

    if not r:
        empty = '''<div class="flex flex-col items-center justify-center py-20 text-center">
          <svg class="w-16 h-16 text-gray-300 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <p class="text-lg font-medium text-gray-500">Enter a ticker to begin analysis</p>
          <p class="text-sm text-gray-400 mt-1">AI-powered pattern detection, statistical prediction &amp; Ollama reasoning</p>
        </div>'''
        body = f'''<h2 class="text-2xl font-bold text-gray-800 mb-1">Analyze Stock</h2>
        <p class="text-sm text-gray-500 mb-6">RAG-powered analysis with 147K+ historical pattern documents</p>
        {flash}{form}{empty}'''
        return page_shell("Analyze", "analyze", body)

    # ── RESULTS ──
    if r.get("error"):
        err = f'<div class="rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700">{_e(r["error"])}</div>'
        body = f'''<h2 class="text-2xl font-bold text-gray-800 mb-1">Analyze Stock</h2>
        <p class="text-sm text-gray-500 mb-6">RAG-powered analysis</p>{flash}{form}{err}'''
        return page_shell("Analyze", "analyze", body)

    # Price overview
    change_cls = "text-emerald-600" if r["change_pct"] >= 0 else "text-red-600"
    price_cards = f'''<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {stat_card("Current Price", _price(r["current_price"]),
                 f'<span class="{change_cls}">{_pct(r["change_pct"])}</span>', "indigo")}
      {stat_card("Day High", _price(r["high"]), "", "green")}
      {stat_card("Day Low", _price(r["low"]), "", "red")}
      {stat_card("Volume", f'{r["volume"]:,}' if r["volume"] > 0 else "N/A", "", "cyan")}
    </div>'''

    # Patterns
    pat_badges = ""
    for p in r["patterns"]:
        if p == "none":
            pat_badges += '<span class="text-sm text-gray-400 italic">No significant pattern detected</span>'
        else:
            is_bull = any(b in p for b in ["bullish", "hammer", "morning", "white", "dragonfly", "piercing"])
            is_bear = any(b in p for b in ["bearish", "shooting", "evening", "black", "dark", "hanging", "gravestone"])
            v = "bullish" if is_bull else "bearish" if is_bear else "default"
            pat_badges += badge(p.replace("_", " ").title(), v) + " "
    conf_pct = f"{r['pattern_confidence']:.0%}" if r['pattern_confidence'] else "N/A"
    vol_icon = '<span class="text-emerald-500 font-semibold">YES</span>' if r["volume_confirmed"] else '<span class="text-red-400">NO</span>'

    # Indicators
    ind = r["indicators"]
    ind_rows = ""
    if "rsi_14" in ind:
        rsi_c = "text-red-600" if ind["rsi_14"] > 70 else "text-emerald-600" if ind["rsi_14"] < 30 else "text-gray-700"
        ind_rows += f'<div class="flex justify-between py-1.5 border-b border-gray-100"><span class="text-gray-500">RSI(14)</span><span class="{rsi_c} font-semibold">{ind["rsi_14"]:.1f} ({ind.get("rsi_zone","neutral")})</span></div>'
    if "trend_short" in ind:
        tc = "text-emerald-600" if ind["trend_short"] == "bullish" else "text-red-600"
        ind_rows += f'<div class="flex justify-between py-1.5 border-b border-gray-100"><span class="text-gray-500">Short Trend</span><span class="{tc} font-semibold">{ind["trend_short"].title()}</span></div>'
    if "trend_medium" in ind:
        tc = "text-emerald-600" if ind["trend_medium"] == "bullish" else "text-red-600"
        ind_rows += f'<div class="flex justify-between py-1.5 border-b border-gray-100"><span class="text-gray-500">Medium Trend</span><span class="{tc} font-semibold">{ind["trend_medium"].title()}</span></div>'
    if "atr_14" in ind:
        ind_rows += f'<div class="flex justify-between py-1.5 border-b border-gray-100"><span class="text-gray-500">ATR(14)</span><span class="font-semibold">{ind["atr_14"]:.2f}</span></div>'
    if "vol_ratio" in ind:
        ind_rows += f'<div class="flex justify-between py-1.5 border-b border-gray-100"><span class="text-gray-500">Volume</span><span class="font-semibold">{ind["vol_ratio"]:.2f}x avg</span></div>'
    if "vwap" in ind:
        vc = "text-emerald-600" if ind.get("price_vs_vwap") == "above" else "text-red-600"
        ind_rows += f'<div class="flex justify-between py-1.5 border-b border-gray-100"><span class="text-gray-500">VWAP</span><span class="{vc} font-semibold">₹{ind["vwap"]:,.2f} ({ind.get("price_vs_vwap","?")})</span></div>'
    if "market_regime" in ind:
        mr = ind["market_regime"]
        mc = "text-emerald-600" if "bull" in mr else "text-red-600" if "bear" in mr else "text-gray-600"
        ind_rows += f'<div class="flex justify-between py-1.5"><span class="text-gray-500">Regime</span><span class="{mc} font-semibold">{mr.replace("_"," ").title()}</span></div>'

    two_col = f'''<div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
      <div class="glass rounded-xl p-5">
        <h3 class="text-sm font-semibold text-gray-800 uppercase tracking-wider mb-3">Detected Patterns</h3>
        <div class="flex flex-wrap gap-2 mb-3">{pat_badges}</div>
        <p class="text-xs text-gray-400">Confidence: <strong>{conf_pct}</strong> | Volume Confirmed: {vol_icon}</p>
      </div>
      <div class="glass rounded-xl p-5">
        <h3 class="text-sm font-semibold text-gray-800 uppercase tracking-wider mb-3">Technical Context</h3>
        <div class="text-sm">{ind_rows}</div>
      </div>
    </div>'''

    # Trade Recommendation Banner
    direction = r["direction"]
    is_no_trade = r["is_no_trade"]
    edge = r["edge"]
    conf = r["confidence"]
    se = r["stat_extras"]
    trade = r["trade"]

    if is_no_trade:
        banner = f'''<div class="rounded-xl bg-amber-50 border-2 border-amber-300 p-6 text-center mb-6">
          <h2 class="text-2xl font-bold text-amber-700 mb-1">NO TRADE — Insufficient Edge</h2>
          <p class="text-amber-600">Edge: <strong>{edge:+.1f}%</strong> (need &gt;8.5%) | Confidence: <strong>{conf.get("level","LOW")}</strong></p>
          <p class="text-sm text-amber-500 mt-1">No statistically significant directional bias after base-rate correction.</p>
        </div>'''
        trade_cards = ""
    else:
        if direction == "BULLISH":
            bg, border, text_c = "bg-emerald-50", "border-emerald-300", "text-emerald-700"
            signal = "BUY / LONG"
        else:
            bg, border, text_c = "bg-red-50", "border-red-300", "text-red-700"
            signal = "SELL / SHORT"
        edge_display = se.get("bullish_edge", 0) if direction == "BULLISH" else se.get("bearish_edge", 0)
        conf_level = conf.get("level", "MEDIUM")
        conf_badge = badge(conf_level, "success" if conf_level == "HIGH" else "warning" if conf_level == "MEDIUM" else "danger")

        banner = f'''<div class="rounded-xl {bg} border-2 {border} p-6 text-center mb-6">
          <h2 class="text-2xl font-bold {text_c} mb-1">{signal}</h2>
          <p class="{text_c}">Edge: <strong>{edge_display:+.1f}%</strong> vs base rate | Confidence: {conf_badge}</p>
        </div>'''

        # Trade levels
        tgt_pct = (trade["target_recommended"] - trade["entry"]) / trade["entry"] * 100
        sl_pct_change = (trade["stop_loss_recommended"] - trade["entry"]) / trade["entry"] * 100
        rr = r["prediction"].get("risk_reward", {})
        sl_info = ""
        if trade.get("sl_pct"):
            sl_label = "structural (candle invalidation)" if trade["sl_type"] == "structural" else f'{trade["sl_multiplier"]}x ATR'
            sl_info = f'<p class="text-xs text-gray-500 mt-3">Stop-loss: <strong>{trade["sl_pct"]:.2f}%</strong> ({sl_label}) — SL triggers on {se.get("sl_triggers_pct",0):.0f}% of similar trades</p>'

        trade_cards = f'''<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-2">
          {stat_card("Entry", _price(trade["entry"]), "", "indigo")}
          {stat_card("Target", _price(trade["target_recommended"]), _pct(tgt_pct), "green")}
          {stat_card("Stop Loss", _price(trade["stop_loss_recommended"]), _pct(sl_pct_change), "red")}
          {stat_card("R:R", f'1:{rr.get("risk_reward_ratio","N/A")}', "", "cyan")}
        </div>{sl_info}'''

    # Stat metrics
    stat_metrics = ""
    if se:
        stat_metrics = f'''<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 mt-4">
          {stat_card("Win Rate (w/ SL)", f'{se.get("sl_win_rate",0):.1f}%', "", "green" if se.get("sl_win_rate",0) >= 55 else "amber")}
          {stat_card("Profit Factor (w/ SL)", f'{se.get("sl_profit_factor",0):.2f}', "", "green" if se.get("sl_profit_factor",0) >= 1.5 else "amber")}
          {stat_card("Match Tier", se.get("match_tier","N/A").replace("_"," ").title(), "", "indigo")}
          {stat_card("Instruments", se.get("instrument_diversity",0), "", "cyan")}
        </div>'''

    # AI Analysis
    ai_html = f'''<div class="glass rounded-xl p-6 mb-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">AI Analysis (Ollama)</h3>
      <div class="text-sm text-gray-700 leading-relaxed">{_md(r["llm_analysis"])}</div>
    </div>'''

    # Forward Returns (collapsible)
    horizons = r["prediction"].get("horizons", {})
    hz_rows = ""
    for hk, hd in horizons.items():
        dir_badge = badge(hd["direction"], "bullish" if hd["direction"] == "BULLISH" else "bearish" if hd["direction"] == "BEARISH" else "default")
        hz_rows += f'''<tr class="border-b border-gray-100 hover:bg-blue-50/50">
          <td class="px-4 py-2 font-medium text-gray-800">{_e(hk)}</td>
          <td class="px-4 py-2 text-center">{dir_badge}</td>
          <td class="px-4 py-2 text-right">{hd.get("bullish_pct","?")}%</td>
          <td class="px-4 py-2 text-right">{hd.get("bullish_edge",0):+.1f}%</td>
          <td class="px-4 py-2 text-right">{hd.get("bearish_edge",0):+.1f}%</td>
          <td class="px-4 py-2 text-right">{hd.get("avg_return_pct",0):+.4f}%</td>
          <td class="px-4 py-2 text-right text-gray-500">{hd.get("count","?")}</td>
        </tr>'''
    fwd_returns = f'''<div class="glass rounded-xl overflow-hidden mb-6">
      <button onclick="this.nextElementSibling.classList.toggle('hidden'); this.querySelector('span').textContent = this.nextElementSibling.classList.contains('hidden') ? 'Show' : 'Hide'"
              class="w-full px-5 py-3 bg-gray-50 border-b border-gray-200 text-left text-sm font-semibold text-gray-700 hover:bg-gray-100 transition flex items-center justify-between">
        Historical Forward Returns <span class="text-blue-500 text-xs">Show</span>
      </button>
      <div class="hidden overflow-x-auto scrollbar-thin">
        <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Horizon</th>
          <th class="px-4 py-2 text-center text-xs text-gray-500 uppercase">Direction</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Bullish %</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Bull Edge</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Bear Edge</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Avg Return</th>
          <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Samples</th>
        </tr></thead><tbody>{hz_rows}</tbody></table>
      </div>
    </div>'''

    # Feedback Section
    feedback_html = f'''<div class="glass rounded-xl p-6 mb-6" id="feedback">
      <h3 class="text-lg font-semibold text-gray-800 mb-2">Was this prediction correct?</h3>
      <p class="text-xs text-gray-400 mb-4">Your feedback trains the AI to make better predictions.</p>
      <div class="flex gap-4 mb-4">
        <form method="POST" action="/feedback">
          <input type="hidden" name="was_correct" value="true">
          <button type="submit" class="px-6 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white font-semibold rounded-lg transition shadow-sm">
            Correct
          </button>
        </form>
        <button id="btn-wrong" onclick="document.getElementById('wrong-form').classList.toggle('hidden')"
                class="px-6 py-2.5 bg-red-500 hover:bg-red-600 text-white font-semibold rounded-lg transition shadow-sm">
          Not Correct
        </button>
      </div>
      <div id="wrong-form" class="hidden border-t border-gray-200 pt-4 mt-2">
        <form method="POST" action="/feedback">
          <input type="hidden" name="was_correct" value="false">
          <p class="text-sm font-medium text-gray-700 mb-3">What went wrong?</p>
          <div class="space-y-2 mb-4">
            <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="radio" name="wrong_reason" value="Direction was opposite" checked class="text-blue-500"> Direction was opposite</label>
            <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="radio" name="wrong_reason" value="Target too aggressive" class="text-blue-500"> Target too aggressive (didn't reach)</label>
            <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="radio" name="wrong_reason" value="Stop loss too tight" class="text-blue-500"> Stop loss too tight (hit SL then reversed)</label>
            <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="radio" name="wrong_reason" value="Timing off" class="text-blue-500"> Timing off (eventually correct, too slow)</label>
            <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="radio" name="wrong_reason" value="News/event overrode pattern" class="text-blue-500"> News/event overrode the pattern</label>
            <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input type="radio" name="wrong_reason" value="Pattern incorrectly detected" class="text-blue-500"> Pattern incorrectly detected</label>
          </div>
          <textarea name="notes" rows="2" placeholder="Tell the AI what actually happened..."
                    class="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm focus:border-blue-400 outline-none mb-3"></textarea>
          <button type="submit" class="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition text-sm">
            Submit Feedback
          </button>
        </form>
      </div>
    </div>'''

    # Chat Section
    chat_msgs = ""
    for msg in _analysis["chat_history"]:
        if msg["role"] == "user":
            chat_msgs += f'''<div class="flex justify-end mb-3">
              <div class="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 max-w-[80%]">
                <p class="text-xs text-blue-400 mb-1 font-medium">You</p>
                <p class="text-sm text-gray-800">{_e(msg["content"])}</p>
              </div></div>'''
        else:
            chat_msgs += f'''<div class="flex justify-start mb-3">
              <div class="bg-white border border-gray-200 rounded-lg px-4 py-3 max-w-[80%] shadow-sm">
                <p class="text-xs text-blue-500 mb-1 font-medium">Traqo AI</p>
                <div class="text-sm text-gray-700">{_md(msg["content"])}</div>
              </div></div>'''

    scroll_js = "document.getElementById('chat-area').scrollTop = document.getElementById('chat-area').scrollHeight;" if _analysis["chat_history"] else ""
    chat_html = f'''<div class="glass rounded-xl p-6" id="chat">
      <h3 class="text-lg font-semibold text-gray-800 mb-2">Ask Follow-Up Questions</h3>
      <p class="text-xs text-gray-400 mb-4">Chat with the AI about this analysis — risk, alternatives, deeper reasoning.</p>
      <div id="chat-area" class="max-h-96 overflow-y-auto scrollbar-thin mb-4 space-y-1">{chat_msgs if chat_msgs else '<p class="text-sm text-gray-400 italic text-center py-8">No messages yet. Ask a question about this trade setup.</p>'}</div>
      <form method="POST" action="/chat" id="chat-form" class="flex gap-3">
        <input type="text" name="message" placeholder="Ask about this trade setup..."
               class="flex-1 px-4 py-2.5 rounded-lg border border-gray-300 focus:border-blue-400 outline-none text-sm" required>
        <button type="submit" id="chat-btn" class="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition text-sm">Send</button>
      </form>
    </div>
    <script>
    {scroll_js}
    document.getElementById('chat-form').addEventListener('submit', function() {{
      var btn = document.getElementById('chat-btn');
      btn.disabled = true; btn.textContent = 'Thinking...';
      btn.classList.add('opacity-60');
    }});
    </script>'''

    cached_badge = ""
    reanalyze_btn = ""
    if r.get("_cached"):
        cached_badge = f' <span class="ml-2 px-2 py-0.5 text-xs font-medium bg-amber-100 text-amber-700 rounded-full">Cached ({r.get("_cache_age","")})</span>'
        reanalyze_btn = f'''<form method="POST" action="/analyze" class="inline">
          <input type="hidden" name="ticker" value="{_e(r['ticker'])}">
          <input type="hidden" name="timeframe" value="{_e(r.get('timeframe','1d'))}">
          <input type="hidden" name="force" value="1">
          <button type="submit" class="text-xs text-blue-500 hover:text-blue-700 underline">Re-analyze (fresh)</button>
        </form>'''

    body = f'''
    <div class="flex items-center justify-between mb-1">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Analysis: {_e(r["ticker"])}{cached_badge}</h2>
        <p class="text-sm text-gray-500">Analyzed at {_e(r["timestamp"])} {reanalyze_btn}</p>
      </div>
      <a href="/analyze" class="text-sm text-gray-400 hover:text-gray-800 transition">New Analysis</a>
    </div>
    <div class="mb-6"></div>
    {flash}{form}
    {price_cards}
    {two_col}
    {banner}
    {trade_cards}
    {stat_metrics}
    {ai_html}
    {fwd_returns}
    {feedback_html}
    {chat_html}'''

    return page_shell(f"Analysis: {r['ticker']}", "analyze", body)


# ============================================================
# PAGE: BATCH RESULTS
# ============================================================
def render_batch_results():
    br = _batch_results
    if not br["results"] and not br["running"]:
        return render_analyze()

    group_key = br.get("group", "?")
    results = br["results"]
    label = NIFTY_GROUP_LABELS.get(group_key, f"Custom ({len(results)} stocks)")
    ts = datetime.now().strftime("%H:%M on %d %b %Y")

    # Summary stats
    ok_results = [r for r in results if not r.get("error") or r.get("direction") != "ERROR"]
    buy_list = [r for r in ok_results if r.get("direction") == "BULLISH" and not r.get("is_no_trade")]
    sell_list = [r for r in ok_results if r.get("direction") == "BEARISH" and not r.get("is_no_trade")]
    neutral_list = [r for r in ok_results if r.get("is_no_trade") or r.get("direction") == "NEUTRAL"]
    err_list = [r for r in results if r.get("direction") == "ERROR"]

    summary_cards = f'''<div class="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
      {stat_card("Total Analyzed", str(len(results)), f"of {br['total']}", "indigo")}
      {stat_card("BUY Signals", str(len(buy_list)), "", "emerald")}
      {stat_card("SELL Signals", str(len(sell_list)), "", "red")}
      {stat_card("Neutral / Avoid", str(len(neutral_list)), "", "gray")}
      {stat_card("Errors", str(len(err_list)), "", "amber")}
    </div>'''

    # ── BUY signals table ──
    buy_html = ""
    if buy_list:
        buy_rows = ""
        for r in sorted(buy_list, key=lambda x: x.get("edge", 0), reverse=True):
            se = r.get("stat_extras", {})
            conf = r.get("confidence", {})
            trade = r.get("trade", {})
            pats = ", ".join(r.get("patterns", [])[:2])
            chg_cls = "text-emerald-600" if r.get("change_pct", 0) >= 0 else "text-red-600"
            buy_rows += f'''<tr class="border-b border-gray-100 hover:bg-emerald-50/50">
              <td class="py-3 px-4 font-semibold text-gray-800">
                <a href="#" onclick="document.querySelector('[name=ticker]').value='{_e(r['ticker'])}';document.getElementById('analyze-form').submit();return false;"
                   class="text-blue-600 hover:underline">{_e(r['ticker'])}</a>
              </td>
              <td class="py-3 px-4">{_price(r.get('current_price',0))}</td>
              <td class="py-3 px-4 {chg_cls}">{_pct(r.get('change_pct',0))}</td>
              <td class="py-3 px-4"><span class="text-xs bg-emerald-100 text-emerald-700 px-2 py-1 rounded-full font-medium">BUY</span></td>
              <td class="py-3 px-4 text-xs text-gray-600">{_e(pats)}</td>
              <td class="py-3 px-4">{_price(trade.get('entry',0))}</td>
              <td class="py-3 px-4 text-emerald-600">{_price(trade.get('target_recommended',0))}</td>
              <td class="py-3 px-4 text-red-500">{_price(trade.get('stop_loss_recommended',0))}</td>
              <td class="py-3 px-4">{se.get('win_rate','—')}%</td>
              <td class="py-3 px-4">{se.get('profit_factor','—')}</td>
              <td class="py-3 px-4">{conf.get('level','—')}</td>
            </tr>'''
        buy_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-bold text-emerald-700 mb-3">BUY Signals ({len(buy_list)})</h3>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-500 uppercase tracking-wider border-b-2 border-gray-200">
                <th class="py-2 px-4">Ticker</th><th class="py-2 px-4">Price</th><th class="py-2 px-4">Chg%</th>
                <th class="py-2 px-4">Signal</th><th class="py-2 px-4">Patterns</th><th class="py-2 px-4">Entry</th>
                <th class="py-2 px-4">Target</th><th class="py-2 px-4">SL</th><th class="py-2 px-4">WR%</th>
                <th class="py-2 px-4">PF</th><th class="py-2 px-4">Conf</th>
              </tr></thead>
              <tbody>{buy_rows}</tbody>
            </table>
          </div>
        </div>'''

    # ── SELL signals table ──
    sell_html = ""
    if sell_list:
        sell_rows = ""
        for r in sorted(sell_list, key=lambda x: x.get("edge", 0), reverse=True):
            se = r.get("stat_extras", {})
            conf = r.get("confidence", {})
            trade = r.get("trade", {})
            pats = ", ".join(r.get("patterns", [])[:2])
            chg_cls = "text-emerald-600" if r.get("change_pct", 0) >= 0 else "text-red-600"
            sell_rows += f'''<tr class="border-b border-gray-100 hover:bg-red-50/50">
              <td class="py-3 px-4 font-semibold text-gray-800">
                <a href="#" onclick="document.querySelector('[name=ticker]').value='{_e(r['ticker'])}';document.getElementById('analyze-form').submit();return false;"
                   class="text-blue-600 hover:underline">{_e(r['ticker'])}</a>
              </td>
              <td class="py-3 px-4">{_price(r.get('current_price',0))}</td>
              <td class="py-3 px-4 {chg_cls}">{_pct(r.get('change_pct',0))}</td>
              <td class="py-3 px-4"><span class="text-xs bg-red-100 text-red-700 px-2 py-1 rounded-full font-medium">SELL</span></td>
              <td class="py-3 px-4 text-xs text-gray-600">{_e(pats)}</td>
              <td class="py-3 px-4">{_price(trade.get('entry',0))}</td>
              <td class="py-3 px-4 text-emerald-600">{_price(trade.get('target_recommended',0))}</td>
              <td class="py-3 px-4 text-red-500">{_price(trade.get('stop_loss_recommended',0))}</td>
              <td class="py-3 px-4">{se.get('win_rate','—')}%</td>
              <td class="py-3 px-4">{se.get('profit_factor','—')}</td>
              <td class="py-3 px-4">{conf.get('level','—')}</td>
            </tr>'''
        sell_html = f'''
        <div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-bold text-red-700 mb-3">SELL Signals ({len(sell_list)})</h3>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-500 uppercase tracking-wider border-b-2 border-gray-200">
                <th class="py-2 px-4">Ticker</th><th class="py-2 px-4">Price</th><th class="py-2 px-4">Chg%</th>
                <th class="py-2 px-4">Signal</th><th class="py-2 px-4">Patterns</th><th class="py-2 px-4">Entry</th>
                <th class="py-2 px-4">Target</th><th class="py-2 px-4">SL</th><th class="py-2 px-4">WR%</th>
                <th class="py-2 px-4">PF</th><th class="py-2 px-4">Conf</th>
              </tr></thead>
              <tbody>{sell_rows}</tbody>
            </table>
          </div>
        </div>'''

    # ── Neutral / Avoid table ──
    neutral_html = ""
    if neutral_list:
        n_rows = ""
        for r in neutral_list:
            pats = ", ".join(r.get("patterns", [])[:2])
            chg_cls = "text-emerald-600" if r.get("change_pct", 0) >= 0 else "text-red-600"
            n_rows += f'''<tr class="border-b border-gray-100">
              <td class="py-2 px-4 text-gray-600">{_e(r.get('ticker',''))}</td>
              <td class="py-2 px-4">{_price(r.get('current_price',0))}</td>
              <td class="py-2 px-4 {chg_cls}">{_pct(r.get('change_pct',0))}</td>
              <td class="py-2 px-4"><span class="text-xs bg-gray-100 text-gray-600 px-2 py-1 rounded-full">NEUTRAL</span></td>
              <td class="py-2 px-4 text-xs text-gray-500">{_e(pats)}</td>
            </tr>'''
        neutral_html = f'''
        <details class="glass rounded-xl p-6 mb-6">
          <summary class="cursor-pointer text-lg font-bold text-gray-600">Neutral / Avoid ({len(neutral_list)}) <span class="text-sm font-normal text-gray-400">— click to expand</span></summary>
          <div class="overflow-x-auto mt-3">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-500 uppercase tracking-wider border-b-2 border-gray-200">
                <th class="py-2 px-4">Ticker</th><th class="py-2 px-4">Price</th><th class="py-2 px-4">Chg%</th>
                <th class="py-2 px-4">Signal</th><th class="py-2 px-4">Patterns</th>
              </tr></thead>
              <tbody>{n_rows}</tbody>
            </table>
          </div>
        </details>'''

    # ── Errors ──
    err_html = ""
    if err_list:
        e_rows = "".join(f'<tr class="border-b border-gray-100"><td class="py-2 px-4 text-gray-600">{_e(r.get("ticker",""))}</td><td class="py-2 px-4 text-red-500 text-xs">{_e(r.get("error",""))}</td></tr>' for r in err_list)
        err_html = f'''
        <details class="glass rounded-xl p-6 mb-6">
          <summary class="cursor-pointer text-lg font-bold text-amber-600">Errors ({len(err_list)}) <span class="text-sm font-normal text-gray-400">— click to expand</span></summary>
          <div class="overflow-x-auto mt-3">
            <table class="w-full text-sm">
              <thead><tr class="text-left text-xs text-gray-500 uppercase border-b-2 border-gray-200">
                <th class="py-2 px-4">Ticker</th><th class="py-2 px-4">Error</th>
              </tr></thead>
              <tbody>{e_rows}</tbody>
            </table>
          </div>
        </details>'''

    body = f'''
    <div class="flex items-center justify-between mb-1">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">Batch Analysis: {_e(label)}</h2>
        <p class="text-sm text-gray-500">Completed at {_e(ts)}</p>
      </div>
      <a href="/analyze" class="text-sm text-blue-600 hover:text-blue-800 font-medium transition">&larr; Back to Analyze</a>
    </div>
    <div class="mb-6"></div>
    {summary_cards}
    {buy_html}
    {sell_html}
    {neutral_html}
    {err_html}
    '''
    return page_shell(f"Batch: {label}", "analyze", body)


# ============================================================
# PAGE: FEEDBACK HISTORY
# ============================================================
def render_feedback():
    stats = get_feedback_stats()
    fb_list = load_feedback()

    if not stats:
        empty = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <p class="text-lg font-medium text-gray-500">No feedback yet</p>
          <p class="text-sm text-gray-400 mt-1">Analyze stocks and provide feedback to start training the AI.</p>
        </div>'''
        body = f'<h2 class="text-2xl font-bold text-gray-800 mb-6">Feedback History</h2>{empty}'
        return page_shell("Feedback", "feedback", body)

    cards = f'''<div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
      {stat_card("Total", stats["total"], "", "indigo")}
      {stat_card("Correct", stats["correct"], "", "green")}
      {stat_card("Incorrect", stats["total"] - stats["correct"], "", "red")}
      {stat_card("Accuracy", f'{stats["accuracy"]}%', "", "green" if stats["accuracy"] >= 60 else "amber")}
    </div>'''

    # Error breakdown
    err_html = ""
    if stats["wrong_reasons"]:
        err_rows = ""
        for reason, count in sorted(stats["wrong_reasons"].items(), key=lambda x: x[1], reverse=True):
            pct = count / max(1, stats["total"] - stats["correct"]) * 100
            err_rows += f'''<tr class="border-b border-gray-100">
              <td class="px-4 py-2 text-gray-700 text-sm">{_e(reason)}</td>
              <td class="px-4 py-2 text-right font-semibold text-gray-800">{count}</td>
              <td class="px-4 py-2 text-right text-gray-500">{pct:.0f}%</td>
            </tr>'''
        err_html = f'''<div class="glass rounded-xl p-6 mb-6">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">Common Error Reasons</h3>
          <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
            <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Reason</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">Count</th>
            <th class="px-4 py-2 text-right text-xs text-gray-500 uppercase">%</th>
          </tr></thead><tbody>{err_rows}</tbody></table>
        </div>'''

    # Recent feedback table
    rows = ""
    for f in reversed(fb_list[-50:]):
        status = badge("Correct", "success") if f.get("was_correct") else badge("Wrong", "danger")
        pats = ", ".join(f.get("patterns", [])) if isinstance(f.get("patterns"), list) else str(f.get("patterns", ""))
        rows += f'''<tr class="border-b border-gray-100 hover:bg-blue-50/50">
          <td class="px-4 py-2 text-xs text-gray-500">{_e(f.get("timestamp","")[:16])}</td>
          <td class="px-4 py-2 font-semibold text-gray-800">{_e(f.get("ticker",""))}</td>
          <td class="px-4 py-2">{badge(f.get("direction",""), "bullish" if f.get("direction") == "BULLISH" else "bearish")}</td>
          <td class="px-4 py-2">{status}</td>
          <td class="px-4 py-2 text-xs text-gray-500 max-w-[200px] truncate">{_e(f.get("wrong_reason",""))}</td>
          <td class="px-4 py-2 text-xs text-gray-500 max-w-[150px] truncate">{_e(pats)}</td>
        </tr>'''
    table = f'''<div class="glass rounded-xl overflow-hidden">
      <div class="px-5 py-3 bg-gray-50 border-b border-gray-200">
        <h3 class="text-sm font-semibold text-gray-800">Recent Feedback ({min(50, len(fb_list))} of {len(fb_list)})</h3>
      </div>
      <div class="overflow-x-auto scrollbar-thin">
        <table class="w-full text-sm"><thead><tr class="border-b border-gray-200">
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Time</th>
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Ticker</th>
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Direction</th>
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Result</th>
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Reason</th>
          <th class="px-4 py-2 text-left text-xs text-gray-500 uppercase">Patterns</th>
        </tr></thead><tbody>{rows}</tbody></table>
      </div>
    </div>'''

    body = f'''<h2 class="text-2xl font-bold text-gray-800 mb-6">Feedback History</h2>
    {cards}{err_html}{table}'''
    return page_shell("Feedback", "feedback", body)


# ============================================================
# PAGE: LEARNING
# ============================================================
def render_learning(params=None):
    params = params or {}
    flash = _flash_html(params)
    rules = load_learned_rules()
    stats = get_feedback_stats()

    fb_count = stats["total"] if stats else 0
    btn_disabled = "opacity-50 cursor-not-allowed" if fb_count < 3 else ""

    relearn_btn = f'''<form method="POST" action="/learning" class="mb-6">
      <button type="submit" class="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition shadow-sm {btn_disabled}"
              {"disabled" if fb_count < 3 else ""}>
        Re-learn from Feedback ({fb_count} entries)
      </button>
    </form>'''

    if not rules:
        empty = '''<div class="flex flex-col items-center justify-center py-16 text-center">
          <svg class="w-16 h-16 text-gray-300 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
          </svg>
          <p class="text-lg font-medium text-gray-500">No learned rules yet</p>
          <p class="text-sm text-gray-400 mt-1">Provide at least 3 feedback entries, then click Re-learn.</p>
        </div>'''
        body = f'''<h2 class="text-2xl font-bold text-gray-800 mb-2">Learned Rules</h2>
          <p class="text-sm text-gray-500 mb-6">AI-extracted trading rules from your feedback</p>
          {flash}{relearn_btn}{empty}'''
        return page_shell("Learning", "learning", body)

    rule_cards = ""
    for rule in rules:
        rt = rule.get("type", "info")
        icon_map = {"avoid": ("text-red-500", "bg-red-50"), "prefer": ("text-emerald-500", "bg-emerald-50"),
                    "adjust": ("text-blue-500", "bg-blue-50"), "info": ("text-gray-500", "bg-gray-50")}
        ic, ibg = icon_map.get(rt, icon_map["info"])
        conf = rule.get("confidence", 0)
        try:
            conf = float(conf)
            conf_str = f"{conf:.0%}"
        except (TypeError, ValueError):
            conf_str = str(conf)
        rule_cards += f'''<div class="glass rounded-xl p-5 mb-3">
          <div class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-lg {ibg} flex items-center justify-center text-sm font-bold {ic} flex-shrink-0 mt-0.5">
              {"✗" if rt == "avoid" else "✓" if rt == "prefer" else "⟳" if rt == "adjust" else "i"}
            </div>
            <div class="flex-1">
              <p class="text-sm text-gray-800">{_e(rule.get("rule", ""))}</p>
              <div class="flex gap-3 mt-2">
                {badge(rt.upper(), "danger" if rt == "avoid" else "success" if rt == "prefer" else "info")}
                <span class="text-xs text-gray-400">Confidence: {conf_str}</span>
                <span class="text-xs text-gray-400">{_e(rule.get("context",""))}</span>
              </div>
            </div>
          </div>
        </div>'''

    body = f'''<h2 class="text-2xl font-bold text-gray-800 mb-2">Learned Rules</h2>
      <p class="text-sm text-gray-500 mb-6">AI-extracted trading rules from your feedback — {len(rules)} rules</p>
      {flash}{relearn_btn}{rule_cards}'''
    return page_shell("Learning", "learning", body)


# ============================================================
# PAGE: SETTINGS
# ============================================================
def render_settings(params=None):
    params = params or {}
    flash = _flash_html(params)
    ollama_ok, models = _get_ollama_status()

    status_card_html = ""
    if ollama_ok:
        model_list = ", ".join(models[:8]) if models else "No models found"
        status_card_html = f'''<div class="glass rounded-xl p-6 mb-6 border-emerald-200">
          <div class="flex items-center gap-3 mb-3">
            <div class="w-3 h-3 rounded-full bg-emerald-500 pulse-dot"></div>
            <h3 class="text-lg font-semibold text-emerald-700">Ollama Connected</h3>
          </div>
          <p class="text-sm text-gray-600">Available models: <strong>{_e(model_list)}</strong></p>
        </div>'''
    else:
        status_card_html = '''<div class="glass rounded-xl p-6 mb-6 border-red-200">
          <div class="flex items-center gap-3 mb-3">
            <div class="w-3 h-3 rounded-full bg-red-400"></div>
            <h3 class="text-lg font-semibold text-red-700">Ollama Offline</h3>
          </div>
          <p class="text-sm text-gray-600">Start Ollama and pull a model: <code class="bg-gray-100 px-2 py-0.5 rounded text-xs">ollama pull qwen2.5:7b</code></p>
        </div>'''

    model_form = f'''<div class="glass rounded-xl p-6 mb-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">Model Configuration</h3>
      <form method="POST" action="/settings">
        <div class="flex gap-4 items-end">
          <div class="flex-1">
            <label class="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Active Model</label>
            <input type="text" name="model" value="{_e(_active_model_name)}"
                   class="w-full px-4 py-3 rounded-lg border border-gray-300 focus:border-blue-400 outline-none text-gray-800 font-mono">
          </div>
          <button type="submit" class="px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition">Save</button>
        </div>
        <p class="text-xs text-gray-400 mt-2">Examples: qwen2.5:7b, mistral, llama3.2, qwen3:4b</p>
      </form>
    </div>'''

    # System info
    sp_status = "Loaded" if _stat_predictor is not None else "Not loaded (loads on first analysis)"
    sys_info = f'''<div class="glass rounded-xl p-6">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">System Info</h3>
      <div class="space-y-2 text-sm">
        <div class="flex justify-between py-1.5 border-b border-gray-100">
          <span class="text-gray-500">Statistical Predictor</span>
          <span class="text-gray-700">{sp_status}</span>
        </div>
        <div class="flex justify-between py-1.5 border-b border-gray-100">
          <span class="text-gray-500">Feedback File</span>
          <span class="text-gray-700 font-mono text-xs">{_e(FEEDBACK_FILE)}</span>
        </div>
        <div class="flex justify-between py-1.5 border-b border-gray-100">
          <span class="text-gray-500">Learning File</span>
          <span class="text-gray-700 font-mono text-xs">{_e(LEARNING_FILE)}</span>
        </div>
        <div class="flex justify-between py-1.5 border-b border-gray-100">
          <span class="text-gray-500">Port</span>
          <span class="text-gray-700">{PORT}</span>
        </div>
        <div class="flex justify-between py-1.5">
          <span class="text-gray-500">Paper Trading Dashboard</span>
          <a href="http://localhost:8521" target="_blank" class="text-blue-500 hover:underline">http://localhost:8521</a>
        </div>
      </div>
    </div>'''

    body = f'''<h2 class="text-2xl font-bold text-gray-800 mb-2">Settings</h2>
      <p class="text-sm text-gray-500 mb-6">Configure Ollama and system parameters</p>
      {flash}{status_card_html}{model_form}{sys_info}'''
    return page_shell("Settings", "settings", body)


# ============================================================
# HTTP HANDLER
# ============================================================
class AnalyzerHandler(BaseHTTPRequestHandler):

    def _parse_post_body(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        return urllib.parse.parse_qs(body)

    def _send_html(self, html, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _redirect(self, path):
        self.send_response(302)
        self.send_header("Location", path)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")
        params = urllib.parse.parse_qs(parsed.query)

        try:
            if path in ("", "analyze"):
                self._send_html(render_analyze(params))
            elif path == "batch":
                self._send_html(render_batch_results())
            elif path == "feedback":
                self._send_html(render_feedback())
            elif path == "learning":
                self._send_html(render_learning(params))
            elif path == "settings":
                self._send_html(render_settings(params))
            elif path == "favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self._redirect("/analyze")
        except Exception as e:
            self._send_html(f"<h1>Error</h1><pre>{_e(traceback.format_exc())}</pre>", 500)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.strip("/")

        try:
            if path == "analyze":
                form = self._parse_post_body()
                ticker_raw = form.get("ticker", [""])[0].strip()
                timeframe = form.get("timeframe", ["1d"])[0]
                force_fresh = form.get("force", ["0"])[0] == "1"
                if not ticker_raw:
                    self._redirect("/analyze")
                    return
                if force_fresh:
                    _clear_cache(ticker_raw.strip().upper())
                # Check for multi-ticker (comma-separated)
                tickers = [t.strip().upper() for t in ticker_raw.split(",") if t.strip()]
                if len(tickers) > 1:
                    # Batch mode
                    _batch_results["group"] = "custom"
                    _batch_results["results"] = []
                    _batch_results["running"] = True
                    _batch_results["total"] = len(tickers)
                    _batch_results["progress"] = 0
                    for i, tk in enumerate(tickers):
                        _batch_results["progress"] = i + 1
                        try:
                            res = run_analysis(tk, timeframe)
                            if res and not res.get("error"):
                                _batch_results["results"].append(res)
                            else:
                                _batch_results["results"].append({
                                    "ticker": tk, "error": res.get("error", "Failed") if res else "Failed",
                                    "direction": "ERROR", "current_price": 0, "change_pct": 0,
                                })
                        except Exception as ex:
                            _batch_results["results"].append({
                                "ticker": tk, "error": str(ex),
                                "direction": "ERROR", "current_price": 0, "change_pct": 0,
                            })
                    _batch_results["running"] = False
                    self._send_html(render_batch_results())
                else:
                    # Single ticker
                    result = run_analysis(tickers[0], timeframe)
                    _analysis["results"] = result
                    _analysis["chat_history"] = []
                    _analysis["analysis_context"] = result.get("analysis_context", "")
                    self._send_html(render_analyze())

            elif path == "feedback":
                form = self._parse_post_body()
                was_correct = form.get("was_correct", [""])[0] == "true"
                wrong_reason = form.get("wrong_reason", [None])[0]
                notes = form.get("notes", [None])[0]
                r = _analysis.get("results")
                if r and not r.get("error"):
                    pred_data = {
                        "patterns": r.get("patterns", []),
                        "direction": r.get("direction", ""),
                        "confidence_level": r.get("confidence_level", ""),
                        "n_matches": r.get("prediction", {}).get("n_matches", 0),
                    }
                    trade_data = r.get("trade", {})
                    reason = None if was_correct else (wrong_reason + (f" | Notes: {notes}" if notes else ""))
                    add_feedback(r["ticker"], pred_data, trade_data, was_correct, reason)
                self._redirect(f"/analyze?msg={'correct' if was_correct else 'wrong'}")

            elif path == "chat":
                form = self._parse_post_body()
                message = form.get("message", [""])[0].strip()
                if message and OLLAMA_AVAILABLE and _analysis.get("analysis_context"):
                    _analysis["chat_history"].append({"role": "user", "content": message})
                    response = ollama_chat_followup(
                        _analysis["chat_history"], _analysis["analysis_context"])
                    _analysis["chat_history"].append({"role": "assistant", "content": response})
                self._send_html(render_analyze())

            elif path == "learning":
                fb = load_feedback()
                if len(fb) >= 3 and OLLAMA_AVAILABLE:
                    rules = ollama_learn_from_feedback(fb)
                    save_learned_rules(rules)
                    self._redirect("/learning?msg=learned")
                else:
                    self._redirect("/learning?msg=learn_err")

            elif path == "settings":
                global _active_model_name
                form = self._parse_post_body()
                model = form.get("model", [OLLAMA_MODEL])[0].strip()
                if model:
                    _active_model_name = model
                self._redirect("/settings?msg=model_saved")

            else:
                self._redirect("/analyze")

        except Exception as e:
            self._send_html(f"<h1>Error</h1><pre>{_e(traceback.format_exc())}</pre>", 500)

    def log_message(self, fmt, *args):
        pass  # suppress default logging


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print(f"\n  Traqo — RAG Analyzer Dashboard")
    print(f"  http://localhost:{PORT}\n")

    server = ThreadedHTTPServer(("0.0.0.0", PORT), AnalyzerHandler)

    # Pre-load statistical predictor in background
    threading.Thread(target=_get_sp, daemon=True).start()

    try:
        webbrowser.open(f"http://localhost:{PORT}")
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
