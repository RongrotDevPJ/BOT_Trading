# --- Bot Configuration ---
SYMBOL = "AUDNZD"
MAGIC_NUMBER = 444444 # For AUDNZD

# --- Trading Mode ---
START_LOT = 0.05 # Base lot size for the first trade
MAX_DEVIATION = 100 # Allow slippage

# --- Risk Management & Auto-Lot ---
AUTO_LOT = True             # Enable dynamic lot sizing based on equity
CENTS_PER_01_LOT = 1000     # Equity required per 0.01 lot step
MIN_START_LOT = 0.05        # Minimum allowed base lot
MAX_START_LOT = 0.50        # Maximum allowed base lot

# --- Smart Grid Settings ---
GRID_DISTANCE_POINTS = 120 # Base distance fallback for AUDNZD
GRID_MULTIPLIER = 1.1 # Distance multiplier for each sub-level
LOT_MULTIPLIER = 1.2 # Multiply lot size for each grid level
MAX_LOT = 0.5 # Maximum lot size allowed
MAX_POSITIONS = 10 # Max positions to open
BASKET_TP_DOLLARS = 0.5 # Basket TP in Dollars (0.5 Cent for cent accounts)
BASKET_TP_POINTS = 100 # Fallback
MIN_GRID_DISTANCE_POINTS = 150 # Minimum distance for dynamic ATR grid

import MetaTrader5 as ag
TIMEFRAME = ag.TIMEFRAME_M5
RSI_TIMEFRAME = ag.TIMEFRAME_M5 
RSI_PERIOD = 14
RSI_BUY_LEVEL = 25  
RSI_SELL_LEVEL = 75 

# AUDNZD Trend Filters
EMA_PERIOD = 200
EMA_TIMEFRAME = ag.TIMEFRAME_M15
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5

# --- Advanced Exit Strategy ---
USE_TRAILING_STOP = False
TRAILING_STOP_POINTS = 50 
TRAILING_STEP_POINTS = 10 

# --- Risk Management ---
MAX_SPREAD_POINTS = 40 
MAX_DD_PERCENT = 30.0 # Stop trading if drawdown > 30%
HEARTBEAT_INTERVAL_SEC = 300 # 5 minutes
COOLDOWN_MINUTES = 20 # Wait at least 20 min between grid levels
MAX_GAP_MULTIPLIER = 4.0 # Pause trading if gap exceeds 4x the grid distance (Crash Recovery)

# --- Advanced Portfolio Protections ---
ENABLE_PARTIAL_CLOSE = True
MIN_POSITIONS_FOR_PARTIAL = 5 # Start looking for Partial Close if holding 5+ positions

# --- Time Filter ---
ALLOW_FRIDAY_TRADING = False
FRIDAY_STOP_HOUR = 15 # Broker time to stop trading on Friday (e.g. 15:00)

# MT5 Account Credentials
# Automatically loads from .env in the root directory if it exists
# Leave empty in .env to use the terminal already logged in
import os
from pathlib import Path

MT5_SERVER = ""
MT5_LOGIN = 0
MT5_PASSWORD = ""

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'\"")
                    if key == "MT5_SERVER": MT5_SERVER = value
                    elif key == "MT5_LOGIN": MT5_LOGIN = int(value or 0)
                    elif key == "MT5_PASSWORD": MT5_PASSWORD = value
    except Exception:
        pass # Fallback to defaults if .env parsing fails
