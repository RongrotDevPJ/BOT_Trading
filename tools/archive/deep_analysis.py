import sqlite3
conn = sqlite3.connect('data/db/trading_data.db')
cur = conn.cursor()

print("=== ALL CLOSED TRADES ===")
cur.execute("SELECT id, side, status, profit, timestamp, lots, rsi_value, atr_value, grid_level FROM trades WHERE status='CLOSED' ORDER BY id DESC")
for r in cur.fetchall():
    print(r)

print("\n=== PHANTOM ROWS REMAINING ===")
cur.execute("SELECT COUNT(*) FROM trades WHERE (side='' OR side IS NULL) AND status IS NULL")
print(cur.fetchone())

print("\n=== SNAPSHOT BALANCE STATS ===")
cur.execute("SELECT MIN(balance), MAX(balance), MIN(equity), MAX(equity), COUNT(*) FROM account_snapshots")
print(cur.fetchone())

print("\n=== BALANCE JOURNEY (First 3, Last 3) ===")
cur.execute("SELECT timestamp, balance, equity, open_trades, regime FROM account_snapshots ORDER BY id ASC LIMIT 3")
for r in cur.fetchall(): print("FIRST:", r)
cur.execute("SELECT timestamp, balance, equity, open_trades, regime FROM account_snapshots ORDER BY id DESC LIMIT 3")
for r in cur.fetchall(): print("LAST:", r)

print("\n=== REGIME DISTRIBUTION ===")
cur.execute("SELECT regime, COUNT(*) as cnt FROM account_snapshots GROUP BY regime ORDER BY cnt DESC")
for r in cur.fetchall(): print(r)

print("\n=== HOURLY OPEN TRADES PATTERN ===")
cur.execute("SELECT strftime('%H', timestamp) as hr, AVG(open_trades) as avg_open FROM account_snapshots GROUP BY hr ORDER BY hr")
for r in cur.fetchall(): print(r)

conn.close()
