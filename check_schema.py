import sqlite3
import os

db_path = "paper_trades/paper_trades.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get trades table schema
    cursor.execute("PRAGMA table_info(trades)")
    schema = cursor.fetchall()
    
    print("=== TRADES TABLE SCHEMA ===")
    for row in schema:
        print(row)
    
    # Get a sample trade to see actual data
    cursor.execute("SELECT id, ticker, status FROM trades LIMIT 3")
    print("\n=== SAMPLE TRADES ===")
    for row in cursor.fetchall():
        print(row)
    
    # Check if there are closed trades
    cursor.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')")
    count = cursor.fetchone()[0]
    print(f"\n=== CLOSED TRADES COUNT: {count} ===")
    
    conn.close()
else:
    print(f"Database not found at {db_path}")
