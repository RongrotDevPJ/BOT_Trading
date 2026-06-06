"""
core/ml_signal.py
─────────────────────────────────────────────────────────────────────────────
LightGBM-based Entry Signal Classifier for XAUUSD Live Bot.

Design:
  - Trained on historical closed trades from trading_data.db
  - Features: RSI, ATR, EMA-distance, spread, session, tick-imbalance,
              ATR-ratio (current/20-period), day-of-week, hour-of-day
  - Target: 1 = profitable trade (profit > 0), 0 = losing trade
  - Inference: Returns probability [0.0, 1.0] — filter by ML_MIN_ENTRY_SCORE

Usage (in strategy.py):
    from core.ml_signal import SignalClassifier
    clf = SignalClassifier()
    score = clf.predict(features)
    if score < config.ML_MIN_ENTRY_SCORE: return  # Block low-quality entry

CPU: Inference < 0.5ms on single core. Training: ~10s on 1000 samples.
"""

import logging
import pickle
import sqlite3
import time
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Feature Engineering ────────────────────────────────────────────────────────

SESSION_MAP = {  # Broker server time → session code
    range(0, 7):   0,   # Asia / off-hours
    range(7, 12):  1,   # London morning
    range(12, 17): 2,   # NY overlap (highest liquidity)
    range(17, 21): 3,   # NY afternoon
    range(21, 24): 0,   # Asia pre-open
}

def get_session(hour: int) -> int:
    for r, code in SESSION_MAP.items():
        if hour in r:
            return code
    return 0


from typing import List, Dict, Optional

def build_features(rsi: float, atr: float, ema: float, price: float,
                   spread: int, tick_imbalance: Optional[float],
                   hour: int, weekday: int,
                   atr_20: Optional[float] = None) -> list:
    """
    Build feature vector for LightGBM inference.
    All values must be numeric — None → 0.0 (safe default).
    """
    ema_dist_pct = ((price - ema) / ema * 100) if ema and ema > 0 else 0.0
    atr_ratio = (atr / atr_20) if atr_20 and atr_20 > 0 else 1.0
    session = get_session(hour)
    imbalance = float(tick_imbalance) if tick_imbalance is not None else 0.0

    return [
        float(rsi),           # 0: RSI value
        float(atr),           # 1: ATR (current)
        float(ema_dist_pct),  # 2: % distance from EMA
        float(spread),        # 3: Spread in points
        imbalance,            # 4: Tick imbalance score [-1, +1]
        float(atr_ratio),     # 5: ATR ratio (volatility vs baseline)
        float(session),       # 6: Session code [0-3]
        float(weekday),       # 7: Day of week [0=Mon, 4=Fri]
        float(hour),          # 8: Hour of day [0-23]
    ]

FEATURE_NAMES = [
    "rsi", "atr", "ema_dist_pct", "spread", "tick_imbalance",
    "atr_ratio", "session", "weekday", "hour"
]


# ── Classifier ─────────────────────────────────────────────────────────────────

class SignalClassifier:
    """
    Wraps a trained LightGBM model for entry signal scoring.
    Falls back to neutral score (0.5) when model is not trained yet.
    """

    def __init__(self, model_path: str = "data/ml_models/lgbm_signal.pkl"):
        self.model_path = Path(model_path)
        self.model = None
        self._load_model()

    def _load_model(self):
        if self.model_path.exists():
            try:
                with open(self.model_path, "rb") as f:
                    self.model = pickle.load(f)
                logger.info(f"[MLSignal] Model loaded from {self.model_path}")
            except Exception as e:
                logger.warning(f"[MLSignal] Failed to load model: {e}. Will use neutral scoring.")
                self.model = None
        else:
            logger.info(f"[MLSignal] No model at {self.model_path}. Neutral score (0.5) until trained.")

    def predict(self, features: List[float]) -> float:
        """
        Returns probability [0.0, 1.0] that this entry will be profitable.
        0.5 = neutral (model not trained or feature error).
        """
        if self.model is None:
            return 0.5  # Neutral — don't block entries before first training

        try:
            import numpy as np
            X = np.array([features], dtype=float)
            prob = self.model.predict_proba(X)[0][1]  # P(class=1=profitable)
            return float(prob)
        except Exception as e:
            logger.warning(f"[MLSignal] Prediction error: {e}")
            return 0.5

    def is_model_ready(self) -> bool:
        return self.model is not None


class DirectionalClassifier:
    """
    Separate BUY and SELL signal classifiers.
    BUY model: trained only on BUY closed trades
    SELL model: trained only on SELL closed trades
    Falls back to neutral 0.5 if model not ready.
    """
    def __init__(self,
                 buy_model_path: str = "data/ml_models/lgbm_buy.pkl",
                 sell_model_path: str = "data/ml_models/lgbm_sell.pkl"):
        self.buy_clf = SignalClassifier(model_path=buy_model_path)
        self.sell_clf = SignalClassifier(model_path=sell_model_path)

    def predict_buy(self, features: list) -> float:
        """Returns BUY signal probability [0.0, 1.0]."""
        return self.buy_clf.predict(features)

    def predict_sell(self, features: list) -> float:
        """Returns SELL signal probability [0.0, 1.0]."""
        return self.sell_clf.predict(features)

    def is_buy_ready(self) -> bool:
        return self.buy_clf.is_model_ready()

    def is_sell_ready(self) -> bool:
        return self.sell_clf.is_model_ready()


# ── Trainer ────────────────────────────────────────────────────────────────────

class SignalTrainer:
    """
    Trains LightGBM on historical closed trades from SQLite.
    Call train() daily (or after N new closed trades).
    Saves model to disk for SignalClassifier to load.

    Minimum viable: 30 closed trades (otherwise skip training).
    """

    def __init__(self, db_path: str = "data/db/trading_data.db",
                 model_path: str = "data/ml_models/lgbm_signal.pkl"):
        self.db_path = Path(db_path)
        self.model_path = Path(model_path)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_training_data(self):
        """Load closed trades with ML-relevant features from DB."""
        sql = """
            SELECT
                rsi_value, atr_value, spread_at_entry,
                open_time_unix, profit,
                entry_signals
            FROM trades
            WHERE status = 'CLOSED'
              AND rsi_value IS NOT NULL
              AND atr_value IS NOT NULL
              AND profit IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 500
        """
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql).fetchall()
        conn.close()
        return rows

    def train(self) -> bool:
        """
        Returns True if model was trained and saved successfully.
        Skips if fewer than 30 samples available.
        """
        try:
            import lightgbm as lgb
            import numpy as np
        except ImportError:
            logger.error("[MLTrainer] lightgbm not installed. Run: pip install lightgbm")
            return False

        rows = self._load_training_data()
        if len(rows) < 30:
            logger.info(f"[MLTrainer] Only {len(rows)} samples. Need 30+ to train. Skipping.")
            return False

        X_list, y_list = [], []
        for row in rows:
            try:
                rsi   = float(row["rsi_value"] or 50)
                atr   = float(row["atr_value"] or 0)
                spread = float(row["spread_at_entry"] or 30)
                profit = float(row["profit"] or 0)
                ts     = int(row["open_time_unix"] or 0)

                # Parse EMA distance from entry_signals string if available
                ema_dist = 0.0
                imbalance = 0.0
                sig = row["entry_signals"] or ""
                for part in sig.split("|"):
                    part = part.strip()
                    if part.startswith("EMA:"):
                        try: ema_dist = float(part.split(":")[1])
                        except: pass
                    if part.startswith("TickImb:"):
                        try: imbalance = float(part.split(":")[1])
                        except: pass

                dt = datetime.fromtimestamp(ts) if ts > 0 else datetime.now()
                features = build_features(
                    rsi=rsi, atr=atr, ema=0.0, price=0.0,
                    spread=int(spread), tick_imbalance=imbalance,
                    hour=dt.hour, weekday=dt.weekday(), atr_20=None
                )
                # Override ema_dist_pct directly
                features[2] = ema_dist

                X_list.append(features)
                y_list.append(1 if profit > 0 else 0)
            except Exception as e:
                logger.debug(f"[MLTrainer] Skipped row: {e}")
                continue

        if len(X_list) < 30:
            logger.info(f"[MLTrainer] After filtering: {len(X_list)} samples. Need 30+.")
            return False

        import numpy as np
        X = np.array(X_list, dtype=float)
        y = np.array(y_list, dtype=int)

        win_count = y.sum()
        loss_count = len(y) - win_count
        scale_pos_weight = loss_count / win_count if win_count > 0 else 1.0

        model = lgb.LGBMClassifier(
            n_estimators=100,
            learning_rate=0.05,
            num_leaves=15,          # Small — prevents overfit on small dataset
            min_child_samples=5,
            scale_pos_weight=scale_pos_weight,
            random_state=42,
            n_jobs=1,               # Single thread — respect 1-core VPS
            verbose=-1
        )
        model.fit(X, y, feature_name=FEATURE_NAMES)

        with open(self.model_path, "wb") as f:
            pickle.dump(model, f)

        acc = (model.predict(X) == y).mean()
        logger.info(
            f"[MLTrainer] ✅ Trained on {len(X)} samples. "
            f"Train accuracy: {acc:.1%} | Win/Loss: {win_count}/{loss_count} | "
            f"Model saved: {self.model_path}"
        )
        return True


class DirectionalTrainer:
    """
    Trains separate BUY and SELL LightGBM models from closed trade DB.
    BUY model: trained on trades where side='BUY'
    SELL model: trained on trades where side='SELL'
    Minimum 20 samples per side to train.
    """
    def __init__(self,
                 db_path: str = "data/db/trading_data.db",
                 buy_model_path: str = "data/ml_models/lgbm_buy.pkl",
                 sell_model_path: str = "data/ml_models/lgbm_sell.pkl"):
        self.db_path = Path(db_path)
        self.buy_model_path = Path(buy_model_path)
        self.sell_model_path = Path(sell_model_path)
        self.buy_model_path.parent.mkdir(parents=True, exist_ok=True)
        self.sell_model_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_data_for_side(self, side: str):
        """Load closed trades for a specific side (BUY or SELL)."""
        sql = """
            SELECT rsi_value, atr_value, spread_at_entry,
                   open_time_unix, profit, entry_signals
            FROM trades
            WHERE status = 'CLOSED'
              AND side = ?
              AND rsi_value IS NOT NULL
              AND atr_value IS NOT NULL
              AND profit IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 500
        """
        import sqlite3
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, (side,)).fetchall()
        conn.close()
        return rows

    def _train_side(self, side: str, model_path) -> bool:
        """Train model for one side. Returns True if successful."""
        try:
            import lightgbm as lgb
            import numpy as np
        except ImportError:
            logger.error("[DirectionalTrainer] lightgbm not installed.")
            return False

        rows = self._load_data_for_side(side)
        MIN_SAMPLES = 20
        if len(rows) < MIN_SAMPLES:
            logger.info(f"[DirectionalTrainer] {side}: only {len(rows)} samples (need {MIN_SAMPLES}+). Skipping.")
            return False

        X_list, y_list = [], []
        for row in rows:
            try:
                rsi    = float(row["rsi_value"] or 50)
                atr    = float(row["atr_value"] or 0)
                spread = float(row["spread_at_entry"] or 30)
                profit = float(row["profit"] or 0)
                ts     = int(row["open_time_unix"] or 0)
                ema_dist = 0.0
                imbalance = 0.0
                sig = row["entry_signals"] or ""
                for part in sig.split("|"):
                    part = part.strip()
                    if part.startswith("EMA:"):
                        try: ema_dist = float(part.split(":")[1])
                        except: pass
                    if part.startswith("TickImb:"):
                        try: imbalance = float(part.split(":")[1])
                        except: pass
                dt = datetime.fromtimestamp(ts) if ts > 0 else datetime.now()
                features = build_features(
                    rsi=rsi, atr=atr, ema=0.0, price=0.0,
                    spread=int(spread), tick_imbalance=imbalance,
                    hour=dt.hour, weekday=dt.weekday(), atr_20=None
                )
                features[2] = ema_dist
                X_list.append(features)
                y_list.append(1 if profit > 0 else 0)
            except Exception as e:
                logger.debug(f"[DirectionalTrainer] Skipped row: {e}")
                continue

        if len(X_list) < MIN_SAMPLES:
            logger.info(f"[DirectionalTrainer] {side}: after filter {len(X_list)} samples. Skipping.")
            return False

        import numpy as np
        X = np.array(X_list, dtype=float)
        y = np.array(y_list, dtype=int)
        win_count = y.sum()
        loss_count = len(y) - win_count
        scale_pos_weight = loss_count / win_count if win_count > 0 else 1.0

        model = lgb.LGBMClassifier(
            n_estimators=100, learning_rate=0.05,
            num_leaves=15, min_child_samples=5,
            scale_pos_weight=scale_pos_weight,
            random_state=42, n_jobs=1, verbose=-1
        )
        model.fit(X, y, feature_name=FEATURE_NAMES)

        import pickle
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        acc = (model.predict(X) == y).mean()
        logger.info(
            f"[DirectionalTrainer] ✅ {side} model trained: {len(X)} samples, "
            f"acc={acc:.1%}, W/L={win_count}/{loss_count}, saved={model_path}"
        )
        return True

    def train(self) -> dict:
        """Train both BUY and SELL models. Returns {buy: bool, sell: bool}."""
        buy_ok  = self._train_side("BUY",  self.buy_model_path)
        sell_ok = self._train_side("SELL", self.sell_model_path)
        return {"buy": buy_ok, "sell": sell_ok}
