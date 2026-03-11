import logging
import MetaTrader5 as ag
import config
import requests

class SmartGridStrategy:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.hedged_this_session = False # Prevent multiple hedges in the same run

    def send_line_notify(self, message):
         """Sends an alert message to Line Notify."""
         if not getattr(config, 'LINE_NOTIFY_TOKEN', ""):
             return
         
         url = "https://notify-api.line.me/api/notify"
         headers = {"Authorization": f"Bearer {config.LINE_NOTIFY_TOKEN}"}
         data = {"message": f"[{config.SYMBOL}] {message}"}
         try:
             requests.post(url, headers=headers, data=data, timeout=5)
         except Exception as e:
             self.logger.error(f"Failed to send Line Notify: {e}")

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
                     self.logger.critical(f"MAX DRAWDOWN REACHED! DD={drawdown_percent:.2f}%.")
                     
                     if getattr(config, 'ENABLE_HEDGE_ON_DD', False) and executor and tick:
                         self.execute_hedge(executor, tick)
                     else:
                         self.logger.critical("Bot is pausing operations without hedging.")
                         self.send_line_notify(f"⚠️ DANGER: MAX DD REACHED ({drawdown_percent:.2f}%). Bot paused.")
                     
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
             self.send_line_notify("🔒 Port is already fully hedged. Bot paused.")
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
         self.send_line_notify(f"🛡️ HEDGE TRIGGERED! Lock Port. Opening {'BUY' if hedge_type == 0 else 'SELL'} {hedge_volume} Lots.")
         
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

    def check_initial_entry(self, executor, current_rsi, current_ema, tick):
        """Checks RSI and EMA to determine if a first trade should be opened."""
        if current_rsi is None or tick is None or current_ema is None:
            return

        positions = self.get_positions()
        if len(positions) > 0:
            return # Grid is already active, do not open primary entry

        # EMA Trend Filter overrides
        # Only buy if price > EMA (uptrend) and RSI is oversold
        if current_rsi < config.RSI_BUY_LEVEL and tick.ask > current_ema:
            self.logger.info(f"Trend Buy: RSI={current_rsi:.2f} < {config.RSI_BUY_LEVEL} | Price > EMA 200")
            executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, config.START_LOT, tick.ask)
            
        # Only sell if price < EMA (downtrend) and RSI is overbought
        elif current_rsi > config.RSI_SELL_LEVEL and tick.bid < current_ema:
            self.logger.info(f"Trend Sell: RSI={current_rsi:.2f} > {config.RSI_SELL_LEVEL} | Price < EMA 200")
            executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, config.START_LOT, tick.bid)

    def get_dynamic_grid_distance(self, num_positions, current_atr):
         """Calculates distance based on Base ATR distance and multiplier."""
         # Base distance is calculated from ATR, with a minimum safety floor
         base_distance = config.MIN_GRID_DISTANCE_POINTS
         if current_atr is not None:
             point = ag.symbol_info(config.SYMBOL).point
             atr_points_distance = (current_atr * config.ATR_MULTIPLIER) / point
             base_distance = max(config.MIN_GRID_DISTANCE_POINTS, atr_points_distance)
             
         # For 1st position (0 existing), distance is base. 2nd uses base * multiplier^1, etc.
         if num_positions <= 1:
             return base_distance
         
         # e.g. level 2 = base * 1.5, level 3 = base * 2.25
         multiplier = config.GRID_MULTIPLIER ** (num_positions - 1)
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
             self.logger.warning(f"Price gapped too far! ({distance_points:.1f} > {max_allowed_distance:.1f} max). Pausing safely.")
             return False

        if distance_points >= required_distance:
            # Check direction of movement relative to side AND APPLY TREND FILTER (EMA 200)
            if side == 0 and current_price < latest_position.price_open:
                # Price dropped below last buy order. Check if we are still above EMA (Uptrend)
                if current_price > current_ema:
                    return True
                else:
                    self.logger.info(f"Trend Filter: Blocked Buy Grid because Price ({current_price}) is below EMA ({current_ema:.5f})")
            elif side == 1 and current_price > latest_position.price_open:
                # Price rose above last sell order. Check if we are still below EMA (Downtrend)
                if current_price < current_ema:
                    return True
                else:
                    self.logger.info(f"Trend Filter: Blocked Sell Grid because Price ({current_price}) is above EMA ({current_ema:.5f})")
                
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
                self.logger.info(f"Opening BUY Grid. Level: {len(buy_positions)+1}, Lot: {dynamic_lot}")
                executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask)
                
            if not config.USE_TRAILING_STOP:
                new_tp = self.calculate_basket_tp(buy_positions, side=0)
                self._update_tps_if_needed(executor, buy_positions, new_tp)

        # Process Sell Grid
        if sell_positions:
             if self.needs_new_grid_level(sell_positions, current_bid, side=1, current_atr=current_atr, current_ema=current_ema):
                 dynamic_lot = self.get_dynamic_lot(len(sell_positions))
                 self.logger.info(f"Opening SELL Grid. Level: {len(sell_positions)+1}, Lot: {dynamic_lot}")
                 executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, dynamic_lot, current_bid)
                 
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

