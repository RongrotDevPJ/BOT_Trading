import time
import sys
import os
from pathlib import Path

current_file = Path(__file__).resolve()
project_root = current_file.parents[2] 
sys.path.insert(0, str(project_root))

from shared_utils.db_manager import DBManager
from shared_utils.csv_logger import CSVLogger
import sqlite3

def verify():
    db = DBManager()
    logger = CSVLogger("VERIFY_BOT")
    
    unique_action = f"VERIFY_{int(time.time())}"
    print(f"Submitting test log with action: {unique_action}")
    
    # These should return immediately
    db.log_trade(action=unique_action, symbol="VERIFY")
    logger.log_event(action=unique_action, notes="Verification entry")
    
    print("Tasks queued. Waiting 3 seconds for workers to process...")
    time.sleep(3)
    
    # Now check directly
    db_path = project_root / "Log_HistoryOrder" / "trading_data.db"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM trades WHERE action=?", (unique_action,))
    count = cursor.fetchone()[0]
    conn.close()
    
    csv_path = project_root / "Log_HistoryOrder" / "Analytics_Data" / "VERIFY_BOT_Analytics.csv"
    csv_exists = os.path.exists(csv_path)
    csv_content = ""
    if csv_exists:
        with open(csv_path, 'r', encoding='utf-8') as f:
            csv_content = f.read()
    
    found_in_csv = unique_action in csv_content
    
    if count > 0 and found_in_csv:
        print("SUCCESS: Database and CSV entries verified.")
    else:
        print(f"FAILURE: DB Count={count}, Found in CSV={found_in_csv}")

if __name__ == "__main__":
    verify()
