import os
import shutil

from pathlib import Path
# Get project root dynamically (two levels up from scripts/tools/ folder)
project_root = Path(__file__).resolve().parents[2]
# Note: Execution is now shared in shared_utils/, but syncing exists for legacy support/customization
source_file = project_root / 'bots' / 'EURGBP_Grid' / 'execution.py' 
targets = ['XAUUSD_Grid', 'EURUSD_Grid', 'AUDNZD_Grid']

for target in targets:
    target_file = project_root / 'bots' / target / 'execution.py'
    if source_file.exists():
        shutil.copy2(source_file, target_file)
        print(f"Copied to {target}")
    else:
        print(f"Source {source_file} not found. Skipping (Execution is now likely shared).")
