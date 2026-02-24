"""
Shared Candlestick Pattern Detector
====================================
Single source of truth for pattern detection logic.
Used by both feature_engineering.py (batch) and app_ollama.py (live).

Detects 53+ candlestick patterns across three categories:
  - Single candle (15+ patterns)
  - Two-candle (16+ patterns)
  - Three-candle (20+ patterns)

Also computes:
  - pattern_confidence (0.0-1.0): Shape quality + volume + trend context
  - volume_confirmed (bool): Whether volume supports the pattern signal
"""

import numpy as np
import pandas as pd
from candlestick_knowledge_base import PATTERN_KB


# ============================================================
# PATTERN CATEGORY SETS (for volume confirmation logic)
# ============================================================

_BULLISH_REVERSAL = {
    "hammer", "bullish_engulfing", "piercing_line", "morning_star",
    "morning_doji_star", "three_white_soldiers", "three_inside_up",
    "three_outside_up", "bullish_harami", "harami_cross",
    "tweezer_bottom", "bullish_kicker", "bullish_counterattack",
    "abandoned_baby_bullish", "dragonfly_doji", "belt_hold_bullish",
    "homing_pigeon", "matching_low", "ladder_bottom",
    "unique_three_river", "tri_star_bullish", "stick_sandwich",
    "three_stars_south", "inverted_hammer",
}

_BEARISH_REVERSAL = {
    "hanging_man", "bearish_engulfing", "dark_cloud_cover",
    "evening_star", "evening_doji_star", "three_black_crows",
    "three_inside_down", "three_outside_down", "bearish_harami",
    "tweezer_top", "bearish_kicker", "bearish_counterattack",
    "abandoned_baby_bearish", "gravestone_doji", "belt_hold_bearish",
    "shooting_star", "matching_high", "tri_star_bearish",
    "advance_block", "deliberation", "concealing_baby_swallow",
    "upside_gap_two_crows",
}

_CONTINUATION = {
    "rising_three_methods", "falling_three_methods", "mat_hold",
    "upside_tasuki_gap", "downside_tasuki_gap", "separating_lines",
    "on_neck", "in_neck",
}

_INDECISION = {
    "doji", "long_legged_doji", "spinning_top", "high_wave",
}

_ALL_REVERSAL = _BULLISH_REVERSAL | _BEARISH_REVERSAL


# ============================================================
# 1. SINGLE-CANDLE PATTERN DETECTOR
# ============================================================

def classify_single_candle(row):
    """
    Classify a single candle by shape.
    Detects: doji variants, hammer, hanging_man, shooting_star,
    inverted_hammer, marubozu, belt_hold, high_wave, spinning_top.
    """
    o, h, l, c = row["Open"], row["High"], row["Low"], row["Close"]
    body = abs(c - o)
    total_range = h - l
    if total_range == 0:
        return "doji"

    body_ratio = body / total_range
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    is_bullish = c > o

    patterns = []

    # ── Doji variants ──
    if body_ratio < 0.05:
        if upper_shadow > 2 * body and lower_shadow > 2 * body:
            patterns.append("long_legged_doji")
        elif upper_shadow > 2 * body and lower_shadow < body:
            patterns.append("gravestone_doji")
        elif lower_shadow > 2 * body and upper_shadow < body:
            patterns.append("dragonfly_doji")
        else:
            patterns.append("doji")

    # ── Marubozu (very full body, minimal shadows) ──
    elif body_ratio > 0.9:
        patterns.append("bullish_marubozu" if is_bullish else "bearish_marubozu")

    # ── Belt Hold (opens at extreme, strong body) ──
    elif body_ratio > 0.65:
        if is_bullish and lower_shadow < body * 0.05:
            patterns.append("belt_hold_bullish")
        elif not is_bullish and upper_shadow < body * 0.05:
            patterns.append("belt_hold_bearish")

    # ── Hammer / Hanging Man / Shooting Star / Inverted Hammer ──
    elif body_ratio < 0.35:
        if lower_shadow > 2 * body and upper_shadow < body * 0.5:
            patterns.append("hammer" if is_bullish else "hanging_man")
        elif upper_shadow > 2 * body and lower_shadow < body * 0.5:
            patterns.append("shooting_star" if not is_bullish else "inverted_hammer")

    # ── High Wave (tiny body, extremely long shadows) ──
    if body_ratio < 0.1 and upper_shadow > 3 * body and lower_shadow > 3 * body:
        if "long_legged_doji" not in patterns:
            patterns.append("high_wave")

    # ── Spinning Top (small body, shadows on both sides) ──
    if 0.05 < body_ratio < 0.35 and upper_shadow > body * 0.5 and lower_shadow > body * 0.5:
        if not any(p in patterns for p in ["hammer", "hanging_man", "shooting_star",
                                            "inverted_hammer", "high_wave"]):
            patterns.append("spinning_top")

    return ",".join(patterns) if patterns else "none"


# ============================================================
# 2. TWO-CANDLE PATTERN DETECTOR
# ============================================================

def detect_two_candle_patterns(df):
    """
    Detect two-candle patterns.
    Covers: engulfing, harami, harami_cross, piercing_line, dark_cloud_cover,
    tweezer, kicker, on_neck, in_neck, counterattack, homing_pigeon,
    matching_low, matching_high, separating_lines.
    """
    patterns = pd.Series("", index=df.index)

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]
        p_o, p_h, p_l, p_c = prev["Open"], prev["High"], prev["Low"], prev["Close"]
        c_o, c_h, c_l, c_c = curr["Open"], curr["High"], curr["Low"], curr["Close"]
        p_body = abs(p_c - p_o)
        c_body = abs(c_c - c_o)
        p_range = p_h - p_l
        c_range = c_h - c_l
        p_bullish = p_c > p_o
        c_bullish = c_c > c_o
        found = []

        if p_range == 0:
            continue

        # ── Bullish Engulfing ──
        if not p_bullish and c_bullish and c_o <= p_c and c_c >= p_o and c_body > p_body:
            found.append("bullish_engulfing")

        # ── Bearish Engulfing ──
        if p_bullish and not c_bullish and c_o >= p_c and c_c <= p_o and c_body > p_body:
            found.append("bearish_engulfing")

        # ── Bullish Harami ──
        if not p_bullish and c_bullish and c_o > p_c and c_c < p_o and c_body < p_body * 0.5:
            found.append("bullish_harami")

        # ── Bearish Harami ──
        if p_bullish and not c_bullish and c_o < p_c and c_c > p_o and c_body < p_body * 0.5:
            found.append("bearish_harami")

        # ── Harami Cross (harami where second candle is a doji) ──
        if c_range > 0 and c_body / c_range < 0.05:
            c_mid = (c_o + c_c) / 2
            if not p_bullish and c_mid > p_c and c_mid < p_o and c_body < p_body * 0.3:
                found.append("harami_cross")
            elif p_bullish and c_mid < p_c and c_mid > p_o and c_body < p_body * 0.3:
                found.append("harami_cross")

        # ── Piercing Line ──
        if not p_bullish and c_bullish and c_o < p_l and c_c > (p_o + p_c) / 2 and c_c < p_o:
            found.append("piercing_line")

        # ── Dark Cloud Cover ──
        if p_bullish and not c_bullish and c_o > p_h and c_c < (p_o + p_c) / 2 and c_c > p_o:
            found.append("dark_cloud_cover")

        # ── Tweezer Bottom ──
        if abs(p_l - c_l) < 0.001 * max(p_l, 0.01) and not p_bullish and c_bullish:
            found.append("tweezer_bottom")

        # ── Tweezer Top ──
        if abs(p_h - c_h) < 0.001 * max(p_h, 0.01) and p_bullish and not c_bullish:
            found.append("tweezer_top")

        # ── Bullish Kicker ──
        if not p_bullish and c_bullish and c_o >= p_o and c_body > 0:
            found.append("bullish_kicker")

        # ── Bearish Kicker ──
        if p_bullish and not c_bullish and c_o <= p_o and c_body > 0:
            found.append("bearish_kicker")

        # ── On Neck Line ──
        if (not p_bullish and c_bullish and p_range > 0 and
            c_body < p_body * 0.5 and abs(c_c - p_l) < 0.002 * max(p_l, 0.01)):
            found.append("on_neck")

        # ── In Neck Line ──
        if (not p_bullish and c_bullish and p_range > 0 and
            c_body < p_body * 0.5 and c_c > p_l and
            c_c < p_c + (p_o - p_c) * 0.3 and c_c > p_c):
            if "on_neck" not in found:
                found.append("in_neck")

        # ── Bullish Counterattack ──
        if (not p_bullish and c_bullish and c_o < p_c and
            abs(c_c - p_c) < 0.003 * max(p_c, 0.01) and c_body > p_body * 0.5):
            found.append("bullish_counterattack")

        # ── Bearish Counterattack ──
        if (p_bullish and not c_bullish and c_o > p_c and
            abs(c_c - p_c) < 0.003 * max(p_c, 0.01) and c_body > p_body * 0.5):
            found.append("bearish_counterattack")

        # ── Homing Pigeon (bullish harami variant — both candles bearish) ──
        if (not p_bullish and not c_bullish and
            c_o > p_c and c_o < p_o and c_c > p_c and c_c < p_o and
            c_body < p_body * 0.5):
            found.append("homing_pigeon")

        # ── Matching Low (two bearish with same close) ──
        if (not p_bullish and not c_bullish and
            abs(p_c - c_c) < 0.001 * max(p_c, 0.01)):
            found.append("matching_low")

        # ── Matching High (two bullish with same close) ──
        if (p_bullish and c_bullish and
            abs(p_c - c_c) < 0.001 * max(p_c, 0.01)):
            found.append("matching_high")

        # ── Separating Lines (opposite colors, same open) ──
        if (abs(p_o - c_o) < 0.001 * max(p_o, 0.01) and
            p_bullish != c_bullish and p_body > 0 and c_body > 0):
            found.append("separating_lines")

        if found:
            patterns.iloc[i] = ",".join(found)

    return patterns


# ============================================================
# 3. THREE-CANDLE PATTERN DETECTOR
# ============================================================

def detect_three_candle_patterns(df):
    """
    Detect three-candle patterns.
    Covers: morning/evening star, doji star variants, three white soldiers,
    three black crows, three inside up/down, three outside up/down,
    abandoned baby, rising/falling three methods, advance block,
    deliberation, tri-star, tasuki gap, upside gap two crows,
    mat hold, stick sandwich, unique three river, ladder bottom,
    concealing baby swallow, three stars in the south.
    """
    patterns = pd.Series("", index=df.index)

    for i in range(2, len(df)):
        p2 = df.iloc[i - 2]
        p1 = df.iloc[i - 1]
        curr = df.iloc[i]
        found = []

        p2_body = abs(p2["Close"] - p2["Open"])
        p1_body = abs(p1["Close"] - p1["Open"])
        c_body = abs(curr["Close"] - curr["Open"])
        p2_range = p2["High"] - p2["Low"]
        p1_range = p1["High"] - p1["Low"]
        c_range = curr["High"] - curr["Low"]

        if p2_range == 0 or p1_range == 0:
            continue

        p1_body_ratio = p1_body / p1_range if p1_range > 0 else 0
        p2_body_ratio = p2_body / p2_range if p2_range > 0 else 0
        c_body_ratio = c_body / c_range if c_range > 0 else 0

        p2_bullish = p2["Close"] > p2["Open"]
        p1_bullish = p1["Close"] > p1["Open"]
        c_bullish = curr["Close"] > curr["Open"]

        # ── Morning Star ──
        if (not p2_bullish and p1_body_ratio < 0.2 and
            c_bullish and curr["Close"] > (p2["Open"] + p2["Close"]) / 2):
            found.append("morning_star")

        # ── Morning Doji Star ──
        if (not p2_bullish and p1_body_ratio < 0.05 and
            c_bullish and curr["Close"] > (p2["Open"] + p2["Close"]) / 2):
            found.append("morning_doji_star")

        # ── Evening Star ──
        if (p2_bullish and p1_body_ratio < 0.2 and
            not c_bullish and curr["Close"] < (p2["Open"] + p2["Close"]) / 2):
            found.append("evening_star")

        # ── Evening Doji Star ──
        if (p2_bullish and p1_body_ratio < 0.05 and
            not c_bullish and curr["Close"] < (p2["Open"] + p2["Close"]) / 2):
            found.append("evening_doji_star")

        # ── Three White Soldiers ──
        if (p2_bullish and p1_bullish and c_bullish and
            p1["Close"] > p2["Close"] and curr["Close"] > p1["Close"] and
            p2_body_ratio > 0.4 and p1_body_ratio > 0.4 and c_body_ratio > 0.4):
            found.append("three_white_soldiers")

        # ── Three Black Crows ──
        if (not p2_bullish and not p1_bullish and not c_bullish and
            p1["Close"] < p2["Close"] and curr["Close"] < p1["Close"] and
            p2_body_ratio > 0.4 and p1_body_ratio > 0.4 and c_body_ratio > 0.4):
            found.append("three_black_crows")

        # ── Three Inside Up ──
        if (not p2_bullish and p1_bullish and
            p1["Open"] > p2["Close"] and p1["Close"] < p2["Open"] and
            c_bullish and curr["Close"] > p2["Open"]):
            found.append("three_inside_up")

        # ── Three Inside Down ──
        if (p2_bullish and not p1_bullish and
            p1["Open"] < p2["Close"] and p1["Close"] > p2["Open"] and
            not c_bullish and curr["Close"] < p2["Open"]):
            found.append("three_inside_down")

        # ── Three Outside Up ──
        if (not p2_bullish and p1_bullish and
            p1["Open"] <= p2["Close"] and p1["Close"] >= p2["Open"] and p1_body > p2_body and
            c_bullish and curr["Close"] > p1["Close"]):
            found.append("three_outside_up")

        # ── Three Outside Down ──
        if (p2_bullish and not p1_bullish and
            p1["Open"] >= p2["Close"] and p1["Close"] <= p2["Open"] and p1_body > p2_body and
            not c_bullish and curr["Close"] < p1["Close"]):
            found.append("three_outside_down")

        # ── Abandoned Baby Bullish ──
        if (not p2_bullish and p1_body_ratio < 0.05 and c_bullish and
            p1["High"] < p2["Low"] and p1["High"] < curr["Low"]):
            found.append("abandoned_baby_bullish")

        # ── Abandoned Baby Bearish ──
        if (p2_bullish and p1_body_ratio < 0.05 and not c_bullish and
            p1["Low"] > p2["High"] and p1["Low"] > curr["High"]):
            found.append("abandoned_baby_bearish")

        # ── Rising Three Methods ──
        if (p2_bullish and p2_body > p1_body * 1.5 and
            c_bullish and c_body > p1_body * 1.5 and
            curr["Close"] > p2["Close"] and
            p1["Low"] >= p2["Low"] and p1["High"] <= p2["High"]):
            found.append("rising_three_methods")

        # ── Falling Three Methods ──
        if (not p2_bullish and p2_body > p1_body * 1.5 and
            not c_bullish and c_body > p1_body * 1.5 and
            curr["Close"] < p2["Close"] and
            p1["Low"] >= curr["Low"] and p1["High"] <= p2["High"]):
            found.append("falling_three_methods")

        # ── Advance Block ──
        if (p2_bullish and p1_bullish and c_bullish and
            p1["Close"] > p2["Close"] and curr["Close"] > p1["Close"] and
            p1_body < p2_body and c_body < p1_body):
            c_upper = curr["High"] - curr["Close"]
            p1_upper = p1["High"] - p1["Close"]
            if c_upper > p1_upper and c_range > 0:
                found.append("advance_block")

        # ── Deliberation (Stalled Pattern) ──
        if (p2_bullish and p1_bullish and p2_body > 0 and p1_body > 0 and
            p1["Close"] > p2["Close"] and
            c_body < p1_body * 0.3 and c_range > 0):
            if c_body_ratio < 0.3:
                found.append("deliberation")

        # ── Tri-Star Bullish / Bearish ──
        if (p2_range > 0 and p1_range > 0 and c_range > 0):
            p2_br = p2_body / p2_range
            p1_br = p1_body / p1_range
            c_br = c_body / c_range
            if p2_br < 0.1 and p1_br < 0.1 and c_br < 0.1:
                p1_mid = (p1["Open"] + p1["Close"]) / 2
                p2_mid = (p2["Open"] + p2["Close"]) / 2
                c_mid = (curr["Open"] + curr["Close"]) / 2
                if p1_mid < p2_mid and p1_mid < c_mid:
                    found.append("tri_star_bullish")
                elif p1_mid > p2_mid and p1_mid > c_mid:
                    found.append("tri_star_bearish")

        # ── Upside Tasuki Gap ──
        if (p2_bullish and p1_bullish and not c_bullish and
            p1["Open"] > p2["Close"] and
            curr["Open"] > p1["Open"] and curr["Open"] < p1["Close"] and
            curr["Close"] > p2["Close"] and curr["Close"] < p1["Open"]):
            found.append("upside_tasuki_gap")

        # ── Downside Tasuki Gap ──
        if (not p2_bullish and not p1_bullish and c_bullish and
            p1["Open"] < p2["Close"] and
            curr["Open"] < p1["Open"] and curr["Open"] > p1["Close"] and
            curr["Close"] < p2["Close"] and curr["Close"] > p1["Open"]):
            found.append("downside_tasuki_gap")

        # ── Upside Gap Two Crows ──
        if (p2_bullish and not p1_bullish and not c_bullish and
            p1["Open"] > p2["Close"] and  # gap up
            c_body > p1_body and  # second crow larger
            curr["Open"] > p1["Open"] and curr["Close"] < p1["Close"] and
            curr["Close"] > p2["Close"]):  # but still above gap
            found.append("upside_gap_two_crows")

        # ── Mat Hold (bullish continuation) ──
        if (p2_bullish and c_bullish and
            p2_body > p1_body * 2 and
            p1["Close"] > p2["Open"] and  # stays within body
            curr["Close"] > p2["Close"] and c_body > p1_body * 1.5):
            found.append("mat_hold")

        # ── Stick Sandwich (two same-close bearish around a bullish) ──
        if (not p2_bullish and p1_bullish and not c_bullish and
            abs(p2["Close"] - curr["Close"]) < 0.002 * max(p2["Close"], 0.01)):
            found.append("stick_sandwich")

        # ── Unique Three River (bearish → harami → small bullish below) ──
        if (not p2_bullish and not p1_bullish and c_bullish and
            p1_body < p2_body * 0.5 and
            p1["Open"] < p2["Open"] and p1["Close"] > p2["Close"] and
            curr["Close"] < p1["Close"] and c_body < p1_body):
            found.append("unique_three_river")

        # ── Ladder Bottom ──
        if (not p2_bullish and not p1_bullish and c_bullish and
            p1["Close"] < p2["Close"] and  # continuing down
            curr["Close"] > p1["Open"]):  # strong reversal
            p1_lower = min(p1["Open"], p1["Close"]) - p1["Low"]
            if p1_lower > p1_body * 0.5:  # long lower shadow on p1
                found.append("ladder_bottom")

        # ── Concealing Baby Swallow ──
        if (not p2_bullish and not p1_bullish and
            p2_body_ratio > 0.85 and  # marubozu-like
            p1_body_ratio > 0.85 and
            not c_bullish and
            curr["High"] > p1["Close"] and curr["Close"] < p1["Close"]):
            found.append("concealing_baby_swallow")

        # ── Three Stars in the South ──
        if (not p2_bullish and not p1_bullish and not c_bullish and
            p1_body < p2_body and c_body < p1_body and
            p1["Low"] > p2["Low"] and curr["Low"] > p1["Low"]):
            found.append("three_stars_south")

        if found:
            patterns.iloc[i] = ",".join(found)

    return patterns


# ============================================================
# 4. COMBINED DETECTOR
# ============================================================

def detect_all_patterns(df):
    """Run all three pattern detection phases, combine, and score results."""
    print("    Detecting single-candle patterns...", flush=True)
    df["pattern_single"] = df.apply(classify_single_candle, axis=1)

    print("    Detecting two-candle patterns...", flush=True)
    df["pattern_double"] = detect_two_candle_patterns(df)

    print("    Detecting three-candle patterns...", flush=True)
    df["pattern_triple"] = detect_three_candle_patterns(df)

    def combine(row):
        parts = [p for p in [row["pattern_single"], row["pattern_double"],
                             row["pattern_triple"]] if p and p != "none"]
        return ",".join(parts) if parts else "none"

    df["patterns_all"] = df.apply(combine, axis=1)

    # Volume confirmation & confidence scoring
    print("    Computing pattern confidence & volume confirmation...", flush=True)
    _compute_pattern_scores(df)

    return df


# ============================================================
# 4b. PATTERN CONFIDENCE & VOLUME CONFIRMATION
# ============================================================

def _compute_pattern_scores(df):
    """
    Post-process detected patterns with confidence scoring and volume
    confirmation.  Adds two columns:
      - pattern_confidence (float 0.0-1.0)
      - volume_confirmed   (bool)

    Scoring factors:
      1. Base reliability from PATTERN_KB (Bulkowski / book data)
      2. Volume confirmation (using vol_ratio or raw Volume column)
      3. Trend context alignment
      4. RSI extremes (oversold + bullish reversal = bonus)
    """
    has_volume = "Volume" in df.columns and df["Volume"].sum() > 0

    # Ensure vol_ratio exists (compute inline if missing)
    if has_volume and "vol_ratio" not in df.columns:
        vol_ma = df["Volume"].rolling(window=20, min_periods=1).mean()
        df["vol_ratio"] = df["Volume"] / vol_ma

    confidences = np.zeros(len(df), dtype=np.float64)
    vol_confirmed = np.zeros(len(df), dtype=bool)

    for i in range(len(df)):
        patterns_str = df["patterns_all"].iat[i]

        if not patterns_str or patterns_str == "none":
            continue

        pattern_list = [p.strip() for p in patterns_str.split(",") if p.strip()]
        if not pattern_list:
            continue

        # --- 1. Base reliability from KB ---
        base_scores = []
        for p in pattern_list:
            kb = PATTERN_KB.get(p)
            base_scores.append(kb["reliability"] if kb else 0.50)

        confidence = max(base_scores)

        # --- 2. Volume confirmation ---
        vr = df["vol_ratio"].iat[i] if "vol_ratio" in df.columns else np.nan
        is_confirmed = False

        if has_volume and pd.notna(vr):
            has_rev = any(p in _ALL_REVERSAL for p in pattern_list)
            has_cont = any(p in _CONTINUATION for p in pattern_list)
            has_indec = any(p in _INDECISION for p in pattern_list)

            if has_rev:
                # Reversal: HIGH volume confirms, LOW volume weakens
                if vr >= 1.5:
                    is_confirmed = True
                    confidence = min(1.0, confidence + 0.15)
                elif vr >= 1.0:
                    is_confirmed = True
                    confidence = min(1.0, confidence + 0.05)
                else:
                    # Low-volume reversal — not confirmed, penalize
                    confidence = max(0.10, confidence - 0.15)

            elif has_cont:
                # Continuation: LOW volume on correction candles is ideal
                if vr < 0.8:
                    is_confirmed = True
                    confidence = min(1.0, confidence + 0.10)
                elif vr > 1.5:
                    # Suspiciously high volume during continuation pause
                    confidence = max(0.10, confidence - 0.10)
                else:
                    is_confirmed = True  # average is acceptable

            elif has_indec:
                # Indecision: HIGH volume makes it more significant
                if vr >= 1.5:
                    is_confirmed = True
                    confidence = min(1.0, confidence + 0.10)
                # Low-volume indecision is normal, no penalty

            # --- Multi-candle volume trend ---
            # For two/three-candle reversals, check if volume is rising
            if has_rev and i >= 1 and "Volume" in df.columns:
                prev_vol = df["Volume"].iat[i - 1]
                curr_vol = df["Volume"].iat[i]
                if prev_vol > 0 and curr_vol > prev_vol * 1.2:
                    # Volume expanding on reversal candle
                    confidence = min(1.0, confidence + 0.05)

        # --- 3. Trend alignment ---
        trend = df.get("trend_short")
        if trend is not None:
            trend_val = trend.iat[i] if hasattr(trend, "iat") else "unknown"
            has_bull = any(p in _BULLISH_REVERSAL for p in pattern_list)
            has_bear = any(p in _BEARISH_REVERSAL for p in pattern_list)

            if has_bull and trend_val == "bearish":
                # Bullish reversal forming at end of downtrend — correct
                confidence = min(1.0, confidence + 0.05)
            elif has_bear and trend_val == "bullish":
                # Bearish reversal forming at end of uptrend — correct
                confidence = min(1.0, confidence + 0.05)

        # --- 4. RSI extreme bonus ---
        rsi_col = df.get("rsi_14")
        if rsi_col is not None:
            rsi_val = rsi_col.iat[i] if hasattr(rsi_col, "iat") else np.nan
            if pd.notna(rsi_val):
                has_bull = any(p in _BULLISH_REVERSAL for p in pattern_list)
                has_bear = any(p in _BEARISH_REVERSAL for p in pattern_list)
                if has_bull and rsi_val < 30:
                    confidence = min(1.0, confidence + 0.10)
                elif has_bear and rsi_val > 70:
                    confidence = min(1.0, confidence + 0.10)

        confidences[i] = round(confidence, 3)
        vol_confirmed[i] = is_confirmed

    df["pattern_confidence"] = confidences
    df["volume_confirmed"] = vol_confirmed


# ============================================================
# 5. MARKET REGIME DETECTOR
# ============================================================

def detect_market_regime(df):
    """
    Detect market regime: trending/ranging, bull/bear.
    Uses ADX for trend strength, EMA slope for direction,
    ATR for volatility regime.
    """
    regime = pd.Series("unknown", index=df.index)

    adx = df.get("ADX_14")
    ema_9 = df.get("ema_9")
    ema_21 = df.get("ema_21")
    ema_50 = df.get("ema_50")
    atr = df.get("atr_14")

    for i in range(len(df)):
        parts = []

        # Trend strength
        if adx is not None and pd.notna(adx.iloc[i]):
            adx_val = adx.iloc[i]
            if adx_val > 40:
                parts.append("strong_trend")
            elif adx_val > 25:
                parts.append("trending")
            elif adx_val > 20:
                parts.append("weak_trend")
            else:
                parts.append("ranging")

        # Trend direction (EMA alignment)
        if (ema_9 is not None and ema_21 is not None and ema_50 is not None and
            pd.notna(ema_9.iloc[i]) and pd.notna(ema_21.iloc[i]) and pd.notna(ema_50.iloc[i])):
            if ema_9.iloc[i] > ema_21.iloc[i] > ema_50.iloc[i]:
                parts.append("bullish_aligned")
            elif ema_9.iloc[i] < ema_21.iloc[i] < ema_50.iloc[i]:
                parts.append("bearish_aligned")
            else:
                parts.append("mixed")

        # Volatility regime
        if atr is not None and pd.notna(atr.iloc[i]):
            atr_val = atr.iloc[i]
            close_val = df["Close"].iloc[i]
            if close_val > 0:
                atr_pct = atr_val / close_val
                if atr_pct > 0.025:  # > 2.5% ATR
                    parts.append("high_volatility")
                elif atr_pct < 0.008:  # < 0.8% ATR
                    parts.append("low_volatility")
                else:
                    parts.append("normal_volatility")

        regime.iloc[i] = "|".join(parts) if parts else "unknown"

    return regime


# ============================================================
# 6. LIVE PATTERN DETECTION (for real-time analysis)
# ============================================================

def detect_live_patterns(df):
    """
    Run pattern detection on live data (typically 50-100 candles).
    Returns dict with patterns, confidence, and volume_confirmed for the
    last candle.
    """
    if len(df) < 3:
        return {"patterns": "none", "confidence": 0.0, "volume_confirmed": False}

    df = detect_all_patterns(df)
    last = df.iloc[-1]
    patterns = last.get("patterns_all", "none")
    patterns = patterns if patterns and patterns != "none" else "none"
    confidence = float(last.get("pattern_confidence", 0.0))
    vol_conf = bool(last.get("volume_confirmed", False))

    return {
        "patterns": patterns,
        "confidence": confidence,
        "volume_confirmed": vol_conf,
    }


def get_recent_pattern_summary(df, lookback=5):
    """
    Get a summary of patterns in the last N candles.
    Returns dict with pattern names, positions, confidence, and
    volume confirmation.
    """
    if len(df) < 3:
        return {}

    df = detect_all_patterns(df)
    summary = {}
    start = max(0, len(df) - lookback)

    for i in range(start, len(df)):
        pats = df["patterns_all"].iloc[i]
        conf = float(df["pattern_confidence"].iloc[i])
        vol_c = bool(df["volume_confirmed"].iloc[i])
        if pats and pats != "none":
            for p in pats.split(","):
                p = p.strip()
                if p:
                    if p not in summary:
                        summary[p] = {"positions": [], "confidence": 0.0,
                                      "volume_confirmed": False}
                    summary[p]["positions"].append(i - len(df) + 1)
                    # Keep max confidence across occurrences
                    summary[p]["confidence"] = max(summary[p]["confidence"], conf)
                    summary[p]["volume_confirmed"] = (
                        summary[p]["volume_confirmed"] or vol_c
                    )

    return summary


# ============================================================
# 7. SUPPORT / RESISTANCE DETECTION
# ============================================================

def detect_swing_points(df, window=10):
    """
    Detect swing highs and swing lows using a rolling window.

    A swing high is where High[i] is the maximum in [i-window : i+window].
    A swing low  is where Low[i]  is the minimum in [i-window : i+window].

    Returns two boolean Series: (swing_highs, swing_lows).
    """
    highs = df["High"].values
    lows = df["Low"].values
    n = len(df)

    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)

    for i in range(window, n - window):
        left_h = highs[i - window: i]
        right_h = highs[i + 1: i + 1 + window]
        if highs[i] >= left_h.max() and highs[i] >= right_h.max():
            sh[i] = True

        left_l = lows[i - window: i]
        right_l = lows[i + 1: i + 1 + window]
        if lows[i] <= left_l.min() and lows[i] <= right_l.min():
            sl[i] = True

    return pd.Series(sh, index=df.index), pd.Series(sl, index=df.index)


def find_sr_levels(df, window=10, lookback=100, tolerance_pct=0.5):
    """
    Find support and resistance levels from recent swing points.

    1. Detects swing highs/lows in the lookback window.
    2. Clusters nearby levels (within tolerance_pct %).
    3. Returns sorted list of (level, type, touch_count, last_touch_idx).
    """
    if len(df) < lookback:
        lookback = len(df)

    sub = df.iloc[-lookback:]
    swing_highs, swing_lows = detect_swing_points(sub, window=min(window, lookback // 4))

    # Collect raw levels
    raw_levels = []
    for i in range(len(sub)):
        if swing_highs.iloc[i]:
            raw_levels.append(("resistance", float(sub["High"].iloc[i]), i))
        if swing_lows.iloc[i]:
            raw_levels.append(("support", float(sub["Low"].iloc[i]), i))

    if not raw_levels:
        return []

    # Sort by price
    raw_levels.sort(key=lambda x: x[1])

    # Cluster levels within tolerance
    clusters = []
    current_cluster = [raw_levels[0]]

    for j in range(1, len(raw_levels)):
        prev_price = current_cluster[-1][1]
        curr_price = raw_levels[j][1]
        if abs(curr_price - prev_price) / max(prev_price, 0.01) * 100 <= tolerance_pct:
            current_cluster.append(raw_levels[j])
        else:
            clusters.append(current_cluster)
            current_cluster = [raw_levels[j]]
    clusters.append(current_cluster)

    # Aggregate clusters
    sr_levels = []
    for cluster in clusters:
        avg_price = np.mean([c[1] for c in cluster])
        touch_count = len(cluster)
        # Type: majority vote
        n_support = sum(1 for c in cluster if c[0] == "support")
        n_resist = sum(1 for c in cluster if c[0] == "resistance")
        sr_type = "support" if n_support >= n_resist else "resistance"
        last_idx = max(c[2] for c in cluster)
        sr_levels.append({
            "level": round(avg_price, 2),
            "type": sr_type,
            "touches": touch_count,
            "last_touch_offset": lookback - 1 - last_idx,  # candles ago
        })

    return sr_levels


def classify_sr_position(close_price, sr_levels, proximity_pct=1.0):
    """
    Classify where the current price sits relative to S/R levels.

    Returns:
        sr_position: "at_support", "at_resistance", "between_sr", "above_all", "below_all"
        nearest_support: float or None
        nearest_resistance: float or None
        support_distance_pct: float or None
        resistance_distance_pct: float or None
    """
    if not sr_levels or close_price <= 0:
        return {
            "sr_position": "unknown",
            "nearest_support": None,
            "nearest_resistance": None,
            "support_distance_pct": None,
            "resistance_distance_pct": None,
        }

    supports = [s for s in sr_levels if s["type"] == "support"]
    resistances = [s for s in sr_levels if s["type"] == "resistance"]

    # Find nearest support below (or at) current price
    nearest_sup = None
    for s in sorted(supports, key=lambda x: -x["level"]):
        if s["level"] <= close_price * 1.005:  # allow small overshoot
            nearest_sup = s
            break

    # Find nearest resistance above (or at) current price
    nearest_res = None
    for r in sorted(resistances, key=lambda x: x["level"]):
        if r["level"] >= close_price * 0.995:  # allow small undershoot
            nearest_res = r
            break

    sup_dist = None
    res_dist = None

    if nearest_sup:
        sup_dist = round((close_price - nearest_sup["level"]) / close_price * 100, 2)
    if nearest_res:
        res_dist = round((nearest_res["level"] - close_price) / close_price * 100, 2)

    # Classify position
    position = "between_sr"

    if sup_dist is not None and sup_dist <= proximity_pct:
        position = "at_support"
    elif res_dist is not None and res_dist <= proximity_pct:
        position = "at_resistance"
    elif nearest_sup is None and nearest_res is not None:
        position = "below_all"
    elif nearest_res is None and nearest_sup is not None:
        position = "above_all"

    return {
        "sr_position": position,
        "nearest_support": nearest_sup["level"] if nearest_sup else None,
        "nearest_resistance": nearest_res["level"] if nearest_res else None,
        "support_distance_pct": sup_dist,
        "resistance_distance_pct": res_dist,
    }


def add_sr_to_dataframe(df, window=10, lookback=100, proximity_pct=1.0):
    """
    Add S/R columns to the dataframe for each row.
    Uses an expanding window: for row i, S/R is computed from rows [0..i].
    For efficiency, recomputes every `window` rows, not every row.

    Adds columns:
      - sr_position: at_support / at_resistance / between_sr / above_all / below_all
      - nearest_support: float
      - nearest_resistance: float
      - support_distance_pct: float
      - resistance_distance_pct: float
    """
    n = len(df)
    positions = ["unknown"] * n
    sup_levels = [np.nan] * n
    res_levels = [np.nan] * n
    sup_dists = [np.nan] * n
    res_dists = [np.nan] * n

    # Min data needed for S/R
    min_rows = max(2 * window + 1, 50)

    # Cache: recompute S/R every `window` rows
    cached_sr = []
    last_compute = -window  # force first computation

    for i in range(min_rows, n):
        # Recompute S/R levels periodically
        if i - last_compute >= window:
            sub = df.iloc[max(0, i - lookback): i + 1]
            cached_sr = find_sr_levels(sub, window=window, lookback=len(sub),
                                        tolerance_pct=0.5)
            last_compute = i

        close_price = float(df["Close"].iat[i])
        result = classify_sr_position(close_price, cached_sr, proximity_pct)

        positions[i] = result["sr_position"]
        sup_levels[i] = result["nearest_support"]
        res_levels[i] = result["nearest_resistance"]
        sup_dists[i] = result["support_distance_pct"]
        res_dists[i] = result["resistance_distance_pct"]

    df["sr_position"] = positions
    df["nearest_support"] = sup_levels
    df["nearest_resistance"] = res_levels
    df["support_distance_pct"] = sup_dists
    df["resistance_distance_pct"] = res_dists

    return df
