import sqlite3
import logging
import random
import time
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
        self.initialize_db()

    def get_connection(self):
        """Returns a connection to the SQLite database with row factory enabled."""
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=20)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA journal_mode=WAL;')
            conn.execute('PRAGMA synchronous=NORMAL;')
            return conn
        except Exception as e:
            self.logger.error(f"Error connecting to database: {e}")
            return None

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
            atr_value REAL,
            rsi_value REAL,
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
                    new_cols = ['spread', 'status', 'mae', 'mfe', 'atr_value', 'rsi_value', 'grid_level', 'cycle_id', 'slippage', 'exec_time_ms']
                    for col in new_cols:
                        if col not in columns:
                            if col in ['status', 'cycle_id']:
                                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} TEXT")
                            elif col in ['grid_level', 'exec_time_ms']:
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
        """Inserts a trade event record into the database."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        INSERT OR IGNORE INTO trades (timestamp, symbol, action, ticket, side, price, lots, sl, tp, spread, profit, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn = self.get_connection()
        if conn:
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(sql, (timestamp, symbol, action, ticket, side, price, lots, sl, tp, spread, profit, comment))
                conn.commit()
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error logging trade to DB: {e}")
            finally:
                conn.close()

    def log_open_trade(self, ticket, symbol, side, open_price, volume, atr, rsi, grid_level, cycle_id, slippage, exec_time_ms, comment=""):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        INSERT OR REPLACE INTO trades (timestamp, symbol, action, ticket, side, price, lots, atr_value, rsi_value, grid_level, cycle_id, slippage, exec_time_ms, status, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
        """
        conn = self.get_connection()
        if conn:
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(sql, (timestamp, symbol, 'ENTRY', ticket, side, open_price, volume, atr, rsi, grid_level, cycle_id, slippage, exec_time_ms, comment))
                conn.commit()
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error logging open trade to DB: {e}")
            finally:
                conn.close()

    def log_closed_trade_update(self, ticket, close_price, profit, mfe, mae):
        sql = """
        UPDATE trades 
        SET status = 'CLOSED', profit = ?, mae = ?, mfe = ?, action = 'DEAL_OUT'
        WHERE ticket = ?
        """
        conn = self.get_connection()
        if conn:
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(sql, (profit, mae, mfe, ticket))
                conn.commit()
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error updating closed trade DB: {e}")
            finally:
                conn.close()

    def sync_deals(self, deals, active_excursions=None):
        """Syncs multiple MT5 history deals into the database."""
        if not deals:
            return
            
        sql_update = """
        UPDATE trades 
        SET status = 'CLOSED', profit = ?, mae = ?, mfe = ?, action = 'DEAL_OUT'
        WHERE ticket = ?
        """
        sql_insert = """
        INSERT OR IGNORE INTO trades (timestamp, symbol, action, ticket, side, price, lots, profit, comment, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
        """
        conn = self.get_connection()
        if conn:
            try:
                with closing(conn.cursor()) as cursor:
                    for d in deals:
                        if d.entry == 1: # DEAL_OUT corresponds to closing out a position
                            total_pnl = d.profit + d.commission + d.swap
                            mae = 0.0
                            mfe = 0.0
                            if active_excursions and d.position_id in active_excursions:
                                mae = active_excursions[d.position_id].get('mae', 0.0)
                                mfe = active_excursions[d.position_id].get('mfe', 0.0)
                            
                            cursor.execute(sql_update, (total_pnl, mae, mfe, d.position_id))
                            
                            if cursor.rowcount == 0:
                                timestamp = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
                                # The outgoing deal direction is the opposite of the position's true direction, but we usually log the side context.
                                side = "SELL" if d.type == 0 else "BUY" 
                                cursor.execute(sql_insert, (timestamp, d.symbol, 'DEAL_OUT', d.position_id, side, d.price, d.volume, total_pnl, f"Magic:{d.magic} {d.comment}"))                            
                conn.commit()
            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error syncing deals to DB: {e}")
            finally:
                conn.close()

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

    def archive_old_data(self, days=90):
        """Moves old records to a backup database to maintain performance."""
        time.sleep(random.uniform(0, 3)) # Jitter to avoid bot collision
        conn = self.get_connection()
        if not conn:
            return
            
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
            if conn: conn.rollback()
            self.logger.error(f"[Archive] Error during data archiving: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    db = DBManager()
    print(f"DB initialized at: {db.db_path}")
