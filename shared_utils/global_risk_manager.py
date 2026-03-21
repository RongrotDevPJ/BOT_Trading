import MetaTrader5 as mt5
import logging
import os
from pathlib import Path

logger = logging.getLogger("GlobalRiskManager")

# Path for the global stop flag
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOP_FLAG_PATH = PROJECT_ROOT / "GLOBAL_STOP.lock"

def check_global_drawdown(max_dd_percent=15.0):
    """
    Checks the overall account drawdown.
    If it exceeds the limit, triggers an emergency close of all positions.
    Returns True if a Kill Switch was triggered or is active.
    """
    # Check if a shutdown is already in progress or active
    if STOP_FLAG_PATH.exists():
        return True

    account = mt5.account_info()
    if account is None:
        logger.error("Failed to retrieve account info for Global Risk check.")
        return False

    balance = account.balance
    equity = account.equity

    if balance > 0:
        drawdown_percent = ((balance - equity) / balance) * 100
        if drawdown_percent > max_dd_percent:
            logger.critical(f"🚨 GLOBAL KILL SWITCH TRIGGERED! Account DD={drawdown_percent:.2f}% (Limit={max_dd_percent}%)")
            trigger_emergency_close()
            return True

    return False

def trigger_emergency_close():
    """Closes every single open position on the account and creates a lock file."""
    # Create the lock file immediately to stop other bots from opening new trades
    with open(STOP_FLAG_PATH, "w") as f:
        f.write(f"Global Kill Switch activated at {mt5.symbol_info_tick('XAUUSD').time if mt5.symbol_info_tick('XAUUSD') else 'unknown time'}")

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
