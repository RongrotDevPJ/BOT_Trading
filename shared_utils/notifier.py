import requests
import logging
from pathlib import Path
import os

logger = logging.getLogger("Notifier")

class TelegramNotifier:
    def __init__(self):
        self.token = ""
        self.chat_id = ""
        self._load_config()

    def _load_config(self):
        # Load from .env in project root
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip("'\"")
                            if key == "TELEGRAM_BOT_TOKEN":
                                self.token = value
                            elif key == "TELEGRAM_CHAT_ID":
                                self.chat_id = value
            except Exception as e:
                logger.error(f"Error loading .env for Telegram: {e}")

    def send_telegram_alert(self, message):
        """Sends a message to the configured Telegram chat."""
        if not self.token or not self.chat_id:
            # Silently skip if not configured, to avoid spamming logs
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            # Using a short timeout to prevent blocking the trading loop
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"Telegram API Error: {response.text}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

# Singleton instance
notifier = TelegramNotifier()

def send_telegram_alert(message):
    notifier.send_telegram_alert(message)
