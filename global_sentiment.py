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
            'ES':   'ES=F',      # S&P 500 Futures
            'VIX':  '^VIX',      # CBOE VIX
            'DXY':  'DX-Y.NYB',  # Dollar Index (^DXY not in yfinance free tier)
            'WTI':  'CL=F',      # WTI Oil
            'NIK':  '^N225',     # Nikkei
            'HSI':  '^HSI',      # Hang Seng
            'ASX':  '^AXJO',     # ASX 200
            'NSE':  '^NSEI',     # Nifty 50 (domestic shock)
            'IVIX': '^INDIAVIX', # India VIX (local panic gauge)
        }

        # Weights must sum to 1.0.  IVIX gets 0.10; others trimmed proportionally.
        self.weights = {
            'ES':   0.20, 'VIX':  0.16, 'DXY': 0.09,
            'WTI':  0.07, 'NIK':  0.09, 'HSI': 0.04, 'ASX': 0.04,
            'NSE':  0.21, 'IVIX': 0.10,
        }

        # Bearish signal thresholds
        self.thresholds = {
            'ES_down':   -1.5,   # % down
            'VIX_high':  22,     # level
            'DXY_up':    0.8,    # % up
            'WTI_down':  -2.5,   # % down
            'ASIA_down': -1.5,   # % down
            'NSE_down':  -1.0,   # % down
            'IVIX_high': 16,     # India VIX > 16 = growing fear
        }

    # ------------------------------------------------------------------
    # PUBLIC: composite bearish score
    # ------------------------------------------------------------------

    def calculate_bearish_score(self) -> Tuple[int, Dict]:
        """Calculate composite bearish score (0-100)."""
        components = {}

        for ticker_key, ticker_yf in self.tickers.items():
            try:
                data = yf.download(ticker_yf, period='2d', progress=False, multi_level_index=False)
                if data is not None and len(data) >= 2:
                    if ticker_key == 'ES':
                        components['ES'] = self._score_es(data)
                    elif ticker_key == 'VIX':
                        components['VIX'] = self._score_vix(data)
                    elif ticker_key == 'DXY':
                        components['DXY'] = self._score_dxy(data)
                    elif ticker_key == 'WTI':
                        components['WTI'] = self._score_wti(data)
                    elif ticker_key == 'NSE':
                        components['NSE'] = self._score_nse(data)
                    elif ticker_key == 'IVIX':
                        components['IVIX'] = self._score_ivix(data)
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

        final = round(composite_score)

        # Override: NSE circuit breaker → force maximum score
        if self._check_nse_circuit_breaker():
            log.warning("[CIRCUIT BREAKER] Nifty intraday drop >= 10%% detected — forcing score to 100")
            final = 100

        return final, {
            'components': components,
            'timestamp': datetime.now().isoformat(),
            'final_score': final
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

    def _score_nse(self, data: pd.DataFrame) -> int:
        try:
            pct = self._pct_change_last(data)
            if pct < self.thresholds['NSE_down']:
                # Heavy penalty when local market sells off hard.
                return min(100, int(abs(pct) * 25))
            return max(0, 15 - int(pct * 6))
        except Exception as e:
            log.debug(f"NSE score error: {e}")
            return 0

    def _score_ivix(self, data: pd.DataFrame) -> int:
        """Score India VIX (^INDIAVIX).  Panic >25, concern >16."""
        try:
            v = float(self._get_close(data).iloc[-1])
            if v > 28:
                return 100                               # panic
            elif v > 20:
                return min(100, int((v - 20) * 10) + 60) # 60-100
            elif v > self.thresholds['IVIX_high']:
                return int((v - self.thresholds['IVIX_high']) * 5)  # 0-20
            else:
                return max(0, int(self.thresholds['IVIX_high'] - v))
        except Exception as e:
            log.debug(f"IVIX score error: {e}")
            return 0

    def _check_nse_circuit_breaker(self) -> bool:
        """Return True if Nifty has dropped >= 10%% intraday (L1 circuit breaker)."""
        try:
            from trading_config import NSE_CIRCUIT_BREAKER_DROP
            df = yf.download('^NSEI', period='1d', interval='5m', progress=False, multi_level_index=False)
            if df is None or len(df) < 2:
                return False
            first_price = float(df['Close'].iloc[0])
            last_price  = float(df['Close'].iloc[-1])
            if first_price <= 0:
                return False
            drop = (last_price - first_price) / first_price * 100
            return drop <= NSE_CIRCUIT_BREAKER_DROP
        except Exception:
            return False

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

            data = yf.download(yf_ticker, start=start, end=end, interval='1m', progress=False, multi_level_index=False)

            if data is None or len(data) == 0:
                log.warning(f"No 1m data for {yf_ticker} around {decision_timestamp}")
                return None

            idx = data.index
            if idx.tzinfo is not None:
                ts = pd.Timestamp(decision_timestamp).tz_localize('Asia/Kolkata').tz_convert(idx.tzinfo)
            else:
                ts = pd.Timestamp(decision_timestamp)

            pos = (idx - ts).abs().argmin()
            return float(data['High'].iloc[pos])

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
