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
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", ".."))
log_dir = os.path.join(project_root, "Log_HistoryOrder", "Text_Logs")
os.makedirs(log_dir, exist_ok=True)
log_filename = os.path.join(log_dir, f"{config.SYMBOL}_bot.log")

file_handler = TimedRotatingFileHandler(log_filename, when="midnight", interval=1, backupCount=7, encoding='utf-8')
file_handler.setLevel(logging.INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[file_handler, console_handler],
    force=True
)
logger = logging.getLogger("MainControl")

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

def main():
    logger.info("Starting XAUUSD SMC Sniper Bot...")
    
    client = MT5Client()
    executor = TradeExecutor(client)
    strategy = SMCSniperStrategy(client)

    # Try to connect
    if not client.connect():
        logger.error("Initial connection failed. Exiting.")
        return

    last_heartbeat = time.time()
    
    # UI Cache
    last_ui_data_update = 0
    cached_equity = 0
    cached_balance = 0
    cached_daily_profit_pct = 0
    cached_drawdown_pct = 0
    # Track start of day for profit calculation
    start_of_day_equity = client.get_account_info().equity if client.is_connected() else 0

    try:
        while True:
            current_time = time.time()

            # 1. Check connection
            if not client.is_connected():
                logger.warning("Terminal disconnected! Attempting reconnect...")
                time.sleep(10)
                client.connect()
                continue
                
            mt5_status = "CONNECTED" if client.is_connected() else "DISCONNECTED"
            
            # Update UI Data Cache every 10 seconds
            if current_time - last_ui_data_update >= 10:
                account_info = client.get_account_info()
                if account_info:
                    cached_equity = account_info.equity
                    cached_balance = account_info.balance
                    if start_of_day_equity and start_of_day_equity > 0:
                        cached_daily_profit_pct = ((cached_equity - start_of_day_equity) / start_of_day_equity) * 100
                    if cached_balance > 0:
                        cached_drawdown_pct = ((cached_balance - cached_equity) / cached_balance) * 100
                last_ui_data_update = current_time

            # Sniper Stats: Bias: {direction} | Zone: {status} | Fib: {level}
            bias = strategy.last_checklist_log.get("H1 Bias", "WAIT")
            zone = "IN ZONE" if strategy.last_checklist_log.get("In Zone", False) else "WAIT"
            fib = strategy.last_checklist_log.get("Fib Level", "N/A")
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
                equity=cached_equity,
                balance=cached_balance,
                daily_profit_pct=cached_daily_profit_pct,
                drawdown_pct=cached_drawdown_pct,
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

            # 2. Heartbeat
            if current_time - last_heartbeat > 300: # 5 min heartbeat for Sniper
                logger.info(f"--- HEARTBEAT --- SMC Sniper is active. Symbol: {config.SYMBOL}")
                last_heartbeat = current_time

            # 3. Core Strategy Logic
            try:
                # Update data and check signals
                strategy.run_sniper_check(executor, tick)
                # Manage existing trades
                strategy.manage_trades(executor, tick)

            except Exception as e:
                logger.error(f"Error during strategy execution: {e}", exc_info=True)

            # 4. Loop delay (Reduced busy waiting to save CPU)
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.critical(f"Bot crashed with unexpected error: {e}", exc_info=True)
    finally:
        logger.info("Shutting down MT5 connection...")
        client.shutdown()
        logger.info("Bot stopped gracefully.")


if __name__ == "__main__":
    main()
