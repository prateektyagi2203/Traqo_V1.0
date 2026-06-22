import sqlite3
conn = sqlite3.connect('paper_trades/paper_trades.db')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(trades)")
cols = cursor.fetchall()
print("Trades table columns:")
for col in cols:
    print(f"  {col[1]}: {col[2]}")
conn.close()
