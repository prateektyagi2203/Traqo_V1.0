import sqlite3
db_path = 'paper_trades/paper_trades.db'
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')")
count = cursor.fetchone()[0]
print(f'Closed trades count: {count}')
conn.close()
