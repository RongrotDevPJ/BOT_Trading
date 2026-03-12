import os
import filecmp

bots_dir = r"c:\Users\t-rongrot.but\Desktop\BOT_Trading"
bots = ['BOT_XAUUSD', 'BOT_EURUSD', 'BOT_AUDNZD', 'BOT_EURGBP']
files_to_check = ['indicator.py', 'main.py', 'strategy.py', 'execution.py', 'mt5_client.py', 'time_filter.py']

base_bot = 'BOT_XAUUSD'

for file in files_to_check:
    print(f"\n--- Checking {file} ---")
    base_file = os.path.join(bots_dir, base_bot, 'Smart Grid', file)
    
    if not os.path.exists(base_file):
        print(f"Base file {base_file} not found!")
        continue
        
    with open(base_file, 'r', encoding='utf-8') as f:
        base_content = f.read()

    for bot in bots:
        if bot == base_bot: continue
        
        target_file = os.path.join(bots_dir, bot, 'Smart Grid', file)
        if not os.path.exists(target_file):
            print(f"[{bot}] Missing {file}")
            continue
            
        with open(target_file, 'r', encoding='utf-8') as f:
            target_content = f.read()
            
        if base_content == target_content:
            pass # print(f"[{bot}] {file} matches {base_bot}")
        else:
            print(f"[{bot}] diff found in {file}")

print("\n--- Summary complete ---")
