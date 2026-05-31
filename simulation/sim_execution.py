"""
simulation/sim_execution.py
Realistic Virtual Execution Engine for Paper Trading Simulation.

Simulates:
  - Dynamic spread by session + news events
  - Gaussian slippage model (normal vs volatile conditions)
  - Swap charges (overnight positions)
  - Commission model
  - Partial fill simulation (large lots)
  - Realistic P&L calculation using tick value (Cent Account)

Key design: All orders go through VirtualExecution.fill()
which returns a SimFill object with realistic fill price.
"""

import random
import logging
import time
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("SimExecution")


# ── Data Structures ────────────────────────────────────────────────────────────

@dataclass
class SimOrder:
    """Represents a virtual order before fill."""
    strategy: str
    side: str             # 'BUY' or 'SELL'
    lot_size: float
    sl_price: float
    tp1_price: float
    tp2_price: Optional[float] = None
    comment: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Context at time of order
    ask: float = 0.0
    bid: float = 0.0
    spread_pts: int = 30
    atr: float = 0.0
    rsi: float = 50.0
    regime: str = "UNKNOWN"
    ml_score: float = 0.0


@dataclass
class SimFill:
    """Represents a completed virtual fill."""
    success: bool
    fill_price: float
    fill_lot: float
    simulated_spread: int
    simulated_slippage: float
    fill_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = ""

    @property
    def total_cost_pts(self) -> float:
        return self.simulated_spread + abs(self.simulated_slippage)


@dataclass
class SimPosition:
    """Represents an open virtual position."""
    id: int
    strategy: str
    side: str
    lot_size: float
    entry_price: float
    sl_price: float
    tp1_price: float
    tp2_price: Optional[float]
    open_time: str
    symbol: str = "XAUUSD"

    # Tracking
    mae_points: float = 0.0   # Maximum Adverse Excursion (pts, always positive)
    mfe_points: float = 0.0   # Maximum Favorable Excursion (pts, always positive)
    days_held: float = 0.0
    tp1_hit: bool = False      # TP1 already partially closed
    db_id: Optional[int] = None  # DB row ID after insert


# ── Spread Model ───────────────────────────────────────────────────────────────

class SpreadModel:
    """
    Returns estimated spread in points based on server time hour.
    Optionally spikes during high-impact news windows.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self._news_window_end: float = 0.0  # Timestamp of news window end

    def get_spread(self, dt: datetime, current_atr: float = 0.0) -> int:
        hour = dt.hour

        # News spike (random event every ~8 hours, 5-minute window)
        now = time.time()
        if now < self._news_window_end:
            return self.cfg.SPREAD_NEWS
        # Randomly trigger news event
        if random.random() < 0.0001:  # ~0.01% chance per second = ~3.6 per hour
            self._news_window_end = now + 300  # 5-minute spike
            logger.info("[SpreadModel] 📰 Simulated news spike! Spread → 150pts for 5 min.")
            return self.cfg.SPREAD_NEWS

        if 0 <= hour < 7:
            return self.cfg.SPREAD_ASIA
        elif 7 <= hour < 12:
            return self.cfg.SPREAD_LONDON
        elif 12 <= hour < 17:
            return self.cfg.SPREAD_NY
        elif 17 <= hour < 20:
            return self.cfg.SPREAD_OVERLAP
        else:
            return self.cfg.SPREAD_ASIA


# ── Slippage Model ─────────────────────────────────────────────────────────────

class SlippageModel:
    """
    Generates realistic slippage from Gaussian distribution.
    Two modes: normal and volatile (based on ATR threshold).
    """

    def __init__(self, cfg):
        self.cfg = cfg

    def sample(self, current_atr: float = 0.0) -> float:
        """Returns slippage in points (can be positive = worse fill)."""
        if current_atr >= self.cfg.ATR_VOLATILE_THRESHOLD:
            slip = abs(random.gauss(
                self.cfg.SLIPPAGE_MEAN_VOLATILE,
                self.cfg.SLIPPAGE_STD_VOLATILE
            ))
        else:
            slip = abs(random.gauss(
                self.cfg.SLIPPAGE_MEAN_NORMAL,
                self.cfg.SLIPPAGE_STD_NORMAL
            ))
        return round(slip, 1)


# ── P&L Calculator ─────────────────────────────────────────────────────────────

class PnLCalculator:
    """
    Calculates P&L for XAUUSD Cent Account positions.

    Cent Account: 1 lot = 1,000 units (not 100,000)
    XAUUSD: 1 pip = 0.01 = 1 point
    Tick value per 0.01 lot on cent = ~$0.001 (USC = $0.01)

    Formula (approximation for XAUUSD Cent):
        profit_usc = (close - open) * direction * lot * 100
        (This gives result in Cent = USC)
    """

    def calc_profit(self, entry: float, close: float, side: str, lot: float) -> float:
        """Returns gross profit in USC (Cent account)."""
        direction = 1 if side == "BUY" else -1
        # XAUUSD: price in USD/oz, lot in mini lots on cent
        # Approx: 1 point movement × 0.01 lot × 100 (cent multiplier) = 0.01 USC
        profit_usd = (close - entry) * direction * lot * 100
        return round(profit_usd, 4)

    def calc_swap(self, side: str, lot: float, days: float, cfg) -> float:
        """Returns swap charge in USC."""
        rate = cfg.SWAP_LONG_PER_LOT_PER_DAY if side == "BUY" else cfg.SWAP_SHORT_PER_LOT_PER_DAY
        return round(rate * lot * days, 4)

    def calc_commission(self, lot: float, cfg) -> float:
        return round(cfg.COMMISSION_PER_LOT_USC * lot, 4)


# ── Virtual Execution Engine ───────────────────────────────────────────────────

class VirtualExecution:
    """
    Simulates broker order filling with realistic spread, slippage,
    commission, and swap.

    Usage:
        vx = VirtualExecution(cfg)
        fill = vx.fill_order(order, ask, bid, atr)
        position = SimPosition(entry_price=fill.fill_price, ...)
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.spread_model = SpreadModel(cfg)
        self.slippage_model = SlippageModel(cfg)
        self.pnl_calc = PnLCalculator()
        self._next_id = 1

    def fill_order(self, order: SimOrder, ask: float, bid: float,
                   atr: float = 0.0, dt: datetime = None) -> SimFill:
        """
        Simulate filling an order with realistic execution.
        Returns SimFill with actual fill price.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        spread = self.spread_model.get_spread(dt, atr)
        slippage = self.slippage_model.sample(atr)
        point = 0.01  # XAUUSD point size

        if order.side == "BUY":
            # BUY fills at ASK + slippage (worse fill for buyer)
            fill_price = ask + (slippage * point)
        else:
            # SELL fills at BID - slippage (worse fill for seller)
            fill_price = bid - (slippage * point)

        return SimFill(
            success=True,
            fill_price=round(fill_price, 2),
            fill_lot=order.lot_size,
            simulated_spread=spread,
            simulated_slippage=slippage,
            fill_time=dt.isoformat(),
        )

    def close_position(self, position: SimPosition, close_ask: float,
                       close_bid: float, atr: float = 0.0,
                       dt: datetime = None, reason: str = "MANUAL") -> dict:
        """
        Simulate closing a position.
        Returns dict with all P&L components.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        slippage = self.slippage_model.sample(atr)
        point = 0.01

        if position.side == "BUY":
            close_price = close_bid - (slippage * point)
        else:
            close_price = close_ask + (slippage * point)

        close_price = round(close_price, 2)

        # Calculate days held
        try:
            open_dt = datetime.fromisoformat(position.open_time.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days_held = (dt - open_dt).total_seconds() / 86400
        except Exception:
            days_held = 0.0

        gross = self.pnl_calc.calc_profit(
            position.entry_price, close_price, position.side, position.lot_size
        )
        swap = self.pnl_calc.calc_swap(position.side, position.lot_size, days_held, self.cfg)
        commission = self.pnl_calc.calc_commission(position.lot_size, self.cfg)
        net = round(gross + swap - commission, 4)

        return {
            "close_price":      close_price,
            "close_time":       dt.isoformat(),
            "gross_profit":     gross,
            "swap":             swap,
            "commission":       commission,
            "net_profit":       net,
            "close_reason":     reason,
            "simulated_slippage": slippage,
            "days_held":        round(days_held, 4),
        }

    def update_excursion(self, position: SimPosition,
                         current_high: float, current_low: float) -> None:
        """Update MAE/MFE for open position."""
        if position.side == "BUY":
            # MFE = how far in profit price went
            mfe = current_high - position.entry_price
            # MAE = how far against us price went
            mae = position.entry_price - current_low
        else:
            mfe = position.entry_price - current_low
            mae = current_high - position.entry_price

        position.mfe_points = max(position.mfe_points, mfe / 0.01)
        position.mae_points = max(position.mae_points, mae / 0.01)

    def get_next_id(self) -> int:
        self._next_id += 1
        return self._next_id
