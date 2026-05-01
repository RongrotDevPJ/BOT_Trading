import sqlite3
import logging
import random
import time
import queue
import threading
from datetime import datetime
from pathlib import Path
from contextlib import closing

class DBManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        current_dir = Path(__file__).resolve().parent
        project_root = current_dir.parent
        self.db_dir = project_root / "Log_HistoryOrder"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "trading_data.db"
        
        # Initialize the database schema synchronously
        self.initialize_db()
        
        # Async Task Queue & Worker Thread
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        self.logger.info("DB Logging Worker Thread started (Daemon).")

    def get_connection(self):
        """Returns a connection to the SQLite database with row factory enabled."""
        try:
            # Multi-process safety: set timeout to 20s to wait for locks
            conn = sqlite3.connect(str(self.db_path), timeout=20)
            conn.row_factory = sqlite3.Row
            # WAL mode is critical for concurrent multi-process access
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            return conn
        except Exception as e:
            self.logger.error(f"Error connecting to database: {e}")
            return None

    def _worker(self):
        """Background worker that processes write tasks asynchronously."""
        # The worker maintains its own persistent connection for efficiency
        conn = self.get_connection()
        while True:
            task = self.task_queue.get()
            if task is None:
                self.task_queue.task_done()
                break
            
            try:
                try:
                    func_name, args, kwargs = task
                    
                    # If connection dropped, try reconnecting
                    if conn is None: conn = self.get_connection()
                    
                    if func_name == "sql_execute":
                        sql, params = args
                        with closing(conn.cursor()) as cursor:
                            cursor.execute(sql, params)
                        conn.commit()
                    elif func_name == "sync_deals":
                        self._execute_sync_deals(conn, *args)
                    elif func_name == "archive":
                        self._execute_archive(conn, *args)
                    elif func_name == "checkpoint":
                        self._execute_checkpoint(conn)

                    
                except Exception as e:
                    self.logger.error(f"Error processing DB task '{task[0]}': {e}", exc_info=True)
                    if conn: conn.rollback()
                    time.sleep(1) # Prevent rapid fire failure spam
            finally:
                self.task_queue.task_done()

        
        if conn: conn.close()

    def initialize_db(self):
        """Creates the trades table and ensures correct schema."""
        sql_create_trades_table = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            ticket INTEGER UNIQUE,
            side TEXT,
            price REAL,
            lots REAL,
            sl REAL,
            tp REAL,
            profit REAL DEFAULT 0.0,
            spread REAL,
            comment TEXT,
            status TEXT,
            mae REAL,
            mfe REAL,
            mae_usc REAL,
            mfe_usc REAL,
            atr_value REAL,
            rsi_value REAL,
            entry_signals TEXT,
            grid_level INTEGER,
            cycle_id TEXT,
            slippage REAL,
            exec_time_ms INTEGER
        );
        """
        conn = self.get_connection()
        if conn:
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(sql_create_trades_table)
                    cursor.execute("PRAGMA table_info(trades)")
                    columns = [row[1] for row in cursor.fetchall()]
                    new_cols = ['spread', 'status', 'mae', 'mfe', 'mae_usc', 'mfe_usc',
                                'atr_value', 'rsi_value', 'entry_signals', 'grid_level',
                                'cycle_id', 'slippage', 'exec_time_ms',
                                'hold_time_sec', 'spread_at_entry', 'open_time_unix']
                    for col in new_cols:
                        if col not in columns:
                            if col in ['status', 'cycle_id', 'entry_signals']:
                                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
                            elif col in ['grid_level', 'exec_time_ms', 'hold_time_sec', 'open_time_unix']:
                                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} INTEGER")
                            else:
                                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} REAL")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_timestamp ON trades(symbol, timestamp);")
                conn.commit()
                self.logger.info("Database initialized successfully.")
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error initializing database: {e}")
            finally:
                conn.close()

    def log_trade(self, action, symbol, ticket=None, side=None, price=0.0, lots=0.0, sl=0.0, tp=0.0, spread=0.0, profit=0.0, comment=""):
        """Queues a trade event record into the database."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        INSERT OR IGNORE INTO trades (timestamp, symbol, action, ticket, side, price, lots, sl, tp, spread, profit, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.task_queue.put(("sql_execute", (sql, (timestamp, symbol, action, ticket, side, price, lots, sl, tp, spread, profit, comment)), {}))

    def log_open_trade(self, ticket, symbol, side, open_price, volume, atr, rsi,
                       grid_level, cycle_id, slippage, exec_time_ms,
                       entry_signals="", comment="", spread_at_entry=0.0):
        """Queues an open trade record into the database."""
        import time as _t
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        open_time_unix = int(_t.time())
        sql = """
        INSERT OR REPLACE INTO trades
            (timestamp, symbol, action, ticket, side, price, lots,
             atr_value, rsi_value, entry_signals, grid_level, cycle_id,
             slippage, exec_time_ms, status, comment, spread_at_entry, open_time_unix)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?)
        """
        self.task_queue.put(("sql_execute", (sql, (
            timestamp, symbol, 'ENTRY', ticket, side, open_price, volume,
            atr, rsi, entry_signals, grid_level, cycle_id,
            slippage, exec_time_ms, comment, spread_at_entry, open_time_unix
        )), {}))

    def log_closed_trade_update(self, ticket, close_price, profit,
                                mfe=0.0, mae=0.0,
                                mae_pts=0.0, mfe_pts=0.0,
                                hold_time_sec=0):
        """Queues a closed trade update — now includes hold time and per-ticket excursion in points."""
        sql = """
        UPDATE trades
        SET status = 'CLOSED',
            profit = ?,
            mae_usc = ?, mfe_usc = ?,
            mae = ?, mfe = ?,
            hold_time_sec = ?,
            action = 'DEAL_OUT'
        WHERE ticket = ?
        """
        self.task_queue.put(("sql_execute", (sql, (
            profit,
            mae, mfe,
            mae_pts, mfe_pts,
            hold_time_sec,
            ticket
        )), {}))

    def sync_deals(self, deals, active_excursions=None):
        """Queues a batch sync of deals."""
        if not deals: return
        self.task_queue.put(("sync_deals", (deals, active_excursions), {}))

    def _execute_sync_deals(self, conn, deals, active_excursions):
        """Internal execution of sync_deals inside the worker thread."""
        sql_update = """
        UPDATE trades 
        SET status = 'CLOSED', profit = ?, mae = ?, mfe = ?, action = 'DEAL_OUT'
        WHERE ticket = ?
        """
        sql_insert = """
        INSERT OR IGNORE INTO trades (timestamp, symbol, action, ticket, side, price, lots, profit, comment, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
        """
        try:
            with closing(conn.cursor()) as cursor:
                for d in deals:
                    if d.entry == 1: # DEAL_OUT
                        total_pnl = d.profit + getattr(d, 'commission', 0.0) + d.swap
                        mae = 0.0
                        mfe = 0.0
                        if active_excursions and d.position_id in active_excursions:
                            # Note: We must be careful about shared state like active_excursions
                            # For now, we assume it's passed as a snapshot or safe to read
                            mae = active_excursions[d.position_id].get('mae', 0.0)
                            mfe = active_excursions[d.position_id].get('mfe', 0.0)
                        
                        cursor.execute(sql_update, (total_pnl, mae, mfe, d.position_id))
                        
                        if cursor.rowcount == 0:
                            timestamp = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
                            side = "SELL" if d.type == 0 else "BUY" 
                            cursor.execute(sql_insert, (timestamp, d.symbol, 'DEAL_OUT', d.position_id, side, d.price, d.volume, total_pnl, f"Magic:{d.magic} {d.comment}"))                            
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Error executing sync_deals: {e}")

    def get_today_summary(self, symbol=None):
        """Calculates the total realized profit for today."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        sql = "SELECT SUM(profit) as total_profit FROM trades WHERE timestamp LIKE ?"
        params = [f"{today_str}%"]
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
            
        conn = self.get_connection()
        if conn:
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(sql, params)
                    row = cursor.fetchone()
                    return row['total_profit'] if row['total_profit'] is not None else 0.0
            except Exception as e:
                self.logger.error(f"Error fetching today summary: {e}")
                return 0.0
            finally:
                conn.close()
        return 0.0

    def get_symbol_stats_30d(self, symbol):
        """
        Phase 5 – Fractional Kelly Position Sizing.

        Queries the last 30 days of CLOSED trades for `symbol` and computes
        the two inputs needed by the Kelly formula:

            Win Rate  (W)  = winning_trades / total_trades       → [0.0, 1.0]
            Risk/Reward (R) = avg_win_profit / avg_loss_abs      → > 0.0

        Returns a dict:
            {
                "win_rate":       float,   # e.g. 0.62
                "risk_reward":    float,   # e.g. 1.85
                "total_trades":   int,
                "winning_trades": int,
                "losing_trades":  int,
                "avg_win":        float,
                "avg_loss":       float,   # stored as positive number
            }

        Returns None if:
          - DB connection fails
          - Fewer than `min_trades` records exist (caller decides threshold)
          - No losing trades exist (can't calculate R; degenerate edge)
        """
        sql = """
            SELECT
                COUNT(*)                                              AS total_trades,
                SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END)          AS winning_trades,
                SUM(CASE WHEN profit < 0 THEN 1 ELSE 0 END)          AS losing_trades,
                AVG(CASE WHEN profit > 0 THEN profit ELSE NULL END)   AS avg_win,
                AVG(CASE WHEN profit < 0 THEN profit ELSE NULL END)   AS avg_loss
            FROM trades
            WHERE symbol    = ?
              AND status    = 'CLOSED'
              AND timestamp >= datetime('now', '-30 days')
        """
        conn = self.get_connection()
        if conn is None:
            self.logger.error("[KellyStats] Cannot connect to DB.")
            return None
        try:
            with closing(conn.cursor()) as cursor:
                cursor.execute(sql, (symbol,))
                row = cursor.fetchone()

            if row is None or row["total_trades"] == 0:
                self.logger.debug(f"[KellyStats] No closed trades found for {symbol} in last 30d.")
                return None

            total     = int(row["total_trades"])
            wins      = int(row["winning_trades"] or 0)
            losses    = int(row["losing_trades"]  or 0)
            avg_win   = float(row["avg_win"]  or 0.0)
            avg_loss  = float(row["avg_loss"] or 0.0)   # negative number from DB

            # Guard: need at least one win AND one loss to compute R meaningfully
            if wins == 0 or losses == 0 or avg_loss == 0.0:
                self.logger.debug(
                    f"[KellyStats] {symbol}: wins={wins}, losses={losses} — "
                    f"degenerate history, cannot compute Kelly."
                )
                return None

            win_rate    = wins / total
            avg_loss_abs = abs(avg_loss)           # convert to positive
            risk_reward  = avg_win / avg_loss_abs  # R = avg_win / avg_loss

            self.logger.debug(
                f"[KellyStats] {symbol} 30d | "
                f"Trades={total} | W={win_rate:.3f} | R={risk_reward:.3f} | "
                f"AvgWin={avg_win:.4f} | AvgLoss={avg_loss_abs:.4f}"
            )
            return {
                "win_rate":       win_rate,
                "risk_reward":    risk_reward,
                "total_trades":   total,
                "winning_trades": wins,
                "losing_trades":  losses,
                "avg_win":        avg_win,
                "avg_loss":       avg_loss_abs,
            }

        except Exception as e:
            self.logger.error(f"[KellyStats] Error querying stats for {symbol}: {e}")
            return None
        finally:
            conn.close()


    def archive_old_data(self, days=90):
        """Queues an archival task and a subsequent WAL checkpoint."""
        self.task_queue.put(("archive", (days,), {}))
        self.checkpoint_wal()


    def _execute_archive(self, conn, days):
        """Internal execution of archive_old_data inside worker."""
        try:
            with closing(conn.cursor()) as cursor:
                cursor.execute("SELECT date('now', '-' || ? || ' days')", (str(days),))
                row = cursor.fetchone()
                if not row: return
                cutoff_date = row[0]
                
                backup_db_path = self.db_path.parent / "backup_data.db"
                cursor.execute(f"ATTACH DATABASE ? AS backup", (str(backup_db_path),))
                cursor.execute("CREATE TABLE IF NOT EXISTS backup.trades AS SELECT * FROM main.trades WHERE 1=0")
                
                # Verify backup schema
                cursor.execute("PRAGMA backup.table_info(trades)")
                backup_cols = [r[1] for r in cursor.fetchall()]
                for col in ['spread', 'profit']:
                    if col not in backup_cols:
                        cursor.execute(f"ALTER TABLE backup.trades ADD COLUMN {col} REAL")

                # Move data
                cursor.execute("INSERT INTO backup.trades SELECT * FROM main.trades WHERE timestamp < ?", (f"{cutoff_date} 00:00:00",))
                rows_moved = cursor.rowcount
                if rows_moved > 0:
                    cursor.execute("DELETE FROM main.trades WHERE timestamp < ?", (f"{cutoff_date} 00:00:00",))
                    conn.commit()
                    self.logger.warning(f"[Archive] Moved {rows_moved} old records to backup.")
                else:
                    self.logger.info("[Archive] No old data found to archive.")
                
                try: cursor.execute("DETACH DATABASE backup")
                except: pass
        except Exception as e:
            conn.rollback()
            self.logger.error(f"[Archive] Error during data archiving: {e}")

    def checkpoint_wal(self):
        """Queues a WAL checkpoint task."""
        self.task_queue.put(("checkpoint", (), {}))

    def _execute_checkpoint(self, conn):
        """Internal execution of WAL checkpoint inside worker thread."""
        try:
            with closing(conn.cursor()) as cursor:
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                res = cursor.fetchone()
                if res:
                    # Result columns: busy, log, checkpointed
                    self.logger.warning(f"[DB Checkpoint] WAL Checkpointed: busy={res[0]}, log={res[1]}, checkpointed={res[2]}")
        except Exception as e:
            self.logger.error(f"[DB Checkpoint] Error during WAL checkpoint: {e}")


if __name__ == "__main__":
    db = DBManager()
    print(f"DB initialized at: {db.db_path}")
