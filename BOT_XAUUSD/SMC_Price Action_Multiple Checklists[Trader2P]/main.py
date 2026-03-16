import os
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import datetime
from mt5_client import MT5Client
from execution import TradeExecutor
from strategy import SMCSniperStrategy
import config

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
