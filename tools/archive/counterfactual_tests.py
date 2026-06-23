import sqlite3
import pandas as pd
import numpy as np

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)

conn = sqlite3.connect('data/db/trading_data.db')
df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED' ORDER BY timestamp ASC", conn)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['hour'] = df['timestamp'].dt.hour
df['dow'] = df['timestamp'].dt.day_name()

def calc_metrics(d):
    w = d[d['profit'] > 0]['profit']
    l = d[d['profit'] < 0]['profit']
    trades = len(d)
    wr = len(w)/trades if trades > 0 else 0
    pf = w.sum() / abs(l.sum()) if len(l)>0 else float('inf')
    net = d['profit'].sum()
    
    if trades > 0:
        d_sorted = d.sort_values('timestamp').copy()
        d_sorted['cum_profit'] = d_sorted['profit'].cumsum()
        d_sorted['peak'] = d_sorted['cum_profit'].cummax()
        d_sorted['drawdown'] = d_sorted['peak'] - d_sorted['cum_profit']
        max_dd = d_sorted['drawdown'].max()
    else:
        max_dd = 0
    
    return trades, wr, pf, net, max_dd

# Sort for worst trades exclusion
df_worst_sorted = df.sort_values('profit', ascending=True)
worst_tickets = df_worst_sorted['ticket'].tolist()

datasets = [
    ("1. Baseline dataset", df),
    ("2. Excluding all SELL trades", df[df['side'] != 'SELL']),
    ("3. Excluding Monday trades", df[df['dow'] != 'Monday']),
    ("4. Excluding trades opened at hour 19", df[df['hour'] != 19]),
    ("5. Excluding worst 1 trade", df[~df['ticket'].isin(worst_tickets[:1])]),
    ("6. Excluding worst 3 trades", df[~df['ticket'].isin(worst_tickets[:3])]),
    ("7. Excluding worst 5 trades", df[~df['ticket'].isin(worst_tickets[:5])]),
    ("8. Excluding worst 10 trades", df[~df['ticket'].isin(worst_tickets[:10])])
]

results = []
for name, d in datasets:
    trades, wr, pf, net, max_dd = calc_metrics(d)
    results.append({
        'Dataset': name,
        'Trade Count': trades,
        'Win Rate': f"{wr:.2%}",
        'Profit Factor': f"{pf:.2f}",
        'Net Profit': f"{net:.2f}",
        'Max Drawdown': f"{max_dd:.2f}"
    })

res_df = pd.DataFrame(results)
print("==== COUNTERFACTUAL DATASETS ====")
print(res_df.to_string(index=False))

print("\n==== GRID LEVEL ANALYSIS ====")
def grid_metrics(x):
    w = x[x['profit']>0]['profit']
    l = x[x['profit']<0]['profit']
    trades = len(x)
    wr = len(w)/trades if trades > 0 else 0
    pf = w.sum() / abs(l.sum()) if len(l)>0 else float('inf')
    net = x['profit'].sum()
    avg = x['profit'].mean()
    return pd.Series({
        'Trades': trades,
        'Win Rate': f"{wr:.2%}",
        'Profit Factor': f"{pf:.2f}",
        'Net Profit': f"{net:.2f}",
        'Average Profit': f"{avg:.2f}"
    })

grid_df = df.dropna(subset=['grid_level']).copy()
grid_df['grid_level'] = grid_df['grid_level'].astype(int)
grid_res = grid_df.groupby('grid_level').apply(grid_metrics, include_groups=False).reset_index()
print(grid_res.to_string(index=False))

