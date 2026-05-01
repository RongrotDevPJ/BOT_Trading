"""
weekly_report.py — Phase A Analytics Report
==========================================
Queries the last 30 days of closed trades from SQLite and sends
a performance summary to Telegram.

Run manually:  python scripts/tools/weekly_report.py
Schedule via Windows Task Scheduler (weekly, e.g. every Sunday 08:00).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sqlite3
from datetime import datetime, timedelta
from contextlib import closing

# ── Config ──────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).resolve().parents[2] / "data" / "db" / "trading_data.db"
LOOKBACK_DAYS = 30
SYMBOLS = ["AUDNZD", "EURGBP", "EURUSD", "XAUUSD"]

# ── Helpers ──────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def query_symbol_stats(conn, symbol, since_str):
    """Return closed-trade stats for a symbol in the lookback window."""
    sql = """
    SELECT
        COUNT(*)                                        AS total,
        SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END)    AS wins,
        SUM(CASE WHEN profit <= 0 THEN 1 ELSE 0 END)   AS losses,
        SUM(profit)                                     AS net_profit,
        AVG(CASE WHEN profit > 0 THEN profit END)       AS avg_win,
        AVG(CASE WHEN profit <= 0 THEN ABS(profit) END) AS avg_loss,
        AVG(hold_time_sec)                              AS avg_hold_sec,
        AVG(mae)                                        AS avg_mae_pts,
        AVG(mfe)                                        AS avg_mfe_pts,
        AVG(spread_at_entry)                            AS avg_spread,
        MAX(grid_level)                                 AS max_grid_level,
        AVG(atr_value)                                  AS avg_atr
    FROM trades
    WHERE symbol = ?
      AND status = 'CLOSED'
      AND timestamp >= ?
    """
    with closing(conn.cursor()) as cur:
        cur.execute(sql, (symbol, since_str))
        return cur.fetchone()

def query_rsi_buckets(conn, symbol, since_str):
    """Win rate by RSI bucket — identifies optimal entry RSI range."""
    sql = """
    SELECT
        CAST(rsi_value / 5 AS INTEGER) * 5     AS rsi_bucket,
        COUNT(*)                                AS trades,
        SUM(CASE WHEN profit > 0 THEN 1 END)   AS wins,
        ROUND(AVG(profit), 4)                   AS avg_pnl
    FROM trades
    WHERE symbol = ?
      AND status = 'CLOSED'
      AND rsi_value IS NOT NULL
      AND timestamp >= ?
    GROUP BY rsi_bucket
    ORDER BY rsi_bucket
    """
    with closing(conn.cursor()) as cur:
        cur.execute(sql, (symbol, since_str))
        return cur.fetchall()

def query_grid_level_perf(conn, symbol, since_str):
    """Profit by grid level — shows which averaging depth is most profitable."""
    sql = """
    SELECT
        grid_level,
        COUNT(*)                                AS trades,
        ROUND(SUM(profit), 4)                   AS total_pnl,
        ROUND(AVG(hold_time_sec) / 60.0, 1)    AS avg_hold_min
    FROM trades
    WHERE symbol = ?
      AND status = 'CLOSED'
      AND grid_level IS NOT NULL
      AND timestamp >= ?
    GROUP BY grid_level
    ORDER BY grid_level
    """
    with closing(conn.cursor()) as cur:
        cur.execute(sql, (symbol, since_str))
        return cur.fetchall()

# ── Report Builder ─────────────────────────────────────────────────────────
def build_report():
    since = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    lines = []
    lines.append(f"📊 <b>BOT_Trading — {LOOKBACK_DAYS}-Day Performance Report</b>")
    lines.append(f"Period: {since} → {datetime.now().strftime('%Y-%m-%d')}\n")

    try:
        conn = get_conn()
    except Exception as e:
        return f"[ERROR] Cannot connect to DB: {e}"

    total_net = 0.0

    for sym in SYMBOLS:
        row = query_symbol_stats(conn, sym, since)
        if not row or row["total"] == 0:
            lines.append(f"── {sym}: No closed trades ──\n")
            continue

        total    = row["total"]
        wins     = row["wins"] or 0
        losses   = row["losses"] or 0
        net      = row["net_profit"] or 0.0
        avg_win  = row["avg_win"] or 0.0
        avg_loss = row["avg_loss"] or 0.0
        hold_min = (row["avg_hold_sec"] or 0) / 60
        mae_pts  = row["avg_mae_pts"] or 0.0
        mfe_pts  = row["avg_mfe_pts"] or 0.0
        spread   = row["avg_spread"] or 0.0
        max_grid = row["max_grid_level"] or 0

        win_rate = wins / total if total > 0 else 0
        pf = (wins * avg_win) / (losses * avg_loss) if losses > 0 and avg_loss > 0 else float('inf')
        kelly = win_rate - (1 - win_rate) / (avg_win / avg_loss) if avg_win > 0 and avg_loss > 0 else 0

        total_net += net

        lines.append(f"<b>── {sym} ──</b>")
        lines.append(f"  Trades: {total} | Wins: {wins} | Losses: {losses}")
        lines.append(f"  Win Rate: {win_rate:.1%} | Profit Factor: {pf:.2f}")
        lines.append(f"  Net PnL: ${net:.2f} | Kelly: {kelly:.1%}")
        lines.append(f"  Avg Win: ${avg_win:.2f} | Avg Loss: ${avg_loss:.2f}")
        lines.append(f"  Avg Hold: {hold_min:.0f} min | Max Grid: L{max_grid}")
        lines.append(f"  Avg MAE: {mae_pts:.1f}pts | Avg MFE: {mfe_pts:.1f}pts")
        lines.append(f"  Avg Spread @ Entry: {spread:.1f}pts")

        # RSI buckets
        rsi_rows = query_rsi_buckets(conn, sym, since)
        if rsi_rows:
            best = max(rsi_rows, key=lambda r: (r["wins"] or 0) / max(r["trades"], 1))
            lines.append(f"  Best RSI bucket: {best['rsi_bucket']}-{best['rsi_bucket']+5}"
                         f" (WR={( (best['wins'] or 0)/best['trades']):.0%}, n={best['trades']})")

        # Grid level performance
        grid_rows = query_grid_level_perf(conn, sym, since)
        if grid_rows:
            best_g = max(grid_rows, key=lambda r: r["total_pnl"] or -9999)
            lines.append(f"  Most profitable grid level: L{best_g['grid_level']}"
                         f" (PnL=${best_g['total_pnl']:.2f}, n={best_g['trades']})")

        lines.append("")

    lines.append(f"<b>Total Net PnL (all bots): ${total_net:.2f}</b>")
    conn.close()
    return "\n".join(lines)

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    report = build_report()
    print(report)

    # Send to Telegram
    try:
        from core.telegram_notifier import send_telegram_message
        send_telegram_message(report)
        print("\n[OK] Report sent to Telegram.")
    except Exception as e:
        print(f"\n[WARN] Telegram send failed: {e}")
        print("[INFO] Report printed above — copy manually if needed.")
