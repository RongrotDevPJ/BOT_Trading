import MetaTrader5 as ag
from datetime import datetime, timedelta
import logging
import config

class TimeFilterClient:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.paused_logged = False # Flag to prevent log spam
        
        # --- Auto-Environment Detection ---
        # Calculate offset between local time and UTC
        now = datetime.now()
        utcnow = datetime.utcnow()
        offset = now - utcnow
        
        self.manual_compensation = timedelta(hours=0)
        self.env_mode = "System"
        
        # If offset is near zero (less than 1 minute), assume it's a UTC VPS
        if abs(offset.total_seconds()) < 60:
            self.manual_compensation = timedelta(hours=7) # Compensate for Thai Time (GMT+7)
            self.env_mode = "VPS-Compensated (+7h)"
            
        self.logger.info(f"Time Filter initialized using {self.env_mode} time.")

    def is_allowed_to_trade(self):
        """
        Checks if the bot is currently allowed to open new positions
        based on Time Filters (e.g., Friday late afternoon).
        Uses system/VPS compensated time.
        """
        # Calculate effective time (Adjusted for VPS if needed)
        effective_now = datetime.now() + self.manual_compensation
        
        # Check for Friday (6 for Sunday, 0 for Monday, 4 for Friday)
        if effective_now.weekday() == 4 and not config.ALLOW_FRIDAY_TRADING:
            if effective_now.hour >= config.FRIDAY_STOP_HOUR:
                # Check if there are any open positions for this bot (using magic number)
                positions = ag.positions_get(symbol=config.SYMBOL)
                bot_positions = []
                if positions is not None:
                    bot_positions = [p for p in positions if p.magic == config.MAGIC_NUMBER]

                if len(bot_positions) > 0:
                    # If there are open positions, we don't log "Fully paused" 
                    # because the bot is still active managing them (Salvage mode).
                    if not self.paused_logged:
                        self.logger.info(f"Time Filter Active: Friday after {config.FRIDAY_STOP_HOUR}:00. New entries paused. Managing/Salvaging {len(bot_positions)} open orders.")
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
