import os
import time
import logging
from logging.handlers import TimedRotatingFileHandler
import datetime
import config
import sys
from pathlib import Path
import logging
from logging.handlers import TimedRotatingFileHandler
import config
import time
import datetime

# Add project root to path for shared_utils and display_manager
current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from shared_utils.mt5_client import MT5Client
from shared_utils.execution import TradeExecutor
from shared_utils.indicator import IndicatorClient
from shared_utils.time_filter import TimeFilterClient
from shared_utils.display_manager import render_dashboard
from strategy import SMCSniperStrategy

# Setup Logging
log_dir = project_root / "Log_HistoryOrder" / "Text_Logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_filename = log_dir / f"{config.SYMBOL}_Sniper_bot.log"

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
    daily_target_reached = False
    last_reset_day = None
    
    # UI Cache
    last_ui_data_update = 0
    cached_equity = 0
    cached_balance = 0
    cached_daily_profit_pct = 0
    cached_daily_profit_amount = 0
    cached_acc_profit_amount = 0
    cached_acc_profit_pct = 0
    cached_target_amount = 0
    cached_drawdown_pct = 0
    cached_acc_drawdown_pct = 0
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
            
            # Get current tick first to avoid UnboundLocalError
            tick = client.get_tick(config.SYMBOL)
            if tick is None:
                time.sleep(1)
                continue

            # --- Daily Equity Target & Reset Logic ---
            current_server_time = datetime.datetime.fromtimestamp(tick.time) if tick else datetime.datetime.now()
            # New trading day starts at 05:00 Broker Time
            trading_day = current_server_time.date() if current_server_time.hour >= 5 else current_server_time.date() - datetime.timedelta(days=1)
            
            if last_reset_day != trading_day:
                account_info = client.get_account_info()
                if account_info:
                    start_of_day_equity = account_info.equity
                    last_reset_day = trading_day
                    daily_target_reached = False
                    logger.info(f"--- DAILY RESET --- New trading day started ({trading_day}). Starting Equity: {start_of_day_equity:.2f}")

            # Update UI Data Cache every 10 seconds
            if current_time - last_ui_data_update >= 10:
                account_info = client.get_account_info()
                if account_info:
                    cached_equity = account_info.equity
                    cached_balance = account_info.balance
                    
                    # 1. Global (for Target and Total display)
                    if start_of_day_equity and start_of_day_equity > 0:
                        cached_target_amount = start_of_day_equity * (getattr(config, 'DAILY_TARGET_PERCENT', 15.0) / 100.0)
                        cached_acc_profit_amount = cached_equity - start_of_day_equity
                        cached_acc_profit_pct = (cached_acc_profit_amount / start_of_day_equity) * 100
                    
                    if cached_balance > 0:
                        cached_acc_drawdown_pct = ((cached_balance - cached_equity) / cached_balance) * 100

                    # 2. Symbol-specific (for Detailed Display)
                    deals = client.get_history_deals(symbol=config.SYMBOL, magic=config.MAGIC_NUMBER, days=0)
                    # Sync deals to SQLite
                    strategy.csv_logger.db_manager.sync_deals(deals)
                    symbol_realized_profit = sum(d.profit + d.commission + d.swap for d in deals)
                    
                    open_pos = client.get_open_positions(symbol=config.SYMBOL, magic=config.MAGIC_NUMBER)
                    symbol_floating_profit = sum(p.profit for p in open_pos)
                    
                    cached_daily_profit_amount = symbol_realized_profit + symbol_floating_profit
                    if start_of_day_equity and start_of_day_equity > 0:
                        cached_daily_profit_pct = (cached_daily_profit_amount / start_of_day_equity) * 100
                    
                    # Symbol-specific Drawdown (Current floating loss of this bot)
                    symbol_floating_loss = sum(p.profit for p in open_pos if p.profit < 0)
                    if cached_balance > 0:
                        cached_drawdown_pct = (abs(symbol_floating_loss) / cached_balance) * 100
                last_ui_data_update = current_time

            # Check Daily Target
            if not daily_target_reached and start_of_day_equity and start_of_day_equity > 0:
                current_equity = client.get_account_info().equity
                target_equity = start_of_day_equity * (1 + getattr(config, 'DAILY_TARGET_PERCENT', 15.0) / 100.0)
                if current_equity >= target_equity:
                    logger.critical(f"🎉 DAILY TARGET REACHED! Equity {current_equity:.2f} >= {target_equity:.2f}. Entering Close-Only mode.")
                    daily_target_reached = True

            if daily_target_reached:
                positions = strategy.get_positions()
                if not positions:
                    # Target reached and all sniper positions closed -> Sleep
                    time.sleep(60)
                    continue

            # Sniper Stats: Bias: {direction} | Zone: {status} | Fib: {level}
            bias = strategy.last_checklist_log.get("H1 Bias", "WAIT")
            zone = "IN ZONE" if strategy.last_checklist_log.get("In Zone", False) else "WAIT"
            fib = strategy.last_checklist_log.get("Fib Level", "N/A")
            stat_line = f"Bias: {bias} | Zone: {zone} | Fib: {fib}"
            
            # Guard values
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
                target_pct=getattr(config, 'DAILY_TARGET_PERCENT', 15.0),
                target_amount=cached_target_amount,
                profit_amount=cached_daily_profit_amount,
                acc_profit_pct=cached_acc_profit_pct,
                acc_profit_amount=cached_acc_profit_amount,
                acc_drawdown_pct=cached_acc_drawdown_pct
            )

            # 2. Heartbeat
            if current_time - last_heartbeat > 300: # 5 min heartbeat for Sniper
                logger.info(f"--- HEARTBEAT --- SMC Sniper is active. Symbol: {config.SYMBOL}")
                last_heartbeat = current_time

            # 3. Core Strategy Logic
            try:
                # Update data and check signals
                if not daily_target_reached:
                    strategy.run_sniper_check(executor, tick)
                
                # Manage existing trades (Always allowed to handle TP/SL/Trailing)
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
