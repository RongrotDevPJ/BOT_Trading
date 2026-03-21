import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import logging
import pytz

logger = logging.getLogger("NewsFilter")

class NewsFilter:
    def __init__(self, impact_level="High", safe_buffer_min=30):
        self.impact_level = impact_level
        self.safe_buffer_min = safe_buffer_min
        self.news_events = []
        self.last_update = datetime.min
        # ForexFactory RSS URL for the week
        self.url = "https://www.forexfactory.com/ff_calendar_thisweek.xml"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    def update_news(self):
        """Fetches and parses the latest news calendar."""
        # Update once per hour to avoid spamming the RSS
        if datetime.now() - self.last_update < timedelta(hours=1):
            return

        try:
            response = requests.get(self.url, headers=self.headers, timeout=10)
            if response.status_code != 200:
                logger.error(f"Failed to fetch news: Status {response.status_code}")
                return

            root = ET.fromstring(response.content)
            events = []
            
            # The XML structure for FF is <event><title>...<country>...<date>...<time>...<impact>...</event>
            for event in root.findall('event'):
                impact = event.find('impact').text
                country = event.find('country').text
                
                # Check if High Impact and Relevant Currency
                if impact == self.impact_level and country in ["USD", "EUR", "GBP", "AUD", "NZD", "JPY"]:
                    date_str = event.find('date').text # "MM-DD-YYYY"
                    time_str = event.find('time').text # "12:00pm" or "All Day"
                    
                    if time_str == "All Day":
                        continue # Skip holiday/all-day events for now

                    try:
                        # Combine Date and Time
                        full_dt_str = f"{date_str} {time_str}"
                        # ForexFactory RSS is usually in EST/EDT
                        est = pytz.timezone('US/Eastern')
                        dt_naive = datetime.strptime(full_dt_str, "%m-%d-%Y %I:%M%p")
                        dt_aware = est.localize(dt_naive)
                        # Convert to local time (or UTC) for comparison
                        events.append({
                            "title": event.find('title').text,
                            "country": country,
                            "time": dt_aware.astimezone(pytz.utc)
                        })
                    except Exception as e:
                        logger.error(f"Error parsing date/time for news event: {e}")

            self.news_events = events
            self.last_update = datetime.now()
            logger.info(f"News calendar updated. Found {len(self.news_events)} {self.impact_level} impact events.")

        except Exception as e:
            logger.error(f"Failed to update news calendar: {e}")

    def is_safe_to_trade(self, symbol="XAUUSD"):
        """
        Determines if it is safe to trade based on upcoming news.
        Returns False if within the safety buffer of a high-impact event.
        """
        self.update_news()
        
        # Determine relevant currencies for this symbol
        # Simple mapping: XAUUSD -> USD, AUDNZD -> AUD, NZD, etc.
        relevant_currencies = []
        if "USD" in symbol: relevant_currencies.append("USD")
        if "EUR" in symbol: relevant_currencies.append("EUR")
        if "GBP" in symbol: relevant_currencies.append("GBP")
        if "AUD" in symbol: relevant_currencies.append("AUD")
        if "NZD" in symbol: relevant_currencies.append("NZD")
        if "JPY" in symbol: relevant_currencies.append("JPY")
        if "XAU" in symbol: relevant_currencies.append("USD") # Gold usually moves with USD news

        now_utc = datetime.now(pytz.utc)
        buffer = timedelta(minutes=self.safe_buffer_min)

        for event in self.news_events:
            if event['country'] in relevant_currencies:
                event_time = event['time']
                
                # Check if we are in the "Forbidden zone" (30 mins before to 30 mins after)
                if (event_time - buffer) <= now_utc <= (event_time + buffer):
                    logger.warning(f"⚠️ NEWS FILTER ACTIVE: High Impact news {event['title']} ({event['country']}) at {event_time}. PAUSING.")
                    return False

        return True

# Singleton instance
news_filter = NewsFilter()

def is_safe_to_trade(symbol):
    return news_filter.is_safe_to_trade(symbol)
