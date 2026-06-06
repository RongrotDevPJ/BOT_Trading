"""
tools/backtest.py
Vectorized backtest from live trading DB.
Reads closed trades and simulates walk-forward performance.

Usage:
    python tools/backtest.py
    python tools/backtest.py --days 30
    python tools/backtest.py --side BUY
"""

import sqlite3
import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

DB_PATH = project_root / "data" / "db" / "trading_data.db"


def load_trades(days=None, side=None):
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM trades WHERE status='CLOSED'"
    params = []
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " AND timestamp >= ?"
        params.append(cutoff)
    if side:
        sql += " AND side = ?"
        params.append(side.upper())
    sql += " ORDER BY timestamp ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calc_metrics(trades):
    if not trades:
        return {}
    profits = [t["profit"] for t in trades if t["profit"] is not None]
    wins    = [p for p in profits if p > 0]
    losses  = [p for p in profits if p <= 0]
    gross_p = sum(wins)
    gross_l = abs(sum(losses))
    net     = sum(profits)
    pf      = gross_p / gross_l if gross_l > 0 else float("inf")
    wr      = len(wins) / len(profits) * 100 if profits else 0
    avg_win = gross_p / len(wins) if wins else 0
    avg_loss = gross_l / len(losses) if losses else 0
    rr      = avg_win / avg_loss if avg_loss > 0 else float("inf")
    # Drawdown
    equity = 5000.0
    peak   = equity
    max_dd = 0.0
    for p in profits:
        equity += p
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return {
        "N": len(profits),
        "WinRate": round(wr, 2),
        "PF": round(pf, 4),
        "Net": round(net, 2),
        "GrossProfit": round(gross_p, 2),
        "GrossLoss": round(gross_l, 2),
        "AvgWin": round(avg_win, 2),
        "AvgLoss": round(avg_loss, 2),
        "RR": round(rr, 2),
        "MaxDD_pct": round(max_dd, 2),
    }


def walk_forward(trades, train_days=30, test_days=15):
    """Rolling walk-forward: train on 30d, test on next 15d."""
    if not trades:
        return []
    from collections import defaultdict
    # Parse timestamps
    for t in trades:
        t["_dt"] = datetime.strptime(t["timestamp"][:19], "%Y-%m-%d %H:%M:%S")
    start = trades[0]["_dt"]
    end   = trades[-1]["_dt"]
    results = []
    window_start = start
    while window_start + timedelta(days=train_days + test_days) <= end:
        train_end  = window_start + timedelta(days=train_days)
        test_end   = train_end + timedelta(days=test_days)
        train_set  = [t for t in trades if window_start <= t["_dt"] < train_end]
        test_set   = [t for t in trades if train_end <= t["_dt"] < test_end]
        train_m    = calc_metrics(train_set)
        test_m     = calc_metrics(test_set)
        results.append({
            "period": f"{train_end.strftime('%Y-%m-%d')} → {test_end.strftime('%Y-%m-%d')}",
            "train_N": train_m.get("N", 0),
            "train_PF": train_m.get("PF", 0),
            "test_N": test_m.get("N", 0),
            "test_PF": test_m.get("PF", 0),
            "test_Net": test_m.get("Net", 0),
        })
        window_start += timedelta(days=test_days)
    return results


def optimize_rsi(trades):
    """
    Grid search over RSI_BUY_LEVEL to find optimal entry threshold.
    Simulates: 'only take trades where rsi_value <= threshold'
    Tests RSI levels 20 to 50 in steps of 5.
    """
    if not trades:
        print("No trades to optimize.")
        return

    print(f"\n{'[ RSI BUY LEVEL OPTIMIZATION ]':=^60}")
    print(f"  {'RSI_BUY':>8} | {'N':>5} | {'WR%':>7} | {'PF':>7} | {'Net':>10} | {'MaxDD%':>8}")
    print("  " + "-"*58)

    best_pf = -1
    best_rsi = None
    buy_trades = [t for t in trades if t.get('side') == 'BUY']

    for threshold in range(20, 55, 5):
        # Simulate: only take BUY trades where RSI was <= threshold at entry
        filtered = [
            t for t in buy_trades
            if t.get('rsi_value') is not None and float(t['rsi_value']) <= threshold
        ]
        if len(filtered) < 5:
            print(f"  RSI<={threshold:>3}  | {'<5':>5} | {'N/A':>7} | {'N/A':>7} | {'N/A':>10} | {'N/A':>8}")
            continue
        m = calc_metrics(filtered)
        flag = " <-- BEST" if m['PF'] > best_pf else ""
        if m['PF'] > best_pf:
            best_pf = m['PF']
            best_rsi = threshold
        print(
            f"  RSI<={threshold:>3}  | {m['N']:>5} | {m['WinRate']:>6.1f}% | "
            f"{m['PF']:>7.4f} | {m['Net']:>+10.2f} | {m['MaxDD_pct']:>7.1f}%{flag}"
        )

    print(f"\n  [OK] Optimal RSI_BUY_LEVEL = {best_rsi} (PF={best_pf:.4f})")
    print(f"  Current config: RSI_BUY_LEVEL=35 (check configs/XAUUSD_LIVE.py)")
    print("=" * 60)
    return best_rsi


def optimize_grid_distance(trades):
    """
    Simulates different grid distance assumptions by grouping consecutive
    trades by cycle_id (same cycle = same basket).
    Shows performance by number of grid levels used.
    """
    if not trades:
        return
    print(f"\n{'[ GRID DEPTH ANALYSIS ]':=^60}")
    from collections import defaultdict
    # Group by cycle_id
    cycles = defaultdict(list)
    for t in trades:
        cid = t.get('cycle_id') or 'unknown'
        cycles[cid].append(t)

    depth_stats = defaultdict(list)
    for cid, ctrades in cycles.items():
        depth = len(ctrades)
        net = sum(t['profit'] for t in ctrades if t['profit'] is not None)
        depth_stats[depth].append(net)

    print(f"  {'Depth':>6} | {'N Cycles':>9} | {'Avg Net':>10} | {'Total Net':>11} | {'Win%':>7}")
    print("  " + "-"*52)
    for depth in sorted(depth_stats.keys()):
        nets = depth_stats[depth]
        wins = sum(1 for n in nets if n > 0)
        print(
            f"  Depth={depth:>2} | {len(nets):>9} | "
            f"{sum(nets)/len(nets):>+10.2f} | "
            f"{sum(nets):>+11.2f} | "
            f"{wins/len(nets)*100:>6.1f}%"
        )
    print("=" * 60)


def print_separator(char="=", width=60):
    print(char * width)

def main():
    parser = argparse.ArgumentParser(description="Vectorized Backtest from DB")
    parser.add_argument("--days",  type=int, default=None, help="Last N days only")
    parser.add_argument("--side",  type=str, default=None, help="BUY or SELL only")
    parser.add_argument("--wf",    action="store_true", help="Run Walk-Forward analysis")
    parser.add_argument("--optimize", action="store_true", help="Run RSI + Grid optimization")
    args = parser.parse_args()

    print_separator()
    print("XAUUSD BOT — VECTORIZED BACKTEST REPORT")
    print(f"DB: {DB_PATH}")
    print_separator()

    trades = load_trades(days=args.days, side=args.side)
    if not trades:
        print("No closed trades found.")
        return

    # Overall
    m = calc_metrics(trades)
    print(f"\n{'[ OVERALL ]':=^60}")
    for k, v in m.items():
        print(f"  {k:<20}: {v}")

    # BUY vs SELL breakdown
    for side in ["BUY", "SELL"]:
        sub = [t for t in trades if t.get("side") == side]
        sm = calc_metrics(sub)
        print(f"\n{'[ ' + side + ' ]':=^60}")
        for k, v in sm.items():
            print(f"  {k:<20}: {v}")

    # Day-of-week
    print(f"\n{'[ DAY OF WEEK ]':=^60}")
    days_map = {0:"Mon",1:"Tue",2:"Wed",3:"Thu",4:"Fri",5:"Sat",6:"Sun"}
    from collections import defaultdict
    by_day = defaultdict(list)
    for t in trades:
        dt = datetime.strptime(t["timestamp"][:19], "%Y-%m-%d %H:%M:%S")
        by_day[dt.weekday()].append(t)
    for d in sorted(by_day.keys()):
        dm = calc_metrics(by_day[d])
        print(f"  {days_map[d]}: N={dm['N']} WR={dm['WinRate']}% PF={dm['PF']} Net={dm['Net']}")

    # Walk-Forward
    if args.wf:
        print(f"\n{'[ WALK-FORWARD (30d train / 15d test) ]':=^60}")
        wf = walk_forward(trades)
        if not wf:
            print("  Not enough data for walk-forward (need 45+ days of trades).")
        for r in wf:
            print(f"  {r['period']} | Train: N={r['train_N']} PF={r['train_PF']} | Test: N={r['test_N']} PF={r['test_PF']} Net={r['test_Net']}")

    if args.optimize:
        optimize_rsi(trades)
        optimize_grid_distance(trades)

    print_separator()
    print("Backtest complete.")


if __name__ == "__main__":
    main()
