import logging
import config
import datetime
from market_analyzer import MarketAnalyzer
from indicator import IndicatorClient
from csv_logger import CSVLogger
from line_notify import LineNotify

class SMCSniperStrategy:
    def __init__(self, mt5_client):
        self.mt5_client = mt5_client
        self.analyzer = MarketAnalyzer(mt5_client)
        self.indicators = IndicatorClient()
        self.notifier = LineNotify()
        self.logger = logging.getLogger(__name__)
        self.csv_logger = CSVLogger(config.SYMBOL)
        
        self.last_bias = None
        self.last_checklist_log = {} # To prevent log spam

    def log_checklist(self, key, status):
        """Logs checklist status only if it changes."""
        if self.last_checklist_log.get(key) != status:
            self.logger.info(f"[Checklist] {key}: {status}")
            self.last_checklist_log[key] = status

    def check_candlestick_pattern(self, rates):
        """Identifies Engulfing or Pin Bar patterns."""
        if len(rates) < 3: return None
        
        last = rates[-1]
        prev = rates[-2]
        
        # Bullish Engulfing
        if last['close'] > prev['open'] and prev['close'] < prev['open'] and last['close'] > last['open']:
            return "BULL_ENGULFING"
            
        # Bearish Engulfing
        if last['close'] < prev['open'] and prev['close'] > prev['open'] and last['close'] < last['open']:
            return "BEAR_ENGULFING"
            
        # Simple Pin Bar detection
        body_size = abs(last['close'] - last['open'])
        candle_range = last['high'] - last['low']
        if candle_range == 0: return None
        
        upper_wick = last['high'] - max(last['close'], last['open'])
        lower_wick = min(last['close'], last['open']) - last['low']
        
        if lower_wick > body_size * 2 and upper_wick < body_size:
            return "BULL_PINBAR"
        if upper_wick > body_size * 2 and lower_wick < body_size:
            return "BEAR_PINBAR"
            
        return None

    def calculate_lot_size(self, balance, sl_points):
        """Calculates lot size based on % risk, SL distance, and broker limits."""
        if sl_points <= 0: return 0.01
        
        symbol_info = ag.symbol_info(config.SYMBOL)
        if not symbol_info: return 0.01
        
        risk_amount = balance * (config.RISK_PERCENT / 100.0)
        
        # XAUUSD lot calculation: 
        # Risk = Lot * SL_Points * TickValue * ContractSize
        # So: Lot = Risk / (SL_Points * TickValue * ContractSize)
        # Note: on many brokers for Gold, SL_Points is already handle by the point value.
        tick_value = symbol_info.trade_tick_value
        tick_size = symbol_info.trade_tick_size
        
        if tick_size == 0 or sl_points == 0: return symbol_info.volume_min
        
        lot = risk_amount / (sl_points * tick_value / tick_size)
        
        # Round to nearest lot step
        step = symbol_info.volume_step
        lot = round(lot / step) * step
        
        # Bound by min/max
        return round(max(symbol_info.volume_min, min(lot, symbol_info.volume_max)), 2)

    def run_sniper_check(self, executor, tick):
        """Main entry checklist loop."""
        # 1. BIAS Alignment (H1)
        h1_bias, h1_high, h1_low = self.analyzer.analyze_structure(config.SYMBOL, config.HTF_TIMEFRAME)
        self.log_checklist("H1 Bias", h1_bias)
        
        # Alert if bias changes
        if h1_bias != self.last_bias:
            self.notifier.send_message(f"🚨 [SMC Alert] {config.SYMBOL} H1 Bias Changed to {h1_bias}")
            self.last_bias = h1_bias

        if h1_bias not in ["BULLISH", "BEARISH"]:
            return

        # 2. Zone Detection (H1 OB)
        h1_rates = self.analyzer.get_rates(config.SYMBOL, config.HTF_TIMEFRAME)
        h1_fractals = self.analyzer.find_fractals(h1_rates)
        obs = self.analyzer.find_order_blocks(h1_rates, h1_fractals[0], h1_fractals[1])
        
        # Check if price is near an OB
        active_ob = None
        for ob in obs:
            if h1_bias == "BULLISH" and ob['type'] == 'DEMAND':
                if tick.bid <= ob['top'] + 2.0 and tick.bid >= ob['bottom'] - 1.0: # Close to Demand
                    active_ob = ob
                    break
            elif h1_bias == "BEARISH" and ob['type'] == 'SUPPLY':
                if tick.ask >= ob['bottom'] - 2.0 and tick.ask <= ob['top'] + 1.0: # Close to Supply
                    active_ob = ob
                    break
        
        if not active_ob:
            self.log_checklist("Zone", "Wait (No active OB)")
            return
        self.log_checklist("Zone", f"IN ZONE ({active_ob['type']})")

        # 3. Fibonacci Check
        in_fib = self.analyzer.is_in_fib_zone(tick.bid, h1_high['price'], h1_low['price'], h1_bias)
        self.log_checklist("Fib Zone", "OK" if in_fib else "Wait")
        if not in_fib: return

        # 4. LTF Execution (M15 CHoCH / Price Action)
        m15_rates = self.analyzer.get_rates(config.SYMBOL, config.LTF_TIMEFRAME)
        pa_pattern = self.check_candlestick_pattern(m15_rates)
        self.log_checklist("PA Pattern", pa_pattern if pa_pattern else "Wait")
        
        if not pa_pattern: return
        
        # Confirmation alignment
        if h1_bias == "BULLISH" and "BULL" in pa_pattern:
            self.execute_trade("BUY", tick, active_ob, executor)
        elif h1_bias == "BEARISH" and "BEAR" in pa_pattern:
            self.execute_trade("SELL", tick, active_ob, executor)

    def execute_trade(self, side, tick, ob, executor):
        """Executes the trade with calculated SL/TP."""
        balance = self.mt5_client.get_account_info().balance
        
        if side == "BUY":
            price = tick.ask
            sl = ob['bottom'] - 1.0 # Buffer below OB
            tp = price + (price - sl) * config.MIN_RR_RATIO
        else:
            price = tick.bid
            sl = ob['top'] + 1.0 # Buffer above OB
            tp = price - (sl - price) * config.MIN_RR_RATIO
            
        sl_points = abs(price - sl)
        lots = self.calculate_lot_size(balance, sl_points)
        
        self.logger.info(f"🚀 [SIGNAL] Executing {side} Sniper Trade! Lot: {lots}, SL: {sl:.2f}, TP: {tp:.2f}")
        
        # Check if already have a position to avoid double entry (simple filter)
        if not executor.get_positions(config.SYMBOL):
            executor.open_position(side, lots, price, sl, tp, "SMC Sniper")
            self.csv_logger.log_event(action=f"ENTRY_{side}", price=price, lot=lots, sl=sl, tp=tp)

    def manage_trades(self, executor, tick):
        """Manages Breakeven and Trailing."""
        positions = executor.get_positions(config.SYMBOL)
        for pos in positions:
            # Breakeven Logic
            if pos.magic == 999: # Simplified Magic check or comment
                profit_points = pos.profit / (pos.volume * 10) # rough est
                sl_dist = abs(pos.price_open - pos.sl)
                
                # If profit > 1R
                if profit_points > sl_dist * config.BREAKEVEN_AT_R:
                    if (pos.type == 0 and pos.sl < pos.price_open) or (pos.type == 1 and pos.sl > pos.price_open):
                        self.logger.info(f"🛡️ [Breakeven] Moving SL to Entry for position {pos.ticket}")
                        executor.modify_position(pos.ticket, pos.price_open, pos.tp)
