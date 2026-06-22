"""
One-time DB initialisation script for bearish_trim_decisions table.
Run once: python init_trim_table.py
"""
import sqlite3, os

db_path = "paper_trades/paper_trades.db"
if not os.path.exists(db_path):
    print(f"ERROR: DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)

conn.execute('''
    CREATE TABLE IF NOT EXISTS bearish_trim_decisions (
        id                     INTEGER  PRIMARY KEY AUTOINCREMENT,
        position_id            INTEGER  NOT NULL,
        position_ticker        TEXT     NOT NULL,
        decision_timestamp     DATETIME NOT NULL,
        decision_price         REAL     NOT NULL,
        decision_bearish_score REAL,
        entry_bearish_score    REAL,
        trim_percentage        INTEGER  DEFAULT 30,
        trim_reason            TEXT,
        execution_timestamp    DATETIME,
        execution_price        REAL,
        execution_status       TEXT     DEFAULT 'PENDING',
        notes                  TEXT,
        created_at             DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(position_id) REFERENCES trades(id)
    )
''')

conn.commit()

# Verify
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bearish_trim_decisions'")
if cur.fetchone():
    print("OK  bearish_trim_decisions table is ready")
else:
    print("ERROR: table creation failed")

conn.close()
