import time
import sys
import os
from pathlib import Path

# Add project root to sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parents[2] 
sys.path.insert(0, str(project_root))

from shared_utils.db_manager import DBManager
from shared_utils.csv_logger import CSVLogger

def test_speed():
    db = DBManager()
    csv = CSVLogger("TEST_SYMBOL")
    
    print("--- Starting High Frequency Logging Test ---")
    start_time = time.perf_counter()
    
    for i in range(100):
        db.log_trade(action="TEST_ACTION", symbol="TEST", comment=f"Batch {i}")
        csv.log_event(action="TEST_EVENT", notes=f"Batch {i}")
    
    end_time = time.perf_counter()
    duration = end_time - start_time
    print(f"✅ Logged 100 events in {duration:.6f} seconds.")
    print("Main thread is FREE. Waiting 2 seconds for background workers to finish...")
    time.sleep(2)
    print("Test finished.")

if __name__ == "__main__":
    test_speed()
