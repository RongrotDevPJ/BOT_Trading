import sqlite3
import pandas as pd
import json

print("--- LIVE DB TABLES ---")
conn = sqlite3.connect('data/db/trading_data.db')
print(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

try:
    df_live = pd.read_sql('SELECT * FROM trades', conn)
    print("Live Trades:", len(df_live))
except Exception as e:
    print(e)

print("\n--- SIM DB TABLES ---")
conn_sim = sqlite3.connect('data/sim/sim_results.db')
print(conn_sim.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())

try:
    df_sim = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn_sim)
except Exception as e:
    print(e)
