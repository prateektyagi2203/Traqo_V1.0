"""
Regime Detector — Market State Classification
================================================
Classifies the current market regime using:
  1. Nifty 50 vs 200-DMA (trend regime)
  2. India VIX level (volatility regime)

Regime labels:
  - bull_low_vol:  Nifty > 200DMA, VIX < 20   → full position size (1.0x)
  - bull_high_vol: Nifty > 200DMA, VIX >= 20   → reduced (0.7x)
  - bear_low_vol:  Nifty < 200DMA, VIX < 20    → half size (0.5x)
  - bear_high_vol: Nifty < 200DMA, VIX >= 20   → minimal (0.3x)
  - extreme:       VIX > 30                     → no trading (0.0x)

Usage:
    from regime_detector import RegimeDetector
    rd = RegimeDetector()
    regime = rd.detect()
    # regime = {"label": "bull_low_vol", "scale": 1.0, ...}

Change log:
  2026-02-24  Initial implementation
"""

import os
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from trading_config import (
    REGIME_INDEX, REGIME_DMA_PERIOD, VIX_INSTRUMENT,
    VIX_HIGH_THRESHOLD, VIX_EXTREME_THRESHOLD,
    REGIME_POSITION_SCALE,
)

# Per-horizon regime scaling overrides.
# Shorter horizons are less sensitive to bear regimes (mean-reversion works).
# Longer horizons are MORE sensitive (trend matters more).
HORIZON_REGIME_SCALE = {
    "BTST_1d": {
        "bull_low_vol": 1.0, "bull_high_vol": 0.85,
        "bear_low_vol": 0.7, "bear_high_vol": 0.5, "extreme": 0.0,
    },
    "Swing_3d": {
        "bull_low_vol": 1.0, "bull_high_vol": 0.75,
        "bear_low_vol": 0.6, "bear_high_vol": 0.4, "extreme": 0.0,
    },
    "Swing_5d": REGIME_POSITION_SCALE,  # primary horizon → default
    "Swing_10d": {
        "bull_low_vol": 1.0, "bull_high_vol": 0.6,
        "bear_low_vol": 0.4, "bear_high_vol": 0.2, "extreme": 0.0,
    },
    "Swing_25d": {
        "bull_low_vol": 1.0, "bull_high_vol": 0.5,
        "bear_low_vol": 0.3, "bear_high_vol": 0.1, "extreme": 0.0,
    },
}


class RegimeDetector:
    """Detect market regime from Nifty 50 + VIX data."""

    def __init__(self):
        self.index_data: Optional[pd.DataFrame] = None
        self.vix_data: Optional[pd.DataFrame] = None
        self._load_data()

    def _load_csv(self, instrument: str) -> Optional[pd.DataFrame]:
        """Load daily CSV for an instrument."""
        csv_path = f"daily_10yr/{instrument}_daily_10yr.csv"
        if not os.path.exists(csv_path):
            return None
        try:
            df = pd.read_csv(csv_path)

            # Handle metadata rows (row 0="Ticker", row 1="Date" labels)
            # Skip rows where "Price" column contains non-date strings
            if "Price" in df.columns:
                # Drop metadata rows (Ticker, Date header rows)
                df = df[~df["Price"].isin(["Ticker", "Date"])].copy()
                df.rename(columns={"Price": "date"}, inplace=True)

            # Detect date column
            date_col = next(
                (c for c in ["date", "Date", "datetime", "Datetime"] if c in df.columns),
                None,
            )
            if date_col is None:
                return None
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col])
            df = df.sort_values(date_col).reset_index(drop=True)
            if date_col != "date":
                df.rename(columns={date_col: "date"}, inplace=True)

            # Detect close column and convert to numeric
            close_col = next(
                (c for c in ["Close", "close", "Adj Close"] if c in df.columns),
                None,
            )
            if close_col is None:
                return None
            df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
            df = df.dropna(subset=[close_col])
            if close_col != "close":
                df.rename(columns={close_col: "close"}, inplace=True)

            return df
        except Exception as e:
            print(f"  [REGIME] Warning: Failed to load {csv_path}: {e}")
            return None

    def _load_data(self):
        """Load Nifty 50 and VIX data."""
        self.index_data = self._load_csv(REGIME_INDEX)
        self.vix_data = self._load_csv(VIX_INSTRUMENT)

        if self.index_data is not None:
            print(f"  [REGIME] Loaded {REGIME_INDEX}: {len(self.index_data)} bars "
                  f"({self.index_data['date'].iloc[0].date()} to "
                  f"{self.index_data['date'].iloc[-1].date()})")
        else:
            print(f"  [REGIME] WARNING: Could not load {REGIME_INDEX} data.")

        if self.vix_data is not None:
            print(f"  [REGIME] Loaded {VIX_INSTRUMENT}: {len(self.vix_data)} bars")
        else:
            print(f"  [REGIME] WARNING: Could not load {VIX_INSTRUMENT} data. "
                  f"VIX regime will default to low_vol.")

    def detect(self, as_of_date: str = None) -> Dict:
        """Detect current market regime.

        Args:
            as_of_date: Optional date string (YYYY-MM-DD). Defaults to latest data.

        Returns:
            Dict with keys: label, scale, trend, vix_level, nifty_close,
                            dma_200, vix_value, as_of_date
        """
        result = {
            "label": "bull_low_vol",
            "scale": 1.0,
            "trend": "unknown",
            "vix_level": "unknown",
            "nifty_close": None,
            "dma_200": None,
            "vix_value": None,
            "as_of_date": as_of_date or datetime.now().strftime("%Y-%m-%d"),
        }

        # --- Trend regime from Nifty 200-DMA ---
        trend = "bull"
        if self.index_data is not None and len(self.index_data) >= REGIME_DMA_PERIOD:
            df = self.index_data
            if as_of_date:
                df = df[df["date"] <= pd.Timestamp(as_of_date)]

            if len(df) >= REGIME_DMA_PERIOD:
                latest_close = float(df["close"].iloc[-1])
                dma_200 = float(df["close"].tail(REGIME_DMA_PERIOD).mean())
                trend = "bull" if latest_close > dma_200 else "bear"
                result["nifty_close"] = round(latest_close, 2)
                result["dma_200"] = round(dma_200, 2)

        result["trend"] = trend

        # --- VIX regime ---
        vix_level = "low_vol"
        if self.vix_data is not None and len(self.vix_data) > 0:
            df = self.vix_data
            if as_of_date:
                df = df[df["date"] <= pd.Timestamp(as_of_date)]

            if len(df) > 0:
                vix_val = float(df["close"].iloc[-1])
                result["vix_value"] = round(vix_val, 2)

                if vix_val >= VIX_EXTREME_THRESHOLD:
                    vix_level = "extreme"
                elif vix_val >= VIX_HIGH_THRESHOLD:
                    vix_level = "high_vol"
                else:
                    vix_level = "low_vol"

        result["vix_level"] = vix_level

        # --- Combine into regime label ---
        if vix_level == "extreme":
            label = "extreme"
        elif trend == "bull" and vix_level == "low_vol":
            label = "bull_low_vol"
        elif trend == "bull" and vix_level == "high_vol":
            label = "bull_high_vol"
        elif trend == "bear" and vix_level == "low_vol":
            label = "bear_low_vol"
        else:
            label = "bear_high_vol"

        result["label"] = label
        result["scale"] = REGIME_POSITION_SCALE.get(label, 1.0)

        return result

    def get_horizon_scale(self, horizon_label: str = None,
                          as_of_date: str = None) -> float:
        """Return regime-adjusted position scale for a specific horizon.

        Args:
            horizon_label: e.g. "BTST_1d", "Swing_5d". None → default scale.
            as_of_date: Optional date string.

        Returns:
            Float scale (0.0 – 1.0).
        """
        regime = self.detect(as_of_date=as_of_date)
        label = regime["label"]
        if horizon_label and horizon_label in HORIZON_REGIME_SCALE:
            return HORIZON_REGIME_SCALE[horizon_label].get(label, regime["scale"])
        return regime["scale"]

    def detect_for_date(self, date_str: str) -> Dict:
        """Convenience wrapper to detect regime for a specific historical date."""
        return self.detect(as_of_date=date_str)

    def get_regime_history(self, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Compute regime for every date in range (useful for backtest analysis).

        Returns DataFrame with columns: date, label, scale, nifty_close, dma_200, vix_value
        """
        if self.index_data is None:
            return pd.DataFrame()

        df = self.index_data.copy()
        if start_date:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        # Pre-compute 200-DMA on the full dataset for efficiency
        full_df = self.index_data.copy()
        full_df["dma_200"] = full_df["close"].rolling(REGIME_DMA_PERIOD, min_periods=REGIME_DMA_PERIOD).mean()

        # Merge VIX data
        vix_series = None
        if self.vix_data is not None:
            vix_series = self.vix_data[["date", "close"]].rename(columns={"close": "vix_close"})

        records = []
        for _, row in df.iterrows():
            date = row["date"]
            close = row["close"]

            # Get DMA from pre-computed
            dma_row = full_df[full_df["date"] == date]
            dma_200 = float(dma_row["dma_200"].iloc[0]) if len(dma_row) > 0 and not pd.isna(dma_row["dma_200"].iloc[0]) else None

            # Get VIX
            vix_val = None
            if vix_series is not None:
                vix_row = vix_series[vix_series["date"] <= date].tail(1)
                if len(vix_row) > 0:
                    vix_val = float(vix_row["vix_close"].iloc[0])

            # Classify
            trend = "bull" if dma_200 is not None and close > dma_200 else ("bear" if dma_200 is not None else "unknown")

            if vix_val is not None and vix_val >= VIX_EXTREME_THRESHOLD:
                label = "extreme"
            elif vix_val is not None and vix_val >= VIX_HIGH_THRESHOLD:
                label = f"{trend}_high_vol" if trend != "unknown" else "bull_high_vol"
            else:
                label = f"{trend}_low_vol" if trend != "unknown" else "bull_low_vol"

            scale = REGIME_POSITION_SCALE.get(label, 1.0)

            records.append({
                "date": date,
                "label": label,
                "scale": scale,
                "nifty_close": round(close, 2),
                "dma_200": round(dma_200, 2) if dma_200 else None,
                "vix_value": round(vix_val, 2) if vix_val else None,
            })

        return pd.DataFrame(records)

    def print_status(self):
        """Print current regime status."""
        r = self.detect()
        print(f"\n  {'=' * 50}")
        print(f"  MARKET REGIME STATUS")
        print(f"  {'=' * 50}")
        print(f"  Regime:        {r['label']}")
        print(f"  Position Scale: {r['scale']:.1f}x")
        print(f"  Trend:         {r['trend']} (Nifty {r['nifty_close']} vs DMA {r['dma_200']})")
        print(f"  VIX:           {r['vix_value']} ({r['vix_level']})")
        print(f"  As of:         {r['as_of_date']}")

        if r["scale"] == 0.0:
            print(f"\n  ⛔ EXTREME REGIME — All trading halted!")
        elif r["scale"] < 1.0:
            print(f"\n  ⚠️  Reduced exposure: {r['scale']:.0%} of normal position sizes")
        else:
            print(f"\n  ✅ Full exposure allowed")


# Quick test
if __name__ == "__main__":
    rd = RegimeDetector()
    rd.print_status()

    # Print regime history for 2024
    print("\n  Regime History (2024):")
    history = rd.get_regime_history(start_date="2024-01-01", end_date="2024-12-31")
    if not history.empty:
        regime_counts = history["label"].value_counts()
        print(f"  Total days: {len(history)}")
        for label, count in regime_counts.items():
            pct = count / len(history) * 100
            print(f"    {label}: {count} days ({pct:.1f}%)")
