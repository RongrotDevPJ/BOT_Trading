import time
import MetaTrader5 as mt5

def clean_all():
    if not mt5.initialize():
        print("Failed to connect to MT5.")
        return

    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        print("No open positions to close.")
        mt5.shutdown()
        return

    print(f"Found {len(positions)} open positions. Closing all...")
    count = 0
    for p in positions:
        tick = mt5.symbol_info_tick(p.symbol)
        if tick:
            order_type = mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY
            price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": p.symbol,
                "volume": p.volume,
                "type": order_type,
                "position": p.ticket,
                "price": price,
                "deviation": 20,
                "magic": p.magic,
                "comment": "Clean Close",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            res = mt5.order_send(request)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                count += 1
            else:
                print(f"Failed to close {p.ticket}: {res}")
            time.sleep(0.5)
    print(f"Successfully closed {count}/{len(positions)} positions.")
    mt5.shutdown()

if __name__ == "__main__":
    clean_all()
