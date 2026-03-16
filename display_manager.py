import os
import datetime
import psutil

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
    target_pct=15.0
):
    """
    Renders a fixed-width dashboard to the terminal.
    """
    # Clear screen
    os.system('cls' if os.name == 'nt' else 'clear')

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

    # Truncate log message
    if len(log_message) > 50:
        log_message = log_message[:47] + "..."

    # Column alignment helper (Colon at Column 12)
    def fmt_line(label, value):
        return f"{label:<11}: {value}"

    header = f"================ [ {symbol} ] {dt_str} ================"
    
    print(header)
    print(fmt_line("EQUITY", f"{equity:.2f}      [ Target: {target_pct}% | Profit: {daily_profit_pct:+.2f}% ]"))
    print(fmt_line("BALANCE", f"{balance:.2f}      [ Drawdown: {drawdown_pct:.2f}% ]"))
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
