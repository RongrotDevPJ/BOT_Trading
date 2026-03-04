# --- Bot Configuration ---
SYMBOL = "AUDNZD"
MAGIC_NUMBER = 444444 # For AUDNZD

# --- Trading Mode ---
START_LOT = 0.01 # Base lot size for the first trade
MAX_DEVIATION = 100 # Allow 100 points slippage for Gold volatility

# --- Risk Management & Auto-Lot ---
AUTO_LOT = True             # Enable dynamic lot sizing based on equity
CENTS_PER_01_LOT = 1000     # Equity required per 0.01 lot step
MIN_START_LOT = 0.01        # Minimum allowed base lot
MAX_START_LOT = 0.10        # Maximum allowed base lot

# --- Smart Grid Settings ---
GRID_DISTANCE_POINTS = 120 # Base distance fallback for AUDNZD
GRID_MULTIPLIER = 1.1 # Distance multiplier for each sub-level
LOT_MULTIPLIER = 1.2 # Multiply lot size for each grid level
MAX_LOT = 0.1 # Maximum lot size allowed
MAX_POSITIONS = 10 # Max positions to open
BASKET_TP_DOLLARS = 0.5 # Basket TP in Dollars (0.5 Cent for cent accounts)
BASKET_TP_POINTS = 100 # Fallback
MIN_GRID_DISTANCE_POINTS = 300 # Minimum distance for dynamic ATR grid

import MetaTrader5 as ag
TIMEFRAME = ag.TIMEFRAME_M5
RSI_TIMEFRAME = ag.TIMEFRAME_M5 # Tuned down to M5 for more signals
RSI_PERIOD = 14
RSI_BUY_LEVEL = 25  # Tighter constraint since we moved to 5M
RSI_SELL_LEVEL = 75 # Tighter constraint since we moved to 5M

# Gold Trend Filters
EMA_PERIOD = 200
EMA_TIMEFRAME = ag.TIMEFRAME_M15
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5

# --- Advanced Exit Strategy ---
USE_TRAILING_STOP = False
TRAILING_STOP_POINTS = 50 # Distance to trail (5 Pips)
TRAILING_STEP_POINTS = 10 # Only move SL if profit increases by >= 10 points

# --- Risk Management ---
MAX_SPREAD_POINTS = 60 # Gold has wider spreads
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

# MT5 Account Credentials (leave empty if already logged into terminal)
MT5_SERVER = ""
MT5_LOGIN = 0
MT5_PASSWORD = ""
