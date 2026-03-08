import sys
import os

print("=== VPS Environment Check ===")
print(f"Python Version: {sys.version}")
print(f"Current Directory: {os.getcwd()}")

try:
    import MetaTrader5
    print("[OK] MetaTrader5 library is installed.")
except ImportError:
    print("[ERROR] MetaTrader5 library is NOT installed.")
    print("Please run: pip install MetaTrader5")

try:
    import config
    print("[OK] config.py found and accessible.")
except ImportError:
    print("[ERROR] config.py NOT found. Ensure you are running from the 'Smart Grid' directory.")

print("==============================")
input("Press Enter to exit...")
