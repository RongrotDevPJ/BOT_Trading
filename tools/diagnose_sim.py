"""
tools/diagnose_sim.py - วิเคราะห์ว่า Sim Bot ทำไมไม่ fire trades
"""
import sqlite3
import sys
import os
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print("=" * 70)
print("SIM BOT DIAGNOSIS")
print("=" * 70)

# 1. DB Summary
db = Path("data/sim/sim_results.db")
conn = sqlite3.connect(str(db), timeout=10)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM sim_trades")
total_trades = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM sim_trades WHERE status='OPEN'")
open_trades = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM sim_trades WHERE status='CLOSED'")
closed_trades = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM sim_snapshots")
total_snaps = cur.fetchone()[0]
cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM sim_snapshots")
first_snap, last_snap = cur.fetchone()

print(f"\n[1] DATABASE STATUS:")
print(f"  sim_trades total: {total_trades}")
print(f"  OPEN: {open_trades} | CLOSED: {closed_trades}")
print(f"  sim_snapshots: {total_snaps}")
print(f"  First snapshot: {first_snap}")
print(f"  Last snapshot:  {last_snap}")

# 2. The 1 existing trade
print(f"\n[2] THE ONLY TRADE EVER OPENED:")
cur.execute("SELECT * FROM sim_trades")
for r in cur.fetchall():
    print(f"  ID={r[0]} | Strategy={r[1]} | Symbol={r[2]} | Side={r[3]}")
    print(f"  OpenTime={r[4]} | CloseTime={r[5]}")
    print(f"  Entry={r[6]} | SL={r[8]} | TP1={r[9]} | TP2={r[10]}")
    print(f"  Status={r[23]} | Regime={r[20]}")
    # Analyze why it's stuck OPEN
    if r[23] == 'OPEN':
        entry = r[6]
        sl = r[8]
        tp1 = r[9]
        tp2 = r[10]
        print(f"\n  *** STUCK OPEN ANALYSIS ***")
        print(f"  This SELL opened at {entry:.2f} with TP1={tp1:.2f} TP2={tp2:.2f} SL={sl:.2f}")
        print(f"  If Gold went UP (Bull Run) = this SELL is deeply underwater")
        print(f"  Gold moved from ~4293 to ~3300+ area during this period?")
        print(f"  This phantom SELL was never closed by the sim engine.")

# 3. Snapshots - are they running? Equity stuck?
print(f"\n[3] RECENT SIM SNAPSHOTS (last 5):")
cur.execute("""
    SELECT timestamp, balance, equity, open_trades_count, regime
    FROM sim_snapshots ORDER BY id DESC LIMIT 5
""")
for r in cur.fetchall():
    print(f"  {r[0]} | Bal:{r[1]:.2f} | Eq:{r[2]:.2f} | Open:{r[3]} | Regime:{r[4]}")

# 4. Regime history
print(f"\n[4] REGIME HISTORY (is it stuck?):")
cur.execute("""
    SELECT regime, COUNT(*) FROM sim_snapshots GROUP BY regime
""")
for r in cur.fetchall():
    print(f"  {r[0]}: {r[1]} snapshots")

# 5. Diagnose the root cause
print(f"\n[5] ROOT CAUSE ANALYSIS:")
print("""
  FINDING 1: sim_trades has only 1 row = 1 trade in entire 2+ weeks
  FINDING 2: That 1 trade is STILL OPEN (SELL from Jun 8)
  FINDING 3: sim_snapshots runs every hour (407 rows = ~17 days) - engine IS running
  FINDING 4: sim_performance has 0 rows = no closed trades to calculate performance

  ROOT CAUSE = SMC Entry Logic Too Strict:
  
  The SMC strategy requires ALL of these simultaneously:
  1. trend = BULL or BEAR (not NEUTRAL)
  2. BOS confirmed (current_close > prev_swing_high for BULL)
  3. Order Block found before the BOS candle
  4. Price RETESTS the OB zone (returns to ob.low <= price <= ob.high)
  
  Problem: Gold has been in a STRONG BULL RUN since ~Apr 2026
  - Market is TRENDING UP = SMC identifies BULL trend
  - BOS fires (break of swing high)
  - OB is found
  - But price NEVER COMES BACK to retest the OB!
  - In a strong trend, price just keeps going up without retracing to OB
  
  FINDING 5: The 1 existing SELL trade was opened when regime was briefly BEAR
  That SELL is now ~100-300+ points in the red (Gold moved from 4293 to ~3300?)
  WAIT - Gold at 3300 would be DOWN, not up. Let me reconsider...
  
  Actually Gold has been oscillating. The SELL at 4293 with:
  - SL at 4300.33 (only 7 points above!)
  - TP at 4282.62 (down 10 points)
  If Gold went above 4300.33 briefly, the SL SHOULD have been hit.
  
  FINDING 6: The sim manage_positions might have a BUG:
  For SELL: if close_price >= pos.sl_price -> reason = "SL"
  But pos.sl_price = 4300.33 and Gold went to 4320+ -> should have hit SL!
  
  POSSIBLE BUG: The sim_engine.py might not be calling update() on old positions
  when it restarts, leaving them STUCK as OPEN forever.
""")

conn.close()
print("=" * 70)
