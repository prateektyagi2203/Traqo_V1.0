"""
Shared FastStatPredictor
========================
Single source of truth for the statistical predictor used by:
  - backtest_walkforward.py (walk-forward OOS backtest)
  - backtest_ab.py (A/B comparison backtest)
  - meta_classifier.py (meta-training data generation)

This avoids the ~200-line duplication across three files.
"""

from collections import defaultdict
import numpy as np

from trading_config import (
    PRIMARY_HORIZON, EXCLUDED_INSTRUMENTS,
    MIN_MATCHES, TOP_K, MAX_PER_INSTRUMENT,
    is_tradeable_instrument, is_tradeable_timeframe,
    is_tradeable_pattern, is_tradeable_tier,
)


class FastStatPredictor:
    """Lightweight statistical predictor for backtesting and meta-training.

    Supports optional leave-one-out via `exclude_id` parameter in predict().
    """

    def __init__(self, docs):
        self.docs = [d for d in docs
                     if d.get("instrument") not in EXCLUDED_INSTRUMENTS
                     and is_tradeable_instrument(d.get("instrument", ""))
                     and is_tradeable_timeframe(d.get("timeframe", ""))
                     and d.get(f"fwd_{PRIMARY_HORIZON}_return_pct") is not None
                     and d.get(f"fwd_{PRIMARY_HORIZON}_direction") is not None]

        # Base rates
        dir_counts = defaultdict(int)
        for d in self.docs:
            dir_counts[d[f"fwd_{PRIMARY_HORIZON}_direction"]] += 1
        total = sum(dir_counts.values())
        self.base_rates = {k: v / total for k, v in dir_counts.items()}

        # Indexes
        self.pattern_idx = defaultdict(list)
        for i, d in enumerate(self.docs):
            for p in d.get("patterns", "").split(","):
                p = p.strip()
                if p and p != "none":
                    self.pattern_idx[p].append(i)

        self.tf_idx = defaultdict(set)
        self.trend_idx = defaultdict(set)
        self.rsi_idx = defaultdict(set)
        self.vwap_idx = defaultdict(set)
        self.vol_confirmed_idx = defaultdict(set)
        self.sr_position_idx = defaultdict(set)
        for i, d in enumerate(self.docs):
            self.tf_idx[d.get("timeframe", "?")].add(i)
            self.trend_idx[d.get("trend_short", "?")].add(i)
            self.rsi_idx[d.get("rsi_zone", "?")].add(i)
            self.vwap_idx[str(d.get("price_vs_vwap", "?"))].add(i)
            self.vol_confirmed_idx[str(d.get("volume_confirmed", False))].add(i)
            self.sr_position_idx[d.get("sr_position", "unknown")].add(i)

    def predict(self, doc, exclude_id=None):
        """Predict for a document.

        Args:
            doc: Document dict with patterns, timeframe, trend_short, rsi_zone.
            exclude_id: If provided, excludes this doc ID (leave-one-out).
        """
        patterns = [p.strip() for p in doc.get("patterns", "").split(",") if p.strip()]
        if not patterns:
            return None

        best_pred = None
        for pattern in patterns:
            pred = self._predict_single(pattern, doc, exclude_id)
            if pred is None:
                continue
            if best_pred is None or abs(pred["edge"]) > abs(best_pred["edge"]):
                best_pred = pred
        return best_pred

    def _predict_single(self, pattern, doc, exclude_id):
        if not is_tradeable_pattern(pattern):
            return None

        matches = set(self.pattern_idx.get(pattern, []))
        if not matches:
            return None

        tf = doc.get("timeframe")
        trend = doc.get("trend_short")
        rsi = doc.get("rsi_zone")
        vwap = str(doc.get("price_vs_vwap", "?"))
        sr_pos = doc.get("sr_position", "unknown")

        tier = "tier_4"
        candidates = matches

        # Tier 1: pattern + tf + trend + rsi + vwap + sr_position
        t1 = matches.copy()
        if tf:
            t1 &= self.tf_idx.get(tf, set())
        if trend:
            t1 &= self.trend_idx.get(trend, set())
        if rsi:
            t1 &= self.rsi_idx.get(rsi, set())
        if vwap and vwap != "?" and vwap != "None":
            t1v = t1 & self.vwap_idx.get(vwap, set())
            if len(t1v) >= MIN_MATCHES:
                t1 = t1v
        # NOTE: S/R position narrowing tested here but degraded results
        # (5/5 → 3/5 folds profitable, avg Net PF 1.097 → 1.09).
        # S/R data kept in docs for ML classifier features instead.
        if len(t1) >= MIN_MATCHES:
            candidates = t1
            tier = "tier_1"
        else:
            # Tier 2: pattern + tf + trend
            t2 = matches.copy()
            if tf:
                t2 &= self.tf_idx.get(tf, set())
            if trend:
                t2 &= self.trend_idx.get(trend, set())
            if len(t2) >= MIN_MATCHES:
                candidates = t2
                tier = "tier_2"
            else:
                # Tier 3: pattern + tf
                t3 = matches.copy()
                if tf:
                    t3 &= self.tf_idx.get(tf, set())
                if len(t3) >= MIN_MATCHES:
                    candidates = t3
                    tier = "tier_3"

        # Exclude self (leave-one-out)
        if exclude_id:
            for i in list(candidates):
                if self.docs[i].get("id") == exclude_id:
                    candidates.discard(i)

        if len(candidates) < MIN_MATCHES:
            return None

        # Reject low-quality tiers
        if not is_tradeable_tier(tier):
            return None

        # Cap per instrument
        inst_buckets = defaultdict(list)
        for idx in candidates:
            inst = self.docs[idx].get("instrument", "?")
            inst_buckets[inst].append(idx)

        capped = []
        for inst, indices in inst_buckets.items():
            if len(indices) > MAX_PER_INSTRUMENT:
                step = len(indices) / MAX_PER_INSTRUMENT
                indices = [indices[int(i * step)] for i in range(MAX_PER_INSTRUMENT)]
            capped.extend(indices)

        if len(capped) < MIN_MATCHES:
            return None

        # Sort by recency, take top K
        capped.sort(key=lambda i: self.docs[i].get("datetime", ""), reverse=True)
        capped = capped[:TOP_K]

        # Aggregate
        ret_key = f"fwd_{PRIMARY_HORIZON}_return_pct"
        dir_key = f"fwd_{PRIMARY_HORIZON}_direction"

        returns = []
        dirs = {"bullish": 0, "bearish": 0, "neutral": 0}
        for i in capped:
            d = self.docs[i]
            if d.get(ret_key) is not None:
                returns.append(float(d[ret_key]))
            if d.get(dir_key) in dirs:
                dirs[d[dir_key]] += 1

        if not returns:
            return None

        total_d = sum(dirs.values())
        bull_pct = dirs["bullish"] / total_d * 100 if total_d else 50
        bear_pct = dirs["bearish"] / total_d * 100 if total_d else 50

        # Base-rate correction
        base_bull = self.base_rates.get("bullish", 0.5) * 100
        base_bear = self.base_rates.get("bearish", 0.5) * 100
        bull_edge = bull_pct - base_bull
        bear_edge = bear_pct - base_bear

        if abs(bull_edge) < 3 and abs(bear_edge) < 3:
            direction = "neutral"
            edge = 0
        elif bull_edge > bear_edge:
            direction = "bullish"
            edge = bull_edge
        else:
            direction = "bearish"
            edge = bear_edge

        # MFE/MAE
        mfes = [float(self.docs[i]["mfe_5"]) for i in capped
                if self.docs[i].get("mfe_5") is not None]
        maes = [float(self.docs[i]["mae_5"]) for i in capped
                if self.docs[i].get("mae_5") is not None]
        avg_mfe = float(np.mean(mfes)) if mfes else 0
        avg_mae = float(np.mean(maes)) if maes else 0

        # Confidence scoring
        edge_strength = abs(edge) / 100
        sample_adeq = min(1.0, len(capped) / 30)
        tier_q = {"tier_1": 1.0, "tier_2": 0.8, "tier_3": 0.5, "tier_4": 0.3}[tier]

        trades = []
        for i in capped:
            r = self.docs[i].get(ret_key)
            if r is None:
                continue
            r = float(r)
            if direction == "bullish":
                trades.append(r)
            elif direction == "bearish":
                trades.append(-r)
        wins = [t for t in trades if t > 0]
        losses_abs = abs(sum(t for t in trades if t <= 0)) or 0.001
        pf = sum(wins) / losses_abs if wins else 0
        pf_factor = min(1.0, max(0, (pf - 0.5) / 1.5))

        confidence = edge_strength * 0.30 + sample_adeq * 0.20 + tier_q * 0.25 + pf_factor * 0.25
        conf_level = "HIGH" if confidence > 0.55 else "MEDIUM" if confidence > 0.35 else "LOW"

        n_instruments = len(set(self.docs[i].get("instrument") for i in capped))

        return {
            "predicted_direction": direction,
            "edge": round(edge, 2),
            "bull_pct": round(bull_pct, 2),
            "bear_pct": round(bear_pct, 2),
            "avg_return": round(float(np.mean(returns)), 4),
            "median_return": round(float(np.median(returns)), 4),
            "confidence_score": round(confidence, 4),
            "confidence_level": conf_level,
            "n_matches": len(capped),
            "tier": tier,
            "profit_factor": round(pf, 3),
            "predicted_pf": round(pf, 3),
            "avg_mfe": round(avg_mfe, 4),
            "avg_mae": round(avg_mae, 4),
            "rr_ratio": round(abs(avg_mfe / avg_mae), 2) if avg_mae != 0 else 0,
            "n_instruments": n_instruments,
            "pattern": pattern,
        }
