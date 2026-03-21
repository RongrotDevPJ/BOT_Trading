import sys
from pathlib import Path

# Add project root to path for shared_utils and strategy imports
# Structure: [Root]/BOT_XXXXX/Smart Grid/main.py (3 levels deep from root)
current_file = Path(__file__).resolve()
project_root = current_file.parents[2] 
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import logging
from logging.handlers import TimedRotatingFileHandler
import time
import datetime
import config 

from shared_utils.mt5_client import MT5Client
from shared_utils.execution import TradeExecutor
from shared_utils.indicator import IndicatorClient
from shared_utils.time_filter import TimeFilterClient
from shared_utils.display_manager import render_dashboard
from strategy import SmartGridStrategy
from shared_utils.global_risk_manager import check_global_drawdown, is_trading_suspended
from shared_utils.notifier import send_telegram_message
from shared_utils.news_filter import is_safe_to_trade as is_news_safe

# Setup Logging
log_dir = project_root / "Log_HistoryOrder" / "Text_Logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_filename = log_dir / f"{config.SYMBOL}_bot.log"

file_handler = TimedRotatingFileHandler(str(log_filename), when="midnight", interval=1, backupCount=7, encoding='utf-8')
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
    logger.info("Starting Smart Grid MT5 Bot...")
    logger.info(f"CSV Logging initialized at: {project_root / 'Log_HistoryOrder' / 'Analytics_Data'}")

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
    last_csv_snapshot_log = 0 
    
    last_reset_day = None
    start_of_day_equity = None
    daily_target_reached = False

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

    try:
        while True:
            current_time = time.time()
            
            # 1. Check connection
            if not client.is_connected():
                logger.warning("Terminal disconnected! Attempting reconnect in 10s...")
                time.sleep(10)
                client.connect() 
                continue

            # 1.1 Global Risk Check (Phase 1)
            if is_trading_suspended():
                if current_time - last_ui_data_update >= 10:
                    logger.warning("🚫 TRADING SUSPENDED: Global Kill Switch is ACTIVE. Manual reset required.")
                time.sleep(10)
                continue

            if check_global_drawdown(max_dd_percent=getattr(config, 'MAX_DD_PERCENT', 15.0)):
                send_telegram_message(f"🚨 <b>CRITICAL: Global Kill Switch Triggered!</b>\nAccount Drawdown exceeded limit. All positions closed.")
                logger.critical("Global Kill Switch activated! Trading stopped.")
                continue
                
            mt5_status = "CONNECTED" if client.is_connected() else "DISCONNECTED"
            
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
                    # Sync deals to SQLite for accurate persistent history
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

            # Get latest stats from strategy for the Stat Line
            positions = strategy.get_positions()
            layer_count = len(positions)
            dist_pts = getattr(config, 'GRID_DISTANCE_POINTS', 0)
            multi_x = getattr(config, 'LOT_MULTIPLIER', 0)
            stat_line = f"Layer: {layer_count} | Dist: {dist_pts}pts | Multi: {multi_x}x"
            
            # Guard values
            tick = client.get_tick(config.SYMBOL)
            symbol_info = client.get_symbol_info(config.SYMBOL)
            current_spread = int((tick.ask - tick.bid) / symbol_info.point) if tick and symbol_info else 0
            max_spread = getattr(config, 'MAX_ALLOWED_SPREAD', 0)
            news_status = "STABLE"

            # Render Dashboard
            render_dashboard(
                symbol=config.SYMBOL,
                equity=cached_equity,
                balance=cached_balance,
                daily_profit_pct=cached_daily_profit_pct,
                drawdown_pct=cached_drawdown_pct,
                strategy_name="Smart Grid",
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
                
            # 2. Heartbeat logging
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
                    if time.time() - last_heartbeat > 10: 
                        logger.warning(f"Waiting for tick data for {config.SYMBOL}... (Market might be closed or symbol not in Market Watch)")
                    time.sleep(1)
                    continue

                # --- Daily Equity Target Logic ---
                current_server_time = datetime.datetime.fromtimestamp(tick.time) if tick else datetime.datetime.now()
                trading_day = current_server_time.date() if current_server_time.hour >= 5 else current_server_time.date() - datetime.timedelta(days=1)
                
                if last_reset_day != trading_day:
                    account_info = client.get_account_info()
                    if account_info:
                        start_of_day_equity = account_info.equity
                        last_reset_day = trading_day
                        daily_target_reached = False
                        logger.info(f"--- DAILY RESET --- New trading day started. Starting Equity: {start_of_day_equity:.2f}")
                        
                        # Send Daily Summary to Telegram (Phase 4)
                        today_profit = strategy.csv_logger.db_manager.get_today_summary(symbol=config.SYMBOL)
                        send_telegram_message(f"💰 <b>Daily Summary: {config.SYMBOL}</b>\nProfit: ${today_profit:.2f}\nEnd Equity: ${account_info.equity:.2f}")
                        
                        # Auto-Archive old data (Phase 3)
                        try:
                            strategy.csv_logger.db_manager.archive_old_data(days=90)
                        except Exception as e:
                            logger.error(f"Failed to archive old data: {e}")

                # Check Daily Target
                if not daily_target_reached and start_of_day_equity is not None:
                    account_info = client.get_account_info()
                    if account_info:
                        current_equity = account_info.equity
                        target_equity = start_of_day_equity * (1 + getattr(config, 'DAILY_TARGET_PERCENT', 15.0) / 100.0)
                        
                        if current_equity >= target_equity:
                            msg = f"🎉 {config.SYMBOL} DAILY TARGET REACHED! Equity {current_equity:.2f} >= {target_equity:.2f}. Entering Close-Only mode."
                            logger.critical(msg)
                            send_telegram_message(msg)
                            daily_target_reached = True
                            
                if daily_target_reached:
                    positions = strategy.get_positions()
                    if not positions:
                        # Only sleep/wait if all positions are now closed
                        time.sleep(60)
                        continue
                    else:
                        # If target reached but positions still open, we skip INITIAL entry but allow grid logic
                        pass

                # Fetch Indicators
                current_rsi = indicator_client.get_rsi(config.SYMBOL, config.TIMEFRAME, config.RSI_PERIOD)
                current_atr = indicator_client.get_atr(config.SYMBOL, config.TIMEFRAME, config.ATR_PERIOD)
                current_ema = indicator_client.get_ema(config.SYMBOL, config.EMA_TIMEFRAME, config.EMA_PERIOD)
                
                # --- Periodic Snapshot Log (Every 15 mins) ---
                if current_time - last_snapshot_log > 900:
                    # Filter: Only log if RSI is extreme (outside 35-65)
                    if current_rsi is not None and (current_rsi < 35 or current_rsi > 65):
                        rsi_val = f"{current_rsi:.2f}"
                        atr_val = f"{current_atr:.5f}" if current_atr is not None else "N/A"
                        ema_val = f"{current_ema:.5f}" if current_ema is not None else "N/A"
                        stoch_val = f"K:{current_stoch[0]:.2f}/D:{current_stoch[1]:.2f}" if current_stoch and current_stoch[0] is not None else "N/A"
                        logger.info(f"📊 [Market Snapshot] Price: {tick.bid:.5f}/{tick.ask:.5f} | Spread: {current_spread} | RSI({getattr(config, 'RSI_PERIOD', 14)}): {rsi_val} | Stoch: {stoch_val} | ATR({getattr(config, 'ATR_PERIOD', 14)}): {atr_val} | EMA({getattr(config, 'EMA_PERIOD', 200)}): {ema_val}")
                        last_snapshot_log = current_time
                    else:
                        # Skip logging but update timer to check again in 15 mins
                        last_snapshot_log = current_time
                    
                # --- Permanent CSV Market Snapshot (Every 1 Hour) ---
                if current_time - last_csv_snapshot_log > 3600:
                    strategy.csv_logger.log_event(action="Market Snapshot", price=tick.ask, spread=current_spread, rsi=current_rsi, atr=current_atr, ema=current_ema, notes=f"Spread:{current_spread}")
                    last_csv_snapshot_log = current_time

                # Check Time Filter AND Daily Target AND News Filter before allowing NEW initial entries
                if not daily_target_reached and time_filter.is_allowed_to_trade() and is_news_safe(config.SYMBOL):
                    strategy.check_initial_entry(executor, current_rsi, current_ema, tick)

                # Execute grid logic (Always allowed even if target reached, to close existing grid)
                strategy.check_grid_logic(executor, current_atr, current_ema)
                
                # Manage positions (Phase 3)
                executor.ghost_close_check(positions, tick, strategy)
                executor.manage_partial_close(positions, tick)
                # Apply Break-Even and Trailing Stop
                executor.apply_break_even(config.SYMBOL, activation_points=300, lock_points=20)
                executor.apply_trailing_stop(config.SYMBOL, trailing_step=50)

            except Exception as e:
                logger.error(f"Error during strategy execution: {e}", exc_info=True)

            # 4. Loop delay (Reduced busy waiting to save CPU)
            time.sleep(0.1)

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
