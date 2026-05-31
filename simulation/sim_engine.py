"""
simulation/sim_engine.py
────────────────────────────────────────────────────────────────────────────
Main Simulation Engine — XAUUSD Paper Trading Bot.

Runs two strategies in parallel:
  - Strategy 1: SMC/ICT (Smart Money Concepts)
  - Strategy 2: ML-Based (LightGBM classifier + HMM regime)

Both use the same MT5 real-time data but NO real orders are placed.
Results are stored to data/sim/sim_results.db.

Architecture:
  - Single thread (CPU-efficient for 1-core VPS)
  - 1-second loop (not 100ms like live bot — saves CPU for live bot)
  - HMM retrained every 6 hours
  - LightGBM retrained every 24 hours
  - Performance report printed every 60 minutes
  - All external API calls happen in background thread

Usage:
  python simulation/sim_engine.py
  python simulation/sim_engine.py --config-key NEWSAPI_KEY=your_key_here
"""

import sys
import os
import time
import signal
import logging
import argparse
import pickle
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import MetaTrader5 as mt5

import simulation.sim_config as cfg
from simulation.sim_db import SimDB
from simulation.sim_execution import VirtualExecution
from simulation.sim_strategy_smc import SMCStrategy
from simulation.api_clients.market_context import MarketContext

# ── Logging Setup ─────────────────────────────────────────────────────────────
Path(cfg.SIM_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(cfg.SIM_LOG_PATH, encoding="utf-8"),
    ]
)
logger = logging.getLogger("SimEngine")


# ── HMM Regime Detector (Simulation version) ──────────────────────────────────

class SimRegimeDetector:
    """Lightweight HMM for simulation — separate model from live bot."""

    def __init__(self):
        self._model = None
        self._label_map: dict = {}
        self._last_train = 0.0
        self._last_regime = "RANGING"
        Path("data/ml_models").mkdir(parents=True, exist_ok=True)

    def detect(self, symbol: str) -> str:
        if time.time() - self._last_train > cfg.HMM_RETRAIN_HOURS * 3600:
            self._train(symbol)
        return self._infer(symbol)

    def _train(self, symbol: str) -> bool:
        try:
            from simulation.ml_models.pure_hmm import GaussianHMM
            import numpy as np, math

            rates = mt5.copy_rates_from_pos(symbol, cfg.TIMEFRAME, 0, cfg.HMM_FEATURE_CANDLES + 20)
            if rates is None or len(rates) < 60:
                return False

            features = []
            for i in range(15, len(rates)):
                close = rates[i]["close"]
                prev  = rates[i-1]["close"]
                trs   = [max(rates[j]["high"] - rates[j]["low"],
                             abs(rates[j]["high"] - rates[j-1]["close"]),
                             abs(rates[j]["low"]  - rates[j-1]["close"]))
                         for j in range(i-14, i+1)]
                avg_tr = sum(trs[:-1]) / 14 if len(trs) > 1 else 1e-8
                log_ret  = math.log(close / prev) if prev > 0 else 0.0
                atr_ratio = (max(trs) / avg_tr) if avg_tr > 0 else 1.0
                spread_r  = min((rates[i].get("spread", 30) if hasattr(rates[i], 'get') else 30) / 100.0, 3.0)
                features.append([log_ret, atr_ratio, spread_r])

            X = np.array(features, dtype=float)
            model = GaussianHMM(n_components=3, covariance_type="diag",
                                n_iter=100, random_state=42)
            model.fit(X)

            means = model.means_
            # Label by atr_ratio mean (feature index 1)
            order = sorted(range(3), key=lambda i: means[i][1])
            self._label_map = {
                order[0]: "RANGING",
                order[1]: "TRENDING",
                order[2]: "VOLATILE",
            }
            self._model = model
            self._last_train = time.time()
            logger.info(f"[SimHMM] ✅ Trained. Labels: {self._label_map}")
            return True
        except Exception as e:
            logger.warning(f"[SimHMM] Training error: {e}")
            return False

    def _infer(self, symbol: str) -> str:
        if self._model is None:
            return self._last_regime
        try:
            import numpy as np, math
            rates = mt5.copy_rates_from_pos(symbol, cfg.TIMEFRAME, 0, 35)
            if rates is None or len(rates) < 20:
                return self._last_regime
            features = []
            for i in range(15, len(rates)):
                close, prev = rates[i]["close"], rates[i-1]["close"]
                trs = [max(rates[j]["high"] - rates[j]["low"],
                           abs(rates[j]["high"] - rates[j-1]["close"]),
                           abs(rates[j]["low"]  - rates[j-1]["close"]))
                       for j in range(i-14, i+1)]
                avg_tr = sum(trs[:-1]) / 14 or 1e-8
                features.append([
                    math.log(close / prev) if prev > 0 else 0.0,
                    max(trs) / avg_tr,
                    min((rates[i].get("spread", 30) if hasattr(rates[i], 'get') else 30) / 100.0, 3.0)
                ])
            X = np.array(features[-20:], dtype=float)
            state = int(self._model.predict(X)[-1])
            self._last_regime = self._label_map.get(state, "RANGING")
        except Exception as e:
            logger.debug(f"[SimHMM] Infer error: {e}")
        return self._last_regime


# ── ML Strategy Wrapper ────────────────────────────────────────────────────────

class MLStrategyWrapper:
    """
    LightGBM-based strategy for simulation.
    Uses same feature engineering as live bot's ml_signal.py.
    Trains on simulation's own closed trades.
    """

    STRATEGY_NAME = "ML"

    def __init__(self, db: SimDB, executor: VirtualExecution, market_ctx: MarketContext):
        self.db = db
        self.executor = executor
        self.market_ctx = market_ctx
        self._model = None
        self._last_train = 0.0
        self.open_positions = []
        self._last_entry = 0.0

    def update(self, tick, account: dict, rates):
        if tick is None or rates is None:
            return

        ask = float(tick.ask)
        bid = float(tick.bid)
        dt  = datetime.now(timezone.utc)
        atr = self._get_atr(rates)

        # 1. Manage existing positions
        self._manage(ask, bid, atr, dt, rates)

        # 2. Retrain model periodically
        if time.time() - self._last_train > cfg.LGBM_RETRAIN_HOURS * 3600:
            self._train()

        # 3. Check for new entry
        if len(self.open_positions) < 1 and time.time() - self._last_entry > 600:
            self._check_entry(ask, bid, atr, account, rates, dt)

    def _check_entry(self, ask, bid, atr, account, rates, dt):
        if self._model is None:
            return  # No model yet

        equity = account.get("equity", cfg.SIM_INITIAL_BALANCE)
        rsi    = self._get_rsi(rates)
        ema    = self._get_ema(rates)

        if rsi is None or ema is None:
            return

        from core.ml_signal import build_features
        spread = int((ask - bid) * 100)  # Real MT5 spread in points
        tick_imb = 0.0

        features = build_features(
            rsi=rsi, atr=atr, ema=ema, price=ask,
            spread=spread, tick_imbalance=tick_imb,
            hour=dt.hour, weekday=dt.weekday()
        )

        try:
            import numpy as np
            score = float(self._model.predict_proba(np.array([features]))[0][1])
        except Exception:
            return

        if score < cfg.ML_ENTRY_SCORE_MIN:
            return

        # Determine direction: if RSI < 40 → BUY, RSI > 60 → SELL
        if rsi < 40:
            side = "BUY"
            sl   = ask - cfg.ML_FIXED_SL_POINTS * 0.01
            tp   = ask + cfg.ML_FIXED_SL_POINTS * cfg.ML_TP_RATIO * 0.01
        elif rsi > 60:
            side = "SELL"
            sl   = bid + cfg.ML_FIXED_SL_POINTS * 0.01
            tp   = bid - cfg.ML_FIXED_SL_POINTS * cfg.ML_TP_RATIO * 0.01
        else:
            return  # RSI in neutral zone — skip

        from simulation.sim_execution import SimOrder, SimPosition
        lot = self._calc_lot(equity, cfg.ML_FIXED_SL_POINTS)

        order = SimOrder(
            strategy=self.STRATEGY_NAME, side=side, lot_size=lot,
            sl_price=sl, tp1_price=tp, ask=ask, bid=bid, atr=atr,
            regime=self.market_ctx.get_regime(), ml_score=score,
        )
        fill = self.executor.fill_order(order, ask, bid, atr, dt)
        if fill.success:
            pos_id = self.executor.get_next_id()
            pos = SimPosition(
                id=pos_id, strategy=self.STRATEGY_NAME, side=side, lot_size=lot,
                entry_price=fill.fill_price, sl_price=sl,
                tp1_price=tp, tp2_price=None, open_time=fill.fill_time,
            )
            self.open_positions.append(pos)
            self.db.insert_trade(
                strategy=self.STRATEGY_NAME, symbol="XAUUSD",
                side=side, open_time=fill.fill_time,
                entry_price=fill.fill_price, sl_price=sl, tp1_price=tp,
                lot_size=lot, simulated_spread=fill.simulated_spread,
                simulated_slippage=fill.simulated_slippage,
                atr_at_entry=atr, ml_score=score,
                regime_at_entry=self.market_ctx.get_regime(),
                rsi_at_entry=rsi, status="OPEN",
            )
            self._last_entry = time.time()
            logger.info(f"[ML] {'🟢' if side=='BUY' else '🔴'} {side} @ {fill.fill_price:.2f} | Score:{score:.3f} | SL:{sl:.2f} TP:{tp:.2f}")

    def _manage(self, ask, bid, atr, dt, rates):
        closed = []
        for pos in self.open_positions:
            self.executor.update_excursion(
                pos,
                current_high=float(rates[-1]["high"]) if rates is not None else ask,
                current_low=float(rates[-1]["low"]) if rates is not None else bid,
            )
            cp = bid if pos.side == "BUY" else ask
            reason = None
            if pos.side == "BUY":
                if cp >= pos.tp1_price: reason = "TP"
                elif cp <= pos.sl_price: reason = "SL"
            else:
                if cp <= pos.tp1_price: reason = "TP"
                elif cp >= pos.sl_price: reason = "SL"

            if reason:
                result = self.executor.close_position(pos, ask, bid, atr, dt, reason)
                if pos.db_id:
                    self.db.update_trade(
                        pos.db_id,
                        close_price=result["close_price"],
                        close_time=result["close_time"],
                        net_profit=result["net_profit"],
                        gross_profit=result["gross_profit"],
                        close_reason=reason,
                        mae_points=pos.mae_points,
                        mfe_points=pos.mfe_points,
                        status="CLOSED",
                    )
                pnl_sym = "✅" if result["net_profit"] > 0 else "❌"
                logger.info(f"[ML] {pnl_sym} {pos.side} closed ({reason}) | PnL: {result['net_profit']:+.2f} USC")
                closed.append(pos)

        for p in closed:
            if p in self.open_positions:
                self.open_positions.remove(p)

    def _train(self):
        trades = self.db.get_closed_trades(strategy=self.STRATEGY_NAME)
        if len(trades) < cfg.LGBM_MIN_SAMPLES:
            logger.info(f"[MLSim] {len(trades)} closed trades — need {cfg.LGBM_MIN_SAMPLES} to train.")
            return
        try:
            import lightgbm as lgb
            import numpy as np
            from core.ml_signal import build_features, get_session
            X_list, y_list = [], []
            for t in trades:
                try:
                    dt = datetime.fromisoformat(t["open_time"].replace("Z", "+00:00"))
                    f = build_features(
                        rsi=t.get("rsi_at_entry") or 50,
                        atr=t.get("atr_at_entry") or 0,
                        ema=0, price=t.get("entry_price") or 0,
                        spread=t.get("simulated_spread") or 30,
                        tick_imbalance=0,
                        hour=dt.hour, weekday=dt.weekday()
                    )
                    X_list.append(f)
                    y_list.append(1 if (t.get("net_profit") or 0) > 0 else 0)
                except Exception:
                    continue
            X = np.array(X_list); y = np.array(y_list)
            model = lgb.LGBMClassifier(n_estimators=100, num_leaves=15, n_jobs=1, verbose=-1)
            model.fit(X, y)
            self._model = model
            self._last_train = time.time()
            acc = (model.predict(X) == y).mean()
            logger.info(f"[MLSim] ✅ Model retrained: {len(X)} samples, accuracy={acc:.1%}")
        except Exception as e:
            logger.warning(f"[MLSim] Training error: {e}")

    def _get_rsi(self, rates, period=14):
        if rates is None or len(rates) < period + 2:
            return None
        closes = [float(r["close"]) for r in rates[-(period*3):]]
        diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in diffs]
        losses = [abs(d) if d < 0 else 0 for d in diffs]
        ag = sum(gains[:period]) / period
        al = sum(losses[:period]) / period
        if al == 0: return 100
        rs = ag / al
        rsi = 100 - (100 / (1 + rs))
        for i in range(period, len(diffs)):
            ag = (ag * (period-1) + gains[i]) / period
            al = (al * (period-1) + losses[i]) / period
            rs = ag / al if al > 0 else 0
            rsi = 100 - (100 / (1 + rs)) if al > 0 else 100
        return rsi

    def _get_ema(self, rates, period=200):
        if rates is None or len(rates) < period:
            return None
        closes = [float(r["close"]) for r in rates]
        ema = sum(closes[:period]) / period
        mult = 2 / (period + 1)
        for c in closes[period:]:
            ema = (c - ema) * mult + ema
        return ema

    def _get_atr(self, rates, period=14):
        if rates is None or len(rates) < period + 1:
            return 3.0
        trs = [max(rates[i]["high"] - rates[i]["low"],
                   abs(rates[i]["high"] - rates[i-1]["close"]),
                   abs(rates[i]["low"]  - rates[i-1]["close"]))
               for i in range(1, len(rates))]
        return float(sum(trs[-period:]) / period)

    def _calc_lot(self, equity, sl_points):
        risk = equity * (cfg.ML_MAX_RISK_PCT / 100)
        lot = risk / max(sl_points * 0.1, 0.1)
        return round(max(0.01, min(lot, 2.0)), 2)


# ── Main Engine ────────────────────────────────────────────────────────────────

def run_simulation():
    logger.info("=" * 60)
    logger.info(f"🚀 XAUUSD Simulation Bot Starting — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # Connect to MT5
    if not mt5.initialize():
        logger.error(f"❌ MT5 initialize failed: {mt5.last_error()}")
        sys.exit(1)

    symbol_info = mt5.symbol_info(cfg.SYMBOL)
    if symbol_info is None:
        logger.error(f"❌ Symbol {cfg.SYMBOL} not found!")
        mt5.shutdown()
        sys.exit(1)
    if not symbol_info.visible:
        mt5.symbol_select(cfg.SYMBOL, True)

    logger.info(f"✅ MT5 connected. Symbol: {cfg.SYMBOL}")

    # Initialize components
    db          = SimDB(cfg.SIM_DB_PATH)
    executor    = VirtualExecution(cfg)
    market_ctx  = MarketContext(newsapi_key=getattr(cfg, "NEWSAPI_KEY", ""))
    regime_det  = SimRegimeDetector()
    smc_strat   = SMCStrategy(cfg, executor, db, market_ctx)
    ml_strat    = MLStrategyWrapper(db, executor, market_ctx)

    market_ctx.start_background_updates()

    # Virtual account state
    balance = cfg.SIM_INITIAL_BALANCE
    equity  = cfg.SIM_INITIAL_BALANCE
    peak_equity = balance
    max_dd = 0.0

    last_report = time.time()
    last_snapshot = time.time()
    last_regime_check = 0.0

    # Graceful shutdown
    _running = [True]
    def _on_signal(signum, frame):
        logger.info("🛑 Shutdown signal received. Stopping simulation...")
        _running[0] = False
    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    logger.info(f"💰 Starting Balance: {balance:.2f} USC | Loop interval: {cfg.SIM_LOOP_SLEEP_SEC}s")
    logger.info("📊 Strategies: SMC/ICT + ML-LightGBM | Data: MT5 Live")

    while _running[0]:
        loop_start = time.time()

        try:
            # ── Fetch Market Data ──────────────────────────────────────────────
            tick = mt5.symbol_info_tick(cfg.SYMBOL)
            if tick is None:
                time.sleep(cfg.SIM_LOOP_SLEEP_SEC)
                continue

            # Fetch candles for indicators (M5 for entry, H1 for structure)
            rates_m5 = mt5.copy_rates_from_pos(cfg.SYMBOL, cfg.TIMEFRAME, 0, 500)
            if rates_m5 is None or len(rates_m5) < 50:
                time.sleep(cfg.SIM_LOOP_SLEEP_SEC)
                continue

            # ── Regime Detection ───────────────────────────────────────────────
            now = time.time()
            if now - last_regime_check > 300:  # Every 5 minutes
                regime = regime_det.detect(cfg.SYMBOL)
                market_ctx.set_regime(regime)
                last_regime_check = now

            # ── Account State (virtual P&L) ────────────────────────────────────
            all_positions = smc_strat.open_positions + ml_strat.open_positions
            floating_pnl = 0.0
            for pos in all_positions:
                close_price = tick.bid if pos.side == "BUY" else tick.ask
                pnl = executor.pnl_calc.calc_profit(
                    pos.entry_price, close_price, pos.side, pos.lot_size
                )
                floating_pnl += pnl

            equity = balance + floating_pnl
            peak_equity = max(peak_equity, equity)
            dd_pct = ((peak_equity - equity) / peak_equity * 100) if peak_equity > 0 else 0
            max_dd = max(max_dd, dd_pct)

            account = {
                "balance": balance, "equity": equity,
                "floating_pnl": floating_pnl,
            }

            # ── Check Economic Calendar (block during news) ────────────────────
            if not market_ctx.is_safe_to_trade():
                time.sleep(cfg.SIM_LOOP_SLEEP_SEC)
                continue

            # ── Strategy Updates ───────────────────────────────────────────────
            smc_strat.update(tick, account, rates_m5)
            ml_strat.update(tick, account, rates_m5)

            # ── Hourly Equity Snapshot ─────────────────────────────────────────
            if now - last_snapshot > 3600:
                bias = market_ctx.get_bias_summary()
                db.insert_snapshot(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    balance=round(balance, 4),
                    equity=round(equity, 4),
                    floating_pnl=round(floating_pnl, 4),
                    open_trades=len(all_positions),
                    regime=market_ctx.get_regime(),
                    dxy_value=bias.get("dxy"),
                    vix_value=bias.get("vix"),
                    gold_sentiment=bias.get("sentiment"),
                    cot_net_pos=bias.get("cot_net"),
                )
                last_snapshot = now

            # ── Performance Report ─────────────────────────────────────────────
            if now - last_report > cfg.SIM_REPORT_INTERVAL_MIN * 60:
                smc_stats = db.calculate_stats("SMC")
                ml_stats  = db.calculate_stats("ML")
                logger.info("─" * 55)
                logger.info(f"📊 SIMULATION REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                logger.info(f"   💰 Balance: {balance:.2f} USC | Equity: {equity:.2f} USC | Max DD: {max_dd:.1f}%")
                logger.info(f"   🌐 Regime: {market_ctx.get_regime()} | Sentiment: {market_ctx.get_gold_sentiment():+.2f}")
                if smc_stats:
                    logger.info(
                        f"   [SMC] Trades:{smc_stats['total_trades']} | "
                        f"WR:{smc_stats['win_rate']:.0f}% | PF:{smc_stats['profit_factor']:.2f} | "
                        f"Net:{smc_stats['net_profit']:+.2f} USC | Sharpe:{smc_stats['sharpe']:.2f}"
                    )
                if ml_stats:
                    logger.info(
                        f"   [ML]  Trades:{ml_stats['total_trades']} | "
                        f"WR:{ml_stats['win_rate']:.0f}% | PF:{ml_stats['profit_factor']:.2f} | "
                        f"Net:{ml_stats['net_profit']:+.2f} USC | Sharpe:{ml_stats['sharpe']:.2f}"
                    )
                logger.info("─" * 55)
                last_report = now

        except Exception as e:
            logger.error(f"[SimEngine] Loop error: {e}", exc_info=True)

        # ── Sleep ──────────────────────────────────────────────────────────────
        elapsed = time.time() - loop_start
        sleep_time = max(0, cfg.SIM_LOOP_SLEEP_SEC - elapsed)
        time.sleep(sleep_time)

    # ── Shutdown ───────────────────────────────────────────────────────────────
    logger.info("🛑 Simulation engine stopped.")
    market_ctx.stop()
    mt5.shutdown()

    # Final stats
    for strategy in ["SMC", "ML"]:
        stats = db.calculate_stats(strategy)
        if stats:
            logger.info(
                f"📊 Final [{strategy}]: Trades={stats['total_trades']} | "
                f"WR={stats['win_rate']:.0f}% | PF={stats['profit_factor']:.2f} | "
                f"Net={stats['net_profit']:+.2f} USC | Sharpe={stats['sharpe']:.2f} | Kelly={stats['kelly']:.1f}%"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="XAUUSD SMC/ML Simulation Bot")
    parser.add_argument("--newsapi-key", default="", help="NewsAPI key (optional, free tier)")
    args = parser.parse_args()
    if args.newsapi_key:
        cfg.NEWSAPI_KEY = args.newsapi_key
    run_simulation()
