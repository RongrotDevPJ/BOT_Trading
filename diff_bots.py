import os
import difflib

bots_dir = r"c:\Users\t-rongrot.but\Desktop\BOT_Trading"
base_bot = 'BOT_XAUUSD'
targets = ['BOT_EURUSD', 'BOT_AUDNZD', 'BOT_EURGBP']
file = 'strategy.py'

base_file = os.path.join(bots_dir, base_bot, 'Smart Grid', file)
with open(base_file, 'r', encoding='utf-8') as f:
    base_lines = f.readlines()

for target in targets:
    print(f"\n--- {base_bot} vs {target} : {file} ---")
    target_file = os.path.join(bots_dir, target, 'Smart Grid', file)
    with open(target_file, 'r', encoding='utf-8') as f:
        target_lines = f.readlines()
        
    for line in difflib.unified_diff(base_lines, target_lines, fromfile=base_bot, tofile=target, n=0):
        print(line, end='')
