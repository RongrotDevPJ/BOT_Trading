"""
tools/dd_analysis.py - วิเคราะห์ว่าอะไรทำให้ DD แตะ 10% เมื่อ 15/6/2026 12:45
"""
import sqlite3
from pathlib import Path
from datetime import datetime

db_path = Path("data/db/trading_data.db")
conn = sqlite3.connect(str(db_path), timeout=10)
cur = conn.cursor()

print("=" * 60)
print("DRAWDOWN EVENT ANALYSIS - 2026-06-15 12:45")
print("=" * 60)

# 1. Balance just BEFORE the event
print("\n[1] BALANCE HISTORY AROUND THE DD EVENT:")
cur.execute("""
    SELECT timestamp, balance, equity, open_trades, drawdown_pct, floating_pnl
    FROM account_snapshots
    WHERE timestamp BETWEEN '2026-06-15 11:00' AND '2026-06-15 13:00'
    ORDER BY timestamp
""")
for r in cur.fetchall():
    ts, bal, eq, open_t, dd, fpnl = r
    calc_dd = ((bal - eq) / bal * 100) if bal > 0 else 0
    flag = " <-- MAX DD" if calc_dd >= 9.5 else ""
    print(f"  {ts} | Bal:{bal:.2f} | Eq:{eq:.2f} | DD:{calc_dd:.2f}% | Open:{open_t} | Floating:{fpnl:+.2f}{flag}")

# 2. ALL trades - timing and profit
print("\n[2] ALL TRADES (chronological):")
cur.execute("""
    SELECT id, ticket, side, price, lots, profit, status,
           rsi_value, atr_value, grid_level, timestamp
    FROM trades
    ORDER BY id
""")
for r in cur.fetchall():
    print(f"  {r}")

# 3. What was the max single-trade loss?
cur.execute("""
    SELECT ticket, side, price, lots, profit, status, timestamp, grid_level
    FROM trades
    WHERE profit < 0
    ORDER BY profit ASC
""")
losses = cur.fetchall()
print(f"\n[3] LOSING TRADES ({len(losses)}):")
for r in losses:
    print(f"  {r}")

# 4. Was there a Grid cascade? Check by timestamp
print("\n[4] TRADES OPENED ON 2026-06-15:")
cur.execute("""
    SELECT ticket, side, price, lots, profit, status, grid_level, timestamp
    FROM trades
    WHERE DATE(timestamp) = '2026-06-15'
    ORDER BY timestamp
""")
for r in cur.fetchall():
    print(f"  {r}")

# 5. Balance start of day
cur.execute("""
    SELECT balance FROM account_snapshots
    WHERE DATE(timestamp) = '2026-06-15'
    ORDER BY timestamp ASC LIMIT 1
""")
r = cur.fetchone()
if r:
    start_bal = r[0]
    print(f"\n[5] START OF DAY BALANCE (15/6): {start_bal:.2f} USC")
    print(f"    10% DD threshold was:         {start_bal * 0.90:.2f} USC (equity below this = trigger)")

conn.close()
print("\n" + "=" * 60)
