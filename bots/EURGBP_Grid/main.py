import sys
from pathlib import Path

# Add project root to path for shared_utils and strategy imports
# Structure: [Root]/BOT_XXXXX/Smart Grid/main.py (3 levels deep from root)
current_file = Path(__file__).resolve()
project_root = current_file.parents[2] 
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import logging
import time
import datetime
import config 

from shared_utils.mt5_client import MT5Client
from shared_utils.db_manager import DBManager
from shared_utils.execution import TradeExecutor
from shared_utils.indicator import IndicatorClient
from shared_utils.time_filter import TimeFilterClient
from shared_utils.display_manager import render_dashboard
from strategy import SmartGridStrategy
from shared_utils.global_risk_manager import is_trading_suspended, check_margin_level, MarginStatus
from shared_utils.notifier import send_telegram_message
from shared_utils.news_filter import is_safe_to_trade as is_news_safe
from shared_utils.system_logger import setup_logger
from shared_utils.correlation_manager import CorrelationGuard

# Setup Persistent Logging
logger = setup_logger(f"{config.SYMBOL}_Bot")
logger.info(f"System Logger initialized for {config.SYMBOL}")

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
    shared_db = DBManager()  # P1: Single shared instance — reduces DB threads from 2 to 1 per bot
    executor = TradeExecutor(client, db=shared_db)
    strategy = SmartGridStrategy(db=shared_db)
    indicator_client = IndicatorClient()
    time_filter = TimeFilterClient()
    correlation_guard = CorrelationGuard()

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
    
    # Indicator Cache
    last_indicator_update = 0
    current_rsi = None
    current_atr = None
    current_ema = None
    current_stoch = None

    try:
        while True:
            current_time = time.time()
            close_only_mode = False  # Default; may be overridden by account DD check below
            
            # 1. Check connection
            if not client.is_connected():
                logger.warning("Terminal disconnected! Attempting reconnect in 10s...")
                time.sleep(10)
                client.connect() 
                continue

            # 1.1 Weekend Sleep Mode (Phase 5)
            if time_filter.is_weekend():
                if current_time - last_ui_data_update >= 3600:
                    logger.info("💤 Weekend Mode: Broker gap detected. Sleeping for 1 hour...")
                    last_ui_data_update = current_time
                time.sleep(60) # Wake up every min to check if weekend finished, but don't do snapshots
                continue

            # 1.1 Global Risk Check (Phase 1)
            if is_trading_suspended():
                if current_time - last_ui_data_update >= 10:
                    logger.warning("🚫 TRADING SUSPENDED: Global Kill Switch is ACTIVE. Manual reset required.")
                time.sleep(10)
                continue

            # Soft Stop & Global Kill Switch
            account_info = client.get_account_info()
            if account_info:
                balance = account_info.balance
                equity = account_info.equity
                current_dd = ((balance - equity) / balance) * 100 if balance > 0 else 0
                max_dd_limit = getattr(config, 'MAX_DD_PERCENT', 15.0)
                soft_stop_limit = max_dd_limit * 0.7
                
                # Check Global Hard Kill Switch
                if current_dd > max_dd_limit:
                    reason = f"Account Drawdown hit {current_dd:.2f}% (Limit: {max_dd_limit}%)"
                    from shared_utils.global_risk_manager import trigger_emergency_close
                    trigger_emergency_close(reason=reason, trigger_bot=config.SYMBOL)
                    send_telegram_message(f"🚨 <b>CRITICAL: Global Kill Switch Triggered by {config.SYMBOL}!</b>\n{reason}. All positions closed.")
                    logger.critical(f"Global Kill Switch activated by {config.SYMBOL}! Trading stopped. Reason: {reason}")
                    continue

                # Check Soft Stop
                close_only_mode = False
                if current_dd > soft_stop_limit:
                    close_only_mode = True
                    if current_time - last_ui_data_update >= 60:
                        logger.warning(f"⚠️ SOFT STOP ACTIVE: DD at {current_dd:.2f}% (> {soft_stop_limit:.2f}%). Entering Close-Only mode.")
                
                # Margin Level Circuit Breaker (Phase 5)
                margin_status = check_margin_level()
                if margin_status == MarginStatus.SOFT_STOP:
                    close_only_mode = True
                    if current_time - last_ui_data_update >= 60:
                        logger.warning("⚠️ [MarginGuard] Margin SOFT STOP active. Blocking new initial entries.")
                elif margin_status == MarginStatus.EMERGENCY:
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
                    strategy.csv_logger.db_manager.sync_deals(deals, active_excursions=strategy.active_excursions)
                    symbol_realized_profit = sum(d.profit + getattr(d, 'commission', 0.0) + d.swap for d in deals)
                    
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
                    logger.warning(f"NULL TICK: Waiting for tick data for {config.SYMBOL}... (Market closed or symbol missing)")
                    time.sleep(1)
                    continue


                # MAE/MFE Tracker
                positions = strategy.get_positions()
                if positions:
                    point = client.get_symbol_info(config.SYMBOL).point
                    for p in positions:
                        if p.ticket not in strategy.active_excursions:
                            strategy.active_excursions[p.ticket] = {'mfe': -1000000.0, 'mae': 1000000.0}
                        if p.type == 0: # BUY
                            current_pts = (tick.bid - p.price_open) / point
                        else: # SELL
                            current_pts = (p.price_open - tick.ask) / point
                        if current_pts > strategy.active_excursions[p.ticket]['mfe']:
                            strategy.active_excursions[p.ticket]['mfe'] = current_pts
                        if current_pts < strategy.active_excursions[p.ticket]['mae']:
                            strategy.active_excursions[p.ticket]['mae'] = current_pts

                # --- Daily Equity Target Logic ---
                current_server_time = datetime.datetime.fromtimestamp(tick.time) if tick else datetime.datetime.now()
                trading_day = current_server_time.date() if current_server_time.hour >= 5 else current_server_time.date() - datetime.timedelta(days=1)
                
                if last_reset_day != trading_day:
                    account_info = client.get_account_info()
                    if account_info:
                        start_of_day_equity = account_info.equity
                        last_reset_day = trading_day
                        daily_target_reached = False
                        from shared_utils.global_risk_manager import reset_daily_target_state
                        reset_daily_target_state()
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
                if getattr(config, 'ENABLE_DAILY_TARGET', False) and start_of_day_equity is not None:
                    account_info = client.get_account_info()
                    if account_info:
                        current_equity = account_info.equity
                        target_equity = start_of_day_equity * (1 + getattr(config, 'DAILY_TARGET_PERCENT', 15.0) / 100.0)
                        trailing_pct = getattr(config, 'DAILY_TARGET_TRAILING_PERCENT', 2.0)
                        
                        from shared_utils.global_risk_manager import check_trailing_daily_target
                        daily_target_reached = check_trailing_daily_target(current_equity, target_equity, trailing_pct, config.SYMBOL)
                            
                if daily_target_reached:
                    positions = strategy.get_positions()
                    if not positions:
                        # Only sleep/wait if all positions are now closed
                        time.sleep(60)
                        continue
                    else:
                        # If target reached but positions still open, we skip INITIAL entry but allow grid logic
                        pass

                # Fetch Indicators (Cached every 60s to save CPU/MT5 resources)
                if current_time - last_indicator_update >= 60:
                    current_rsi = indicator_client.get_rsi(config.SYMBOL, config.TIMEFRAME, config.RSI_PERIOD)
                    current_atr = indicator_client.get_atr(config.SYMBOL, config.TIMEFRAME, config.ATR_PERIOD)
                    current_ema = indicator_client.get_ema(config.SYMBOL, config.EMA_TIMEFRAME, config.EMA_PERIOD)
                    
                    if getattr(config, 'ENABLE_STOCH_FILTER', False):
                        current_stoch = indicator_client.get_stochastic(
                            config.SYMBOL, 
                            config.TIMEFRAME, 
                            getattr(config, 'STOCH_K', 5), 
                            getattr(config, 'STOCH_D', 3), 
                            getattr(config, 'STOCH_SLOWING', 3)
                        )
                    last_indicator_update = current_time
                
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
                    strategy.csv_logger.log_event(
                        action="Market Snapshot", 
                        price=tick.ask, 
                        spread=current_spread, 
                        rsi=current_rsi, 
                        atr=current_atr, 
                        ema=current_ema, 
                        drawdown=cached_acc_drawdown_pct,
                        balance=cached_balance,
                        equity=cached_equity,
                        notes=f"Spread:{current_spread}"
                    )
                    last_csv_snapshot_log = current_time

                # Check Time Filter AND Daily Target AND News Filter before allowing NEW initial entries
                if not daily_target_reached and not close_only_mode and time_filter.is_allowed_to_trade() and is_news_safe(config.SYMBOL):
                    # Phase 3: Correlation Guard Check
                    if correlation_guard.is_allowed_to_open_initial(config.SYMBOL):
                        strategy.check_initial_entry(executor, current_rsi, current_ema, tick, current_stoch=current_stoch, current_atr=current_atr, equity=cached_equity)

                # Execute grid logic (Always allowed even if target reached, to close existing grid)
                # However, if SOFT STOP (close_only_mode) is active, we don't open NEW grid levels
                if not close_only_mode:
                    strategy.check_grid_logic(executor, current_atr, current_ema, equity=cached_equity)
                else:
                    # In Soft Stop, we still check is_max_drawdown_reached to keep it consistent
                    strategy.is_max_drawdown_reached(executor, tick)
                
                # Manage positions (Phase 2 & 3)
                strategy.check_basket_trailing(executor, tick, current_atr=current_atr)
                executor.ghost_close_check(positions, tick, strategy)
                executor.manage_partial_close(positions, tick)
                # Apply Break-Even and Trailing Stop
                executor.apply_break_even(config.SYMBOL, positions, tick, symbol_info,
                                          activation_points=getattr(config, 'BE_ACTIVATION_POINTS', 300),
                                          lock_points=getattr(config, 'BE_LOCK_POINTS', 20))
                executor.apply_trailing_stop(config.SYMBOL, positions, tick, symbol_info, atr=current_atr)

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
