import os
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import datetime
from mt5_client import MT5Client
from execution import TradeExecutor
from strategy import SMCSniperStrategy
import config
import sys
# Add project root to path for display_manager
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
if project_root not in sys.path:
    sys.path.append(project_root)
from display_manager import render_dashboard

# Setup Logging
# Get the root directory of the project (BOT_Trading)
# __file__ is BOT_Trading\BOT_XAUUSD\SMC_Price Action_Multiple Checklists[Trader2P]\main.py
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
log_dir = os.path.join(project_root, "Log_HistoryOrder", "Text_Logs")
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"{config.SYMBOL}_sniper_bot.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        TimedRotatingFileHandler(log_filename, when="midnight", interval=1, backupCount=7, encoding='utf-8'),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger("SniperControl")

# Custom handler to capture latest log
class LatestLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.latest_msg = "Bot Started"
        self.latest_time = datetime.datetime.now().strftime("%H:%M:%S")

    def emit(self, record):
        self.latest_msg = record.getMessage()
        self.latest_time = datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S")

latest_log_handler = LatestLogHandler()
logger.addHandler(latest_log_handler)
# Also add it to the root logger or specific strategy logger if needed
logging.getLogger("").addHandler(latest_log_handler)

def main():
    logger.info("==========================================")
    logger.info("Starting SMC & Price Action Sniper Bot...")
    logger.info(f"Symbol: {config.SYMBOL} | HTF: {config.HTF_TIMEFRAME} | LTF: {config.LTF_TIMEFRAME}")
    logger.info("==========================================")

    client = MT5Client()
    executor = TradeExecutor(client)
    strategy = SMCSniperStrategy(client)

    # Try to connect
    if not client.connect():
        logger.error("Initial connection failed. Exiting.")
        return

    last_heartbeat = time.time()

    try:
        while True:
            # 1. Check connection
            if not client.is_connected():
                logger.warning("Terminal disconnected! Attempting reconnect in 10s...")
                time.sleep(10)
                client.connect()
                continue
                
            # Define default values for UI if not yet calculated
            equity = 0
            balance = 0
            daily_profit_pct = 0
            drawdown_pct = 0
            mt5_status = "CONNECTED" if client.is_connected() else "DISCONNECTED"
            
            account_info = client.get_account_info()
            if account_info:
                equity = account_info.equity
                balance = account_info.balance
                # For Sniper, we might not have start_of_day_equity reset logic yet, 
                # let's try to find it or use a default.
                # Since main.py doesn't have the reset logic like Grid, we use current_time vs start of day
                # but better to stick to a simple 0 if not tracked.
                # Actually, I'll add a simple tracking for today.
            
            # Sniper Stats: Bias: {direction} | Zone: {status} | Fib: {level}
            # We can extract these from strategy.last_checklist_log
            bias = strategy.last_checklist_log.get("H1 Bias", "WAIT")
            zone = strategy.last_checklist_log.get("Zone", "WAIT")
            fib = strategy.last_checklist_log.get("Fib Zone", "WAIT")
            stat_line = f"Bias: {bias} | Zone: {zone} | Fib: {fib}"
            
            # Guard values
            tick = client.get_tick(config.SYMBOL)
            symbol_info = client.get_symbol_info(config.SYMBOL)
            current_spread = int((tick.ask - tick.bid) / symbol_info.point) if tick and symbol_info else 0
            max_spread = getattr(config, 'MAX_SPREAD', 0)
            news_status = "STABLE"

            # Render Dashboard
            render_dashboard(
                symbol=config.SYMBOL,
                equity=equity,
                balance=balance,
                daily_profit_pct=daily_profit_pct, # Tracker needed for full accuracy
                drawdown_pct=drawdown_pct,
                strategy_name="SMC Sniper",
                stat_line=stat_line,
                current_spread=current_spread,
                max_spread=max_spread,
                news_status=news_status,
                log_time=latest_log_handler.latest_time,
                log_message=latest_log_handler.latest_msg,
                mt5_status=mt5_status,
                target_pct=getattr(config, 'DAILY_TARGET_PERCENT', 15.0)
            )
                
            # 2. Heartbeat logging
            current_time = time.time()
            if current_time - last_heartbeat > 3600: # Hourly heartbeat
                account_info = client.get_account_info()
                if account_info:
                    logger.info(f"--- HEARTBEAT --- Balance: {account_info.balance:.2f} | Equity: {account_info.equity:.2f}")
                last_heartbeat = current_time

            # 3. Core Strategy Logic
            try:
                tick = client.get_tick(config.SYMBOL)
                if tick is None:
                    time.sleep(1)
                    continue

                # Run Sniper Checklist
                strategy.run_sniper_check(executor, tick)
                
                # Manage existing trades (Breakeven, etc.)
                strategy.manage_trades(executor, tick)

            except Exception as e:
                logger.error(f"Error during strategy execution: {e}", exc_info=True)

            # 4. Loop delay
            time.sleep(1) # Check every second

    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Bot crashed: {e}", exc_info=True)
    finally:
        logger.info("Shutting down MT5 connection...")
        client.shutdown()

if __name__ == "__main__":
    main()
