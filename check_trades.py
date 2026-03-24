import sqlite3
conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

# Check all trades by month
print("=" * 80)
print("FEBRUARY TRADES")
print("=" * 80)
cur = conn.execute('''
SELECT id, ticker, entry_date, patterns, predicted_win_rate, predicted_pf 
FROM trades WHERE entry_date >= '2026-02-01' AND entry_date < '2026-03-01'
ORDER BY entry_date ASC
''')
feb_trades = cur.fetchall()
print(f"Total February trades: {len(feb_trades)}")
for row in feb_trades[:5]:
    print(dict(row))
if len(feb_trades) > 5:
    print(f"... and {len(feb_trades) - 5} more")

print("\n" + "=" * 80)
print("MARCH TRADES")
print("=" * 80)
cur = conn.execute('''
SELECT id, ticker, entry_date, patterns, predicted_win_rate, predicted_pf 
FROM trades WHERE entry_date >= '2026-03-01'
ORDER BY entry_date DESC LIMIT 10
''')
march_trades = cur.fetchall()
print(f"Total March trades: {len(march_trades)}")
for row in march_trades:
    print(dict(row))
