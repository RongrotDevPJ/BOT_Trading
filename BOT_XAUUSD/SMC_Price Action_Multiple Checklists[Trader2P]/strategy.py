import logging
import config
import datetime
import sys
import time
from pathlib import Path

# Add project root to path for shared_utils
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from market_analyzer import MarketAnalyzer
from shared_utils.csv_logger import CSVLogger
from shared_utils.indicator import IndicatorClient
import MetaTrader5 as ag

class SMCSniperStrategy:
    def __init__(self, mt5_client):
        self.mt5_client = mt5_client
        self.analyzer = MarketAnalyzer(mt5_client)
        self.indicators = IndicatorClient()
        self.logger = logging.getLogger("SMCSniper")
        self.csv_logger = CSVLogger(config.SYMBOL)
        
        self.last_bias = None
        self.last_checklist_log = {} # To prevent log spam

    def get_positions(self):
        """Gets all open positions managed by this bot."""
        return self.mt5_client.get_open_positions(symbol=config.SYMBOL, magic=config.MAGIC_NUMBER)

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
            return "BULLISH_ENGULFING"
        # Bearish Engulfing
        if last['close'] < prev['open'] and prev['close'] > prev['open'] and last['close'] < last['open']:
            return "BEARISH_ENGULFING"
            
        return None

    def calculate_lot_size(self, balance, sl_points):
        """Calculates lot size based on fixed risk percentage."""
        if sl_points <= 0: return config.MIN_LOT
        
        risk_amount = balance * (config.RISK_PER_TRADE / 100.0)
        point_value = ag.symbol_info(config.SYMBOL).trade_tick_value
        
        if point_value == 0: return config.MIN_LOT
        
        lots = risk_amount / (sl_points * point_value)
        lots = round(lots, 2)
        
        return max(config.MIN_LOT, min(config.MAX_LOT, lots))

    def run_sniper_check(self, executor, tick):
        """Main entry signal detection."""
        # 1. HTF Bias (H1 BOS/CHoCH)
        h1_bias, h1_high, h1_low = self.analyzer.analyze_structure(config.SYMBOL, config.HTF_TIMEFRAME)
        self.log_checklist("H1 Bias", h1_bias)
        self.last_bias = h1_bias
        
        if h1_bias == "NEUTRAL":
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
        self.log_checklist("In Zone", True)
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
        account = self.mt5_client.get_account_info()
        balance = account.balance if account else 0
        
        if side == "BUY":
            order_type = ag.ORDER_TYPE_BUY
            price = tick.ask
            sl = ob['bottom'] - 1.0 # Buffer below OB
            tp = price + (price - sl) * config.MIN_RR_RATIO
        else:
            order_type = ag.ORDER_TYPE_SELL
            price = tick.bid
            sl = ob['top'] + 1.0 # Buffer above OB
            tp = price - (sl - price) * config.MIN_RR_RATIO
            
        sl_points_val = abs(price - sl)
        point = ag.symbol_info(config.SYMBOL).point
        sl_points = sl_points_val / point
        
        lots = self.calculate_lot_size(balance, sl_points)
        
        self.logger.info(f"🚀 [SIGNAL] Executing {side} Sniper Trade! Lot: {lots}, SL: {sl:.2f}, TP: {tp:.2f}")
        
        # Check if already have a position to avoid double entry (simple filter)
        if not self.get_positions():
            result = executor.send_order(config.SYMBOL, order_type, lots, price, sl, tp)
            if result:
                self.csv_logger.log_event(action=f"ENTRY_{side}", side=side, price=price, lot_size=lots, sl=sl, tp=tp, ticket=result.order, notes="Sniper Entry")

    def manage_trades(self, executor, tick):
        """Manages Breakeven and Trailing."""
        positions = self.get_positions()
        for pos in positions:
            # Breakeven Logic
            # Since we only have one sniper position usually, magic check is enough
            profit_points = pos.profit / (pos.volume * 10) # rough estimate for major pairs/gold
            sl_dist = abs(pos.price_open - pos.sl)
            
            # If profit > 1R (or whatever config says)
            if profit_points > sl_dist * getattr(config, 'BREAKEVEN_AT_R', 1.0):
                if (pos.type == ag.ORDER_TYPE_BUY and pos.sl < pos.price_open) or \
                   (pos.type == ag.ORDER_TYPE_SELL and pos.sl > pos.price_open):
                    self.logger.info(f"🛡️ [Breakeven] Moving SL to Entry for position {pos.ticket}")
                    executor.modify_sl(pos.ticket, config.SYMBOL, pos.price_open)
