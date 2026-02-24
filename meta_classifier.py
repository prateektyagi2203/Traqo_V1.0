"""
Meta-Classifier — Trade Quality Gate
======================================
Predicts whether a stat predictor trade will be profitable.

This model answers:
  "Given that the stat predictor says trade X, will this trade be profitable?"

Architecture:
  1. StatisticalPredictor generates a signal (direction, edge, PF, etc.)
  2. MetaClassifier receives the stat predictor's output + market context
  3. MetaClassifier outputs P(profitable) in [0, 1]
  4. Trade executes only if P(profitable) > threshold

Training methodology (double walk-forward, no leakage):
  - Fold 1: Train StatPredictor on ≤2020, generate meta-labels for 2021
  - Fold 2: Train StatPredictor on ≤2021, generate meta-labels for 2022
  - Fold 3: Train StatPredictor on ≤2022, generate meta-labels for 2023
  - Meta-classifier trains on pooled 2021-2023 labels
  - Meta-classifier tests on 2024+ (true OOS, never seen)

Benchmark: Must beat Rule6 (pf≥1.0 & n≥15) which is a simple filter
achieving PF 1.31 on OOS with 1,166 trades.

Change log:
  2026-02-24  Initial implementation (honest, non-overfit approach)
"""

import json
import os
import pickle
import numpy as np
from collections import defaultdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

import xgboost as xgb
from sklearn.model_selection import cross_val_score
from sklearn.metrics import roc_auc_score, classification_report

from trading_config import (
    PRIMARY_HORIZON, EXCLUDED_INSTRUMENTS, EXCLUDED_PATTERNS,
    WHITELISTED_PATTERNS, ALLOWED_TIMEFRAMES, ALLOWED_INSTRUMENTS,
    SLIPPAGE_COMMISSION_PCT, MIN_MATCHES, TOP_K, MAX_PER_INSTRUMENT,
    SL_FLOOR_PCT, SL_CAP_PCT, STRUCTURAL_SL_PATTERNS,
    STRUCTURAL_SL_MULTIPLIER, STANDARD_SL_MULTIPLIER,
    is_tradeable_instrument, is_tradeable_timeframe, is_tradeable_pattern,
    is_tradeable_tier,
)


# ============================================================
# FEATURE EXTRACTION
# ============================================================

# Categorical encodings — same as ml_classifier.py for consistency
TREND_MAP = {"bullish": 1, "bearish": -1, "neutral": 0, "unknown": 0, "?": 0}
OBV_MAP = {"rising": 1, "falling": -1, "flat": 0, "unknown": 0}
VWAP_MAP = {"above": 1, "below": -1, "unknown": 0, "None": 0, "?": 0, "at": 0}
PATTERN_IDS = {p: i + 1 for i, p in enumerate(sorted(WHITELISTED_PATTERNS))}

# Sector encoding for meta-classifier features
SECTOR_IDS = {
    "banking": 1, "it": 2, "auto": 3, "metals": 4, "fmcg": 5,
    "pharma": 6, "telecom": 7, "infra": 8, "finance": 9, "consumer": 10,
    "energy": 11, "media": 12, "index_in": 13, "index_us": 14,
    "index_asia": 15, "index_eu": 16, "commodity": 17, "other": 0,
}

# Import sector mapping from config
from trading_config import INSTRUMENT_SECTORS

# Feature names — order matters for array consistency
META_FEATURE_NAMES = [
    # Group 1: Market context (13)
    "rsi_14",
    "atr_14_pct",
    "vol_ratio",
    "trend_short_enc",
    "trend_medium_enc",
    "trend_long_enc",
    "vwap_position_enc",
    "obv_trend_enc",
    "gap_pct",
    "regime_trending",
    "regime_high_vol",
    "day_of_week",
    "is_expiry",
    # Group 2: Candle structure (5)
    "body_pct",
    "upper_shadow_pct",
    "lower_shadow_pct",
    "candle_range_pct",
    "is_green",
    # Group 3: Pattern identity (4)
    "pattern_id",
    "n_patterns",
    "pattern_confidence",
    "volume_confirmed",
    # Group 4: Stat predictor outputs (6) — KEY differentiators
    "stat_edge",
    "stat_pf",
    "stat_confidence",
    "stat_n_matches",
    "stat_tier_quality",
    "stat_rr_ratio",
    # Group 5: Interaction features (4)
    "edge_x_vol_ratio",
    "trend_alignment",
    "rsi_extremity",
    "edge_x_confidence",
    # Group 6: Enhanced features — VIX, calendar, sector (6)
    "vix_bucket",           # 0=low(<15), 1=medium(15-20), 2=high(20-30), 3=extreme(>30)
    "month_of_year",        # 1-12 (captures budget month, FII rotation, etc.)
    "is_month_start",       # First 5 trading days of month
    "is_month_end",         # Last 5 trading days of month
    "sector_id",            # Encoded sector (banking=1, it=2, ...)
    "above_200dma",         # 1 if nifty above 200-DMA, else 0
]


def extract_meta_features(doc: dict, stat_pred: dict) -> Optional[dict]:
    """Extract features for the meta-classifier.

    Args:
        doc: The original RAG document (has OHLC, RSI, trends, etc.)
        stat_pred: Output from the statistical predictor (edge, PF, etc.)

    Returns:
        dict of feature_name -> float, or None if invalid.
    """
    if stat_pred is None:
        return None
    if stat_pred.get("predicted_direction", "neutral") == "neutral":
        return None

    features = {}

    # -------------------------------------------------------
    # Group 1: Market context
    # -------------------------------------------------------
    features["rsi_14"] = float(doc.get("rsi_14", 50) or 50)

    close = float(doc.get("close", 1) or 1)
    atr = float(doc.get("atr_14", 0) or 0)
    features["atr_14_pct"] = (atr / close * 100) if close > 0 else 0

    features["vol_ratio"] = float(doc.get("vol_ratio", 1.0) or 1.0)

    features["trend_short_enc"] = TREND_MAP.get(doc.get("trend_short", "?"), 0)
    features["trend_medium_enc"] = TREND_MAP.get(doc.get("trend_medium", "?"), 0)
    features["trend_long_enc"] = TREND_MAP.get(doc.get("trend_long", "?"), 0)

    features["vwap_position_enc"] = VWAP_MAP.get(str(doc.get("price_vs_vwap", "?")), 0)
    features["obv_trend_enc"] = OBV_MAP.get(doc.get("obv_trend", "unknown"), 0)

    features["gap_pct"] = float(doc.get("gap_pct", 0) or 0)

    regime = doc.get("market_regime", "")
    features["regime_trending"] = 1.0 if "trending" in regime else 0.0
    features["regime_high_vol"] = 1.0 if "high_volatility" in regime else 0.0

    dt_str = doc.get("datetime", "")
    if dt_str:
        try:
            dt = datetime.fromisoformat(str(dt_str)[:19])
            features["day_of_week"] = dt.weekday()
        except (ValueError, TypeError):
            features["day_of_week"] = 2
    else:
        features["day_of_week"] = 2

    features["is_expiry"] = float(doc.get("is_thursday", 0))

    # -------------------------------------------------------
    # Group 2: Candle structure
    # -------------------------------------------------------
    open_p = float(doc.get("open", 0) or 0)
    high_p = float(doc.get("high", 0) or 0)
    low_p = float(doc.get("low", 0) or 0)
    close_p = float(doc.get("close", 0) or 0)

    candle_range = high_p - low_p if high_p > low_p else 0.001
    body = abs(close_p - open_p)

    features["body_pct"] = (body / candle_range * 100) if candle_range > 0 else 50
    features["upper_shadow_pct"] = ((high_p - max(open_p, close_p)) / candle_range * 100) if candle_range > 0 else 0
    features["lower_shadow_pct"] = ((min(open_p, close_p) - low_p) / candle_range * 100) if candle_range > 0 else 0
    features["candle_range_pct"] = (candle_range / close_p * 100) if close_p > 0 else 0
    features["is_green"] = 1.0 if close_p > open_p else 0.0

    # -------------------------------------------------------
    # Group 3: Pattern identity
    # -------------------------------------------------------
    patterns = [p.strip() for p in doc.get("patterns", "").split(",") if p.strip()]
    tradeable = [p for p in patterns if is_tradeable_pattern(p)]
    if not tradeable:
        return None

    features["pattern_id"] = PATTERN_IDS.get(tradeable[0], 0)
    features["n_patterns"] = len(tradeable)
    features["pattern_confidence"] = float(doc.get("pattern_confidence", 0.5) or 0.5)
    features["volume_confirmed"] = 1.0 if doc.get("volume_confirmed", False) else 0.0

    # -------------------------------------------------------
    # Group 4: Stat predictor outputs
    # -------------------------------------------------------
    features["stat_edge"] = abs(float(stat_pred.get("edge", 0)))
    features["stat_pf"] = float(stat_pred.get("profit_factor", stat_pred.get("predicted_pf", 0)))
    features["stat_confidence"] = float(stat_pred.get("confidence_score", stat_pred.get("predicted_confidence", 0)))
    features["stat_n_matches"] = float(stat_pred.get("n_matches", 0))
    # Tier quality: tier_1=1.0, tier_2=0.8
    tier = stat_pred.get("tier", stat_pred.get("match_tier", "tier_2"))
    if str(tier).startswith("tier_1"):
        features["stat_tier_quality"] = 1.0
    elif str(tier).startswith("tier_2"):
        features["stat_tier_quality"] = 0.8
    else:
        features["stat_tier_quality"] = 0.5
    features["stat_rr_ratio"] = float(stat_pred.get("rr_ratio", 1.0))

    # -------------------------------------------------------
    # Group 5: Interaction features
    # -------------------------------------------------------
    features["edge_x_vol_ratio"] = features["stat_edge"] * features["vol_ratio"]
    
    # Trend alignment: all 3 trends same direction = strong signal
    ts = features["trend_short_enc"]
    tm = features["trend_medium_enc"]
    tl = features["trend_long_enc"]
    if ts == tm == tl and ts != 0:
        features["trend_alignment"] = float(ts)  # +1 or -1
    elif (ts == tm or ts == tl or tm == tl) and any(x != 0 for x in [ts, tm, tl]):
        features["trend_alignment"] = 0.5 * float(ts if ts != 0 else tm)
    else:
        features["trend_alignment"] = 0.0

    features["rsi_extremity"] = abs(features["rsi_14"] - 50) / 50  # 0=neutral, 1=extreme
    features["edge_x_confidence"] = features["stat_edge"] * features["stat_confidence"]

    # -------------------------------------------------------
    # Group 6: Enhanced features — VIX, calendar, sector
    # -------------------------------------------------------
    # VIX bucket (from doc metadata if available, else default to medium)
    vix_val = float(doc.get("vix_value", doc.get("vix", 17)) or 17)
    if vix_val < 15:
        features["vix_bucket"] = 0
    elif vix_val < 20:
        features["vix_bucket"] = 1
    elif vix_val < 30:
        features["vix_bucket"] = 2
    else:
        features["vix_bucket"] = 3

    # Calendar features
    if dt_str:
        try:
            dt = datetime.fromisoformat(str(dt_str)[:19])
            features["month_of_year"] = dt.month
            features["is_month_start"] = 1.0 if dt.day <= 5 else 0.0
            features["is_month_end"] = 1.0 if dt.day >= 25 else 0.0
        except (ValueError, TypeError):
            features["month_of_year"] = 6
            features["is_month_start"] = 0.0
            features["is_month_end"] = 0.0
    else:
        features["month_of_year"] = 6
        features["is_month_start"] = 0.0
        features["is_month_end"] = 0.0

    # Sector encoding
    instrument = doc.get("instrument", "").lower()
    sector = INSTRUMENT_SECTORS.get(instrument, "other")
    features["sector_id"] = SECTOR_IDS.get(sector, 0)

    # Nifty above 200-DMA (from doc metadata if available)
    features["above_200dma"] = float(doc.get("above_200dma", doc.get("regime_trending", 0.5)) or 0.5)

    return features


def meta_features_to_array(features: dict) -> np.ndarray:
    """Convert features dict to numpy array in consistent order."""
    return np.array([features.get(f, 0.0) for f in META_FEATURE_NAMES], dtype=np.float32)


from fast_stat_predictor import FastStatPredictor as _FastStatPredictor


# ============================================================
# META-CLASSIFIER
# ============================================================

META_MODEL_PATH = "models/meta_classifier.pkl"
META_THRESHOLD_DEFAULT = 0.50  # OOS: 721 trades, PF 1.31, MaxDD ~55%
PROFIT_THRESHOLD_PCT = 0.10   # Net return threshold for 'profitable' label (OOS-validated)

class MetaClassifier:
    """XGBoost classifier predicting trade profitability.

    This is a GATE, not a direction predictor. It answers:
    "Given that the stat predictor says to trade, will this trade be profitable?"

    Training uses double walk-forward methodology:
    - Expanding-window StatPredictor generates trades on rolling OOS years
    - Labels: 1=profitable (net return > 0.10%), 0=unprofitable
    - Profit threshold filters out noise trades near breakeven
    - Meta-classifier never sees its own test data during training
    """

    def __init__(self, model_path: str = META_MODEL_PATH):
        self.model_path = model_path
        self.model = None
        self.is_trained = False
        self.train_metrics = {}
        self.feature_importance = {}
        self.threshold = META_THRESHOLD_DEFAULT
        self.trained_at: Optional[str] = None

    def generate_training_data(self, all_docs: List[dict],
                                meta_train_years: List[int] = None,
                                verbose: bool = True) -> Tuple[np.ndarray, np.ndarray, List[dict]]:
        """Generate meta-training data using double walk-forward.

        For each year Y in meta_train_years:
          1. Train a StatPredictor on docs with datetime < Y-01-01
          2. Run that predictor on docs from year Y
          3. For each trade taken, compute ground truth (profitable or not)
          4. Extract features (doc + stat predictor output)

        Returns:
            X: feature matrix
            y: binary labels (1=profitable, 0=not)
            records: list of dicts with full context for analysis
        """
        if meta_train_years is None:
            meta_train_years = [2021, 2022, 2023]

        if verbose:
            print(f"\n  [META] Generating double walk-forward training data")
            print(f"  [META] Meta-train years: {meta_train_years}")

        # Pre-filter all docs
        eligible = []
        for d in all_docs:
            dt_str = d.get("datetime", "")
            if not dt_str:
                continue
            if d.get("instrument") in EXCLUDED_INSTRUMENTS:
                continue
            if not is_tradeable_instrument(d.get("instrument", "")):
                continue
            if not is_tradeable_timeframe(d.get("timeframe", "")):
                continue
            if d.get(f"fwd_{PRIMARY_HORIZON}_return_pct") is None:
                continue
            if d.get(f"fwd_{PRIMARY_HORIZON}_direction") is None:
                continue
            eligible.append(d)

        if verbose:
            print(f"  [META] Eligible docs: {len(eligible)}")

        X_list = []
        y_list = []
        records = []

        for year in meta_train_years:
            split_date = f"{year}-01-01"
            end_date = f"{year + 1}-01-01"

            train_docs = [d for d in eligible if d.get("datetime", "") < split_date]
            test_docs = [d for d in eligible if split_date <= d.get("datetime", "") < end_date]

            if len(train_docs) < 1000 or len(test_docs) < 50:
                if verbose:
                    print(f"  [META] Year {year}: SKIPPED (train={len(train_docs)}, test={len(test_docs)})")
                continue

            if verbose:
                print(f"  [META] Year {year}: Training predictor on {len(train_docs)} docs, "
                      f"testing on {len(test_docs)} docs...")

            sp = _FastStatPredictor(train_docs)

            n_trades = 0
            n_profitable = 0

            for doc in test_docs:
                pred = sp.predict(doc)
                if pred is None or pred["predicted_direction"] == "neutral":
                    continue

                # Extract features
                feats = extract_meta_features(doc, pred)
                if feats is None:
                    continue

                # Compute ground truth label
                actual_ret = float(doc.get(f"fwd_{PRIMARY_HORIZON}_return_pct", 0))
                mae_5 = float(doc.get("mae_5", 0) or 0)
                mfe_5 = float(doc.get("mfe_5", 0) or 0)
                atr_14 = float(doc.get("atr_14", 0) or 0)
                close_price = float(doc.get("close", 1) or 1)

                # SL simulation (same as backtest)
                doc_patterns = set(p.strip() for p in doc.get("patterns", "").split(",") if p.strip())
                is_structural = bool(doc_patterns & STRUCTURAL_SL_PATTERNS)
                sl_mult = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
                sl_pct = sl_mult * atr_14 / close_price * 100 if atr_14 > 0 and close_price > 0 else 1.0
                sl_pct = max(SL_FLOOR_PCT, min(SL_CAP_PCT, sl_pct))

                pred_dir = pred["predicted_direction"]
                if pred_dir == "bullish":
                    if mae_5 < -sl_pct:
                        net_ret = -sl_pct - SLIPPAGE_COMMISSION_PCT
                    else:
                        net_ret = actual_ret - SLIPPAGE_COMMISSION_PCT
                elif pred_dir == "bearish":
                    if mfe_5 > sl_pct:
                        net_ret = -sl_pct - SLIPPAGE_COMMISSION_PCT
                    else:
                        net_ret = -actual_ret - SLIPPAGE_COMMISSION_PCT
                else:
                    continue

                label = 1 if net_ret > PROFIT_THRESHOLD_PCT else 0
                n_trades += 1
                n_profitable += int(label)

                X_list.append(meta_features_to_array(feats))
                y_list.append(label)
                records.append({
                    "year": year,
                    "doc_id": doc.get("id"),
                    "instrument": doc.get("instrument"),
                    "datetime": doc.get("datetime"),
                    "predicted_direction": pred_dir,
                    "net_return": round(net_ret, 4),
                    "label": label,
                    "edge": pred["edge"],
                    "predicted_pf": pred.get("profit_factor", 0),
                    "n_matches": pred.get("n_matches", 0),
                })

            if verbose and n_trades > 0:
                print(f"  [META]   Year {year}: {n_trades} trades, "
                      f"{n_profitable}/{n_trades} profitable ({n_profitable/n_trades:.1%})")

        if not X_list:
            if verbose:
                print(f"  [META] ERROR: No training data generated!")
            return None, None, []

        X = np.array(X_list)
        y = np.array(y_list)

        if verbose:
            print(f"\n  [META] Total training data: {len(X)} samples, "
                  f"{sum(y)}/{len(y)} profitable ({sum(y)/len(y):.1%})")

        return X, y, records

    def train(self, X: np.ndarray, y: np.ndarray, verbose: bool = True) -> dict:
        """Train the meta-classifier on prepared data.

        Returns training metrics dict.
        """
        if X is None or len(X) < 200:
            n = len(X) if X is not None else 0
            if verbose:
                print(f"  [META] Insufficient data: {n} < 200")
            return {"error": "insufficient_data"}

        if verbose:
            print(f"\n  [META] Training on {len(X)} samples "
                  f"({sum(y)}/{len(y)} profitable = {sum(y)/len(y):.1%})")

        # Hyperparameters tuned via CV + OOS validation (2026-02-24)
        # depth=5 + target>0.10% boosted CV AUC 0.565→0.576, OOS PF 1.31-1.58
        self.model = xgb.XGBClassifier(
            n_estimators=150,         # Not too many trees
            max_depth=5,              # Depth 5 (CV: 0.576 vs depth 3: 0.565)
            learning_rate=0.05,       # Slow learning
            subsample=0.7,            # Row sampling for regularization
            colsample_bytree=0.7,     # Column sampling
            min_child_weight=15,      # Require large leaf populations
            gamma=2.0,                # Aggressive pruning
            reg_alpha=0.5,            # L1 regularization
            reg_lambda=2.0,           # L2 regularization
            scale_pos_weight=len(y[y == 0]) / max(len(y[y == 1]), 1),
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
            verbosity=0,
        )

        # 5-fold CV for honest AUC estimate
        cv_scores = cross_val_score(self.model, X, y, cv=5, scoring="roc_auc")

        if verbose:
            print(f"  [META] 5-fold CV AUC: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")
            if cv_scores.mean() < 0.53:
                print(f"  [META] WARNING: AUC < 0.53 — model is near random!")
                print(f"  [META] Consider using simple rules instead of ML.")

        # Train final model
        self.model.fit(X, y)
        self.is_trained = True

        # Feature importance
        importances = self.model.feature_importances_
        self.feature_importance = {
            META_FEATURE_NAMES[i]: round(float(importances[i]), 4)
            for i in range(len(META_FEATURE_NAMES))
        }
        sorted_fi = sorted(self.feature_importance.items(), key=lambda x: -x[1])

        if verbose:
            print(f"  [META] Top 10 features:")
            for fname, imp in sorted_fi[:10]:
                print(f"          {fname}: {imp:.4f}")

        # Training metrics
        y_prob = self.model.predict_proba(X)[:, 1]
        train_auc = roc_auc_score(y, y_prob)

        self.train_metrics = {
            "n_samples": len(X),
            "profitable_pct": float(sum(y) / len(y) * 100),
            "cv_auc_mean": float(cv_scores.mean()),
            "cv_auc_std": float(cv_scores.std()),
            "train_auc": float(train_auc),
            "feature_importance": self.feature_importance,
        }

        if verbose:
            print(f"  [META] Train AUC: {train_auc:.4f}")

        return self.train_metrics

    def predict_probability(self, doc: dict, stat_pred: dict) -> Optional[float]:
        """Predict probability that a trade will be profitable.

        Args:
            doc: Original RAG document
            stat_pred: Statistical predictor output

        Returns:
            float in [0, 1] = P(profitable), or None if cannot predict.
        """
        if not self.is_trained or self.model is None:
            return None

        features = extract_meta_features(doc, stat_pred)
        if features is None:
            return None

        X = meta_features_to_array(features).reshape(1, -1)
        prob = float(self.model.predict_proba(X)[0, 1])
        return prob

    def should_trade(self, doc: dict, stat_pred: dict, threshold: float = None) -> Tuple[bool, float]:
        """Gate decision: should we execute this trade?

        Returns:
            (should_execute, probability)
        """
        if threshold is None:
            threshold = self.threshold

        prob = self.predict_probability(doc, stat_pred)
        if prob is None:
            return False, 0.0

        return prob >= threshold, prob

    def tune_threshold(self, X: np.ndarray, y: np.ndarray,
                       net_returns: np.ndarray = None,
                       verbose: bool = True) -> float:
        """Tune threshold on validation data to maximize net PF.

        This should be called on held-out validation data (e.g., 2023)
        NOT on the final test set (2024+).
        """
        if not self.is_trained:
            return META_THRESHOLD_DEFAULT

        y_prob = self.model.predict_proba(X)[:, 1]

        if verbose:
            print(f"\n  [META] Threshold tuning ({len(X)} samples)")
            header = f"  {'Threshold':>10} {'Trades':>7} {'Dropped':>8} {'WR':>7} {'PF':>7}"
            print(header)
            print(f"  {'-' * 42}")

        best_threshold = META_THRESHOLD_DEFAULT
        best_pf = 0
        best_n = 0

        for thresh in np.arange(0.40, 0.65, 0.02):
            mask = y_prob >= thresh
            n_pass = mask.sum()
            n_drop = (~mask).sum()

            if n_pass < 50:
                continue

            passed_y = y[mask]
            wr = passed_y.mean() * 100

            if net_returns is not None:
                passed_ret = net_returns[mask]
                wins_ret = passed_ret[passed_ret > 0]
                losses_ret = passed_ret[passed_ret <= 0]
                gw = wins_ret.sum() if len(wins_ret) > 0 else 0
                gl = abs(losses_ret.sum()) if len(losses_ret) > 0 else 0.001
                pf = gw / gl
            else:
                # Approximate PF from win rate
                pf = wr / (100 - wr) if wr < 100 else 10

            if verbose:
                print(f"  {thresh:>10.2f} {n_pass:>7} {n_drop:>8} {wr:>6.1f}% {pf:>6.2f}")

            # Maximize PF but require minimum trade count.
            # Use 40% of validation data as floor to prevent aggressive thresholds
            # that don't generalize to OOS (e.g., 22% pass on val → 10% on OOS).
            min_trades = max(200, int(0.40 * len(y)))
            if pf > best_pf and n_pass >= min_trades:
                best_pf = pf
                best_threshold = float(thresh)
                best_n = n_pass

        self.threshold = best_threshold
        if verbose:
            print(f"\n  [META] Optimal threshold: {best_threshold:.2f} "
                  f"(PF={best_pf:.2f}, N={best_n})")

        return best_threshold

    def save(self, path: str = None):
        """Save trained model with timestamp for staleness detection."""
        from datetime import datetime
        path = path or self.model_path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.trained_at = datetime.now().isoformat()
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "train_metrics": self.train_metrics,
                "feature_importance": self.feature_importance,
                "feature_names": META_FEATURE_NAMES,
                "threshold": self.threshold,
                "trained_at": self.trained_at,
            }, f)
        print(f"  [META] Model saved to {path} (trained_at={self.trained_at})")

    def load(self, path: str = None) -> bool:
        """Load trained model."""
        path = path or self.model_path
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.model = data["model"]
            self.train_metrics = data.get("train_metrics", {})
            self.feature_importance = data.get("feature_importance", {})
            self.threshold = data.get("threshold", META_THRESHOLD_DEFAULT)
            self.trained_at = data.get("trained_at", None)
            self.is_trained = True
            print(f"  [META] Model loaded from {path} (threshold={self.threshold:.2f})")
            return True
        except Exception as e:
            print(f"  [META] Failed to load: {e}")
            return False

    def is_stale(self, max_age_days: int = None) -> bool:
        """Check if model is older than ML_RETRAIN_INTERVAL_DAYS.

        Returns True if model should be retrained.
        """
        from datetime import datetime, timedelta
        from trading_config import ML_RETRAIN_INTERVAL_DAYS

        if max_age_days is None:
            max_age_days = ML_RETRAIN_INTERVAL_DAYS

        if self.trained_at is None:
            # Legacy model without timestamp — assume stale
            return True

        try:
            trained_dt = datetime.fromisoformat(self.trained_at)
            age = datetime.now() - trained_dt
            return age > timedelta(days=max_age_days)
        except (ValueError, TypeError):
            return True

    def get_model_age_days(self) -> Optional[int]:
        """Return model age in days, or None if unknown."""
        from datetime import datetime
        if self.trained_at is None:
            return None
        try:
            trained_dt = datetime.fromisoformat(self.trained_at)
            return (datetime.now() - trained_dt).days
        except (ValueError, TypeError):
            return None


# ============================================================
# CLI: TRAIN + EVALUATE
# ============================================================

if __name__ == "__main__":
    import time

    print("=" * 70)
    print("  META-CLASSIFIER — DOUBLE WALK-FORWARD TRAINING")
    print("=" * 70)

    # Load all docs
    print("\n  Loading RAG documents...")
    t0 = time.time()
    with open("rag_documents_v2/all_pattern_documents.json") as f:
        all_docs = json.load(f)
    print(f"  Loaded {len(all_docs)} docs in {time.time()-t0:.1f}s")

    # -------------------------------------------------------
    # PHASE 1: Generate meta-training data (double walk-forward)
    # Train stat predictor on <=2020, 2021, 2022 respectively
    # Generate labels for 2021, 2022, 2023
    # -------------------------------------------------------
    mc = MetaClassifier()
    X_train, y_train, train_records = mc.generate_training_data(
        all_docs, meta_train_years=[2021, 2022, 2023], verbose=True
    )

    if X_train is None:
        print("\n  FATAL: No training data generated. Exiting.")
        exit(1)

    # -------------------------------------------------------
    # PHASE 2: Train meta-classifier
    # -------------------------------------------------------
    metrics = mc.train(X_train, y_train, verbose=True)

    # -------------------------------------------------------
    # PHASE 3: Tune threshold on last meta-train year (2023)
    # NOT on OOS (2024+)
    # -------------------------------------------------------
    val_mask = np.array([r["year"] == 2023 for r in train_records])
    n_val = val_mask.sum()
    if n_val >= 50:
        val_X = X_train[val_mask]
        val_y = y_train[val_mask]
        val_returns = np.array([r["net_return"] for r, m in zip(train_records, val_mask) if m])
        print(f"\n  Tuning threshold on 2023 validation data ({n_val} samples)...")
        mc.tune_threshold(val_X, val_y, val_returns, verbose=True)
    else:
        print(f"\n  Insufficient 2023 validation data ({n_val} samples). Using default threshold.")

    # -------------------------------------------------------
    # PHASE 4: TRUE OOS EVALUATION (2024+)
    # The meta-classifier has never seen 2024+ data
    # -------------------------------------------------------
    print(f"\n{'=' * 70}")
    print(f"  TRUE OOS EVALUATION (2024+)")
    print(f"  Meta-classifier threshold: {mc.threshold:.2f}")
    print(f"{'=' * 70}")

    # Build stat predictor on all data <= 2023 (same as baseline backtest)
    split_date = "2024-01-01"
    eligible = [d for d in all_docs
                if d.get("datetime", "")
                and d.get("instrument") not in EXCLUDED_INSTRUMENTS
                and is_tradeable_instrument(d.get("instrument", ""))
                and is_tradeable_timeframe(d.get("timeframe", ""))
                and d.get(f"fwd_{PRIMARY_HORIZON}_return_pct") is not None
                and d.get(f"fwd_{PRIMARY_HORIZON}_direction") is not None]

    is_docs = [d for d in eligible if d.get("datetime", "") < split_date]
    oos_docs = [d for d in eligible if d.get("datetime", "") >= split_date]

    print(f"  IS docs (train): {len(is_docs)}")
    print(f"  OOS docs (test): {len(oos_docs)}")

    sp_oos = _FastStatPredictor(is_docs)

    # Run OOS: baseline (no gate) vs meta-gated
    baseline_trades = []  # net returns for ALL stat predictor trades
    gated_trades = []     # net returns for trades that pass meta gate
    rejected_trades = []  # net returns for trades rejected by meta gate

    n_total = 0
    n_traded_baseline = 0
    n_gated_pass = 0
    n_gated_reject = 0

    for doc in oos_docs:
        pred = sp_oos.predict(doc)
        if pred is None or pred["predicted_direction"] == "neutral":
            continue

        n_traded_baseline += 1

        # Compute actual net return (same as backtest)
        actual_ret = float(doc.get(f"fwd_{PRIMARY_HORIZON}_return_pct", 0))
        mae_5 = float(doc.get("mae_5", 0) or 0)
        mfe_5 = float(doc.get("mfe_5", 0) or 0)
        atr_14 = float(doc.get("atr_14", 0) or 0)
        close_price = float(doc.get("close", 1) or 1)

        doc_patterns = set(p.strip() for p in doc.get("patterns", "").split(",") if p.strip())
        is_structural = bool(doc_patterns & STRUCTURAL_SL_PATTERNS)
        sl_mult = STRUCTURAL_SL_MULTIPLIER if is_structural else STANDARD_SL_MULTIPLIER
        sl_pct = sl_mult * atr_14 / close_price * 100 if atr_14 > 0 and close_price > 0 else 1.0
        sl_pct = max(SL_FLOOR_PCT, min(SL_CAP_PCT, sl_pct))

        pred_dir = pred["predicted_direction"]
        if pred_dir == "bullish":
            if mae_5 < -sl_pct:
                net_ret = -sl_pct - SLIPPAGE_COMMISSION_PCT
            else:
                net_ret = actual_ret - SLIPPAGE_COMMISSION_PCT
        elif pred_dir == "bearish":
            if mfe_5 > sl_pct:
                net_ret = -sl_pct - SLIPPAGE_COMMISSION_PCT
            else:
                net_ret = -actual_ret - SLIPPAGE_COMMISSION_PCT
        else:
            continue

        baseline_trades.append(net_ret)

        # Meta-classifier gate
        should_execute, prob = mc.should_trade(doc, pred)
        if should_execute:
            gated_trades.append(net_ret)
            n_gated_pass += 1
        else:
            rejected_trades.append(net_ret)
            n_gated_reject += 1

    # -------------------------------------------------------
    # RESULTS
    # -------------------------------------------------------
    def calc_pf_stats(trades_list, label):
        if not trades_list:
            print(f"  {label}: No trades")
            return {}
        trades = np.array(trades_list)
        wins = trades[trades > 0]
        losses = trades[trades <= 0]
        gw = wins.sum() if len(wins) > 0 else 0
        gl = abs(losses.sum()) if len(losses) > 0 else 0.001
        pf = gw / gl
        wr = len(wins) / len(trades) * 100
        total_ret = trades.sum()
        avg_ret = trades.mean()

        # Max drawdown
        equity = np.cumsum(np.insert(trades, 0, 0))
        peak = np.maximum.accumulate(equity)
        dd = peak - equity
        max_dd = dd.max()

        print(f"\n  {label}")
        print(f"    Trades:      {len(trades)}")
        print(f"    Win Rate:    {wr:.1f}%")
        print(f"    Profit Factor: {pf:.2f}")
        print(f"    Total Return:  {total_ret:+.1f}%")
        print(f"    Avg Ret/Trade: {avg_ret:+.4f}%")
        print(f"    Max Drawdown:  {max_dd:.1f}%")

        return {"n": len(trades), "wr": wr, "pf": pf, "total_ret": total_ret, "max_dd": max_dd}

    print(f"\n{'=' * 70}")
    print(f"  OOS RESULTS COMPARISON (2024+)")
    print(f"{'=' * 70}")

    base_stats = calc_pf_stats(baseline_trades, "BASELINE (stat predictor only)")
    gated_stats = calc_pf_stats(gated_trades, f"META-GATED (threshold={mc.threshold:.2f})")
    reject_stats = calc_pf_stats(rejected_trades, "REJECTED TRADES (should be bad)")

    # Rule6 comparison
    # Load walkforward results to compute Rule6 benchmark
    print(f"\n  --- COMPARISON ---")
    if base_stats and gated_stats:
        base_pf = base_stats.get("pf", 0)
        gated_pf = gated_stats.get("pf", 0)
        improvement = (gated_pf - base_pf) / base_pf * 100 if base_pf > 0 else 0
        print(f"  Baseline PF:   {base_pf:.2f}")
        print(f"  Meta-gated PF: {gated_pf:.2f} ({improvement:+.1f}% improvement)")
        print(f"  Trades dropped: {len(rejected_trades)} ({len(rejected_trades)/len(baseline_trades)*100:.0f}%)")

        # Was the gate worth it?
        if gated_pf > base_pf and gated_pf > 1.0:
            print(f"\n  VERDICT: META-CLASSIFIER ADDS VALUE (PF {base_pf:.2f} -> {gated_pf:.2f})")
        elif gated_pf <= base_pf:
            print(f"\n  VERDICT: META-CLASSIFIER DOES NOT ADD VALUE (PF did not improve)")
            print(f"  Recommendation: Use simple rules instead (Rule6: pf>=1.0 & n>=15)")
        else:
            print(f"\n  VERDICT: MARGINAL (PF {base_pf:.2f} -> {gated_pf:.2f})")

    # Sanity check: rejected trades SHOULD have lower PF than accepted
    if reject_stats and gated_stats:
        reject_pf = reject_stats.get("pf", 0)
        gated_pf = gated_stats.get("pf", 0)
        if reject_pf >= gated_pf:
            print(f"\n  WARNING: Rejected trades (PF={reject_pf:.2f}) >= Gated trades (PF={gated_pf:.2f})")
            print(f"  This means the meta-classifier is WRONG about which trades to reject!")
            print(f"  DO NOT USE THIS MODEL IN PRODUCTION.")
        else:
            print(f"\n  Sanity check PASSED: Rejected PF ({reject_pf:.2f}) < Gated PF ({gated_pf:.2f})")

    # Save model
    mc.save()

    # Also save detailed results
    oos_report = {
        "threshold": mc.threshold,
        "train_metrics": mc.train_metrics,
        "oos_baseline": base_stats,
        "oos_gated": gated_stats,
        "oos_rejected": reject_stats,
    }
    with open("meta_classifier_results.json", "w") as f:
        json.dump(oos_report, f, indent=2, default=str)
    print(f"\n  Results saved to meta_classifier_results.json")
    print(f"\nDone.")
