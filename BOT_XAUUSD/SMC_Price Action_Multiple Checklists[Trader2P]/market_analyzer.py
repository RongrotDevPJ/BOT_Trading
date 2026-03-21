import MetaTrader5 as ag
import config
import logging

class MarketAnalyzer:
    def __init__(self, mt5_client):
        self.mt5_client = mt5_client
        self.logger = logging.getLogger(__name__)

    def get_rates(self, symbol, timeframe_str, count=200):
        """Fetches rates for the specified timeframe string."""
        tf_map = {
            "M1": ag.TIMEFRAME_M1,
            "M5": ag.TIMEFRAME_M5,
            "M15": ag.TIMEFRAME_M15,
            "M30": ag.TIMEFRAME_M30,
            "H1": ag.TIMEFRAME_H1,
            "H4": ag.TIMEFRAME_H4,
            "D1": ag.TIMEFRAME_D1
        }
        tf = tf_map.get(timeframe_str, ag.TIMEFRAME_H1)
        rates = ag.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None:
            self.logger.error(f"Failed to fetch rates for {symbol} {timeframe_str}")
            return []
        return rates

    def find_fractals(self, rates, n=config.FRACTAL_NEIGHBORS):
        """Identifies Fractal Highs and Lows."""
        highs = [] # list of (index, price)
        lows = []
        
        for i in range(n, len(rates) - n):
            # Check for Fractal High
            is_high = True
            for j in range(1, n + 1):
                if rates[i]['high'] < rates[i-j]['high'] or rates[i]['high'] < rates[i+j]['high']:
                    is_high = False
                    break
            if is_high:
                highs.append({'index': i, 'price': rates[i]['high'], 'time': rates[i]['time']})

            # Check for Fractal Low
            is_low = True
            for j in range(1, n + 1):
                if rates[i]['low'] > rates[i-j]['low'] or rates[i]['low'] > rates[i+j]['low']:
                    is_low = False
                    break
            if is_low:
                lows.append({'index': i, 'price': rates[i]['low'], 'time': rates[i]['time']})
        
        return highs, lows

    def analyze_structure(self, symbol, timeframe_str):
        """Detects BOS and CHoCH to determine current Bias with Body Close confirmation."""
        rates = self.get_rates(symbol, timeframe_str)
        if len(rates) < 20: return "NEUTRAL", None, None

        highs, lows = self.find_fractals(rates)
        if not highs or not lows: return "NEUTRAL", None, None

        # --- Trend Bias Logic with Body Close Confirmation ---
        # We check if the most recent finished candles have closed 
        # above the last fractal high or below the last fractal low.
        last_high = highs[-1]
        last_low = lows[-1]
        
        # Check the last 3 candles for a body close break
        current_bias = "NEUTRAL"
        for i in range(-1, -4, -1):
            if rates[i]['close'] > last_high['price']:
                current_bias = "BULLISH" # BOS Up (Confirmed by Body Close)
                break
            elif rates[i]['close'] < last_low['price']:
                current_bias = "BEARISH" # BOS Down (Confirmed by Body Close)
                break

        # If no immediate break, use relative fractal positions (H-H, L-L)
        if current_bias == "NEUTRAL" and len(highs) >= 2 and len(lows) >= 2:
            if last_high['price'] > highs[-2]['price'] and last_low['price'] > lows[-2]['price']:
                current_bias = "BULLISH"
            elif last_high['price'] < highs[-2]['price'] and last_low['price'] < lows[-2]['price']:
                current_bias = "BEARISH"

        return current_bias, last_high, last_low

    def find_order_blocks(self, rates, highs, lows):
        """Finds valid Order Blocks (Supply/Demand zones) with Validated Imbalance (FVG)."""
        obs = []
        
        # Look for Demand Zones (Last bearish candle before a strong move up)
        for low in lows:
            idx = low['index']
            if idx + 2 >= len(rates): continue
            
            # FVG Up: low of candle[i+2] > high of candle[i]
            imbalance = rates[idx+2]['low'] - rates[idx]['high']
            if imbalance >= config.MIN_FVG_SIZE:
                obs.append({
                    'type': 'DEMAND',
                    'top': rates[idx]['high'],
                    'bottom': rates[idx]['low'],
                    'time': rates[idx]['time'],
                    'strength': imbalance
                })

        # Look for Supply Zones (Last bullish candle before a strong move down)
        for high in highs:
            idx = high['index']
            if idx + 2 >= len(rates): continue
            
            # FVG Down: high of candle[i+2] < low of candle[i]
            imbalance = rates[idx]['low'] - rates[idx+2]['high']
            if imbalance >= config.MIN_FVG_SIZE:
                obs.append({
                    'type': 'SUPPLY',
                    'top': rates[idx]['high'],
                    'bottom': rates[idx]['low'],
                    'time': rates[idx]['time'],
                    'strength': imbalance
                })
        
        return obs

    def is_in_fib_zone(self, price, high, low, bias):
        """Checks if price is in Discount (for Buy) or Premium (for Sell) zone."""
        range_size = high - low
        if range_size == 0: return False
        
        retracement = (price - low) / range_size
        
        if bias == "BULLISH":
            # Looking for Buy in Discount (below 0.5) or deep discount (below 0.618)
            return retracement <= (1 - config.FIB_DISCOUNT_LEVEL) # e.g. retracement <= 0.382
        elif bias == "BEARISH":
            # Looking for Sell in Premium (above 0.5) or deep premium (above 0.618)
            return retracement >= config.FIB_DISCOUNT_LEVEL # e.g. retracement >= 0.618
            
        return False
