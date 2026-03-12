import os
import shutil

bots_dir = r"c:\Users\t-rongrot.but\Desktop\BOT_Trading"
source_file = os.path.join(bots_dir, 'BOT_XAUUSD', 'Smart Grid', 'strategy.py')
targets = ['BOT_EURGBP', 'BOT_EURUSD', 'BOT_AUDNZD']

for target in targets:
    target_file = os.path.join(bots_dir, target, 'Smart Grid', 'strategy.py')
    shutil.copy2(source_file, target_file)
    print(f"Copied strategy.py to {target}")
