import os
import shutil

from pathlib import Path

# Get project root dynamically (two levels up from scripts/tools/ folder)
project_root = Path(__file__).resolve().parents[2]
source_dir = project_root / 'bots' / 'XAUUSD_Grid'
targets = ['AUDNZD_Grid', 'EURGBP_Grid', 'EURUSD_Grid']
files_to_sync = ['main.py', 'strategy.py'] # execution.py is now shared!

print("Starting synchronization from XAUUSD to other bots...")
for target in targets:
    for f in files_to_sync:
        src = source_dir / f
        dst = project_root / 'bots' / target / f
        if src.exists():
            shutil.copy2(src, dst)
            print(f"Copied {f} to {target}")
print("Done!")
