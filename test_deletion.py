import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Get a closed trade ID before deletion
db_path = "paper_trades/paper_trades.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT id FROM trades WHERE status NOT IN ('OPEN','CANCELLED') LIMIT 1")
trade_id = cursor.fetchone()[0]
print(f"Selected trade ID for deletion test: {trade_id}")

# Verify it exists
cursor.execute("SELECT ticker, status FROM trades WHERE id = ?", (trade_id,))
result = cursor.fetchone()
print(f"Before deletion - Ticker: {result[0]}, Status: {result[1]}")

conn.close()

# Now try to delete using the purge function
print("\n=== ATTEMPTING DELETION ===")
try:
    from paper_trader import PaperTrader
    result = PaperTrader.purge_trades_complete([trade_id])
    print(f"Purge result: {result}")
except Exception as e:
    print(f"Error during purge: {e}")
    import traceback
    traceback.print_exc()

# Check if it was deleted
print("\n=== CHECKING AFTER DELETION ===")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT id FROM trades WHERE id = ?", (trade_id,))
result = cursor.fetchone()
if result:
    print(f"FAILED: Trade {trade_id} still exists!")
else:
    print(f"SUCCESS: Trade {trade_id} was deleted!")

# Count remaining closed trades
cursor.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')")
count = cursor.fetchone()[0]
print(f"Remaining closed trades: {count}")

conn.close()
