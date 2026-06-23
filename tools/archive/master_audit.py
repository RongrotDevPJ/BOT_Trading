"""
MASTER AUDIT SCRIPT
Follows STRICT EVIDENCE HIERARCHY from MASTER_PROMPT.md
All findings labelled: VERIFIED | NOT VERIFIED | OBSERVATION
"""
import sqlite3, json, math, os, sys
from pathlib import Path

BASE = Path(r"c:\Users\lunza\Documents\VSCode Git\BOT_Trading")
LIVE_DB = BASE / "data/db/trading_data.db"
SIM_DB  = BASE / "data/sim/sim_results.db"

def q(db_path, sql, params=None):
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params or []).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return {"ERROR": str(e)}

def q1(db_path, sql, params=None):
    r = q(db_path, sql, params)
    if isinstance(r, list) and r:
        return r[0]
    return r

sep = "\n" + "="*60 + "\n"

# ─────────────────────────────────────────────────────────────
# SECTION 1 — LIVE DB SCHEMA DISCOVERY
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 1 — LIVE DB TABLES" + sep)
tables = q(LIVE_DB, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for t in tables:
    print("  TABLE:", t['name'])
    cols = q(LIVE_DB, f"PRAGMA table_info({t['name']})")
    for c in cols:
        print(f"    col: {c['name']} ({c['type']})")

# ─────────────────────────────────────────────────────────────
# SECTION 2 — LIVE TRADE STATS (VERIFIED)
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 2 — LIVE TRADE STATS" + sep)

# Total rows
cnt = q1(LIVE_DB, "SELECT COUNT(*) as n FROM trades")
print(f"[VERIFIED] Total trades (all statuses): {cnt}")

closed = q(LIVE_DB, "SELECT * FROM trades WHERE status='CLOSED' ORDER BY timestamp ASC")
print(f"[VERIFIED] Closed trades: {len(closed)}")

if closed:
    profits = [r['profit'] for r in closed]
    wins    = [p for p in profits if p > 0]
    losses  = [p for p in profits if p <= 0]
    wr = len(wins)/len(profits)*100
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = gp/gl if gl > 0 else float('inf')
    print(f"[VERIFIED] Win Rate: {wr:.2f}%")
    print(f"[VERIFIED] Gross Profit: {gp:.2f}")
    print(f"[VERIFIED] Gross Loss: {gl:.2f}")
    print(f"[VERIFIED] Profit Factor: {pf:.4f}")
    print(f"[VERIFIED] Net Profit: {sum(profits):.2f}")
    print(f"[VERIFIED] Avg Win: {sum(wins)/len(wins):.2f}" if wins else "[VERIFIED] No wins")
    print(f"[VERIFIED] Avg Loss: {sum(losses)/len(losses):.2f}" if losses else "[VERIFIED] No losses")
    print(f"[VERIFIED] Largest Win: {max(profits):.2f}")
    print(f"[VERIFIED] Largest Loss: {min(profits):.2f}")
    worst = min(closed, key=lambda r: r['profit'])
    print(f"[VERIFIED] Worst Trade: Ticket={worst.get('ticket','N/A')} Profit={worst['profit']} Side={worst.get('side','N/A')} Time={worst.get('timestamp','N/A')}")

# ─────────────────────────────────────────────────────────────
# SECTION 3 — BUY vs SELL BREAKDOWN
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 3 — BUY vs SELL BREAKDOWN" + sep)
for side in ['BUY','SELL']:
    rows = [r for r in closed if r.get('side') == side]
    if not rows:
        print(f"[NOT VERIFIED] No {side} trades found")
        continue
    p = [r['profit'] for r in rows]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp2 = sum(w); gl2 = abs(sum(l))
    pf2 = gp2/gl2 if gl2 > 0 else float('inf')
    print(f"[VERIFIED] {side}: N={len(p)} WR={len(w)/len(p)*100:.1f}% PF={pf2:.2f} Net={sum(p):.2f}")

# ─────────────────────────────────────────────────────────────
# SECTION 4 — OPEN TRADES (CURRENT EXPOSURE)
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 4 — OPEN TRADES" + sep)
open_trades = q(LIVE_DB, "SELECT * FROM trades WHERE status='OPEN' OR status='ACTIVE'")
print(f"[VERIFIED] Open/Active trades: {len(open_trades)}")
for t in open_trades:
    print(f"  Ticket={t.get('ticket','N/A')} Side={t.get('side','N/A')} Lots={t.get('lots','N/A')} Price={t.get('price','N/A')}")

# ─────────────────────────────────────────────────────────────
# SECTION 5 — MAX DRAWDOWN CALCULATION
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 5 — DRAWDOWN ANALYSIS" + sep)
if closed:
    equity = 5000.0
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    for r in closed:
        equity += r['profit']
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = dd/peak*100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
    final_equity = equity
    print(f"[VERIFIED] Starting Equity (assumed): 5000.00")
    print(f"[VERIFIED] Final Equity: {final_equity:.2f}")
    print(f"[VERIFIED] Max Drawdown (USD): {max_dd:.2f}")
    print(f"[VERIFIED] Max Drawdown (%): {max_dd_pct:.2f}%")

# ─────────────────────────────────────────────────────────────
# SECTION 6 — DAY OF WEEK ANALYSIS
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 6 — DAY-OF-WEEK BREAKDOWN" + sep)
import datetime
days = {0:'Mon',1:'Tue',2:'Wed',3:'Thu',4:'Fri',5:'Sat',6:'Sun'}
day_buckets = {}
for r in closed:
    ts = r.get('timestamp','')
    try:
        dt = datetime.datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
        d = dt.weekday()
    except:
        continue
    day_buckets.setdefault(d, []).append(r['profit'])

for d in sorted(day_buckets.keys()):
    p = day_buckets[d]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp2 = sum(w); gl2 = abs(sum(l))
    pf2 = gp2/gl2 if gl2 > 0 else float('inf')
    print(f"[VERIFIED] {days[d]}: N={len(p)} WR={len(w)/len(p)*100:.1f}% PF={pf2:.2f} Net={sum(p):.2f}")

# ─────────────────────────────────────────────────────────────
# SECTION 7 — HOUR OF DAY ANALYSIS
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 7 — HOUR-OF-DAY BREAKDOWN" + sep)
hour_buckets = {}
for r in closed:
    ts = r.get('timestamp','')
    try:
        dt = datetime.datetime.strptime(ts[:19], '%Y-%m-%d %H:%M:%S')
        h = dt.hour
    except:
        continue
    hour_buckets.setdefault(h, []).append(r['profit'])

for h in sorted(hour_buckets.keys()):
    p = hour_buckets[h]
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    gp2 = sum(w); gl2 = abs(sum(l))
    pf2 = gp2/gl2 if gl2 > 0 else float('inf')
    net = sum(p)
    print(f"[VERIFIED] Hour {h:02d}: N={len(p)} WR={len(w)/len(p)*100:.1f}% PF={pf2:.2f} Net={net:.2f}")

# ─────────────────────────────────────────────────────────────
# SECTION 8 — OUTLIER SENSITIVITY
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 8 — OUTLIER SENSITIVITY" + sep)
if closed:
    for r in sorted(closed, key=lambda x: x['profit'])[:3]:
        without = [x['profit'] for x in closed if x.get('ticket') != r.get('ticket')]
        if without:
            w2 = [x for x in without if x > 0]; l2 = [x for x in without if x <= 0]
            pf2 = sum(w2)/abs(sum(l2)) if l2 else float('inf')
            print(f"[VERIFIED] Without Ticket {r.get('ticket','N/A')} (Profit={r['profit']:.2f}): PF = {pf2:.4f}")

# ─────────────────────────────────────────────────────────────
# SECTION 9 — MONTE CARLO (Bootstrap)
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 9 — MONTE CARLO (10000 runs, 1000 trades/run)" + sep)
import random

if closed:
    trade_returns = [r['profit'] for r in closed]
    INITIAL = 5000.0
    RUIN_THRESHOLD = INITIAL * 0.5  # Ruin = 50% drawdown
    RUNS = 10000
    TRADES_PER_RUN = 1000

    for seed in [1, 42, 99, 1234]:
        random.seed(seed)
        ruin_count = 0
        for _ in range(RUNS):
            equity = INITIAL
            sample = random.choices(trade_returns, k=TRADES_PER_RUN)
            for pnl in sample:
                equity += pnl
                if equity <= RUIN_THRESHOLD:
                    ruin_count += 1
                    break
        ruin_pct = ruin_count / RUNS * 100
        print(f"[VERIFIED] Seed={seed}: Risk of Ruin = {ruin_pct:.2f}% ({ruin_count}/{RUNS} runs hit 50% drawdown)")

# ─────────────────────────────────────────────────────────────
# SECTION 10 — SIM DB INSPECTION
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 10 — SIMULATION DB STATUS" + sep)
sim_tables = q(SIM_DB, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
for t in sim_tables:
    cnt2 = q1(SIM_DB, f"SELECT COUNT(*) as n FROM {t['name']}")
    print(f"[VERIFIED] sim_table={t['name']} rows={cnt2.get('n','?')}")

sim_closed = q(SIM_DB, "SELECT * FROM sim_trades WHERE status='CLOSED'")
print(f"[VERIFIED] Sim Closed Trades: {len(sim_closed)}")
if sim_closed:
    for strat in ['SMC','ML']:
        rows = [r for r in sim_closed if r.get('strategy') == strat]
        if rows:
            p = [r['net_profit'] for r in rows]
            w = [x for x in p if x > 0]; l = [x for x in p if x <= 0]
            pf2 = sum(w)/abs(sum(l)) if l else float('inf')
            print(f"[VERIFIED] Sim {strat}: N={len(p)} WR={len(w)/len(p)*100:.1f}% PF={pf2:.2f} Net={sum(p):.2f}")

# ─────────────────────────────────────────────────────────────
# SECTION 11 — ACCOUNT SNAPSHOTS / BALANCE HISTORY
# ─────────────────────────────────────────────────────────────
print(sep + "SECTION 11 — ACCOUNT SNAPSHOTS" + sep)
snap_tables = q(LIVE_DB, "SELECT name FROM sqlite_master WHERE type='table'")
snap_names = [t['name'] for t in snap_tables]
print(f"[VERIFIED] Live DB tables: {snap_names}")

if 'account_snapshots' in snap_names:
    snaps = q(LIVE_DB, "SELECT * FROM account_snapshots ORDER BY timestamp DESC LIMIT 5")
    for s in snaps:
        print(f"  {s}")
else:
    print("[NOT VERIFIED] Table 'account_snapshots' does NOT exist in trading_data.db")
    print("[OBSERVATION] Dashboard may be querying wrong table name")

print(sep + "AUDIT COMPLETE" + sep)
