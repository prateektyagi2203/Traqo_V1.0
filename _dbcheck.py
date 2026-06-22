import sqlite3
db = sqlite3.connect('paper_trades/paper_trades.db')
rows = db.execute(
    "SELECT id, ticker, entry_date, predicted_win_rate, horizon_label, status "
    "FROM trades WHERE status IN ('WON','LOST','EXPIRED_WIN','EXPIRED_LOSS') "
    "ORDER BY id DESC LIMIT 10"
).fetchall()
for r in rows:
    print(r)

nulls = db.execute(
    "SELECT COUNT(*) FROM trades WHERE predicted_win_rate IS NULL "
    "AND status IN ('WON','LOST','EXPIRED_WIN','EXPIRED_LOSS')"
).fetchone()[0]
total = db.execute(
    "SELECT COUNT(*) FROM trades WHERE status IN ('WON','LOST','EXPIRED_WIN','EXPIRED_LOSS')"
).fetchone()[0]
print(f"\nNULL predicted_win_rate: {nulls} / {total} closed trades")
