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
SYMBOLS = ["XAUUSD"]

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
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    try:
        conn = get_conn()
    except Exception as e:
        return f"[ERROR] Cannot connect to DB: {e}"

    stats_list = []
    total_net = 0.0
    total_cycles = 0
    total_wins = 0

    for sym in SYMBOLS:
        row = query_symbol_stats(conn, sym, since)
        if not row or row["total"] == 0:
            continue
            
        net = row["net_profit"] or 0.0
        cycles = row["total"] or 0
        wins = row["wins"] or 0
        
        total_net += net
        total_cycles += cycles
        total_wins += wins
        
        stats_list.append({
            "symbol": sym,
            "net": net,
            "cycles": cycles
        })
        
    conn.close()

    # Sort by profit (highest first)
    stats_list.sort(key=lambda x: x["net"], reverse=True)

    lines = []
    lines.append(f"📈 <b>Weekly Report — BOT_Trading</b>")
    lines.append(f"Period: {since} → {end_date}")
    lines.append("─────────────────────────────")
    
    medals = ["🥇", "🥈", "🥉", "🏅"]
    for i, stat in enumerate(stats_list):
        medal = medals[i] if i < len(medals) else "🔹"
        sym_padded = stat["symbol"].ljust(8)
        lines.append(f"{medal} {sym_padded} {stat['net']:+7.2f}  ({stat['cycles']} cycles)")
        
    if not stats_list:
        lines.append("No closed trades in this period.")

    lines.append("─────────────────────────────")
    lines.append(f"<b>Total P&L:</b> {total_net:+.2f} USC")
    
    overall_win_rate = (total_wins / total_cycles) if total_cycles > 0 else 0
    lines.append(f"<b>Win Rate:</b>  {overall_win_rate:.0%} ({total_wins}/{total_cycles} cycles)")
    
    return "\n".join(lines)

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    report = build_report()
    print(report)

    # Send to Telegram
    try:
        from core.notifier import send_telegram_message
        send_telegram_message(report)
        print("\n[OK] Report sent to Telegram.")
    except Exception as e:
        print(f"\n[WARN] Telegram send failed: {e}")
        print("[INFO] Report printed above — copy manually if needed.")
