import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/db/trading_data.db')
query = "SELECT * FROM trades WHERE status='CLOSED' ORDER BY timestamp ASC"
df = pd.read_sql(query, conn)
df['timestamp'] = pd.to_datetime(df['timestamp'])

print("==== AUDIT 1: BUY vs SELL ====")
buy_df = df[df['side'] == 'BUY']
sell_df = df[df['side'] == 'SELL']

for name, subset in [("BUY", buy_df), ("SELL", sell_df)]:
    wins = subset[subset['profit'] > 0]['profit']
    losses = subset[subset['profit'] < 0]['profit']
    total = len(subset)
    if total > 0:
        wr = len(wins) / total
        pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 else float('inf')
        print(f"[{name}] Trades: {total} | Win Rate: {wr:.2%} | Profit Factor: {pf:.2f} | Net: {subset['profit'].sum():.2f}")

print("\n==== AUDIT 2: BY HOUR ====")
df['hour'] = df['timestamp'].dt.hour
hourly = df.groupby('hour').apply(
    lambda x: pd.Series({
        'Trades': len(x),
        'Win_Rate': len(x[x['profit']>0])/len(x) if len(x)>0 else 0,
        'Profit_Factor': x[x['profit']>0]['profit'].sum() / abs(x[x['profit']<0]['profit'].sum()) if len(x[x['profit']<0])>0 else float('inf'),
        'Net_Profit': x['profit'].sum()
    })
)
print(hourly.to_string())

print("\n==== AUDIT 3: BY DAY OF WEEK ====")
df['dow'] = df['timestamp'].dt.day_name()
daily = df.groupby('dow').apply(
    lambda x: pd.Series({
        'Trades': len(x),
        'Win_Rate': len(x[x['profit']>0])/len(x) if len(x)>0 else 0,
        'Profit_Factor': x[x['profit']>0]['profit'].sum() / abs(x[x['profit']<0]['profit'].sum()) if len(x[x['profit']<0])>0 else float('inf'),
        'Net_Profit': x['profit'].sum()
    })
)
print(daily.to_string())

print("\n==== AUDIT 4: MAE / MFE ====")
if 'mae' in df.columns and 'mfe' in df.columns:
    avg_mae = df['mae'].mean()
    avg_mfe = df['mfe'].mean()
    avg_profit = df['profit'].mean()
    print(f"Average MAE: {avg_mae:.2f}")
    print(f"Average MFE: {avg_mfe:.2f}")
    print(f"Average Profit: {avg_profit:.2f}")
else:
    print("MAE / MFE columns not found or null.")

print("\n==== AUDIT 5: THE -697.40 LOSS ====")
worst_trade = df.loc[df['profit'].idxmin()]
print("Worst Trade Details:")
print(worst_trade[['ticket', 'timestamp', 'side', 'lots', 'profit', 'grid_level', 'cycle_id', 'mae', 'mfe', 'atr_value', 'rsi_value']].to_string())

# Find all trades in the same cycle as the worst trade
cycle_id = worst_trade['cycle_id']
if pd.notna(cycle_id):
    cycle_df = df[df['cycle_id'] == cycle_id]
    print(f"\nAll trades in Cycle {cycle_id}:")
    print(cycle_df[['ticket', 'timestamp', 'side', 'lots', 'price', 'profit']].to_string())
else:
    print("No cycle_id found for the worst trade.")
