"""
Global Sentiment Monitor — Pre-Market Bearish Detection
========================================================
Fetches overnight US/Asian market data and produces composite bearish score.
Minute-level price tracking for decision-price separation.

Decision Separation Model:
  - Bearish score crosses threshold at 1:00 PM -> store HIGH price at 1 PM
  - Laptop closed, market continues
  - Laptop opens at 4 PM -> Execute trim using stored 1 PM HIGH price
"""

import yfinance as yf
import pandas as pd
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import os

log = logging.getLogger("global_sentiment")


class GlobalSentimentMonitor:
    def __init__(self):
        self.tickers = {
            'ES':  'ES=F',    # S&P 500 Futures
            'VIX': '^VIX',    # VIX Index
            'DXY': '^DXY',    # Dollar Index
            'WTI': 'CL=F',    # WTI Oil
            'NIK': '^N225',   # Nikkei
            'HSI': '^HSI',    # Hang Seng
            'ASX': '^AXJO',   # ASX 200
        }

        self.weights = {
            'ES': 0.30, 'VIX': 0.25, 'DXY': 0.15,
            'WTI': 0.10, 'NIK': 0.10, 'HSI': 0.05, 'ASX': 0.05
        }

        # Bearish signal thresholds
        self.thresholds = {
            'ES_down':   -1.5,   # % down
            'VIX_high':  22,     # level
            'DXY_up':    0.8,    # % up
            'WTI_down':  -2.5,   # % down
            'ASIA_down': -1.5,   # % down
        }

    # ------------------------------------------------------------------
    # PUBLIC: composite bearish score
    # ------------------------------------------------------------------

    def calculate_bearish_score(self) -> Tuple[int, Dict]:
        """Calculate composite bearish score (0-100)."""
        components = {}

        for ticker_key, ticker_yf in self.tickers.items():
            try:
                data = yf.download(ticker_yf, period='2d', progress=False)
                if data is not None and len(data) >= 2:
                    if ticker_key == 'ES':
                        components['ES'] = self._score_es(data)
                    elif ticker_key == 'VIX':
                        components['VIX'] = self._score_vix(data)
                    elif ticker_key == 'DXY':
                        components['DXY'] = self._score_dxy(data)
                    elif ticker_key == 'WTI':
                        components['WTI'] = self._score_wti(data)
                    else:
                        components[ticker_key] = self._score_asian(data)
            except Exception as e:
                log.warning(f"Failed to fetch {ticker_key} ({ticker_yf}): {e}")

        if not components:
            log.warning("No market data available for bearish score")
            return 30, {'error': 'No data', 'components': {}}

        composite_score = 0.0
        weight_sum = 0.0

        for ticker, score in components.items():
            if ticker in self.weights:
                composite_score += score * self.weights[ticker]
                weight_sum += self.weights[ticker]

        if weight_sum > 0:
            composite_score = composite_score / weight_sum

        return round(composite_score), {
            'components': components,
            'timestamp': datetime.now().isoformat(),
            'final_score': round(composite_score)
        }

    # ------------------------------------------------------------------
    # PRIVATE: per-instrument scoring helpers
    # ------------------------------------------------------------------

    def _get_close(self, data: pd.DataFrame) -> pd.Series:
        """Safely extract Close series from DataFrame (handles MultiIndex)."""
        close = data['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.astype(float)

    def _pct_change_last(self, data: pd.DataFrame) -> float:
        close = self._get_close(data)
        return float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)

    def _score_es(self, data: pd.DataFrame) -> int:
        try:
            pct = self._pct_change_last(data)
            return min(100, int(abs(pct) * 15)) if pct < self.thresholds['ES_down'] \
                   else max(0, 20 - int(pct * 10))
        except Exception as e:
            log.debug(f"ES score error: {e}")
            return 0

    def _score_vix(self, data: pd.DataFrame) -> int:
        try:
            v = float(self._get_close(data).iloc[-1])
            if v > 30:
                return 100
            elif v > self.thresholds['VIX_high']:
                return int((v - self.thresholds['VIX_high']) * 3)
            else:
                return max(0, int(self.thresholds['VIX_high'] - v))
        except Exception as e:
            log.debug(f"VIX score error: {e}")
            return 0

    def _score_dxy(self, data: pd.DataFrame) -> int:
        try:
            pct = self._pct_change_last(data)
            return min(100, int(abs(pct) * 12)) if pct > self.thresholds['DXY_up'] \
                   else max(0, 15 - int(pct * 8))
        except Exception as e:
            log.debug(f"DXY score error: {e}")
            return 0

    def _score_wti(self, data: pd.DataFrame) -> int:
        try:
            pct = self._pct_change_last(data)
            return min(100, int(abs(pct) * 10)) if pct < self.thresholds['WTI_down'] \
                   else max(0, 10 - int(pct * 5))
        except Exception as e:
            log.debug(f"WTI score error: {e}")
            return 0

    def _score_asian(self, data: pd.DataFrame) -> int:
        try:
            pct = self._pct_change_last(data)
            return min(100, int(abs(pct) * 12)) if pct < self.thresholds['ASIA_down'] \
                   else max(0, 10 - int(pct * 5))
        except Exception as e:
            log.debug(f"Asian score error: {e}")
            return 0

    # ------------------------------------------------------------------
    # PUBLIC: minute-level price lookup (used for decision price)
    # ------------------------------------------------------------------

    def get_minute_high(self, ticker: str, decision_timestamp: datetime) -> Optional[float]:
        """
        Fetch HIGH price of the minute candle at decision_timestamp.
        Conservative price for trim decision logging.
        """
        try:
            yf_ticker = ticker.upper()
            if '.NS' not in yf_ticker and not any(x in yf_ticker for x in ['=F', '^']):
                yf_ticker = f"{yf_ticker}.NS"

            start = decision_timestamp - timedelta(minutes=5)
            end   = decision_timestamp + timedelta(minutes=5)

            data = yf.download(yf_ticker, start=start, end=end, interval='1m', progress=False)

            if data is None or len(data) == 0:
                log.warning(f"No 1m data for {yf_ticker} around {decision_timestamp}")
                return None

            idx = data.index
            if idx.tzinfo is not None:
                ts = pd.Timestamp(decision_timestamp).tz_localize('Asia/Kolkata').tz_convert(idx.tzinfo)
            else:
                ts = pd.Timestamp(decision_timestamp)

            pos = (idx - ts).abs().argmin()
            high_col = data['High']
            if isinstance(high_col, pd.DataFrame):
                high_col = high_col.iloc[:, 0]
            return float(high_col.iloc[pos])

        except Exception as e:
            log.warning(f"get_minute_high failed for {ticker}: {e}")
            return None

    # ------------------------------------------------------------------
    # PUBLIC: save/load overnight snapshot
    # ------------------------------------------------------------------

    def save_overnight_score(self, filepath: str = "overnight_bearish_score.json"):
        """Save calculated score to JSON for startup retrieval."""
        score, details = self.calculate_bearish_score()
        payload = {
            'score': score,
            'timestamp': datetime.now().isoformat(),
            'details': details
        }
        try:
            with open(filepath, 'w') as f:
                json.dump(payload, f, indent=2)
            log.info(f"[BEARISH SCORE] Overnight score saved: {score}")
        except Exception as e:
            log.error(f"Failed to save overnight score: {e}")

        return score, details


def get_overnight_bearish_score(filepath: str = "overnight_bearish_score.json") -> int:
    """Load saved overnight bearish score from disk. Returns 30 (caution) if missing."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                score = data.get('score', 30)
                log.info(f"[BEARISH SCORE] Loaded: {score} (saved {data.get('timestamp','?')})")
                return score
    except Exception as e:
        log.warning(f"Failed to load overnight score: {e}")
    return 30


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    monitor = GlobalSentimentMonitor()
    score, details = monitor.calculate_bearish_score()
    label = "RED ALERT" if score >= 70 else "YELLOW CAUTION" if score >= 40 else "SAFE"
    print(f"\nBearish Score: {score}/100  [{label}]")
    print("Components:")
    for k, v in details.get('components', {}).items():
        print(f"  {k}: {v}")
    monitor.save_overnight_score()
    print("\nSaved to overnight_bearish_score.json")
