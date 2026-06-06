import sqlite3
import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

conn = sqlite3.connect('data/db/trading_data.db')
df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED' ORDER BY timestamp ASC", conn)
df['timestamp'] = pd.to_datetime(df['timestamp'])

print("==== A) BUY vs SELL (Evidence Only) ====")
buy_df = df[df['side'] == 'BUY']
sell_df = df[df['side'] == 'SELL']

metrics = ['hold_time_sec', 'mae', 'mfe', 'atr_value', 'spread_at_entry', 'rsi_value', 'grid_level', 'lots']
results_A = pd.DataFrame(index=metrics, columns=['BUY_Avg', 'SELL_Avg'])

for m in metrics:
    if m in df.columns:
        results_A.loc[m, 'BUY_Avg'] = buy_df[m].mean()
        results_A.loc[m, 'SELL_Avg'] = sell_df[m].mean()

print(results_A)

print("\n==== B) TICKET 3560310082 (Evidence Only) ====")
worst_ticket = 3560310082
worst_row = df[df['ticket'] == worst_ticket]
if not worst_row.empty:
    cycle_id = worst_row.iloc[0]['cycle_id']
    print(f"Cycle ID: {cycle_id}")
    cycle_trades = df[df['cycle_id'] == cycle_id].copy()
    cycle_trades.sort_values(by='timestamp', inplace=True)
    cols = ['ticket', 'timestamp', 'open_time_unix', 'side', 'price', 'lots', 'profit', 'grid_level', 'mae', 'mfe', 'atr_value', 'rsi_value']
    print(cycle_trades[[c for c in cols if c in cycle_trades.columns]].to_string())
else:
    print("Ticket not found.")

print("\n==== C) MONDAY LOSSES (Evidence Only) ====")
df['dow'] = df['timestamp'].dt.day_name()
mon_df = df[df['dow'] == 'Monday'].copy()
if not mon_df.empty:
    print("Monday Profit Distribution:")
    print(f"Count: {len(mon_df)}")
    print(f"Mean: {mon_df['profit'].mean():.2f}")
    print(f"Median: {mon_df['profit'].median():.2f}")
    print(f"Std Dev: {mon_df['profit'].std():.2f}")
    
    print("\nTop 5 Monday Losses:")
    print(mon_df.nsmallest(5, 'profit')[['ticket', 'profit', 'side', 'grid_level', 'timestamp']].to_string(index=False))
    
    print("\nTop 5 Monday Wins:")
    print(mon_df.nlargest(5, 'profit')[['ticket', 'profit', 'side', 'grid_level', 'timestamp']].to_string(index=False))
else:
    print("No Monday trades.")

print("\n==== D) FULL vs REMOVED WORST TRADE (Evidence Only) ====")
def calc_metrics(d):
    w = d[d['profit'] > 0]['profit']
    l = d[d['profit'] < 0]['profit']
    wr = len(w)/len(d) if len(d)>0 else 0
    pf = w.sum() / abs(l.sum()) if len(l)>0 else float('inf')
    
    d_sorted = d.sort_values('timestamp').copy()
    d_sorted['cum_profit'] = d_sorted['profit'].cumsum()
    d_sorted['peak'] = d_sorted['cum_profit'].cummax()
    d_sorted['drawdown'] = d_sorted['peak'] - d_sorted['cum_profit']
    max_dd = d_sorted['drawdown'].max()
    return wr, pf, max_dd

wr_full, pf_full, dd_full = calc_metrics(df)
df_minus_worst = df[df['ticket'] != worst_ticket]
wr_minus, pf_minus, dd_minus = calc_metrics(df_minus_worst)

print(f"Dataset Full:          WR={wr_full:.2%}, PF={pf_full:.2f}, MaxDD={dd_full:.2f}")
print(f"Dataset Minus Worst:   WR={wr_minus:.2%}, PF={pf_minus:.2f}, MaxDD={dd_minus:.2f}")

print("\n==== E) MONTE CARLO SEEDS (Evidence Only) ====")
INITIAL_EQUITY = 5000.0
RUNS = 10000
TRADES_PER_RUN = 1000
trades_array = df['profit'].values

seeds = [1, 42, 99, 1234]
for s in seeds:
    np.random.seed(s)
    ruin_count = 0
    mc_dds = []
    
    # Fast vectorized MC logic for multiple runs to save time
    sims = np.random.choice(trades_array, size=(RUNS, TRADES_PER_RUN), replace=True)
    equity_paths = INITIAL_EQUITY + np.cumsum(sims, axis=1)
    
    # Ruin
    ruins = np.any(equity_paths <= 0, axis=1)
    risk_of_ruin = ruins.sum() / RUNS
    
    # DD
    peaks = np.maximum.accumulate(equity_paths, axis=1)
    dds = peaks - equity_paths
    max_dds = np.max(dds, axis=1)
    
    avg_dd = np.mean(max_dds)
    worst_dd = np.max(max_dds)
    
    print(f"Seed {s:4d}: Ruin={risk_of_ruin:6.2%}, Avg DD={avg_dd:8.2f}, Worst DD={worst_dd:8.2f}")
