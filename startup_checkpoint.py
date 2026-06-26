"""
Startup Checkpoint — Retroactive Trim Execution
================================================
Loads pending trim decisions from DB and executes them whenever laptop opens.
Uses DECISION PRICE (HIGH of minute candle at decision time), NOT current price.

Flow:
  1:00 PM  - bearish score triggered, HIGH price stored in bearish_trim_decisions
  Laptop opens at 4 PM  - process_pending_trims_on_startup() runs
  -> Executes trim at stored 1 PM HIGH price
  -> Position closed? -> SKIPPED_POSITION_CLOSED (no action)
"""

import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional

log = logging.getLogger("startup_checkpoint")

DB_PATH_DEFAULT = "paper_trades/paper_trades.db"


class StartupCheckpoint:
    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        self.db_path = db_path

    def get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # SCHEMA
    # ------------------------------------------------------------------

    def ensure_trim_table(self):
        """Create bearish_trim_decisions table if it doesn't exist."""
        conn = self.get_db()
        try:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS bearish_trim_decisions (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id           INTEGER NOT NULL,
                    position_ticker       TEXT    NOT NULL,
                    decision_timestamp    DATETIME NOT NULL,
                    decision_price        REAL    NOT NULL,
                    decision_bearish_score REAL,
                    entry_bearish_score   REAL,
                    trim_percentage       INTEGER DEFAULT 30,
                    trim_reason           TEXT,
                    execution_timestamp   DATETIME,
                    execution_price       REAL,
                    execution_status      TEXT    DEFAULT 'PENDING',
                    notes                 TEXT,
                    created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(position_id) REFERENCES trades(id)
                )
            ''')
            conn.commit()
        except Exception as e:
            log.warning(f"ensure_trim_table: {e}")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # WRITE: log a trim decision
    # ------------------------------------------------------------------

    def log_trim_decision(
        self,
        position_id: int,
        position_ticker: str,
        decision_price: float,
        bearish_score: float,
        entry_bearish_score: float,
        trim_reason: str,
        trim_percentage: int = 30,
    ) -> Optional[int]:
        """
        Persist a trim decision.  Called during market hours when threshold crossed.
        Returns the new row ID or None on failure.
        """
        self.ensure_trim_table()
        conn = self.get_db()
        try:
            cur = conn.execute('''
                INSERT INTO bearish_trim_decisions
                (position_id, position_ticker, decision_timestamp, decision_price,
                 decision_bearish_score, entry_bearish_score, trim_reason,
                 trim_percentage, execution_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                position_id, position_ticker,
                datetime.now().isoformat(), decision_price,
                bearish_score, entry_bearish_score, trim_reason,
                trim_percentage, 'PENDING',
            ))
            conn.commit()
            row_id = cur.lastrowid
            log.info(
                f"[TRIM DECISION] Logged #{row_id}: {position_ticker} "
                f"@ {decision_price:.2f}, score={bearish_score if bearish_score is not None else 'N/A'}"
            )
            return row_id
        except Exception as e:
            log.error(f"Failed to log trim decision: {e}")
            return None
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # READ: pending trims
    # ------------------------------------------------------------------

    def get_pending_trims(self) -> List[Dict]:
        """Load all PENDING trim decisions."""
        self.ensure_trim_table()
        conn = self.get_db()
        try:
            cur = conn.execute('''
                SELECT * FROM bearish_trim_decisions
                WHERE execution_status = 'PENDING'
                ORDER BY decision_timestamp ASC
            ''')
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # EXECUTE: process pending trims on startup
    # ------------------------------------------------------------------

    def execute_pending_trims(self) -> Dict:
        """
        Execute all PENDING trim decisions.
        Uses stored decision_price (HIGH at time of decision).
        Called automatically when paper_trader starts.
        """
        pending = self.get_pending_trims()
        results = {'executed': 0, 'skipped': 0, 'errors': 0, 'details': []}

        if not pending:
            return results

        log.info(f"[STARTUP CHECKPOINT] Found {len(pending)} pending trim decision(s)")
        conn = self.get_db()

        for trim in pending:
            trim_id         = trim['id']
            position_id     = trim['position_id']
            ticker          = trim['position_ticker']
            decision_price  = trim['decision_price']
            decision_ts     = trim['decision_timestamp']
            trim_pct        = trim.get('trim_percentage', 30)

            try:
                # Check if position still open
                row = conn.execute(
                    "SELECT id, quantity, status FROM trades WHERE id = ?",
                    (position_id,)
                ).fetchone()

                if not row or row['status'] != 'OPEN':
                    # Position closed — log and skip
                    conn.execute('''
                        UPDATE bearish_trim_decisions
                        SET execution_status = 'SKIPPED_POSITION_CLOSED',
                            execution_timestamp = ?,
                            notes = 'Position already closed before execution'
                        WHERE id = ?
                    ''', (datetime.now().isoformat(), trim_id))
                    conn.commit()

                    results['skipped'] += 1
                    results['details'].append({
                        'status': 'SKIPPED_POSITION_CLOSED',
                        'ticker': ticker,
                        'trim_id': trim_id,
                    })
                    log.info(f"[TRIM] Skipped #{trim_id} ({ticker}): position closed")
                    continue

                # Position still OPEN — execute trim at stored decision price
                qty_to_trim = max(1, int(row['quantity'] * (trim_pct / 100)))
                new_qty     = row['quantity'] - qty_to_trim

                # With qty=1, any partial trim becomes a full exit (avoid ghost qty=0)
                if trim_pct >= 100 or new_qty <= 0:
                    # FULL EXIT — properly close trade; avoid ghost quantity=0 positions
                    entry_row = conn.execute(
                        "SELECT entry_price, direction FROM trades WHERE id = ?",
                        (position_id,)
                    ).fetchone()
                    if entry_row:
                        ep        = float(entry_row['entry_price'])
                        direction = (entry_row['direction'] or 'BULLISH').upper()
                        ret = ((ep - decision_price) / ep * 100
                               if direction == 'BEARISH'
                               else (decision_price - ep) / ep * 100)
                        trade_status = 'WON' if ret > 0 else 'LOST'
                    else:
                        ret          = 0.0
                        trade_status = 'LOST'

                    conn.execute(
                        """UPDATE trades
                               SET status=?, exit_price=?, exit_date=?,
                                   exit_reason=?, actual_return_pct=?,
                                   updated_at=datetime('now')
                             WHERE id=?""",
                        (trade_status, decision_price,
                         datetime.now().strftime('%Y-%m-%d'),
                         f'bearish_full_exit (decision @ {decision_ts})',
                         ret, position_id),
                    )
                    exec_status = 'EXECUTED_FULL_EXIT'
                else:
                    conn.execute(
                        "UPDATE trades SET quantity = ? WHERE id = ?",
                        (new_qty, position_id)
                    )
                    exec_status = 'EXECUTED'

                conn.execute('''
                    UPDATE bearish_trim_decisions
                    SET execution_status    = ?,
                        execution_timestamp = ?,
                        execution_price     = ?,
                        notes               = ?
                    WHERE id = ?
                ''', (
                    exec_status,
                    datetime.now().isoformat(),
                    decision_price,
                    f"Trimmed {qty_to_trim} units at decision price {decision_price:.2f} "
                    f"(decision at {decision_ts}). Executed retroactively on startup.",
                    trim_id,
                ))
                conn.commit()

                results['executed'] += 1
                results['details'].append({
                    'status': exec_status,
                    'ticker': ticker,
                    'trim_id': trim_id,
                    'qty_trimmed': qty_to_trim,
                    'price': decision_price,
                    'decision_time': decision_ts,
                })
                log.warning(
                    f"[TRIM EXECUTED] #{trim_id}: {ticker}, "
                    f"status={exec_status}, qty={qty_to_trim} @ {decision_price:.2f} "
                    f"(decided {decision_ts})"
                )

            except Exception as e:
                log.error(f"[TRIM] Error processing #{trim_id} ({ticker}): {e}")
                results['errors'] += 1
                results['details'].append({
                    'status': 'ERROR', 'ticker': ticker,
                    'trim_id': trim_id, 'error': str(e),
                })

        conn.close()
        log.info(
            f"[STARTUP CHECKPOINT] Done: {results['executed']} executed, "
            f"{results['skipped']} skipped, {results['errors']} errors"
        )
        return results


def process_pending_exits_on_startup(db_path: str = DB_PATH_DEFAULT) -> Dict:
    """
    Execute all pending early-exit decisions (same table as trims).
    Identical flow to trims: execute at stored decision price, skip if position closed.
    """
    cp = StartupCheckpoint(db_path=db_path)
    return cp.execute_pending_trims()  # Executes both trims and early-exits from same table


def process_pending_exits_on_startup(db_path: str = DB_PATH_DEFAULT) -> Dict:
    """Alias for process_pending_trims_on_startup() (same table logic)."""
    return process_pending_trims_on_startup(db_path=db_path)


def process_pending_trims_on_startup(db_path: str = DB_PATH_DEFAULT) -> Dict:
    """Convenience function — call this from paper_trader.py startup."""
    cp = StartupCheckpoint(db_path=db_path)
    return cp.execute_pending_trims()
