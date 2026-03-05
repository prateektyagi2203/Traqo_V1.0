import sqlite3
import json

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

# Check all OPEN trades to see which horizons are trading
cur = conn.cursor()
cur.execute("""SELECT horizon_days, horizon_label, COUNT(*) as cnt FROM trades WHERE status='OPEN' GROUP BY horizon_days ORDER BY horizon_days""")
open_by_horizon = cur.fetchall()

print("Currently OPEN trades by horizon:")
for r in open_by_horizon:
    print(f"  {r['horizon_label']:>15} ({r['horizon_days']:>2}d): {r['cnt']} trades")

print("\n" + "="*70)

# Check trading_config to see what horizons are enabled
print("\nChecking trading_config.py for horizon settings...")
with open('trading_config.py') as f:
    content = f.read()
    if 'HORIZON_FILTERS' in content or 'ALLOWED_HORIZONS' in content:
        for line in content.split('\n'):
            if 'HORIZON' in line and ('=' in line or 'days' in line.lower()):
                print(f"  {line.strip()}")

conn.close()
