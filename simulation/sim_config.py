"""
simulation/sim_config.py
Configuration for XAUUSD Paper Trading Simulation Bot.
All parameters are independent from the Live Bot.
"""

# ── Identity ───────────────────────────────────────────────────────────────────
SYMBOL       = "XAUUSD"
SIM_NAME     = "XAUUSD_SMC_ML_SIM"
SIM_DB_PATH  = "data/sim/sim_results.db"

# ── Simulation Account (mirrors your cent account) ─────────────────────────────
SIM_INITIAL_BALANCE  = 5000.0    # USC (=$50 real)
SIM_LEVERAGE         = 500       # Typical for cent accounts

# ── Realistic Execution Model ──────────────────────────────────────────────────
# Spread model by session (points)
SPREAD_ASIA    = 50    # 00:00-07:00 server time
SPREAD_LONDON  = 30    # 07:00-12:00
SPREAD_NY      = 25    # 12:00-17:00
SPREAD_OVERLAP = 28    # 17:00-20:00
SPREAD_NEWS    = 150   # During high-impact news (simulated)
SPREAD_WEEKEND = 300   # Friday close / Sunday open

# Slippage model (points, random normal distribution)
SLIPPAGE_MEAN_NORMAL   = 2.0    # Average slippage in normal conditions
SLIPPAGE_STD_NORMAL    = 3.0    # Std dev
SLIPPAGE_MEAN_VOLATILE = 10.0   # During high ATR periods
SLIPPAGE_STD_VOLATILE  = 8.0

# ATR threshold to switch to volatile slippage model
ATR_VOLATILE_THRESHOLD = 8.0    # XAUUSD ATR > 8.0 = volatile

# Commission model (per lot, one-way, USC on cent account)
COMMISSION_PER_LOT_USC = 0.0    # Most cent accounts have no commission
SWAP_LONG_PER_LOT_PER_DAY  = -0.5   # USC (approximation)
SWAP_SHORT_PER_LOT_PER_DAY = -0.3

# ── Strategy Parameters ────────────────────────────────────────────────────────
# --- Strategy 1: SMC/ICT ---
SMC_SWING_LOOKBACK     = 5        # Reduced: 20 → 5 (XAUUSD M5 needs shorter lookback to find swings)
SMC_BOS_CONFIRM_BARS   = 1        # Reduced: 2 → 1 (less confirmation needed)
SMC_OB_DEPTH_BARS      = 3        # Order Block lookback from BOS candle
SMC_SL_ATR_MULTIPLIER  = 1.5     # SL = ATR * 1.5 below/above OB
SMC_TP1_RR             = 1.5     # TP1 at 1.5R (50% close)
SMC_TP2_RR             = 3.0     # TP2 at 3R (remaining 50%)
SMC_MAX_RISK_PCT       = 1.0     # Max 1% per trade
SMC_MAX_CONCURRENT     = 2       # Max 2 positions at once
SMC_OB_EXPIRE_HOURS    = 4       # Expire OB retest lock after 4h

# --- Strategy 2: ML-Based ---
ML_LOOKBACK_CANDLES    = 50      # Feature window for prediction
ML_ENTRY_SCORE_MIN     = 0.60    # Higher than live bot (more selective)
ML_MAX_RISK_PCT        = 1.0
ML_FIXED_SL_POINTS     = 400     # Fixed SL for ML strategy
ML_TP_RATIO            = 2.0     # TP = SL * TP_RATIO

# ── Indicators ─────────────────────────────────────────────────────────────────
import MetaTrader5 as mt5
TIMEFRAME     = mt5.TIMEFRAME_M5
TIMEFRAME_H1  = mt5.TIMEFRAME_H1
ATR_PERIOD    = 14
RSI_PERIOD    = 14
EMA_PERIOD    = 200

# ── HMM Regime Model ───────────────────────────────────────────────────────────
HMM_MODEL_PATH        = "data/ml_models/sim_hmm_regime.pkl"
HMM_RETRAIN_HOURS     = 6
HMM_FEATURE_CANDLES   = 300

# ── LightGBM Signal Model ──────────────────────────────────────────────────────
LGBM_MODEL_PATH       = "data/ml_models/sim_lgbm_signal.pkl"
LGBM_RETRAIN_HOURS    = 24
LGBM_MIN_SAMPLES      = 50      # More data required than live bot

# ── External APIs ──────────────────────────────────────────────────────────────
# All free APIs — no payment required
NEWSAPI_KEY           = ""       # Free at newsapi.org (100 req/day)
NEWSAPI_QUERY         = "gold price XAU OR XAUUSD OR Federal Reserve"
NEWSAPI_REFRESH_MIN   = 15       # Fetch sentiment every 15 minutes

# Yahoo Finance via yfinance (free, no key needed)
DXY_TICKER   = "DX-Y.NYB"       # US Dollar Index
VIX_TICKER   = "^VIX"           # CBOE Volatility Index
GLD_TICKER   = "GLD"            # SPDR Gold ETF (proxy for institutional flow)

# CFTC COT Reports (free, weekly, from CFTC website)
COT_URL      = "https://www.cftc.gov/dea/futures/deacmesf.htm"
COT_CACHE_H  = 168              # Cache for 1 week (COT is weekly)

# ── Loop Timing ────────────────────────────────────────────────────────────────
SIM_LOOP_SLEEP_SEC = 1.0        # Check every 1 second (not 0.1 — save CPU)
SIM_REPORT_INTERVAL_MIN = 60    # Print performance report every hour

# ── Output ─────────────────────────────────────────────────────────────────────
SIM_LOG_PATH  = "Log_HistoryOrder/System_Logs/XAUUSD_Sim_system.log"
SIM_CSV_PATH  = "data/logs/XAUUSD_Sim_Analytics.csv"
