import sys
from pathlib import Path
import logging
import time
import MetaTrader5 as ag
import config
# Add project root to path for shared_utils
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from shared_utils.csv_logger import CSVLogger
from shared_utils.news_filter import is_safe_to_trade

class SmartGridStrategy:
    def __init__(self):
        self.logger = logging.getLogger("SmartGrid")
        self.csv_logger = CSVLogger(config.SYMBOL)
        self.hedged_this_session = False # Prevent multiple hedges in the same run
        self.last_dynamic_log_time = 0 # Prevent log spam
        self.last_trend_log_time = 0
        self.last_gap_log_time = 0
        self.last_analysis_log_time = 0
        self.last_initial_log_time = 0 # Prevent initial entry log spam
        self.last_initial_entry_time = 0
        self.active_excursions = {}

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

    def calculate_basket_tp(self, positions, side):
        """
        Calculates the uniform basket Take Profit price for a group of positions.
        side: 0 for Buy, 1 for Sell
        """
        if not positions:
            return 0.0

        total_volume = sum(p.volume for p in positions)
        if total_volume == 0:
            return 0.0

        # Calculate break-even price (volume-weighted average price)
        total_value = sum(p.price_open * p.volume for p in positions)
        break_even_price = total_value / total_volume

        point = ag.symbol_info(config.SYMBOL).point
        
        # Calculate Basket TP
        if side == 0: # Buy basket
             basket_tp = break_even_price + (config.BASKET_TP_POINTS * point)
        else: # Sell basket
             basket_tp = break_even_price - (config.BASKET_TP_POINTS * point)
             
        return basket_tp

    def check_initial_entry(self, executor, current_rsi, current_ema, tick, current_stoch=None, current_atr=None):
        """Checks RSI, Stochastic, and EMA to determine if a first trade should be opened."""
        if current_rsi is None or tick is None or current_ema is None:
            return

        if time.time() - self.last_initial_entry_time < 10.0:
            return

        positions = self.get_positions()
        if len(positions) > 0:
            return # Grid is already active, do not open primary entry

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
            current_time = time.time()
            trend_str = f"| Price({tick.ask:.5f}) > EMA({current_ema:.5f})" if enable_trend else "(Trend Filter OFF)"
            if current_time - self.last_initial_log_time > 60:
                self.logger.info(f"✨ [Analysis] Initial BUY Entry Triggered: RSI={current_rsi:.2f} <= {config.RSI_BUY_LEVEL} {stoch_str} {trend_str}")
                self.last_initial_log_time = current_time
            result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, config.START_LOT, tick.ask, atr_value=current_atr, rsi_value=current_rsi, grid_level=1, cycle_id=None)
            if result:
                self.last_initial_entry_time = time.time()
                self.csv_logger.log_event(action="Initial Entry", side="BUY", price=tick.ask, rsi=current_rsi, ema=current_ema, lot_size=config.START_LOT, ticket=result.order, notes=stoch_str)
            
        elif is_rsi_sell and is_trend_sell and is_stoch_sell:
            current_time = time.time()
            trend_str = f"| Price({tick.bid:.5f}) < EMA({current_ema:.5f})" if enable_trend else "(Trend Filter OFF)"
            if current_time - self.last_initial_log_time > 60:
                self.logger.info(f"✨ [Analysis] Initial SELL Entry Triggered: RSI={current_rsi:.2f} >= {config.RSI_SELL_LEVEL} {stoch_str} {trend_str}")
                self.last_initial_log_time = current_time
            result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, config.START_LOT, tick.bid, atr_value=current_atr, rsi_value=current_rsi, grid_level=1, cycle_id=None)
            if result:
                self.last_initial_entry_time = time.time()
                self.csv_logger.log_event(action="Initial Entry", side="SELL", price=tick.bid, rsi=current_rsi, ema=current_ema, lot_size=config.START_LOT, ticket=result.order, notes=stoch_str)

    def get_dynamic_grid_distance(self, num_positions, current_atr):
         """Calculates distance based on ATR * Multiplier or Fixed Points with smart multipliers."""
         # Use ATR if enabled, else fallback to fixed GRID_DISTANCE_POINTS
         if getattr(config, 'ENABLE_ATR_DISTANCE', False) and current_atr is not None:
             point = ag.symbol_info(config.SYMBOL).point
             atr_points_distance = (current_atr * config.ATR_MULTIPLIER) / point
             base_distance = max(config.MIN_GRID_DISTANCE_POINTS, atr_points_distance)
         else:
             base_distance = config.GRID_DISTANCE_POINTS
             
         # Smart Dynamic Grid Distance Logic
         # Orders 1-4 (num_positions 0-3): Base distance
         # Orders 5-7 (num_positions 4-6): Base distance * 1.5
         # Orders 8-10+ (num_positions >= 7): Base distance * 2.0
         if num_positions < 4:
             multiplier = 1.0
         elif num_positions < 7:
             multiplier = 1.5
         else:
             multiplier = 2.0
             
         current_time = time.time()
         if current_time - self.last_dynamic_log_time > 60:
             atr_str = f"{current_atr:.5f}" if current_atr is not None else "0"
             self.logger.info(f"🔍 [System Check] Dynamic Distance Layer {num_positions + 1}: BaseDist={base_distance:.1f}pts, Multiplier={multiplier}x => Required Distance={base_distance * multiplier:.1f}pts (ATR={atr_str})")
             self.last_dynamic_log_time = current_time
             
         return base_distance * multiplier

    def get_dynamic_lot(self, num_positions):
         """Calculates lot size based on equity and multiplier."""
         # Calculate dynamic starting lot based on equity if enabled
         equity = ag.account_info().equity if ag.account_info() else 0
         
         if getattr(config, 'AUTO_LOT', False) and equity > 0:
             calculated_start_lot = (equity / config.CENTS_PER_01_LOT) * 0.01
             base_lot = max(config.MIN_START_LOT, min(config.MAX_START_LOT, calculated_start_lot))
         else:
             base_lot = config.START_LOT

         # If 1 open trade, num_positions=1, next lot is base * multiplier ^ 1
         lot = base_lot * (config.LOT_MULTIPLIER ** num_positions)
         lot = round(lot, 2) # Format for Cent accounts (2 decimal places)
         
         if lot > config.MAX_LOT:
             lot = config.MAX_LOT
             
         return lot

    def needs_new_grid_level(self, positions, current_price, side, current_atr, current_ema):
        """
        Determines if price has moved far enough to open a new grid level.
        Positions should be sorted by time (oldest first or newest first) to find the LAST opened level.
        """
        if not positions or current_ema is None:
           return False

        # Find the most recently opened position in this direction
        latest_position = max(positions, key=lambda p: p.time)
        
        # Cooldown check: prevent opening trades too quickly
        symbol_info = ag.symbol_info(config.SYMBOL)
        if symbol_info is not None:
             current_time_sec = symbol_info.time
             time_since_last_pos = current_time_sec - latest_position.time
             if time_since_last_pos < (config.COOLDOWN_MINUTES * 60):
                  return False

        point = ag.symbol_info(config.SYMBOL).point
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
            
            # Check direction of movement relative to side AND APPLY TREND FILTER (EMA 200) if enabled
            if side == 0 and current_price < latest_position.price_open:
                # Price dropped below last buy order. Check if we are still above EMA (Uptrend) or if filter is disabled
                if not enable_trend or current_price > current_ema:
                    current_time = time.time()
                    if current_time - self.last_analysis_log_time > 60:
                        atr_str = f"{current_atr:.5f}" if current_atr is not None else "0"
                        self.logger.info(f"✨ [Analysis] BUY Grid Open: Price={current_price:.5f}, LastBuyPrice={latest_position.price_open:.5f}, Moved={distance_points:.1f}pts, Required={required_distance:.1f}pts, ATR={atr_str}, EMA={current_ema:.5f}")
                        self.last_analysis_log_time = current_time
                    return True
                else:
                    current_time = time.time()
                    if current_time - self.last_trend_log_time > 60:
                        self.logger.info(f"🚫 [Trend Filter] Blocked BUY Grid: Price({current_price:.5f}) is BELOW EMA({current_ema:.5f}) (Downtrend detected). Dist Moved={distance_points:.1f}pts")
                        self.last_trend_log_time = current_time
            elif side == 1 and current_price > latest_position.price_open:
                # Price rose above last sell order. Check if we are still below EMA (Downtrend) or if filter is disabled
                if not enable_trend or current_price < current_ema:
                    current_time = time.time()
                    if current_time - self.last_analysis_log_time > 60:
                        atr_str = f"{current_atr:.5f}" if current_atr is not None else "0"
                        self.logger.info(f"✨ [Analysis] SELL Grid Open: Price={current_price:.5f}, LastSellPrice={latest_position.price_open:.5f}, Moved={distance_points:.1f}pts, Required={required_distance:.1f}pts, ATR={atr_str}, EMA={current_ema:.5f}")
                        self.last_analysis_log_time = current_time
                    return True
                else:
                    current_time = time.time()
                    if current_time - self.last_trend_log_time > 60:
                        self.logger.info(f"🚫 [Trend Filter] Blocked SELL Grid: Price({current_price:.5f}) is ABOVE EMA({current_ema:.5f}) (Uptrend detected). Dist Moved={distance_points:.1f}pts")
                        self.last_trend_log_time = current_time
                
        return False
        
    def check_grid_logic(self, executor, current_atr, current_ema):
        """Core logic to check positions and open new grid levels."""
        
        tick = ag.symbol_info_tick(config.SYMBOL)
        if tick is None:
            return # Probably weekend/market closed
            
        if self.is_max_drawdown_reached(executor, tick):
             return # Skip processing if max DD hit (Hedging is handled inside)

        positions = self.get_positions()
        buy_positions = [p for p in positions if p.type == 0]
        sell_positions = [p for p in positions if p.type == 1]
        
        current_ask = tick.ask
        current_bid = tick.bid

        # Process Buy Grid
        if buy_positions:
            if self.needs_new_grid_level(buy_positions, current_ask, side=0, current_atr=current_atr, current_ema=current_ema):
                dynamic_lot = self.get_dynamic_lot(len(buy_positions))
                self.logger.info(f"🛒 Executing BUY Grid. Level: {len(buy_positions)+1}, Lot: {dynamic_lot}")
                cycle_id_val = str(min(buy_positions, key=lambda x: x.time).ticket)
                result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask, atr_value=current_atr, rsi_value=None, grid_level=len(buy_positions)+1, cycle_id=cycle_id_val)
                if result:
                    latest_p = max(buy_positions, key=lambda p: p.time)
                    dist_moved = abs(current_ask - latest_p.price_open) / ag.symbol_info(config.SYMBOL).point
                    req_dist = self.get_dynamic_grid_distance(len(buy_positions), current_atr)
                    self.csv_logger.log_event(action="Grid Open", side="BUY", price=current_ask, atr=current_atr, ema=current_ema, grid_level=len(buy_positions)+1, lot_size=dynamic_lot, distance_moved=dist_moved, required_distance=req_dist, ticket=result.order)
                
            if not config.USE_TRAILING_STOP:
                new_tp = self.calculate_basket_tp(buy_positions, side=0)
                self._update_tps_if_needed(executor, buy_positions, new_tp)

        # Process Sell Grid
        if sell_positions:
             if self.needs_new_grid_level(sell_positions, current_bid, side=1, current_atr=current_atr, current_ema=current_ema):
                 dynamic_lot = self.get_dynamic_lot(len(sell_positions))
                 self.logger.info(f"🛒 Executing SELL Grid. Level: {len(sell_positions)+1}, Lot: {dynamic_lot}")
                 cycle_id_val = str(min(sell_positions, key=lambda x: x.time).ticket)
                 result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, dynamic_lot, current_bid, atr_value=current_atr, rsi_value=None, grid_level=len(sell_positions)+1, cycle_id=cycle_id_val)
                 if result:
                     latest_p = max(sell_positions, key=lambda p: p.time)
                     dist_moved = abs(current_bid - latest_p.price_open) / ag.symbol_info(config.SYMBOL).point
                     req_dist = self.get_dynamic_grid_distance(len(sell_positions), current_atr)
                     self.csv_logger.log_event(action="Grid Open", side="SELL", price=current_bid, atr=current_atr, ema=current_ema, grid_level=len(sell_positions)+1, lot_size=dynamic_lot, distance_moved=dist_moved, required_distance=req_dist, ticket=result.order)
                 
             if not config.USE_TRAILING_STOP:
                 new_tp = self.calculate_basket_tp(sell_positions, side=1)
                 self._update_tps_if_needed(executor, sell_positions, new_tp)
             
    def _update_tps_if_needed(self, executor, positions, new_tp):
         """Helper to iterate and modify TPs only if they differ significantly."""
         # Floating point comparison requires small tolerance
         point = ag.symbol_info(config.SYMBOL).point
         tolerance = point / 2.0 
         
         for p in positions:
             if abs(p.tp - new_tp) > tolerance:
                 executor.modify_tp(p.ticket, config.SYMBOL, new_tp)

