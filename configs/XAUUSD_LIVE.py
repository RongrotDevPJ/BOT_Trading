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

# ── Grid Parameters ──────────────────────────────────────────────────────
LOT_MULTIPLIER          = 1.2    # Conservative — prevent blowup
MAX_GRID_LEVELS         = 2      # Reduced from 4 → 2 (limit exposure after -97% loss event)
GRID_DISTANCE_POINTS    = 300    # Fallback fixed
MIN_GRID_DISTANCE_POINTS = 600   # ATR floor
ENABLE_ATR_DISTANCE     = True
ATR_PERIOD              = 14
ATR_MULTIPLIER          = 2.5
GRID_DISTANCE_MULTIPLIER = 1.3
MAX_GAP_MULTIPLIER      = 4.0
COOLDOWN_MINUTES        = 10     # Increased 5→10: prevent rapid re-entry after bad exits

# ── Basket Profit Management ───────────────────────────────────────────────────
MIN_CYCLE_PROFIT_USC      = 20.0   # Min profit target per cycle
BASKET_TP_POINTS          = 50
BASKET_TRAILING_STEP_USD  = 5.0
BASKET_HARD_STOP_USC      = -50.0  # -60 was too loose for 103 USC balance; -50 = max basket risk
# Per-Trade Individual Stop Loss (NEW 2026-06-24)
# Protects against Sunday gaps and sudden spikes before basket-level stop activates
PER_TRADE_HARD_STOP_USC   = -20.0  # Close any single trade losing more than -20 USC
PER_TRADE_MAX_HOLD_HOURS  = 48.0   # Force-close trades stuck for >48h without recovery

# ── Exit Strategy ──────────────────────────────────────────────────────────────
USE_TRAILING_STOP      = True
TRAILING_STOP_POINTS   = 50
TRAILING_STEP_POINTS   = 10
BE_ACTIVATION_POINTS   = 500
BE_LOCK_POINTS         = 20

# ── Indicators ────────────────────────────────────────────────────────────
import MetaTrader5 as mt5
TIMEFRAME     = mt5.TIMEFRAME_M5
RSI_PERIOD    = 14
# NOTE 2026-06-27: Level 1 DB Evidence proves Trade #58 and #60 losses were caused by Monday market open gap, NOT RSI level.
# With BLOCK_MONDAY=True and BLOCKED_HOURS_UTC=[19,21,22,23] now active, mid-week trades have 100% WR (+5.80 USC).
# Raising RSI_BUY_LEVEL to 40 to fulfill Phase 1 Data Collection target (N >= 30).
RSI_BUY_LEVEL = 40   # Optimized level for mid-week trend pullbacks (Phase 1 Data Collection)
RSI_SELL_LEVEL = 70   # Raised from 65 → 70 (SELL PF was 0.37, too many premature SELL entries)
EMA_PERIOD    = 200
EMA_TIMEFRAME = mt5.TIMEFRAME_M15

# ── ML Signal Filter ──────────────────────────────────────────────────────────
# NOTE: Disabled until lgbm_buy.pkl / lgbm_sell.pkl are trained from real closed trades.
# Will auto-enable once ML trainer runs successfully (needs N >= 20 closed trades per side).
ENABLE_ML_SIGNAL_FILTER  = False  # Was True — disabled: models not trained yet
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
# NOTE 2026-06-16: Kill switch fired AGAIN at 15.25% from Sunday gap (Trade #60 at 4337.91)
# The issue is NOT the DD limit — it is that the bot opens trades during dangerous hours.
# Keep MAX_DD=15% but fix the root cause: Sunday night / Monday open blocking.
MAX_DD_PERCENT      = 15.0   # Keep 15%. Root cause fix = time filter, not DD limit.
ENABLE_HEDGE_ON_DD  = True
MAX_CONSECUTIVE_LOSSES = 3   # Loosened for data collection phase

# ── Direction Control (BUY Only Mode) ─────────────────────────────────────────
# VERIFIED: SELL PF = 0.38 (N=46), BUY PF = 2.24 (N=40) from 86-trade DB
ENABLE_SELL = False   # ⛔ SELL entries disabled — BUY Only Mode
ENABLE_BUY  = True    # ✅ BUY entries enabled

# ── Smart SELL Conditions (used when ENABLE_SELL=True in future) ───────────────
# ALL 3 must be True simultaneously to allow SELL entry:
#   1. Regime = BEAR (from HMM detector)
#   2. RSI >= RSI_SELL_LEVEL (currently 70)
#   3. Price < EMA200
# Currently ENABLE_SELL=False overrides this — will re-enable after N_SELL >= 100, PF > 1.0
SMART_SELL_REQUIRE_REGIME_BEAR = True   # Must be BEAR regime
SMART_SELL_REQUIRE_BELOW_EMA   = True   # Must be Price < EMA200

# ── Day Filters ───────────────────────────────────────────────────────────────
# 2026-06-24: ENABLED Monday block after 2nd kill switch on Monday 00:36 UTC
# Kill switch #2 caused by Sunday night gap trade entering at 23:53 UTC Sunday
BLOCK_MONDAY = True   # ENABLED: Monday gaps confirmed dangerous. N_monday=2 WR=50% PF=0.22

# ── Daily Limits ───────────────────────────────────────────────────────────────
ENABLE_DAILY_TARGET          = True
DAILY_TARGET_PERCENT         = 5.0
DAILY_TARGET_TRAILING_PERCENT = 1.5
ENABLE_DAILY_LOSS_LIMIT      = True
DAILY_LOSS_LIMIT_PERCENT     = 8.0   # Raised 5% → 8%: 5% on 115 USC = -5.75 USC in one 0.01-lot trade

# ── Partial Close ──────────────────────────────────────────────────────────────
ENABLE_PARTIAL_CLOSE      = True
MIN_POSITIONS_FOR_PARTIAL = 5

# ── Session & Time ─────────────────────────────────────────────────────────────
ENABLE_SESSION_FILTER = True
TRADING_HOURS_START   = "00:00"
TRADING_HOURS_END     = "23:59"
# 2026-06-24 CRITICAL FIX: Added hours 21,22,23 (Sunday night market reopen)
# Root cause of Kill Switch #2: Trade opened at 23:53 UTC Sunday (market reopen)
# Worst hours confirmed: 19 UTC (old), 21-23 UTC (Sunday gap risk)
BLOCKED_HOURS_UTC     = [19, 21, 22, 23]  # 19=worst trading hour; 21-23=Sunday night gap risk
ALLOW_FRIDAY_TRADING  = False
FRIDAY_STOP_HOUR      = 14              # Tightened 15→14: extra buffer before weekend

# ── System ─────────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_SEC = 300
BOT_ENABLED            = True

# ── MT5 Credentials (loaded from .env) ────────────────────────────────────────
MT5_SERVER   = ""
MT5_LOGIN    = 0
MT5_PASSWORD = ""
