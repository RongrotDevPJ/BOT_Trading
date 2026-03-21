import logging
import MetaTrader5 as ag
import config
from shared_utils.notifier import send_telegram_alert

class TradeExecutor:
    def __init__(self, mt5_client):
        self.logger = logging.getLogger(__name__)
        self.mt5_client = mt5_client

    def normalize_price(self, price, symbol):
        """Rounds price to the correct number of decimal places for the symbol."""
        info = ag.symbol_info(symbol)
        if info:
            return round(price, info.digits)
        return price

    def get_filling_mode(self, symbol):
        """Determines the correct order filling mode supported by the symbol."""
        info = ag.symbol_info(symbol)
        if info is None:
            return ag.ORDER_FILLING_IOC
            
        filling = info.filling_mode
        # 1 = FOK, 2 = IOC
        if filling & 2:
            return ag.ORDER_FILLING_IOC
        elif filling & 1:
            return ag.ORDER_FILLING_FOK
        else:
            return ag.ORDER_FILLING_RETURN

    def check_spread(self, symbol):
        """Checks if current spread is within acceptable limits."""
        info = ag.symbol_info(symbol)
        if info is None:
            self.logger.warning(f"Failed to get symbol info for {symbol}")
            return False
            
        spread = info.spread
        if spread > config.MAX_ALLOWED_SPREAD:
            self.logger.warning(f"Spread {spread} exceeds max limit {config.MAX_ALLOWED_SPREAD}. Trade blocked.")
            return False
        return True

    def check_trade_allowed(self, symbol):
        """Checks if trading is fully enabled for the symbol."""
        info = ag.symbol_info(symbol)
        if info is None:
            self.logger.warning(f"Failed to get symbol info for {symbol}")
            return False
            
        trade_mode = info.trade_mode
        if trade_mode == ag.SYMBOL_TRADE_MODE_DISABLED:
            self.logger.warning(f"Trade is DISABLED for {symbol}.")
            return False
        elif trade_mode == ag.SYMBOL_TRADE_MODE_CLOSEONLY:
            self.logger.warning(f"Trade is CLOSE_ONLY for {symbol}. Cannot open new positions.")
            return False
            
        return True

    def send_order(self, symbol, order_type, lot, price, sl=0.0, tp=0.0):
        """Sends a market order and handles common errors."""
        
        # Verify spread before sending order
        if not self.check_spread(symbol):
            return None

        # Verify trade is allowed
        if not self.check_trade_allowed(symbol):
            return None

        # Normalize prices
        price = self.normalize_price(price, symbol)
        
        if config.USE_TRAILING_STOP:
            # If using Trailing Stop, we don't set a hard TP right away
            tp = 0.0
            
        if sl > 0: sl = self.normalize_price(sl, symbol)
        if tp > 0: tp = self.normalize_price(tp, symbol)

        request = {
            "action": ag.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": config.MAX_DEVIATION,
            "magic": config.MAGIC_NUMBER,
            "comment": "Smart Grid Bot",
            "type_time": ag.ORDER_TIME_GTC,
            "type_filling": self.get_filling_mode(symbol),
        }

        # Send the order
        self.logger.info(f"Sending Order Request: Type={order_type}, Lot={lot}, Price={price}")
        result = ag.order_send(request)

        if result is None:
            self.logger.error("order_send() returned None. Terminal disconnected or failed.")
            return None

        # Handle retcodes
        return self._handle_retcode(result, request)

    def modify_sl(self, ticket, symbol, new_sl):
         """Modifies the stop loss of an existing order."""
         new_sl = self.normalize_price(new_sl, symbol)
         request = {
             "action": ag.TRADE_ACTION_SLTP,
             "symbol": symbol,
             "position": ticket,
             "sl": new_sl,
             "magic": config.MAGIC_NUMBER
         }
         
         result = ag.order_send(request)
         if result and result.retcode == ag.TRADE_RETCODE_DONE:
             self.logger.info(f"Successfully modified SL (Trailing) for position {ticket} to {new_sl}")
             return True
         else:
             self._handle_retcode(result, request)
             return False

    def manage_trailing_stop(self, positions, tick):
        """
        [DEPRECATED/LEGACY] Use apply_trailing_stop for newer logic.
        """
        pass # Will be replaced by apply_trailing_stop in main loops

    def apply_break_even(self, symbol, activation_points=300, lock_points=20):
        """
        If profit exceeds activation_points, moves SL to Entry + lock_points.
        Guarantees no loss once a certain profit threshold is met.
        """
        positions = ag.positions_get(symbol=symbol)
        if not positions:
            return

        point = ag.symbol_info(symbol).point
        activation_dist = activation_points * point
        lock_dist = lock_points * point

        for p in positions:
            if p.magic != config.MAGIC_NUMBER: continue

            if p.type == ag.POSITION_TYPE_BUY:
                tick = ag.symbol_info_tick(symbol)
                if tick and (tick.bid - p.price_open) >= activation_dist:
                    target_sl = p.price_open + lock_dist
                    # Only move SL if it's currently below the target or not set
                    if p.sl < target_sl:
                        self.modify_sl(p.ticket, symbol, target_sl)
                        self.logger.info(f"💎 BE: Moved BUY SL for {p.ticket} to {target_sl}")

            elif p.type == ag.POSITION_TYPE_SELL:
                tick = ag.symbol_info_tick(symbol)
                if tick and (p.price_open - tick.ask) >= activation_dist:
                    target_sl = p.price_open - lock_dist
                    # Only move SL if it's currently above the target or not set
                    if p.sl == 0.0 or p.sl > target_sl:
                        self.modify_sl(p.ticket, symbol, target_sl)
                        self.logger.info(f"💎 BE: Moved SELL SL for {p.ticket} to {target_sl}")

    def apply_trailing_stop(self, symbol, trailing_step=50):
        """
        Moves SL every 'trailing_step' points in the direction of profit.
        Trailing Step ensures we don't spam modifications too often.
        """
        positions = ag.positions_get(symbol=symbol)
        if not positions:
            return

        point = ag.symbol_info(symbol).point
        step_dist = trailing_step * point
        
        # User requested 50 points trailing distance as well? 
        # Usually Trailing Stop has a 'distance' and a 'step'. 
        # I'll use trailing_step as both for simplicity or as the minimal move.
        trail_dist = step_dist 

        for p in positions:
            if p.magic != config.MAGIC_NUMBER: continue
            tick = ag.symbol_info_tick(symbol)
            if not tick: continue

            if p.type == ag.POSITION_TYPE_BUY:
                # If price is far above current SL + trail_dist
                # New potential SL
                new_sl = tick.bid - trail_dist
                if p.sl == 0.0:
                    # Initial move to BE or slightly below open if in profit
                    if (tick.bid - p.price_open) > step_dist:
                        self.modify_sl(p.ticket, symbol, p.price_open)
                elif (new_sl - p.sl) >= step_dist:
                    self.modify_sl(p.ticket, symbol, new_sl)

            elif p.type == ag.POSITION_TYPE_SELL:
                new_sl = tick.ask + trail_dist
                if p.sl == 0.0:
                    if (p.price_open - tick.ask) > step_dist:
                        self.modify_sl(p.ticket, symbol, p.price_open)
                elif p.sl > 0.0 and (p.sl - new_sl) >= step_dist:
                    self.modify_sl(p.ticket, symbol, new_sl)

    def modify_tp(self, ticket, symbol, new_tp):
         """Modifies the take profit of an existing order."""
         new_tp = self.normalize_price(new_tp, symbol)
         request = {
             "action": ag.TRADE_ACTION_SLTP,
             "symbol": symbol,
             "position": ticket,
             "tp": new_tp,
             "magic": config.MAGIC_NUMBER
         }
         
         result = ag.order_send(request)
         if result and result.retcode == ag.TRADE_RETCODE_DONE:
             self.logger.info(f"Successfully modified TP for position {ticket} to {new_tp}")
             return True
         else:
             self._handle_retcode(result, request)
             return False

    def close_position(self, position, tick):
         """Sends an inverse market order to close a single position."""
         order_type = ag.ORDER_TYPE_SELL if position.type == 0 else ag.ORDER_TYPE_BUY
         price = tick.bid if order_type == ag.ORDER_TYPE_SELL else tick.ask
         
         request = {
             "action": ag.TRADE_ACTION_DEAL,
             "symbol": position.symbol,
             "volume": position.volume,
             "type": order_type,
             "position": position.ticket, # Specific ticket to close
             "price": price,
             "deviation": config.MAX_DEVIATION,
             "magic": config.MAGIC_NUMBER,
             "comment": "Bot Partial Close",
             "type_time": ag.ORDER_TIME_GTC,
             "type_filling": self.get_filling_mode(position.symbol),
         }
         
         self.logger.info(f"Closing Position {position.ticket}")
         result = ag.order_send(request)
         
         if result and result.retcode == ag.TRADE_RETCODE_DONE:
             # Calculate final PnL for the alert
             pnl = position.profit + position.commission + position.swap
             icon = "✅" if pnl >= 0 else "❌"
             send_telegram_alert(f"{icon} <b>Trade Closed: {position.symbol}</b>\nTicket: {position.ticket}\nSide: {'BUY' if position.type == 0 else 'SELL'}\nProfit: ${pnl:.2f}")
         
         return self._handle_retcode(result, request)

    def manage_partial_close(self, positions, tick):
         """
         If we have too many positions (e.g. >= 5), we find the oldest losing trade
         and the newest profitable trade. If Total Profit of both >= 0 => Close Both to reduce load.
         """
         if not config.ENABLE_PARTIAL_CLOSE or tick is None:
              return

         buy_pos = [p for p in positions if p.type == 0]
         sell_pos = [p for p in positions if p.type == 1]

         for side_positions in (buy_pos, sell_pos):
              if len(side_positions) >= config.MIN_POSITIONS_FOR_PARTIAL:
                  # Sort oldest to newest (by time)
                  side_positions.sort(key=lambda x: x.time)
                  
                  oldest = side_positions[0] # Usually the one with Max DD
                  newest = side_positions[-1] # Usually the fastest to flip to profit
                  
                  # Compare total floating profit of the TWO
                  total_profit_cents = oldest.profit + newest.profit
                  
                  # If positive (or 0), close the pair to reduce margin load safely
                  if total_profit_cents >= 0:
                       self.logger.warning(f"PARTIAL CLOSE TRIGGERED! Closing Ticket {oldest.ticket} and {newest.ticket}. Combined PnL={total_profit_cents}")
                       self.close_position(newest, tick) # Close profitable first
                       self.close_position(oldest, tick) # Then close the loser
                       
                       # We stop checking to avoid modifying lists while closing
                       return

    def ghost_close_check(self, positions, tick, strategy_instance):
         """
         Ghost Take Profit: Real-time monitoring of floating profit vs Basket TP.
         Closes positions instantly if price crosses the TP to avoid slippage.
         """
         if not positions or tick is None:
             return

         buy_pos = [p for p in positions if p.type == 0]
         sell_pos = [p for p in positions if p.type == 1]

         for side_positions, side in [(buy_pos, 0), (sell_pos, 1)]:
             if not side_positions:
                 continue

             basket_tp_price = strategy_instance.calculate_basket_tp(side_positions, side)
             if basket_tp_price == 0.0:
                 continue

             # Check Ghost TP
             if side == 0 and tick.bid >= basket_tp_price:
                 self.logger.critical(f"👻 GHOST TP TRIGGERED (BUY)! Bid {tick.bid:.5f} >= Target {basket_tp_price:.5f}. Securing profits!")
                 for p in side_positions:
                     self.close_position(p, tick)
             elif side == 1 and tick.ask <= basket_tp_price:
                 self.logger.critical(f"👻 GHOST TP TRIGGERED (SELL)! Ask {tick.ask:.5f} <= Target {basket_tp_price:.5f}. Securing profits!")
                 for p in side_positions:
                     self.close_position(p, tick)

    def _handle_retcode(self, result, request):
        """Processes MetaTrader 5 return codes with descriptive logging."""
        
        code = result.retcode
        
        if code == ag.TRADE_RETCODE_DONE:
            self.logger.info(f"Order executed successfully! Ticket: {result.order}")
            return result
        elif code == ag.TRADE_RETCODE_REJECT:
            self.logger.error(f"Order rejected by server. Request: {request}")
        elif code == ag.TRADE_RETCODE_CANCEL:
            self.logger.error(f"Order canceled by client or server. Request: {request}")
        elif code == ag.TRADE_RETCODE_PLACED:
            self.logger.info(f"Order placed. Ticket: {result.order}")
            return result
        elif code == ag.TRADE_RETCODE_DONE_PARTIAL:
            self.logger.warning(f"Order partially executed. Ticket: {result.order}")
            return result
        elif code == ag.TRADE_RETCODE_ERROR:
            self.logger.error(f"Trade error. Request: {request}")
        elif code == ag.TRADE_RETCODE_TIMEOUT:
            self.logger.error("Trade request timeout.")
        elif code == ag.TRADE_RETCODE_INVALID:
            self.logger.error(f"Invalid request parameters. Request: {request}")
        elif code == ag.TRADE_RETCODE_INVALID_VOLUME:
            self.logger.error(f"Invalid volume (Lot size). Given: {request['volume']}")
        elif code == ag.TRADE_RETCODE_INVALID_PRICE:
            self.logger.error(f"Invalid price error. Hint: normalize price to broker digits. Given: {request['price']}")
        elif code == ag.TRADE_RETCODE_INVALID_STOPS:
            self.logger.error(f"Invalid stops (SL/TP) error. Given SL:{request.get('sl')} TP:{request.get('tp')}")
        elif code == ag.TRADE_RETCODE_TRADE_DISABLED:
            self.logger.error("Trading disabled for this symbol or account.")
        elif code == ag.TRADE_RETCODE_MARKET_CLOSED:
            # Important for handling weekends
            self.logger.warning("Market is closed.")
        elif code == ag.TRADE_RETCODE_NO_MONEY:
            self.logger.error("Not enough money to open position.")
        elif code == ag.TRADE_RETCODE_PRICE_CHANGED:
            self.logger.warning("Requote: Price changed.")
            # We could optionally implement retry logic here.
        elif code == ag.TRADE_RETCODE_PRICE_OFF:
            self.logger.warning("Off quotes: No current price available.")
        elif code == ag.TRADE_RETCODE_CONNECTION:
             self.logger.error("No connection to broker.")
        elif code == 10025: # TRADE_RETCODE_NO_CHANGES
             self.logger.debug(f"Modification ignored (Error 10025): TP/SL is already at requested value for Ticket {request.get('position', 'unknown')}.")
        elif code == 10044: # TRADE_RETCODE_CLOSE_ONLY
             self.logger.error(f"Only position closing is allowed for {request.get('symbol')} (Error 10044). Broker restriction.")
        else:
             self.logger.error(f"Trade failed with unknown error code: {code}. Result: {result}")
        
        return None
