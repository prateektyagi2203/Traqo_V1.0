import sqlite3

conn = sqlite3.connect('paper_trades/paper_trades.db')
cur = conn.cursor()
cur.execute("""
    SELECT DISTINCT expiry_date
    FROM trades
    WHERE horizon_label LIKE '%BTST%'
    ORDER BY expiry_date DESC
    LIMIT 10
""")
print("Recent BTST expiry dates:")
for row in cur.fetchall():
    print(f"  {row[0]}")
conn.close()
