"""
Quick test script for news_filter.py — checks IG API connectivity and event parsing.
Run: python scripts/tools/test_news.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import requests
import pytz
from datetime import datetime, timedelta

URL = "https://api.ig.com/explore/events"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "*/*",
    "Authorization": "Basic Y2FsZW5kYXI6U3VQZVJsT25HcEEkJCR3MDByZDU2NzE=",
    "Origin": "https://www.ig.com",
    "Referer": "https://www.ig.com/",
}

now = datetime.now(pytz.utc)
params = {
    "from": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    "to":   (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    "lang": "en",
}

print(f"[TEST] Calling IG API: {URL}")
print(f"[TEST] Range: {params['from']} -> {params['to']}")

try:
    r = requests.get(URL, headers=HEADERS, params=params, timeout=15)
    print(f"\n[RESULT] HTTP Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"[RESULT] Total events returned: {len(data)}")

        high_impact = [x for x in data if x.get("importance") == 3]
        print(f"[RESULT] High-impact events (importance=3): {len(high_impact)}")

        if high_impact:
            print("\n[SAMPLE] First 5 high-impact events:")
            for e in high_impact[:5]:
                print(f"  - {e.get('date','?')} | {e.get('event','?')} | {e.get('currency','?')} | {e.get('country','?')}")
        else:
            print("[INFO] No high-impact events in this window (normal if weekend/holiday).")

        # Test is_safe_to_trade via the actual module
        print("\n[TEST] Running is_safe_to_trade() for each symbol...")
        from shared_utils.news_filter import is_safe_to_trade
        for sym in ["AUDNZD", "EURGBP", "EURUSD", "XAUUSD"]:
            result = is_safe_to_trade(sym)
            icon = "✅ SAFE" if result else "⚠️  BLOCKED (news)"
            print(f"  {sym}: {icon}")

    else:
        print(f"[ERROR] Non-200 response. Body: {r.text[:500]}")
        print("[WARN] news_filter will use stale cache or return True (allow all) — RISK!")

except requests.exceptions.ConnectionError:
    print("[ERROR] Connection failed — VPS may not have internet access to api.ig.com")
except requests.exceptions.Timeout:
    print("[ERROR] Request timed out — IG API may be down")
except Exception as e:
    print(f"[ERROR] Unexpected: {e}")
