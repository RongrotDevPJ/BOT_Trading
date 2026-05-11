import sqlite3, math, os
from datetime import datetime, timedelta

DB = r'c:\Users\lunza\Documents\VSCode Git\BOT_Trading\data\db\trading_data.db'

def run():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    symbols = ['EURUSD','EURGBP','AUDNZD','XAUUSD']

    print("=" * 70)
    print("  30-DAY PERFORMANCE ANALYTICS")
    print("=" * 70)

    for sym in symbols:
        c.execute("""
            SELECT
              COUNT(*) total,
              SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) wins,
              SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END) losses,
              AVG(CASE WHEN profit > 0 THEN profit END) avg_win,
              AVG(CASE WHEN profit < 0 THEN profit END) avg_loss,
              SUM(profit) net_pnl,
              SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END) gross_profit,
              SUM(CASE WHEN profit < 0 THEN profit ELSE 0 END) gross_loss
            FROM trades
            WHERE symbol=? AND status='CLOSED'
              AND timestamp >= datetime('now','-30 days')
        """, (sym,))
        r = c.fetchone()
        total = r['total'] or 0
        wins  = r['wins'] or 0
        losses= r['losses'] or 0
        avg_win  = r['avg_win'] or 0
        avg_loss = r['avg_loss'] or 0
        net_pnl  = r['net_pnl'] or 0
        gp = r['gross_profit'] or 0
        gl = abs(r['gross_loss'] or 0.0001)

        if total == 0:
            print(f"\n[{sym}] No closed trades in last 30 days.")
            continue

        wr = wins / total
        pf = gp / gl if gl > 0 else 0
        rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

        # Kelly
        kelly = wr - ((1 - wr) / rr) if rr > 0 else -1
        frac_kelly = max(0, kelly * 0.25)

        print(f"\n[{sym}]")
        print(f"  Trades: {total} | Wins: {wins} | Losses: {losses}")
        print(f"  Win Rate: {wr:.1%} | Profit Factor: {pf:.2f} | Avg R/R: {rr:.2f}")
        print(f"  Avg Win: {avg_win:.4f} | Avg Loss: {avg_loss:.4f} | Net PnL: {net_pnl:.4f}")
        print(f"  Kelly%: {kelly:.4f} | Frac Kelly (0.25x): {frac_kelly:.4f}")

        # Expectancy
        exp = wr * avg_win + (1 - wr) * avg_loss
        print(f"  Expectancy per trade: {exp:.4f}")

        # MAE/MFE
        c.execute("""
            SELECT AVG(mae) avg_mae, AVG(mfe) avg_mfe,
                   MIN(mae) worst_mae, MAX(mfe) best_mfe,
                   AVG(mae_usc) avg_mae_usc, AVG(mfe_usc) avg_mfe_usc
            FROM trades
            WHERE symbol=? AND status='CLOSED'
              AND timestamp >= datetime('now','-30 days')
              AND mae IS NOT NULL
        """, (sym,))
        m = c.fetchone()
        if m and m['avg_mae'] is not None:
            print(f"  MAE pts: avg={m['avg_mae']:.1f}, worst={m['worst_mae']:.1f} | MFE pts: avg={m['avg_mfe']:.1f}, best={m['best_mfe']:.1f}")
            if m['avg_mae_usc'] is not None:
                print(f"  MAE USC: avg={m['avg_mae_usc']:.4f} | MFE USC: avg={m['avg_mfe_usc']:.4f}")

        # Grid level breakdown
        c.execute("""
            SELECT grid_level, COUNT(*) cnt, AVG(profit) avg_pnl, SUM(profit) total_pnl
            FROM trades
            WHERE symbol=? AND status='CLOSED'
              AND timestamp >= datetime('now','-30 days')
              AND grid_level IS NOT NULL
            GROUP BY grid_level ORDER BY grid_level
        """, (sym,))
        glevels = c.fetchall()
        if glevels:
            print(f"  Grid Levels:")
            for g in glevels:
                print(f"    L{g['grid_level']}: {g['cnt']} trades, avgPnL={g['avg_pnl']:.4f}, totalPnL={g['total_pnl']:.4f}")

        # Hold time
        c.execute("""
            SELECT AVG(hold_time_sec) avg_h, MIN(hold_time_sec) min_h, MAX(hold_time_sec) max_h
            FROM trades WHERE symbol=? AND status='CLOSED'
              AND timestamp >= datetime('now','-30 days')
              AND hold_time_sec > 0
        """, (sym,))
        h = c.fetchone()
        if h and h['avg_h']:
            avg_h = int(h['avg_h'])
            max_h = int(h['max_h'])
            print(f"  Hold Time: avg={avg_h//3600}h{(avg_h%3600)//60}m, max={max_h//3600}h{(max_h%3600)//60}m")

        # Slippage
        c.execute("""
            SELECT AVG(slippage) avg_s, MAX(ABS(slippage)) max_s, AVG(exec_time_ms) avg_ms, MAX(exec_time_ms) max_ms
            FROM trades WHERE symbol=? AND timestamp >= datetime('now','-30 days')
              AND slippage IS NOT NULL
        """, (sym,))
        sl = c.fetchone()
        if sl and sl['avg_s'] is not None:
            print(f"  Slippage: avg={sl['avg_s']:.5f}, max={sl['max_s']:.5f} | ExecTime: avg={sl['avg_ms']:.1f}ms, max={sl['max_ms']:.1f}ms")

    # Sharpe-like approximation
    print("\n" + "=" * 70)
    print("  SHARPE / CALMAR APPROXIMATION (30-day, daily PnL basis)")
    print("=" * 70)
    for sym in symbols:
        c.execute("""
            SELECT DATE(timestamp) day, SUM(profit) daily_pnl
            FROM trades WHERE symbol=? AND status='CLOSED'
              AND timestamp >= datetime('now','-30 days')
            GROUP BY DATE(timestamp) ORDER BY day
        """, (sym,))
        rows = c.fetchall()
        if len(rows) < 5:
            print(f"  [{sym}] Insufficient daily data for Sharpe ({len(rows)} days)")
            continue
        pnls = [r['daily_pnl'] for r in rows]
        n = len(pnls)
        mean = sum(pnls) / n
        var  = sum((x - mean)**2 for x in pnls) / n
        std  = math.sqrt(var) if var > 0 else 0.0001
        sharpe = (mean / std) * math.sqrt(252) if std > 0 else 0  # annualized
        max_dd = min(pnls)
        calmar = (mean * 252) / abs(max_dd) if max_dd != 0 else 0
        print(f"  [{sym}] Days={n}, MeanDailyPnL={mean:.4f}, Std={std:.4f}, Sharpe(ann)={sharpe:.2f}, Calmar(ann)={calmar:.2f}, MaxDailyDD={max_dd:.4f}")

    conn.close()
    print("\nDONE.")

if __name__ == "__main__":
    run()
