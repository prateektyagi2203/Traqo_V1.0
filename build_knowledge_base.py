"""
Knowledge Base Builder
======================
Reads parsed_knowledge/all_book_knowledge.json (extracted from 12 books)
and generates the comprehensive candlestick_knowledge_base.py with:
- 53+ pattern entries enriched with real book knowledge
- Volume analysis rules (from Anna Coulling)
- Risk management rules (from Elder)
- Trading psychology principles (from Douglas)
- Intraday/session rules (from Volman)
- Entry/exit/stoploss framework (from High Prob Strategies + Pivots)
- Pattern confirmation criteria (from Morris, Nison)
"""

import json
import os
import re
import textwrap
from collections import defaultdict

PARSED_PATH = "parsed_knowledge/all_book_knowledge.json"
OUTPUT_PATH = "candlestick_knowledge_base.py"


def load_parsed():
    with open(PARSED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_text(text, max_len=300):
    """Clean extracted text for use in Python string."""
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace('"', "'").replace('\\', '/')
    if len(text) > max_len:
        text = text[:max_len-3] + "..."
    return text


def pick_best(items, max_items=3, max_len=200):
    """Pick the most informative items, deduplicate, clean."""
    if not items:
        return []
    # Score by length (prefer medium-length) and uniqueness
    scored = []
    seen_starts = set()
    for item in items:
        clean = clean_text(item, max_len)
        start = clean[:50].lower()
        if start in seen_starts:
            continue
        seen_starts.add(start)
        # Prefer items that are 50-200 chars
        length_score = min(len(clean), 200) / 200
        scored.append((length_score, clean))
    scored.sort(key=lambda x: -x[0])
    return [s[1] for s in scored[:max_items]]


def extract_summary(descriptions, max_len=300):
    """Create a summary from multiple descriptions."""
    if not descriptions:
        return "No description available."
    # Pick the longest, most informative one
    best = sorted(descriptions, key=len, reverse=True)
    for desc in best:
        clean = clean_text(desc, max_len)
        if len(clean) > 40:
            return clean
    return clean_text(descriptions[0], max_len)


def generate_kb():
    print("Loading parsed book knowledge...")
    data = load_parsed()

    patterns = data["consolidated_patterns"]
    volume_knowledge = data.get("volume_knowledge", {})
    price_action = data.get("price_action_knowledge", {})
    entry_exit = data.get("entry_exit_knowledge", {})
    risk_mgmt = data.get("risk_management", {})
    psychology = data.get("trading_psychology", {})
    bulkowski = data.get("bulkowski_stats", {})

    # ── Build pattern classification ──
    BULLISH_REVERSAL = {
        "hammer", "inverted_hammer", "dragonfly_doji", "bullish_engulfing",
        "bullish_harami", "piercing_line", "tweezer_bottom", "bullish_kicker",
        "bullish_counterattack", "morning_star", "morning_doji_star",
        "three_white_soldiers", "three_inside_up", "three_outside_up",
        "abandoned_baby_bullish", "rising_three_methods", "tri_star",
        "unique_three_river", "three_stars_south", "concealing_baby_swallow",
        "ladder_bottom", "matching_low", "stick_sandwich", "homing_pigeon",
        "belt_hold", "mat_hold",
    }
    BEARISH_REVERSAL = {
        "hanging_man", "shooting_star", "gravestone_doji", "bearish_engulfing",
        "bearish_harami", "dark_cloud_cover", "tweezer_top", "bearish_kicker",
        "bearish_counterattack", "evening_star", "evening_doji_star",
        "three_black_crows", "three_inside_down", "three_outside_down",
        "abandoned_baby_bearish", "advance_block", "deliberation",
        "upside_gap_two_crows", "matching_high", "separating_lines",
    }
    CONTINUATION = {
        "rising_three_methods", "falling_three_methods", "mat_hold",
        "upside_tasuki_gap", "downside_tasuki_gap", "on_neck", "in_neck",
    }
    NEUTRAL = {
        "doji", "long_legged_doji", "spinning_top", "high_wave", "marubozu",
        "bullish_marubozu", "bearish_marubozu", "harami_cross",
    }

    def get_signal(pat_name):
        if pat_name in BULLISH_REVERSAL:
            return "bullish reversal"
        elif pat_name in BEARISH_REVERSAL:
            return "bearish reversal"
        elif pat_name in CONTINUATION:
            return "continuation"
        elif "bullish" in pat_name:
            return "bullish"
        elif "bearish" in pat_name:
            return "bearish"
        return "neutral/indecision"

    def get_pattern_type(pat_name):
        if pat_name in {"doji", "long_legged_doji", "gravestone_doji", "dragonfly_doji",
                        "hammer", "hanging_man", "shooting_star", "inverted_hammer",
                        "marubozu", "bullish_marubozu", "bearish_marubozu",
                        "spinning_top", "belt_hold", "high_wave"}:
            return "single"
        elif pat_name in {"bullish_engulfing", "bearish_engulfing", "bullish_harami",
                          "bearish_harami", "harami_cross", "piercing_line",
                          "dark_cloud_cover", "tweezer_top", "tweezer_bottom",
                          "bullish_kicker", "bearish_kicker", "on_neck", "in_neck",
                          "bullish_counterattack", "bearish_counterattack",
                          "homing_pigeon", "matching_low", "matching_high",
                          "stick_sandwich", "separating_lines"}:
            return "double"
        return "triple"

    # ── Base reliability estimates (refined by book evidence) ──
    RELIABILITY_MAP = {
        "doji": 0.45, "long_legged_doji": 0.40, "gravestone_doji": 0.60,
        "dragonfly_doji": 0.60, "hammer": 0.65, "hanging_man": 0.55,
        "shooting_star": 0.60, "inverted_hammer": 0.55, "marubozu": 0.70,
        "bullish_marubozu": 0.72, "bearish_marubozu": 0.72,
        "spinning_top": 0.35, "belt_hold": 0.55, "high_wave": 0.35,
        "bullish_engulfing": 0.70, "bearish_engulfing": 0.72,
        "bullish_harami": 0.50, "bearish_harami": 0.48,
        "harami_cross": 0.55, "piercing_line": 0.64,
        "dark_cloud_cover": 0.62, "tweezer_top": 0.55,
        "tweezer_bottom": 0.55, "bullish_kicker": 0.80,
        "bearish_kicker": 0.80, "on_neck": 0.40, "in_neck": 0.38,
        "bullish_counterattack": 0.50, "bearish_counterattack": 0.50,
        "morning_star": 0.75, "morning_doji_star": 0.78,
        "evening_star": 0.75, "evening_doji_star": 0.78,
        "three_white_soldiers": 0.72, "three_black_crows": 0.72,
        "three_inside_up": 0.65, "three_inside_down": 0.65,
        "three_outside_up": 0.70, "three_outside_down": 0.70,
        "abandoned_baby_bullish": 0.80, "abandoned_baby_bearish": 0.80,
        "rising_three_methods": 0.68, "falling_three_methods": 0.68,
        "advance_block": 0.58, "deliberation": 0.55,
        "tri_star": 0.60, "upside_tasuki_gap": 0.55,
        "downside_tasuki_gap": 0.55, "upside_gap_two_crows": 0.62,
        "mat_hold": 0.72, "unique_three_river": 0.55,
        "three_stars_south": 0.50, "concealing_baby_swallow": 0.65,
        "ladder_bottom": 0.60, "homing_pigeon": 0.48,
        "matching_low": 0.52, "matching_high": 0.50,
        "stick_sandwich": 0.55, "separating_lines": 0.50,
    }

    # Adjust reliability based on how much book evidence we have
    for pat, info in patterns.items():
        n_sources = len(info.get("sources", []))
        n_stats = len(info.get("statistics", []))
        n_rules = len(info.get("formation_rules", []))
        # More corroboration → slight reliability boost
        if n_sources >= 4 and n_stats >= 3:
            if pat in RELIABILITY_MAP:
                RELIABILITY_MAP[pat] = min(0.85, RELIABILITY_MAP[pat] + 0.05)
        elif n_sources >= 3:
            if pat in RELIABILITY_MAP:
                RELIABILITY_MAP[pat] = min(0.82, RELIABILITY_MAP[pat] + 0.02)

    # ── Generate Python code ──
    print(f"Generating knowledge base with {len(patterns)} patterns...")

    lines = []
    lines.append('"""')
    lines.append('Candlestick Pattern Knowledge Base — Book-Enriched Edition')
    lines.append('=' * 60)
    lines.append('Auto-generated from 12 trading/candlestick books:')
    lines.append('  CRITICAL: Morris (Candlestick Charting Explained),')
    lines.append('            Nison (Beyond Candlesticks),')
    lines.append('            Bulkowski (Encyclopedia of Chart Patterns),')
    lines.append('            Person (Candlestick & Pivot Point Triggers)')
    lines.append('  HIGH VALUE: Coulling (Volume Price Analysis),')
    lines.append('              Volman (Understanding Price Action 5-min),')
    lines.append('              Miner (High Probability Trading Strategies),')
    lines.append('              Pesavento (Trade What You See)')
    lines.append('  SUPPLEMENTARY: Douglas (Trading in the Zone),')
    lines.append('                 Elder (New Trading for a Living)')
    lines.append('')
    lines.append(f'Total patterns: {len(patterns)}')
    lines.append(f'Total book-extracted rules: {sum(len(v.get("formation_rules", [])) for v in patterns.values())}')
    lines.append('"""')
    lines.append('')

    # ── PATTERN_KB dict ──
    lines.append('PATTERN_KB = {')

    for pat_name in sorted(patterns.keys()):
        info = patterns[pat_name]
        signal = get_signal(pat_name)
        pat_type = get_pattern_type(pat_name)
        reliability = RELIABILITY_MAP.get(pat_name, 0.50)
        sources = info.get("sources", [])

        description = extract_summary(info.get("descriptions", []))
        formation_rules = pick_best(info.get("formation_rules", []), 5, 250)
        confirmation = pick_best(info.get("confirmation_criteria", []), 3, 250)
        statistics_raw = pick_best(info.get("statistics", []), 3, 250)
        psychology_raw = pick_best(info.get("psychology", []), 2, 250)
        entry_exit_raw = pick_best(info.get("entry_exit_rules", []), 4, 250)
        volume_raw = pick_best(info.get("volume_requirements", []), 2, 250)
        context_raw = pick_best(info.get("context_rules", []), 2, 250)
        tips_raw = pick_best(info.get("trading_tips", []), 2, 250)

        lines.append(f'    "{pat_name}": {{')
        lines.append(f'        "name": "{pat_name.replace("_", " ").title()}",')
        lines.append(f'        "type": "{pat_type}",')
        lines.append(f'        "signal": "{signal}",')
        lines.append(f'        "reliability": {reliability},')
        lines.append(f'        "sources": {sources},')
        lines.append(f'        "description": "{description}",')

        # Formation rules from books
        lines.append(f'        "formation_rules": [')
        for rule in formation_rules:
            lines.append(f'            "{rule}",')
        lines.append(f'        ],')

        # Confirmation
        lines.append(f'        "confirmation": [')
        for c in confirmation:
            lines.append(f'            "{c}",')
        lines.append(f'        ],')

        # Statistics from books
        lines.append(f'        "statistics": [')
        for s in statistics_raw:
            lines.append(f'            "{s}",')
        lines.append(f'        ],')

        # Psychology
        lines.append(f'        "psychology": [')
        for p in psychology_raw:
            lines.append(f'            "{p}",')
        lines.append(f'        ],')

        # Entry/Exit/Stoploss
        lines.append(f'        "entry_exit_stoploss": [')
        for ee in entry_exit_raw:
            lines.append(f'            "{ee}",')
        lines.append(f'        ],')

        # Volume requirements
        lines.append(f'        "volume_notes": [')
        for v in volume_raw:
            lines.append(f'            "{v}",')
        lines.append(f'        ],')

        # Context rules
        lines.append(f'        "context_rules": [')
        for cr in context_raw:
            lines.append(f'            "{cr}",')
        lines.append(f'        ],')

        # Trading tips
        lines.append(f'        "trading_tips": [')
        for t in tips_raw:
            lines.append(f'            "{t}",')
        lines.append(f'        ],')

        lines.append(f'    }},')
        lines.append('')

    lines.append('}')
    lines.append('')

    # ── VOLUME ANALYSIS RULES (from Coulling) ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# VOLUME ANALYSIS RULES (from Anna Coulling)')
    lines.append('# ' + '=' * 60)
    lines.append('')

    vol_rules = pick_best(volume_knowledge.get("volume_rules", []), 25, 300)
    vol_pattern = pick_best(volume_knowledge.get("volume_pattern_rules", []), 25, 300)
    vol_anomaly = pick_best(volume_knowledge.get("anomaly_rules", []), 15, 300)

    lines.append('VOLUME_RULES = [')
    for r in vol_rules:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('VOLUME_PATTERN_RULES = [')
    for r in vol_pattern:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('VOLUME_ANOMALY_RULES = [')
    for r in vol_anomaly:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    # ── INTRADAY / SESSION RULES (from Volman) ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# INTRADAY & SESSION RULES (from Volman)')
    lines.append('# ' + '=' * 60)
    lines.append('')

    intraday = pick_best(price_action.get("intraday_rules", []), 25, 300)
    session = pick_best(price_action.get("session_rules", []), 25, 300)
    pa_principles = pick_best(price_action.get("price_action_principles", []), 25, 300)

    lines.append('INTRADAY_RULES = [')
    for r in intraday:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('SESSION_RULES = [')
    for r in session:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('PRICE_ACTION_PRINCIPLES = [')
    for r in pa_principles:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    # ── ENTRY / EXIT / STOPLOSS FRAMEWORK (from Miner + Person) ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# ENTRY / EXIT / STOPLOSS FRAMEWORK (from Miner, Person)')
    lines.append('# ' + '=' * 60)
    lines.append('')

    pivots_data = entry_exit.get("pivots", {})
    high_prob = entry_exit.get("high_prob", {})

    entry_rules = pick_best(pivots_data.get("entry_rules", []), 20, 300)
    exit_rules = pick_best(pivots_data.get("exit_rules", []), 15, 300)
    sl_rules = pick_best(pivots_data.get("stoploss_rules", []), 15, 300)
    pivot_rules = pick_best(pivots_data.get("pivot_integration", []), 15, 300)

    hp_entry = pick_best(high_prob.get("entry_tactics", []), 15, 300)
    hp_exit = pick_best(high_prob.get("exit_tactics", []), 15, 300)
    hp_rr = pick_best(high_prob.get("risk_reward_rules", []), 10, 300)
    hp_fib = pick_best(high_prob.get("fibonacci_rules", []), 15, 300)
    hp_momentum = pick_best(high_prob.get("momentum_rules", []), 15, 300)

    lines.append('ENTRY_RULES = [')
    for r in entry_rules + hp_entry:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('EXIT_RULES = [')
    for r in exit_rules + hp_exit:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('STOPLOSS_RULES = [')
    for r in sl_rules:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('PIVOT_RULES = [')
    for r in pivot_rules:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('RISK_REWARD_RULES = [')
    for r in hp_rr:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('FIBONACCI_RULES = [')
    for r in hp_fib:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('MOMENTUM_RULES = [')
    for r in hp_momentum:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    # ── RISK MANAGEMENT (from Elder) ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# RISK MANAGEMENT (from Elder)')
    lines.append('# ' + '=' * 60)
    lines.append('')

    risk_rules = pick_best(risk_mgmt.get("risk_rules", []), 20, 300)
    pos_sizing = pick_best(risk_mgmt.get("position_sizing", []), 10, 300)
    money_mgmt = pick_best(risk_mgmt.get("money_management", []), 15, 300)
    indicator_rules = pick_best(risk_mgmt.get("indicator_rules", []), 20, 300)

    lines.append('RISK_MANAGEMENT_RULES = [')
    for r in risk_rules:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('POSITION_SIZING_RULES = [')
    for r in pos_sizing:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('MONEY_MANAGEMENT_RULES = [')
    for r in money_mgmt:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('ELDER_INDICATOR_RULES = [')
    for r in indicator_rules:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    # ── TRADING PSYCHOLOGY (from Douglas) ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# TRADING PSYCHOLOGY (from Douglas)')
    lines.append('# ' + '=' * 60)
    lines.append('')

    principles = pick_best(psychology.get("principles", []), 20, 300)
    discipline = pick_best(psychology.get("discipline_rules", []), 15, 300)
    mindset = pick_best(psychology.get("mindset_rules", []), 15, 300)

    lines.append('TRADING_PRINCIPLES = [')
    for r in principles:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('DISCIPLINE_RULES = [')
    for r in discipline:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    lines.append('MINDSET_RULES = [')
    for r in mindset:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    # ── BULKOWSKI STATISTICAL RULES ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# BULKOWSKI STATISTICAL RULES')
    lines.append('# ' + '=' * 60)
    lines.append('')

    bk_rules = pick_best(bulkowski.get("general_rules", []), 30, 300)
    lines.append('BULKOWSKI_RULES = [')
    for r in bk_rules:
        lines.append(f'    "{r}",')
    lines.append(']')
    lines.append('')

    # ── CONTEXT MODIFIERS ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# CONTEXT MODIFIERS')
    lines.append('# ' + '=' * 60)
    lines.append('')
    lines.append('''CONTEXT_MODIFIERS = {
    "trend_alignment": {
        "aligned": {"modifier": 1.15, "note": "Pattern aligns with prevailing trend — higher reliability"},
        "counter_trend": {"modifier": 0.75, "note": "Pattern fights the trend — lower reliability, need stronger confirmation"},
    },
    "volume_confirmation": {
        "high_volume": {"modifier": 1.20, "note": "Above-average volume confirms pattern (Coulling: volume validates price)"},
        "low_volume": {"modifier": 0.80, "note": "Below-average volume weakens pattern signal"},
        "volume_spike": {"modifier": 1.30, "note": "Volume spike with pattern is strongest confirmation"},
    },
    "rsi_context": {
        "oversold_bullish": {"modifier": 1.20, "note": "RSI < 30 + bullish pattern = strong reversal signal"},
        "overbought_bearish": {"modifier": 1.20, "note": "RSI > 70 + bearish pattern = strong reversal signal"},
        "oversold_bearish": {"modifier": 0.70, "note": "RSI < 30 + bearish pattern = likely false signal"},
        "overbought_bullish": {"modifier": 0.70, "note": "RSI > 70 + bullish pattern = likely false signal"},
        "neutral": {"modifier": 1.0, "note": "RSI neutral zone — pattern reliability at baseline"},
    },
    "support_resistance": {
        "at_support_bullish": {"modifier": 1.25, "note": "Bullish pattern at support = high probability reversal"},
        "at_resistance_bearish": {"modifier": 1.25, "note": "Bearish pattern at resistance = high probability reversal"},
        "at_support_bearish": {"modifier": 1.15, "note": "Bearish break of support = strong breakdown"},
        "at_resistance_bullish": {"modifier": 0.85, "note": "Bullish pattern at resistance faces selling pressure"},
    },
    "session_timing": {
        "opening_30min": {"modifier": 0.85, "note": "First 30 minutes volatile — patterns less reliable (Volman)"},
        "morning_session": {"modifier": 1.10, "note": "Morning session has best momentum follow-through"},
        "lunch_session": {"modifier": 0.80, "note": "Lunch doldrums — low commitment patterns"},
        "closing_30min": {"modifier": 0.90, "note": "End-of-day positioning can distort patterns"},
        "power_hour": {"modifier": 1.05, "note": "2-3pm often sees renewed momentum"},
    },
    "day_of_week": {
        "monday": {"modifier": 0.95, "note": "Monday gap risk — patterns affected by weekend news"},
        "tuesday_wednesday": {"modifier": 1.05, "note": "Mid-week has strongest trend days"},
        "thursday_expiry": {"modifier": 0.85, "note": "Expiry day — option activity distorts price patterns"},
        "friday": {"modifier": 0.90, "note": "Friday positioning may not follow through to Monday"},
    },
    "market_regime": {
        "strong_trend": {"modifier": 1.15, "note": "ADX > 25: trending market — continuation patterns more reliable"},
        "weak_trend": {"modifier": 0.90, "note": "ADX < 20: ranging market — reversal patterns at extremes"},
        "volatile": {"modifier": 0.85, "note": "High ATR relative to avg — larger stops needed, lower reliability"},
        "low_volatility": {"modifier": 1.05, "note": "Low volatility — breakout patterns more significant when they occur"},
    },
}
''')

    # ── HELPER FUNCTIONS ──
    lines.append('')
    lines.append('# ' + '=' * 60)
    lines.append('# HELPER FUNCTIONS')
    lines.append('# ' + '=' * 60)
    lines.append('')
    lines.append('''
def get_pattern_knowledge(pattern_names):
    """Get KB entries for a list of pattern names."""
    if isinstance(pattern_names, str):
        pattern_names = [p.strip() for p in pattern_names.split(",") if p.strip()]
    result = {}
    for name in pattern_names:
        name = name.strip().lower()
        if name in PATTERN_KB:
            result[name] = PATTERN_KB[name]
    return result


def get_reliability_rating(pattern_name):
    """Get reliability rating 0.0–1.0 for a pattern."""
    entry = PATTERN_KB.get(pattern_name.strip().lower())
    if entry:
        return entry["reliability"]
    return 0.5  # Default


def get_all_pattern_names():
    """Get list of all pattern names in KB."""
    return list(PATTERN_KB.keys())


def get_pattern_context_text(pattern_names, indicators=None):
    """
    Build a rich context text block for Ollama prompt injection.
    Combines pattern knowledge, volume rules, risk rules, and context modifiers.
    """
    if isinstance(pattern_names, str):
        pattern_names = [p.strip() for p in pattern_names.split(",") if p.strip()]

    sections = []
    sections.append("=" * 50)
    sections.append("CANDLESTICK PATTERN KNOWLEDGE BASE (Book-Enriched)")
    sections.append("=" * 50)

    for name in pattern_names:
        name = name.strip().lower()
        entry = PATTERN_KB.get(name)
        if not entry:
            continue

        sections.append(f"\\n--- {entry['name']} ---")
        sections.append(f"Type: {entry['type']} | Signal: {entry['signal']} | Reliability: {entry['reliability']:.0%}")
        sections.append(f"Sources: {', '.join(entry.get('sources', []))}")
        sections.append(f"Description: {entry['description']}")

        if entry.get('formation_rules'):
            sections.append("Formation Rules:")
            for rule in entry['formation_rules'][:3]:
                sections.append(f"  - {rule}")

        if entry.get('confirmation'):
            sections.append("Confirmation Criteria:")
            for c in entry['confirmation'][:2]:
                sections.append(f"  - {c}")

        if entry.get('statistics'):
            sections.append("Statistics:")
            for s in entry['statistics'][:2]:
                sections.append(f"  - {s}")

        if entry.get('psychology'):
            sections.append("Psychology:")
            for p in entry['psychology'][:2]:
                sections.append(f"  - {p}")

        if entry.get('entry_exit_stoploss'):
            sections.append("Entry/Exit/Stoploss:")
            for ee in entry['entry_exit_stoploss'][:3]:
                sections.append(f"  - {ee}")

        if entry.get('volume_notes'):
            sections.append("Volume:")
            for v in entry['volume_notes'][:2]:
                sections.append(f"  - {v}")

    # Add context modifiers if indicators provided
    if indicators:
        sections.append("\\n--- CONTEXTUAL MODIFIERS ---")
        rsi = indicators.get("rsi_14")
        vol_ratio = indicators.get("vol_ratio")
        adx = indicators.get("adx")
        trend = indicators.get("trend_short")

        if rsi is not None:
            if rsi < 30:
                sections.append(f"RSI={rsi:.1f} → OVERSOLD — bullish patterns +20% reliability")
            elif rsi > 70:
                sections.append(f"RSI={rsi:.1f} → OVERBOUGHT — bearish patterns +20% reliability")
            else:
                sections.append(f"RSI={rsi:.1f} → Neutral zone")

        if vol_ratio is not None:
            if vol_ratio > 1.5:
                sections.append(f"Volume ratio={vol_ratio:.1f}x → HIGH VOLUME — strong confirmation (+20-30%)")
            elif vol_ratio < 0.6:
                sections.append(f"Volume ratio={vol_ratio:.1f}x → LOW VOLUME — weak signal (-20%)")
            else:
                sections.append(f"Volume ratio={vol_ratio:.1f}x → Normal volume")

        if adx is not None:
            if adx > 25:
                sections.append(f"ADX={adx:.1f} → TRENDING — continuation patterns more reliable")
            else:
                sections.append(f"ADX={adx:.1f} → RANGING — reversal patterns at extremes more reliable")

        if trend:
            sections.append(f"Short-term trend: {trend}")

    # Add key volume analysis principles
    sections.append("\\n--- KEY VOLUME PRINCIPLES (Coulling) ---")
    for rule in VOLUME_RULES[:5]:
        sections.append(f"  - {rule}")

    # Add key risk rules
    sections.append("\\n--- KEY RISK PRINCIPLES (Elder) ---")
    for rule in RISK_MANAGEMENT_RULES[:3]:
        sections.append(f"  - {rule}")

    return "\\n".join(sections)
''')

    # Write file
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n  Generated: {OUTPUT_PATH}")
    print(f"  Patterns: {len(patterns)}")
    print(f"  Volume rules: {len(vol_rules) + len(vol_pattern) + len(vol_anomaly)}")
    print(f"  Entry/Exit rules: {len(entry_rules) + len(hp_entry) + len(exit_rules) + len(hp_exit)}")
    print(f"  Risk rules: {len(risk_rules) + len(pos_sizing) + len(money_mgmt)}")
    print(f"  Psychology: {len(principles) + len(discipline) + len(mindset)}")
    print(f"  Bulkowski rules: {len(bk_rules)}")


if __name__ == "__main__":
    generate_kb()
