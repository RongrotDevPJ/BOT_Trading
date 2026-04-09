import sqlite3
import pandas as pd
import os

def export_db_to_csv(db_path, output_folder):
    # ตรวจสอบว่าไฟล์ DB มีอยู่จริงไหม
    if not os.path.exists(db_path):
        print(f"❌ ไม่พบไฟล์ฐานข้อมูล: {db_path}")
        return

    # สร้างโฟลเดอร์สำหรับเก็บไฟล์ Export ถ้ายังไม่มี
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    try:
        # เชื่อมต่อฐานข้อมูล SQLite
        conn = sqlite3.connect(db_path)
        
        # ดึงรายชื่อตาราง (Table) ทั้งหมดที่มีในไฟล์ DB
        query = "SELECT name FROM sqlite_master WHERE type='table';"
        tables = pd.read_sql_query(query, conn)
        
        if tables.empty:
            print(f"⚠️ ไม่พบตารางข้อมูลใน {db_path}")
            return

        print(f"🔍 พบตารางใน {db_path}: {tables['name'].tolist()}")

        # ดึงข้อมูลแต่ละตารางออกมาเซฟเป็น CSV
        for table_name in tables['name']:
            # ข้ามตารางระบบของ SQLite
            if table_name == 'sqlite_sequence':
                continue
                
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            
            # ตั้งชื่อไฟล์และเซฟ
            output_file = os.path.join(output_folder, f"{os.path.basename(db_path).split('.')[0]}_{table_name}.csv")
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            print(f"✅ ดึงข้อมูลตาราง '{table_name}' สำเร็จ! เซฟไว้ที่: {output_file}")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")
    finally:
        # Check if conn was initialized before trying to close it
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("--- 📊 เริ่มต้นกระบวนการอ่านและ Export ฐานข้อมูล ---")
    
    # กำหนด Path ไปหาไฟล์ DB (อ้างอิงจากโฟลเดอร์ root ของโปรเจกต์)
    # paths are relative to this script's location in scripts/tools/
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trading_db = os.path.normpath(os.path.join(script_dir, "../../Log_HistoryOrder/trading_data.db"))
    backup_db = os.path.normpath(os.path.join(script_dir, "../../Log_HistoryOrder/backup_data.db"))
    
    # โฟลเดอร์ปลายทางที่จะเก็บไฟล์ CSV
    export_dir = os.path.normpath(os.path.join(script_dir, "../../Log_HistoryOrder/DB_Exports"))
    
    export_db_to_csv(trading_db, export_dir)
    export_db_to_csv(backup_db, export_dir)
    
    print("--- 🎉 เสร็จสิ้นกระบวนการ ---")
