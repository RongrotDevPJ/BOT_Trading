import os
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import datetime
from mt5_client import MT5Client
from execution import TradeExecutor
from strategy import SmartGridStrategy
from indicator import IndicatorClient
from time_filter import TimeFilterClient
import config

# Setup Logging
log_dir = r"C:\Users\t-rongrot.but\Desktop\BOT_Trading\Log_HistoryOrder\Text_Logs"
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"{config.SYMBOL}_bot.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        TimedRotatingFileHandler(log_filename, when="midnight", interval=1, backupCount=7, encoding='utf-8'),
        logging.StreamHandler()
    ],
    force=True
)
logger = logging.getLogger("MainControl")

def main():
    logger.info("Starting Smart Grid MT5 Bot...")
    logger.info(f"CSV Logging initialized at: C:\\Users\\t-rongrot.but\\Desktop\\BOT_Trading\\Log_HistoryOrder\\Analytics_Data")

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
    last_snapshot_log = 0
    last_csv_snapshot_log = 0 # This will trigger snapshot immediately as current_time - 0 > 3600
    
    last_reset_day = None
    start_of_day_equity = None
    daily_target_reached = False

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
                    if time.time() - last_heartbeat > 10: # Log warning every 10s if tick missing
                        logger.warning(f"Waiting for tick data for {config.SYMBOL}... (Market might be closed or symbol not in Market Watch)")
                    time.sleep(1)
                    continue

                # --- Daily Equity Target Logic ---
                current_server_time = datetime.datetime.fromtimestamp(tick.time) if tick else datetime.datetime.now()
                # We consider "trading day" to start at 05:00 server time.
                trading_day = current_server_time.date() if current_server_time.hour >= 5 else current_server_time.date() - datetime.timedelta(days=1)
                
                if last_reset_day != trading_day:
                    account_info = client.get_account_info()
                    if account_info:
                        start_of_day_equity = account_info.equity
                        last_reset_day = trading_day
                        daily_target_reached = False
                        logger.info(f"--- DAILY RESET --- New trading day started. Starting Equity: {start_of_day_equity:.2f}")

                # Check Daily Target
                if not daily_target_reached and start_of_day_equity is not None:
                    account_info = client.get_account_info()
                    if account_info:
                        current_equity = account_info.equity
                        target_equity = start_of_day_equity * (1 + getattr(config, 'DAILY_TARGET_PERCENT', 15.0) / 100.0)
                        
                        if current_equity >= target_equity:
                            logger.critical(f"🎉 DAILY TARGET REACHED! Equity {current_equity:.2f} >= {target_equity:.2f} (15% Lock)")
                            

                            # Close all positions
                            positions = strategy.get_positions()
                            for p in positions:
                                executor.close_position(p, tick)
                                
                            daily_target_reached = True
                            
                if daily_target_reached:
                    # Bot pauses operations until the next trading day
                    time.sleep(60)
                    continue
                # -------------------------------

                # Fetch Indicators
                current_rsi = indicator_client.get_rsi(config.SYMBOL, config.TIMEFRAME, config.RSI_PERIOD)
                current_atr = indicator_client.get_atr(config.SYMBOL, config.TIMEFRAME, config.ATR_PERIOD)
                current_ema = indicator_client.get_ema(config.SYMBOL, config.EMA_TIMEFRAME, config.EMA_PERIOD)
                
                # --- Periodic Snapshot Log (Every 15 mins) ---
                if current_time - last_snapshot_log > 900:
                    rsi_val = f"{current_rsi:.2f}" if current_rsi is not None else "N/A"
                    atr_val = f"{current_atr:.5f}" if current_atr is not None else "N/A"
                    ema_val = f"{current_ema:.5f}" if current_ema is not None else "N/A"
                    logger.info(f"📊 [Market Snapshot] Price: {tick.bid:.5f}/{tick.ask:.5f} | RSI({getattr(config, 'RSI_PERIOD', 14)}): {rsi_val} | ATR({getattr(config, 'ATR_PERIOD', 14)}): {atr_val} | EMA({getattr(config, 'EMA_PERIOD', 200)}): {ema_val}")
                    last_snapshot_log = current_time
                    
                # --- Permanent CSV Market Snapshot (Every 1 Hour) ---
                if current_time - last_csv_snapshot_log > 3600:
                    strategy.csv_logger.log_event(action="Market Snapshot", price=tick.ask, rsi=current_rsi, atr=current_atr, ema=current_ema)
                    last_csv_snapshot_log = current_time

                # Check Time Filter before allowing NEW initial entries
                if time_filter.is_allowed_to_trade():
                    # Check initial entry (if no grid active)
                    strategy.check_initial_entry(executor, current_rsi, current_ema, tick)

                # Execute grid logic (DCA if needed - we allow DCA even if time filter is active to save account)
                strategy.check_grid_logic(executor, current_atr, current_ema)
                
                # Manage positions
                positions = strategy.get_positions()
                
                # 0. Ghost Close Check (Check if price hits Basket TP to avoid slippage)
                executor.ghost_close_check(positions, tick, strategy)
                
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
