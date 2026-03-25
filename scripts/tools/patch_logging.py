import os
import glob
import re
from pathlib import Path

# Calculate project root dynamically based on the current script location (scripts/tools/)
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent

base_dir = str(project_root / "bots")

def read_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(filepath, content):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

# Patch execution.py to handle cycle_id=None as self ticket
exec_path = str(project_root / "shared_utils" / "execution.py")
exec_content = read_file(exec_path)
exec_content = exec_content.replace(
    "cycle_id=cycle_id,",
    "cycle_id=cycle_id if cycle_id is not None else str(handled_result.order),"
)
write_file(exec_path, exec_content)

for bot_dir in glob.glob(os.path.join(base_dir, "*_Grid")):
    strategy_path = os.path.join(bot_dir, "strategy.py")
    main_path = os.path.join(bot_dir, "main.py")
    
    if os.path.exists(strategy_path):
        content = read_file(strategy_path)
        
        # 1. Add self.active_excursions = {}
        if "self.active_excursions = {}" not in content:
            content = content.replace("        self.last_initial_entry_time = 0", "        self.last_initial_entry_time = 0\n        self.active_excursions = {}")
        
        # 2. Update check_initial_entry signature
        content = content.replace(
            "def check_initial_entry(self, executor, current_rsi, current_ema, tick, current_stoch=None):",
            "def check_initial_entry(self, executor, current_rsi, current_ema, tick, current_stoch=None, current_atr=None):"
        )
        
        # 3. Inject kwargs to BUY send_order in check_initial_entry
        # Find: result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, config.START_LOT, tick.ask)
        content = content.replace(
            "result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, config.START_LOT, tick.ask)",
            "result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, config.START_LOT, tick.ask, atr_value=current_atr, rsi_value=current_rsi, grid_level=1, cycle_id=None)"
        )
        # Sell send_order
        content = content.replace(
            "result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, config.START_LOT, tick.bid)",
            "result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, config.START_LOT, tick.bid, atr_value=current_atr, rsi_value=current_rsi, grid_level=1, cycle_id=None)"
        )
        
        # 4. Inject kwargs to BUY send_order in check_grid_logic
        # Find: result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask)
        content = content.replace(
            "result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask)",
            "cycle_id_val = str(min(buy_positions, key=lambda x: x.time).ticket)\n                result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_BUY, dynamic_lot, current_ask, atr_value=current_atr, rsi_value=None, grid_level=len(buy_positions)+1, cycle_id=cycle_id_val)"
        )
        
        # Sell send_order in check_grid_logic
        content = content.replace(
            "result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, dynamic_lot, current_bid)",
            "cycle_id_val = str(min(sell_positions, key=lambda x: x.time).ticket)\n                 result = executor.send_order(config.SYMBOL, ag.ORDER_TYPE_SELL, dynamic_lot, current_bid, atr_value=current_atr, rsi_value=None, grid_level=len(sell_positions)+1, cycle_id=cycle_id_val)"
        )
        
        write_file(strategy_path, content)
        
    if os.path.exists(main_path):
        content = read_file(main_path)
        
        # 1. Update sync_deals
        content = content.replace(
            "strategy.csv_logger.db_manager.sync_deals(deals)",
            "strategy.csv_logger.db_manager.sync_deals(deals, active_excursions=strategy.active_excursions)"
        )
        
        # 2. Update check_initial_entry call
        content = content.replace(
            "strategy.check_initial_entry(executor, current_rsi, current_ema, tick, current_stoch=current_stoch)",
            "strategy.check_initial_entry(executor, current_rsi, current_ema, tick, current_stoch=current_stoch, current_atr=current_atr)"
        )
        
        # 3. Add MAE/MFE Tracking after tick validation
        tracking_code = """                # MAE/MFE Tracker
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

                # --- Daily Equity Target Logic ---"""
                
        content = content.replace("                # --- Daily Equity Target Logic ---", tracking_code)
        
        write_file(main_path, content)

print("Patching complete!")
