SYMBOL = "EURUSD"
MAGIC_NUMBER = 123456
START_LOT = 0.01

# --- Smart Grid Settings ---
GRID_DISTANCE_POINTS = 150 # Base distance (15 Pips)
GRID_MULTIPLIER = 1.2 # Distance multiplier for each sub-level
BASKET_TP_POINTS = 100 # Break-even profit target (10 Pips)

# --- Initial Entry Setup ---
import MetaTrader5 as ag
TIMEFRAME = ag.TIMEFRAME_M5
RSI_PERIOD = 14
RSI_BUY_LEVEL = 30
RSI_SELL_LEVEL = 70

# --- Advanced Exit Strategy ---
USE_TRAILING_STOP = True
TRAILING_STOP_POINTS = 50 # Distance to trail (5 Pips)
TRAILING_STEP_POINTS = 10 # Only move SL if profit increases by >= 10 points

# --- Risk Management ---
MAX_SPREAD_POINTS = 30
MAX_DD_PERCENT = 30.0 # Stop trading if drawdown > 30%
HEARTBEAT_INTERVAL_SEC = 300 # 5 minutes

# MT5 Account Credentials (leave empty if already logged into terminal)
MT5_SERVER = ""
MT5_LOGIN = 0
MT5_PASSWORD = ""
