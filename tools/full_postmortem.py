"""
tools/full_postmortem.py - วิเคราะห์ผลรวมทุกสัปดาห์
"""
import sqlite3
from pathlib import Path

db = Path("data/db/trading_data.db")
conn = sqlite3.connect(str(db), timeout=10)
cur = conn.cursor()

print("=" * 70)
print("FULL POSTMORTEM ANALYSIS - BOT_Trading XAUUSD")
print("=" * 70)

# 1. All trades with full detail
print("\n[1] ALL TRADES (Full Detail):")
cur.execute("""
    SELECT id, ticket, side, price, lots, profit, status,
           rsi_value, atr_value, grid_level, timestamp,
           open_time_unix, hold_time_sec
    FROM trades ORDER BY id
""")
trades = cur.fetchall()
net_total = 0
for t in trades:
    net_total += (t[5] or 0)
    hold = f"{t[12]//3600}h{(t[12]%3600)//60}m" if t[12] else "?"
    print(f"  #{t[0]} | Ticket:{t[1]} | {t[2]} | Entry:{t[3]:.2f} | Lots:{t[4]:.2f} "
          f"| Profit:{t[5]:+.2f} | Status:{t[6]} | RSI:{t[7]:.1f} | "
          f"Grid:{t[9]} | Hold:{hold} | {t[10]}")
print(f"  NET TOTAL: {net_total:+.2f} USC")

# 2. Balance journey (weekly)
print("\n[2] WEEKLY BALANCE JOURNEY:")
cur.execute("""
    SELECT strftime('%Y-W%W', timestamp) as week,
           MIN(timestamp), MAX(timestamp),
           MIN(balance), MAX(balance),
           MAX((balance-equity)/balance*100) as max_dd,
           AVG(open_trades) as avg_open
    FROM account_snapshots
    GROUP BY week ORDER BY week
""")
for r in cur.fetchall():
    print(f"  Week {r[0]}: {r[1][:10]} to {r[2][:10]} | "
          f"Balance: {r[3]:.2f}->{r[4]:.2f} | MaxDD:{r[5]:.2f}% | AvgOpen:{r[6]:.2f}")

# 3. Critical: the big losing trade analysis
print("\n[3] LOSING TRADE DEEP DIVE:")
cur.execute("""
    SELECT id, ticket, side, price, lots, profit, rsi_value, timestamp,
           open_time_unix, hold_time_sec, spread_at_entry
    FROM trades WHERE profit < 0 ORDER BY profit ASC
""")
for t in cur.fetchall():
    hold_h = (t[9] or 0) / 3600
    print(f"  Ticket:{t[1]} | Entry:{t[3]:.2f} | Profit:{t[5]:+.2f} USC | "
          f"RSI:{t[6]:.1f} | Hold:{hold_h:.1f}h | Spread@Entry:{t[10]}")

# 4. Kill switch events from snapshots
print("\n[4] DD SPIKE EVENTS (DD > 7%):")
cur.execute("""
    SELECT timestamp, balance, equity, drawdown_pct, open_trades, floating_pnl
    FROM account_snapshots
    WHERE drawdown_pct > 7.0
    ORDER BY timestamp
""")
spikes = cur.fetchall()
for r in spikes:
    print(f"  {r[0]} | Bal:{r[1]:.2f} | Eq:{r[2]:.2f} | DD:{r[3]:.2f}% | Open:{r[4]} | Float:{r[5]:+.2f}")
if not spikes:
    print("  None found")

# 5. Regime stuck at RANGING?
print("\n[5] REGIME DISTRIBUTION (ALL TIME):")
cur.execute("SELECT regime, COUNT(*) FROM account_snapshots GROUP BY regime ORDER BY COUNT(*) DESC")
total = 0
regimes = cur.fetchall()
for r in regimes:
    total += r[1]
for r in regimes:
    pct = r[1]/total*100 if total > 0 else 0
    print(f"  {r[0]}: {r[1]} snapshots ({pct:.1f}%)")

# 6. Net PnL calculation
print("\n[6] PERFORMANCE SUMMARY:")
cur.execute("SELECT COUNT(*), SUM(profit), SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END) FROM trades WHERE status='CLOSED'")
n, net, wins = cur.fetchone()
n = n or 0; net = net or 0; wins = wins or 0
cur.execute("SELECT balance, equity FROM account_snapshots ORDER BY id ASC LIMIT 1")
first = cur.fetchone()
cur.execute("SELECT balance, equity FROM account_snapshots ORDER BY id DESC LIMIT 1")
last = cur.fetchone()
start_bal = first[0] if first else 0
end_bal = last[0] if last else 0
print(f"  Closed Trades: {n} | WR: {wins/n*100:.1f}% | Net PnL: {net:+.2f} USC")
print(f"  Start Balance: {start_bal:.2f} USC")
print(f"  End Balance:   {end_bal:.2f} USC")
print(f"  Balance Change: {end_bal-start_bal:+.2f} USC ({(end_bal-start_bal)/start_bal*100:+.2f}%)")

conn.close()
print("\n" + "=" * 70)
