import os
import csv
import queue
import time
from datetime import datetime
import threading
import MetaTrader5 as mt5
from core.db_manager import DBManager

class CSVLogger:
    _lock = threading.Lock()
    
    def __init__(self, symbol):
        self.symbol = symbol
        from pathlib import Path
        current_dir = Path(__file__).resolve().parent
        project_root = current_dir.parent
        self.log_dir = project_root / "data" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.log_dir / f"{self.symbol}_Analytics.csv"
        self.db_manager = DBManager()
        self._init_file()
        
        # Async Task Queue & Worker Thread
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def _worker(self):
        """Background worker that processes CSV write tasks asynchronously."""
        while True:
            row = self.task_queue.get()
            if row is None:
                self.task_queue.task_done()
                break
            
            try:
                try:
                    with open(self.filepath, mode='a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(row)
                except Exception as e:
                    print(f"CSV Worker failed to write row: {e}")
                    time.sleep(1)
            finally:
                self.task_queue.task_done()


    def _init_file(self):
        with self._lock:
            if not os.path.exists(self.filepath):
                try:
                    with open(self.filepath, mode='w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            "Timestamp", "Action", "Symbol", "Side", "Price", "Spread", 
                            "RSI", "ATR", "EMA", "GridLevel", 
                            "DistanceMoved", "RequiredDistance", "LotSize", 
                            "Drawdown_Percent", "Balance", "Equity", "Notes"
                        ])
                except Exception as e:
                    print(f"Error initializing CSV file: {e}")

    def log_event(self, action, side="", price=0.0, spread=None, rsi=None, atr=None, ema=None, 
                  grid_level=None, distance_moved=None, required_distance=None, lot_size=None, 
                  drawdown=None, balance=None, equity=None, profit=None, notes="", ticket=None):
        """Queues a logging event for both CSV and Database."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Auto-fetch internal spread if not provided for specific actions
        if spread is None and action in ["Initial Entry", "Grid Open", "Initial BUY Entry Triggered", "Initial SELL Entry Triggered"]:
            s_info = mt5.symbol_info(self.symbol)
            if s_info:
                spread = s_info.spread
        
        # Dual-Logging: CSV
        if self.filepath:
            row = [
                timestamp, action, self.symbol, side,
                f"{price:.5f}" if price else "",
                f"{spread}" if spread is not None else "",
                f"{rsi:.2f}" if rsi is not None else "",
                f"{atr:.5f}" if atr is not None else "",
                f"{ema:.5f}" if ema is not None else "",
                grid_level if grid_level is not None else "",
                f"{distance_moved:.1f}" if distance_moved is not None else "",
                f"{required_distance:.1f}" if required_distance is not None else "",
                f"{lot_size:.2f}" if lot_size is not None else "",
                f"{drawdown:.2f}%" if drawdown is not None else "",
                f"{balance:.2f}" if balance is not None else "",
                f"{equity:.2f}" if equity is not None else "",
                notes
            ]
            self.task_queue.put(row)
        
        # Dual-Logging: SQLite (Now also non-blocking)
        try:
            self.db_manager.log_trade(
                action=action,
                symbol=self.symbol,
                ticket=ticket,
                side=side,
                price=price if price else 0.0,
                lots=lot_size if lot_size is not None else 0.0,
                spread=spread if spread is not None else 0.0,
                profit=profit if profit is not None else 0.0,
                comment=f"{notes}"[:100]
            )
        except Exception as e:
            print(f"Error queuing log to DB (via CSVLogger): {e}")
