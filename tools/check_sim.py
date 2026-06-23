import sqlite3
from pathlib import Path

db = Path("data/sim/sim_results.db")
conn = sqlite3.connect(str(db), timeout=10)
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("TABLES:", tables)

for name in tables:
    cur.execute(f"SELECT COUNT(*) FROM {name}")
    count = cur.fetchone()[0]
    print(f"\n  [{name}]: {count} rows")
    if count > 0:
        cur.execute(f"SELECT * FROM {name} ORDER BY rowid DESC LIMIT 5")
        for r in cur.fetchall():
            print(f"    {r}")
    else:
        cur.execute(f"PRAGMA table_info({name})")
        cols = [r[1] for r in cur.fetchall()]
        print(f"    COLUMNS: {cols}")

conn.close()
