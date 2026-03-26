import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

# Mock MetaTrader5 and config before importing components
mock_ag = MagicMock()
mock_ag.ORDER_TYPE_BUY = 0
mock_ag.ORDER_TYPE_SELL = 1
mock_ag.POSITION_TYPE_BUY = 0
mock_ag.POSITION_TYPE_SELL = 1
mock_ag.TRADE_ACTION_DEAL = 1
mock_ag.TRADE_ACTION_SLTP = 6
mock_ag.TRADE_RETCODE_DONE = 10009

mock_config = MagicMock()
mock_config.MAGIC_NUMBER = 222222
mock_config.MAX_DEVIATION = 20
mock_config.TRAILING_STOP_POINTS = 50
mock_config.TRAILING_STEP_POINTS = 10
mock_config.USE_TRAILING_STOP = True
mock_config.MAX_GRID_LEVELS = 4
mock_config.BASKET_TP_POINTS = 50
mock_config.SYMBOL = "XAUUSD"
mock_config.MAX_DD_PERCENT = 10.0
mock_config.ENABLE_TREND_FILTER = False
mock_config.COOLDOWN_MINUTES = 0

sys.modules['MetaTrader5'] = mock_ag
sys.modules['config'] = mock_config

import bots.XAUUSD_Grid.config as bot_config
from shared_utils.execution import TradeExecutor
from bots.XAUUSD_Grid.strategy import SmartGridStrategy

def test_atr_trailing_stop():
    print("Testing ATR Trailing Stop...")
    mock_executor = TradeExecutor(MagicMock())
    
    # Mock position
    p = MagicMock()
    p.magic = bot_config.MAGIC_NUMBER
    p.type = 0 # BUY
    p.price_open = 2000.0
    p.sl = 2000.0
    p.ticket = 123
    
    mock_ag.positions_get.return_value = [p]
    
    # Mock tick
    tick = MagicMock()
    tick.bid = 2010.0 # $10 profit
    mock_ag.symbol_info_tick.return_value = tick
    
    # Mock symbol info
    info = MagicMock()
    info.point = 0.01
    mock_ag.symbol_info.return_value = info
    
    # Test with ATR
    atr = 2.0 # $2.00 ATR
    # Trail = 1.5 * 2.0 = 3.0
    # Step = 0.5 * 2.0 = 1.0
    
    # At bid 2010.0, new_sl = 2010.0 - 3.0 = 2007.0
    # Profit (10.0) > Step (1.0), so it should modify SL
    
    mock_executor.apply_trailing_stop("XAUUSD", atr=atr)
    
    # Check if modify_sl was called or order_send was called with TRADE_ACTION_SLTP
    args, kwargs = mock_ag.order_send.call_args
    request = args[0]
    if request['sl'] == 2007.0:
        print("OK: ATR Trailing Stop Correctly Calculated: new_sl=2007.0 (Bid=2010.0, Trail=3.0)")
    else:
        raise Exception(f"Expected SL 2007.0, got {request['sl']}")

def test_grid_capping():
    print("Testing Grid Level Capping...")
    strategy = SmartGridStrategy()
    
    # Mock 4 positions
    positions = [MagicMock() for _ in range(4)]
    for i, p in enumerate(positions):
        p.magic = bot_config.MAGIC_NUMBER
        p.time = 1000 + i
        p.price_open = 2000.0 - (i * 5.0)
    
    # Current ASK moved far enough to trigger next level
    current_price = 1980.0
    current_atr = 2.0
    current_ema = 2005.0
    
    mock_ag.symbol_info.return_value = MagicMock(point=0.01, time=2000)
    
    with patch('bots.XAUUSD_Grid.config.ENABLE_TREND_FILTER', False):
        with patch('bots.XAUUSD_Grid.config.MAX_GRID_LEVELS', 4):
            with patch('bots.XAUUSD_Grid.config.COOLDOWN_MINUTES', 0):
                # needs_new_grid_level should return False because we already have 4
                result = strategy.needs_new_grid_level(positions, current_price, side=0, current_atr=current_atr, current_ema=current_ema)
                if result is False:
                    print("OK: Grid Level Caper Correctly Blocked Level 5.")
                else:
                    raise Exception("Grid Level Caper failed to block Level 5")

def test_be_tp_shift():
    print("Testing Break-Even TP Shift...")
    strategy = SmartGridStrategy()
    executor = MagicMock()
    
    # Mock 4 positions at different prices
    p1 = MagicMock(); p1.price_open = 2000.0; p1.volume = 0.1; p1.tp = 2010.0; p1.magic = bot_config.MAGIC_NUMBER; p1.ticket=1; p1.time=100; p1.type=0
    p2 = MagicMock(); p2.price_open = 1995.0; p2.volume = 0.1; p2.tp = 2010.0; p2.magic = bot_config.MAGIC_NUMBER; p2.ticket=2; p2.time=200; p2.type=0
    p3 = MagicMock(); p3.price_open = 1990.0; p3.volume = 0.1; p3.tp = 2010.0; p3.magic = bot_config.MAGIC_NUMBER; p3.ticket=3; p3.time=300; p3.type=0
    p4 = MagicMock(); p4.price_open = 1985.0; p4.volume = 0.1; p4.tp = 2010.0; p4.magic = bot_config.MAGIC_NUMBER; p4.ticket=4; p4.time=400; p4.type=0
    
    buy_positions = [p1, p2, p3, p4]
    
    # BE price = (2000+1995+1990+1985)/4 = 1992.5
    
    mock_ag.account_info.return_value = MagicMock(balance=10000.0, equity=9900.0)
    mock_ag.positions_get.return_value = buy_positions
    mock_ag.symbol_info_tick.return_value = MagicMock(ask=1980.0, bid=1975.0, time=500)
    mock_ag.symbol_info.return_value = MagicMock(point=0.01, time=500)
    
    with patch('bots.XAUUSD_Grid.config.MAX_GRID_LEVELS', 4):
        with patch('bots.XAUUSD_Grid.config.USE_TRAILING_STOP', False):
            strategy.check_grid_logic(executor, current_atr=2.0, current_ema=2000.0)
            
            # check_grid_logic calls _update_tps_if_needed which calls executor.modify_tp
            # modify_tp should be called with new_tp = 1992.5
            
            calls = executor.modify_tp.call_args_list
            found_be = False
            for call in calls:
                args, kwargs = call
                if args[2] == 1992.5:
                    found_be = True
            
            if found_be:
                print("OK: TP Shifted to Break-Even (1992.5) successfully at Max Grid Level.")
            else:
                raise Exception("TP was not shifted to Break-Even")

if __name__ == "__main__":
    try:
        test_atr_trailing_stop()
        test_grid_capping()
        test_be_tp_shift()
        print("\nAll Tests Passed Successfully!")
    except Exception as e:
        print(f"\n[ERROR] Test Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
