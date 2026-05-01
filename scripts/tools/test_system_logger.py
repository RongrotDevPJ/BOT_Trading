import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from core.system_logger import setup_logger

def test_system_logger():
    bot_name = "TEST_BOT"
    logger = setup_logger(bot_name)
    
    # 1. Test logging at various levels
    logger.info("This is an INFO message for testing.")
    logger.warning("This is a WARNING message for testing.")
    logger.error("This is an ERROR message for testing.")
    
    # 2. Verify Directory existence
    log_dir = Path("Log_HistoryOrder") / "System_Logs"
    if log_dir.exists():
        print(f"✅ Directory {log_dir} created successfully.")
    else:
        print(f"❌ Directory {log_dir} NOT found.")
        return

    # 3. Verify File existence
    log_file = log_dir / f"{bot_name}_system.log"
    if log_file.exists():
        print(f"✅ Log file {log_file} created successfully.")
        print(f"OK: Log file {log_file} created successfully.")
    else:
        print(f"FAIL: Log file {log_file} NOT found.")

    # 4. Verify Content and Format
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        if len(lines) >= 3:
            print("OK: Log content verified.")
            for line in lines[-3:]:
                print(f"   [File Content]: {line.strip()}")
                # Check format: YYYY-MM-DD HH:MM:SS,ms | LEVEL | Message
                parts = line.split('|')
                if len(parts) == 3:
                    print(f"   OK: Format Check: OK")
                else:
                    print(f"   FAIL: Format Check FAILED: Expected 3 parts split by '|', got {len(parts)}")
        else:
            print(f"FAIL: Log content incomplete. Expected 3 lines, got {len(lines)}")

if __name__ == "__main__":
    test_system_logger()
