# --- Bot Configuration ---
SYMBOL = "BTCUSD"
MAGIC_NUMBER = 333333 # For BTCUSD

# --- Trading Mode ---
START_LOT = 0.05 # Base lot size for the first trade
MAX_DEVIATION = 100 # Allow 100 points slippage for Gold volatility

# --- Risk Management & Auto-Lot ---
AUTO_LOT = True             # Enable dynamic lot sizing based on equity
CENTS_PER_01_LOT = 1000     # Equity required per 0.01 lot step
MIN_START_LOT = 0.05        # Minimum allowed base lot
MAX_START_LOT = 0.50        # Maximum allowed base lot

# --- Smart Grid Settings ---
GRID_DISTANCE_POINTS = 1000 # Base distance fallback
GRID_MULTIPLIER = 1.3 # Distance multiplier for each sub-level (Higher for Gold)
LOT_MULTIPLIER = 1.1 # Multiply lot size cautiously for each grid level
MAX_LOT = 1.0 # Maximum lot size allowed to protect Cent account
BASKET_TP_POINTS = 100 # Break-even profit target (10 Pips)
MIN_GRID_DISTANCE_POINTS = 300 # Minimum distance for dynamic ATR grid

import MetaTrader5 as ag
TIMEFRAME = ag.TIMEFRAME_M5
RSI_TIMEFRAME = ag.TIMEFRAME_M15
RSI_PERIOD = 14
RSI_BUY_LEVEL = 40  # Tuned for higher frequency Trades (Option B)
RSI_SELL_LEVEL = 60 # Tuned for higher frequency Trades (Option B)

# BTC Trend Filters
EMA_PERIOD = 200
EMA_TIMEFRAME = ag.TIMEFRAME_H1
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.5

# --- Advanced Exit Strategy ---
USE_TRAILING_STOP = True
TRAILING_STOP_POINTS = 300 # Distance to trail (5 Pips)
TRAILING_STEP_POINTS = 50 # Only move SL if profit increases by >= 10 points

# --- Risk Management ---
MAX_SPREAD_POINTS = 5000 # BTC has wider spreads (e.g., 2000-5000 points)
MAX_DD_PERCENT = 30.0 # Stop trading if drawdown > 30%
HEARTBEAT_INTERVAL_SEC = 300 # 5 minutes
COOLDOWN_MINUTES = 60 # Wait at least 30 min between grid levels (Gold is volatile)
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
