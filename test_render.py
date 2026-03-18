import sys
import os
import time

# Add current dir to path
sys.path.append(os.getcwd())
from shared_utils.display_manager import render_dashboard

print("Testing Dashboard Throttling and ANSI Escape codes...")
for i in range(10):
    print(f"Loop {i}")
    render_dashboard(
        symbol="XAUUSD",
        equity=2000.0 + i,
        balance=2100.0,
        daily_profit_pct=0.5,
        drawdown_pct=4.7,
        strategy_name="Smart Grid",
        stat_line=f"Iteration {i}",
        current_spread=15,
        max_spread=30,
        news_status="STABLE",
        log_time="12:00:00",
        log_message=f"Test message {i}",
        mt5_status="CONNECTED",
        target_pct=15.0,
        target_amount=150.0,
        profit_amount=10.0 + i
    )
    time.sleep(0.5) # Should only render every 4th loop (approx)

print("\nTest complete.")
