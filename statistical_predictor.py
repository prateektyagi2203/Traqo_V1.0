"""
Statistical Predictor — Metadata-based Pattern Matching
=========================================================
Replaces embedding-based RAG retrieval with structured statistical lookups.

Key design fixes vs. the old RAG approach:
  1. Matches by pattern NAME (exact), not text similarity
  2. Base-rate correction: subtracts the DB's inherent bullish bias
  3. Caps self-instrument matches (max 5/20) for cross-instrument generalization
  4. Excludes VIX/inverse instruments (they move inversely to stocks)
  5. Tiered filtering: exact match → relaxed match → broader match
  6. Calibrated confidence based on sample adequacy + directional edge

Usage:
    from statistical_predictor import StatisticalPredictor
    sp = StatisticalPredictor()
    pred = sp.predict("bullish_engulfing", timeframe="daily",
                      trend_short="bearish", rsi_zone="oversold")
"""

import json
import os
import numpy as np
from collections import defaultdict
from typing import Optional

# Import centralized production config
from trading_config import (
    EXCLUDED_INSTRUMENTS, EXCLUDED_PATTERNS, WHITELISTED_PATTERNS,
    STRUCTURAL_SL_PATTERNS, STRUCTURAL_SL_MULTIPLIER, STANDARD_SL_MULTIPLIER,
    MAX_PER_INSTRUMENT, MIN_MATCHES, TOP_K, PRIMARY_HORIZON,
    ALLOWED_TIMEFRAMES, ALLOWED_INSTRUMENTS, ALLOWED_TIERS,
    SL_FLOOR_PCT, SL_CAP_PCT, INSTRUMENT_SECTORS,
    is_tradeable_instrument, is_tradeable_timeframe, is_tradeable_pattern,
    is_tradeable_tier,
)

# Max matches from any single sector (prevents sector concentration)
MAX_PER_SECTOR = 15

RAG_DOCS_PATH = "rag_documents_v2/all_pattern_documents.json"
FEEDBACK_LEARNING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback", "learned_rules.json")


class StatisticalPredictor:
    """In-memory statistical predictor using structured metadata lookups."""

    def __init__(self, docs_path=RAG_DOCS_PATH):
        print("  Loading statistical predictor...", flush=True)
        self._load_feedback()

        with open(docs_path, "r") as f:
            raw_docs = json.load(f)

        # Filter docs: exclude VIX, non-allowed instruments, non-allowed timeframes,
        # and docs without outcomes
        self.docs = []
        n_tf_filtered = 0
        n_inst_filtered = 0
        for d in raw_docs:
            if d.get("instrument") in EXCLUDED_INSTRUMENTS:
                continue
            if not is_tradeable_instrument(d.get("instrument", "")):
                n_inst_filtered += 1
                continue
            if not is_tradeable_timeframe(d.get("timeframe", "")):
                n_tf_filtered += 1
                continue
            if d.get(f"fwd_{PRIMARY_HORIZON}_return_pct") is None:
                continue
            if d.get(f"fwd_{PRIMARY_HORIZON}_direction") is None:
                continue
            self.docs.append(d)

        # Pre-compute base rates (the inherent bullish bias in the dataset)
        dir_counts = defaultdict(int)
        for d in self.docs:
            dir_counts[d[f"fwd_{PRIMARY_HORIZON}_direction"]] += 1
        total = sum(dir_counts.values())
        self.base_rates = {k: v / total for k, v in dir_counts.items()}

        # Build indexes for fast lookup
        # Pattern index: pattern_name -> [doc indices]
        self.pattern_index = defaultdict(list)
        for i, d in enumerate(self.docs):
            for p in d.get("patterns", "").split(","):
                p = p.strip()
                if p and p != "none":
                    self.pattern_index[p].append(i)

        # Timeframe index
        self.tf_index = defaultdict(set)
        for i, d in enumerate(self.docs):
            self.tf_index[d.get("timeframe", "unknown")].add(i)

        # Trend index
        self.trend_index = defaultdict(set)
        for i, d in enumerate(self.docs):
            self.trend_index[d.get("trend_short", "unknown")].add(i)

        # RSI zone index
        self.rsi_index = defaultdict(set)
        for i, d in enumerate(self.docs):
            self.rsi_index[d.get("rsi_zone", "unknown")].add(i)

        # VWAP position index
        self.vwap_index = defaultdict(set)
        for i, d in enumerate(self.docs):
            self.vwap_index[str(d.get("price_vs_vwap", "unknown"))].add(i)

        # Market regime index (first component only for broader matching)
        self.regime_index = defaultdict(set)
        for i, d in enumerate(self.docs):
            regime = d.get("market_regime", "unknown")
            self.regime_index[regime].add(i)
            # Also index by first component (e.g., "trending" from "trending|bullish_aligned|normal_volatility")
            first = regime.split("|")[0] if "|" in regime else regime
            self.regime_index[f"_broad_{first}"].add(i)

        # Sector index: sector_name -> set of doc indices
        self.sector_index = defaultdict(set)
        for i, d in enumerate(self.docs):
            sector = d.get("sector") or INSTRUMENT_SECTORS.get(d.get("instrument", ""), "unknown")
            self.sector_index[sector].add(i)

        print(f"  Loaded {len(self.docs)} docs (excluded {len(raw_docs) - len(self.docs)} total)")
        print(f"  Sectors indexed: {len(self.sector_index)} unique sectors")
        print(f"    - Timeframe filtered: {n_tf_filtered} (allowed: {ALLOWED_TIMEFRAMES})")
        print(f"    - Instrument filtered: {n_inst_filtered} (allowed: {len(ALLOWED_INSTRUMENTS)} instruments)")
        print(f"  Base rates: { {k: f'{v:.1%}' for k, v in self.base_rates.items()} }")
        print(f"  Indexed {len(self.pattern_index)} unique patterns")

    # ----------------------------------------------------------
    # FEEDBACK LOOP — Paper Trading Learned Rules
    # ----------------------------------------------------------
    def _load_feedback(self):
        """Load pattern adjustments and rules from paper trading feedback."""
        self.feedback_pattern_adj = {}   # pattern -> {actual_win_rate, decay_weighted_win_rate, ...}
        self.feedback_rules = []          # [{rule, confidence, type, context}, ...]
        self.feedback_regime_adj = {}     # pattern__trend -> {win_rate, decay_weighted_win_rate, ...}
        self.feedback_horizon_adj = {}    # pattern__horizon -> {win_rate, decay_weighted_win_rate, ...}
        self.feedback_triple_adj = {}     # pattern__trend__horizon -> {...}
        self.feedback_filter_penalties = {}  # pattern -> {action, reason, ...}
        self.feedback_filter_boosts = {}    # pattern -> {action, reason, ...}
        self.feedback_horizon_filter_penalties = {}  # pattern__horizon -> {action, ...}
        self.feedback_horizon_filter_boosts = {}     # pattern__horizon -> {action, ...}
        self.feedback_sector_adj = {}      # pattern__sector -> {win_rate, ...}
        self.feedback_sector_filter_penalties = {}  # pattern__sector -> {action, ...}
        self.feedback_sector_filter_boosts = {}     # pattern__sector -> {action, ...}
        self.feedback_loaded_at = None

        if not os.path.exists(FEEDBACK_LEARNING_FILE):
            return
        try:
            with open(FEEDBACK_LEARNING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.feedback_pattern_adj = data.get("pattern_adjustments", {})
            self.feedback_rules = data.get("rules", [])
            self.feedback_regime_adj = data.get("regime_adjustments", {})
            self.feedback_horizon_adj = data.get("horizon_adjustments", {})
            self.feedback_triple_adj = data.get("triple_adjustments", {})
            self.feedback_filter_penalties = data.get("filter_penalties", {})
            self.feedback_filter_boosts = data.get("filter_boosts", {})
            self.feedback_horizon_filter_penalties = data.get("horizon_filter_penalties", {})
            self.feedback_horizon_filter_boosts = data.get("horizon_filter_boosts", {})
            self.feedback_sector_adj = data.get("sector_adjustments", {})
            self.feedback_sector_filter_penalties = data.get("sector_filter_penalties", {})
            self.feedback_sector_filter_boosts = data.get("sector_filter_boosts", {})
            self.feedback_loaded_at = data.get("updated_at")
            n_adj = len(self.feedback_pattern_adj)
            n_rules = len(self.feedback_rules)
            n_regime = len(self.feedback_regime_adj)
            n_horizon = len(self.feedback_horizon_adj)
            n_triple = len(self.feedback_triple_adj)
            n_sector = len(self.feedback_sector_adj)
            if n_adj or n_rules or n_regime:
                print(f"  Feedback loop: {n_adj} pattern adj, {n_regime} regime, "
                      f"{n_horizon} horizon, {n_triple} triple, {n_sector} sector segments, "
                      f"{n_rules} rules (updated {self.feedback_loaded_at or 'unknown'})")
        except Exception as e:
            print(f"  Feedback loop: failed to load — {e}")

    def reload_feedback(self):
        """Re-read feedback file (call after new outcomes are fed)."""
        self._load_feedback()

    def get_horizon_feedback(self, patterns, trend_short, horizon_label):
        """Look up horizon-specific feedback WR for given patterns.

        Cascade: triple → horizon → regime → pattern (most specific first).
        Returns (adjusted_wr, source_tag) or (None, None) if no horizon-specific
        feedback is available (caller should use the default prediction WR).
        """
        if not horizon_label:
            return None, None

        for pat in (patterns if isinstance(patterns, list) else [patterns]):
            # 1. Triple key: pattern__trend__horizon
            if trend_short:
                tkey = f"{pat}__{trend_short}__{horizon_label}"
                ta = self.feedback_triple_adj.get(tkey)
                if ta and ta.get("total_trades", 0) >= 3:
                    wr = ta.get("decay_weighted_win_rate", ta.get("win_rate"))
                    return wr, f"triple:{tkey}"

            # 2. Horizon key: pattern__horizon
            hkey = f"{pat}__{horizon_label}"
            ha = self.feedback_horizon_adj.get(hkey)
            if ha and ha.get("total_trades", 0) >= 2:
                wr = ha.get("decay_weighted_win_rate", ha.get("win_rate"))
                return wr, f"horizon:{hkey}"

        return None, None

    def _apply_feedback(self, result, pattern, trend_short=None, horizon_label=None, sector=None):
        """Blend paper-trading actual performance into raw statistical prediction.

        Cascade lookup (most specific to least specific):
          1. pattern__trend__horizon  (triple key)
          2. pattern__horizon          (horizon-segmented)
          3. pattern__sector           (sector-segmented)
          4. pattern__trend            (regime-segmented)
          5. pattern                   (base pattern)

        - Confidence: scaled boost/penalize based on learned rules (3-5x stronger than v1).
        - A/B tracking: stores raw_win_rate alongside blended for later analysis.
        - Returns the modified result dict in-place.
        """
        # --- A/B tracking: always record the raw (pre-feedback) values (#8) ---
        result["raw_win_rate"] = result.get("win_rate", 50)
        result["raw_confidence_score"] = result.get("confidence_score", 0.5)

        # --- 5-tier cascade lookup for most specific feedback ---
        triple_key = f"{pattern}__{trend_short}__{horizon_label}" if (trend_short and horizon_label) else None
        horizon_key = f"{pattern}__{horizon_label}" if horizon_label else None
        sector_key = f"{pattern}__{sector}" if sector else None
        regime_key = f"{pattern}__{trend_short}" if trend_short else None

        triple_adj = self.feedback_triple_adj.get(triple_key) if triple_key else None
        horizon_adj = self.feedback_horizon_adj.get(horizon_key) if horizon_key else None
        sector_adj = self.feedback_sector_adj.get(sector_key) if sector_key else None
        regime_adj = self.feedback_regime_adj.get(regime_key) if regime_key else None
        adj = self.feedback_pattern_adj.get(pattern)

        # Pick the best available feedback source (most specific first)
        paper_wr = None
        paper_n = 0
        feedback_source = None

        if triple_adj and triple_adj.get("total_trades", 0) >= 3:
            paper_wr = triple_adj.get("decay_weighted_win_rate", triple_adj.get("win_rate", 50))
            paper_n = triple_adj["total_trades"]
            feedback_source = f"triple:{triple_key}"
        elif horizon_adj and horizon_adj.get("total_trades", 0) >= 2:
            paper_wr = horizon_adj.get("decay_weighted_win_rate", horizon_adj.get("win_rate", 50))
            paper_n = horizon_adj["total_trades"]
            feedback_source = f"horizon:{horizon_key}"
        elif sector_adj and sector_adj.get("total_trades", 0) >= 2:
            paper_wr = sector_adj.get("decay_weighted_win_rate", sector_adj.get("win_rate", 50))
            paper_n = sector_adj["total_trades"]
            feedback_source = f"sector:{sector_key}"
        elif regime_adj and regime_adj.get("total_trades", 0) >= 3:
            paper_wr = regime_adj.get("decay_weighted_win_rate", regime_adj.get("win_rate", 50))
            paper_n = regime_adj["total_trades"]
            feedback_source = f"regime:{regime_key}"
        elif adj and adj.get("total_trades", 0) >= 2:
            paper_wr = adj.get("decay_weighted_win_rate", adj.get("actual_win_rate", 50))
            paper_n = adj["total_trades"]
            feedback_source = f"pattern:{pattern}"

        if paper_wr is not None and paper_n >= 2:
            raw_wr = result.get("win_rate", 50)

            # Weight: paper data gets up to 50% influence, scaling with sample size
            paper_weight = min(0.50, paper_n / (paper_n + 20))
            blended_wr = raw_wr * (1 - paper_weight) + paper_wr * paper_weight
            result["win_rate"] = round(blended_wr, 2)
            result["feedback_applied"] = True
            result["feedback_paper_wr"] = round(paper_wr, 1)
            result["feedback_paper_n"] = paper_n
            result["feedback_blend_weight"] = round(paper_weight, 2)
            result["feedback_source"] = feedback_source

        # --- Apply learned rules to confidence (scaled 3-5x stronger) (#7) ---
        conf_boost = 0.0
        for rule in self.feedback_rules:
            ctx = rule.get("context", "")
            rule_conf = rule.get("confidence", 0.5)
            # Scale factor based on sample size backing the rule
            scale = min(3.0, 1.0 + rule_conf * 2.5)  # 1.0 to 3.0x

            if ctx == "trend_alignment" and trend_short:
                direction = result.get("predicted_direction", "")
                is_aligned = (direction == "bullish" and trend_short == "bullish") or \
                             (direction == "bearish" and trend_short == "bearish")
                if is_aligned:
                    conf_boost += 0.05 * scale * rule_conf  # up to +0.135
                else:
                    conf_boost -= 0.04 * scale * rule_conf  # up to -0.108

            elif ctx == "volume_confirmation":
                conf_boost += 0.03 * scale * rule_conf  # up to +0.064

            elif ctx.startswith("volume_per_pattern_"):
                # Per-pattern volume rules — stronger signal
                rule_pattern = ctx.replace("volume_per_pattern_", "")
                if rule_pattern == pattern:
                    conf_boost += 0.04 * scale * rule_conf  # targeted boost

            elif ctx == "stop_loss_tuning":
                conf_boost -= 0.04 * scale * rule_conf  # up to -0.108

        # --- Volume breakdown confidence adjustment (#5) ---
        if adj and adj.get("volume_breakdown"):
            vb = adj["volume_breakdown"]
            vc_wr = vb.get("vol_confirmed_wr")
            vn_wr = vb.get("vol_unconfirmed_wr")
            if vc_wr is not None and vn_wr is not None:
                # If volume-confirmed WR is significantly better, boost confidence
                vol_edge = (vc_wr - vn_wr) / 100  # e.g., 0.20 for 20% difference
                if vol_edge > 0.1:
                    conf_boost += vol_edge * 0.15  # up to +0.03 for 20% edge

        if conf_boost != 0:
            old_conf = result.get("confidence_score", 0.5)
            new_conf = max(0.0, min(1.0, old_conf + conf_boost))
            result["confidence_score"] = round(new_conf, 4)
            result["confidence_level"] = (
                "HIGH" if new_conf > 0.55 else
                "MEDIUM" if new_conf > 0.35 else
                "LOW"
            )
            result["feedback_conf_boost"] = round(conf_boost, 4)

        return result

    def _cap_per_instrument(self, doc_indices, query_instrument=None):
        """Cap matches from any single instrument to MAX_PER_INSTRUMENT.
        Ensures cross-instrument generalization."""
        inst_buckets = defaultdict(list)
        for idx in doc_indices:
            inst = self.docs[idx].get("instrument", "unknown")
            inst_buckets[inst].append(idx)

        capped = []
        for inst, indices in inst_buckets.items():
            limit = MAX_PER_INSTRUMENT
            # If querying own instrument, allow slightly more but still cap
            if inst == query_instrument:
                limit = min(MAX_PER_INSTRUMENT, max(3, len(indices) // 5))
            if len(indices) > limit:
                # Take evenly spaced samples instead of random (deterministic)
                step = len(indices) / limit
                indices = [indices[int(i * step)] for i in range(limit)]
            capped.extend(indices)

        return capped

    def _cap_per_sector(self, doc_indices, query_sector=None):
        """Cap matches from any single sector to MAX_PER_SECTOR.
        Prevents sector concentration in match pool."""
        if not query_sector or query_sector == "unknown":
            return doc_indices  # no sector info, skip capping

        sector_buckets = defaultdict(list)
        for idx in doc_indices:
            d = self.docs[idx]
            sec = d.get("sector") or INSTRUMENT_SECTORS.get(d.get("instrument", ""), "unknown")
            sector_buckets[sec].append(idx)

        capped = []
        for sec, indices in sector_buckets.items():
            limit = MAX_PER_SECTOR
            if len(indices) > limit:
                step = len(indices) / limit
                indices = [indices[int(i * step)] for i in range(limit)]
            capped.extend(indices)
        return capped

    def _sort_sector_first(self, doc_indices, query_sector=None):
        """Sort matches so same-sector docs come first (sector-aware retrieval weighting)."""
        if not query_sector or query_sector == "unknown":
            return doc_indices

        same = []
        other = []
        for idx in doc_indices:
            d = self.docs[idx]
            sec = d.get("sector") or INSTRUMENT_SECTORS.get(d.get("instrument", ""), "unknown")
            if sec == query_sector:
                same.append(idx)
            else:
                other.append(idx)
        return same + other

    def _retrieve_matches(self, pattern, timeframe=None, trend_short=None,
                          rsi_zone=None, price_vs_vwap=None,
                          market_regime=None, instrument=None):
        """Tiered filtering to find matching historical patterns.

        Tier 1: Exact match on all provided fields
        Tier 2: Relax RSI zone (keep pattern + timeframe + trend)
        Tier 3: Relax trend (keep pattern + timeframe)
        Tier 4: Pattern only

        Same-sector matches are prioritized (sorted first) for better relevance.
        """
        # Resolve query sector for sector-aware retrieval
        query_sector = INSTRUMENT_SECTORS.get(instrument, "unknown") if instrument else None

        # Start with pattern matches
        pattern_matches = set(self.pattern_index.get(pattern, []))
        if not pattern_matches:
            return [], "no_pattern"

        # Build tier filters
        tier_1 = pattern_matches.copy()
        if timeframe:
            tier_1 &= self.tf_index.get(timeframe, set())
        if trend_short:
            tier_1 &= self.trend_index.get(trend_short, set())
        if rsi_zone:
            tier_1 &= self.rsi_index.get(rsi_zone, set())
        if price_vs_vwap and price_vs_vwap not in ("None", "unknown"):
            tier_1 &= self.vwap_index.get(price_vs_vwap, set())

        if len(tier_1) >= MIN_MATCHES:
            capped = self._cap_per_instrument(list(tier_1), instrument)
            capped = self._cap_per_sector(capped, query_sector)
            if len(capped) >= MIN_MATCHES:
                capped = self._sort_sector_first(capped, query_sector)
                return capped[:TOP_K * 3], "tier_1_exact"  # return more, will sort later

        # Tier 2: relax VWAP and RSI
        tier_2 = pattern_matches.copy()
        if timeframe:
            tier_2 &= self.tf_index.get(timeframe, set())
        if trend_short:
            tier_2 &= self.trend_index.get(trend_short, set())

        if len(tier_2) >= MIN_MATCHES:
            capped = self._cap_per_instrument(list(tier_2), instrument)
            capped = self._cap_per_sector(capped, query_sector)
            if len(capped) >= MIN_MATCHES:
                capped = self._sort_sector_first(capped, query_sector)
                return capped[:TOP_K * 3], "tier_2_relax_rsi_vwap"

        # Tier 3: relax trend too
        tier_3 = pattern_matches.copy()
        if timeframe:
            tier_3 &= self.tf_index.get(timeframe, set())

        if len(tier_3) >= MIN_MATCHES:
            capped = self._cap_per_instrument(list(tier_3), instrument)
            capped = self._cap_per_sector(capped, query_sector)
            if len(capped) >= MIN_MATCHES:
                capped = self._sort_sector_first(capped, query_sector)
                return capped[:TOP_K * 3], "tier_3_relax_trend"

        # Tier 4: pattern only
        capped = self._cap_per_instrument(list(pattern_matches), instrument)
        capped = self._cap_per_sector(capped, query_sector)
        if len(capped) >= MIN_MATCHES:
            capped = self._sort_sector_first(capped, query_sector)
            return capped[:TOP_K * 3], "tier_4_pattern_only"

        return list(pattern_matches)[:TOP_K * 3], "insufficient"

    def predict(self, pattern, timeframe=None, trend_short=None,
                rsi_zone=None, price_vs_vwap=None, market_regime=None,
                instrument=None, horizon=PRIMARY_HORIZON):
        """Generate a prediction for the given pattern + context.

        Returns dict with:
          predicted_direction, confidence_score, confidence_level,
          bullish_pct, bearish_pct, bullish_edge (base-rate corrected),
          avg_return, median_return, win_rate, profit_factor,
          avg_mfe, avg_mae, rr_ratio, n_matches, match_tier,
          horizons (multi-horizon data)
        """
        # Skip excluded patterns and non-whitelisted patterns
        if pattern in EXCLUDED_PATTERNS:
            return None
        if not is_tradeable_pattern(pattern):
            return None
        indices, tier = self._retrieve_matches(
            pattern=pattern,
            timeframe=timeframe,
            trend_short=trend_short,
            rsi_zone=rsi_zone,
            price_vs_vwap=price_vs_vwap,
            market_regime=market_regime,
            instrument=instrument,
        )

        if len(indices) < 3:
            return None

        # Reject low-quality tiers (tier_3, tier_4 have OOS PF < 1.0)
        if not is_tradeable_tier(tier):
            return None

        # Get the matched documents
        matches = [self.docs[i] for i in indices]

        # Limit to TOP_K most relevant (prefer recent data)
        # Sort by datetime descending to prefer recent
        matches.sort(key=lambda d: d.get("datetime", ""), reverse=True)
        matches = matches[:TOP_K]

        # --- Aggregate outcomes ---
        result = {
            "pattern": pattern,
            "match_tier": tier,
            "n_matches": len(matches),
            "horizons": {},
        }

        for n in [1, 3, 5, 10, 25]:
            ret_key = f"fwd_{n}_return_pct"
            dir_key = f"fwd_{n}_direction"

            returns = []
            directions = {"bullish": 0, "bearish": 0, "neutral": 0}

            for m in matches:
                if m.get(ret_key) is not None:
                    returns.append(float(m[ret_key]))
                if m.get(dir_key) in directions:
                    directions[m[dir_key]] += 1

            if not returns:
                continue

            total_dir = sum(directions.values())
            bullish_pct = directions["bullish"] / total_dir * 100 if total_dir > 0 else 50
            bearish_pct = directions["bearish"] / total_dir * 100 if total_dir > 0 else 50

            # Base-rate correction: what's the edge ABOVE random?
            base_bull = self.base_rates.get("bullish", 0.5) * 100
            bullish_edge = bullish_pct - base_bull
            bearish_edge = bearish_pct - (self.base_rates.get("bearish", 0.5) * 100)

            # Direction based on edge, not raw percentage
            if abs(bullish_edge) < 3 and abs(bearish_edge) < 3:
                direction = "neutral"
            elif bullish_edge > bearish_edge:
                direction = "bullish"
            else:
                direction = "bearish"

            result["horizons"][f"+{n}_candles"] = {
                "direction": direction,
                "bullish_pct": round(bullish_pct, 2),
                "bearish_pct": round(bearish_pct, 2),
                "bullish_edge": round(bullish_edge, 2),
                "bearish_edge": round(bearish_edge, 2),
                "avg_return": round(float(np.mean(returns)), 4),
                "median_return": round(float(np.median(returns)), 4),
                "std_return": round(float(np.std(returns)), 4),
                "min_return": round(min(returns), 4),
                "max_return": round(max(returns), 4),
                "count": len(returns),
            }

        # --- Primary horizon details ---
        h = result["horizons"].get(f"+{horizon}_candles")
        if not h:
            return None

        result["predicted_direction"] = h["direction"]
        result["bullish_pct"] = h["bullish_pct"]
        result["bearish_pct"] = h["bearish_pct"]
        result["bullish_edge"] = h["bullish_edge"]
        result["bearish_edge"] = h["bearish_edge"]
        result["avg_return"] = h["avg_return"]
        result["median_return"] = h["median_return"]

        # --- Win rate / profit factor (simulated trades) ---
        # Also compute stop-loss adjusted metrics
        trade_returns = []
        trade_returns_sl = []
        n_sl_triggered = 0
        for m in matches:
            ret = m.get(f"fwd_{horizon}_return_pct")
            if ret is None:
                continue
            ret = float(ret)
            mae = float(m.get(f"mae_{horizon}", m.get("mae_5", 0)) or 0)
            mfe = float(m.get(f"mfe_{horizon}", m.get("mfe_5", 0)) or 0)
            atr = float(m.get("atr_14", 0) or 0)
            close = float(m.get("close", 1) or 1)

            # Tiered ATR-based stop-loss: structural patterns get wider SL
            is_structural = pattern in STRUCTURAL_SL_PATTERNS
            sl_mult = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
            sl_pct = sl_mult * atr / close * 100 if (atr > 0 and close > 0) else 1.0
            sl_pct = max(0.3, min(5.0, sl_pct))

            if h["direction"] == "bullish":
                trade_returns.append(ret)
                # SL: if price dropped below SL during trade
                if mae < -sl_pct:
                    trade_returns_sl.append(-sl_pct)
                    n_sl_triggered += 1
                else:
                    trade_returns_sl.append(ret)
            elif h["direction"] == "bearish":
                trade_returns.append(-ret)
                # SL: if price rose above SL during trade
                if mfe > sl_pct:
                    trade_returns_sl.append(-sl_pct)
                    n_sl_triggered += 1
                else:
                    trade_returns_sl.append(-ret)
            # neutral = no trade

        wins = [t for t in trade_returns if t > 0]
        losses = [t for t in trade_returns if t <= 0]
        result["win_rate"] = round(len(wins) / len(trade_returns) * 100, 2) if trade_returns else 0
        gross_wins = sum(wins) if wins else 0
        gross_losses = abs(sum(losses)) if losses else 0.001
        result["profit_factor"] = round(gross_wins / gross_losses, 3) if gross_losses > 0 else 0

        # Stop-loss adjusted metrics
        sl_wins = [t for t in trade_returns_sl if t > 0]
        sl_losses = [t for t in trade_returns_sl if t <= 0]
        result["sl_win_rate"] = round(len(sl_wins) / len(trade_returns_sl) * 100, 2) if trade_returns_sl else 0
        sl_gross_wins = sum(sl_wins) if sl_wins else 0
        sl_gross_losses = abs(sum(sl_losses)) if sl_losses else 0.001
        result["sl_profit_factor"] = round(sl_gross_wins / sl_gross_losses, 3) if sl_gross_losses > 0 else 0
        result["sl_triggers_pct"] = round(n_sl_triggered / len(trade_returns_sl) * 100, 1) if trade_returns_sl else 0

        # --- MFE / MAE (horizon-specific with fallback to 5-candle) ---
        mfe_key = f"mfe_{horizon}"
        mae_key = f"mae_{horizon}"
        mfes = [float(m.get(mfe_key, m.get("mfe_5", 0)) or 0) for m in matches
                if m.get(mfe_key) is not None or m.get("mfe_5") is not None]
        maes = [float(m.get(mae_key, m.get("mae_5", 0)) or 0) for m in matches
                if m.get(mae_key) is not None or m.get("mae_5") is not None]
        result["avg_mfe"] = round(float(np.mean(mfes)), 4) if mfes else 0
        result["avg_mae"] = round(float(np.mean(maes)), 4) if maes else 0
        result["rr_ratio"] = round(abs(result["avg_mfe"] / result["avg_mae"]), 2) \
            if result["avg_mae"] != 0 else 0

        # --- Calibrated confidence ---
        # Factors: sample size, directional edge strength, match tier quality
        edge_strength = max(abs(h["bullish_edge"]), abs(h["bearish_edge"])) / 100
        sample_adequacy = min(1.0, len(matches) / 30)
        tier_quality = {"tier_1_exact": 1.0, "tier_2_relax_rsi_vwap": 0.8,
                        "tier_3_relax_trend": 0.5, "tier_4_pattern_only": 0.3,
                        "insufficient": 0.1}.get(tier, 0.3)
        pf_factor = min(1.0, max(0, (result["profit_factor"] - 0.5) / 1.5))  # 0.5->0, 2.0->1.0

        confidence = (
            edge_strength * 0.30 +
            sample_adequacy * 0.20 +
            tier_quality * 0.25 +
            pf_factor * 0.25
        )
        conf_level = "HIGH" if confidence > 0.55 else "MEDIUM" if confidence > 0.35 else "LOW"

        result["confidence_score"] = round(confidence, 4)
        result["confidence_level"] = conf_level

        # --- Apply paper-trading feedback adjustments ---\n        # Map numeric horizon to label for horizon-aware feedback\n        _horizon_labels = {1: \"BTST_1d\", 3: \"Swing_3d\", 5: \"Swing_5d\", 10: \"Swing_10d\"}\n        h_label = _horizon_labels.get(horizon)\n        query_sector = INSTRUMENT_SECTORS.get(instrument, None) if instrument else None\n        self._apply_feedback(result, pattern, trend_short=trend_short, horizon_label=h_label, sector=query_sector)

        # --- Instrument breakdown ---
        inst_counts = defaultdict(int)
        for m in matches:
            inst_counts[m.get("instrument", "?")] += 1
        result["instrument_diversity"] = len(inst_counts)
        result["top_instruments"] = dict(
            sorted(inst_counts.items(), key=lambda x: -x[1])[:5]
        )

        return result

    def predict_multi_pattern(self, patterns_str, **kwargs):
        """Predict for a comma-separated pattern string.
        Returns the prediction for the strongest-edge pattern."""
        patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]
        if not patterns:
            return None

        # Filter out excluded patterns (PF < 0.5)
        patterns = [p for p in patterns if p not in EXCLUDED_PATTERNS]
        if not patterns:
            return None

        best = None
        for p in patterns:
            pred = self.predict(p, **kwargs)
            if pred is None:
                continue
            if best is None or abs(pred.get("bullish_edge", 0)) > abs(best.get("bullish_edge", 0)):
                best = pred

        return best

    def format_prediction(self, pred, query_summary=""):
        """Format prediction into a readable report."""
        if pred is None:
            return "No prediction available (insufficient matching data)."

        lines = []
        lines.append("=" * 70)
        lines.append("STATISTICAL PREDICTOR - PREDICTION REPORT")
        lines.append("=" * 70)

        if query_summary:
            lines.append(f"\nQUERY: {query_summary}")

        lines.append(f"\nPattern: {pred['pattern']}")
        lines.append(f"Match tier: {pred['match_tier']}  ({pred['n_matches']} matches)")
        lines.append(f"Instrument diversity: {pred['instrument_diversity']} unique instruments")

        # Confidence
        lines.append(f"Confidence: {pred['confidence_level']} ({pred['confidence_score']:.1%})")

        # Multi-horizon
        lines.append(f"\n{'---' * 24}")
        lines.append("FORWARD PREDICTIONS (base-rate corrected)")
        lines.append(f"{'---' * 24}")
        lines.append(f"{'Horizon':<14} {'Direction':<10} {'Edge':>8} {'Bull%':>7} {'Avg Ret':>9} {'Med Ret':>9}")

        for horizon, data in pred["horizons"].items():
            edge = max(data["bullish_edge"], data["bearish_edge"])
            lines.append(
                f"{horizon:<14} {data['direction']:<10} {edge:>+7.1f}% "
                f"{data['bullish_pct']:>6.1f}% {data['avg_return']:>+8.4f}% "
                f"{data['median_return']:>+8.4f}%"
            )

        # Trade performance
        lines.append(f"\n{'---' * 24}")
        lines.append("TRADE METRICS (primary horizon)")
        lines.append(f"{'---' * 24}")
        lines.append(f"  Win rate:       {pred['win_rate']:.1f}%")
        lines.append(f"  Profit factor:  {pred['profit_factor']:.2f}")
        lines.append(f"  Avg MFE:        {pred['avg_mfe']:+.4f}%")
        lines.append(f"  Avg MAE:        {pred['avg_mae']:+.4f}%")
        lines.append(f"  Risk/Reward:    1:{pred['rr_ratio']:.1f}")

        # Signal
        lines.append(f"\n{'=' * 70}")
        d = pred["predicted_direction"]
        signal = "BUY/LONG" if d == "bullish" else "SELL/SHORT" if d == "bearish" else "NO TRADE"
        edge_val = pred["bullish_edge"] if d == "bullish" else pred["bearish_edge"]
        lines.append(f"SIGNAL: {signal}  (edge: {edge_val:+.1f}% vs base rate)")
        lines.append(f"Confidence: {pred['confidence_level']}")
        lines.append("=" * 70)

        return "\n".join(lines)


# Quick CLI test
if __name__ == "__main__":
    sp = StatisticalPredictor()

    test_cases = [
        ("bullish_engulfing", {"timeframe": "daily", "trend_short": "bearish", "rsi_zone": "oversold"}),
        ("bearish_engulfing", {"timeframe": "daily", "trend_short": "bullish", "rsi_zone": "overbought"}),
        ("bullish_engulfing", {"timeframe": "daily", "trend_short": "bearish", "rsi_zone": "neutral"}),
        ("morning_star", {"timeframe": "daily", "trend_short": "bearish", "rsi_zone": "oversold"}),
        ("spinning_top", {"timeframe": "daily", "trend_short": "bullish", "rsi_zone": "neutral"}),
        ("tweezer_bottom", {"timeframe": "15min", "trend_short": "bearish"}),
    ]

    for pattern, ctx in test_cases:
        pred = sp.predict(pattern, **ctx)
        label = f"{pattern} | {' | '.join(f'{k}={v}' for k, v in ctx.items())}"
        print(sp.format_prediction(pred, label))
        print()
