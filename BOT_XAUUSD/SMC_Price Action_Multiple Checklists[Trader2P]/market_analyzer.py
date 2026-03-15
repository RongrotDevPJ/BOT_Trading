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
        """Detects BOS and CHoCH to determine current Bias."""
        rates = self.get_rates(symbol, timeframe_str)
        if len(rates) < 20: return "NEUTRAL", None, None

        highs, lows = self.find_fractals(rates)
        if not highs or not lows: return "NEUTRAL", None, None

        # Current price (latest close)
        current_price = rates[-1]['close']
        
        last_high = highs[-1]
        last_low = lows[-1]
        
        # Simple Logic for BOS/CHoCH
        # If price breaks last High -> Uptrend (BOS)
        # If price breaks last Low -> Downtrend (BOS)
        # If trend was UP and breaks last Low -> CHoCH (Reversal to Down)
        
        # For simplicity in this version, we use the relative positions of the last 2 highs/lows
        if len(highs) >= 2 and len(lows) >= 2:
            prev_high = highs[-2]
            prev_low = lows[-2]
            
            if last_high['price'] > prev_high['price'] and last_low['price'] > prev_low['price']:
                bias = "BULLISH"
            elif last_high['price'] < prev_high['price'] and last_low['price'] < prev_low['price']:
                bias = "BEARISH"
            else:
                bias = "RANGING"
        else:
            bias = "NEUTRAL"

        return bias, last_high, last_low

    def find_order_blocks(self, rates, highs, lows):
        """Finds valid Order Blocks (Supply/Demand zones) with Imbalance."""
        obs = [] # list of {'type': 'DEMAND'/'SUPPLY', 'top': float, 'bottom': float, 'validated': bool}
        
        # Look for Demand Zones (Last bearish candle before a strong move up)
        for low in lows:
            idx = low['index']
            if idx + 2 >= len(rates): continue
            
            # Check for Imbalance (FVG) right after the fractal
            # FVG Up: low of candle[i+2] > high of candle[i]
            if rates[idx+2]['low'] > rates[idx]['high'] + config.OB_IMBALANCE_MIN_GAP:
                # Valid Demand Zone! Use the body/range of the fractal candle or the candle before it
                obs.append({
                    'type': 'DEMAND',
                    'top': rates[idx]['high'],
                    'bottom': rates[idx]['low'],
                    'time': rates[idx]['time'],
                    'strength': rates[idx+2]['low'] - rates[idx]['high']
                })

        # Look for Supply Zones (Last bullish candle before a strong move down)
        for high in highs:
            idx = high['index']
            if idx + 2 >= len(rates): continue
            
            # FVG Down: high of candle[i+2] < low of candle[i]
            if rates[idx+2]['high'] < rates[idx]['low'] - config.OB_IMBALANCE_MIN_GAP:
                obs.append({
                    'type': 'SUPPLY',
                    'top': rates[idx]['high'],
                    'bottom': rates[idx]['low'],
                    'time': rates[idx]['time'],
                    'strength': rates[idx]['low'] - rates[idx+2]['high']
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
