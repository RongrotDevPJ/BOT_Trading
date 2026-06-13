import requests
import logging
import threading
import queue
import time
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("Notifier")


class TelegramNotifier:
    """
    Thread-safe Telegram notifier with rich trade event formatting.
    Sends messages in background thread to avoid blocking trading loop.
    Rate-limited: max 1 message per 3 seconds (Telegram API limit).
    """

    def __init__(self):
        self.token = ""
        self.chat_id = ""
        self._queue = queue.Queue(maxsize=50)
        self.last_update_id = 0
        self._load_config()
        # Background sender thread
        self._thread = threading.Thread(target=self._sender_loop, daemon=True)
        self._thread.start()
        # Background polling thread for /status command
        if self.token and self.chat_id:
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()

    def _load_config(self):
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if "=" in line and not line.startswith("#"):
                            key, value = line.split("=", 1)
                            key   = key.strip()
                            value = value.strip().strip("'\"")
                            if key == "TELEGRAM_BOT_TOKEN":
                                self.token = value
                            elif key == "TELEGRAM_CHAT_ID":
                                self.chat_id = value
            except Exception as e:
                logger.error(f"Error loading .env for Telegram: {e}")

    def _sender_loop(self):
        """Background thread: drain queue and send with rate limiting."""
        while True:
            try:
                msg = self._queue.get(timeout=60)
                self._do_send(msg)
                time.sleep(3)  # Telegram rate limit: ~20 msg/min
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[Telegram] Sender loop error: {e}")

    def _poll_loop(self):
        """Background thread to poll for /status commands."""
        while True:
            try:
                if not self.token:
                    time.sleep(60)
                    continue
                url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                payload = {"offset": self.last_update_id + 1, "timeout": 30}
                resp = requests.post(url, json=payload, timeout=35)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            self.last_update_id = update["update_id"]
                            msg = update.get("message", {})
                            text = msg.get("text", "")
                            chat_id = str(msg.get("chat", {}).get("id", ""))
                            # Verify chat_id for security
                            if chat_id == self.chat_id and text.startswith("/status"):
                                self._handle_status_command()
                            elif chat_id == self.chat_id and text.startswith("/report"):
                                self._handle_report_command()
            except Exception as e:
                logger.debug(f"[Telegram Poll] error: {e}")
            time.sleep(5)  # Poll interval

    def _handle_status_command(self):
        """Build and send current bot status manually when requested."""
        try:
            import sqlite3
            from configs import XAUUSD_LIVE as config
            
            # Fetch latest snapshot from DB
            db_path = Path("data/db/trading_data.db")
            if not db_path.exists():
                self.send_telegram_message("Bot is running, but no DB found yet.")
                return
                
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT balance, equity, floating_pnl, open_trades, drawdown_pct, regime FROM account_snapshots ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            
            if row:
                bal, eq, float_pnl, open_t, dd, regime = row
                msg = (
                    f"🤖 <b>BOT STATUS (On-Demand)</b> — {getattr(config, 'SYMBOL', 'XAUUSD')}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 Balance  : {bal:.2f} USC\n"
                    f"📊 Equity   : {eq:.2f} USC\n"
                    f"💵 Floating : {float_pnl:+.2f} USC\n"
                    f"📉 Drawdown : {dd:.2f}%\n"
                    f"📦 Open Pos : {open_t}\n"
                    f"🧭 Regime   : {regime}\n"
                    f"⏰ Time     : {datetime.now().strftime('%H:%M:%S')}\n"
                )
                self.send_telegram_message(msg)
            else:
                self.send_telegram_message("Bot is running. Waiting for first snapshot.")
        except Exception as e:
            logger.error(f"[Telegram] Handle status error: {e}")
            self.send_telegram_message("Error fetching status.")

    def _handle_report_command(self):
        """Build and send a 7-day performance report when /report is requested."""
        try:
            import sqlite3
            from configs import XAUUSD_LIVE as config

            db_path = Path("data/db/trading_data.db")
            if not db_path.exists():
                self.send_telegram_message("No DB found yet.")
                return

            conn = sqlite3.connect(str(db_path), timeout=10)
            cur = conn.cursor()

            # 7-day closed trades stats
            cur.execute("""
                SELECT COUNT(*) as n,
                       SUM(profit) as net,
                       SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                       MAX(profit) as best,
                       MIN(profit) as worst
                FROM trades
                WHERE status='CLOSED'
                  AND timestamp >= datetime('now', '-7 days')
            """)
            trade_row = cur.fetchone()

            # Balance start/end from snapshots (7 days)
            cur.execute("""
                SELECT balance, timestamp FROM account_snapshots
                ORDER BY timestamp ASC LIMIT 1
            """)
            snap_first = cur.fetchone()
            cur.execute("""
                SELECT balance, equity, open_trades, regime, timestamp
                FROM account_snapshots
                ORDER BY timestamp DESC LIMIT 1
            """)
            snap_last = cur.fetchone()

            # Max drawdown in 7 days
            cur.execute("""
                SELECT MAX(drawdown_pct) FROM account_snapshots
                WHERE timestamp >= datetime('now', '-7 days')
            """)
            max_dd_row = cur.fetchone()
            conn.close()

            # Build report
            n = trade_row[0] or 0
            net = trade_row[1] or 0.0
            wins = trade_row[2] or 0
            best = trade_row[3] or 0.0
            worst = trade_row[4] or 0.0
            wr = (wins / n * 100) if n > 0 else 0.0

            start_bal = snap_first[0] if snap_first else 0.0
            end_bal   = snap_last[0] if snap_last else 0.0
            cur_eq    = snap_last[1] if snap_last else 0.0
            open_t    = snap_last[2] if snap_last else 0
            regime    = snap_last[3] if snap_last else "N/A"
            bal_change = end_bal - start_bal
            max_dd = max_dd_row[0] if max_dd_row and max_dd_row[0] else 0.0

            msg = (
                f"📊 <b>WEEKLY REPORT</b> — {getattr(config, 'SYMBOL', 'XAUUSD')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 Period   : Last 7 Days\n"
                f"💰 Balance  : {start_bal:.2f} → {end_bal:.2f} USC "
                f"({bal_change:+.2f})\n"
                f"📊 Equity   : {cur_eq:.2f} USC\n"
                f"───────────────────────\n"
                f"🎯 Trades   : {n} closed\n"
                f"✅ Win Rate  : {wr:.1f}% ({wins}W/{n-wins}L)\n"
                f"📈 Net PnL  : {net:+.2f} USC\n"
                f"🏆 Best     : +{best:.2f} USC\n"
                f"💀 Worst    : {worst:.2f} USC\n"
                f"📉 Max DD   : {max_dd:.2f}%\n"
                f"───────────────────────\n"
                f"📦 Open Pos : {open_t}\n"
                f"🧭 Regime   : {regime}\n"
                f"⏰ Time     : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            )
            self.send_telegram_message(msg)
        except Exception as e:
            logger.error(f"[Telegram] Handle report error: {e}")
            self.send_telegram_message("Error generating report.")

    def _do_send(self, message: str):
        """Actual HTTP send to Telegram API."""
        if not self.token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
        }
        try:
            response = requests.post(url, json=payload, timeout=8)
            if response.status_code != 200:
                logger.error(f"Telegram API Error {response.status_code}: {response.text[:200]}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")

    def send_telegram_message(self, message: str):
        """Queue a raw message for sending."""
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            logger.warning("[Telegram] Queue full — message dropped.")

    # ── Rich Event Formatters ─────────────────────────────────────────────────

    def notify_trade_open(self, symbol: str, side: str, lots: float,
                          price: float, sl: float, tp: float,
                          rsi: float = None, grid_level: int = 1,
                          ticket: int = None):
        """Notify when a new trade opens."""
        side_emoji = "🟢" if side == "BUY" else "🔴"
        now = datetime.now().strftime("%H:%M:%S")
        msg = (
            f"{side_emoji} <b>TRADE OPEN</b> — {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Time     : {now}\n"
            f"📊 Side     : <b>{side}</b> (Grid #{grid_level})\n"
            f"💰 Lots     : {lots:.2f}\n"
            f"🎯 Price    : {price:.5f}\n"
            f"🛑 SL       : {sl:.5f}\n"
            f"✅ TP       : {tp:.5f}\n"
        )
        if rsi is not None:
            msg += f"📈 RSI      : {rsi:.2f}\n"
        if ticket:
            msg += f"🎫 Ticket   : {ticket}\n"
        self.send_telegram_message(msg)

    def notify_trade_close(self, symbol: str, side: str, lots: float,
                           open_price: float, close_price: float,
                           profit: float, hold_time_sec: int = 0,
                           close_reason: str = ""):
        """Notify when a trade closes — with profit/loss formatting."""
        result_emoji = "✅ PROFIT" if profit >= 0 else "❌ LOSS"
        side_emoji   = "🟢" if side == "BUY" else "🔴"
        hold_str = f"{hold_time_sec // 3600}h {(hold_time_sec % 3600) // 60}m" if hold_time_sec else "N/A"
        now = datetime.now().strftime("%H:%M:%S")
        msg = (
            f"{result_emoji} — {symbol} {side_emoji}{side}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Close    : {now}\n"
            f"📊 Lots     : {lots:.2f}\n"
            f"🎯 Open     : {open_price:.5f}\n"
            f"🏁 Close    : {close_price:.5f}\n"
            f"💵 PnL      : <b>{profit:+.2f} USC</b>\n"
            f"⏱️ Hold     : {hold_str}\n"
            f"📝 Reason   : {close_reason}\n"
        )
        self.send_telegram_message(msg)

    def notify_drawdown_alert(self, symbol: str, dd_pct: float,
                              equity: float, balance: float,
                              threshold_pct: float = 5.0):
        """Alert when drawdown exceeds threshold."""
        msg = (
            f"⚠️ <b>DRAWDOWN ALERT</b> — {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📉 Drawdown : <b>{dd_pct:.2f}%</b> (threshold: {threshold_pct}%)\n"
            f"💰 Balance  : {balance:.2f} USC\n"
            f"📊 Equity   : {equity:.2f} USC\n"
            f"⏰ Time     : {datetime.now().strftime('%H:%M:%S')}\n"
        )
        self.send_telegram_message(msg)

    def notify_daily_summary(self, symbol: str, daily_pnl: float,
                             n_trades: int, win_trades: int,
                             balance: float, equity: float):
        """Send daily performance summary."""
        wr = (win_trades / n_trades * 100) if n_trades > 0 else 0
        result_emoji = "📈" if daily_pnl >= 0 else "📉"
        msg = (
            f"{result_emoji} <b>DAILY SUMMARY</b> — {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Date     : {datetime.now().strftime('%Y-%m-%d')}\n"
            f"💵 Daily PnL: <b>{daily_pnl:+.2f} USC</b>\n"
            f"🎯 Trades   : {n_trades} (W:{win_trades} / L:{n_trades - win_trades})\n"
            f"📊 Win Rate : {wr:.1f}%\n"
            f"💰 Balance  : {balance:.2f} USC\n"
            f"📈 Equity   : {equity:.2f} USC\n"
        )
        self.send_telegram_message(msg)

    def notify_bot_status(self, symbol: str, status: str, reason: str = ""):
        """Notify bot start/stop/error events."""
        emoji_map = {
            "START":   "🚀",
            "STOP":    "🛑",
            "ERROR":   "🔥",
            "RESTART": "🔄",
            "HEDGE":   "🛡️",
        }
        emoji = emoji_map.get(status.upper(), "ℹ️")
        msg = (
            f"{emoji} <b>BOT {status}</b> — {symbol}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ Time   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        if reason:
            msg += f"📝 Reason : {reason}\n"
        self.send_telegram_message(msg)


# Singleton instance
notifier = TelegramNotifier()


def send_telegram_message(message: str):
    """Backward-compatible wrapper."""
    notifier.send_telegram_message(message)


def notify_trade_open(symbol, side, lots, price, sl, tp,
                      rsi=None, grid_level=1, ticket=None):
    notifier.notify_trade_open(symbol, side, lots, price, sl, tp,
                               rsi, grid_level, ticket)


def notify_trade_close(symbol, side, lots, open_price, close_price,
                       profit, hold_time_sec=0, close_reason=""):
    notifier.notify_trade_close(symbol, side, lots, open_price, close_price,
                                profit, hold_time_sec, close_reason)


def notify_drawdown_alert(symbol, dd_pct, equity, balance, threshold_pct=5.0):
    notifier.notify_drawdown_alert(symbol, dd_pct, equity, balance, threshold_pct)


def notify_daily_summary(symbol, daily_pnl, n_trades, win_trades, balance, equity):
    notifier.notify_daily_summary(symbol, daily_pnl, n_trades, win_trades, balance, equity)


def notify_bot_status(symbol, status, reason=""):
    notifier.notify_bot_status(symbol, status, reason)
