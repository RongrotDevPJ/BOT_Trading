import sqlite3
import os
import logging
from datetime import datetime
from pathlib import Path

class DBManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Get the root directory of the project (BOT_Trading)
        # __file__ is BOT_Trading\shared_utils\db_manager.py
        current_dir = Path(__file__).resolve().parent
        project_root = current_dir.parent
        self.db_dir = project_root / "Log_HistoryOrder"
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / "trading_data.db"
        self.initialize_db()

    def get_connection(self):
        """Returns a connection to the SQLite database with row factory enabled."""
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            self.logger.error(f"Error connecting to database: {e}")
            return None

    def initialize_db(self):
        """Creates the trades table if it doesn't exist."""
        sql_create_trades_table = """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL, -- Initial Entry, Grid Open, Close
            ticket INTEGER UNIQUE, -- MT5 Ticket ID
            side TEXT,            -- BUY, SELL
            price REAL,
            lots REAL,
            sl REAL,
            tp REAL,
            profit REAL DEFAULT 0.0,
            comment TEXT
        );
        """
        conn = self.get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(sql_create_trades_table)
                # Add Index for performance
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_symbol_timestamp ON trades(symbol, timestamp);")
                self.logger.info("Database initialized with indexes successfully.")
            except Exception as e:
                self.logger.error(f"Error initializing database table: {e}")
            finally:
                conn.close()

    def log_trade(self, action, symbol, ticket=None, side=None, price=0.0, lots=0.0, sl=0.0, tp=0.0, profit=0.0, comment=""):
        """Inserts a trade event record into the database."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        INSERT OR IGNORE INTO trades (timestamp, symbol, action, ticket, side, price, lots, sl, tp, profit, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn = self.get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(sql, (timestamp, symbol, action, ticket, side, price, lots, sl, tp, profit, comment))
                conn.commit()
            except Exception as e:
                self.logger.error(f"Error logging trade to DB: {e}")
            finally:
                conn.close()

    def sync_deals(self, deals):
        """Syncs multiple MT5 history deals into the database."""
        if not deals:
            return
            
        sql = """
        INSERT OR IGNORE INTO trades (timestamp, symbol, action, ticket, side, price, lots, profit, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        conn = self.get_connection()
        if conn:
            try:
                cursor = conn.cursor()
                for d in deals:
                    # action 0 = BUY, 1 = SELL (for entry)
                    # BUT history deals contain entry and exit deals. 
                    # We only care about deals with profit (exit deals) OR entry deals to track tickets.
                    # For now, let's log all deals as they appear in history for maximum data.
                    timestamp = datetime.fromtimestamp(d.time).strftime("%Y-%m-%d %H:%M:%S")
                    side = "BUY" if d.type == 0 else "SELL"
                    # entry 0 = IN, 1 = OUT, 2 = IN/OUT
                    action = "DEAL_IN" if d.entry == 0 else "DEAL_OUT"
                    total_pnl = d.profit + d.commission + d.swap
                    
                    cursor.execute(sql, (
                        timestamp, 
                        d.symbol, 
                        action, 
                        d.ticket, 
                        side, 
                        d.price, 
                        d.volume, 
                        total_pnl, 
                        f"Magic:{d.magic} {d.comment}"
                    ))
                conn.commit()
            except Exception as e:
                self.logger.error(f"Error syncing deals to DB: {e}")
            finally:
                conn.close()

    def get_today_summary(self, symbol=None):
        """
        Calculates the total realized profit for today.
        If symbol is provided, filters for that specific symbol.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        sql = "SELECT SUM(profit) as total_profit FROM trades WHERE timestamp LIKE ?"
        params = [f"{today_str}%"]
        
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
            
        conn = self.get_connection()
        if conn:
            try:
                cursor = conn.cursor()
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
        """
        Moves records older than 'days' to a backup database to keep the main DB fast.
        """
        conn = self.get_connection()
        if not conn:
            return
            
        try:
            cursor = conn.cursor()
            # Calculate cutoff date
            cursor.execute(f"SELECT date('now', '-{days} days')")
            cutoff_date = cursor.fetchone()[0]
            
            backup_db_path = self.db_dir / "backup_data.db"
            
            self.logger.info(f"Archiving data older than {cutoff_date} to {backup_db_path.name}...")
            
            # Attach backup database
            cursor.execute(f"ATTACH DATABASE '{str(backup_db_path)}' AS backup")
            
            # Create table in backup if not exists
            cursor.execute("CREATE TABLE IF NOT EXISTS backup.trades AS SELECT * FROM main.trades WHERE 1=0")
            
            # Move data
            cursor.execute("INSERT INTO backup.trades SELECT * FROM main.trades WHERE timestamp < ?", (f"{cutoff_date}%",))
            rows_moved = cursor.rowcount
            
            if rows_moved > 0:
                cursor.execute("DELETE FROM main.trades WHERE timestamp < ?", (f"{cutoff_date}%",))
                conn.commit()
                self.logger.warning(f"Successfully archived {rows_moved} old records.")
            else:
                self.logger.info("No old data found to archive.")
                
            cursor.execute("DETACH DATABASE backup")
            
        except Exception as e:
            self.logger.error(f"Error during data archiving: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    # Test DB
    db = DBManager()
    db.log_trade("TEST", "XAUUSD", "BUY", 2000.50, 0.1, 1990.0, 2020.0, 10.5, "Unit Test")
    print(f"Today Profit: {db.get_today_summary()}")
