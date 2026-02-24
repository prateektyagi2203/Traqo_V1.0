"""
Candlestick RAG Predictor — Ollama-Powered Conversational UI
=============================================================
Full pipeline with:
  - Ollama LLM for reasoning & conversation
  - Statistical predictor for pattern matching
  - Feedback loop that teaches the model what worked & what didn't
  - Conversational follow-ups (chat interface)
"""

import os
import json
import time
import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta
import warnings
import ollama
from candlestick_knowledge_base import get_pattern_context_text, get_reliability_rating, TRADING_PRINCIPLES
from pattern_detector import detect_live_patterns, detect_market_regime, get_recent_pattern_summary
from statistical_predictor import StatisticalPredictor
from trading_config import (
    EXCLUDED_PATTERNS, WHITELISTED_PATTERNS,
    STRUCTURAL_SL_PATTERNS, STRUCTURAL_SL_MULTIPLIER, STANDARD_SL_MULTIPLIER,
    ALLOWED_TIMEFRAMES, ALLOWED_INSTRUMENTS,
    is_tradeable_pattern, is_tradeable_instrument, is_tradeable_timeframe,
)

warnings.filterwarnings("ignore")

# ============================================================
# CONFIG
# ============================================================
FEEDBACK_FILE = "feedback/feedback_log.json"
LEARNING_FILE = "feedback/learned_rules.json"
TOP_K = 25
OLLAMA_MODEL = "qwen2.5:7b"  # Available: qwen2.5:7b, mistral, qwen3:4b, llava

os.makedirs("feedback", exist_ok=True)


def _active_model():
    """Return the currently selected Ollama model (session state or default)."""
    try:
        return st.session_state.get("ollama_model_active", OLLAMA_MODEL)
    except Exception:
        return OLLAMA_MODEL


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
- Be direct and data-driven, not wishy-washy
- Explain the psychology behind patterns (why buyers/sellers acted this way)
- Reference specific reliability ratings and contextual modifiers from the knowledge base
- Use specific numbers from the retrieved historical data
- Think like a professional trader who understands both theory and statistics
- Acknowledge uncertainty when pattern data or theory is conflicting

IMPORTANT: You now have expert-level pattern knowledge AND real historical data. Use BOTH in your analysis. Reference reliability ratings, contextual modifiers, and the psychology of each pattern alongside the empirical statistics."""

SYSTEM_PROMPT_CONVERSATION = """You are a trading assistant continuing a conversation about a stock analysis. You have deep knowledge of candlestick pattern theory (Nison, Bulkowski) and access to the original analysis data. You can answer follow-up questions about:
- Pattern psychology — why specific candle shapes indicate buyer/seller dynamics
- Why a particular entry/exit was recommended (backed by theory + data)
- What-if scenarios (e.g., "what if RSI was higher?" — reference the contextual modifiers)
- Pattern reliability ratings and when patterns are strong vs weak
- Risk management adjustments based on pattern theory
- Alternative trade setups
- How volume, trend, and session timing affect pattern reliability

Keep responses focused on the specific trade being discussed. Use both pattern theory AND data from the analysis context provided. If the user asks about a different stock, suggest they enter a new ticker."""

SYSTEM_PROMPT_LEARNING = """You are reviewing trading feedback data to extract actionable rules. Based on the feedback history (what predictions were correct vs incorrect), generate concise trading rules that the system should follow. Focus on:

1. Which patterns + context combinations are reliable vs unreliable
2. Common failure modes to avoid
3. Adjustments to target/stop loss levels based on actual outcomes
4. Time-of-day or day-of-week patterns in accuracy

Output your rules as a structured JSON array of rule objects with format:
{"rule": "description", "confidence": 0.0-1.0, "type": "avoid|prefer|adjust", "context": "when this applies"}"""


# ============================================================
# CANDLESTICK PATTERN DETECTOR  (uses shared pattern_detector module)
# ============================================================

def detect_patterns_on_df(df):
    """Detect patterns on the last candle using the shared module.
    Returns dict: {patterns: list, confidence: float, volume_confirmed: bool}
    Filters: excluded patterns (PF < 0.5) AND non-whitelisted patterns.
    """
    result = detect_live_patterns(df)
    # detect_live_patterns now returns a dict
    if isinstance(result, dict):
        pats = result.get("patterns", "none")
        pattern_list = [p.strip() for p in pats.split(",") if p.strip()] if pats != "none" else ["none"]
        # Filter: excluded patterns AND apply whitelist
        pattern_list = [p for p in pattern_list if is_tradeable_pattern(p)]
        if not pattern_list:
            pattern_list = ["none"]
        return {
            "patterns": pattern_list,
            "confidence": result.get("confidence", 0.0),
            "volume_confirmed": result.get("volume_confirmed", False),
        }
    # Fallback for legacy string return
    if result == "none":
        return {"patterns": ["none"], "confidence": 0.0, "volume_confirmed": False}
    return {
        "patterns": [p.strip() for p in result.split(",") if p.strip()],
        "confidence": 0.5,
        "volume_confirmed": False,
    }


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

def compute_live_indicators(df):
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else None
    indicators = {}

    for period in [9, 21, 50]:
        if len(close) >= period:
            indicators[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean().iloc[-1]

    if len(close) >= 15:
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        indicators["rsi_14"] = rsi.iloc[-1]

    if len(close) >= 15:
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        indicators["atr_14"] = tr.rolling(14).mean().iloc[-1]

    if volume is not None and len(volume) >= 21 and volume.sum() > 0:
        vol_ma = volume.rolling(20).mean().iloc[-1]
        if vol_ma > 0:
            indicators["vol_ratio"] = volume.iloc[-1] / vol_ma

    # VWAP (intraday volume-weighted average price)
    if volume is not None and volume.sum() > 0 and len(close) >= 2:
        try:
            typical_price = (high + low + close) / 3
            cum_tp_vol = (typical_price * volume).cumsum()
            cum_vol = volume.cumsum()
            vwap = cum_tp_vol / cum_vol
            vwap_val = vwap.iloc[-1]
            if pd.notna(vwap_val) and vwap_val > 0:
                indicators["vwap"] = float(vwap_val)
                indicators["price_vs_vwap"] = "above" if close.iloc[-1] > vwap_val else "below"
        except Exception:
            pass

    if "ema_9" in indicators and "ema_21" in indicators:
        indicators["trend_short"] = "bullish" if indicators["ema_9"] > indicators["ema_21"] else "bearish"
    if "ema_21" in indicators and "ema_50" in indicators:
        indicators["trend_medium"] = "bullish" if indicators["ema_21"] > indicators["ema_50"] else "bearish"

    if "rsi_14" in indicators:
        rsi_val = indicators["rsi_14"]
        indicators["rsi_zone"] = "oversold" if rsi_val < 30 else "overbought" if rsi_val > 70 else "neutral"

    if len(close) >= 2:
        indicators["gap_pct"] = ((df["Open"].iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)

    return indicators


# ============================================================
# STATISTICAL PREDICTION
# ============================================================

@st.cache_resource
def load_stat_predictor():
    """Load the statistical predictor (in-memory, metadata-based)."""
    return StatisticalPredictor()


def stat_predict_and_adapt(sp, patterns, timeframe=None, trend_short=None,
                           rsi_zone=None, price_vs_vwap=None,
                           market_regime=None, instrument=None):
    """Call StatisticalPredictor and adapt output to the dict format
    expected by compute_trade_levels, get_ollama_analysis, and the UI.

    Returns a dict with: {n_matches, avg_similarity, horizons, risk_reward,
       confidence, matches, pattern_breakdown, retrieved_documents,
       stat_extras: {win_rate, profit_factor, match_tier, edge, ...}}
    """
    tf_map = {"15m": "15min", "1d": "daily"}
    tf_db = tf_map.get(timeframe, timeframe)

    patterns_str = ",".join(patterns) if isinstance(patterns, list) else patterns
    pred = sp.predict_multi_pattern(
        patterns_str,
        timeframe=tf_db,
        trend_short=trend_short,
        rsi_zone=rsi_zone,
        price_vs_vwap=price_vs_vwap,
        market_regime=market_regime,
        instrument=instrument,
    )

    if pred is None:
        return None

    # --- Adapt horizons ---
    adapted_horizons = {}
    for hkey, hdata in pred.get("horizons", {}).items():
        direction_upper = hdata["direction"].upper()
        if direction_upper == "NEUTRAL":
            direction_upper = "NEUTRAL"
        adapted_horizons[hkey] = {
            "avg_return_pct": hdata["avg_return"],
            "median_return_pct": hdata["median_return"],
            "std_return_pct": hdata["std_return"],
            "bullish_pct": hdata["bullish_pct"],
            "bearish_pct": hdata["bearish_pct"],
            "direction": direction_upper,
            "count": hdata["count"],
            # New fields from stat predictor
            "bullish_edge": hdata["bullish_edge"],
            "bearish_edge": hdata["bearish_edge"],
        }

    # --- Build adapted prediction dict ---
    prediction = {
        "n_matches": pred["n_matches"],
        "avg_similarity": pred["confidence_score"],  # substitute confidence for similarity
        "horizons": adapted_horizons,
        "risk_reward": {
            "avg_mfe_pct": pred["avg_mfe"],
            "avg_mae_pct": pred["avg_mae"],
            "risk_reward_ratio": pred["rr_ratio"],
        },
        "confidence": {
            "score": pred["confidence_score"],
            "level": pred["confidence_level"],
        },
        "matches": [],  # no individual matches from stat predictor
        "pattern_breakdown": {pred["pattern"]: pred["n_matches"]},
        "retrieved_documents": [],  # no raw docs needed
        # Extra statistical metrics for the UI
        "stat_extras": {
            "win_rate": pred["win_rate"],
            "profit_factor": pred["profit_factor"],
            "match_tier": pred["match_tier"],
            "bullish_edge": pred["bullish_edge"],
            "bearish_edge": pred["bearish_edge"],
            "instrument_diversity": pred.get("instrument_diversity", 0),
            "top_instruments": pred.get("top_instruments", {}),
            "predicted_direction": pred["predicted_direction"],
            "sl_win_rate": pred.get("sl_win_rate", pred["win_rate"]),
            "sl_profit_factor": pred.get("sl_profit_factor", pred["profit_factor"]),
            "sl_triggers_pct": pred.get("sl_triggers_pct", 0),
        },
    }

    return prediction


def compute_trade_levels(current_price, prediction, atr, direction, patterns=None, df=None):
    """Compute entry, target, and stop-loss levels.
    
    Stop-loss: Tiered system —
      Tier A (structural patterns): 2.0x ATR or candle-based structural SL
      Tier B (standard patterns): 1.5x ATR
    Target: Uses historical MFE, with ATR-based as reference.
    Recommended: Weighted blend (ATR-primary for SL, data-primary for target).
    """
    rr = prediction.get("risk_reward", {})
    avg_mfe = rr.get("avg_mfe_pct", 0.5)
    avg_mae = rr.get("avg_mae_pct", -0.3)

    # Determine SL tier based on patterns
    pat_set = set(patterns) if patterns else set()
    is_structural = bool(pat_set & STRUCTURAL_SL_PATTERNS)
    sl_multiplier = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER

    # ATR-based stop loss (tiered multiplier, floor 0.3%, cap 5%)
    if atr and atr > 0:
        atr_sl_pct = sl_multiplier * atr / current_price * 100
        atr_sl_pct = max(0.3, min(5.0, atr_sl_pct))
    else:
        atr_sl_pct = abs(avg_mae) if avg_mae else 1.0

    # Try structural SL from actual candle data (if available)
    structural_sl_price = None
    if df is not None and len(df) >= 2 and is_structural:
        if "bullish_harami" in pat_set:
            # SL below the mother candle's low (candle before current)
            structural_sl_price = float(df["Low"].iloc[-2])
        elif "belt_hold_bearish" in pat_set:
            # SL above the belt candle's open price
            structural_sl_price = float(df["Open"].iloc[-1])
        elif any(p in pat_set for p in {"bullish_kicker", "ladder_bottom", "mat_hold"}):
            # SL below the prior candle's low (conservative structural)
            structural_sl_price = float(df["Low"].iloc[-2])

    if direction == "BULLISH":
        entry = current_price
        target_data = round(current_price * (1 + avg_mfe / 100), 2)
        sl_data = round(current_price * (1 + avg_mae / 100), 2)  # mae is negative
        target_atr = round(current_price + 1.5 * atr, 2) if atr else target_data
        sl_atr = round(current_price * (1 - atr_sl_pct / 100), 2)
    else:
        entry = current_price
        target_data = round(current_price * (1 - abs(avg_mfe) / 100), 2)
        sl_data = round(current_price * (1 - avg_mae / 100), 2)
        target_atr = round(current_price - 1.5 * atr, 2) if atr else target_data
        sl_atr = round(current_price * (1 + atr_sl_pct / 100), 2)

    # Recommended SL: use structural candle-level SL if available, else ATR-based
    # For structural patterns, the candle invalidation level is more meaningful
    if structural_sl_price is not None:
        sl_recommended = structural_sl_price
        # Compute the structural SL as a percentage
        sl_pct_actual = abs(current_price - structural_sl_price) / current_price * 100
        sl_pct_actual = max(0.3, min(5.0, sl_pct_actual))
        sl_type = "structural"
    else:
        sl_recommended = sl_atr
        sl_pct_actual = atr_sl_pct
        sl_type = "atr"

    return {
        "entry": entry,
        "target_data": target_data,
        "stop_loss_data": sl_data,
        "target_atr": target_atr,
        "stop_loss_atr": sl_atr,
        "target_recommended": round((target_data * 0.6 + target_atr * 0.4), 2),
        "stop_loss_recommended": round(sl_recommended, 2),
        "sl_pct": round(sl_pct_actual, 2),
        "sl_type": sl_type,
        "sl_multiplier": sl_multiplier,
    }


# ============================================================
# OLLAMA LLM INTEGRATION
# ============================================================

def check_ollama_available():
    """Check if Ollama is running and the model is available."""
    try:
        models = ollama.list()
        model_names = [m.model for m in models.models] if hasattr(models, 'models') else []
        return True, model_names
    except Exception as e:
        return False, str(e)


def get_ollama_analysis(ticker, current_price, patterns, indicators, prediction,
                        trade_levels, direction, feedback_context=""):
    """Get Ollama-powered detailed analysis."""

    # Build comprehensive context for the LLM
    rr = prediction.get("risk_reward", {})
    h5 = prediction["horizons"].get("+5_candles", {})
    confidence = prediction.get("confidence", {})

    # Format retrieved historical documents for context
    retrieved_docs = prediction.get("retrieved_documents", [])
    docs_context = "\n".join([f"  - {doc[:200]}" for doc in retrieved_docs[:7]])

    # Statistical extras
    stat_extras = prediction.get("stat_extras", {})

    # Load any learned rules from feedback
    learned_rules = load_learned_rules()
    rules_context = ""
    if learned_rules:
        rules_context = "\n\nLEARNED RULES FROM PAST FEEDBACK:\n"
        for rule in learned_rules[:10]:
            rules_context += f"  - [{rule.get('type', 'info')}] {rule.get('rule', '')} (confidence: {rule.get('confidence', 'N/A')})\n"

    # Get knowledge base context for detected patterns
    kb_indicators = {
        "rsi_14": indicators.get("rsi_14"),
        "vol_ratio": indicators.get("vol_ratio"),
        "trend_short": indicators.get("trend_short"),
        "session": indicators.get("session"),
        "day_name": indicators.get("day_name"),
    }
    pattern_knowledge = get_pattern_context_text(patterns, kb_indicators)

    # --- Compute pattern quality tier label ---
    pf_value = stat_extras.get("profit_factor")
    try:
        pf_value = float(pf_value)
    except (TypeError, ValueError):
        pf_value = None

    if pf_value is not None and pf_value >= 1.5:
        pattern_tier = "TIER A — EXCEPTIONAL (top decile, PF {:.2f}). High-conviction trade — trust this signal unless volume or macro news contradicts.".format(pf_value)
    elif pf_value is not None and pf_value >= 1.0:
        pattern_tier = "TIER B — MODERATE (PF {:.2f}). Requires confirmation from volume surge and trend alignment before committing.".format(pf_value)
    else:
        pattern_tier = "TIER C — WEAK (PF {}). Low confidence — consider AVOID unless multiple confirming signals align.".format(pf_value if pf_value is not None else 'N/A')

    prompt = f"""Analyze this trading setup and provide a detailed recommendation:

TICKER: {ticker}
CURRENT PRICE: ₹{current_price:,.2f}
TIMEFRAME: Intraday

DETECTED CANDLESTICK PATTERNS: {', '.join(patterns)}

*** PATTERN QUALITY: {pattern_tier} ***

{pattern_knowledge}

TECHNICAL INDICATORS:
- RSI(14): {indicators.get('rsi_14', 'N/A'):.1f if isinstance(indicators.get('rsi_14'), (int, float)) else 'N/A'} ({indicators.get('rsi_zone', 'N/A')})
- Short-term Trend (EMA 9 vs 21): {indicators.get('trend_short', 'N/A')}
- Medium-term Trend (EMA 21 vs 50): {indicators.get('trend_medium', 'N/A')}
- Market Regime: {indicators.get('market_regime', 'N/A')}
- ATR(14): {indicators.get('atr_14', 'N/A'):.2f if isinstance(indicators.get('atr_14'), (int, float)) else 'N/A'}
- Volume vs 20-day avg: {indicators.get('vol_ratio', 'N/A'):.2f if isinstance(indicators.get('vol_ratio'), (int, float)) else 'N/A'}x
- VWAP: {indicators.get('vwap', 'N/A'):.2f if isinstance(indicators.get('vwap'), (int, float)) else 'N/A'} (price {indicators.get('price_vs_vwap', 'N/A')})
- Pattern Confidence: {indicators.get('pattern_confidence', 0):.0%} | Volume Confirmed: {'YES' if indicators.get('volume_confirmed') else 'NO'}
- Gap: {indicators.get('gap_pct', 'N/A'):+.2f if isinstance(indicators.get('gap_pct'), (int, float)) else 'N/A'}%

RAG RETRIEVAL RESULTS (from 147,000+ historical pattern documents):
- Matching patterns found: {prediction['n_matches']}
- Match tier: {stat_extras.get('match_tier', 'N/A')} (how specific the contextual match is)
- 5-candle forward: {h5.get('bullish_pct', 'N/A')}% bullish, {h5.get('bearish_pct', 'N/A')}% bearish
- Bullish edge (base-rate corrected): {h5.get('bullish_edge', 0):+.1f}%
- Bearish edge (base-rate corrected): {h5.get('bearish_edge', 0):+.1f}%
- Avg return at +5 candles: {h5.get('avg_return_pct', 'N/A')}%
- Median return at +5 candles: {h5.get('median_return_pct', 'N/A')}%
- Win rate: {stat_extras.get('win_rate', 'N/A')}%
- Win rate (with SL): {stat_extras.get('sl_win_rate', 'N/A')}%
- Profit factor: {stat_extras.get('profit_factor', 'N/A')}
- Profit factor (with SL): {stat_extras.get('sl_profit_factor', 'N/A')}
- SL trigger rate: {stat_extras.get('sl_triggers_pct', 0):.0f}% of similar trades hit the stop-loss
- Avg Max Favorable Excursion (best case): {rr.get('avg_mfe_pct', 'N/A')}%
- Avg Max Adverse Excursion (worst case): {rr.get('avg_mae_pct', 'N/A')}%
- Risk:Reward ratio: 1:{rr.get('risk_reward_ratio', 'N/A')}
- Instruments matched across: {stat_extras.get('instrument_diversity', 'N/A')} different instruments
- Confidence: {confidence.get('level', 'N/A')} ({confidence.get('score', 'N/A')})

COMPUTED TRADE LEVELS:
- Entry: ₹{trade_levels['entry']:,.2f}
- Target (recommended): ₹{trade_levels['target_recommended']:,.2f}
- Stop Loss (recommended): ₹{trade_levels['stop_loss_recommended']:,.2f}  ({trade_levels.get('sl_type', 'atr')} SL, {trade_levels.get('sl_multiplier', 1.5)}x ATR tier)
- Stop Loss %: {trade_levels.get('sl_pct', 'N/A')}%

SIMILAR HISTORICAL SETUPS (from RAG):
{docs_context}

HORIZON BREAKDOWN:
{json.dumps(prediction['horizons'], indent=2)}
{rules_context}
{feedback_context}

Based on all this data, provide:
1. Your TRADE CALL (BUY/SELL/AVOID) with confidence level
2. ENTRY PRICE and why
3. TARGET PRICE and justification
4. STOP LOSS and reasoning  
5. RISK assessment — what could go wrong
6. KEY INSIGHT — the single most important thing about this setup
7. If the data is conflicting or weak, say so honestly

Be concise but thorough. Use actual numbers from the data above."""

    try:
        response = ollama.chat(
            model=_active_model(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_ANALYSIS},
                {"role": "user", "content": prompt},
            ],
            options={"temperature": 0.3, "num_predict": 1500},
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Ollama analysis unavailable: {e}\n\nFalling back to statistical analysis."


def ollama_chat_followup(chat_history, analysis_context):
    """Handle conversational follow-up with Ollama."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_CONVERSATION + f"\n\nANALYSIS CONTEXT:\n{analysis_context}"},
    ]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    try:
        response = ollama.chat(
            model=_active_model(),
            messages=messages,
            options={"temperature": 0.4, "num_predict": 1000},
        )
        return response["message"]["content"]
    except Exception as e:
        return f"Error communicating with Ollama: {e}"


def ollama_learn_from_feedback(feedback_data):
    """Use Ollama to extract learning rules from accumulated feedback."""
    if not feedback_data or len(feedback_data) < 3:
        return []

    # Summarize feedback for the LLM
    correct = [f for f in feedback_data if f.get("was_correct")]
    incorrect = [f for f in feedback_data if not f.get("was_correct")]

    summary = f"""FEEDBACK HISTORY SUMMARY:
Total predictions reviewed: {len(feedback_data)}
Correct predictions: {len(correct)} ({len(correct)/len(feedback_data)*100:.1f}%)
Incorrect predictions: {len(incorrect)} ({len(incorrect)/len(feedback_data)*100:.1f}%)

CORRECT PREDICTIONS (what worked):
"""
    for fb in correct[-15:]:  # Last 15
        summary += f"  - {fb.get('ticker', '?')} | Patterns: {fb.get('patterns', '?')} | Direction: {fb.get('direction', '?')} | Confidence: {fb.get('confidence', '?')}\n"

    summary += f"\nINCORRECT PREDICTIONS (what failed):\n"
    for fb in incorrect[-15:]:
        summary += f"  - {fb.get('ticker', '?')} | Patterns: {fb.get('patterns', '?')} | Direction: {fb.get('direction', '?')} | Reason: {fb.get('wrong_reason', 'unknown')}\n"

    # Group error reasons
    error_counts = {}
    for fb in incorrect:
        reason = fb.get("wrong_reason", "unknown")
        # Extract the main reason (before any notes)
        main_reason = reason.split(" | Notes:")[0] if " | Notes:" in reason else reason
        error_counts[main_reason] = error_counts.get(main_reason, 0) + 1

    summary += f"\nERROR BREAKDOWN:\n"
    for reason, count in sorted(error_counts.items(), key=lambda x: x[1], reverse=True):
        summary += f"  - {reason}: {count} times\n"

    try:
        response = ollama.chat(
            model=_active_model(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_LEARNING},
                {"role": "user", "content": summary},
            ],
            options={"temperature": 0.2, "num_predict": 2000},
        )

        # Try to parse rules from the response
        content = response["message"]["content"]
        # Try to extract JSON from the response
        try:
            # Find JSON array in the response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                rules = json.loads(content[start:end])
                return rules
        except json.JSONDecodeError:
            pass

        # If JSON parsing fails, create a simple rule from the text
        return [{"rule": content[:500], "confidence": 0.5, "type": "info", "context": "general"}]

    except Exception as e:
        return [{"rule": f"Learning failed: {e}", "confidence": 0, "type": "info", "context": "error"}]


# ============================================================
# FEEDBACK & LEARNING SYSTEM
# ============================================================

def load_feedback():
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "r") as f:
            return json.load(f)
    return []


def save_feedback(feedback_list):
    with open(FEEDBACK_FILE, "w") as f:
        json.dump(feedback_list, f, indent=2, default=str)


def load_learned_rules():
    if os.path.exists(LEARNING_FILE):
        with open(LEARNING_FILE, "r") as f:
            return json.load(f)
    return []


def save_learned_rules(rules):
    with open(LEARNING_FILE, "w") as f:
        json.dump(rules, f, indent=2, default=str)


def add_feedback(ticker, prediction_data, trade_levels, was_correct,
                 wrong_reason=None, notes=None):
    fb = load_feedback()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "ticker": ticker,
        "patterns": prediction_data.get("detected_patterns", []),
        "direction": prediction_data.get("direction", ""),
        "entry_price": trade_levels.get("entry"),
        "target": trade_levels.get("target_recommended"),
        "stop_loss": trade_levels.get("stop_loss_recommended"),
        "confidence": prediction_data.get("confidence", {}).get("level"),
        "was_correct": was_correct,
        "wrong_reason": wrong_reason,
        "notes": notes,
        "n_matches": prediction_data.get("n_matches"),
        "avg_similarity": prediction_data.get("avg_similarity"),
    }
    fb.append(entry)
    save_feedback(fb)

    # Trigger learning every 5 feedback entries
    if len(fb) % 5 == 0:
        with st.spinner("🧠 Learning from feedback history..."):
            rules = ollama_learn_from_feedback(fb)
            if rules:
                save_learned_rules(rules)
                st.toast(f"🧠 Model updated! Extracted {len(rules)} rules from {len(fb)} feedback entries.")

    return len(fb)


def get_feedback_stats():
    fb = load_feedback()
    if not fb:
        return None
    total = len(fb)
    correct = sum(1 for f in fb if f["was_correct"])
    wrong_reasons = {}
    for f in fb:
        if not f["was_correct"] and f.get("wrong_reason"):
            r = f["wrong_reason"].split(" | Notes:")[0]
            wrong_reasons[r] = wrong_reasons.get(r, 0) + 1
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "wrong_reasons": wrong_reasons,
    }


# ============================================================
# FETCH LIVE DATA
# ============================================================

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
        if "open" in cl and "Open" not in col_map.values():
            col_map[c] = "Open"
        elif "high" in cl and "High" not in col_map.values():
            col_map[c] = "High"
        elif "low" in cl and "Low" not in col_map.values():
            col_map[c] = "Low"
        elif "close" in cl and "adj" not in cl and "Close" not in col_map.values():
            col_map[c] = "Close"
        elif "volume" in cl and "Volume" not in col_map.values():
            col_map[c] = "Volume"
    df = df.rename(columns=col_map)

    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df, ticker_yf


# ============================================================
# STREAMLIT APP
# ============================================================

def main():
    st.set_page_config(
        page_title="Candlestick RAG + Ollama",
        page_icon="🧠",
        layout="wide",
    )

    # Initialize session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "analysis_context" not in st.session_state:
        st.session_state.analysis_context = ""
    if "analysis_done" not in st.session_state:
        st.session_state.analysis_done = False
    if "show_wrong_form" not in st.session_state:
        st.session_state.show_wrong_form = False

    st.title("🧠 Candlestick RAG Predictor")
    st.caption("Powered by Statistical Predictor + Ollama LLM + 147K historical patterns + self-learning feedback")

    # ── Sidebar ──
    with st.sidebar:
        st.header("🤖 Ollama Status")
        ollama_ok, model_info = check_ollama_available()
        if ollama_ok:
            st.success(f"✅ Connected")
            if isinstance(model_info, list) and model_info:
                st.caption(f"Models: {', '.join(model_info[:5])}")
            ollama_model = st.text_input("Model", value=OLLAMA_MODEL)
        else:
            st.error(f"❌ Ollama not running")
            st.caption(f"Start Ollama and pull a model:\n```\nollama pull llama3.2\n```")
            ollama_model = OLLAMA_MODEL

        st.divider()
        st.header("📈 Model Performance")
        stats = get_feedback_stats()
        if stats:
            col1, col2 = st.columns(2)
            col1.metric("Predictions", stats["total"])
            col2.metric("Accuracy", f"{stats['accuracy']}%")
            if stats["wrong_reasons"]:
                st.subheader("Common Errors")
                for reason, count in sorted(stats["wrong_reasons"].items(),
                                            key=lambda x: x[1], reverse=True)[:5]:
                    st.caption(f"• {reason}: **{count}**")
        else:
            st.info("No feedback yet. Analyze stocks and provide feedback to train!")

        # Learned rules
        rules = load_learned_rules()
        if rules:
            st.divider()
            st.header("🧠 Learned Rules")
            for rule in rules[:5]:
                rule_type = rule.get("type", "info")
                emoji = "🚫" if rule_type == "avoid" else "✅" if rule_type == "prefer" else "🔧" if rule_type == "adjust" else "ℹ️"
                st.caption(f"{emoji} {rule.get('rule', '')[:100]}")

        st.divider()
        st.header("⚙️ Settings")
        # Only show allowed timeframes (production config)
        tf_options = ["1d"]  # daily is the primary allowed timeframe
        if "15min" in ALLOWED_TIMEFRAMES:
            tf_options.insert(0, "15m")
        timeframe = st.selectbox("Timeframe", tf_options, index=0)
        if timeframe == "15m" and "15min" not in ALLOWED_TIMEFRAMES:
            st.warning("⚠️ 15-min timeframe is currently disabled (OOS PF 0.79). Using daily."    )
            timeframe = "1d"

        if st.button("🔄 Re-learn from Feedback", use_container_width=True):
            fb = load_feedback()
            if len(fb) >= 3:
                with st.spinner("🧠 Analyzing feedback history..."):
                    rules = ollama_learn_from_feedback(fb)
                    save_learned_rules(rules)
                    st.success(f"Extracted {len(rules)} rules from {len(fb)} feedback entries!")
                    st.rerun()
            else:
                st.warning("Need at least 3 feedback entries to learn.")

    # ── Main Area ──
    # Ticker Input
    st.header("Enter NSE Ticker")
    col_input1, col_input2 = st.columns([3, 1])
    with col_input1:
        ticker = st.text_input(
            "NSE Symbol",
            placeholder="e.g. RELIANCE, HDFCBANK, INFY, NIFTY",
            label_visibility="collapsed",
        )
    with col_input2:
        analyze_btn = st.button("🔍 Analyze", type="primary", use_container_width=True)

    # ── ANALYSIS ──
    if analyze_btn and ticker:
        ticker = ticker.strip().upper()
        ticker_map = {
            "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK",
            "BANK NIFTY": "^NSEBANK", "SENSEX": "^BSESN",
        }
        ticker_resolved = ticker_map.get(ticker, ticker)

        # Reset chat for new analysis
        st.session_state.chat_history = []
        st.session_state.analysis_done = False
        st.session_state.show_wrong_form = False

        # Update model name if changed in sidebar
        st.session_state["ollama_model_active"] = ollama_model

        with st.spinner(f"Fetching live data for {ticker_resolved}..."):
            df, ticker_yf = fetch_live_data(ticker_resolved, interval=timeframe)

        if df is None or len(df) < 20:
            st.error(f"Could not fetch data for **{ticker_yf}**. Check the ticker.")
            return

        last = df.iloc[-1]
        current_price = float(last["Close"])
        prev_close = float(df["Close"].iloc[-2])
        change_pct = (current_price - prev_close) / prev_close * 100

        st.divider()

        # Price header
        p1, p2, p3, p4 = st.columns(4)
        p1.metric("Current Price", f"₹{current_price:,.2f}", f"{change_pct:+.2f}%")
        p2.metric("High", f"₹{float(last['High']):,.2f}")
        p3.metric("Low", f"₹{float(last['Low']):,.2f}")
        p4.metric("Volume", f"{int(last.get('Volume', 0)):,}" if last.get('Volume', 0) > 0 else "N/A")

        # Patterns & Indicators
        with st.spinner("Detecting patterns & computing indicators..."):
            pat_result = detect_patterns_on_df(df)
            patterns = pat_result["patterns"]
            pattern_confidence = pat_result["confidence"]
            volume_confirmed = pat_result["volume_confirmed"]
            indicators = compute_live_indicators(df)
            # Market regime detection
            regime = detect_market_regime(df)
            indicators["market_regime"] = regime
            indicators["pattern_confidence"] = pattern_confidence
            indicators["volume_confirmed"] = volume_confirmed

        col_pat, col_ind = st.columns(2)
        with col_pat:
            st.subheader("🕯️ Detected Patterns")
            if patterns and patterns[0] != "none":
                for p in patterns:
                    emoji = "🟢" if any(b in p for b in ["bullish", "hammer", "morning", "white", "dragonfly", "piercing"]) else \
                            "🔴" if any(b in p for b in ["bearish", "shooting", "evening", "black", "dark", "hanging", "gravestone"]) else "⚪"
                    st.write(f"{emoji} **{p.replace('_', ' ').title()}**")
                # Confidence & Volume confirmation
                conf_pct = f"{pattern_confidence:.0%}" if pattern_confidence else "N/A"
                vol_icon = "✅" if volume_confirmed else "❌"
                st.caption(f"Confidence: **{conf_pct}** | Volume Confirmed: {vol_icon}")
            else:
                st.info("No significant pattern detected.")
                patterns = ["none"]

        with col_ind:
            st.subheader("📐 Technical Context")
            if "rsi_14" in indicators:
                rsi_val = indicators["rsi_14"]
                rsi_color = "🔴" if rsi_val > 70 else "🟢" if rsi_val < 30 else "⚪"
                st.write(f"RSI(14): {rsi_color} **{rsi_val:.1f}** ({indicators.get('rsi_zone', 'neutral')})")
            if "trend_short" in indicators:
                st.write(f"Short Trend: {'🟢' if indicators['trend_short'] == 'bullish' else '🔴'} **{indicators['trend_short'].title()}**")
            if "trend_medium" in indicators:
                st.write(f"Medium Trend: {'🟢' if indicators['trend_medium'] == 'bullish' else '🔴'} **{indicators['trend_medium'].title()}**")
            if "atr_14" in indicators:
                st.write(f"ATR(14): **{indicators['atr_14']:.2f}**")
            if "vol_ratio" in indicators:
                st.write(f"Volume: **{indicators['vol_ratio']:.2f}x** avg")
            if "vwap" in indicators:
                vwap_v = indicators["vwap"]
                pvw = indicators.get("price_vs_vwap", "?")
                vwap_icon = "🟢" if pvw == "above" else "🔴"
                st.write(f"VWAP: {vwap_icon} **₹{vwap_v:,.2f}** (price {pvw})")
            if "market_regime" in indicators:
                regime = indicators["market_regime"]
                regime_emoji = "📈" if "bull" in regime else "📉" if "bear" in regime else "↔️"
                st.write(f"Market Regime: {regime_emoji} **{regime.replace('_', ' ').title()}**")

        # Statistical Predictor Query
        query_pattern = ",".join(patterns) if patterns[0] != "none" else "spinning_top"

        with st.spinner("Statistical predictor analyzing 147K patterns..."):
            try:
                sp = load_stat_predictor()
            except Exception as e:
                st.error(f"Statistical predictor not ready: {e}. Ensure rag_documents_v2/all_pattern_documents.json exists.")
                return

            prediction = stat_predict_and_adapt(
                sp,
                patterns=patterns if patterns[0] != "none" else ["spinning_top"],
                timeframe=timeframe,
                trend_short=indicators.get("trend_short"),
                rsi_zone=indicators.get("rsi_zone"),
                price_vs_vwap=indicators.get("price_vs_vwap"),
                market_regime=indicators.get("market_regime"),
                instrument=ticker_resolved,
            )

        if not prediction:
            st.error("No similar patterns found in database.")
            return

        # Direction & trade levels
        h5 = prediction["horizons"].get("+5_candles", prediction["horizons"].get("+3_candles", {}))
        direction = h5.get("direction", "NEUTRAL") if h5 else "NEUTRAL"
        bullish_pct = h5.get("bullish_pct", 50) if h5 else 50
        bearish_pct = h5.get("bearish_pct", 50) if h5 else 50
        confidence = prediction.get("confidence", {})
        stat_extras = prediction.get("stat_extras", {})
        atr = indicators.get("atr_14", current_price * 0.005)

        # Check for NO TRADE (neutral direction or insufficient edge)
        is_no_trade = direction == "NEUTRAL"
        edge = max(abs(stat_extras.get("bullish_edge", 0)),
                   abs(stat_extras.get("bearish_edge", 0)))
        if edge < 8.5:
            is_no_trade = True

        if not is_no_trade:
            trade = compute_trade_levels(current_price, prediction, atr, direction,
                                         patterns=patterns, df=df)
        else:
            # Minimal trade dict for NO TRADE
            trade = {
                "entry": current_price, "target_data": current_price,
                "stop_loss_data": current_price, "target_atr": current_price,
                "stop_loss_atr": current_price,
                "target_recommended": current_price, "stop_loss_recommended": current_price,
            }

        # Store in session
        st.session_state["last_prediction"] = {
            "ticker": ticker, "detected_patterns": patterns,
            "direction": direction, "confidence": confidence,
            "n_matches": prediction["n_matches"],
            "avg_similarity": prediction["avg_similarity"],
        }
        st.session_state["last_trade"] = trade

        # ── TRADE RECOMMENDATION ──
        st.divider()
        st.header("🎯 Trade Recommendation")

        if is_no_trade:
            st.markdown(f"""
            <div style="background-color: #3b3b0d; 
                        padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px;">
                <h2 style="color: #ffcc00; margin: 0;">
                    ⚠️ NO TRADE — Insufficient Edge
                </h2>
                <p style="color: #ccc; font-size: 18px; margin: 5px 0;">
                    Edge: <b>{edge:+.1f}%</b> (need &gt;8.5%) | 
                    Confidence: 🔴 <b>{confidence.get('level', 'LOW')}</b>
                </p>
                <p style="color: #aaa; font-size: 14px; margin: 5px 0;">
                    The pattern has no statistically significant directional bias after base-rate correction.
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            signal_text = "📈 BUY / LONG" if direction == "BULLISH" else "📉 SELL / SHORT"
            conf_level = confidence.get("level", "MEDIUM")
            conf_emoji = "🟢" if conf_level == "HIGH" else "🟡" if conf_level == "MEDIUM" else "🔴"
            edge_display = stat_extras.get("bullish_edge", 0) if direction == "BULLISH" else stat_extras.get("bearish_edge", 0)

            st.markdown(f"""
            <div style="background-color: {'#0d3b0d' if direction == 'BULLISH' else '#3b0d0d'}; 
                        padding: 20px; border-radius: 10px; text-align: center; margin-bottom: 20px;">
                <h2 style="color: {'#00ff00' if direction == 'BULLISH' else '#ff4444'}; margin: 0;">
                    {signal_text}
                </h2>
                <p style="color: #ccc; font-size: 18px; margin: 5px 0;">
                    Edge: <b>{edge_display:+.1f}%</b> vs base rate | 
                    Confidence: {conf_emoji} <b>{conf_level}</b>
                </p>
            </div>
            """, unsafe_allow_html=True)

            # Trade levels
            lc1, lc2, lc3, lc4 = st.columns(4)
            lc1.metric("🎯 Entry", f"₹{trade['entry']:,.2f}")
            lc2.metric("✅ Target", f"₹{trade['target_recommended']:,.2f}",
                       f"{((trade['target_recommended'] - trade['entry']) / trade['entry'] * 100):+.2f}%")
            lc3.metric("🛑 Stop Loss", f"₹{trade['stop_loss_recommended']:,.2f}",
                       f"{((trade['stop_loss_recommended'] - trade['entry']) / trade['entry'] * 100):+.2f}%")
            rr = prediction.get("risk_reward", {})
            lc4.metric("⚖️ R:R", f"1:{rr.get('risk_reward_ratio', 'N/A')}")

            # SL enforcement note
            sl_pct = trade.get("sl_pct", 0)
            sl_type = trade.get("sl_type", "atr")
            sl_mult = trade.get("sl_multiplier", 1.5)
            if sl_pct:
                if sl_type == "structural":
                    sl_label = "structural (candle invalidation level)"
                else:
                    sl_label = f"{sl_mult}x ATR"
                st.caption(f"🔒 **Stop-loss enforced at {sl_pct:.2f}%** ({sl_label}) — "
                           f"Historically, SL triggers on {stat_extras.get('sl_triggers_pct', 0):.0f}% of similar trades")

        # ── Statistical Metrics ──
        if stat_extras:
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("🏆 Win Rate (w/ SL)", f"{stat_extras.get('sl_win_rate', 0):.1f}%")
            sm2.metric("📊 Profit Factor (w/ SL)", f"{stat_extras.get('sl_profit_factor', 0):.2f}")
            sm3.metric("🔍 Match Tier", stat_extras.get('match_tier', 'N/A').replace('_', ' ').title())
            sm4.metric("🌐 Instruments", f"{stat_extras.get('instrument_diversity', 0)}")

        # ── OLLAMA ANALYSIS ──
        st.divider()
        st.header("🧠 AI Analysis (Ollama)")

        # Build feedback context for the LLM
        feedback_context = ""
        fb = load_feedback()
        relevant_fb = [f for f in fb if f.get("ticker") == ticker]
        if relevant_fb:
            feedback_context = f"\n\nPAST FEEDBACK FOR {ticker} ({len(relevant_fb)} entries):\n"
            for rfb in relevant_fb[-5:]:
                status = "✅ CORRECT" if rfb["was_correct"] else f"❌ WRONG ({rfb.get('wrong_reason', 'unknown')})"
                feedback_context += f"  - {rfb['timestamp'][:10]} | {rfb.get('direction', '?')} | {status}\n"

        with st.spinner("🧠 Ollama is analyzing the setup..."):
            llm_analysis = get_ollama_analysis(
                ticker, current_price, patterns, indicators,
                prediction, trade, direction, feedback_context
            )

        st.markdown(llm_analysis)

        # Build analysis context for follow-up chat
        conf_level = confidence.get("level", "MEDIUM")
        analysis_summary = f"""
TICKER: {ticker} at ₹{current_price:,.2f}
PATTERNS: {', '.join(patterns)}
DIRECTION: {direction}
ENTRY: ₹{trade['entry']:,.2f} | TARGET: ₹{trade['target_recommended']:,.2f} | SL: ₹{trade['stop_loss_recommended']:,.2f}
RSI: {indicators.get('rsi_14', 'N/A')} | TREND: {indicators.get('trend_short', 'N/A')}
STAT MATCHES: {prediction['n_matches']} | TIER: {stat_extras.get('match_tier', 'N/A')}
WIN RATE: {stat_extras.get('win_rate', 'N/A')}% | PROFIT FACTOR: {stat_extras.get('profit_factor', 'N/A')}
EDGE: bullish {stat_extras.get('bullish_edge', 0):+.1f}% / bearish {stat_extras.get('bearish_edge', 0):+.1f}%
CONFIDENCE: {conf_level}
HORIZONS: {json.dumps(prediction['horizons'], indent=2)}
RISK/REWARD: {json.dumps(prediction.get('risk_reward', {}), indent=2)}

OLLAMA ANALYSIS:
{llm_analysis}
"""
        st.session_state.analysis_context = analysis_summary
        st.session_state.analysis_done = True

        # Forward returns table
        with st.expander("📊 Historical Forward Returns"):
            horizon_data = []
            for horizon, data in prediction["horizons"].items():
                horizon_data.append({
                    "Horizon": horizon, "Direction": data["direction"],
                    "Bullish %": f"{data['bullish_pct']}%",
                    "Bull Edge": f"{data.get('bullish_edge', 0):+.1f}%",
                    "Bear Edge": f"{data.get('bearish_edge', 0):+.1f}%",
                    "Avg Return": f"{data['avg_return_pct']:+.4f}%",
                    "Samples": data["count"],
                })
            if horizon_data:
                st.table(pd.DataFrame(horizon_data))

        # Top contributing instruments
        with st.expander("🔍 Match Details"):
            if stat_extras:
                st.write(f"**Match Tier:** {stat_extras.get('match_tier', 'N/A').replace('_', ' ').title()}")
                st.write(f"**Total Matches:** {prediction['n_matches']} across {stat_extras.get('instrument_diversity', 0)} instruments")
                st.write(f"**Win Rate:** {stat_extras.get('win_rate', 0):.1f}% | **Profit Factor:** {stat_extras.get('profit_factor', 0):.2f}")
                top_inst = stat_extras.get("top_instruments", {})
                if top_inst:
                    st.write("**Top instruments in match pool:**")
                    for inst, cnt in list(top_inst.items())[:10]:
                        st.write(f"  - {inst}: {cnt} matches")
            else:
                for i, m in enumerate(prediction.get("matches", []), 1):
                    ret = m.get("fwd_5_return_pct")
                    ret_str = f"{ret:+.4f}%" if ret is not None else "N/A"
                    emoji = "🟢" if m.get("fwd_5_direction") == "bullish" else "🔴"
                    st.write(f"**{i}.** [{m['similarity']:.1%}] {m['instrument']} @ {m['datetime']} — *{m['patterns']}* → {emoji} {ret_str}")

        # ── FEEDBACK ──
        st.divider()
        st.header("📝 Was this prediction correct?")
        st.caption("Your feedback trains the AI to make better predictions.")

        fb_col1, fb_col2 = st.columns(2)

        with fb_col1:
            if st.button("✅ Bang On! (Correct)", type="primary", use_container_width=True, key="btn_correct"):
                pred_data = st.session_state.get("last_prediction", {})
                trade_data = st.session_state.get("last_trade", {})
                count = add_feedback(ticker, pred_data, trade_data, was_correct=True)
                st.success(f"✅ Recorded as CORRECT! Total feedback: {count}")
                st.balloons()

        with fb_col2:
            if st.button("❌ Not Correct", type="secondary", use_container_width=True, key="btn_wrong"):
                st.session_state.show_wrong_form = True

        if st.session_state.get("show_wrong_form", False):
            st.subheader("What went wrong?")
            wrong_reason = st.radio(
                "Select the issue:",
                [
                    "Direction was opposite",
                    "Target too aggressive (didn't reach)",
                    "Stop loss too tight (hit SL then reversed)",
                    "Timing off (eventually correct, too slow)",
                    "News/event overrode the pattern",
                    "Pattern incorrectly detected",
                ],
                key="wrong_reason",
            )
            wrong_notes = st.text_area("Tell the AI what actually happened:", key="wrong_notes",
                                        placeholder="e.g. Price reversed at ₹2450 due to RBI announcement...")

            if st.button("Submit Feedback & Train", key="submit_wrong"):
                pred_data = st.session_state.get("last_prediction", {})
                trade_data = st.session_state.get("last_trade", {})
                count = add_feedback(ticker, pred_data, trade_data,
                                     was_correct=False, wrong_reason=wrong_reason,
                                     notes=wrong_notes)
                st.warning(f"❌ Recorded as INCORRECT. Model will learn from this!")

                # Ask Ollama to reflect on the mistake
                if wrong_notes:
                    with st.spinner("🧠 AI is processing your feedback..."):
                        reflection_prompt = f"""The user said our prediction was wrong.

Our prediction: {pred_data.get('direction', '?')} on {ticker}
Patterns: {pred_data.get('detected_patterns', '?')}
What happened: {wrong_reason}
User's explanation: {wrong_notes}

What should we learn from this? Give a brief, actionable takeaway (2-3 sentences)."""
                        try:
                            reflection = ollama.chat(
                                model=_active_model(),
                                messages=[
                                    {"role": "system", "content": "You are a trading system learning from mistakes. Be concise and actionable."},
                                    {"role": "user", "content": reflection_prompt},
                                ],
                                options={"temperature": 0.3, "num_predict": 300},
                            )
                            st.info(f"🧠 **AI Takeaway:** {reflection['message']['content']}")
                        except Exception:
                            pass

                st.session_state.show_wrong_form = False
                st.rerun()

    # ── CONVERSATIONAL FOLLOW-UP ──
    if st.session_state.get("analysis_done", False):
        st.divider()
        st.header("💬 Ask Follow-Up Questions")
        st.caption("Chat with the AI about this analysis. Ask about risk, alternatives, or deeper reasoning.")

        # Display chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input
        user_question = st.chat_input("Ask about this trade setup...",
                                       key="chat_input")

        if user_question:
            # Add user message
            st.session_state.chat_history.append({"role": "user", "content": user_question})
            with st.chat_message("user"):
                st.markdown(user_question)

            # Get AI response
            with st.chat_message("assistant"):
                with st.spinner("🧠 Thinking..."):
                    response = ollama_chat_followup(
                        st.session_state.chat_history,
                        st.session_state.analysis_context
                    )
                st.markdown(response)

            # Add assistant message
            st.session_state.chat_history.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
