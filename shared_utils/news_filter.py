import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
import pytz
import time

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, impact_level=3, safe_buffer_min=30):
        self.impact_level = impact_level # 3 = High Impact in IG API
        self.safe_buffer_min = safe_buffer_min
        self.news_events = []
        self.last_update = datetime.min
        self.last_warning_time = 0
        self._last_fetch_success = False  # P2: Track API health for fallback logic
        # IG.com API via DailyFX
        self.base_url = "https://api.ig.com/explore/events"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://www.ig.com",
            "Referer": "https://www.ig.com/",
            "Authorization": "Basic Y2FsZW5kYXI6U3VQZVJsT25HcEEkJCR3MDByZDU2NzE="
        }

    def update_news(self):
        """Fetches and parses the latest news calendar from IG.com."""
        # Update once per hour to avoid spamming the API
        if datetime.now() - self.last_update < timedelta(hours=1):
            return

        try:
            # Generate date range for the next 7 days
            now = datetime.now(pytz.utc)
            from_date = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            to_date = (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            
            params = {
                "from": from_date,
                "to": to_date,
                "lang": "en"
            }

            response = requests.get(self.base_url, headers=self.headers, params=params, timeout=15)
            if response.status_code != 200:
                logger.error(f"Failed to fetch news from IG: Status {response.status_code}")
                # P2: Don't update — keep stale cache. Caller will use fallback logic.
                return

            data = response.json()
            events = []
            
            # Country to Currency mapping fallback
            country_map = {
                "United States": "USD",
                "Euro Area": "EUR",
                "Germany": "EUR",
                "France": "EUR",
                "Italy": "EUR",
                "United Kingdom": "GBP",
                "Canada": "CAD",
                "Australia": "AUD",
                "New Zealand": "NZD",
                "Japan": "JPY",
                "Switzerland": "CHF",
                "China": "CNY"
            }

            for item in data:
                importance = item.get('importance', 0)
                
                # Filter by High Impact (3)
                if importance == self.impact_level:
                    event_date_str = item.get('date') 
                    if not event_date_str: continue
                    
                    try:
                        dt_utc = datetime.fromisoformat(event_date_str.replace('Z', '+00:00'))
                        
                        # Get affected currencies
                        currencies = []
                        if item.get('currency'):
                            currencies.append(item['currency'])
                        
                        metadata = item.get('metadata', {})
                        if metadata and metadata.get('impactedCurrency'):
                            currencies.extend(metadata['impactedCurrency'])
                        
                        # Fallback to country mapping
                        country = item.get('country')
                        if not currencies and country in country_map:
                            currencies.append(country_map[country])
                        
                        # Remove duplicates and empty strings
                        currencies = list(set([c.upper() for c in currencies if c]))
                        
                        events.append({
                            "title": item.get('event', 'Unknown Event'),
                            "currencies": currencies,
                            "time": dt_utc
                        })
                    except Exception as e:
                        logger.error(f"Error parsing date for news event {item.get('event')}: {e}")

            self.news_events = events
            self.last_update = datetime.now()
            self._last_fetch_success = True  # P2: Mark API as healthy
            logger.info(f"News calendar updated via IG. Found {len(self.news_events)} high impact events.")

        except Exception as e:
            logger.error(f"Failed to update news calendar: {e}")
            # P2: _last_fetch_success remains unchanged (stays False if first call failed)

    def is_safe_to_trade(self, symbol="XAUUSD"):
        """
        Determines if it is safe to trade based on upcoming news.
        Returns False if within the safety buffer of a high-impact event.
        P2 Safety: If API has never succeeded AND cache is empty, returns False
        (block trading) to avoid entering during unknown high-impact events.
        """
        self.update_news()

        # P2: Fallback — if API failed on first-ever call and cache is empty, block trading
        if not self._last_fetch_success and not self.news_events:
            logger.warning("[NewsFilter] API unavailable and no cached events. Blocking trading as precaution.")
            return False
        
        # Determine relevant currencies for this symbol
        relevant_currencies = []
        if "USD" in symbol: relevant_currencies.append("USD")
        if "EUR" in symbol: relevant_currencies.append("EUR")
        if "GBP" in symbol: relevant_currencies.append("GBP")
        if "AUD" in symbol: relevant_currencies.append("AUD")
        if "NZD" in symbol: relevant_currencies.append("NZD")
        if "JPY" in symbol: relevant_currencies.append("JPY")
        if "XAU" in symbol: relevant_currencies.append("USD") 

        now_utc = datetime.now(pytz.utc)
        buffer = timedelta(minutes=self.safe_buffer_min)

        for event in self.news_events:
            # Check if any of the event's currencies match our symbol's currencies
            if any(currency in relevant_currencies for currency in event['currencies']):
                event_time = event['time'] # This is UTC
                
                # Check if we are in the "Forbidden zone"
                if (event_time - buffer) <= now_utc <= (event_time + buffer):
                    current_time = time.time()
                    if current_time - self.last_warning_time > 60:
                        logger.warning(f"⚠️ NEWS FILTER ACTIVE: High Impact news '{event['title']}' ({', '.join(event['currencies'])}) at {event_time.strftime('%H:%M')} UTC. PAUSING.")
                        self.last_warning_time = current_time
                    return False

        return True

# Singleton instance
news_filter = NewsFilter()

def is_safe_to_trade(symbol):
    return news_filter.is_safe_to_trade(symbol)
