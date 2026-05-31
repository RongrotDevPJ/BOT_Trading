"""
core/regime_detector.py  (PRODUCTION — replaces dry-run version)
─────────────────────────────────────────────────────────────────────────────
Hidden Markov Model (HMM) Market Regime Detector for XAUUSD.

States:
    0 = RANGING    — Mean-reversion grid works best
    1 = TRENDING   — Reduce grid levels, block counter-trend entries
    2 = VOLATILE   — Block all new initial entries

Algorithm:
    - GaussianHMM with 3 hidden states
    - Features: log-return, ATR-ratio, spread-ratio (3D observation)
    - Trained on last 200 M5 candles (~16.6 hours of data)
    - Retrained every 4 hours (or on bot startup)

CPU usage: Training ~2s, Inference < 1ms. Safe for 1-core VPS.
"""

import logging
import pickle
import time
import threading
from pathlib import Path
from datetime import datetime

import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
REGIME_RANGING  = "RANGING"
REGIME_TRENDING = "TRENDING"
REGIME_VOLATILE = "VOLATILE"
REGIME_UNKNOWN  = "UNKNOWN"

MODEL_PATH = Path("data/ml_models/hmm_regime.pkl")
RETRAIN_INTERVAL_SEC = 4 * 3600   # Retrain every 4 hours
INFERENCE_CANDLES    = 200         # Candles used for both training & inference
HMM_N_STATES         = 3


class RegimeDetector:
    """
    Production HMM Regime Detector — actively used by engine.py to gate entries.
    Thread-safe with internal lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._state_label_map: dict[int, str] = {}   # hmm_state → REGIME_*
        self._last_train_time = 0.0
        self._last_regime = REGIME_UNKNOWN
        self._last_prob = 0.0
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._load_model()

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect_regime(self, symbol: str, timeframe=None) -> tuple[str, float]:
        """
        Returns (regime_name, confidence_pct).
        Automatically retrains if model is stale.
        Safe to call every loop tick — caches result between retrains.
        """
        import MetaTrader5 as mt5
        if timeframe is None:
            timeframe = mt5.TIMEFRAME_M5

        with self._lock:
            now = time.time()

            # Retrain if stale or no model
            if (self._model is None or
                    now - self._last_train_time > RETRAIN_INTERVAL_SEC):
                trained = self._train(symbol, timeframe)
                if trained:
                    self._last_train_time = now
                else:
                    return REGIME_UNKNOWN, 0.0

            # Inference on latest window
            regime, prob = self._infer(symbol, timeframe)
            self._last_regime = regime
            self._last_prob = prob
            return regime, prob

    def get_cached_regime(self) -> tuple[str, float]:
        """Return last known regime without triggering retrain."""
        return self._last_regime, self._last_prob

    # ── Training ───────────────────────────────────────────────────────────────

    def _get_features(self, symbol: str, timeframe, n_candles: int = INFERENCE_CANDLES):
        """Fetch candles and extract (log_return, atr_ratio, spread_ratio) features."""
        try:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_candles + 20)
            if rates is None or len(rates) < 50:
                return None
        except Exception as e:
            logger.warning(f"[Regime] Failed to fetch rates: {e}")
            return None

        import math
        features = []
        atr_window = 14

        for i in range(atr_window + 1, len(rates)):
            close   = rates[i]["close"]
            prev    = rates[i - 1]["close"]
            high    = rates[i]["high"]
            low     = rates[i]["low"]
            spread  = rates[i]["spread"] if "spread" in rates.dtype.names else 30

            # Feature 1: Log return
            log_ret = math.log(close / prev) if prev > 0 else 0.0

            # Feature 2: ATR ratio (current TR / average TR over window)
            tr_list = []
            for j in range(i - atr_window, i):
                tr = max(
                    rates[j]["high"] - rates[j]["low"],
                    abs(rates[j]["high"] - rates[j-1]["close"]),
                    abs(rates[j]["low"]  - rates[j-1]["close"])
                )
                tr_list.append(tr)
            avg_tr = sum(tr_list) / len(tr_list) if tr_list else 1e-8
            curr_tr = high - low
            atr_ratio = curr_tr / avg_tr if avg_tr > 0 else 1.0

            # Feature 3: Spread ratio (normalized)
            spread_ratio = min(spread / 100.0, 3.0)

            features.append([log_ret, atr_ratio, spread_ratio])

        if len(features) < 30:
            return None

        return features

    def _train(self, symbol: str, timeframe) -> bool:
        try:
            from simulation.ml_models.pure_hmm import GaussianHMM
            import numpy as np
        except ImportError as e:
            logger.warning(f"[Regime] Import error: {e}. Pure HMM not found.")
            return False

        features = self._get_features(symbol, timeframe, INFERENCE_CANDLES)
        if features is None:
            logger.warning("[Regime] Insufficient data for HMM training.")
            return False

        X = np.array(features, dtype=float)

        try:
            model = GaussianHMM(
                n_components=HMM_N_STATES,
                covariance_type="diag",
                n_iter=100,
                random_state=42
            )
            model.fit(X)
        except Exception as e:
            logger.warning(f"[Regime] HMM training failed: {e}")
            return False

        # ── Label States by volatility (atr_ratio mean) ───────────────────────
        # Low atr_ratio = Ranging, High = Trending or Volatile
        means = model.means_  # shape: (n_states, n_features)
        atr_means = [(i, means[i][1]) for i in range(HMM_N_STATES)]
        atr_means.sort(key=lambda x: x[1])

        spread_means = [(i, means[i][2]) for i in range(HMM_N_STATES)]
        spread_means.sort(key=lambda x: x[1])

        # Lowest atr_ratio = RANGING
        state_ranging  = atr_means[0][0]
        # Highest spread_ratio = VOLATILE
        state_volatile = spread_means[-1][0]
        # Remaining = TRENDING
        remaining = [i for i in range(HMM_N_STATES)
                     if i != state_ranging and i != state_volatile]
        state_trending = remaining[0] if remaining else state_ranging

        self._model = model
        self._state_label_map = {
            state_ranging:  REGIME_RANGING,
            state_trending: REGIME_TRENDING,
            state_volatile: REGIME_VOLATILE,
        }

        # Save to disk
        try:
            with open(MODEL_PATH, "wb") as f:
                pickle.dump({"model": model, "label_map": self._state_label_map}, f)
        except Exception as e:
            logger.warning(f"[Regime] Failed to save model: {e}")

        logger.info(
            f"[Regime] ✅ HMM trained on {len(X)} observations. "
            f"States: RANGING={state_ranging}, TRENDING={state_trending}, "
            f"VOLATILE={state_volatile}"
        )
        return True

    def _infer(self, symbol: str, timeframe) -> tuple[str, float]:
        """Run inference on the last 20 candles and return regime + confidence."""
        try:
            import numpy as np
        except ImportError:
            return REGIME_UNKNOWN, 0.0

        features = self._get_features(symbol, timeframe, n_candles=50)
        if features is None or self._model is None:
            return REGIME_UNKNOWN, 0.0

        import numpy as np
        X = np.array(features[-20:], dtype=float)  # Use last 20 observations

        try:
            states   = self._model.predict(X)
            probs    = self._model.predict_proba(X)
            last_state = int(states[-1])
            last_prob  = float(probs[-1][last_state]) * 100
            regime     = self._state_label_map.get(last_state, REGIME_UNKNOWN)
            return regime, round(last_prob, 1)
        except Exception as e:
            logger.warning(f"[Regime] Inference error: {e}")
            return REGIME_UNKNOWN, 0.0

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_model(self):
        if not MODEL_PATH.exists():
            return
        try:
            with open(MODEL_PATH, "rb") as f:
                data = pickle.load(f)
            self._model = data["model"]
            self._state_label_map = data["label_map"]
            logger.info(f"[Regime] Loaded saved HMM from {MODEL_PATH}")
        except Exception as e:
            logger.warning(f"[Regime] Could not load saved model: {e}")
