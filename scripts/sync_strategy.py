import os
import shutil

from pathlib import Path
project_root = Path(__file__).resolve().parents[1]
source_file = project_root / 'bots' / 'XAUUSD_Grid' / 'strategy.py'
targets = ['AUDNZD_Grid', 'EURGBP_Grid', 'EURUSD_Grid']

for target in targets:
    target_file = project_root / 'bots' / target / 'strategy.py'
    shutil.copy2(source_file, target_file)
    print(f"Copied to {target}")
