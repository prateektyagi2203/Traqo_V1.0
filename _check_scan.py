import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

# Check scan_log for today (March 5, 2026)
cur = conn.cursor()
cur.execute("""SELECT * FROM scan_log WHERE date(scan_date) = '2026-03-05' ORDER BY scan_date DESC LIMIT 1""")
latest_scan = cur.fetchone()

if latest_scan:
    print(f"Latest scan on 2026-03-05: {latest_scan['scan_date']}")
    print(f"Tickers scanned: {latest_scan['tickers_scanned']}")
    print(f"Signals found: {latest_scan['signals_found']}")
    print(f"Trades entered: {latest_scan['trades_entered']}")
    print(f"Errors: {latest_scan['errors']}")
    print(f"Duration: {latest_scan['duration_seconds']:.1f}s")
else:
    print("No scan found for today")

# Check if there's daily_summary
cur.execute("""SELECT * FROM daily_summary WHERE date(report_date) = '2026-03-05' ORDER BY report_date DESC""")
summary = cur.fetchone()
if summary:
    print(f"\n\nDaily summary for 2026-03-05:")
    print(f"Trades opened: {summary['trades_opened']}")
    print(f"Trades closed: {summary['trades_closed']}")
    print(f"Wins: {summary['wins']}")
    print(f"Losses: {summary['losses']}")
    print(f"Win rate: {summary['win_rate']:.1f}%")

conn.close()
