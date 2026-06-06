"""
simulation/api_clients/market_context.py
────────────────────────────────────────────────────────────────────────────
Aggregates external market context data for the simulation bot:
  1. DXY (US Dollar Index) — inverse correlation with Gold
  2. VIX (Fear Index) — high VIX = safe-haven Gold demand
  3. Gold News Sentiment — from NewsAPI (free tier)
  4. CFTC COT Report — institutional Gold futures positioning
  5. Economic Calendar — high-impact news blocking

All data is cached to minimize API calls on the 1-core VPS.
Uses only free APIs: yfinance, newsapi.org, CFTC public data.

Usage:
    ctx = MarketContext()
    ctx.start_background_updates()  # Non-blocking
    regime = ctx.get_regime()
    sentiment = ctx.get_gold_sentiment()  # -1.0 to +1.0
"""

import logging
import threading
import time
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger("MarketContext")

CACHE_DIR = Path("data/market_context")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ── DXY + VIX (via yfinance) ───────────────────────────────────────────────────

class MarketDataFetcher:
    """Fetches DXY and VIX from Yahoo Finance via yfinance."""

    def __init__(self):
        self._dxy: Optional[float] = None
        self._vix: Optional[float] = None
        self._last_update: float = 0

    def update(self) -> bool:
        try:
            import yfinance as yf
            dxy = yf.Ticker("DX-Y.NYB").fast_info
            vix = yf.Ticker("^VIX").fast_info
            self._dxy = float(dxy.get("lastPrice", 0) or 0)
            self._vix = float(vix.get("lastPrice", 0) or 0)
            self._last_update = time.time()
            logger.debug(f"[MarketData] DXY={self._dxy:.2f}, VIX={self._vix:.2f}")
            return True
        except Exception as e:
            logger.warning(f"[MarketData] yfinance error: {e}")
            return False

    @property
    def dxy(self) -> Optional[float]:
        return self._dxy

    @property
    def vix(self) -> Optional[float]:
        return self._vix

    def is_high_vix(self, threshold: float = 25.0) -> bool:
        """VIX > 25 = elevated fear = Gold bullish bias."""
        return bool(self._vix and self._vix > threshold)

    def dxy_trend(self) -> str:
        """Returns rough DXY regime (strong/weak/neutral)."""
        if self._dxy is None:
            return "NEUTRAL"
        if self._dxy > 104:
            return "STRONG"   # Bearish for Gold
        elif self._dxy < 100:
            return "WEAK"     # Bullish for Gold
        return "NEUTRAL"


# ── Gold News Sentiment (NewsAPI free) ─────────────────────────────────────────

class GoldNewsSentiment:
    """
    Fetches Gold-related news headlines from NewsAPI (free tier: 100 req/day).
    Uses simple keyword-based scoring — no external NLP library required
    (keeps memory low on 4GB VPS).
    """

    BULLISH_KEYWORDS = [
        "gold rises", "gold rally", "xau gains", "gold surge", "safe haven",
        "fed dovish", "rate cut", "inflation", "war", "crisis", "recession fear",
        "gold hits", "bullion demand", "central bank buying", "etf inflows",
    ]
    BEARISH_KEYWORDS = [
        "gold falls", "gold drops", "xau declines", "gold sink", "gold tumbles",
        "fed hawkish", "rate hike", "dollar strength", "risk-on", "gold selloff",
        "gold loses", "profit taking", "etf outflows",
    ]

    def __init__(self, api_key: str = "", refresh_minutes: int = 15):
        self.api_key = api_key
        self.refresh_sec = refresh_minutes * 60
        self._score: float = 0.0          # -1.0 to +1.0
        self._headlines: List[str] = []
        self._last_update: float = 0.0
        self._cache_file = CACHE_DIR / "gold_sentiment_cache.json"
        self._load_cache()

    def _load_cache(self):
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text())
                self._score = data.get("score", 0.0)
                self._last_update = data.get("ts", 0.0)
                self._headlines = data.get("headlines", [])
            except Exception:
                pass

    def _save_cache(self):
        try:
            self._cache_file.write_text(json.dumps({
                "score": self._score,
                "ts": self._last_update,
                "headlines": self._headlines[:20],
            }))
        except Exception:
            pass

    def update(self) -> bool:
        if not self.api_key:
            # Without API key: use neutral sentiment
            self._score = 0.0
            return True

        if time.time() - self._last_update < self.refresh_sec:
            return True  # Cache still fresh

        try:
            import urllib.request, urllib.parse
            query = urllib.parse.quote("gold OR XAUUSD OR XAU price")
            url = (
                f"https://newsapi.org/v2/everything?"
                f"q={query}&language=en&sortBy=publishedAt"
                f"&pageSize=30&apiKey={self.api_key}"
            )
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())

            articles = data.get("articles", [])
            self._headlines = [a.get("title", "") for a in articles]
            self._score = self._score_headlines(self._headlines)
            self._last_update = time.time()
            self._save_cache()
            logger.info(f"[GoldSentiment] Score={self._score:+.2f} ({len(self._headlines)} headlines)")
            return True

        except Exception as e:
            logger.warning(f"[GoldSentiment] NewsAPI error: {e}. Using cached score.")
            return False

    def _score_headlines(self, headlines: List[str]) -> float:
        bull, bear = 0, 0
        for h in headlines:
            h_lower = h.lower()
            bull += sum(1 for kw in self.BULLISH_KEYWORDS if kw in h_lower)
            bear += sum(1 for kw in self.BEARISH_KEYWORDS if kw in h_lower)
        total = bull + bear
        if total == 0:
            return 0.0
        return round((bull - bear) / total, 3)

    @property
    def score(self) -> float:
        """Returns sentiment score: -1.0 (very bearish) to +1.0 (very bullish)."""
        return self._score

    @property
    def label(self) -> str:
        if self._score > 0.3:
            return "BULLISH"
        elif self._score < -0.3:
            return "BEARISH"
        return "NEUTRAL"


# ── CFTC COT Report ─────────────────────────────────────────────────────────────

class COTAnalyzer:
    """
    Fetches CFTC Commitment of Traders data (weekly, free).
    Tracks Gold futures (COMEX) net positioning of large speculators.
    Positive = speculators are net LONG (bullish bias).
    Negative = speculators are net SHORT (bearish bias).
    """

    COT_URL = "https://www.cftc.gov/dea/futures/deacmesf.htm"
    CACHE_FILE = CACHE_DIR / "cot_cache.json"
    CACHE_HOURS = 168   # 1 week

    def __init__(self):
        self._net_position: Optional[int] = None
        self._last_update: float = 0.0
        self._load_cache()

    def _load_cache(self):
        if self.CACHE_FILE.exists():
            try:
                data = json.loads(self.CACHE_FILE.read_text())
                self._net_position = data.get("net")
                self._last_update  = data.get("ts", 0.0)
            except Exception:
                pass

    def update(self) -> bool:
        if (self._net_position is not None and
                time.time() - self._last_update < self.CACHE_HOURS * 3600):
            return True  # Cached for 1 week

        try:
            import urllib.request
            # CFTC provides downloadable CSV files
            csv_url = "https://www.cftc.gov/files/dea/history/fut_disagg_xls_2025.zip"
            # Simplified: use pre-known typical range for Gold
            # Full implementation would parse the zip file
            # For now: return neutral (0) as placeholder
            # TODO: Implement full CSV parsing in production
            self._net_position = 0
            self._last_update = time.time()
            logger.info("[COT] Using placeholder COT data (0). Enable full parsing for production.")
            self._save_cache()
            return True
        except Exception as e:
            logger.warning(f"[COT] Fetch error: {e}")
            return False

    def _save_cache(self):
        try:
            self.CACHE_FILE.write_text(json.dumps({
                "net": self._net_position,
                "ts": self._last_update,
            }))
        except Exception:
            pass

    @property
    def net_position(self) -> Optional[int]:
        return self._net_position

    @property
    def bias(self) -> str:
        if self._net_position is None:
            return "NEUTRAL"
        if self._net_position > 100000:
            return "BULL_EXTREME"   # Crowded long — caution!
        elif self._net_position > 50000:
            return "BULL"
        elif self._net_position < -50000:
            return "BEAR"
        return "NEUTRAL"


# ── Economic Calendar ─────────────────────────────────────────────────────────

class EconomicCalendar:
    """
    Tracks high-impact economic events that affect Gold.
    Uses forexfactory.com calendar RSS (free).
    Blocks SMC/ML entries during ±15 minutes of major events.

    High-impact events that most affect XAUUSD:
      - FOMC Decision / Press Conference
      - US CPI, PPI, PCE
      - NFP (Non-Farm Payrolls)
      - US GDP
      - Fed Chair Speech
    """

    HIGH_IMPACT_KEYWORDS = [
        "fomc", "interest rate", "cpi", "ppi", "nfp", "non-farm",
        "gdp", "pce", "federal reserve", "powell", "inflation",
        "treasury", "dollar index"
    ]

    def __init__(self, block_minutes_before: int = 10,
                 block_minutes_after: int = 15):
        self._events: List[dict] = []
        self._last_update: float = 0.0
        self._block_before = block_minutes_before * 60
        self._block_after  = block_minutes_after * 60
        self._cache_file = CACHE_DIR / "econ_calendar_cache.json"
        self._load_cache()

    def _load_cache(self):
        if self._cache_file.exists():
            try:
                data = json.loads(self._cache_file.read_text())
                self._events = data.get("events", [])
                self._last_update = data.get("ts", 0.0)
            except Exception:
                pass

    def update(self):
        """Fetch ForexFactory calendar. Updates every 6 hours."""
        if time.time() - self._last_update < 21600:
            return

        try:
            import urllib.request
            # ForexFactory RSS/JSON endpoint (unofficial but reliable)
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=10) as r:
                events = json.loads(r.read().decode())
            
            # Filter high-impact USD events
            high_impact = [
                e for e in events
                if e.get("country", "").upper() == "USD"
                and e.get("impact", "").upper() in ("HIGH", "3")
                and any(kw in e.get("title", "").lower()
                        for kw in self.HIGH_IMPACT_KEYWORDS)
            ]
            self._events = high_impact
            self._last_update = time.time()
            self._save_cache()
            logger.info(f"[EconCal] Fetched {len(high_impact)} high-impact USD events this week.")
        except Exception as e:
            logger.warning(f"[EconCal] Fetch failed: {e}")

    def _save_cache(self):
        try:
            self._cache_file.write_text(json.dumps({
                "events": self._events,
                "ts": self._last_update,
            }))
        except Exception:
            pass

    def is_safe_to_trade(self) -> bool:
        """Returns False during high-impact news windows."""
        now = time.time()
        for event in self._events:
            try:
                event_time_str = event.get("date", "") + " " + event.get("time", "")
                event_dt = datetime.strptime(event_time_str, "%Y-%m-%d %I:%M%p")
                event_ts = event_dt.replace(tzinfo=timezone.utc).timestamp()
                if (event_ts - self._block_before) <= now <= (event_ts + self._block_after):
                    logger.warning(
                        f"[EconCal] 🚨 High-impact event nearby: {event.get('title')} "
                        f"@ {event_time_str}. Blocking entries."
                    )
                    return False
            except Exception:
                continue
        return True


# ── Unified Market Context ─────────────────────────────────────────────────────

class MarketContext:
    """
    Single interface for all external market data.
    Runs background update threads to keep data fresh.
    """

    def __init__(self, newsapi_key: str = ""):
        self._mkt_data  = MarketDataFetcher()
        self._sentiment = GoldNewsSentiment(api_key=newsapi_key)
        self._cot       = COTAnalyzer()
        self._econ_cal  = EconomicCalendar()
        self._regime    = "UNKNOWN"
        self._stop_flag = threading.Event()

    def start_background_updates(self):
        """Start background threads for non-blocking data refresh."""
        t = threading.Thread(
            target=self._update_loop, daemon=True, name="MarketCtx-Updater"
        )
        t.start()
        logger.info("[MarketContext] Background data updater started.")

    def _update_loop(self):
        while not self._stop_flag.is_set():
            try:
                self._mkt_data.update()
                self._sentiment.update()
                self._cot.update()
                self._econ_cal.update()
            except Exception as e:
                logger.warning(f"[MarketContext] Update error: {e}")
            time.sleep(900)  # Update every 15 minutes

    def stop(self):
        self._stop_flag.set()

    # ── Convenience Properties ─────────────────────────────────────────────────

    def get_regime(self) -> str:
        """Returns externally-set HMM regime."""
        return self._regime

    def set_regime(self, regime: str):
        self._regime = regime

    def get_gold_sentiment(self) -> float:
        return self._sentiment.score

    def get_dxy(self) -> Optional[float]:
        return self._mkt_data.dxy

    def get_vix(self) -> Optional[float]:
        return self._mkt_data.vix

    def get_cot_net(self) -> Optional[int]:
        return self._cot.net_position

    def is_safe_to_trade(self) -> bool:
        """Master safety check (economic calendar)."""
        return self._econ_cal.is_safe_to_trade()

    def get_bias_summary(self) -> dict:
        """Returns a dict with all bias signals for logging."""
        return {
            "dxy":        self._mkt_data.dxy,
            "dxy_trend":  self._mkt_data.dxy_trend(),
            "vix":        self._mkt_data.vix,
            "high_vix":   self._mkt_data.is_high_vix(),
            "sentiment":  self._sentiment.score,
            "sent_label": self._sentiment.label,
            "cot_net":    self._cot.net_position,
            "cot_bias":   self._cot.bias,
            "regime":     self._regime,
        }
