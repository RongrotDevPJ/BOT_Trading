import MetaTrader5 as mt5
from datetime import datetime
import logging
import os
import time
import threading
from pathlib import Path

logger = logging.getLogger("GlobalRiskManager")

# Path for the global stop flag
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOP_FLAG_PATH = PROJECT_ROOT / "GLOBAL_STOP.lock"

class GlobalRiskState:
    """
    Class-level state management for Global Risk to implement TTL caching 
    and thread-safe MT5 API access.
    """
    _lock = threading.Lock()
    _last_check_time = 0
    _cached_result = False
    _ttl = 5.0 # Seconds

    @classmethod
    def get_drawdown_status(cls, max_dd_percent):
        """Thread-safe TTL check for global drawdown."""
        current_time = time.time()
        
        with cls._lock:
            # Check if cache is still valid
            if current_time - cls._last_check_time < cls._ttl:
                return cls._cached_result

            # Perform the expensive MT5 API call
            account = mt5.account_info()
            if account is None:
                logger.error("Failed to retrieve account info for Global Risk check.")
                # Return previous status but don't update timestamp to allow retry
                return cls._cached_result

            balance = account.balance
            equity = account.equity
            
            is_limit_hit = False
            if balance > 0:
                drawdown_percent = ((balance - equity) / balance) * 100
                if drawdown_percent > max_dd_percent:
                    logger.critical(f"🚨 GLOBAL KILL SWITCH TRIGGERED! Account DD={drawdown_percent:.2f}% (Limit={max_dd_percent}%)")
                    # Trigger the actual closure logic
                    trigger_emergency_close(
                        reason=f"Account DD hit {drawdown_percent:.2f}%", 
                        trigger_bot="GlobalRiskManager"
                    )
                    is_limit_hit = True
            
            # Update cache
            cls._cached_result = is_limit_hit
            cls._last_check_time = current_time
            return is_limit_hit

def check_global_drawdown(max_dd_percent=15.0):
    """
    Checks the overall account drawdown.
    Uses a 5-second TTL cache to reduce MT5 API overhead.
    """
    # 1. Check for the physical lock file (Always the priority, non-cached)
    if is_trading_suspended():
        return True

    # 2. Check the cached drawdown status
    return GlobalRiskState.get_drawdown_status(max_dd_percent)

def trigger_emergency_close(reason="Unknown", trigger_bot="Unknown"):
    """Closes every single open position on the account and creates a lock file."""
    # Ensure double-checking the suspended state before action
    if is_trading_suspended():
        # Just update the existing file or return
        pass

    # Create the lock file immediately to stop other bots from opening new trades
    try:
        with open(STOP_FLAG_PATH, "w") as f:
            f.write(f"Global Kill Switch activated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Triggered by: {trigger_bot}\n")
            f.write(f"Reason: {reason}\n")
    except Exception as e:
        logger.error(f"Failed to create stop flag: {e}")

    positions = mt5.positions_get()
    if positions:
        logger.warning(f"Closing {len(positions)} total positions across the account...")
        for pos in positions:
            symbol = pos.symbol
            ticket = pos.ticket
            volume = pos.volume
            order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.error(f"Could not get tick for {symbol}. Skipping close for ticket {ticket}.")
                continue
                
            price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "position": ticket,
                "price": price,
                "deviation": 20,
                "magic": pos.magic,
                "comment": "GLOBAL KILL SWITCH",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(f"Failed to close position {ticket}: {result.comment}")
            else:
                logger.info(f"Successfully closed position {ticket} ({symbol})")
    
    logger.critical("Global Kill Switch: All positions processed. Trading suspended.")

def is_trading_suspended():
    """Helper to check if the global stop flag exists."""
    return STOP_FLAG_PATH.exists()

def reset_global_stop():
    """Manually remove the stop flag to resume trading (use with caution)."""
    if STOP_FLAG_PATH.exists():
        os.remove(STOP_FLAG_PATH)
        logger.info("Global Stop Flag removed. Trading can resume.")
