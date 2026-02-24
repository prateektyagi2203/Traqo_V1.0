"""
Book Knowledge Parser
=====================
Reads extracted book JSON files from book_extracts/ and parses them
into structured candlestick knowledge, volume principles, risk rules,
and trading psychology. Outputs a comprehensive knowledge dict that
will be used to rebuild candlestick_knowledge_base.py.

Strategy:
1. For candlestick books (Morris, Nison Beyond, Dummies, Getting Started,
   Pivots): extract pattern-specific formation rules, confirmation criteria,
   win rates, entry/exit/stoploss rules
2. For Bulkowski: extract statistical methodology, failure rates, measure rules
3. For Volume Price Analysis: extract volume confirmation rules
4. For Price Action / High Prob / Trade What You See: extract context rules
5. For Elder / Trading Zone: extract risk management & psychology principles
"""

import os
import json
import re
from collections import defaultdict

EXTRACT_DIR = "book_extracts"
OUTPUT_DIR = "parsed_knowledge"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# PATTERN NAME NORMALIZER
# ============================================================

PATTERN_ALIASES = {
    # Single candle
    r"doji\s*(?:star)?(?!\s*(?:grave|dragon|long))": "doji",
    r"long[\-\s]*legged\s*doji": "long_legged_doji",
    r"gravestone\s*doji": "gravestone_doji",
    r"dragonfly\s*doji": "dragonfly_doji",
    r"hammer(?!\s*(?:inverted))": "hammer",
    r"inverted\s*hammer": "inverted_hammer",
    r"hanging\s*man": "hanging_man",
    r"shooting\s*star": "shooting_star",
    r"marubozu": "marubozu",
    r"bullish\s*marubozu": "bullish_marubozu",
    r"bearish\s*marubozu": "bearish_marubozu",
    r"spinning\s*top": "spinning_top",
    r"belt[\-\s]*hold": "belt_hold",
    r"high[\-\s]*wave": "high_wave",
    # Two candle
    r"bullish\s*engulfing": "bullish_engulfing",
    r"bearish\s*engulfing": "bearish_engulfing",
    r"bullish\s*harami": "bullish_harami",
    r"bearish\s*harami": "bearish_harami",
    r"harami\s*cross": "harami_cross",
    r"piercing\s*(?:line|pattern)": "piercing_line",
    r"dark\s*cloud\s*cover": "dark_cloud_cover",
    r"tweezer\s*top": "tweezer_top",
    r"tweezer\s*bottom": "tweezer_bottom",
    r"bullish\s*kicker": "bullish_kicker",
    r"bearish\s*kicker": "bearish_kicker",
    r"on[\-\s]*neck(?:\s*line)?": "on_neck",
    r"in[\-\s]*neck(?:\s*line)?": "in_neck",
    r"bullish\s*counterattack": "bullish_counterattack",
    r"bearish\s*counterattack": "bearish_counterattack",
    # Three candle
    r"morning\s*star(?!\s*doji)": "morning_star",
    r"morning\s*doji\s*star": "morning_doji_star",
    r"evening\s*star(?!\s*doji)": "evening_star",
    r"evening\s*doji\s*star": "evening_doji_star",
    r"three\s*white\s*soldiers": "three_white_soldiers",
    r"three\s*black\s*crows": "three_black_crows",
    r"three\s*inside\s*up": "three_inside_up",
    r"three\s*inside\s*down": "three_inside_down",
    r"three\s*outside\s*up": "three_outside_up",
    r"three\s*outside\s*down": "three_outside_down",
    r"abandoned\s*baby\s*(?:bullish|bottom)": "abandoned_baby_bullish",
    r"abandoned\s*baby\s*(?:bearish|top)": "abandoned_baby_bearish",
    r"rising\s*three\s*methods": "rising_three_methods",
    r"falling\s*three\s*methods": "falling_three_methods",
    r"advance\s*block": "advance_block",
    r"deliberation": "deliberation",
    r"stalled\s*pattern": "deliberation",
    r"tri[\-\s]*star": "tri_star",
    r"(?:upside|up)\s*(?:gap\s*)?tasuki\s*gap": "upside_tasuki_gap",
    r"(?:downside|down)\s*(?:gap\s*)?tasuki\s*gap": "downside_tasuki_gap",
    r"(?:upside|up)\s*gap\s*two\s*crows": "upside_gap_two_crows",
    r"mat[\-\s]*hold": "mat_hold",
    r"unique\s*three\s*river": "unique_three_river",
    r"three\s*stars\s*in\s*the\s*south": "three_stars_south",
    r"concealing\s*baby\s*swallow": "concealing_baby_swallow",
    r"ladder\s*(?:bottom|top)": "ladder_bottom",
    r"separating\s*lines": "separating_lines",
    r"stick\s*sandwich": "stick_sandwich",
    r"homing\s*pigeon": "homing_pigeon",
    r"matching\s*low": "matching_low",
    r"matching\s*high": "matching_high",
}


def normalize_pattern_name(text):
    """Try to identify a pattern name from surrounding text."""
    text = text.lower().strip()
    for regex, canonical in PATTERN_ALIASES.items():
        if re.search(regex, text, re.IGNORECASE):
            return canonical
    return None


def find_all_patterns_in_text(text):
    """Find all pattern names mentioned in a block of text."""
    found = set()
    for regex, canonical in PATTERN_ALIASES.items():
        if re.search(regex, text, re.IGNORECASE):
            found.add(canonical)
    return found


# ============================================================
# TEXT EXTRACTION HELPERS
# ============================================================

def extract_percentages(text):
    """Find all percentage values in text."""
    return re.findall(r'(\d+(?:\.\d+)?)\s*%', text)


def extract_sentences_around_pattern(text, pattern_name, context_sentences=3):
    """Get sentences surrounding a pattern mention."""
    # Find the pattern alias regex
    pattern_regex = None
    for regex, canonical in PATTERN_ALIASES.items():
        if canonical == pattern_name:
            pattern_regex = regex
            break
    if not pattern_regex:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text)
    results = []
    for i, sent in enumerate(sentences):
        if re.search(pattern_regex, sent, re.IGNORECASE):
            start = max(0, i - context_sentences)
            end = min(len(sentences), i + context_sentences + 1)
            context = " ".join(sentences[start:end])
            results.append(context)
    return results


# ============================================================
# PARSERS FOR EACH BOOK TYPE
# ============================================================

def parse_morris_explained(data):
    """
    Parse Morris 'Candlestick Charting Explained' — the most comprehensive source.
    Morris provides: pattern descriptions, formation rules, confirmation,
    and importantly, statistical reliability data.
    """
    print("  Parsing Morris 'Candlestick Charting Explained'...")
    knowledge = defaultdict(lambda: {
        "descriptions": [], "rules": [], "confirmation": [],
        "statistics": [], "psychology": [], "entry_exit": [],
        "volume_notes": [], "source": "Morris"
    })

    highly_relevant = [p for p in data["extracted_pages"] if p["is_highly_relevant"]]

    for page in highly_relevant:
        text = page["text"]
        patterns_found = find_all_patterns_in_text(text)

        for pat in patterns_found:
            # Extract sentences around each pattern
            contexts = extract_sentences_around_pattern(text, pat, 4)
            for ctx in contexts:
                ctx_lower = ctx.lower()

                # Classify the context
                if any(w in ctx_lower for w in ["form", "consist", "compris", "made up of",
                                                  "open", "close", "body", "shadow", "wick",
                                                  "real body", "upper shadow", "lower shadow"]):
                    knowledge[pat]["rules"].append(ctx)

                if any(w in ctx_lower for w in ["confirm", "verification", "validate",
                                                  "next day", "next candle", "wait for",
                                                  "follow-through"]):
                    knowledge[pat]["confirmation"].append(ctx)

                if any(w in ctx_lower for w in ["percent", "success", "failure", "reliable",
                                                  "probability", "frequency", "win rate",
                                                  "historically", "statistic"]):
                    knowledge[pat]["statistics"].append(ctx)

                if any(w in ctx_lower for w in ["psychology", "sentiment", "emotion",
                                                  "fear", "greed", "bulls", "bears",
                                                  "buyer", "seller", "control",
                                                  "momentum shift", "indecision"]):
                    knowledge[pat]["psychology"].append(ctx)

                if any(w in ctx_lower for w in ["entry", "exit", "stop", "target",
                                                  "profit", "risk", "trade", "position",
                                                  "buy", "sell", "long", "short"]):
                    knowledge[pat]["entry_exit"].append(ctx)

                if any(w in ctx_lower for w in ["volume", "turnover", "activity",
                                                  "heavy", "light", "increasing",
                                                  "declining"]):
                    knowledge[pat]["volume_notes"].append(ctx)

                # General description
                knowledge[pat]["descriptions"].append(ctx)

    print(f"    Extracted knowledge for {len(knowledge)} patterns")
    return dict(knowledge)


def parse_nison_beyond(data):
    """Parse Nison 'Beyond Candlesticks' — advanced patterns & combinations."""
    print("  Parsing Nison 'Beyond Candlesticks'...")
    knowledge = defaultdict(lambda: {
        "descriptions": [], "rules": [], "confirmation": [],
        "combinations": [], "context_rules": [], "source": "Nison"
    })

    highly_relevant = [p for p in data["extracted_pages"] if p["is_highly_relevant"]]

    for page in highly_relevant:
        text = page["text"]
        patterns_found = find_all_patterns_in_text(text)

        for pat in patterns_found:
            contexts = extract_sentences_around_pattern(text, pat, 4)
            for ctx in contexts:
                ctx_lower = ctx.lower()

                if any(w in ctx_lower for w in ["form", "consist", "body", "shadow",
                                                  "open", "close"]):
                    knowledge[pat]["rules"].append(ctx)

                if any(w in ctx_lower for w in ["confirm", "wait", "follow"]):
                    knowledge[pat]["confirmation"].append(ctx)

                if any(w in ctx_lower for w in ["combin", "together", "along with",
                                                  "followed by", "preceded by"]):
                    knowledge[pat]["combinations"].append(ctx)

                if any(w in ctx_lower for w in ["context", "trend", "support", "resistance",
                                                  "level", "area"]):
                    knowledge[pat]["context_rules"].append(ctx)

                knowledge[pat]["descriptions"].append(ctx)

    print(f"    Extracted knowledge for {len(knowledge)} patterns")
    return dict(knowledge)


def parse_bulkowski(data):
    """
    Parse Bulkowski 'Encyclopedia of Chart Patterns' — statistical gold.
    Bulkowski provides: failure rates, performance rank, measure rules.
    """
    print("  Parsing Bulkowski 'Encyclopedia of Chart Patterns'...")
    knowledge = {
        "pattern_stats": {},
        "general_rules": [],
        "failure_analysis": [],
        "measure_rules": [],
        "source": "Bulkowski"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        text_lower = text.lower()

        # Look for statistical data
        pcts = extract_percentages(text)

        # Failure rate patterns
        failure_matches = re.findall(
            r'failure\s*rate[^.]*?(\d+(?:\.\d+)?)\s*%', text, re.IGNORECASE
        )
        if failure_matches:
            knowledge["failure_analysis"].append({
                "page": page["page"],
                "rates": failure_matches,
                "context": text[:500]
            })

        # Performance rank
        rank_matches = re.findall(
            r'(?:performance|rank)[^.]*?(\d+)\s*(?:out\s*of|/)\s*(\d+)',
            text, re.IGNORECASE
        )
        if rank_matches:
            patterns_found = find_all_patterns_in_text(text)
            for pat in patterns_found:
                if pat not in knowledge["pattern_stats"]:
                    knowledge["pattern_stats"][pat] = {"ranks": [], "failure_rates": []}
                knowledge["pattern_stats"][pat]["ranks"].extend(rank_matches)

        # Measure rule (price target calculation)
        if "measure" in text_lower and ("rule" in text_lower or "target" in text_lower):
            knowledge["measure_rules"].append({
                "page": page["page"],
                "text": text[:600]
            })

        # General trading rules
        if any(w in text_lower for w in ["rule of thumb", "guideline", "best practice",
                                           "key finding", "important"]):
            for sent in re.split(r'(?<=[.!?])\s+', text):
                if any(w in sent.lower() for w in ["rule", "guideline", "always", "never",
                                                     "should", "must", "important"]):
                    if len(sent) > 30 and len(sent) < 500:
                        knowledge["general_rules"].append(sent.strip())

    print(f"    Pattern stats for {len(knowledge['pattern_stats'])} patterns, "
          f"{len(knowledge['general_rules'])} rules, "
          f"{len(knowledge['failure_analysis'])} failure analyses")
    return knowledge


def parse_candlestick_pivots(data):
    """Parse 'Candlestick and Pivot Point Trading Triggers' — entry/exit/stoploss."""
    print("  Parsing 'Candlestick and Pivot Point Trading Triggers'...")
    knowledge = {
        "entry_rules": [],
        "exit_rules": [],
        "stoploss_rules": [],
        "pivot_integration": [],
        "pattern_triggers": defaultdict(list),
        "source": "Person"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        text_lower = text.lower()
        patterns_found = find_all_patterns_in_text(text)

        sentences = re.split(r'(?<=[.!?])\s+', text)
        for sent in sentences:
            sl = sent.lower()

            if any(w in sl for w in ["entry", "enter", "trigger", "buy signal",
                                       "sell signal", "initiate"]):
                knowledge["entry_rules"].append(sent.strip())
                for pat in patterns_found:
                    if re.search(
                        [r for r, c in PATTERN_ALIASES.items() if c == pat][0] if
                        any(c == pat for r, c in PATTERN_ALIASES.items()) else pat,
                        sent, re.IGNORECASE
                    ):
                        knowledge["pattern_triggers"][pat].append(
                            {"type": "entry", "rule": sent.strip()})

            if any(w in sl for w in ["exit", "take profit", "target", "close position",
                                       "price objective"]):
                knowledge["exit_rules"].append(sent.strip())

            if any(w in sl for w in ["stop", "stoploss", "stop-loss", "protective",
                                       "risk point", "stop level"]):
                knowledge["stoploss_rules"].append(sent.strip())

            if any(w in sl for w in ["pivot", "support", "resistance", "level",
                                       "price level"]):
                knowledge["pivot_integration"].append(sent.strip())

    knowledge["pattern_triggers"] = dict(knowledge["pattern_triggers"])
    print(f"    Entry rules: {len(knowledge['entry_rules'])}, "
          f"Exit: {len(knowledge['exit_rules'])}, "
          f"Stoploss: {len(knowledge['stoploss_rules'])}, "
          f"Pivot: {len(knowledge['pivot_integration'])}")
    return knowledge


def parse_volume_price(data):
    """Parse 'Complete Guide to Volume Price Analysis' — volume confirmation."""
    print("  Parsing 'Volume Price Analysis'...")
    knowledge = {
        "volume_rules": [],
        "volume_pattern_rules": [],
        "anomaly_rules": [],
        "source": "Coulling"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sent in sentences:
            sl = sent.lower()
            if len(sent) < 20 or len(sent) > 500:
                continue

            if any(w in sl for w in ["volume", "turnover", "activity"]):
                if any(w in sl for w in ["confirm", "validate", "support", "agree",
                                           "accompany", "should be", "must be",
                                           "expect", "look for"]):
                    knowledge["volume_rules"].append(sent.strip())

                if any(w in sl for w in ["candle", "bar", "pattern", "breakout",
                                           "reversal", "continuation"]):
                    knowledge["volume_pattern_rules"].append(sent.strip())

                if any(w in sl for w in ["anomal", "unusual", "diverge", "contradict",
                                           "warning", "suspicious", "disagree",
                                           "without volume"]):
                    knowledge["anomaly_rules"].append(sent.strip())

    # Deduplicate
    for key in ["volume_rules", "volume_pattern_rules", "anomaly_rules"]:
        knowledge[key] = list(set(knowledge[key]))

    print(f"    Volume rules: {len(knowledge['volume_rules'])}, "
          f"Pattern-volume: {len(knowledge['volume_pattern_rules'])}, "
          f"Anomalies: {len(knowledge['anomaly_rules'])}")
    return knowledge


def parse_price_action(data):
    """Parse 'Understanding Price Action — 5-min timeframe'."""
    print("  Parsing 'Understanding Price Action (5-min)'...")
    knowledge = {
        "intraday_rules": [],
        "price_action_principles": [],
        "session_rules": [],
        "source": "Volman"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sent in sentences:
            sl = sent.lower()
            if len(sent) < 20 or len(sent) > 500:
                continue

            if any(w in sl for w in ["5-minute", "5 minute", "intraday", "scalp",
                                       "short-term", "day trad"]):
                knowledge["intraday_rules"].append(sent.strip())

            if any(w in sl for w in ["price action", "naked chart", "no indicator",
                                       "bar by bar", "candle by candle"]):
                knowledge["price_action_principles"].append(sent.strip())

            if any(w in sl for w in ["session", "market open", "market close",
                                       "first hour", "last hour", "lunch",
                                       "opening range"]):
                knowledge["session_rules"].append(sent.strip())

    for key in knowledge:
        if isinstance(knowledge[key], list):
            knowledge[key] = list(set(knowledge[key]))

    print(f"    Intraday rules: {len(knowledge['intraday_rules'])}, "
          f"Price action: {len(knowledge['price_action_principles'])}, "
          f"Session: {len(knowledge['session_rules'])}")
    return knowledge


def parse_high_prob_strategies(data):
    """Parse 'High Probability Trading Strategies'."""
    print("  Parsing 'High Probability Trading Strategies'...")
    knowledge = {
        "entry_tactics": [],
        "exit_tactics": [],
        "risk_reward_rules": [],
        "fibonacci_rules": [],
        "momentum_rules": [],
        "source": "Miner"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sent in sentences:
            sl = sent.lower()
            if len(sent) < 20 or len(sent) > 500:
                continue

            if any(w in sl for w in ["entry", "enter", "trigger", "setup",
                                       "buy signal", "sell signal"]):
                knowledge["entry_tactics"].append(sent.strip())

            if any(w in sl for w in ["exit", "target", "take profit",
                                       "profit target", "trailing"]):
                knowledge["exit_tactics"].append(sent.strip())

            if any(w in sl for w in ["risk-reward", "risk reward", "r:r",
                                       "risk/reward", "reward-to-risk"]):
                knowledge["risk_reward_rules"].append(sent.strip())

            if any(w in sl for w in ["fibonacci", "fib ", "retrace", "extension",
                                       "38.2", "50", "61.8", "78.6"]):
                knowledge["fibonacci_rules"].append(sent.strip())

            if any(w in sl for w in ["momentum", "overbought", "oversold",
                                       "divergence", "rsi", "stochastic"]):
                knowledge["momentum_rules"].append(sent.strip())

    for key in knowledge:
        if isinstance(knowledge[key], list):
            knowledge[key] = list(set(knowledge[key]))

    print(f"    Entry: {len(knowledge['entry_tactics'])}, "
          f"Exit: {len(knowledge['exit_tactics'])}, "
          f"R:R: {len(knowledge['risk_reward_rules'])}, "
          f"Fib: {len(knowledge['fibonacci_rules'])}")
    return knowledge


def parse_trade_what_you_see(data):
    """Parse 'Trade What You See — Pattern Recognition'."""
    print("  Parsing 'Trade What You See'...")
    knowledge = {
        "pattern_recognition_rules": [],
        "confirmation_rules": [],
        "failure_rules": [],
        "source": "Pesavento"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sent in sentences:
            sl = sent.lower()
            if len(sent) < 20 or len(sent) > 500:
                continue

            if any(w in sl for w in ["pattern", "recognize", "identify", "form",
                                       "setup", "formation"]):
                knowledge["pattern_recognition_rules"].append(sent.strip())

            if any(w in sl for w in ["confirm", "validate", "verify",
                                       "follow-through", "next bar"]):
                knowledge["confirmation_rules"].append(sent.strip())

            if any(w in sl for w in ["fail", "false", "trap", "whipsaw",
                                       "breakdown", "fake"]):
                knowledge["failure_rules"].append(sent.strip())

    for key in knowledge:
        if isinstance(knowledge[key], list):
            knowledge[key] = list(set(knowledge[key]))

    print(f"    Pattern recognition: {len(knowledge['pattern_recognition_rules'])}, "
          f"Confirmation: {len(knowledge['confirmation_rules'])}, "
          f"Failure: {len(knowledge['failure_rules'])}")
    return knowledge


def parse_candlestick_basics(data, source_name):
    """Parse basic candlestick books (Dummies, Getting Started)."""
    print(f"  Parsing '{source_name}'...")
    knowledge = defaultdict(lambda: {
        "descriptions": [], "rules": [], "examples": [],
        "trading_tips": [], "source": source_name
    })

    highly_relevant = [p for p in data["extracted_pages"] if p["is_highly_relevant"]]

    for page in highly_relevant:
        text = page["text"]
        patterns_found = find_all_patterns_in_text(text)

        for pat in patterns_found:
            contexts = extract_sentences_around_pattern(text, pat, 3)
            for ctx in contexts:
                ctx_lower = ctx.lower()

                if any(w in ctx_lower for w in ["form", "body", "shadow", "consist",
                                                  "looks like", "appears"]):
                    knowledge[pat]["rules"].append(ctx)

                if any(w in ctx_lower for w in ["example", "instance", "figure",
                                                  "chart shows", "see "]):
                    knowledge[pat]["examples"].append(ctx)

                if any(w in ctx_lower for w in ["trade", "entry", "exit", "stop",
                                                  "tip", "remember", "important",
                                                  "key", "caution"]):
                    knowledge[pat]["trading_tips"].append(ctx)

                knowledge[pat]["descriptions"].append(ctx)

    print(f"    Patterns found: {len(knowledge)}")
    return dict(knowledge)


def parse_trading_psychology(data):
    """Parse 'Trading in the Zone'."""
    print("  Parsing 'Trading in the Zone'...")
    knowledge = {
        "principles": [],
        "discipline_rules": [],
        "mindset_rules": [],
        "source": "Douglas"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sent in sentences:
            sl = sent.lower()
            if len(sent) < 30 or len(sent) > 400:
                continue

            if any(w in sl for w in ["principle", "truth", "fundamental",
                                       "believe", "accept", "understand"]):
                knowledge["principles"].append(sent.strip())

            if any(w in sl for w in ["discipline", "rule", "consistent",
                                       "follow the plan", "system"]):
                knowledge["discipline_rules"].append(sent.strip())

            if any(w in sl for w in ["mindset", "attitude", "emotion",
                                       "fear", "greed", "confidence",
                                       "probabili"]):
                knowledge["mindset_rules"].append(sent.strip())

    for key in knowledge:
        if isinstance(knowledge[key], list):
            knowledge[key] = list(set(knowledge[key]))[:50]  # Cap

    print(f"    Principles: {len(knowledge['principles'])}, "
          f"Discipline: {len(knowledge['discipline_rules'])}, "
          f"Mindset: {len(knowledge['mindset_rules'])}")
    return knowledge


def parse_elder_trading(data):
    """Parse Elder 'New Trading for a Living' — risk management."""
    print("  Parsing Elder 'New Trading for a Living'...")
    knowledge = {
        "risk_rules": [],
        "position_sizing": [],
        "money_management": [],
        "indicator_rules": [],
        "source": "Elder"
    }

    for page in data["extracted_pages"]:
        text = page["text"]
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sent in sentences:
            sl = sent.lower()
            if len(sent) < 20 or len(sent) > 500:
                continue

            if any(w in sl for w in ["risk", "2 percent", "2%", "loss limit",
                                       "maximum loss", "drawdown"]):
                knowledge["risk_rules"].append(sent.strip())

            if any(w in sl for w in ["position size", "lot size", "how many shares",
                                       "units", "contracts"]):
                knowledge["position_sizing"].append(sent.strip())

            if any(w in sl for w in ["money management", "capital", "account",
                                       "preserve", "survive"]):
                knowledge["money_management"].append(sent.strip())

            if any(w in sl for w in ["ema", "macd", "rsi", "force index",
                                       "elder-ray", "impulse"]):
                knowledge["indicator_rules"].append(sent.strip())

    for key in knowledge:
        if isinstance(knowledge[key], list):
            knowledge[key] = list(set(knowledge[key]))

    print(f"    Risk: {len(knowledge['risk_rules'])}, "
          f"Position sizing: {len(knowledge['position_sizing'])}, "
          f"Money mgmt: {len(knowledge['money_management'])}, "
          f"Indicators: {len(knowledge['indicator_rules'])}")
    return knowledge


# ============================================================
# KNOWLEDGE CONSOLIDATOR
# ============================================================

def consolidate_pattern_knowledge(all_parsed):
    """Merge all pattern knowledge from multiple books into one dict per pattern."""
    print("\n  Consolidating pattern knowledge across all books...")

    consolidated = defaultdict(lambda: {
        "descriptions": [],
        "formation_rules": [],
        "confirmation_criteria": [],
        "statistics": [],
        "psychology": [],
        "entry_exit_rules": [],
        "volume_requirements": [],
        "context_rules": [],
        "trading_tips": [],
        "sources": set(),
    })

    # Morris patterns
    if "morris" in all_parsed:
        for pat, info in all_parsed["morris"].items():
            consolidated[pat]["formation_rules"].extend(info.get("rules", []))
            consolidated[pat]["confirmation_criteria"].extend(info.get("confirmation", []))
            consolidated[pat]["statistics"].extend(info.get("statistics", []))
            consolidated[pat]["psychology"].extend(info.get("psychology", []))
            consolidated[pat]["entry_exit_rules"].extend(info.get("entry_exit", []))
            consolidated[pat]["volume_requirements"].extend(info.get("volume_notes", []))
            consolidated[pat]["descriptions"].extend(info.get("descriptions", []))
            consolidated[pat]["sources"].add("Morris")

    # Nison Beyond
    if "nison_beyond" in all_parsed:
        for pat, info in all_parsed["nison_beyond"].items():
            consolidated[pat]["formation_rules"].extend(info.get("rules", []))
            consolidated[pat]["confirmation_criteria"].extend(info.get("confirmation", []))
            consolidated[pat]["context_rules"].extend(info.get("context_rules", []))
            consolidated[pat]["sources"].add("Nison")

    # Dummies
    if "dummies" in all_parsed:
        for pat, info in all_parsed["dummies"].items():
            consolidated[pat]["formation_rules"].extend(info.get("rules", []))
            consolidated[pat]["trading_tips"].extend(info.get("trading_tips", []))
            consolidated[pat]["descriptions"].extend(info.get("descriptions", []))
            consolidated[pat]["sources"].add("Dummies")

    # Getting Started
    if "getting_started" in all_parsed:
        for pat, info in all_parsed["getting_started"].items():
            consolidated[pat]["formation_rules"].extend(info.get("rules", []))
            consolidated[pat]["trading_tips"].extend(info.get("trading_tips", []))
            consolidated[pat]["descriptions"].extend(info.get("descriptions", []))
            consolidated[pat]["sources"].add("Getting Started")

    # Pivot triggers
    if "pivots" in all_parsed:
        triggers = all_parsed["pivots"].get("pattern_triggers", {})
        for pat, rules in triggers.items():
            for rule in rules:
                consolidated[pat]["entry_exit_rules"].append(rule.get("rule", ""))
            consolidated[pat]["sources"].add("Person/Pivots")

    # Deduplicate and cap each field
    for pat in consolidated:
        for field in consolidated[pat]:
            if isinstance(consolidated[pat][field], list):
                # Deduplicate by taking unique strings
                seen = set()
                unique = []
                for item in consolidated[pat][field]:
                    key = item[:100].lower()
                    if key not in seen:
                        seen.add(key)
                        unique.append(item)
                consolidated[pat][field] = unique[:30]  # Cap at 30 per field
            elif isinstance(consolidated[pat][field], set):
                consolidated[pat][field] = list(consolidated[pat][field])

    print(f"    Consolidated {len(consolidated)} unique patterns")
    return dict(consolidated)


def main():
    print("=" * 80)
    print("BOOK KNOWLEDGE PARSER — Processing ALL Extracted Books")
    print("=" * 80)

    all_parsed = {}

    # Load each extract and parse
    parsers = {
        "morris_explained": ("morris", parse_morris_explained),
        "nison_beyond": ("nison_beyond", parse_nison_beyond),
        "bulkowski_encyclopedia": ("bulkowski", parse_bulkowski),
        "candlestick_pivots": ("pivots", parse_candlestick_pivots),
        "volume_price": ("volume", parse_volume_price),
        "price_action_5min": ("price_action", parse_price_action),
        "high_prob_strategies": ("high_prob", parse_high_prob_strategies),
        "trade_what_you_see": ("pattern_recog", parse_trade_what_you_see),
        "candlestick_dummies": ("dummies", lambda d: parse_candlestick_basics(d, "Dummies")),
        "candlestick_getting_started": ("getting_started", lambda d: parse_candlestick_basics(d, "Getting Started")),
        "trading_zone": ("psychology", parse_trading_psychology),
        "elder_trading": ("elder", parse_elder_trading),
    }

    for filename, (key, parser) in parsers.items():
        filepath = os.path.join(EXTRACT_DIR, f"{filename}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data["relevant_pages"] > 0 or data["total_pages"] > 0:
                all_parsed[key] = parser(data)
            else:
                print(f"  SKIPPING {filename} — no relevant pages")
        else:
            print(f"  SKIPPING {filename} — file not found")

    # Consolidate pattern knowledge
    consolidated_patterns = consolidate_pattern_knowledge(all_parsed)

    # Save everything
    output = {
        "consolidated_patterns": consolidated_patterns,
        "volume_knowledge": all_parsed.get("volume", {}),
        "price_action_knowledge": all_parsed.get("price_action", {}),
        "entry_exit_knowledge": {
            "pivots": all_parsed.get("pivots", {}),
            "high_prob": all_parsed.get("high_prob", {}),
        },
        "pattern_recognition": all_parsed.get("pattern_recog", {}),
        "risk_management": all_parsed.get("elder", {}),
        "trading_psychology": all_parsed.get("psychology", {}),
        "bulkowski_stats": all_parsed.get("bulkowski", {}),
    }

    outpath = os.path.join(OUTPUT_DIR, "all_book_knowledge.json")
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=list)
    print(f"\n  ALL parsed knowledge saved: {outpath}")

    # Print summary
    print("\n" + "=" * 80)
    print("PARSING SUMMARY")
    print("=" * 80)
    print(f"  Consolidated patterns: {len(consolidated_patterns)}")
    for pat in sorted(consolidated_patterns.keys()):
        info = consolidated_patterns[pat]
        n_rules = len(info.get("formation_rules", []))
        n_conf = len(info.get("confirmation_criteria", []))
        n_stats = len(info.get("statistics", []))
        n_ee = len(info.get("entry_exit_rules", []))
        sources = info.get("sources", [])
        print(f"    {pat}: rules={n_rules} confirm={n_conf} "
              f"stats={n_stats} entry/exit={n_ee} sources={sources}")

    # Section summaries
    vol = all_parsed.get("volume", {})
    print(f"\n  Volume rules: {len(vol.get('volume_rules', []))}")
    print(f"  Volume-pattern rules: {len(vol.get('volume_pattern_rules', []))}")

    pa = all_parsed.get("price_action", {})
    print(f"  Intraday rules: {len(pa.get('intraday_rules', []))}")
    print(f"  Session rules: {len(pa.get('session_rules', []))}")

    psy = all_parsed.get("psychology", {})
    print(f"  Psychology principles: {len(psy.get('principles', []))}")

    elder = all_parsed.get("elder", {})
    print(f"  Risk management rules: {len(elder.get('risk_rules', []))}")

    print(f"\n  Output: {outpath}")


if __name__ == "__main__":
    main()
