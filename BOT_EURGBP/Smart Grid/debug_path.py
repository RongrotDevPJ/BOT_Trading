import sys
from pathlib import Path
import os

print(f"Current Working Directory: {os.getcwd()}")
print(f"File Path: {__file__}")

current_dir = Path(__file__).resolve().parent
print(f"Resolved current_dir: {current_dir}")

project_root = current_dir.parent.parent
print(f"Calculated project_root: {project_root}")

print(f"Project Root exists? {project_root.exists()}")

if str(project_root) not in sys.path:
    print(f"Appending {project_root} to sys.path")
    sys.path.append(str(project_root))

print("Current sys.path:")
for p in sys.path:
    print(f"  {p}")

try:
    import shared_utils
    print("SUCCESS: shared_utils imported.")
    import shared_utils.mt5_client
    print("SUCCESS: shared_utils.mt5_client imported.")
except ImportError as e:
    print(f"FAILED: {e}")

# Check if shared_utils is in project_root
expected_shared_utils = project_root / "shared_utils"
print(f"Looking for shared_utils at: {expected_shared_utils}")
print(f"Does it exist? {expected_shared_utils.exists()}")
if expected_shared_utils.exists():
    print(f"Contents of {expected_shared_utils}:")
    try:
        for f in os.listdir(expected_shared_utils):
            print(f"  {f}")
    except Exception as ex:
        print(f"  Error listing: {ex}")
