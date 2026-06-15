"""
tools/reset_kill_switch.py - Reset Global Kill Switch อย่างปลอดภัย
"""
import sqlite3, os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOP_FLAG_PATH = PROJECT_ROOT / "GLOBAL_STOP.lock"

print("=" * 60)
print("GLOBAL KILL SWITCH - STATUS CHECK & RESET TOOL")
print("=" * 60)

# 1. Check lock file
if STOP_FLAG_PATH.exists():
    print(f"\n[LOCK] LOCK FILE EXISTS: {STOP_FLAG_PATH}")
    content = open(STOP_FLAG_PATH, encoding='utf-8').read()
    print("Contents:\n" + content)
else:
    print("\n[OK] No lock file found - trading is active")

# 2. Check latest DB state
db_path = PROJECT_ROOT / "data" / "db" / "trading_data.db"
conn = sqlite3.connect(str(db_path), timeout=10)
cur = conn.cursor()

cur.execute("""
    SELECT timestamp, balance, equity, open_trades, drawdown_pct, floating_pnl, regime
    FROM account_snapshots ORDER BY id DESC LIMIT 1
""")
snap = cur.fetchone()
if snap:
    ts, bal, eq, open_t, dd, fpnl, regime = snap
    print(f"\nLATEST SNAPSHOT ({ts}):")
    print(f"   Balance:     {bal:.2f} USC")
    print(f"   Equity:      {eq:.2f} USC")
    print(f"   Floating:    {fpnl:+.2f} USC")
    print(f"   Open Trades: {open_t}")
    print(f"   Drawdown:    {dd:.2f}%")
    print(f"   Regime:      {regime}")

    current_dd = ((bal - eq) / bal * 100) if bal > 0 else 0
    print(f"\n   Current Calculated DD: {current_dd:.2f}%")

    if current_dd > 8.0:
        print(f"   [!!!] WARNING: DD still {current_dd:.2f}% - RISKY to reset! Wait for recovery.")
    elif current_dd > 5.0:
        print(f"   [!!] Drawdown {current_dd:.2f}% - moderate risk, reset with caution.")
    else:
        print(f"   [OK] Drawdown {current_dd:.2f}% - SAFE to reset.")

cur.execute("SELECT ticket, side, price, lots, profit FROM trades WHERE status='OPEN'")
open_trades = cur.fetchall()
print(f"\nOPEN TRADES ({len(open_trades)}):")
for t in open_trades:
    print(f"   Ticket:{t[0]} | {t[1]} | Entry:{t[2]:.2f} | Lots:{t[3]:.2f} | Profit:{t[4]:.2f}")

conn.close()

# 3. Perform Reset
print("\n" + "=" * 60)
if STOP_FLAG_PATH.exists():
    print("Removing GLOBAL_STOP.lock file...")
    STOP_FLAG_PATH.unlink()
    if not STOP_FLAG_PATH.exists():
        print("[OK] SUCCESS: Lock file removed. Bot can now resume trading.")
        print("[!] ACTION REQUIRED: Restart the bot on VPS (restart_bots.bat)")
    else:
        print("[FAIL] ERROR: Could not remove lock file!")
else:
    print("[OK] No lock file to remove - trading already active.")
print("=" * 60)
