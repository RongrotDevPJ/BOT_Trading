# --- Bot Configuration ---
SYMBOL = "AUDNZD"
MAGIC_NUMBER = 444444 # Unique Magic Number

# --- Trading Mode ---
MAX_DEVIATION = 20 # Slippage allowance

# --- Risk Management & Auto-Lot (Phase 3 Optimized) ---
AUTO_LOT = True              
DEFAULT_LOT = 0.10           # Safe base lot for Cent
BASE_EQUITY = 5000.0         # Milestone for scaling (5000 USC = $50)
BASE_LOT = 0.10              # Lot per BASE_EQUITY
MAX_LOT = 2.0                # Cap to prevent broker rejection
MIN_LOT = 0.01
MIN_CYCLE_PROFIT_USC = 15.0  # Minimum profit in cents per grid cycle

# --- Grid Scaling ---
LOT_MULTIPLIER = 1.5         # Multiply lot size for each grid level
MAX_GRID_LEVELS = 10         # Maximum number of grid levels allowed

# --- Dynamic Grid Settings ---
GRID_DISTANCE_POINTS = 300   # Base distance fallback
MIN_GRID_DISTANCE_POINTS = 250 # Minimum distance for dynamic ATR grid
ENABLE_ATR_DISTANCE = True    # Enable ATR-based dynamic grid distance
ATR_PERIOD = 14
ATR_MULTIPLIER = 2.0
MAX_GAP_MULTIPLIER = 4.0     # Pause if gap > 4x grid distance

# --- Phase 2 Upgrades (Grid Multiplier & Basket Trailing) ---
GRID_DISTANCE_MULTIPLIER = 1.3
BASKET_TRAILING_TRIGGER_USD = 10.0
BASKET_TRAILING_STEP_USD = 3.0

# --- Indicators & Filters Setup ---
import MetaTrader5 as ag
TIMEFRAME = ag.TIMEFRAME_M5
RSI_PERIOD = 14
RSI_BUY_LEVEL = 35           # Buy trigger level
RSI_SELL_LEVEL = 65          # Sell trigger level

# Trend Filter (EMA 200)
ENABLE_TREND_FILTER = True
EMA_PERIOD = 200
EMA_TIMEFRAME = ag.TIMEFRAME_M15

# --- Exit Strategy ---
BASKET_TP_POINTS = 50        # Strategy TP profit goal in points
USE_TRAILING_STOP = True     # Use Break-Even and Trailing Stop
TRAILING_STOP_POINTS = 50
TRAILING_STEP_POINTS = 10

# --- Advanced Protections ---
MAX_ALLOWED_SPREAD = 80
ENABLE_PARTIAL_CLOSE = True
MIN_POSITIONS_FOR_PARTIAL = 5
MAX_DD_PERCENT = 30.0        # Max drawdown before safety actions
ENABLE_HEDGE_ON_DD = True    # Auto-hedge if DD reached
COOLDOWN_MINUTES = 15        # Minimum time between grid orders

# --- Time Filter ---
ALLOW_FRIDAY_TRADING = False
FRIDAY_STOP_HOUR = 15

# MT5 Account Credentials (Placeholder - Loaded from .env in main.py)
MT5_SERVER = ""
MT5_LOGIN = 0
MT5_PASSWORD = ""
