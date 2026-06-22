import sqlite3
import json

db_path = "paper_trades/paper_trades.db"

# Before deletion
print("=== BEFORE DELETION ===")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT id, ticker, status FROM trades WHERE status NOT IN ('OPEN','CANCELLED') ORDER BY id DESC LIMIT 5")
before_trades = cursor.fetchall()
print("Trades to delete:")
for tid, ticker, status in before_trades:
    print(f"  ID: {tid}, Ticker: {ticker}, Status: {status}")

cursor.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')")
before_count = cursor.fetchone()[0]
print(f"Total closed trades: {before_count}")
conn.close()

# Get IDs to delete
ids_to_delete = [row[0] for row in before_trades[:2]]
print(f"\nDeleting trade IDs: {ids_to_delete}")

# Simulate the UI delete (call the backend function)
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from paper_trader import PaperTrader

print("\n=== PERFORMING DELETION ===")
result = PaperTrader.purge_trades_complete(ids_to_delete)
print(f"Deletion result: {result}")

# Check after deletion
print("\n=== AFTER DELETION ===")
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Check if deleted trades are gone
cursor.execute(f"SELECT COUNT(*) FROM trades WHERE id IN ({','.join('?' * len(ids_to_delete))})", ids_to_delete)
still_exist = cursor.fetchone()[0]
print(f"Deleted trades still in DB: {still_exist} (should be 0)")

# Check total closed trades
cursor.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')")
after_count = cursor.fetchone()[0]
print(f"Total closed trades after: {after_count}")
print(f"Trades removed: {before_count - after_count} (should be {len(ids_to_delete)})")

# Check feedback log
fb_path = "feedback/feedback_log.json"
with open(fb_path) as f:
    feedback = json.load(f)
print(f"Feedback entries: {len(feedback)}")

conn.close()

if still_exist == 0 and (before_count - after_count) == len(ids_to_delete):
    print("\n✅ DELETION WORKS CORRECTLY!")
else:
    print("\n❌ DELETION FAILED!")
