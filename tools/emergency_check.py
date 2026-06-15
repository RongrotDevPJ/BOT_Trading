import sqlite3
conn = sqlite3.connect('data/db/trading_data.db')
cur = conn.cursor()

print("=== LATEST SNAPSHOT (LIVE STATE) ===")
cur.execute("SELECT timestamp, balance, equity, open_trades, drawdown_pct, regime, floating_pnl FROM account_snapshots ORDER BY id DESC LIMIT 1")
row = cur.fetchone()
if row:
    ts, bal, eq, open_t, dd, regime, fpnl = row
    print(f"  Time:        {ts}")
    print(f"  Balance:     {bal:.2f} USC")
    print(f"  Equity:      {eq:.2f} USC")
    print(f"  Floating:    {fpnl:+.2f} USC")
    print(f"  Open Trades: {open_t}")
    print(f"  Drawdown:    {dd:.2f}%")
    print(f"  Regime:      {regime}")

print("\n=== OPEN TRADE DETAIL ===")
cur.execute("SELECT id, ticket, side, price, lots, profit, rsi_value, atr_value, timestamp, status FROM trades WHERE status='OPEN'")
for r in cur.fetchall():
    print(f"  {r}")

print("\n=== MAX DD IN LAST 24H ===")
cur.execute("SELECT MAX(drawdown_pct), MAX((balance-equity)/balance*100) FROM account_snapshots WHERE timestamp >= datetime('now', '-24 hours')")
print(cur.fetchone())

print("\n=== BALANCE HISTORY (HOURLY, LAST 24H) ===")
cur.execute("""
    SELECT strftime('%Y-%m-%d %H:00', timestamp) as hr,
           MIN(balance), MAX(balance), MIN(equity), MAX(equity),
           MAX(drawdown_pct)
    FROM account_snapshots
    WHERE timestamp >= datetime('now', '-24 hours')
    GROUP BY hr ORDER BY hr
""")
for r in cur.fetchall(): print(f"  {r}")

conn.close()
