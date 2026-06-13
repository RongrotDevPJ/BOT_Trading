import sys
from pathlib import Path
import logging
import time
import threading
import MetaTrader5 as ag
import config
# Add project root to path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from core.csv_logger import CSVLogger
from core.news_filter import is_safe_to_trade
from core.notifier import send_telegram_message
from core.indicator import IndicatorClient
from core.db_manager import DBManager
from core.ml_signal import SignalClassifier, build_features, get_session

class SmartGridStrategy:
    def __init__(self, db=None):
        self.logger = logging.getLogger("SmartGrid")
        self.csv_logger = CSVLogger(config.SYMBOL)
        self.indicator = IndicatorClient()  # Phase 5: Order Flow filter
        self.db = db if db is not None else DBManager()  # Phase 5: Kelly position sizing
        self.hedged_this_session = False # Prevent multiple hedges in the same run
        self.last_dynamic_log_time = 0 # Prevent log spam
        self.last_trend_log_time = 0
        self.last_gap_log_time = 0
        self.last_analysis_log_time = 0
        self.last_initial_log_time = 0 # Prevent initial entry log spam
        self.last_initial_entry_time = 0
        self.active_excursions = {}
        self.max_basket_pnl = -1000000.0
        self.last_trailing_log_time = 0
        self.last_diag_log_time = 0      # Entry diagnostic: log why entries blocked every 15min
        self._diag_blocked_count = 0    # Count of blocked entry attempts since last log

        # Phase 3: Enhanced Analytics (Cycle Life MAE/MFE)
        self.min_basket_pnl = 1000000.0
        self.max_basket_mfe = -1000000.0
        self.initial_signals = ""

        # Phase 5: Consecutive Loss Circuit Breaker
        self.consecutive_losses = 0
        self.cooldown_until = 0.0
        self._had_active_cycle = False

        # Atomic entry lock — prevents duplicate initial entries during MT5 latency
        self._entry_lock = threading.Lock()

        # ML Signal Classifier
        self._ml_clf = SignalClassifier(
            model_path=getattr(config, 'ML_MODEL_PATH', 'data/ml_models/lgbm_signal.pkl')
        )

    def is_max_drawdown_reached(self, executor, tick):
         """Checks if current account drawdown exceeds the max limit and performs Hedging if enabled."""
         account = ag.account_info()
         if account is None:
             self.logger.error("Failed to retrieve account info to check DD.")
             return False

         balance = account.balance
         equity = account.equity
         
         if balance > 0:
             drawdown_percent = ((balance - equity) / balance) * 100
             if drawdown_percent > config.MAX_DD_PERCENT:
                 if not self.hedged_this_session:
                     self.logger.critical(f"🔥 MAX DRAWDOWN REACHED! DD={drawdown_percent:.2f}% (Balance={balance:.2f}, Equity={equity:.2f})")
                     self.csv_logger.log_event(action="MAX DRAWDOWN", drawdown=drawdown_percent, balance=balance, equity=equity, notes="Auto-Hedge triggered" if getattr(config, 'ENABLE_HEDGE_ON_DD', False) else "")
                     
                     if getattr(config, 'ENABLE_HEDGE_ON_DD', False) and executor and tick:
                         self.execute_hedge(executor, tick)
                     else:
                         self.logger.critical("Bot is pausing operations without hedging.")
                     
                     self.hedged_this_session = True # Only trigger once per session to prevent spamming
                 return True
                 
         # Reset hedge flag if drawdown recovers (optional, but safer to require manual restart once hedged)
         return False

    def execute_hedge(self, executor, tick):
         """Calculates net lots and opens a hedge position to lock the account."""
         positions = self.get_positions()
         if not positions:
             return
             
         buy_lots = sum(p.volume for p in positions if p.type == 0)
         sell_lots = sum(p.volume for p in positions if p.type == 1)
         
         # Round to handle floating point precision
         buy_lots = round(buy_lots, 2)
         sell_lots = round(sell_lots, 2)
         
         net_lots = buy_lots - sell_lots
         
         if net_lots == 0:
             self.logger.info("Port is already fully hedged (Buy Lots = Sell Lots).")
             return
             
         self.logger.warning(f"Preparing to Hedge. Buy Lots: {buy_lots}, Sell Lots: {sell_lots}, Net: {net_lots}")
         
         # If Net > 0 (More Buys), we need to SELL
         if net_lots > 0:
             hedge_type = ag.ORDER_TYPE_SELL
             hedge_price = tick.bid
             hedge_volume = net_lots
         # If Net < 0 (More Sells), we need to BUY
         else:
             hedge_type = ag.ORDER_TYPE_BUY
             hedge_price = tick.ask
             hedge_volume = abs(net_lots)
             
         self.logger.critical(f"Executing HEDGE Order: Type={hedge_type}, Volume={hedge_volume}")
         
         # Send Hedge Order directly to executor without normal validations
         executor.send_order(config.SYMBOL, hedge_type, hedge_volume, hedge_price)

    def get_positions(self):
         """Gets all open positions managed by this bot."""
         positions = ag.positions_get(symbol=config.SYMBOL)
         if positions is None:
             return []
             
         # Filter by magic number
         bot_positions = [p for p in positions if p.magic == config.MAGIC_NUMBER]
         return bot_positions

    def calculate_basket_tp(self, positions, side, use_be=False):
        """
        Calculates the uniform basket Take Profit price for a group of positions.
        Ensures a minimum profit of MIN_CYCLE_PROFIT_USC is reached.
        """
        if not positions:
            return 0.0

        total_volume = sum(p.volume for p in positions)
        if total_volume == 0:
            return 0.0

        # Calculate break-even price (volume-weighted average price)
        total_value = sum(p.price_open * p.volume for p in positions)
        break_even_price = total_value / total_volume

        if use_be:
            return break_even_price

        symbol_info = ag.symbol_info(config.SYMBOL)
        tick_size = symbol_info.trade_tick_size
        tick_value = symbol_info.trade_tick_value # Profit of 1 lot per 1 tick move
        point = symbol_info.point
        
        # Calculate Dynamic Profit Target based on Initial Lot
        # 'positions' is already filtered by MAGIC_NUMBER in get_positions()
        oldest_pos = min(positions, key=lambda p: p.time)
        initial_lot = oldest_pos.volume
        divisor = max(0.01, getattr(config, 'DEFAULT_LOT', 0.1))
        dynamic_target = config.MIN_CYCLE_PROFIT_USC * (initial_lot / divisor)

        # Calculate movement needed for Dynamic Profit Target
        # Profit = (Move / TickSize) * Volume * TickValue
        # Move = (TargetProfit * TickSize) / (Volume * TickValue)
        required_move = (dynamic_target * tick_size) / (total_volume * tick_value)
        
        # Standard movement from config
        standard_move = config.BASKET_TP_POINTS * point
        
        # Ensure TP covers at least the minimum profit
        final_move = max(standard_move, required_move)

        if side == 0: # Buy basket
             basket_tp = break_even_price + final_move
        else: # Sell basket
             basket_tp = break_even_price - final_move
             
        return basket_tp

    def check_initial_entry(self, executor, current_rsi, current_ema, tick,
                            current_stoch=None, current_atr=None, equity=0,
                            current_regime="RANGING"):
        """Checks RSI, Stochastic, and EMA to determine if a first trade should be opened."""
        # --- SESSION FILTER ---
        if getattr(config, 'ENABLE_SESSION_FILTER', False):
            from core.time_filter import is_in_trading_session, get_utc_compensation
            if not is_in_trading_session(config.TRADING_HOURS_START, config.TRADING_HOURS_END,
                                          utc_compensation_hours=get_utc_compensation()):
                return False # Block new entries outside allowed hours

        # --- ATOMIC ENTRY LOCK ---
        # Prevents duplicate entries during MT5 latency window
        if not self._entry_lock.acquire(blocking=False):
            return  # Another entry is being processed

        try:
            self._check_initial_entry_inner(
                executor, current_rsi, current_ema, tick,
                current_stoch, current_atr, equity, current_regime
            )
        finally:
            self._entry_lock.release()

    def _check_initial_entry_inner(self, executor, current_rsi, current_ema, tick,
                                   current_stoch=None, current_atr=None, equity=0,
                                   current_regime="RANGING"):
        """Inner entry logic — called inside atomic lock."""
        if current_rsi is None or tick is None or current_ema is None:
            return

        if time.time() - self.last_initial_entry_time < 120.0:
            return

        # ── Entry Diagnostic: Log why we are NOT entering (every 15 minutes) ──
        _now = time.time()
        if _now - self.last_diag_log_time > 900:
            positions_check = self.get_positions()
            _reasons = []
            if current_rsi is not None and current_rsi > config.RSI_BUY_LEVEL:
                _reasons.append(f"RSI={current_rsi:.1f} > BUY_LEVEL={config.RSI_BUY_LEVEL}")
            if current_ema is not None and tick is not None and tick.ask <= current_ema:
                _reasons.append(f"Price({tick.ask:.2f}) <= EMA200({current_ema:.2f})")
            if len(positions_check) > 0:
                _reasons.append(f"Cycle active ({len(positions_check)} positions open)")
            if _now < self.cooldown_until:
                _reasons.append(f"Cooldown {int(self.cooldown_until - _now)}s remaining")
            if _reasons:
                self.logger.info(
                    f"[EntryDiag] No entry in last 15min. Blocked by: {' | '.join(_reasons)} "
                    f"| Blocked attempts: {self._diag_blocked_count}"
                )
            else:
                self.logger.info(
                    f"[EntryDiag] All filters PASS but no entry yet "
                    f"(RSI={current_rsi:.1f} <= {config.RSI_BUY_LEVEL}, Price={tick.ask:.2f} > EMA={current_ema:.2f})"
                )
            self.last_diag_log_time = _now
            self._diag_blocked_count = 0

        # Phase 5: Consecutive Loss Cooldown Gate
        if time.time() < self.cooldown_until:
            remaining = int(self.cooldown_until - time.time())
            _now = time.time()
            if _now - self.last_initial_log_time > 60:
                self.logger.warning(f"⏸️ [CircuitBreaker] Cooldown active for {config.SYMBOL}. New entries blocked for {remaining}s.")
                self.last_initial_log_time = _now
            return

        positions = self.get_positions()
        buy_positions = [p for p in positions if p.type == 0]
        sell_positions = [p for p in positions if p.type == 1]

        if len(buy_positions) > 0 or len(sell_positions) > 0:
            return  # Trade cycle already active

        # Max open positions guard — hard cap regardless of grid level
        max_open = getattr(config, 'MAX_GRID_LEVELS', 4)
        if len(positions) >= max_open:
            return

        # Check News Filter (Phase 2)
        if not is_safe_to_trade(config.SYMBOL):
            return

        # Check Trend Filter if enabled, otherwise assume trend matches
        enable_trend = getattr(config, 'ENABLE_TREND_FILTER', True)
        
        is_trend_buy = True
        is_trend_sell = True
        if enable_trend:
            is_trend_buy = tick.ask > current_ema
            is_trend_sell = tick.bid < current_ema
            
        is_rsi_buy = current_rsi <= config.RSI_BUY_LEVEL
        is_rsi_sell = current_rsi >= config.RSI_SELL_LEVEL

        # Stochastic Filter
        enable_stoch = getattr(config, 'ENABLE_STOCH_FILTER', False)
        is_stoch_buy = True
        is_stoch_sell = True
        stoch_str = ""

        if enable_stoch and current_stoch is not None:
             k, d = current_stoch
             if k is not None:
                 is_stoch_buy = k <= config.STOCH_BUY_LEVEL
                 is_stoch_sell = k >= config.STOCH_SELL_LEVEL
                 stoch_str = f"| Stoch={k:.2f}"

        if is_rsi_buy and is_trend_buy and is_stoch_buy:
            # Direction gate: check ENABLE_BUY flag
            if not getattr(config, 'ENABLE_BUY', True):
                return
            current_time = time.time()
            # In TRENDING regime, only allow BUY if trend is UP (price > EMA)
            if current_regime == "TRENDING" and tick.ask <= current_ema:
                self.logger.info(f"[Regime] TRENDING market — blocking counter-trend BUY (price<EMA).")
                return

            trend_str = f"| Price({tick.ask:.5f}) > EMA({current_ema:.5f})" if enable_trend else "(Trend Filter OFF)"
            if current_time - self.last_initial_log_time > 60:
                self.logger.info(f"✨ [Analysis] Initial BUY Entry Triggered: RSI={current_rsi:.2f} <= {config.RSI_BUY_LEVEL} {stoch_str} {trend_str}")
                self.last_initial_log_time = current_time

            # --- Tick Imbalance / Falling Knife Filter ---
            imb_threshold = getattr(config, 'TICK_IMBALANCE_THRESHOLD', 0.3)
            imb_lookback  = getattr(config, 'TICK_IMBALANCE_LOOKBACK_SEC', 60)
            tick_imb = self.indicator.get_tick_imbalance(config.SYMBOL, lookback_seconds=imb_lookback)
            if tick_imb is not None and tick_imb < -imb_threshold:
                self.logger.warning(
                    f"🔪 [Falling Knife] BUY blocked on {config.SYMBOL}. "
                    f"Imbalance={tick_imb:+.3f} < -{imb_threshold}. RSI={current_rsi:.2f}"
                )
                return

            # --- ML Signal Filter ---
            if getattr(config, 'ENABLE_ML_SIGNAL_FILTER', True) and self._ml_clf.is_model_ready():
                s_info = ag.symbol_info(config.SYMBOL)
                spread_pts = s_info.spread if s_info else 30
                dt = __import__('datetime').datetime.now()
                features = build_features(
                    rsi=current_rsi, atr=current_atr or 0,
                    ema=current_ema, price=tick.ask,
                    spread=spread_pts, tick_imbalance=tick_imb,
                    hour=dt.hour, weekday=dt.weekday()
                )
                ml_score = self._ml_clf.predict(features)
                min_score = getattr(config, 'ML_MIN_ENTRY_SCORE', 0.55)
                if ml_score < min_score:
                    self.logger.info(
                        f"[ML] BUY blocked — score={ml_score:.3f} < {min_score}. "
                        f"RSI={current_rsi:.2f}"
                    )
                    return
                self.logger.info(f"[ML] BUY signal quality: {ml_score:.3f} ≥ {min_score} ✓")

            initial_lot = self.get_dynamic_lot(0, equity)
            
            # Capture Initial Entry Signals for Analytics
            imb_str = f" | TickImb:{tick_imb:+.3f}" if tick_imb is not None else ""
            self.initial_signals = f"RSI:{current_rsi:.2f} | ATR:{current_atr:.5f} | EMA:{current_ema:.5f}{imb_str}"
            if enable_stoch and current_stoch:
                self.initial_signals += f" | Stoch:{current_stoch[0]:.2f}"

            # Pre-stamp timer BEFORE send_order to block duplicate entries even if MT5 returns None
            self.last_initial_entry_time = time.time()
            result = executor.send_order(
                config.SYMBOL, ag.ORDER_TYPE_BUY, initial_lot, tick.ask, 
                atr_value=current_atr, rsi_value=current_rsi, 
                grid_level=1, cycle_id=None,
                entry_signals=self.initial_signals
            )
            if result:
                self.csv_logger.log_event(action="Initial Entry", side="BUY", price=tick.ask, rsi=current_rsi, ema=current_ema, lot_size=initial_lot, ticket=result.order, notes=stoch_str)
            else:
                self.logger.warning(f"[InitialEntry] BUY order failed or rejected by MT5 for {config.SYMBOL}. Cooldown still active (120s).")
            
        elif is_rsi_sell and is_trend_sell and is_stoch_sell:
            # Direction gate: check ENABLE_SELL flag
            if not getattr(config, 'ENABLE_SELL', True):
                self.logger.debug("[Direction] SELL entry blocked — ENABLE_SELL=False (BUY Only Mode)")
                return
            current_time = time.time()

            # ── Smart SELL: Regime-Aware Gate ──────────────────────────────────
            # Requires ALL 3 conditions simultaneously (from audit findings):
            #   1. Regime = BEAR or RANGING (not TRENDING UP)
            #   2. Price < EMA200 (confirmed downtrend)
            #   3. RSI >= RSI_SELL_LEVEL (overbought)
            if getattr(config, 'SMART_SELL_REQUIRE_REGIME_BEAR', False):
                if current_regime not in ("BEAR", "RANGING", "UNKNOWN"):
                    self.logger.info(
                        f"[SmartSELL] Blocked — Regime={current_regime} (need BEAR/RANGING). "
                        f"RSI={current_rsi:.2f}"
                    )
                    return
            if getattr(config, 'SMART_SELL_REQUIRE_BELOW_EMA', False):
                if tick.bid >= current_ema:
                    self.logger.info(
                        f"[SmartSELL] Blocked — Price({tick.bid:.2f}) >= EMA({current_ema:.2f}). "
                        f"Cannot SELL in uptrend."
                    )
                    return

            # Legacy regime check (kept for backward compat)
            if current_regime == "TRENDING" and tick.bid >= current_ema:
                self.logger.info(f"[Regime] TRENDING market — blocking counter-trend SELL (price>EMA).")
                return

            trend_str = f"| Price({tick.bid:.5f}) < EMA({current_ema:.5f})" if enable_trend else "(Trend Filter OFF)"
            if current_time - self.last_initial_log_time > 60:
                self.logger.info(f"✨ [Analysis] Initial SELL Entry Triggered: RSI={current_rsi:.2f} >= {config.RSI_SELL_LEVEL} {stoch_str} {trend_str}")
                self.last_initial_log_time = current_time

            # --- Tick Imbalance / Buying Surge Filter ---
            imb_threshold = getattr(config, 'TICK_IMBALANCE_THRESHOLD', 0.3)
            imb_lookback  = getattr(config, 'TICK_IMBALANCE_LOOKBACK_SEC', 60)
            tick_imb = self.indicator.get_tick_imbalance(config.SYMBOL, lookback_seconds=imb_lookback)
            if tick_imb is not None and tick_imb > imb_threshold:
                self.logger.warning(
                    f"🚀 [Buying Surge] SELL blocked on {config.SYMBOL}. "
                    f"Imbalance={tick_imb:+.3f} > +{imb_threshold}. RSI={current_rsi:.2f}"
                )
                return

            # --- ML Signal Filter ---
            if getattr(config, 'ENABLE_ML_SIGNAL_FILTER', True) and self._ml_clf.is_model_ready():
                s_info = ag.symbol_info(config.SYMBOL)
                spread_pts = s_info.spread if s_info else 30
                dt = __import__('datetime').datetime.now()
                features = build_features(
                    rsi=current_rsi, atr=current_atr or 0,
                    ema=current_ema, price=tick.bid,
                    spread=spread_pts, tick_imbalance=tick_imb,
                    hour=dt.hour, weekday=dt.weekday()
                )
                ml_score = self._ml_clf.predict(features)
                min_score = getattr(config, 'ML_MIN_ENTRY_SCORE', 0.55)
                if ml_score < min_score:
                    self.logger.info(
                        f"[ML] SELL blocked — score={ml_score:.3f} < {min_score}. "
                        f"RSI={current_rsi:.2f}"
                    )
                    return
                self.logger.info(f"[ML] SELL signal quality: {ml_score:.3f} ≥ {min_score} ✓")

            initial_lot = self.get_dynamic_lot(1, equity)
            
            # Capture Initial Entry Signals for Analytics
            imb_str = f" | TickImb:{tick_imb:+.3f}" if tick_imb is not None else ""
            self.initial_signals = f"RSI:{current_rsi:.2f} | ATR:{current_atr:.5f} | EMA:{current_ema:.5f}{imb_str}"
            if enable_stoch and current_stoch:
                self.initial_signals += f" | Stoch:{current_stoch[0]:.2f}"

            # Pre-stamp timer BEFORE send_order to block duplicate entries even if MT5 returns None
            self.last_initial_entry_time = time.time()
            result = executor.send_order(
                config.SYMBOL, ag.ORDER_TYPE_SELL, initial_lot, tick.bid, 
                atr_value=current_atr, rsi_value=current_rsi, 
                grid_level=1, cycle_id=None,
                entry_signals=self.initial_signals
            )
            if result:
                self.csv_logger.log_event(action="Initial Entry", side="SELL", price=tick.bid, rsi=current_rsi, ema=current_ema, lot_size=initial_lot, ticket=result.order, notes=stoch_str)
            else:
                self.logger.warning(f"[InitialEntry] SELL order failed or rejected by MT5 for {config.SYMBOL}. Cooldown still active (120s).")

    def get_dynamic_grid_distance(self, num_positions, current_atr):
         """Calculates distance based on ATR * Multiplier or Fixed Points with smart multipliers."""
         # Use ATR if enabled, else fallback to fixed GRID_DISTANCE_POINTS
         if getattr(config, 'ENABLE_ATR_DISTANCE', False) and current_atr is not None:
             point = ag.symbol_info(config.SYMBOL).point
             atr_points_distance = (current_atr * config.ATR_MULTIPLIER) / point
             base_distance = max(config.MIN_GRID_DISTANCE_POINTS, atr_points_distance)
         else:
             base_distance = config.GRID_DISTANCE_POINTS
             
         # Phase 2: Exponential Dynamic Grid Distance Multiplier
         multiplier = config.GRID_DISTANCE_MULTIPLIER ** num_positions
             
         current_time = time.time()
         if current_time - self.last_dynamic_log_time > 60:
             atr_str = f"{current_atr:.5f}" if current_atr is not None else "0"
             self.logger.info(f"🔍 [System Check] Dynamic Distance Layer {num_positions + 1}: BaseDist={base_distance:.1f}pts, Multiplier={multiplier:.2f}x => Required Distance={base_distance * multiplier:.1f}pts (ATR={atr_str})")
             self.last_dynamic_log_time = current_time
             
         return base_distance * multiplier

    def calculate_dynamic_lot(self, current_equity):
        """
        Phase 5: Fractional Kelly Criterion position sizing.

        Decision tree:
          1. AUTO_LOT disabled        → return DEFAULT_LOT (manual override)
          2. < KELLY_MIN_TRADES hist  → return linear equity lot (warm-up fallback)
          3. Kelly % <= 0             → edge has decayed; return MIN_LOT (sit tight)
          4. Normal Kelly path        → fractional Kelly, clamped to [MIN_LOT, MAX_LOT]

        Formula:
            Kelly%  = W - ((1 - W) / R)
            Adj%    = Kelly% * KELLY_FRACTION          # e.g. 0.25 = "quarter Kelly"
            Adj%    = min(Adj%, KELLY_MAX_FRACTION)    # hard cap for safety
            lot_raw = current_equity * Adj% * (BASE_LOT / BASE_EQUITY)
        """
        if not getattr(config, 'AUTO_LOT', False):
            return config.DEFAULT_LOT

        kelly_fraction     = getattr(config, 'KELLY_FRACTION',     0.25)
        kelly_min_trades   = getattr(config, 'KELLY_MIN_TRADES',   10)
        kelly_max_fraction = getattr(config, 'KELLY_MAX_FRACTION', 0.20)

        # --- Pull 30-day stats from DB ---
        stats = self.db.get_symbol_stats_30d(config.SYMBOL)

        # Calculate normal linear lot based on equity (e.g. 5000 -> 0.10)
        raw_linear_lot = (current_equity / config.BASE_EQUITY) * config.BASE_LOT
        base_linear_lot = max(config.MIN_LOT, min(round(raw_linear_lot, 2), config.MAX_LOT))

        # Fallback 1: insufficient history → warm-up with linear equity sizing
        if stats is None or stats["total_trades"] < kelly_min_trades:
            trades_seen = stats["total_trades"] if stats else 0
            self.logger.info(
                f"[Kelly] {config.SYMBOL}: Only {trades_seen} closed trades "
                f"(need {kelly_min_trades}). Using linear equity fallback."
            )
            return base_linear_lot

        W = stats["win_rate"]
        R = stats["risk_reward"]

        # --- Core Kelly formula ---
        kelly_pct = W - ((1.0 - W) / R)

        # Fallback 2: negative Kelly → strategy has no edge right now → lock at base linear lot
        if kelly_pct <= 0:
            self.logger.warning(
                f"[Kelly] {config.SYMBOL}: Negative Kelly ({kelly_pct:.4f}) — "
                f"W={W:.3f}, R={R:.3f}. Reverting to base linear lot: {base_linear_lot}."
            )
            return base_linear_lot

        # Apply fractional Kelly and hard cap
        adjusted_pct = kelly_pct * kelly_fraction
        adjusted_pct = min(adjusted_pct, kelly_max_fraction)

        # Base lot is the floor. Kelly provides a proportional boost.
        # kelly_bonus_multiplier ranges from 0.0 to 1.0 (0% to +100% boost)
        kelly_bonus_multiplier = adjusted_pct / kelly_max_fraction
        final_multiplier = 1.0 + kelly_bonus_multiplier
        
        lot_raw = base_linear_lot * final_multiplier
        calculated_lot = round(lot_raw, 2)
        final_lot      = max(config.MIN_LOT, min(calculated_lot, config.MAX_LOT))

        self.logger.info(
            f"[Kelly] {config.SYMBOL}: W={W:.3f} | R={R:.3f} | "
            f"Kelly%={kelly_pct:.4f} | BonusMultiplier={final_multiplier:.2f}x | "
            f"Equity={current_equity:.2f} | Lot={final_lot}"
        )
        return final_lot

    def get_dynamic_lot(self, num_positions, equity):
         """Calculates lot size based on equity and grid multiplier."""
         base_lot = self.calculate_dynamic_lot(equity)

         # If 1 open trade, num_positions=1, next lot is base * multiplier ^ 1
         lot = base_lot * (config.LOT_MULTIPLIER ** num_positions)
         lot = round(lot, 2) # Format for Cent accounts (2 decimal places)
         
         if lot > config.MAX_LOT:
             lot = config.MAX_LOT
             
         return max(config.MIN_LOT, lot)

    def needs_new_grid_level(self, positions, current_price, side, current_atr, current_ema):
        """
        Determines if price has moved far enough to open a new grid level.
        Positions should be sorted by time (oldest first or newest first) to find the LAST opened level.
        """
        if not positions or current_ema is None:
           return False

        # Hard Grid Level Capping
        if len(positions) >= getattr(config, 'MAX_GRID_LEVELS', 10):
            return False

        # Find the most recently opened position in this direction
        latest_position = max(positions, key=lambda p: p.time)
        
        # Cooldown check: prevent opening trades too quickly
        s_info = ag.symbol_info(config.SYMBOL)
        if s_info is not None:
             current_time_sec = s_info.time
             time_since_last_pos = current_time_sec - latest_position.time
             if time_since_last_pos < (config.COOLDOWN_MINUTES * 60):
                  return False

        point = s_info.point if s_info else 0.00001
        distance_points = abs(current_price - latest_position.price_open) / point
        
        required_distance = self.get_dynamic_grid_distance(len(positions), current_atr)

        # Crash Recovery / Max Gap check
        max_allowed_distance = required_distance * config.MAX_GAP_MULTIPLIER
        if distance_points > max_allowed_distance:
             current_time = time.time()
             if current_time - self.last_gap_log_time > 60:
                 self.logger.warning(f"Price gapped too far! ({distance_points:.1f} > {max_allowed_distance:.1f} max). Pausing safely.")
                 self.last_gap_log_time = current_time
             return False

        if distance_points >= required_distance:
            enable_trend = getattr(config, 'ENABLE_TREND_FILTER', True)
            # GRID AVERAGING: EMA filter is optional on grid levels (default OFF)
            # Only initial entry should be filtered by EMA trend.
            # Once a position is open, the grid MUST be allowed to average regardless of trend.
            enable_trend_on_grid = getattr(config, 'ENABLE_TREND_FILTER_ON_GRID', False)
            
            # Check direction of movement relative to side
            if side == 0 and current_price < latest_position.price_open:
                # Price dropped below last buy order.
                # Apply EMA filter ONLY if ENABLE_TREND_FILTER_ON_GRID is True
                if not (enable_trend and enable_trend_on_grid) or current_price > current_ema:
                    current_time = time.time()
                    if current_time - self.last_analysis_log_time > 60:
                        atr_str = f"{current_atr:.5f}" if current_atr is not None else "0"
                        ema_note = f"EMA={current_ema:.5f} [Grid EMA Filter={'ON' if enable_trend_on_grid else 'OFF'}]"
                        self.logger.info(f"✨ [Analysis] BUY Grid Open: Price={current_price:.5f}, LastBuyPrice={latest_position.price_open:.5f}, Moved={distance_points:.1f}pts, Required={required_distance:.1f}pts, ATR={atr_str}, {ema_note}")
                        self.last_analysis_log_time = current_time
                    return True
                else:
                    current_time = time.time()
                    if current_time - self.last_trend_log_time > 60:
                        self.logger.info(f"🚫 [Trend Filter ON GRID] Blocked BUY Grid: Price({current_price:.5f}) is BELOW EMA({current_ema:.5f}). Dist={distance_points:.1f}pts")
                        self.last_trend_log_time = current_time
            elif side == 1 and current_price > latest_position.price_open:
                # Price rose above last sell order.
                # Apply EMA filter ONLY if ENABLE_TREND_FILTER_ON_GRID is True
                if not (enable_trend and enable_trend_on_grid) or current_price < current_ema:
                    current_time = time.time()
                    if current_time - self.last_analysis_log_time > 60:
                        atr_str = f"{current_atr:.5f}" if current_atr is not None else "0"
                        ema_note = f"EMA={current_ema:.5f} [Grid EMA Filter={'ON' if enable_trend_on_grid else 'OFF'}]"
                        self.logger.info(f"✨ [Analysis] SELL Grid Open: Price={current_price:.5f}, LastSellPrice={latest_position.price_open:.5f}, Moved={distance_points:.1f}pts, Required={required_distance:.1f}pts, ATR={atr_str}, {ema_note}")
                        self.last_analysis_log_time = current_time
                    return True
                else:
                    current_time = time.time()
                    if current_time - self.last_trend_log_time > 60:
                        self.logger.info(f"🚫 [Trend Filter ON GRID] Blocked SELL Grid: Price({current_price:.5f}) is ABOVE EMA({current_ema:.5f}). Dist={distance_points:.1f}pts")
                        self.last_trend_log_time = current_time
                
        return False

    def check_grid_logic(self, executor, current_atr, current_ema, equity=0, current_regime="RANGING"):
        """Core logic to check positions and open new grid levels."""
        # Regime-aware MAX_GRID_LEVELS
        regime_max_levels = getattr(config, 'MAX_GRID_LEVELS', 10)
        if (current_regime == "TRENDING" and
                getattr(config, 'ENABLE_REGIME_FILTER', True)):
            regime_max_levels = min(
                regime_max_levels,
                getattr(config, 'REGIME_TRENDING_MAX_LEVELS', 2)
            )
        
        tick = ag.symbol_info_tick(config.SYMBOL)
        if tick is None:
            return # Probably weekend/market closed

        s_info = ag.symbol_info(config.SYMBOL)
        if s_info is None:
            return
            
        if self.is_max_drawdown_reached(executor, tick):
             return # Skip processing if max DD hit (Hedging is handled inside)

        positions = self.get_positions()
        buy_positions = [p for p in positions if p.type == 0]
        sell_positions = [p for p in positions if p.type == 1]
        
        current_ask = tick.ask
        current_bid = tick.bid

        # Process Buy Grid
        if buy_positions:
            max_levels = regime_max_levels
            if self.needs_new_grid_level(buy_positions, current_ask, side=0, current_atr=current_atr, current_ema=current_ema):
                dynamic_lot = self.get_dynamic_lot(len(buy_positions), equity)
                self.logger.info(f"🛒 Executing BUY Grid. Level: {len(buy_positions)+1}, Lot: {dynamic_lot}")
                cycle_id_val = str(min(buy_positions, key=lambda x: x.time).ticket)
                result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask, atr_value=current_atr, rsi_value=None, grid_level=len(buy_positions)+1, cycle_id=cycle_id_val)
                if result:
                    latest_p = max(buy_positions, key=lambda p: p.time)
                    dist_moved = abs(current_ask - latest_p.price_open) / s_info.point
                    req_dist = self.get_dynamic_grid_distance(len(buy_positions), current_atr)
                    self.csv_logger.log_event(action="Grid Open", side="BUY", price=current_ask, atr=current_atr, ema=current_ema, grid_level=len(buy_positions)+1, lot_size=dynamic_lot, distance_moved=dist_moved, required_distance=req_dist, ticket=result.order)
                
            # TP Management
            use_be = len(buy_positions) >= max_levels
            if use_be:
                self.logger.warning(f"⚠️ MAX GRID LEVELS REACHED ({len(buy_positions)}). Shifting BUY TP to Break-Even.")
            
            if not config.USE_TRAILING_STOP or use_be:
                new_tp = self.calculate_basket_tp(buy_positions, side=0, use_be=use_be)
                self._update_tps_if_needed(executor, buy_positions, new_tp)

        # Process Sell Grid
        if sell_positions:
             max_levels = regime_max_levels
             if self.needs_new_grid_level(sell_positions, current_bid, side=1, current_atr=current_atr, current_ema=current_ema):
                 dynamic_lot = self.get_dynamic_lot(len(sell_positions), equity)
                 self.logger.info(f"🛒 Executing SELL Grid. Level: {len(sell_positions)+1}, Lot: {dynamic_lot}")
                 cycle_id_val = str(min(sell_positions, key=lambda x: x.time).ticket)
                 result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, dynamic_lot, current_bid, atr_value=current_atr, rsi_value=None, grid_level=len(sell_positions)+1, cycle_id=cycle_id_val)
                 if result:
                     latest_p = max(sell_positions, key=lambda p: p.time)
                     dist_moved = abs(current_bid - latest_p.price_open) / s_info.point
                     req_dist = self.get_dynamic_grid_distance(len(sell_positions), current_atr)
                     self.csv_logger.log_event(action="Grid Open", side="SELL", price=current_bid, atr=current_atr, ema=current_ema, grid_level=len(sell_positions)+1, lot_size=dynamic_lot, distance_moved=dist_moved, required_distance=req_dist, ticket=result.order)
                 
             use_be = len(sell_positions) >= max_levels
             if use_be:
                 self.logger.warning(f"⚠️ MAX GRID LEVELS REACHED ({len(sell_positions)}). Shifting SELL TP to Break-Even.")
 
             if not config.USE_TRAILING_STOP or use_be:
                 new_tp = self.calculate_basket_tp(sell_positions, side=1, use_be=use_be)
                 self._update_tps_if_needed(executor, sell_positions, new_tp)

    def check_basket_trailing(self, executor, tick, current_atr=None):
        """
        Tracks total floating PnL and applies a trailing stop.
        Also tracks Cycle-Life MAE and MFE for Analytics.
        """
        positions = self.get_positions()
        if not positions:
            # Cycle ended externally (SL, ghost TP, manual close)
            # If trailing was NEVER activated, the cycle never profited = potential loss
            if self._had_active_cycle and self.max_basket_pnl == -1000000.0:
                self.consecutive_losses += 1
                self.logger.warning(f"⚠️ [CircuitBreaker] Cycle on {config.SYMBOL} ended without profit peak. Consecutive losses: {self.consecutive_losses}")
                max_losses = getattr(config, 'MAX_CONSECUTIVE_LOSSES', 3)
                if self.consecutive_losses >= max_losses:
                    msg = (f"🚨 CIRCUIT BREAKER TRIGGERED on {config.SYMBOL}! "
                           f"{max_losses} consecutive losing cycles detected. "
                           f"Entering 1-hour cooldown.")
                    self.logger.critical(msg)
                    send_telegram_message(msg)
                    self.cooldown_until = time.time() + 3600
                    self.consecutive_losses = 0
            self._had_active_cycle = False
            self.max_basket_pnl = -1000000.0 # Reset trailing trigger
            self.min_basket_pnl = 1000000.0  # Reset MAE
            self.max_basket_mfe = -1000000.0 # Reset MFE
            return

        self._had_active_cycle = True  # Positions exist: cycle is active

        # 1. Calculate Dynamic Profit Target (Trigger)
        oldest_pos = min(positions, key=lambda p: p.time)
        initial_lot = oldest_pos.volume
        divisor = max(0.01, getattr(config, 'DEFAULT_LOT', 0.1))
        dynamic_target = config.MIN_CYCLE_PROFIT_USC * (initial_lot / divisor)
        
        # 2. Calculate Trailing Step based on ATR
        total_volume = sum(p.volume for p in positions)
        s_info = ag.symbol_info(config.SYMBOL)
        
        if current_atr and s_info:
            # ATR_USD_Value = (ATR_Value / tick_size) * tick_value * total_volume
            atr_usd = (current_atr / s_info.trade_tick_size) * s_info.trade_tick_value * total_volume
            trailing_step = atr_usd * getattr(config, 'ATR_MULTIPLIER', 1.5)
            is_dynamic = True
        else:
            trailing_step = getattr(config, 'BASKET_TRAILING_STEP_USD', 5.0)
            is_dynamic = False

        # 3. Calculate current PnL (including commission/swap)
        total_pnl = sum(p.profit + getattr(p, 'commission', 0.0) + p.swap for p in positions)
        
        # 3.1 Update Cycle-Life MAE/MFE
        self.max_basket_mfe = max(self.max_basket_mfe, total_pnl)
        self.min_basket_pnl = min(self.min_basket_pnl, total_pnl)
        
        # 4. Activate/Update Trailing
        if total_pnl >= dynamic_target:
            if total_pnl > self.max_basket_pnl:
                if self.max_basket_pnl == -1000000.0:
                    self.logger.info(f"🚀 Basket Trailing ACTIVATED for {config.SYMBOL} - Target: {dynamic_target:.2f} USC")
                
                self.max_basket_pnl = total_pnl
                
                curr_time = time.time()
                if curr_time - self.last_trailing_log_time > 60: # Log every minute if moving
                    dyn_str = "[DYNAMIC]" if is_dynamic else "[STATIC]"
                    exit_pnl = self.max_basket_pnl - trailing_step
                    self.logger.info(f"👻 {config.SYMBOL} Trailing Updated: Max PnL: {self.max_basket_pnl:.2f} USC | Current PnL: {total_pnl:.2f} USC | Exit Point: {exit_pnl:.2f} USC")
                    self.last_trailing_log_time = curr_time
                    
        # 5. Check if trailing stop is hit
        if self.max_basket_pnl > -1000000.0:
            exit_point = max(1.0, self.max_basket_pnl - trailing_step)
            if total_pnl < exit_point:
                self.logger.critical(f"🚀 [Basket Trailing] TRAILING STOP HIT! Current PnL: ${total_pnl:.2f} < Exit (${exit_point:.2f}). Closing all {len(positions)} positions.")
                for p in positions:
                    executor.close_position(p, tick, is_trailing_stop=True)
                    self.active_excursions.pop(p.ticket, None)
                self._close_cycle_cleanup(executor, positions, tick, total_pnl)
                return

        # 5b. HARD BASKET STOP LOSS (NEW) — prevents catastrophic loss in strong trends
        hard_stop = getattr(config, 'BASKET_HARD_STOP_USC', -80.0)
        if total_pnl <= hard_stop:
            self.logger.critical(
                f"🚨 [HardBasketSL] Basket loss ${total_pnl:.2f} <= Hard Stop ${hard_stop:.2f}. "
                f"Closing ALL {len(positions)} positions to prevent further loss."
            )
            send_telegram_message(
                f"🚨 <b>Hard Basket SL Hit: {config.SYMBOL}</b>\n"
                f"Loss: ${total_pnl:.2f} USC exceeded limit ${hard_stop:.2f} USC\n"
                f"Closing {len(positions)} position(s) now."
            )
            for p in positions:
                executor.close_position(p, tick, is_trailing_stop=True)
                self.active_excursions.pop(p.ticket, None)
            self._close_cycle_cleanup(executor, positions, tick, total_pnl)

    def _close_cycle_cleanup(self, executor, positions, tick, total_pnl):
        """Common cleanup after any basket closure (trailing, hard SL, etc)."""
        max_losses = getattr(config, 'MAX_CONSECUTIVE_LOSSES', 3)
        if total_pnl <= 0:
            self.consecutive_losses += 1
            self.logger.warning(f"⚠️ [CircuitBreaker] Losing cycle on {config.SYMBOL}. Consecutive: {self.consecutive_losses}/{max_losses}")
            if self.consecutive_losses >= max_losses:
                msg = (
                    f"🚨 CIRCUIT BREAKER TRIGGERED on {config.SYMBOL}! "
                    f"{max_losses} consecutive losing cycles. Entering 1-hour cooldown."
                )
                self.logger.critical(msg)
                send_telegram_message(msg)
                self.cooldown_until = time.time() + 3600
                self.consecutive_losses = 0
        else:
            if self.consecutive_losses > 0:
                self.logger.info(f"✅ [CircuitBreaker] Winning cycle on {config.SYMBOL}. Counter reset.")
            self.consecutive_losses = 0
        self._had_active_cycle = False
        self.max_basket_pnl = -1000000.0
             
    def _update_tps_if_needed(self, executor, positions, new_tp):
         """Helper to iterate and modify TPs only if they differ significantly."""
         # Floating point comparison requires small tolerance
         point = ag.symbol_info(config.SYMBOL).point
         tolerance = point / 2.0 
         
         for p in positions:
             if abs(p.tp - new_tp) > tolerance:
                 executor.modify_tp(p.ticket, config.SYMBOL, new_tp)
