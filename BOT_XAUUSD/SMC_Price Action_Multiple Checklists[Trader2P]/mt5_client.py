import MetaTrader5 as ag
import config
import logging

class MT5Client:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def connect(self):
        """Initializes connection to MT5 terminal."""
        # Try to initialize
        if not ag.initialize(login=config.MT5_LOGIN, password=config.MT5_PASSWORD, server=config.MT5_SERVER) if (config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER) else not ag.initialize():
            self.logger.error(f"initialize() failed, error code = {ag.last_error()}")
            return False

        # If credentials are provided but initialization was generic, attempt login (double-check)
        if config.MT5_LOGIN and config.MT5_PASSWORD and config.MT5_SERVER:
            authorized = ag.login(
                login=config.MT5_LOGIN, 
                password=config.MT5_PASSWORD, 
                server=config.MT5_SERVER
            )
            if not authorized:
                self.logger.error(f"Failed to connect to trade account {config.MT5_LOGIN}, error code: {ag.last_error()}")
                return False

        self.logger.info("Successfully connected to MetaTrader 5")
        
        # Check if requested symbol is available
        if not self._enable_symbol(config.SYMBOL):
             return False

        return True

    def _enable_symbol(self, symbol):
         """Ensures the symbol is visible and available for trading."""
         symbol_info = ag.symbol_info(symbol)
         if symbol_info is None:
             self.logger.error(f"{symbol} not found, can not call symbol_info()")
             return False
         
         if not symbol_info.visible:
             if not ag.symbol_select(symbol, True):
                 self.logger.error(f"symbol_select({symbol}) failed, exit")
                 return False
                 
         return True

    def is_connected(self):
         """Checks if connection to terminal is active and market is open."""
         terminal_info = ag.terminal_info()
         if terminal_info is None:
            return False
         
         if not terminal_info.connected:
             self.logger.warning("Terminal is not connected to broker.")
             return False
        
         # Optional: Check if market is open based on symbol (requires more logic)
         # We'll handle this in the main loop or execution by checking for tick data updates
             
         return True

    def get_tick(self, symbol):
        """Gets the latest tick data for a symbol."""
        tick = ag.symbol_info_tick(symbol)
        if tick is None:
             # This can happen if market is closed or disconnect
             self.logger.warning(f"Could not get tick data for {symbol}, market might be closed.")
        return tick

    def get_account_info(self):
        """Gets account information (equity, balance, etc)"""
        return ag.account_info()
        
    def shutdown(self):
         """Shuts down MT5 connection."""
         ag.shutdown()
