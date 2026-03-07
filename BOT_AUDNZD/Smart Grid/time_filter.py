import MetaTrader5 as ag
from datetime import datetime
import logging
import config

class TimeFilterClient:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.paused_logged = False # Flag to prevent log spam

    def is_allowed_to_trade(self):
        """
        Checks if the bot is currently allowed to open new positions
        based on Time Filters (e.g., Friday late afternoon).
        """
        # Get current time from broker server using symbol info
        symbol_info = ag.symbol_info(config.SYMBOL)
        if symbol_info is None:
            # If we can't get broker time, err on the side of caution or rely on local loop retries
            self.logger.warning("Could not retrieve broker time for time filter.")
            return False

        broker_time_stamp = symbol_info.time

        broker_time = datetime.fromtimestamp(broker_time_stamp)
        
        # Check for Friday (weekday() returns 0 for Monday, 4 for Friday)
        if broker_time.weekday() == 4 and not config.ALLOW_FRIDAY_TRADING:
            if broker_time.hour >= config.FRIDAY_STOP_HOUR:
                # Check if there are any open positions for this bot (using magic number)
                positions = ag.positions_get(symbol=config.SYMBOL)
                bot_positions = []
                if positions is not None:
                    bot_positions = [p for p in positions if p.magic == config.MAGIC_NUMBER]

                if len(bot_positions) > 0:
                    # If there are open positions, we don't log "Fully paused" 
                    # because the bot is still active managing them.
                    if not self.paused_logged:
                        self.logger.info(f"Time Filter Active: Friday after {config.FRIDAY_STOP_HOUR}:00. New entries paused. Managing {len(bot_positions)} open orders.")
                        self.paused_logged = True
                    return False
                
                # Only log once when fully paused (no orders)
                if not self.paused_logged:
                    self.logger.info(f"Time Filter Active: Friday after {config.FRIDAY_STOP_HOUR}:00. Trading fully paused (No open orders).")
                    self.paused_logged = True
                return False

        # Reset flag when trading is allowed (not Friday or before stop hour)
        self.paused_logged = False
        return True
