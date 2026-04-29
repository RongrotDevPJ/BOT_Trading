import MetaTrader5 as mt5
from datetime import datetime
from enum import Enum
import logging
import os
import time
import threading
from pathlib import Path

logger = logging.getLogger("GlobalRiskManager")

# Path for the global stop flag
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOP_FLAG_PATH = PROJECT_ROOT / "GLOBAL_STOP.lock"

# ── Margin Level Circuit Breaker ─────────────────────────────────────────────
class MarginStatus(Enum):
    OK        = "OK"       # Margin is healthy
    WARNING   = "WARNING"  # Log only
    SOFT_STOP = "SOFT_STOP"  # Block new initial entries
    EMERGENCY = "EMERGENCY"  # Emergency close all positions

MARGIN_LEVEL_WARNING   = 500.0  # % — start logging warnings
MARGIN_LEVEL_SOFT_STOP = 300.0  # % — block new initial entries
MARGIN_LEVEL_EMERGENCY = 150.0  # % — close everything

class MarginLevelState:
    """
    TTL-cached margin level check — mirrors GlobalRiskState pattern.
    30-second cache since margin level changes slowly.
    """
    _lock = threading.Lock()
    _last_check_time = 0
    _cached_status = MarginStatus.OK
    _ttl = 30.0

    @classmethod
    def get_status(cls):
        current_time = time.time()
        with cls._lock:
            if current_time - cls._last_check_time < cls._ttl:
                return cls._cached_status

            account = mt5.account_info()
            if account is None:
                logger.error("MarginLevelState: Failed to retrieve account info.")
                return cls._cached_status

            margin_level = account.margin_level  # 0.0 when no open positions

            # margin_level == 0.0 means no open positions — treat as safe
            if margin_level == 0.0 or margin_level > MARGIN_LEVEL_WARNING:
                status = MarginStatus.OK
            elif margin_level > MARGIN_LEVEL_SOFT_STOP:
                logger.warning(f"⚠️ [MarginGuard] Margin Level WARNING: {margin_level:.1f}% (< {MARGIN_LEVEL_WARNING:.0f}%)")
                status = MarginStatus.WARNING
            elif margin_level > MARGIN_LEVEL_EMERGENCY:
                logger.critical(f"🚨 [MarginGuard] SOFT STOP: Margin Level {margin_level:.1f}% < {MARGIN_LEVEL_SOFT_STOP:.0f}%. Blocking new entries.")
                status = MarginStatus.SOFT_STOP
            else:
                logger.critical(f"🚨 [MarginGuard] EMERGENCY: Margin Level {margin_level:.1f}% < {MARGIN_LEVEL_EMERGENCY:.0f}%! Triggering emergency close!")
                trigger_emergency_close(
                    reason=f"Margin Level hit {margin_level:.1f}% (Emergency threshold: {MARGIN_LEVEL_EMERGENCY:.0f}%)",
                    trigger_bot="MarginLevelGuard"
                )
                status = MarginStatus.EMERGENCY

            cls._cached_status = status
            cls._last_check_time = current_time
            return status

def check_margin_level() -> MarginStatus:
    """
    Returns the current MarginStatus based on account margin level.
    Uses a 30-second TTL cache. Safe to call every loop tick.
    """
    return MarginLevelState.get_status()

# ─────────────────────────────────────────────────────────────────────────────

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

# ── Trailing Daily Target ────────────────────────────────────────────────────
class DailyTargetState:
    _lock = threading.Lock()
    peak_daily_equity = 0.0
    daily_target_reached = False

def check_trailing_daily_target(current_equity, target_equity, trailing_percent, symbol):
    from shared_utils.notifier import send_telegram_message
    
    with DailyTargetState._lock:
        if current_equity >= target_equity:
            if not DailyTargetState.daily_target_reached:
                DailyTargetState.daily_target_reached = True
                msg = f"🎉 {symbol} DAILY TARGET REACHED! Equity {current_equity:.2f} >= {target_equity:.2f}. Let Profit Run activated."
                logger.critical(msg)
                send_telegram_message(msg)
            
            # Update peak equity
            DailyTargetState.peak_daily_equity = max(DailyTargetState.peak_daily_equity, current_equity)
            
        # Check for trailing stop if target was hit
        if DailyTargetState.daily_target_reached and DailyTargetState.peak_daily_equity > 0:
            exit_equity = DailyTargetState.peak_daily_equity * (1 - (trailing_percent / 100.0))
            if current_equity < exit_equity:
                reason = f"Trailing Daily Target Hit! Peak: {DailyTargetState.peak_daily_equity:.2f}, Dropped below exit {exit_equity:.2f}"
                trigger_emergency_close(reason=reason, trigger_bot=symbol)
                msg = f"💰 <b>Trailing Daily Target Hit! ({symbol})</b>\nLocked Equity: ${current_equity:.2f}\nPeak Equity was: ${DailyTargetState.peak_daily_equity:.2f}"
                logger.critical(msg)
                send_telegram_message(msg)
                
                # Reset for safety (though trading is suspended)
                DailyTargetState.daily_target_reached = False
                DailyTargetState.peak_daily_equity = 0.0
                return True
                
        return DailyTargetState.daily_target_reached

def reset_daily_target_state():
    with DailyTargetState._lock:
        DailyTargetState.peak_daily_equity = 0.0
        DailyTargetState.daily_target_reached = False
