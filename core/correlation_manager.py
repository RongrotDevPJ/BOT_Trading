import MetaTrader5 as ag
import logging

class CorrelationGuard:
    def __init__(self):
        self.logger = logging.getLogger("CorrelationGuard")
        
        # Magic Numbers corresponding to bot configurations
        # EURUSD: 111111, EURGBP: 333333
        self.CORRELATED_PAIRS = {
            "EURGBP": {"partner": "EURUSD", "partner_magic": 111111},
            "EURUSD": {"partner": "EURGBP", "partner_magic": 333333}
        }

    def is_allowed_to_open_initial(self, current_symbol):
        """
        Calculates if a new cycle is safe based on correlated pair drawdown.
        Blocks entry if the correlated partner has >= 5 open grid levels.
        """
        # If the symbol has no correlated partner defined, it's allowed
        if current_symbol not in self.CORRELATED_PAIRS:
            return True
            
        partner_info = self.CORRELATED_PAIRS[current_symbol]
        partner_symbol = partner_info["partner"]
        partner_magic = partner_info["partner_magic"]
        
        # Fetch current open positions for the partner symbol
        positions = ag.positions_get(symbol=partner_symbol)
        
        if positions:
            # Filter positions by the partner bot's magic number
            bot_positions = [p for p in positions if p.magic == partner_magic]
            grid_depth = len(bot_positions)
            
            # BLOCK trigger: Partner has 5 or more open levels
            if grid_depth >= 5:
                # Log using the specific format requested by the user
                self.logger.warning(f"⚠️ Correlation Guard: Correlated pair drawdown high ({grid_depth} layers). Blocking new initial entry for {current_symbol}.")
                return False
        
        return True
