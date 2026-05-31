# ==============================================================================
# XAUUSD Live Bot — Regime-Aware ML Grid Configuration
# Bot System 1: Production Trading Bot
# ==============================================================================

SYMBOL       = "XAUUSD"
MAGIC_NUMBER = 222222

# ── Execution ──────────────────────────────────────────────────────────────────
MAX_DEVIATION      = 20    # Slippage allowance (pts)
MAX_ALLOWED_SPREAD = 150   # XAUUSD spikes to 100-300 on news

# ── Lot Sizing (Cent Account: BASE_EQUITY=5000 USC = $50) ─────────────────────
AUTO_LOT    = True
DEFAULT_LOT = 0.10
BASE_EQUITY = 5000.0
BASE_LOT    = 0.10
MIN_LOT     = 0.01
MAX_LOT     = 2.0

# ── Kelly Criterion ────────────────────────────────────────────────────────────
KELLY_FRACTION     = 0.25
KELLY_MIN_TRADES   = 10
KELLY_MAX_FRACTION = 0.20

# ── Grid Parameters ────────────────────────────────────────────────────────────
LOT_MULTIPLIER          = 1.2    # Conservative — prevent blowup
MAX_GRID_LEVELS         = 4      # Hard cap; regime may reduce to 2
GRID_DISTANCE_POINTS    = 300    # Fallback fixed
MIN_GRID_DISTANCE_POINTS = 600   # ATR floor
ENABLE_ATR_DISTANCE     = True
ATR_PERIOD              = 14
ATR_MULTIPLIER          = 2.5
GRID_DISTANCE_MULTIPLIER = 1.3
MAX_GAP_MULTIPLIER      = 4.0
COOLDOWN_MINUTES        = 5

# ── Basket Profit Management ───────────────────────────────────────────────────
MIN_CYCLE_PROFIT_USC      = 25.0   # Min profit target per cycle
BASKET_TP_POINTS          = 50
BASKET_TRAILING_STEP_USD  = 6.0
BASKET_HARD_STOP_USC      = -80.0  # NEW: Hard stop if basket loss > $0.80 USC
                                    # Prevents catastrophic drawdown in strong trend

# ── Exit Strategy ──────────────────────────────────────────────────────────────
USE_TRAILING_STOP      = True
TRAILING_STOP_POINTS   = 50
TRAILING_STEP_POINTS   = 10
BE_ACTIVATION_POINTS   = 500
BE_LOCK_POINTS         = 20

# ── Indicators ─────────────────────────────────────────────────────────────────
import MetaTrader5 as mt5
TIMEFRAME     = mt5.TIMEFRAME_M5
RSI_PERIOD    = 14
RSI_BUY_LEVEL = 35
RSI_SELL_LEVEL = 65
EMA_PERIOD    = 200
EMA_TIMEFRAME = mt5.TIMEFRAME_M15

# ── ML Signal Filter (NEW) ─────────────────────────────────────────────────────
ENABLE_ML_SIGNAL_FILTER  = True   # Use LightGBM to score entry quality
ML_MIN_ENTRY_SCORE       = 0.55   # Min probability threshold (0.5=50%, 0.55=55%)
ML_MODEL_PATH            = "data/ml_models/lgbm_signal.pkl"

# ── Regime Detection (ACTIVE — not dry-run) ────────────────────────────────────
ENABLE_REGIME_FILTER       = True
REGIME_TRENDING_MAX_LEVELS = 2    # When TRENDING, limit grid depth
REGIME_VOLATILE_BLOCK_ENTRY = True  # When VOLATILE, block all initial entries

# ── Stochastic Filter ──────────────────────────────────────────────────────────
ENABLE_STOCH_FILTER = False   # Keep OFF on XAUUSD (too many false blocks)

# ── Tick Imbalance Filter ──────────────────────────────────────────────────────
TICK_IMBALANCE_THRESHOLD  = 0.3
TICK_IMBALANCE_LOOKBACK_SEC = 60

# ── Trend Filter ───────────────────────────────────────────────────────────────
ENABLE_TREND_FILTER         = True
ENABLE_TREND_FILTER_ON_GRID = False

# ── Risk Management ────────────────────────────────────────────────────────────
MAX_DD_PERCENT      = 20.0
ENABLE_HEDGE_ON_DD  = True
MAX_CONSECUTIVE_LOSSES = 3

# ── Daily Limits ───────────────────────────────────────────────────────────────
ENABLE_DAILY_TARGET          = True
DAILY_TARGET_PERCENT         = 5.0
DAILY_TARGET_TRAILING_PERCENT = 1.5
ENABLE_DAILY_LOSS_LIMIT      = True
DAILY_LOSS_LIMIT_PERCENT     = 5.0

# ── Partial Close ──────────────────────────────────────────────────────────────
ENABLE_PARTIAL_CLOSE      = True
MIN_POSITIONS_FOR_PARTIAL = 5

# ── Session & Time ─────────────────────────────────────────────────────────────
ENABLE_SESSION_FILTER = False   # Gold is 24h but avoid thin Asian session
TRADING_HOURS_START   = "00:00"
TRADING_HOURS_END     = "23:59"
ALLOW_FRIDAY_TRADING  = False
FRIDAY_STOP_HOUR      = 15

# ── System ─────────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SEC = 300
BOT_ENABLED            = True

# ── MT5 Credentials (loaded from .env) ────────────────────────────────────────
MT5_SERVER   = ""
MT5_LOGIN    = 0
MT5_PASSWORD = ""
