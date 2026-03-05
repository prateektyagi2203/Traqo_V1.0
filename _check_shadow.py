import sqlite3

conn = sqlite3.connect('paper_trades/paper_trades.db')
conn.row_factory = sqlite3.Row

# Get shadow trade stats
print("SHADOW TRADE ANALYSIS (Filtered Signals Tracked)")
print("="*70)

# Count by status
statuses = ['SHADOW_OPEN', 'SHADOW_WON', 'SHADOW_LOST', 'SHADOW_EXPIRED_WIN', 'SHADOW_EXPIRED_LOSS']
for st in statuses:
    count = conn.execute(f"SELECT COUNT(*) FROM shadow_trades WHERE status=?", (st,)).fetchone()[0]
    print(f"  {st:>20}: {count}")

# Overall statistics
total_shadow = conn.execute("SELECT COUNT(*) FROM shadow_trades").fetchone()[0]
sh_closed = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status!='SHADOW_OPEN'").fetchone()[0]
sh_wins = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status IN ('SHADOW_WON','SHADOW_EXPIRED_WIN')").fetchone()[0]
sh_losses = conn.execute("SELECT COUNT(*) FROM shadow_trades WHERE status IN ('SHADOW_LOST','SHADOW_EXPIRED_LOSS')").fetchone()[0]

print(f"\nTotal shadow trades created: {total_shadow}")
print(f"Closed: {sh_closed}")
if sh_closed > 0:
    print(f"  Wins: {sh_wins} ({100*sh_wins/sh_closed:.1f}%)")
    print(f"  Losses: {sh_losses} ({100*sh_losses/sh_closed:.1f}%)")

# Compare with real trades
real_total = conn.execute("SELECT COUNT(*) FROM trades WHERE status NOT IN ('OPEN','CANCELLED')").fetchone()[0]
real_wins = conn.execute("SELECT COUNT(*) FROM trades WHERE status IN ('WON','EXPIRED_WIN')").fetchone()[0]
real_losses = conn.execute("SELECT COUNT(*) FROM trades WHERE status IN ('LOST','EXPIRED_LOSS')").fetchone()[0]

print(f"\n\nREAL TRADES (Taken)")
print(f"Total closed: {real_total}")
if real_total > 0:
    print(f"  Wins: {real_wins} ({100*real_wins/real_total:.1f}%)")
    print(f"  Losses: {real_losses} ({100*real_losses/real_total:.1f}%)")

print(f"\n\nCOMPARISON")
print(f"Shadow WR: {100*sh_wins/sh_closed:.1f}%" if sh_closed > 0 else "Shadow WR: N/A (no closed)")
print(f"Real WR:   {100*real_wins/real_total:.1f}%" if real_total > 0 else "Real WR: N/A")
print(f"\nAre filtered signals performing BETTER than taken trades?")
if sh_closed > 0 and real_total > 0:
    if (sh_wins/sh_closed) > (real_wins/real_total):
        print(f"  ⚠️  YES - You may be filtering OUT winners! Win rate gap: {100*(sh_wins/sh_closed - real_wins/real_total):.1f}%")
    else:
        print(f"  ✓ NO - Filtering is working. Taken trades outperform filtered signals.")
else:
    print("  Not enough data yet")

conn.close()
