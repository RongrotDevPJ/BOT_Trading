import sqlite3
import pandas as pd
import os

def export_db_to_csv(db_path, output_folder):
    # Check if DB file exists
    if not os.path.exists(db_path):
        print(f"Error: Database file not found: {db_path}")
        return

    # Create export folder if it doesn't exist
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    try:
        # Connect to SQLite
        conn = sqlite3.connect(db_path)
        
        # Get all table names
        query = "SELECT name FROM sqlite_master WHERE type='table';"
        tables = pd.read_sql_query(query, conn)
        
        if tables.empty:
            print(f"Warning: No tables found in {db_path}")
            return

        print(f"Tables found in {os.path.basename(db_path)}: {tables['name'].tolist()}")

        # Export each table to CSV
        for table_name in tables['name']:
            # Skip SQLite internal tables
            if table_name == 'sqlite_sequence':
                continue
                
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            
            # Create filename and save
            output_file = os.path.join(output_folder, f"{os.path.basename(db_path).split('.')[0]}_{table_name}.csv")
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            print(f"  - Exported '{table_name}' to CSV.")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    print("--- Starting Database Export Process ---")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trading_db = os.path.normpath(os.path.join(script_dir, "../../Log_HistoryOrder/trading_data.db"))
    backup_db = os.path.normpath(os.path.join(script_dir, "../../Log_HistoryOrder/backup_data.db"))
    
    export_dir = os.path.normpath(os.path.join(script_dir, "../../Log_HistoryOrder/DB_Exports"))
    
    export_db_to_csv(trading_db, export_dir)
    export_db_to_csv(backup_db, export_dir)
    
    print("--- Database Export Process Finished ---")
