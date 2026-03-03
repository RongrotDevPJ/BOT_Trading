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

    def send_order(self, symbol, order_type, lot, price, sl=0.0, tp=0.0):
        """Sends a market order and handles common errors."""
        
        # Verify spread before sending order
        if not self.check_spread(symbol):
            return None

        # Normalize prices
        price = self.normalize_price(price, symbol)
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
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": "Smart Grid Bot",
            "type_time": ag.ORDER_TIME_GTC,
            "type_filling": ag.ORDER_FILLING_IOC, # Commonly required by Cent accounts
        }

        # Send the order
        self.logger.info(f"Sending Order Request: Type={order_type}, Lot={lot}, Price={price}")
        result = ag.order_send(request)

        if result is None:
            self.logger.error("order_send() returned None. Terminal disconnected or failed.")
            return None

        # Handle retcodes
        return self._handle_retcode(result, request)

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
        else:
             self.logger.error(f"Trade failed with unknown error code: {code}. Result: {result}")
        
        return None
