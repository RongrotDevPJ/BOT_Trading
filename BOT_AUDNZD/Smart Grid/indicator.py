import MetaTrader5 as ag
import logging

class IndicatorClient:
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _calculate_rsi(self, prices, period):
        """
        Calculates the Relative Strength Index (RSI) purely using built-in Python.
        Avoids the need for external libraries like NumPy or Pandas for a lighter bot.
        Note: We use Wilder's Smoothing method for standard RSI.
        """
        if len(prices) < period + 1:
            return None

        # Calculate price differences
        diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

        # Separate gains and losses
        gains = [d if d > 0 else 0 for d in diffs]
        losses = [abs(d) if d < 0 else 0 for d in diffs]

        # Calculate initial averages (Simple Moving Average)
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        # Calculate RSI for the first point
        if avg_loss == 0:
            rs = 0
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        # Wilder's Smoothing for the rest of the data
        for i in range(period, len(diffs)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

        return rsi

    def get_rsi(self, symbol, timeframe, period):
        """
        Fetches recent candles and calculates the current RSI.
        Fetches extra candles (`period * 2`) to ensure Wilder's smoothing is accurate.
        """
        # Fetch rates: need enough data to smooth the RSI properly (at least period * 2 or more)
        num_candles = period * 3 
        rates = ag.copy_rates_from_pos(symbol, timeframe, 0, num_candles)

        if rates is None or len(rates) < num_candles:
            self.logger.warning(f"Could not fetch enough rates to calculate RSI for {symbol}.")
            return None

        # Extract closing prices
        close_prices = [candle[4] for candle in rates] # index 4 is usually close, but we can access by name if it's a structured array
        
        # MetaTrader5 returns a numpy structured array, let's convert it safely
        close_prices = [float(rate['close']) for rate in rates]

        # Ensure we only calculate on completed candles if needed, but for real-time we can use the latest (index -1)
        rsi_value = self._calculate_rsi(close_prices, period)
        
    def _calculate_atr(self, rates, period):
        """
        Calculates the Average True Range (ATR) purely using built-in Python.
        """
        if len(rates) < period + 1:
             return None
             
        true_ranges = []
        # Calculate True Range for each candle
        for i in range(1, len(rates)):
            high = rates[i]['high']
            low = rates[i]['low']
            prev_close = rates[i-1]['close']
            
            tr1 = high - low
            tr2 = abs(high - prev_close)
            tr3 = abs(low - prev_close)
            
            true_range = max(tr1, tr2, tr3)
            true_ranges.append(true_range)
            
        # Initial ATR is simple moving average of first 'period' TRs
        atr = sum(true_ranges[:period]) / period
        
        # Smoothed ATR for subsequent values (Wilder's smoothing)
        for i in range(period, len(true_ranges)):
             atr = ((atr * (period - 1)) + true_ranges[i]) / period
             
        return atr
        
    def get_atr(self, symbol, timeframe, period):
        """ Fetches recent candles and calculates current ATR. """
        num_candles = period * 3
        rates = ag.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
        
        if rates is None or len(rates) < num_candles:
            self.logger.warning(f"Could not fetch enough rates to calculate ATR for {symbol}.")
            return None
            
        return self._calculate_atr(rates, period)
        
    def _calculate_ema(self, prices, period):
        """ Calculates Exponential Moving Average (EMA). """
        if len(prices) < period:
             return None
             
        # Initial EMA is the Simple Moving Average of the first 'period' prices
        ema = sum(prices[:period]) / period
        
        # Multiplier
        multiplier = 2 / (period + 1)
        
        # Apply EMA formula to the rest of the prices
        for i in range(period, len(prices)):
             ema = (prices[i] - ema) * multiplier + ema
             
        return ema
        
    def get_ema(self, symbol, timeframe, period):
        """ Fetches data and calculates EMA. """
        num_candles = period * 2 # Need enough historical data to stabilize EMA
        rates = ag.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
        
        if rates is None or len(rates) < num_candles:
            self.logger.warning(f"Could not fetch enough rates to calculate EMA for {symbol}.")
            return None
            
        close_prices = [float(rate['close']) for rate in rates]
        return self._calculate_ema(close_prices, period)
