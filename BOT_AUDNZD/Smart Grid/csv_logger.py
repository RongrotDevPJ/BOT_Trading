import os
import csv
from datetime import datetime
import threading

class CSVLogger:
    _lock = threading.Lock()
    
    def __init__(self, symbol):
        self.symbol = symbol
        # Get the root directory of the project (BOT_Trading)
        # __file__ is BOT_Trading\BOT_AUDNZD\Smart Grid\csv_logger.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
        self.log_dir = os.path.join(project_root, "Log_HistoryOrder", "Analytics_Data")
        os.makedirs(self.log_dir, exist_ok=True)
        self.filepath = os.path.join(self.log_dir, f"{self.symbol}_Analytics.csv")
        self._init_file()

    def _init_file(self):
        with self._lock:
            if not os.path.exists(self.filepath):
                try:
                    with open(self.filepath, mode='w', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow([
                            "Timestamp", "Action", "Symbol", "Side", "Price", 
                            "RSI", "ATR", "EMA", "GridLevel", 
                            "DistanceMoved", "RequiredDistance", "LotSize", 
                            "Drawdown_Percent", "Balance", "Equity", "Notes"
                        ])
                except Exception as e:
                    print(f"Error initializing CSV file: {e}")

    def log_event(self, action, side="", price=0.0, rsi=None, atr=None, ema=None, 
                  grid_level=None, distance_moved=None, required_distance=None, lot_size=None, 
                  drawdown=None, balance=None, equity=None, notes=""):
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        row = [
            timestamp,
            action,
            self.symbol,
            side,
            f"{price:.5f}" if price else "",
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
        
        with self._lock:
            try:
                with open(self.filepath, mode='a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)
            except Exception as e:
                print(f"Error logging to CSV: {e}")
