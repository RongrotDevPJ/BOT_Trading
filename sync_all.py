import os
import shutil

bots_dir = r"c:\Users\t-rongrot.but\Desktop\BOT_Trading"
source_dir = os.path.join(bots_dir, 'BOT_XAUUSD', 'Smart Grid')
targets = ['BOT_EURUSD', 'BOT_EURGBP', 'BOT_AUDNZD']
files_to_sync = ['main.py', 'execution.py', 'strategy.py']

print("Starting synchronization from XAUUSD to other bots...")
for target in targets:
    for f in files_to_sync:
        src = os.path.join(source_dir, f)
        dst = os.path.join(bots_dir, target, 'Smart Grid', f)
        shutil.copy2(src, dst)
        print(f"Copied {f} to {target}")
print("Done!")
