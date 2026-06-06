import sqlite3
import pandas as pd

conn = sqlite3.connect('data/db/trading_data.db')
df = pd.read_sql("SELECT * FROM trades WHERE status='CLOSED'", conn)
print("Closed Trades:", len(df))
print(df.head())
