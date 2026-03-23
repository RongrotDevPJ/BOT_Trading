# --- Bot Configuration ---
SYMBOL = "AUDNZD"
MAGIC_NUMBER = 444444 # Different from EURUSD

# --- Trading Mode ---
START_LOT = 0.10 # Base lot size for the first trade (Increased for higher profit)
MAX_DEVIATION = 20 # Allow 100 points slippage for Gold volatility

# --- Risk Management & Auto-Lot ---
AUTO_LOT = True             # Enable dynamic lot sizing based on equity
CENTS_PER_01_LOT = 500     # Equity required per 0.01 lot step (Decreased to increase lot size)
MIN_START_LOT = 0.10        # Minimum allowed base lot
MAX_START_LOT = 0.50        # Maximum allowed base lot

# --- Smart Grid Settings ---
GRID_DISTANCE_POINTS = 100 # Base distance fallback
GRID_MULTIPLIER = 1.2 # Distance multiplier for each sub-level (Moderate for Gold)
LOT_MULTIPLIER = 1.1 # Multiply lot size cautiously for each grid level
MAX_LOT = 0.5 # Maximum lot size allowed to protect Cent account
BASKET_TP_POINTS = 50 # Break-even profit target (25 Pips)
MIN_GRID_DISTANCE_POINTS = 100 # Minimum distance for dynamic ATR grid
ENABLE_ATR_DISTANCE = True    # Enable ATR-based dynamic grid distance

# --- Indicators & Filters Setup ---
import MetaTrader5 as ag
TIMEFRAME = ag.TIMEFRAME_M5
RSI_PERIOD = 14
RSI_BUY_LEVEL = 35  # Trend confirmation (Oversold)
RSI_SELL_LEVEL = 65 # Trend confirmation (Overbought)

# Trend Filters
ENABLE_TREND_FILTER = False # Turned off for sideways pairs
EMA_PERIOD = 200
EMA_TIMEFRAME = ag.TIMEFRAME_M15
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0

# --- Advanced Exit Strategy ---
USE_TRAILING_STOP = True
TRAILING_STOP_POINTS = 50 # Distance to trail (5 Pips)
TRAILING_STEP_POINTS = 10 # Only move SL if profit increases by >= 10 points

# --- Risk Management ---
MAX_ALLOWED_SPREAD = 50 # Spread Guard limit
ENABLE_DAILY_TARGET = False # Set to True to enable daily profit target (Close-Only)
DAILY_TARGET_PERCENT = 15.0 # Stop trading for the day if equity grows by 15%
MAX_DD_PERCENT = 30.0 # Stop trading if drawdown > 30%
ENABLE_HEDGE_ON_DD = True # Auto hedge to lock port when DD > MAX_DD_PERCENT
HEARTBEAT_INTERVAL_SEC = 300 # 5 minutes
COOLDOWN_MINUTES = 15 # Wait at least 15 min between grid levels
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
