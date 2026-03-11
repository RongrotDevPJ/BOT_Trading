import logging
import MetaTrader5 as ag
import config

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
        if spread > config.MAX_SPREAD_POINTS:
            self.logger.warning(f"Spread {spread} exceeds max limit {config.MAX_SPREAD_POINTS}. Trade blocked.")
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
        Manages trailing stops for all open positions.
        Called on every tick.
        """
        if not config.USE_TRAILING_STOP or not positions or tick is None:
            return

        point = ag.symbol_info(config.SYMBOL).point
        trail_points = config.TRAILING_STOP_POINTS * point
        step_points = config.TRAILING_STEP_POINTS * point
        
        for p in positions:
            if p.type == 0: # BUY
                # Calculate profit in price difference
                profit_distance = tick.bid - p.price_open
                
                # Check if we are past the break-even + basket target
                if profit_distance > (config.BASKET_TP_POINTS * point):
                    new_sl = tick.bid - trail_points
                    
                    # Only move SL up, and only if it moves more than step_points
                    if p.sl == 0.0 or (new_sl - p.sl) >= step_points:
                        self.modify_sl(p.ticket, config.SYMBOL, new_sl)
                        
            elif p.type == 1: # SELL
                profit_distance = p.price_open - tick.ask
                
                if profit_distance > (config.BASKET_TP_POINTS * point):
                    new_sl = tick.ask + trail_points
                    
                    # Only move SL down, and only if it moves more than step_points
                    # p.sl == 0.0 means SL hasn't been set yet
                    if p.sl == 0.0 or (p.sl - new_sl) >= step_points:
                        self.modify_sl(p.ticket, config.SYMBOL, new_sl)

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
