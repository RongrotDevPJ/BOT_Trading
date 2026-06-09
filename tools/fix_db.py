"""
tools/fix_db.py — แก้ไขข้อมูล Phantom rows ใน trades table
ลบแถวที่เป็น Market Snapshot (side='', status=NULL, ticket=NULL)
และแสดงสรุปหลังจากทำความสะอาดแล้ว
"""
import sqlite3
from pathlib import Path

db = Path("data/db/trading_data.db")
print(f"DB path: {db}")
print(f"DB size: {db.stat().st_size:,} bytes")

conn = sqlite3.connect(str(db), timeout=20)
conn.execute("PRAGMA journal_mode=WAL;")

cur = conn.cursor()

# 1. Count before
cur.execute("SELECT COUNT(*) FROM trades")
total_before = cur.fetchone()[0]
print(f"\nBefore cleanup: {total_before} rows")

cur.execute("SELECT COUNT(*) FROM trades WHERE (side='' OR side IS NULL) AND status IS NULL AND (ticket IS NULL OR ticket=0)")
phantom_count = cur.fetchone()[0]
print(f"Phantom snapshot rows to remove: {phantom_count}")

# 2. Show examples of phantom rows
cur.execute("SELECT id, timestamp, action, side, status, profit, lots, ticket FROM trades WHERE (side='' OR side IS NULL) AND status IS NULL LIMIT 5")
print("\nExample phantom rows:")
for r in cur.fetchall():
    print(f"  {r}")

# 3. Delete phantom rows (Market Snapshots)
cur.execute("""
    DELETE FROM trades 
    WHERE (side='' OR side IS NULL) 
      AND status IS NULL 
      AND (ticket IS NULL OR ticket=0)
""")
deleted = cur.rowcount
conn.commit()
print(f"\nDeleted {deleted} phantom rows")

# 4. Count after
cur.execute("SELECT COUNT(*) FROM trades")
total_after = cur.fetchone()[0]
print(f"After cleanup: {total_after} rows")

cur.execute("SELECT status, COUNT(*) FROM trades GROUP BY status")
print("\nBy status:")
for r in cur.fetchall():
    print(f"  {r}")

cur.execute("SELECT side, COUNT(*) FROM trades GROUP BY side")
print("\nBy side:")
for r in cur.fetchall():
    print(f"  {r}")

conn.close()
print("\nDone.")
