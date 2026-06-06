"""
simulation/sim_db.py
SQLite database for storing simulation results.
Separate from the live bot DB — no writes to trading_data.db.
"""

import sqlite3
from typing import List, Dict, Optional, Any
import queue
import threading
import logging
import time
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("SimDB")


CREATE_TABLES = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS sim_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy        TEXT NOT NULL,        -- 'SMC' or 'ML'
    symbol          TEXT NOT NULL DEFAULT 'XAUUSD',
    side            TEXT NOT NULL,        -- 'BUY' or 'SELL'
    open_time       TEXT NOT NULL,        -- ISO datetime
    close_time      TEXT,
    entry_price     REAL NOT NULL,
    close_price     REAL,
    sl_price        REAL,
    tp1_price       REAL,
    tp2_price       REAL,
    lot_size        REAL NOT NULL,
    gross_profit    REAL DEFAULT 0.0,
    commission      REAL DEFAULT 0.0,
    swap            REAL DEFAULT 0.0,
    net_profit      REAL DEFAULT 0.0,
    simulated_spread INTEGER DEFAULT 30,
    simulated_slippage REAL DEFAULT 0.0,
    mae_points      REAL DEFAULT 0.0,    -- Maximum Adverse Excursion
    mfe_points      REAL DEFAULT 0.0,    -- Maximum Favorable Excursion
    regime_at_entry TEXT DEFAULT 'UNKNOWN',
    ml_score        REAL DEFAULT 0.0,
    rsi_at_entry    REAL,
    atr_at_entry    REAL,
    status          TEXT DEFAULT 'OPEN', -- 'OPEN', 'CLOSED', 'STOPPED'
    close_reason    TEXT,               -- 'TP1', 'TP2', 'SL', 'TRAILING', 'MANUAL'
    balance_after   REAL,
    equity_after    REAL,
    drawdown_pct    REAL DEFAULT 0.0,
    tags            TEXT DEFAULT ''     -- JSON tags for filtering
);

CREATE TABLE IF NOT EXISTS sim_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    balance         REAL NOT NULL,
    equity          REAL NOT NULL,
    floating_pnl    REAL DEFAULT 0.0,
    open_trades     INTEGER DEFAULT 0,
    regime          TEXT DEFAULT 'UNKNOWN',
    dxy_value       REAL,
    vix_value       REAL,
    gold_sentiment  REAL,             -- -1.0 to +1.0
    cot_net_pos     INTEGER           -- Net COT positioning
);

CREATE TABLE IF NOT EXISTS sim_performance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period          TEXT NOT NULL,    -- 'hourly', 'daily', 'weekly'
    period_label    TEXT NOT NULL,    -- e.g., '2026-06-01', '2026-W22'
    strategy        TEXT NOT NULL,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    losing_trades   INTEGER DEFAULT 0,
    win_rate        REAL DEFAULT 0.0,
    gross_profit    REAL DEFAULT 0.0,
    gross_loss      REAL DEFAULT 0.0,
    net_profit      REAL DEFAULT 0.0,
    profit_factor   REAL DEFAULT 0.0,
    avg_win         REAL DEFAULT 0.0,
    avg_loss        REAL DEFAULT 0.0,
    max_drawdown    REAL DEFAULT 0.0,
    sharpe_ratio    REAL DEFAULT 0.0,
    kelly_fraction  REAL DEFAULT 0.0,
    calculated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sim_trades_strategy ON sim_trades(strategy);
CREATE INDEX IF NOT EXISTS idx_sim_trades_open ON sim_trades(open_time);
CREATE INDEX IF NOT EXISTS idx_sim_trades_status ON sim_trades(status);
CREATE INDEX IF NOT EXISTS idx_sim_snapshots_ts ON sim_snapshots(timestamp);
"""


class SimDB:
    """Async SQLite writer for simulation results. Thread-safe."""

    def __init__(self, db_path: str = "data/sim/sim_results.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(CREATE_TABLES)
        conn.commit()
        conn.close()
        logger.info(f"[SimDB] Database ready: {self.db_path}")

        # Async queue writer
        self._queue: queue.Queue = queue.Queue(maxsize=1000)
        self._worker = threading.Thread(target=self._run_worker, daemon=True, name="SimDB-Worker")
        self._worker.start()

    # ── Public Write API ───────────────────────────────────────────────────────

    def insert_trade(self, **kwargs) -> None:
        """Queue a trade insert. Non-blocking."""
        self._enqueue("INSERT_TRADE", kwargs)

    def update_trade(self, trade_id: int, **kwargs) -> None:
        """Queue a trade update. Non-blocking."""
        self._enqueue("UPDATE_TRADE", {"id": trade_id, **kwargs})

    def insert_snapshot(self, **kwargs) -> None:
        """Queue an equity snapshot. Non-blocking."""
        self._enqueue("INSERT_SNAPSHOT", kwargs)

    def upsert_performance(self, **kwargs) -> None:
        """Queue a performance record upsert. Non-blocking."""
        self._enqueue("UPSERT_PERF", kwargs)

    # ── Public Read API ────────────────────────────────────────────────────────

    def get_closed_trades(self, strategy: str = None, limit: int = 500) -> List[dict]:
        """Returns closed trades as list of dicts. Synchronous read."""
        where = "WHERE status = 'CLOSED'"
        params = []
        if strategy:
            where += " AND strategy = ?"
            params.append(strategy)
        sql = f"SELECT * FROM sim_trades {where} ORDER BY close_time DESC LIMIT ?"
        params.append(limit)
        return self._read(sql, params)

    def get_open_trades(self, strategy: str = None) -> List[dict]:
        where = "WHERE status = 'OPEN'"
        params = []
        if strategy:
            where += " AND strategy = ?"
            params.append(strategy)
        return self._read(f"SELECT * FROM sim_trades {where}", params)

    def get_balance_history(self, limit: int = 1000) -> List[dict]:
        return self._read(
            "SELECT timestamp, balance, equity, regime FROM sim_snapshots ORDER BY timestamp DESC LIMIT ?",
            [limit]
        )

    def calculate_stats(self, strategy: str) -> dict:
        """Compute live performance stats for a strategy."""
        trades = self.get_closed_trades(strategy=strategy)
        if not trades:
            return {}

        profits = [t["net_profit"] for t in trades]
        wins    = [p for p in profits if p > 0]
        losses  = [p for p in profits if p <= 0]

        win_rate = len(wins) / len(profits) if profits else 0
        avg_win  = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        pf       = sum(wins) / abs(sum(losses)) if losses else float('inf')
        kelly    = win_rate - (1 - win_rate) / (avg_win / avg_loss) if avg_loss > 0 else 0

        # Sharpe (annualized, assuming 252 trading days)
        if len(profits) >= 2:
            import math
            mean_r = sum(profits) / len(profits)
            std_r  = (sum((p - mean_r)**2 for p in profits) / (len(profits)-1)) ** 0.5
            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0
        else:
            sharpe = 0

        return {
            "strategy":      strategy,
            "total_trades":  len(profits),
            "win_rate":      round(win_rate * 100, 1),
            "profit_factor": round(pf, 2),
            "net_profit":    round(sum(profits), 2),
            "avg_win":       round(avg_win, 2),
            "avg_loss":      round(avg_loss, 2),
            "kelly":         round(kelly * 100, 2),
            "sharpe":        round(sharpe, 2),
        }

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _enqueue(self, op: str, data: dict):
        try:
            self._queue.put_nowait((op, data))
        except queue.Full:
            logger.warning("[SimDB] Queue full — dropping write task")

    def _run_worker(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        while True:
            try:
                op, data = self._queue.get(timeout=5)
                self._dispatch(conn, op, data)
                conn.commit()
            except queue.Empty:
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                conn.commit()
            except Exception as e:
                logger.error(f"[SimDB] Worker error: {e}")
                time.sleep(1)

    def _dispatch(self, conn, op: str, data: dict):
        if op == "INSERT_TRADE":
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" * len(data))
            conn.execute(
                f"INSERT INTO sim_trades ({cols}) VALUES ({placeholders})",
                list(data.values())
            )
        elif op == "UPDATE_TRADE":
            tid = data.pop("id")
            set_clause = ", ".join(f"{k} = ?" for k in data)
            conn.execute(
                f"UPDATE sim_trades SET {set_clause} WHERE id = ?",
                list(data.values()) + [tid]
            )
        elif op == "INSERT_SNAPSHOT":
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" * len(data))
            conn.execute(
                f"INSERT INTO sim_snapshots ({cols}) VALUES ({placeholders})",
                list(data.values())
            )
        elif op == "UPSERT_PERF":
            cols = ", ".join(data.keys())
            placeholders = ", ".join("?" * len(data))
            conn.execute(
                f"INSERT OR REPLACE INTO sim_performance ({cols}) VALUES ({placeholders})",
                list(data.values())
            )

    def _read(self, sql: str, params: list = None) -> List[dict]:
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(sql, params or []).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[SimDB] Read error: {e}")
            return []
