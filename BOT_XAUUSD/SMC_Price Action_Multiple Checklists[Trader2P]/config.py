# --- Symbol & Timeframe ---
SYMBOL = "XAUUSD"
HTF_TIMEFRAME = "H1"  # For Trend Bias
LTF_TIMEFRAME = "M15" # For Entry Execution
MAGIC_NUMBER = 999  # Unique ID for this bot

# --- Execution Settings ---
MAX_ALLOWED_SPREAD = 50  # Points
MAX_DEVIATION = 10       # Points
USE_TRAILING_STOP = False # We use Breakeven instead, but keep for compatibility

# --- Risk Management ---
RISK_PERCENT = 1.0    # 1.0% risk per trade
MIN_RR_RATIO = 3.0    # Minimum Reward/Risk Ratio
BREAKEVEN_AT_R = 1.0  # Move SL to entry when profit reaches 1R

# --- SMC Parameters ---
FRACTAL_NEIGHBORS = 2 # Number of candles to check on each side for HH/HL
MIN_FVG_SIZE = 0.3    # Minimum Points for an Imbalance to be valid (to filter tiny gaps)
OB_IMBALANCE_MIN_GAP = 0.5 # Min points gap for OB validation
FIB_DISCOUNT_LEVEL = 0.618
FIB_DEEP_DISCOUNT = 0.786

# --- Indicator Settings ---
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
STOCH_K = 5
STOCH_D = 3
STOCH_SLOWING = 3

# --- Line Notify ---
LINE_NOTIFY_TOKEN = "" # Fill your token here

# --- Path Configuration (Auto-detected if kept in same project structure) ---
MT5_LOGIN = None       # Set manually or detect from env
MT5_PASSWORD = ""
MT5_SERVER = ""
