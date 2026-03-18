import os
import csv
from datetime import datetime
import threading
from shared_utils.db_manager import DBManager

class CSVLogger:
    _lock = threading.Lock()
    
    def __init__(self, symbol):
        self.symbol = symbol
        from pathlib import Path
        # Get the root directory of the project (BOT_Trading)
        # __file__ is BOT_Trading\shared_utils\csv_logger.py
        current_dir = Path(__file__).resolve().parent
        project_root = current_dir.parent
        self.log_dir = project_root / "Log_HistoryOrder" / "Analytics_Data"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.filepath = self.log_dir / f"{self.symbol}_Analytics.csv"
        self.db_manager = DBManager()
        self._init_file()

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
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
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
            try:
                with self._lock:
                    with open(self.filepath, mode='a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        writer.writerow(row)
            except Exception as e:
                print(f"Error logging to CSV: {e}")
        
        # Dual-Logging: SQLite
        try:
            self.db_manager.log_trade(
                action=action,
                symbol=self.symbol,
                ticket=ticket,
                side=side,
                price=price if price else 0.0,
                lots=lot_size if lot_size is not None else 0.0,
                profit=profit if profit is not None else 0.0,
                comment=f"RSI:{rsi} EMA:{ema} {notes}"[:100]
            )
        except Exception as e:
            print(f"Error logging to DB (via CSVLogger): {e}")
