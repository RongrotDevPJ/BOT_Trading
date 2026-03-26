import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

def setup_logger(bot_name):
    """
    Sets up a dual-logger that outputs to both the Terminal and a persistent log file.
    Log file location: [Project Root]/Log_HistoryOrder/System_Logs/{bot_name}_system.log
    """
    # Find Project Root (shared_utils is one level below root)
    project_root = Path(__file__).resolve().parents[1]
    
    # Ensure the directory exists relative to project root
    log_dir = project_root / "Log_HistoryOrder" / "System_Logs"
    os.makedirs(str(log_dir), exist_ok=True)
    
    log_file = log_dir / f"{bot_name}_system.log"
    
    # Create logger
    logger = logging.getLogger(bot_name)
    logger.setLevel(logging.INFO)
    
    # Avoid duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger
        
    # Format: Timestamp | Level | Message
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    
    # 1. TimedRotatingFileHandler (Daily rotation, 14 days backup)
    file_handler = TimedRotatingFileHandler(
        str(log_file), 
        when="midnight", 
        interval=1, 
        backupCount=14, 
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # 2. StreamHandler (Terminal)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Prevent propagation to the root logger to avoid double printing
    logger.propagate = False
    
    return logger
