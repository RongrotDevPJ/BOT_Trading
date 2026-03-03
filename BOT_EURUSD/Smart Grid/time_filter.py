import MetaTrader5 as ag
from datetime import datetime
import logging
import config

class TimeFilterClient:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

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
                self.logger.info(f"Time Filter Active: Friday after {config.FRIDAY_STOP_HOUR}:00 broker time. Trading paused.")
                return False

        return True
