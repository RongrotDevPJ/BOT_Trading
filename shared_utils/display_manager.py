import os
import time
import datetime
try:
    import psutil
except ImportError:
    psutil = None
import config
from shared_utils.db_manager import DBManager

def get_system_stats():
    # Return stats using global psutil
    try:
        cpu = psutil.cpu_percent()
        ram = int(psutil.virtual_memory().used / (1024 * 1024))
        return cpu, ram
    except Exception:
        return "N/A", "N/A"

# Try to enable ANSI support on Windows using ctypes
_ansi_supported = False
if os.name == 'nt':
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(-11) # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        mode.value |= 4 
        kernel32.SetConsoleMode(handle, mode)
        _ansi_supported = True
    except Exception:
        # Fallback to os.system('') which sometimes works in newer Win10/11
        try:
            os.system('')
            _ansi_supported = True
        except:
            _ansi_supported = False

# Module-level variable to track last update time
_last_render_time = 0
_force_use_cls = False # User can set this to True for legacy behavior
_db_manager = None # Cached DBManager instance

def get_db():
    """Lazily initializes and returns the DBManager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DBManager()
    return _db_manager

def render_dashboard(
    symbol, 
    equity, 
    balance, 
    daily_profit_pct, 
    drawdown_pct, 
    strategy_name, 
    stat_line, 
    current_spread, 
    max_spread, 
    news_status, 
    log_time, 
    log_message, 
    mt5_status,
    target_pct=15.0,
    target_amount=None,
    profit_amount=None,
    acc_profit_pct=None,
    acc_profit_amount=None,
    acc_drawdown_pct=None
):
    """
    Renders a fixed-width dashboard to the terminal with anti-flicker and throttling.
    """
    global _last_render_time
    current_time = time.time()
    
    # Throttle rendering to every 5 seconds
    if current_time - _last_render_time < 5:
        return
    
    _last_render_time = current_time

    try:
        # Use cached DB Manager for summary data
        db = get_db()
        daily_profit_usd = db.get_today_summary(symbol)
        
        # Calculate daily_profit_pct based on actual closed trades
        # If no trades yet, fallback to 0.0 or the provided value
        if daily_profit_usd != 0 and balance > 0:
            daily_profit_pct = (daily_profit_usd / (balance - daily_profit_usd)) * 100
        else:
            daily_profit_pct = 0.0
    except Exception as e:
        # Handle DB errors gracefully, perhaps log them
        print(f"Error fetching daily summary: {e}")
        # Keep the original daily_profit_pct if DB fetch fails

    # Priority 1: Mandatory clear for Windows (reliable for VPS/Legacy terminals)
    if os.name == 'nt':
        os.system('cls')
    # Priority 2: ANSI positioning for other systems
    elif _ansi_supported:
        print('\x1b[H', end='')
    # Priority 3: Fallback
    else:
        os.system('clear')

    # Date and Time
    now = datetime.datetime.now()
    dt_str = now.strftime("%d/%m/%Y | %H:%M:%S")

    # System Stats
    try:
        cpu = psutil.cpu_percent()
        ram = int(psutil.virtual_memory().used / (1024 * 1024))
    except (ImportError, Exception):
        cpu = "N/A"
        ram = "N/A"

    # Truncate and filter log message
    if "HEARTBEAT" in log_message:
        log_message = "💓 Heartbeat - Bot is active"
    elif "Market Snapshot" in log_message:
        # Shorten market snapshot for small VPS windows
        log_message = log_message.replace("[Market Snapshot]", "📊 Snapshot:")
    
    # Strictly limit log length to prevent wrapping in small windows
    if len(log_message) > 45:
        log_message = log_message[:42] + "..."

    # Build Profit and Target strings (Compact)
    profit_str = f"{daily_profit_pct:+.2f}%"
    if profit_amount is not None:
        profit_str += f"({profit_amount:+.2f})"
        
    target_str = f"{target_pct}%"
    if target_amount is not None:
        target_str += f"({target_amount:.1f})"

    # Build Account Total Profit string (Compact)
    acc_profit_str = "N/A"
    if acc_profit_pct is not None:
        acc_profit_str = f"{acc_profit_pct:+.2f}%"
        if acc_profit_amount is not None:
            acc_profit_str += f"({acc_profit_amount:+.2f})"

    # Column alignment helper (Strict)
    def fmt_line(label, value):
        return f"{label:<10}: {value}"

    header = f"================ [ {symbol} ] {dt_str} ================"
    print(header)
    
    # Compact EQUITY and BALANCE lines to prevent wrap
    equity_info = f"[ Tgt:{target_str} | AccPL:{acc_profit_str} ]"
    print(fmt_line("EQUITY", f"{equity:.2f} {equity_info}"))
    
    dd_str = f"Bot:{drawdown_pct:.1f}%"
    if acc_drawdown_pct is not None:
        dd_str += f"|Acc:{acc_drawdown_pct:.1f}%"

    balance_info = f"[ BotPL:{profit_str} | DD:{dd_str} ]"
    print(fmt_line("BALANCE", f"{balance:.2f} {balance_info}"))
    print("-" * len(header))
    print(fmt_line("STRATEGY", strategy_name))
    print(fmt_line("STATISTICS", stat_line))
    print(fmt_line("GUARDS", f"Spread: {current_spread} (Max: {max_spread}) | News: {news_status} | Bot: ACTIVE"))
    print("-" * len(header))
    print(fmt_line("LATEST LOG", f"[{log_time}] - {log_message}"))
    print(fmt_line("SYSTEM", f"CPU: {cpu}% | RAM: {ram}MB | MT5: {mt5_status}"))
    print("=" * len(header))

if __name__ == "__main__":
    # Test Render
    render_dashboard(
        symbol="XAUUSD",
        equity=10500.50,
        balance=10000.00,
        daily_profit_pct=5.00,
        drawdown_pct=0.00,
        strategy_name="Smart Grid",
        stat_line="Layer: 3 | Dist: 50pts | Multi: 1.5x",
        current_spread=15,
        max_spread=30,
        news_status="NONE",
        log_time="17:45:00",
        log_message="Initial entry Buy executed at 2050.25",
        mt5_status="CONNECTED"
    )
