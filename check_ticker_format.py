import sqlite3

conn = sqlite3.connect('paper_trades/paper_trades.db')
cur = conn.cursor()
cur.execute("SELECT DISTINCT ticker FROM trades WHERE horizon_label LIKE '%BTST%' LIMIT 5")
rows = cur.fetchall()
conn.close()
for row in rows:
    print(row[0])
