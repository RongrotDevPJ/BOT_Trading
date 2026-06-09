import sqlite3
from pathlib import Path

db = Path("data/db/trading_data.db")
print(f"DB size: {db.stat().st_size:,} bytes")
conn = sqlite3.connect(str(db))
cur = conn.cursor()

print("\n=== TABLES ===")
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print(cur.fetchall())

print("\n=== TRADES by STATUS ===")
cur.execute("SELECT status, COUNT(*) FROM trades GROUP BY status")
print(cur.fetchall())

print("\n=== LATEST 10 TRADES ===")
cur.execute("SELECT id, side, status, profit, timestamp, lots FROM trades ORDER BY id DESC LIMIT 10")
for row in cur.fetchall():
    print(row)

print("\n=== ACCOUNT SNAPSHOTS ===")
cur.execute("SELECT COUNT(*) FROM account_snapshots")
r = cur.fetchone()
print(f"Total snapshots: {r[0]}")
cur.execute("SELECT timestamp, balance, equity, open_trades, regime FROM account_snapshots ORDER BY id DESC LIMIT 3")
for row in cur.fetchall():
    print(row)

conn.close()
