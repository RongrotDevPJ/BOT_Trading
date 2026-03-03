import logging
import MetaTrader5 as ag
import config

class SmartGridStrategy:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def is_max_drawdown_reached(self):
         """Checks if current account drawdown exceeds the max limit."""
         account = ag.account_info()
         if account is None:
             self.logger.error("Failed to retrieve account info to check DD.")
             return False

         balance = account.balance
         equity = account.equity
         
         if balance > 0:
             drawdown_percent = ((balance - equity) / balance) * 100
             if drawdown_percent > config.MAX_DD_PERCENT:
                 self.logger.critical(f"MAX DRAWDOWN REACHED! DD={drawdown_percent:.2f}%. Bot is pausing operations.")
                 return True
                 
         return False

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

    def check_initial_entry(self, executor, current_rsi, tick):
        """Checks RSI to determine if a first trade should be opened."""
        if current_rsi is None or tick is None:
            return

        positions = self.get_positions()
        if len(positions) > 0:
            return # Grid is already active, do not open primary entry

        if current_rsi < config.RSI_BUY_LEVEL:
            self.logger.info(f"RSI={current_rsi:.2f} < {config.RSI_BUY_LEVEL}. Opening Initial BUY.")
            executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, config.START_LOT, tick.ask)
            
        elif current_rsi > config.RSI_SELL_LEVEL:
            self.logger.info(f"RSI={current_rsi:.2f} > {config.RSI_SELL_LEVEL}. Opening Initial SELL.")
            executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, config.START_LOT, tick.bid)

    def get_dynamic_grid_distance(self, num_positions):
         """Calculates distance based on base distance and multiplier."""
         # For 1st position (0 existing), distance is base. 2nd uses base * multiplier^1, etc.
         if num_positions <= 1:
             return config.GRID_DISTANCE_POINTS
         
         # e.g. level 2 = base * 1.2, level 3 = base * 1.44
         multiplier = config.GRID_MULTIPLIER ** (num_positions - 1)
         return config.GRID_DISTANCE_POINTS * multiplier

    def get_dynamic_lot(self, num_positions):
         """Calculates lot size based on multiplier, up to MAX_LOT."""
         # If 1 open trade, num_positions=1, next lot is base * multiplier ^ 1
         lot = config.START_LOT * (config.LOT_MULTIPLIER ** num_positions)
         lot = round(lot, 2) # Format for Cent accounts (2 decimal places)
         
         if lot > config.MAX_LOT:
             lot = config.MAX_LOT
             
         return lot

    def needs_new_grid_level(self, positions, current_price, side):
        """
        Determines if price has moved far enough to open a new grid level.
        Positions should be sorted by time (oldest first or newest first) to find the LAST opened level.
        """
        if not positions:
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
        
        required_distance = self.get_dynamic_grid_distance(len(positions))

        # Crash Recovery / Max Gap check
        max_allowed_distance = required_distance * config.MAX_GAP_MULTIPLIER
        if distance_points > max_allowed_distance:
             self.logger.warning(f"Price gapped too far! ({distance_points:.1f} > {max_allowed_distance:.1f} max). Pausing safely.")
             return False

        if distance_points >= required_distance:
            # Check direction of movement relative to side
            if side == 0 and current_price < latest_position.price_open:
                # Price dropped below last buy order, open new buy
                return True
            elif side == 1 and current_price > latest_position.price_open:
                # Price rose above last sell order, open new sell
                return True
                
        return False
        
    def check_grid_logic(self, executor):
        """Core logic to check positions and open new grid levels."""
        
        if self.is_max_drawdown_reached():
             return # Skip processing

        positions = self.get_positions()
        buy_positions = [p for p in positions if p.type == 0]
        sell_positions = [p for p in positions if p.type == 1]
        
        tick = ag.symbol_info_tick(config.SYMBOL)
        if tick is None:
            return # Probably weekend/market closed

        current_ask = tick.ask
        current_bid = tick.bid

        # Process Buy Grid
        if buy_positions:
            if self.needs_new_grid_level(buy_positions, current_ask, side=0):
                dynamic_lot = self.get_dynamic_lot(len(buy_positions))
                self.logger.info(f"Opening BUY Grid. Level: {len(buy_positions)+1}, Lot: {dynamic_lot}")
                executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask)
                
            if not config.USE_TRAILING_STOP:
                new_tp = self.calculate_basket_tp(buy_positions, side=0)
                self._update_tps_if_needed(executor, buy_positions, new_tp)

        # Process Sell Grid
        if sell_positions:
             if self.needs_new_grid_level(sell_positions, current_bid, side=1):
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

