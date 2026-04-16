import os
import glob
import subprocess
import sys

# หา Path หลักของโปรเจกต์ (อิงจากตำแหน่งปัจจุบันของสคริปต์ที่อยู่ใน scripts/tools)
current_dir = os.path.dirname(os.path.abspath(__file__))
base_path = os.path.abspath(os.path.join(current_dir, "..", ".."))
output_filename = os.path.join(base_path, "ALL_CONTEXT_FOR_GEMINI.txt")

# Step 1: รัน read_db.py เพื่ออัปเดตข้อมูล CSV ล่าสุดจากฐานข้อมูล
print("--- Step 1: Updating Database Exports ---")
try:
    read_db_script = os.path.join(current_dir, "read_db.py")
    # ใช้ sys.executable แทน "python" เพื่อให้ชัวร์ว่ารันใน Interpreter เดียวกัน (venv)
    subprocess.run([sys.executable, read_db_script], check=True)

    print("Database exports updated successfully.\n")
except Exception as e:
    print(f"Warning: Could not update database exports: {e}\n")

# Step 2: รวบรวมไฟล์ทั้งหมดเข้าด้วยกัน
print(f"--- Step 2: Collecting Files from {base_path} ---")

# กำหนดรูปแบบการค้นหา
search_patterns = [
    "**/*.py",           # ไฟล์โค้ด Python ทั่วทั้งโปรเจกต์
    "**/*.log",          # ไฟล์ Log
    "**/*.csv",          # ไฟล์ข้อมูล CSV (รวมถึงที่เพิ่ง Export มาใหม่)
    "scripts/tools/*"    # ทุกไฟล์ในโฟลเดอร์ scripts/tools
]

with open(output_filename, 'w', encoding='utf-8') as outfile:
    processed_files = set() # ป้องกันไฟล์ซ้ำ
    
    for pattern in search_patterns:
        full_pattern = os.path.join(base_path, pattern)
        # ใช้ recursive=True สำหรับ pattern ที่มี **
        for filepath in glob.glob(full_pattern, recursive=("**" in pattern)):
            filepath = os.path.normpath(filepath)
            
            # ตรวจสอบเงื่อนไขการข้ามไฟล์
            if (not os.path.isfile(filepath) or 
                filepath in processed_files or 
                output_filename in filepath or
                "__pycache__" in filepath or 
                ".git" in filepath):
                continue
            
            # บันทึกหัวข้อไฟล์
            rel_path = os.path.relpath(filepath, base_path)
            outfile.write(f"\n\n{'='*50}\n")
            outfile.write(f"📁 FILE PATH: {rel_path}\n")
            outfile.write(f"{'='*50}\n\n")
            
            try:
                with open(filepath, 'r', encoding='utf-8') as infile:
                    outfile.write(infile.read())
                processed_files.add(filepath)
                print(f"Added: {rel_path}")
            except Exception as e:
                outfile.write(f"[Read Error: {e}]\n")

print(f"\nSuccess! ALL_CONTEXT_FOR_GEMINI.txt is ready at: {output_filename}")
