"""
Feature Engineering Pipeline for Candlestick RAG
=================================================
Reads raw OHLCV CSVs → detects candlestick patterns → computes technical
indicators → adds time features → calculates probabilistic outcomes →
saves enriched CSVs + RAG-ready JSON documents.

v3: Uses shared pattern_detector module (53+ patterns),
    market regime detection, and book-enriched knowledge base.
"""

import os
import json
import glob
import warnings
import numpy as np
import pandas as pd
import ta as ta_lib
from candlestick_knowledge_base import get_reliability_rating, PATTERN_KB
from pattern_detector import detect_all_patterns, detect_market_regime, add_sr_to_dataframe
from ta.trend import EMAIndicator, ADXIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice
from datetime import datetime

warnings.filterwarnings("ignore")

# Pattern detection is imported from shared pattern_detector module
# (detect_all_patterns, detect_market_regime)

# ============================================================
# 2. TECHNICAL INDICATORS
# ============================================================

def add_technical_indicators(df):
    """Compute technical indicators using the 'ta' library."""
    print("    Computing technical indicators...", flush=True)

    # Flatten MultiIndex columns if present (yfinance quirk)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    # Ensure proper column names
    col_map = {}
    for c in df.columns:
        cl = c.lower().strip()
        if "open" in cl:
            col_map[c] = "Open"
        elif "high" in cl:
            col_map[c] = "High"
        elif "low" in cl:
            col_map[c] = "Low"
        elif "close" in cl and "adj" not in cl:
            col_map[c] = "Close"
        elif "volume" in cl:
            col_map[c] = "Volume"
    if col_map:
        df = df.rename(columns=col_map)

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else None

    # --- EMA ---
    for period in [9, 21, 50, 200]:
        try:
            ema = EMAIndicator(close=close, window=period)
            df[f"ema_{period}"] = ema.ema_indicator()
        except Exception:
            pass

    # --- RSI ---
    try:
        rsi = RSIIndicator(close=close, window=14)
        df["rsi_14"] = rsi.rsi()
    except Exception:
        pass

    # --- MACD ---
    try:
        macd = MACD(close=close)
        df["MACD_12_26_9"] = macd.macd()
        df["MACDs_12_26_9"] = macd.macd_signal()
        df["MACDh_12_26_9"] = macd.macd_diff()
    except Exception:
        pass

    # --- Stochastic ---
    try:
        stoch = StochasticOscillator(high=high, low=low, close=close)
        df["STOCHk_14"] = stoch.stoch()
        df["STOCHd_14"] = stoch.stoch_signal()
    except Exception:
        pass

    # --- Bollinger Bands ---
    try:
        bb = BollingerBands(close=close, window=20)
        df["BBL_20"] = bb.bollinger_lband()
        df["BBM_20"] = bb.bollinger_mavg()
        df["BBU_20"] = bb.bollinger_hband()
        df["BBB_20"] = bb.bollinger_wband()
        df["BBP_20"] = bb.bollinger_pband()
    except Exception:
        pass

    # --- ATR ---
    try:
        atr = AverageTrueRange(high=high, low=low, close=close, window=14)
        df["atr_14"] = atr.average_true_range()
    except Exception:
        pass

    # --- ADX ---
    try:
        adx = ADXIndicator(high=high, low=low, close=close, window=14)
        df["ADX_14"] = adx.adx()
        df["DMP_14"] = adx.adx_pos()
        df["DMN_14"] = adx.adx_neg()
    except Exception:
        pass

    # --- Volume indicators (only if volume exists and is non-zero) ---
    if volume is not None and volume.sum() > 0:
        # VWAP
        try:
            vwap = VolumeWeightedAveragePrice(high=high, low=low, close=close, volume=volume)
            df["vwap"] = vwap.volume_weighted_average_price()
        except Exception:
            pass

        # OBV
        try:
            obv = OnBalanceVolumeIndicator(close=close, volume=volume)
            df["obv"] = obv.on_balance_volume()
        except Exception:
            pass

        # Volume MA
        df["vol_ma_20"] = volume.rolling(window=20).mean()
        df["vol_ratio"] = volume / df["vol_ma_20"]

    # --- Trend direction ---
    if "ema_9" in df.columns and "ema_21" in df.columns:
        df["trend_short"] = np.where(df["ema_9"] > df["ema_21"], "bullish", "bearish")
    if "ema_21" in df.columns and "ema_50" in df.columns:
        df["trend_medium"] = np.where(df["ema_21"] > df["ema_50"], "bullish", "bearish")
    if "ema_50" in df.columns and "ema_200" in df.columns:
        df["trend_long"] = np.where(df["ema_50"] > df["ema_200"], "bullish", "bearish")

    # --- RSI zone ---
    if "rsi_14" in df.columns:
        conditions = [df["rsi_14"] < 30, df["rsi_14"] > 70]
        choices = ["oversold", "overbought"]
        df["rsi_zone"] = np.select(conditions, choices, default="neutral")

    return df


# ============================================================
# 3. TIME-BASED FEATURES
# ============================================================

def add_time_features(df, timeframe):
    """Add time-based features from the index."""
    print("    Adding time features...", flush=True)
    idx = pd.to_datetime(df.index)

    df["day_of_week"] = idx.dayofweek  # 0=Mon, 4=Fri
    df["day_name"] = idx.day_name()
    df["month"] = idx.month

    if timeframe == "intraday":
        # For intraday data, extract time-of-day features
        # Handle timezone-aware timestamps
        if hasattr(idx, 'tz') and idx.tz is not None:
            local_hour = idx.hour + 5  # UTC to IST rough offset
            local_minute = idx.minute + 30
            # Normalize
            local_hour = local_hour + local_minute // 60
            local_minute = local_minute % 60
        else:
            local_hour = idx.hour
            local_minute = idx.minute

        df["hour"] = local_hour
        df["minute"] = local_minute

        # Session classification
        def classify_session(h):
            if h < 10:
                return "opening"       # 9:15 - 10:00
            elif h < 12:
                return "morning"       # 10:00 - 12:00
            elif h < 14:
                return "lunch"         # 12:00 - 14:00
            elif h < 15:
                return "afternoon"     # 14:00 - 15:00
            else:
                return "closing"       # 15:00 - 15:30

        df["session"] = pd.Series(local_hour, index=df.index).apply(classify_session)

    # Gap from previous close
    df["gap_pct"] = ((df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100)

    # Is it an expiry day? (Thursday for weekly, last Thursday for monthly)
    df["is_thursday"] = (idx.dayofweek == 3).astype(int)

    return df


# ============================================================
# 4. PROBABILISTIC OUTCOME CALCULATOR
# ============================================================

def add_outcomes(df, forward_periods=[1, 3, 5, 10, 25]):
    """Calculate what happened N candles after each row."""
    print("    Computing probabilistic outcomes...", flush=True)

    close = df["Close"]

    for n in forward_periods:
        # Future return
        future_close = close.shift(-n)
        df[f"fwd_{n}_return_pct"] = ((future_close - close) / close * 100)

        # Direction
        df[f"fwd_{n}_direction"] = np.where(
            df[f"fwd_{n}_return_pct"] > 0, "bullish",
            np.where(df[f"fwd_{n}_return_pct"] < 0, "bearish", "neutral")
        )

    # Max favorable excursion (MFE) and Max adverse excursion (MAE)
    # in the next 5 candles
    look_ahead = 5
    mfe_list = []
    mae_list = []
    for i in range(len(df)):
        if i + look_ahead >= len(df):
            mfe_list.append(np.nan)
            mae_list.append(np.nan)
            continue
        future_highs = df["High"].iloc[i + 1: i + 1 + look_ahead]
        future_lows = df["Low"].iloc[i + 1: i + 1 + look_ahead]
        current_close = close.iloc[i]
        if current_close == 0:
            mfe_list.append(np.nan)
            mae_list.append(np.nan)
            continue
        mfe = (future_highs.max() - current_close) / current_close * 100
        mae = (future_lows.min() - current_close) / current_close * 100
        mfe_list.append(round(mfe, 4))
        mae_list.append(round(mae, 4))

    df["mfe_5"] = mfe_list  # Max Favorable Excursion (next 5 candles)
    df["mae_5"] = mae_list  # Max Adverse Excursion (next 5 candles)

    return df


# ============================================================
# 5. RAG DOCUMENT GENERATOR
# ============================================================

def _obv_trend(df, idx, lookback=5):
    """Determine OBV trend direction over the last `lookback` candles."""
    if "obv" not in df.columns or idx < lookback:
        return "unknown"
    obv_now = df["obv"].iat[idx]
    obv_prev = df["obv"].iat[idx - lookback]
    if pd.isna(obv_now) or pd.isna(obv_prev) or obv_prev == 0:
        return "unknown"
    change_pct = (obv_now - obv_prev) / abs(obv_prev) * 100
    if change_pct > 2:
        return "rising"
    elif change_pct < -2:
        return "falling"
    return "flat"


def generate_rag_documents(df, instrument_name, timeframe):
    """Generate structured JSON documents for the RAG vector store."""
    print("    Generating RAG documents...", flush=True)

    documents = []

    for i, (idx, row) in enumerate(df.iterrows()):
        patterns = row.get("patterns_all", "none")
        if patterns == "none" or not patterns:
            continue  # Only create documents for candles WITH patterns

        # Skip rows without outcome data
        if pd.isna(row.get("fwd_1_return_pct", np.nan)):
            continue

        doc = {
            "id": f"{instrument_name}_{timeframe}_{i}",
            "datetime": str(idx),
            "instrument": instrument_name,
            "timeframe": timeframe,

            # Pattern
            "patterns": patterns,

            # Price
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),

            # Context - Trend
            "trend_short": row.get("trend_short", "unknown"),
            "trend_medium": row.get("trend_medium", "unknown"),
            "trend_long": row.get("trend_long", "unknown"),

            # Context - Momentum
            "rsi_14": round(float(row["rsi_14"]), 2) if pd.notna(row.get("rsi_14")) else None,
            "rsi_zone": row.get("rsi_zone", "unknown"),

            # Context - Volatility
            "atr_14": round(float(row["atr_14"]), 2) if pd.notna(row.get("atr_14")) else None,

            # Context - Volume
            "vol_ratio": round(float(row["vol_ratio"]), 2) if pd.notna(row.get("vol_ratio")) else None,

            # VWAP & OBV (previously computed but not wired into docs)
            "vwap": round(float(row["vwap"]), 2) if pd.notna(row.get("vwap")) else None,
            "price_vs_vwap": (
                "above" if pd.notna(row.get("vwap")) and row["Close"] > row["vwap"]
                else "below" if pd.notna(row.get("vwap")) and row["Close"] < row["vwap"]
                else "at" if pd.notna(row.get("vwap"))
                else None
            ),
            "obv_trend": (
                _obv_trend(df, i) if "obv" in df.columns else None
            ),

            # Pattern confidence & volume confirmation (from pattern_detector)
            "pattern_confidence": round(float(row.get("pattern_confidence", 0.0)), 3),
            "volume_confirmed": bool(row.get("volume_confirmed", False)),

            # Market Regime
            "market_regime": row.get("market_regime", "unknown"),

            # Support / Resistance
            "sr_position": row.get("sr_position", "unknown"),
            "nearest_support": round(float(row["nearest_support"]), 2) if pd.notna(row.get("nearest_support")) else None,
            "nearest_resistance": round(float(row["nearest_resistance"]), 2) if pd.notna(row.get("nearest_resistance")) else None,
            "support_distance_pct": round(float(row["support_distance_pct"]), 2) if pd.notna(row.get("support_distance_pct")) else None,
            "resistance_distance_pct": round(float(row["resistance_distance_pct"]), 2) if pd.notna(row.get("resistance_distance_pct")) else None,

            # Time features
            "day_name": row.get("day_name", "unknown"),
            "gap_pct": round(float(row["gap_pct"]), 4) if pd.notna(row.get("gap_pct")) else None,
            "is_thursday": int(row.get("is_thursday", 0)),
        }

        # Intraday-specific
        if timeframe == "15min":
            doc["session"] = row.get("session", "unknown")
            doc["hour"] = int(row.get("hour", 0)) if pd.notna(row.get("hour")) else None

        # Outcomes
        for n in [1, 3, 5, 10, 25]:
            ret_key = f"fwd_{n}_return_pct"
            dir_key = f"fwd_{n}_direction"
            doc[ret_key] = round(float(row[ret_key]), 4) if pd.notna(row.get(ret_key)) else None
            doc[dir_key] = row.get(dir_key, None)

        doc["mfe_5"] = round(float(row["mfe_5"]), 4) if pd.notna(row.get("mfe_5")) else None
        doc["mae_5"] = round(float(row["mae_5"]), 4) if pd.notna(row.get("mae_5")) else None

        # Text representation for embedding
        doc["text"] = _build_text_repr(doc)

        documents.append(doc)

    return documents


def _build_text_repr(doc):
    """Build a natural-language text for embedding, enriched with KB knowledge."""
    pattern_str = doc['patterns']
    pattern_list = [p.strip() for p in pattern_str.split(",") if p.strip()]

    # Enrich pattern line with KB reliability ratings
    pattern_parts = []
    for p in pattern_list:
        kb_entry = PATTERN_KB.get(p)
        if kb_entry:
            pattern_parts.append(
                f"{p} (signal={kb_entry['signal']}, reliability={kb_entry['reliability']:.0%})"
            )
        else:
            pattern_parts.append(p)

    parts = [
        f"Pattern: {' | '.join(pattern_parts)}",
        f"Instrument: {doc['instrument']} | Timeframe: {doc['timeframe']}",
        f"Date: {doc['datetime']}",
        f"OHLC: O={doc['open']} H={doc['high']} L={doc['low']} C={doc['close']}",
    ]
    # Context
    ctx = []
    if doc.get("trend_short") and doc["trend_short"] != "unknown":
        ctx.append(f"Short trend: {doc['trend_short']}")
    if doc.get("trend_medium") and doc["trend_medium"] != "unknown":
        ctx.append(f"Medium trend: {doc['trend_medium']}")
    if doc.get("rsi_14") is not None:
        ctx.append(f"RSI(14): {doc['rsi_14']} ({doc.get('rsi_zone', '')})")
    if doc.get("atr_14") is not None:
        ctx.append(f"ATR(14): {doc['atr_14']}")
    if doc.get("vol_ratio") is not None:
        ctx.append(f"Volume ratio: {doc['vol_ratio']}x avg")
    if doc.get("vwap") is not None:
        ctx.append(f"VWAP: {doc['vwap']} (price {doc.get('price_vs_vwap', '?')})")
    if doc.get("obv_trend") and doc["obv_trend"] != "unknown":
        ctx.append(f"OBV trend: {doc['obv_trend']}")
    if doc.get("pattern_confidence") is not None:
        conf = doc["pattern_confidence"]
        vol_tag = " [VOL✓]" if doc.get("volume_confirmed") else ""
        ctx.append(f"Confidence: {conf:.0%}{vol_tag}")
    if doc.get("gap_pct") is not None:
        ctx.append(f"Gap: {doc['gap_pct']}%")
    if doc.get("market_regime") and doc["market_regime"] != "unknown":
        ctx.append(f"Market regime: {doc['market_regime']}")
    if doc.get("sr_position") and doc["sr_position"] != "unknown":
        sr_parts = [f"S/R: {doc['sr_position']}"]
        if doc.get("nearest_support") is not None:
            sr_parts.append(f"sup={doc['nearest_support']}({doc.get('support_distance_pct','?')}%)")
        if doc.get("nearest_resistance") is not None:
            sr_parts.append(f"res={doc['nearest_resistance']}({doc.get('resistance_distance_pct','?')}%)")
        ctx.append(" ".join(sr_parts))
    if doc.get("session"):
        ctx.append(f"Session: {doc.get('session', 'N/A')}")
    ctx.append(f"Day: {doc.get('day_name', 'N/A')}")
    if doc.get("is_thursday"):
        ctx.append("Expiry day (Thursday)")
    if ctx:
        parts.append("Context: " + " | ".join(ctx))

    # Outcomes
    outcomes = []
    for n in [1, 3, 5, 10, 25]:
        ret = doc.get(f"fwd_{n}_return_pct")
        direction = doc.get(f"fwd_{n}_direction")
        if ret is not None:
            outcomes.append(f"+{n} candles: {ret:+.4f}% ({direction})")
    if doc.get("mfe_5") is not None:
        outcomes.append(f"MFE(5): {doc['mfe_5']:+.4f}%")
    if doc.get("mae_5") is not None:
        outcomes.append(f"MAE(5): {doc['mae_5']:+.4f}%")
    if outcomes:
        parts.append("Outcome: " + " | ".join(outcomes))

    return "\n".join(parts)


# ============================================================
# 6. MAIN PIPELINE
# ============================================================

def process_file(filepath, instrument_name, timeframe):
    """Full pipeline for one CSV file."""
    print(f"\n  Processing: {filepath}")

    # Try reading with multi-level header first (yfinance format)
    try:
        df = pd.read_csv(filepath, header=[0, 1], index_col=0, parse_dates=True)
        # Flatten MultiIndex: take top-level column names
        df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]
    except Exception:
        df = pd.read_csv(filepath, index_col=0, parse_dates=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

    # Normalize column names
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

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"    SKIPPED: Missing columns {missing}")
        return None, []

    # Ensure numeric types (yfinance CSVs sometimes parse as strings)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows with NaN in OHLC
    df = df.dropna(subset=required)
    if len(df) < 50:
        print(f"    SKIPPED: Only {len(df)} rows (need at least 50)")
        return None, []

    # Pipeline — ORDER MATTERS:
    # 1. Technical indicators FIRST (vol_ratio, RSI, EMAs, VWAP, OBV)
    # 2. Pattern detection SECOND (needs vol_ratio + RSI + trend for confidence scoring)
    # 3. Market regime (needs ADX, EMAs, ATR from step 1)
    df = add_technical_indicators(df)
    df = detect_all_patterns(df)

    # Market regime detection (requires indicators to be computed first)
    print("    Detecting market regime...", flush=True)
    df["market_regime"] = detect_market_regime(df)

    # Support / Resistance levels
    print("    Computing S/R levels...", flush=True)
    df = add_sr_to_dataframe(df, window=10, lookback=100, proximity_pct=1.0)

    tf_type = "intraday" if timeframe == "15min" else "daily"
    df = add_time_features(df, tf_type)

    fwd = [1, 3, 5, 10] if timeframe == "15min" else [1, 3, 5, 10, 25]
    df = add_outcomes(df, fwd)

    # Generate RAG docs
    docs = generate_rag_documents(df, instrument_name, timeframe)

    return df, docs


def main():
    print("=" * 80)
    print("CANDLESTICK RAG — Feature Engineering Pipeline (EXPANDED)")
    print("=" * 80)

    # Use expanded data folders (10yr daily, 60d intraday, 47 instruments)
    DAILY_INPUT    = "daily_10yr"
    INTRA_INPUT    = "intraday_15min_v2"
    DAILY_OUTPUT   = "enriched_v2/daily"
    INTRA_OUTPUT   = "enriched_v2/intraday_15min"
    RAG_OUTPUT     = "rag_documents_v2"

    os.makedirs(DAILY_OUTPUT, exist_ok=True)
    os.makedirs(INTRA_OUTPUT, exist_ok=True)
    os.makedirs(RAG_OUTPUT, exist_ok=True)

    all_docs = []
    stats = {"daily_files": 0, "intra_files": 0, "daily_patterns": 0,
             "intra_patterns": 0, "total_docs": 0}

    # --- Process Daily Files (10 years) ---
    print("\n" + "=" * 80)
    print(f"PHASE 1: Daily Data — 10 years ({DAILY_INPUT}/)")
    print("=" * 80)
    for fp in sorted(glob.glob(f"{DAILY_INPUT}/*.csv")):
        name = os.path.basename(fp).replace("_daily_10yr.csv", "")
        df, docs = process_file(fp, name, "daily")
        if df is not None:
            out_path = f"{DAILY_OUTPUT}/{name}_daily_enriched.csv"
            df.to_csv(out_path)
            n_patterns = (df["patterns_all"] != "none").sum()
            print(f"    => Saved {out_path} | {len(df)} rows | {n_patterns} pattern events | {len(docs)} RAG docs")
            all_docs.extend(docs)
            stats["daily_files"] += 1
            stats["daily_patterns"] += n_patterns

    # --- Process Intraday Files (60 days) ---
    print("\n" + "=" * 80)
    print(f"PHASE 2: Intraday 15-min Data — 60 days ({INTRA_INPUT}/)")
    print("=" * 80)
    for fp in sorted(glob.glob(f"{INTRA_INPUT}/*.csv")):
        name = os.path.basename(fp).replace("_15min_60d.csv", "")
        df, docs = process_file(fp, name, "15min")
        if df is not None:
            out_path = f"{INTRA_OUTPUT}/{name}_15min_enriched.csv"
            df.to_csv(out_path)
            n_patterns = (df["patterns_all"] != "none").sum()
            print(f"    => Saved {out_path} | {len(df)} rows | {n_patterns} pattern events | {len(docs)} RAG docs")
            all_docs.extend(docs)
            stats["intra_files"] += 1
            stats["intra_patterns"] += n_patterns

    stats["total_docs"] = len(all_docs)

    # --- Save all RAG documents ---
    rag_path = f"{RAG_OUTPUT}/all_pattern_documents.json"
    with open(rag_path, "w") as f:
        json.dump(all_docs, f, indent=2, default=str)
    print(f"\n  RAG documents saved to: {rag_path}")

    # --- Also save a JSONL version (one doc per line, useful for batch embedding) ---
    jsonl_path = f"{RAG_OUTPUT}/all_pattern_documents.jsonl"
    with open(jsonl_path, "w") as f:
        for doc in all_docs:
            f.write(json.dumps(doc, default=str) + "\n")
    print(f"  RAG documents (JSONL) saved to: {jsonl_path}")

    # --- Summary ---
    print("\n" + "=" * 80)
    print("PIPELINE SUMMARY")
    print("=" * 80)
    print(f"  Daily files processed:      {stats['daily_files']}")
    print(f"  Daily pattern events:       {stats['daily_patterns']}")
    print(f"  Intraday files processed:   {stats['intra_files']}")
    print(f"  Intraday pattern events:    {stats['intra_patterns']}")
    print(f"  Total RAG documents:        {stats['total_docs']}")
    print(f"\n  Output directories:")
    print(f"    {DAILY_OUTPUT}/  - Enriched daily CSVs")
    print(f"    {INTRA_OUTPUT}/  - Enriched intraday CSVs")
    print(f"    {RAG_OUTPUT}/    - JSON + JSONL for vector store ingestion")


if __name__ == "__main__":
    main()
