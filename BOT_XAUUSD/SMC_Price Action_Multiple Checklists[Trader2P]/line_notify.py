import requests
import logging
import config

class LineNotify:
    def __init__(self):
        self.token = getattr(config, 'LINE_NOTIFY_TOKEN', "")
        self.url = "https://notify-api.line.me/api/notify"
        self.logger = logging.getLogger(__name__)

    def send_message(self, message):
        """Sends a text message to Line Notify."""
        if not self.token:
            self.logger.warning("Line Notify token is missing. Skipping notification.")
            return False

        headers = {"Authorization": f"Bearer {self.token}"}
        data = {"message": message}
        
        try:
            response = requests.post(self.url, headers=headers, data=data)
            if response.status_code == 200:
                self.logger.info("Line Notify sent successfully.")
                return True
            else:
                self.logger.error(f"Line Notify failed! Status: {response.status_code}, Response: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"Error sending Line Notify: {e}")
            return False
