import os
import shutil

from pathlib import Path
project_root = Path(__file__).resolve().parents[1]
source_file = project_root / 'bots' / 'EURGBP_Grid' / 'execution.py' # This might not exist if deleted!
targets = ['XAUUSD_Grid', 'EURUSD_Grid', 'AUDNZD_Grid']

for target in targets:
    target_file = project_root / 'bots' / target / 'execution.py'
    if source_file.exists():
        shutil.copy2(source_file, target_file)
        print(f"Copied to {target}")
    else:
        print(f"Source {source_file} not found. Skipping (Execution is now likely shared).")
