"""
Trade Logger & Alert Infrastructure
=======================================
Append-only JSONL trade log + system event logger + Telegram alerts.

Components:
  1. TradeLogger     — append-only JSONL audit trail (logs/trade_log.jsonl)
  2. SystemLogger    — Python logging for system events (logs/system.log)
  3. AlertManager    — Telegram bot notifications (optional, token-gated)

Usage:
    from trade_logger import TradeLogger, AlertManager

    logger = TradeLogger()
    logger.log_signal(signal_dict)
    logger.log_exit(exit_dict)

    alerts = AlertManager()
    alerts.send("New signal: BULLISH RELIANCE @ ₹2,850")

Change log:
  2026-02-24  Initial implementation
"""

import json
import logging
import os
from datetime import datetime
from typing import Dict, Optional

from trading_config import (
    ALERT_LOG_DIR, TRADE_LOG_FILE, SYSTEM_LOG_FILE,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    ALERT_ON_SIGNAL, ALERT_ON_EXIT, ALERT_ON_BREAKER,
)


# ============================================================
# TRADE LOGGER — Append-only JSONL audit trail
# ============================================================

class TradeLogger:
    """Immutable, append-only trade log in JSONL format.

    Every trade event (signal, entry, exit, breaker trip) is appended
    as a single JSON line. This is the golden source for post-trade analysis.
    """

    def __init__(self, log_file: str = TRADE_LOG_FILE):
        self.log_file = log_file
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

    def _append(self, record: Dict):
        """Append a single record as a JSON line."""
        record["logged_at"] = datetime.now().isoformat()
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def log_signal(self, signal: Dict):
        """Log a new trade signal (before execution)."""
        self._append({
            "event": "signal",
            "instrument": signal.get("instrument"),
            "pattern": signal.get("pattern"),
            "direction": signal.get("direction"),
            "confidence": signal.get("confidence"),
            "meta_probability": signal.get("meta_probability"),
            "profit_factor": signal.get("profit_factor"),
            "win_rate": signal.get("win_rate"),
            "entry_price": signal.get("entry_price"),
            "sl_pct": signal.get("sl_pct"),
            "position_pct": signal.get("position_pct"),
            "position_value": signal.get("position_value"),
            "date": signal.get("date"),
        })

    def log_entry(self, trade: Dict):
        """Log a trade entry (after execution/acceptance)."""
        self._append({
            "event": "entry",
            "instrument": trade.get("instrument"),
            "direction": trade.get("direction"),
            "pattern": trade.get("pattern"),
            "entry_price": trade.get("entry_price"),
            "sl_pct": trade.get("sl_pct"),
            "position_pct": trade.get("position_pct"),
            "position_value": trade.get("position_value"),
            "date": trade.get("date"),
        })

    def log_exit(self, trade: Dict):
        """Log a trade exit."""
        self._append({
            "event": "exit",
            "instrument": trade.get("instrument"),
            "direction": trade.get("direction"),
            "pattern": trade.get("pattern"),
            "entry_price": trade.get("entry_price"),
            "exit_price": trade.get("exit_price"),
            "exit_reason": trade.get("exit_reason"),
            "pnl_value": trade.get("pnl_value"),
            "net_pnl_pct": trade.get("net_pnl_pct"),
            "days_held": trade.get("days_held"),
            "date": trade.get("date"),
            "exit_date": trade.get("exit_date"),
        })

    def log_breaker(self, breaker_name: str, details: str = ""):
        """Log a circuit breaker trip."""
        self._append({
            "event": "breaker_trip",
            "breaker": breaker_name,
            "details": details,
        })

    def log_regime(self, regime: Dict):
        """Log a regime change/detection."""
        self._append({
            "event": "regime",
            "label": regime.get("label"),
            "scale": regime.get("scale"),
            "nifty_close": regime.get("nifty_close"),
            "dma_200": regime.get("dma_200"),
            "vix_value": regime.get("vix_value"),
        })

    def get_all_records(self):
        """Read all records from the log file."""
        if not os.path.exists(self.log_file):
            return []
        records = []
        with open(self.log_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def get_trade_summary(self) -> Dict:
        """Summarize logged trades."""
        records = self.get_all_records()
        entries = [r for r in records if r.get("event") == "entry"]
        exits = [r for r in records if r.get("event") == "exit"]
        breakers = [r for r in records if r.get("event") == "breaker_trip"]

        total_pnl = sum(r.get("pnl_value", 0) for r in exits)
        wins = [r for r in exits if r.get("pnl_value", 0) > 0]

        return {
            "total_entries": len(entries),
            "total_exits": len(exits),
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(len(wins) / len(exits) * 100, 1) if exits else 0,
            "breaker_trips": len(breakers),
            "log_file": self.log_file,
        }


# ============================================================
# SYSTEM LOGGER — Python logging for system events
# ============================================================

def get_system_logger(name: str = "trading_system") -> logging.Logger:
    """Get or create a configured system logger.

    Logs to both file (logs/system.log) and console.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    os.makedirs(ALERT_LOG_DIR, exist_ok=True)

    # File handler — full log
    fh = logging.FileHandler(SYSTEM_LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    # Console handler — warnings and above
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter(
        "  [%(levelname)s] %(message)s"
    ))
    logger.addHandler(ch)

    return logger


# ============================================================
# TELEGRAM ALERT MANAGER
# ============================================================

class AlertManager:
    """Send notifications via Telegram bot.

    To enable:
      1. Create bot via @BotFather → get token
      2. Message your bot, then visit:
         https://api.telegram.org/bot<TOKEN>/getUpdates
         to get your chat_id
      3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in trading_config.py

    When token is empty, all sends are silently skipped (no error).
    """

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.enabled = bool(self.token and self.chat_id)
        self.logger = get_system_logger("alerts")

        if self.enabled:
            self.logger.info("Telegram alerts enabled")
        else:
            self.logger.debug(
                "Telegram alerts disabled (set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID in trading_config.py)"
            )

    def send(self, message: str, silent: bool = False) -> bool:
        """Send a Telegram message.

        Args:
            message: Text message to send (supports Markdown).
            silent: If True, send without notification sound.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self.enabled:
            return False

        try:
            import requests  # only import when actually sending
        except ImportError:
            self.logger.warning("requests package not installed. Cannot send Telegram alerts.")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_notification": silent,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                self.logger.info(f"Telegram alert sent: {message[:80]}...")
                return True
            else:
                self.logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
                return False
        except Exception as e:
            self.logger.warning(f"Telegram send failed: {e}")
            return False

    def alert_signal(self, signal: Dict):
        """Send alert for a new trade signal."""
        if not ALERT_ON_SIGNAL:
            return
        direction = signal.get("direction", "?").upper()
        instrument = signal.get("instrument", "?").upper()
        pattern = signal.get("pattern", "?")
        price = signal.get("entry_price", 0)
        pf = signal.get("profit_factor", 0)
        meta = signal.get("meta_probability")
        meta_str = f" | Meta: {meta:.2f}" if meta else ""

        msg = (
            f"📊 *NEW SIGNAL*\n"
            f"  {direction} {instrument} @ ₹{price:,.2f}\n"
            f"  Pattern: {pattern} | PF: {pf:.2f}{meta_str}\n"
            f"  SL: {signal.get('sl_pct', 0):.1f}% | "
            f"Size: {signal.get('position_pct', 0):.1f}%"
        )
        self.send(msg)

    def alert_exit(self, trade: Dict):
        """Send alert for a trade exit."""
        if not ALERT_ON_EXIT:
            return
        pnl = trade.get("pnl_value", 0)
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"{emoji} *TRADE CLOSED*\n"
            f"  {trade.get('instrument', '?').upper()} | "
            f"{trade.get('direction', '?')}\n"
            f"  P&L: ₹{pnl:,.0f} ({trade.get('net_pnl_pct', 0):+.2f}%)\n"
            f"  Reason: {trade.get('exit_reason', '?')} | "
            f"Days: {trade.get('days_held', 0)}"
        )
        self.send(msg)

    def alert_breaker(self, breaker_name: str, details: str = ""):
        """Send alert for a circuit breaker trip."""
        if not ALERT_ON_BREAKER:
            return
        msg = (
            f"⚠️ *CIRCUIT BREAKER*\n"
            f"  {breaker_name}\n"
            f"  {details}"
        )
        self.send(msg)

    def alert_regime(self, regime: Dict):
        """Send alert for regime change."""
        scale = regime.get("scale", 1.0)
        msg = (
            f"🌍 *REGIME UPDATE*\n"
            f"  Regime: {regime.get('label', '?')}\n"
            f"  Position scale: {scale:.0%}\n"
            f"  Nifty: {regime.get('nifty_close')} vs DMA {regime.get('dma_200')}\n"
            f"  VIX: {regime.get('vix_value')}"
        )
        self.send(msg)


# Quick test
if __name__ == "__main__":
    tl = TradeLogger()
    print(f"Trade log file: {tl.log_file}")

    # Log a sample signal
    tl.log_signal({
        "instrument": "reliance",
        "pattern": "hammer",
        "direction": "bullish",
        "confidence": "HIGH",
        "entry_price": 2850.0,
        "sl_pct": 1.5,
        "position_pct": 2.0,
        "position_value": 20000,
        "date": "2025-01-15",
    })
    print("  Sample signal logged.")

    summary = tl.get_trade_summary()
    print(f"  Summary: {summary}")

    # Alert manager
    am = AlertManager()
    print(f"  Telegram enabled: {am.enabled}")
    if not am.enabled:
        print("  To enable: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in trading_config.py")

    # System logger
    syslog = get_system_logger()
    syslog.info("Trade logger test completed")
    print(f"  System log: {SYSTEM_LOG_FILE}")
