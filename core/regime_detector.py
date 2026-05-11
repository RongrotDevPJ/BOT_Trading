import MetaTrader5 as ag
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger("RegimeDetector")

class RegimeDetector:
    def __init__(self, lookback_candles=100, atr_period=14):
        self.lookback_candles = lookback_candles
        self.atr_period = atr_period

    def calculate_atr(self, df, period):
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(period).mean()
        return atr

    def detect_regime(self, symbol, timeframe=ag.TIMEFRAME_M15):
        """
        Detects the current market regime using Rolling Statistics.
        Returns: (state_name, probability)
        state_name: 'TRENDING' or 'RANGING' or 'UNKNOWN'
        """
        try:
            rates = ag.copy_rates_from_pos(symbol, timeframe, 0, self.lookback_candles)
            if rates is None or len(rates) < self.lookback_candles:
                return "UNKNOWN", 0.0

            df = pd.DataFrame(rates)
            
            # Feature 1: Normalized Returns Volatility
            df['returns'] = df['close'].pct_change()
            df['volatility'] = df['returns'].rolling(window=20).std()
            volatility_sma = df['volatility'].rolling(window=50).mean()
            
            # Feature 2: ATR Ratio (Current ATR vs Historical ATR)
            df['atr'] = self.calculate_atr(df, self.atr_period)
            df['atr_sma'] = df['atr'].rolling(window=50).mean()
            df['atr_ratio'] = df['atr'] / df['atr_sma']
            
            # Drop NaN rows due to rolling calculations
            df = df.dropna()
            
            if len(df) < 10:
                return "UNKNOWN", 0.0
                
            current_atr_ratio = df['atr_ratio'].iloc[-1]
            current_vol = df['volatility'].iloc[-1]
            avg_vol = volatility_sma.iloc[-1]
            
            # Logic: If ATR is higher than its moving average AND Volatility is expanding
            if current_atr_ratio > 1.0 and current_vol > avg_vol:
                state_name = "TRENDING"
                # Estimate confidence based on how far above average it is
                prob = min(99.0, 50 + (current_atr_ratio - 1.0) * 100)
            else:
                state_name = "RANGING"
                # Estimate confidence based on how far below average it is
                prob = min(99.0, 50 + (1.0 - current_atr_ratio) * 100)
            
            return state_name, round(prob, 1)

        except Exception as e:
            logger.error(f"Error detecting regime for {symbol}: {e}")
            return "UNKNOWN", 0.0
