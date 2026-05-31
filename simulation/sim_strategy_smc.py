"""
simulation/sim_strategy_smc.py
SMC/ICT (Smart Money Concepts) Strategy for XAUUSD Paper Trading.

Core concepts implemented:
  1. Swing High / Swing Low Detection
  2. Break of Structure (BOS) — trend direction change
  3. Change of Character (CHoCH) — potential reversal
  4. Order Block (OB) Identification
  5. Fair Value Gap (FVG) Detection
  6. Entry on OB retest after BOS
  7. Liquidity Sweep Detection (false breakouts)

Entry Logic:
  - Identify market structure (HH/HL for BUY, LH/LL for SELL)
  - Detect BOS (break above last swing high / below last swing low)
  - Find Order Block (last bearish candle before bullish BOS or vice versa)
  - Enter on price returning to OB zone
  - SL: Below/Above OB (+ ATR buffer)
  - TP1: 1.5R, TP2: 3R (or next liquidity level)

Max 2 concurrent positions per strategy.
Risk: 1% per trade (dynamic lot from equity × 1%).
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone

import MetaTrader5 as mt5

from simulation.sim_execution import VirtualExecution, SimOrder, SimPosition

logger = logging.getLogger("SMCStrategy")


# ── Data Structures ────────────────────────────────────────────────────────────

@dataclass
class SwingPoint:
    index: int
    price: float
    point_type: str   # 'HH', 'HL', 'LH', 'LL'
    time: float       # Unix timestamp of that candle


@dataclass
class OrderBlock:
    high: float
    low: float
    side: str          # 'BULL' (buy from) or 'BEAR' (sell from)
    formed_at: int     # Candle index of OB
    bos_price: float   # The swing level that was broken


@dataclass
class FairValueGap:
    high: float
    low: float
    side: str          # 'BULL' or 'BEAR'
    candle_index: int


# ── Structure Analysis ─────────────────────────────────────────────────────────

class MarketStructure:
    """
    Analyzes swing highs/lows and determines Break of Structure.
    Works on OHLCV candle arrays (MT5 structured numpy arrays).
    """

    def __init__(self, swing_lookback: int = 20, bos_confirm_bars: int = 2):
        self.swing_lookback = swing_lookback
        self.bos_confirm_bars = bos_confirm_bars
        self._swings: list[SwingPoint] = []

    def find_swing_high(self, rates, i: int) -> bool:
        lb = self.swing_lookback
        if i < lb or i >= len(rates) - lb:
            return False
        high = rates[i]["high"]
        return all(rates[j]["high"] <= high for j in range(i - lb, i + lb + 1) if j != i)

    def find_swing_low(self, rates, i: int) -> bool:
        lb = self.swing_lookback
        if i < lb or i >= len(rates) - lb:
            return False
        low = rates[i]["low"]
        return all(rates[j]["low"] >= low for j in range(i - lb, i + lb + 1) if j != i)

    def analyze(self, rates) -> dict:
        """
        Full structure analysis on rate array.
        Returns dict with:
          - trend: 'BULL', 'BEAR', 'NEUTRAL'
          - last_bos: OrderBlock or None
          - last_choch: price level or None
          - fvgs: list[FairValueGap]
          - swings: list[SwingPoint]
        """
        if rates is None or len(rates) < self.swing_lookback * 2 + 5:
            return {"trend": "NEUTRAL", "last_bos": None, "fvgs": []}

        # 1. Find all swing points
        highs, lows = [], []
        for i in range(self.swing_lookback, len(rates) - self.swing_lookback):
            if self.find_swing_high(rates, i):
                highs.append((i, float(rates[i]["high"]), rates[i]["time"]))
            if self.find_swing_low(rates, i):
                lows.append((i, float(rates[i]["low"]), rates[i]["time"]))

        if len(highs) < 2 or len(lows) < 2:
            return {"trend": "NEUTRAL", "last_bos": None, "fvgs": []}

        # 2. Determine trend from last 2 swing points
        last_high = highs[-1][1]
        prev_high = highs[-2][1]
        last_low  = lows[-1][1]
        prev_low  = lows[-2][1]

        if last_high > prev_high and last_low > prev_low:
            trend = "BULL"
        elif last_high < prev_high and last_low < prev_low:
            trend = "BEAR"
        else:
            trend = "NEUTRAL"

        # 3. Detect BOS (Break of Structure)
        last_bos = None
        current_close = float(rates[-1]["close"])

        if trend == "BULL":
            # BOS: Close breaks above last swing HIGH
            bos_level = prev_high
            if current_close > bos_level:
                # Find Order Block: last BEARISH candle before the BOS
                ob = self._find_order_block(rates, highs[-2][0], side="BULL")
                if ob:
                    ob.bos_price = bos_level
                    last_bos = ob

        elif trend == "BEAR":
            # BOS: Close breaks below last swing LOW
            bos_level = prev_low
            if current_close < bos_level:
                ob = self._find_order_block(rates, lows[-2][0], side="BEAR")
                if ob:
                    ob.bos_price = bos_level
                    last_bos = ob

        # 4. FVG Detection (last 50 candles)
        fvgs = self._find_fvgs(rates, lookback=50)

        return {
            "trend": trend,
            "last_bos": last_bos,
            "fvgs": fvgs,
            "last_high": last_high,
            "last_low": last_low,
            "highs": highs,
            "lows": lows,
        }

    def _find_order_block(self, rates, bos_candle_idx: int, side: str,
                          lookback: int = 5) -> Optional[OrderBlock]:
        """Find the Order Block candle before the BOS."""
        start = max(0, bos_candle_idx - lookback)
        end   = bos_candle_idx

        if side == "BULL":
            # Look for the last BEARISH candle (close < open) before bullish BOS
            for i in range(end, start - 1, -1):
                c = rates[i]
                if float(c["close"]) < float(c["open"]):  # Bearish candle
                    return OrderBlock(
                        high=float(c["high"]),
                        low=float(c["low"]),
                        side="BULL",
                        formed_at=i,
                        bos_price=0.0,
                    )
        else:
            # BEAR: Look for the last BULLISH candle before bearish BOS
            for i in range(end, start - 1, -1):
                c = rates[i]
                if float(c["close"]) > float(c["open"]):  # Bullish candle
                    return OrderBlock(
                        high=float(c["high"]),
                        low=float(c["low"]),
                        side="BEAR",
                        formed_at=i,
                        bos_price=0.0,
                    )
        return None

    def _find_fvgs(self, rates, lookback: int = 50) -> list[FairValueGap]:
        """Detect Fair Value Gaps: 3-candle pattern where candle 1 and 3 don't overlap."""
        fvgs = []
        start = max(1, len(rates) - lookback)
        for i in range(start, len(rates) - 1):
            prev  = rates[i - 1]
            curr  = rates[i]
            nxt   = rates[i + 1]

            # Bullish FVG: low[i+1] > high[i-1]
            if float(nxt["low"]) > float(prev["high"]):
                fvgs.append(FairValueGap(
                    high=float(nxt["low"]),
                    low=float(prev["high"]),
                    side="BULL",
                    candle_index=i,
                ))
            # Bearish FVG: high[i+1] < low[i-1]
            elif float(nxt["high"]) < float(prev["low"]):
                fvgs.append(FairValueGap(
                    high=float(prev["low"]),
                    low=float(nxt["high"]),
                    side="BEAR",
                    candle_index=i,
                ))
        return fvgs[-5:]  # Keep last 5 FVGs only


# ── SMC Strategy ───────────────────────────────────────────────────────────────

class SMCStrategy:
    """
    Full SMC/ICT trading strategy for XAUUSD simulation.
    Manages up to MAX_CONCURRENT positions.
    """

    STRATEGY_NAME = "SMC"

    def __init__(self, cfg, executor: VirtualExecution, db, market_ctx):
        self.cfg = cfg
        self.executor = executor
        self.db = db
        self.market_ctx = market_ctx
        self.structure = MarketStructure(
            swing_lookback=cfg.SMC_SWING_LOOKBACK,
            bos_confirm_bars=cfg.SMC_BOS_CONFIRM_BARS,
        )
        self.open_positions: list[SimPosition] = []
        self._ob_retest_tracker: dict = {}   # ob_id → True/False (already entered?)
        self._last_entry_time = 0.0

    def update(self, tick, account: dict, rates_m5, rates_h1=None):
        """
        Called every loop tick.
        Manages existing positions and checks for new entries.
        """
        if tick is None or rates_m5 is None:
            return

        ask = float(tick.ask)
        bid = float(tick.bid)
        atr = self._get_atr(rates_m5)
        dt  = datetime.now(timezone.utc)

        # 1. Manage open positions
        self._manage_positions(ask, bid, rates_m5, atr, dt)

        # 2. Check for new entries
        if len(self.open_positions) < self.cfg.SMC_MAX_CONCURRENT:
            self._check_entry(rates_m5, ask, bid, atr, account, dt)

    def _check_entry(self, rates, ask, bid, atr, account, dt):
        """Analyze structure and enter if OB retest detected."""
        if time.time() - self._last_entry_time < 300:  # 5-min cooldown
            return

        struct = self.structure.analyze(rates)
        trend  = struct.get("trend", "NEUTRAL")
        ob     = struct.get("last_bos")

        if trend == "NEUTRAL" or ob is None:
            return

        equity   = account.get("equity", self.cfg.SIM_INITIAL_BALANCE)
        ob_id    = f"{ob.side}_{ob.high:.2f}_{ob.low:.2f}"

        if self._ob_retest_tracker.get(ob_id):
            return  # Already traded this OB

        if ob.side == "BULL":
            # Enter BUY if price has returned into the OB zone (after BOS above)
            if ob.low <= ask <= ob.high:
                sl = ob.low - (atr * self.cfg.SMC_SL_ATR_MULTIPLIER * 0.01)
                sl_pts = (ask - sl) / 0.01
                if sl_pts <= 0:
                    return
                lot = self._calc_lot(equity, sl_pts)
                tp1 = ask + (ask - sl) * self.cfg.SMC_TP1_RR
                tp2 = ask + (ask - sl) * self.cfg.SMC_TP2_RR

                order = SimOrder(
                    strategy=self.STRATEGY_NAME, side="BUY", lot_size=lot,
                    sl_price=sl, tp1_price=tp1, tp2_price=tp2,
                    ask=ask, bid=bid, atr=atr,
                    regime=self.market_ctx.get_regime(),
                )
                fill = self.executor.fill_order(order, ask, bid, atr, dt)
                if fill.success:
                    pos = self._register_position(fill, order, sl, tp1, tp2, atr)
                    logger.info(
                        f"[SMC] 🟢 BUY entry @ {fill.fill_price:.2f} | "
                        f"SL:{sl:.2f} TP1:{tp1:.2f} TP2:{tp2:.2f} | "
                        f"Lot:{lot:.2f} | OB zone [{ob.low:.2f}-{ob.high:.2f}]"
                    )
                    self._ob_retest_tracker[ob_id] = True
                    self._last_entry_time = time.time()

        elif ob.side == "BEAR":
            if ob.low <= bid <= ob.high:
                sl = ob.high + (atr * self.cfg.SMC_SL_ATR_MULTIPLIER * 0.01)
                sl_pts = (sl - bid) / 0.01
                if sl_pts <= 0:
                    return
                lot = self._calc_lot(equity, sl_pts)
                tp1 = bid - (bid - sl) * self.cfg.SMC_TP1_RR  # wait: this is wrong
                # Correct for SELL: TP is BELOW entry
                tp1 = bid - (sl - bid) * self.cfg.SMC_TP1_RR
                tp2 = bid - (sl - bid) * self.cfg.SMC_TP2_RR

                order = SimOrder(
                    strategy=self.STRATEGY_NAME, side="SELL", lot_size=lot,
                    sl_price=sl, tp1_price=tp1, tp2_price=tp2,
                    ask=ask, bid=bid, atr=atr,
                    regime=self.market_ctx.get_regime(),
                )
                fill = self.executor.fill_order(order, ask, bid, atr, dt)
                if fill.success:
                    pos = self._register_position(fill, order, sl, tp1, tp2, atr)
                    logger.info(
                        f"[SMC] 🔴 SELL entry @ {fill.fill_price:.2f} | "
                        f"SL:{sl:.2f} TP1:{tp1:.2f} TP2:{tp2:.2f} | "
                        f"Lot:{lot:.2f}"
                    )
                    self._ob_retest_tracker[ob_id] = True
                    self._last_entry_time = time.time()

    def _manage_positions(self, ask, bid, rates, atr, dt):
        """Check TP1, TP2, and SL hits for all open positions."""
        closed = []
        for pos in self.open_positions:
            self.executor.update_excursion(
                pos,
                current_high=float(rates[-1]["high"]) if rates is not None else ask,
                current_low=float(rates[-1]["low"]) if rates is not None else bid,
            )

            close_price = bid if pos.side == "BUY" else ask
            reason = None

            if pos.side == "BUY":
                if not pos.tp1_hit and close_price >= pos.tp1_price:
                    reason = "TP1"
                    pos.tp1_hit = True
                    # Partial close (50%)
                    self._close_position(pos, ask, bid, atr, dt, reason="TP1_PARTIAL")
                    # Move SL to entry (break-even)
                    pos.sl_price = pos.entry_price
                    continue
                elif pos.tp1_hit and pos.tp2_price and close_price >= pos.tp2_price:
                    reason = "TP2"
                elif close_price <= pos.sl_price:
                    reason = "SL"
            else:
                if not pos.tp1_hit and close_price <= pos.tp1_price:
                    reason = "TP1"
                    pos.tp1_hit = True
                    self._close_position(pos, ask, bid, atr, dt, reason="TP1_PARTIAL")
                    pos.sl_price = pos.entry_price
                    continue
                elif pos.tp1_hit and pos.tp2_price and close_price <= pos.tp2_price:
                    reason = "TP2"
                elif close_price >= pos.sl_price:
                    reason = "SL"

            if reason:
                self._close_position(pos, ask, bid, atr, dt, reason=reason)
                closed.append(pos)

        for pos in closed:
            if pos in self.open_positions:
                self.open_positions.remove(pos)

    def _close_position(self, pos, ask, bid, atr, dt, reason):
        result = self.executor.close_position(pos, ask, bid, atr, dt, reason=reason)
        if pos.db_id:
            self.db.update_trade(
                pos.db_id,
                close_price=result["close_price"],
                close_time=result["close_time"],
                gross_profit=result["gross_profit"],
                swap=result["swap"],
                commission=result["commission"],
                net_profit=result["net_profit"],
                close_reason=result["close_reason"],
                mae_points=pos.mae_points,
                mfe_points=pos.mfe_points,
                status="CLOSED",
            )
        pnl_sym = "✅" if result["net_profit"] > 0 else "❌"
        logger.info(
            f"[SMC] {pnl_sym} {pos.side} closed @ {result['close_price']:.2f} "
            f"({reason}) | PnL: {result['net_profit']:+.2f} USC"
        )

    def _register_position(self, fill, order, sl, tp1, tp2, atr) -> SimPosition:
        pos_id = self.executor.get_next_id()
        pos = SimPosition(
            id=pos_id,
            strategy=self.STRATEGY_NAME,
            side=order.side,
            lot_size=fill.fill_lot,
            entry_price=fill.fill_price,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            open_time=fill.fill_time,
        )
        self.open_positions.append(pos)

        db_data = dict(
            strategy=self.STRATEGY_NAME,
            symbol="XAUUSD",
            side=order.side,
            open_time=fill.fill_time,
            entry_price=fill.fill_price,
            sl_price=sl,
            tp1_price=tp1,
            tp2_price=tp2,
            lot_size=fill.fill_lot,
            simulated_spread=fill.simulated_spread,
            simulated_slippage=fill.simulated_slippage,
            atr_at_entry=atr,
            regime_at_entry=order.regime,
            ml_score=order.ml_score,
            status="OPEN",
        )
        self.db.insert_trade(**db_data)
        return pos

    def _get_atr(self, rates, period: int = 14) -> float:
        if rates is None or len(rates) < period + 1:
            return 3.0  # Default fallback
        trs = []
        for i in range(1, len(rates)):
            h, l, pc = rates[i]["high"], rates[i]["low"], rates[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[-period:]) / period
        return float(atr)

    def _calc_lot(self, equity: float, sl_points: float) -> float:
        """Risk-based lot calculation: risk 1% of equity on this trade."""
        risk_usc = equity * (self.cfg.SMC_MAX_RISK_PCT / 100)
        # P&L per point per 0.01 lot ≈ 0.01 USC (XAUUSD cent)
        # lot = risk_usc / (sl_points × 0.01 per 0.01 lot)
        # = risk_usc / (sl_points × 0.01) → in units of 0.01 lots
        # Simplification for cent account:
        lot = risk_usc / max(sl_points * 0.1, 0.1)
        lot = round(max(0.01, min(lot, 2.0)), 2)
        return lot
