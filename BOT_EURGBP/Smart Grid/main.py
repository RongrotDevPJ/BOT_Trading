import time
import logging
from mt5_client import MT5Client
from execution import TradeExecutor
from strategy import SmartGridStrategy
from indicator import IndicatorClient
from time_filter import TimeFilterClient
import config

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("smart_grid_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MainControl")

def main():
    logger.info("Starting Smart Grid MT5 Bot...")

    client = MT5Client()
    executor = TradeExecutor(client)
    strategy = SmartGridStrategy()
    indicator_client = IndicatorClient()
    time_filter = TimeFilterClient()

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
                client.connect() # Attempt to reconnect
                continue
                
            # 2. Heartbeat logging
            current_time = time.time()
            if current_time - last_heartbeat > config.HEARTBEAT_INTERVAL_SEC:
                account_info = client.get_account_info()
                if account_info:
                    logger.info(f"--- HEARTBEAT --- Bot is running. Equity: {account_info.equity:.2f} Balance: {account_info.balance:.2f}")
                else:
                     logger.info("--- HEARTBEAT --- Bot is running but couldn't fetch account info.")
                last_heartbeat = current_time

            # 3. Core Strategy Logic
            try:
                # Fetch tick data globally for all checks to ensure consistency
                tick = client.get_tick(config.SYMBOL)
                if tick is None:
                    time.sleep(1)
                    continue

                # Fetch Indicators
                current_rsi = indicator_client.get_rsi(config.SYMBOL, config.RSI_TIMEFRAME, config.RSI_PERIOD)
                current_atr = indicator_client.get_atr(config.SYMBOL, config.TIMEFRAME, config.ATR_PERIOD)
                current_ema = indicator_client.get_ema(config.SYMBOL, config.EMA_TIMEFRAME, config.EMA_PERIOD)
                
                # Check Time Filter before allowing NEW initial entries
                initial_entry_placed = False
                if time_filter.is_allowed_to_trade():
                    # Check initial entry (if no grid active)
                    initial_entry_placed = strategy.check_initial_entry(executor, current_rsi, current_ema, tick)

                # Execute grid logic ONLY IF we didn't just place an initial entry
                # (to prevent double orders on the same tick)
                if not initial_entry_placed:
                    strategy.check_grid_logic(executor, current_atr)
                
                # Manage positions
                positions = strategy.get_positions()
                
                # 1. Partial Close (Hedging bad trades with good ones)
                executor.manage_partial_close(positions, tick)
                
                # 2. Trailing Stops (Lock Profit)
                executor.manage_trailing_stop(positions, tick)

            except Exception as e:
                logger.error(f"Error during strategy execution: {e}", exc_info=True)

            # 4. Loop delay (efficiency)
            time.sleep(1) # 1 second delay to avoid burning CPU

    except KeyboardInterrupt:
        logger.info("Bot stopped by user (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"Bot crashed with unexpected error: {e}", exc_info=True)
    finally:
        logger.info("Shutting down MT5 connection...")
        client.shutdown()
        logger.info("Bot stopped gracefully.")


if __name__ == "__main__":
    main()
