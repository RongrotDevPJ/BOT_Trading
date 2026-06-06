import sqlite3
import pandas as pd
import numpy as np

# 1. Load Data
conn = sqlite3.connect('data/db/trading_data.db')
df = pd.read_sql("SELECT profit, timestamp, ticket, side, lots FROM trades WHERE status='CLOSED' ORDER BY timestamp ASC", conn)

total_trades = len(df)
if total_trades == 0:
    print("No closed trades found.")
    exit()

wins = df[df['profit'] > 0]['profit']
losses = df[df['profit'] < 0]['profit']

win_rate = len(wins) / total_trades
gross_profit = wins.sum()
gross_loss = abs(losses.sum())
profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

avg_win = wins.mean() if len(wins) > 0 else 0
avg_loss = losses.mean() if len(losses) > 0 else 0
largest_win = wins.max() if len(wins) > 0 else 0
largest_loss = losses.min() if len(losses) > 0 else 0

# Consecutive losses
df['is_loss'] = df['profit'] < 0
streak = 0
max_streak = 0
for is_loss in df['is_loss']:
    if is_loss:
        streak += 1
        max_streak = max(max_streak, streak)
    else:
        streak = 0

# Max Drawdown (Historical)
df['cum_profit'] = df['profit'].cumsum()
df['peak'] = df['cum_profit'].cummax()
df['drawdown'] = df['peak'] - df['cum_profit']
max_drawdown = df['drawdown'].max()

print("--- HISTORICAL METRICS ---")
print(f"Total Trades: {total_trades}")
print(f"Win Rate: {win_rate:.2%}")
print(f"Profit Factor: {profit_factor:.2f}")
print(f"Average Win: {avg_win:.2f}")
print(f"Average Loss: {avg_loss:.2f}")
print(f"Largest Win: {largest_win:.2f}")
print(f"Largest Loss: {largest_loss:.2f}")
print(f"Consecutive Loss Streak: {max_streak}")
print(f"Max Drawdown: {max_drawdown:.2f}")

# Monte Carlo (10,000 runs)
# Simulate 1,000 trades per run to estimate long-term risk of ruin
# Initial Equity = $5000 (USC)
INITIAL_EQUITY = 5000.0
RUNS = 10000
TRADES_PER_RUN = 1000

trades_array = df['profit'].values
ruin_count = 0
mc_max_dds = []

np.random.seed(42)

for i in range(RUNS):
    # Randomly sample trades with replacement
    sampled_trades = np.random.choice(trades_array, size=TRADES_PER_RUN, replace=True)
    
    # Calculate cumulative equity
    equity_curve = INITIAL_EQUITY + np.cumsum(sampled_trades)
    
    # Check for ruin (equity <= 0)
    if np.any(equity_curve <= 0):
        ruin_count += 1
        
    # Calculate max drawdown for this run
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = peak - equity_curve
    mc_max_dds.append(np.max(drawdowns))

risk_of_ruin = ruin_count / RUNS
avg_mc_dd = np.mean(mc_max_dds)
worst_mc_dd = np.max(mc_max_dds)

print("\n--- MONTE CARLO STRESS TEST (10,000 runs, 1,000 trades/run) ---")
print(f"Risk of Ruin: {risk_of_ruin:.2%}")
print(f"Average MC Max Drawdown: {avg_mc_dd:.2f}")
print(f"Worst MC Max Drawdown: {worst_mc_dd:.2f}")

