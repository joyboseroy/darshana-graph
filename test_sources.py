"""
test_sources.py — run this first to check all sources are reachable
and the parsers return sensible output.

Usage: python test_sources.py
"""

import requests
import json
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0"}

def check(label, url, expected_fragment):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        found = expected_fragment.lower() in r.text.lower()
        status = "✓" if found else "⚠ reachable but fragment not found"
        print(f"  {status}  {label}")
        if not found:
            print(f"         Expected: '{expected_fragment}'")
            print(f"         Got (first 200 chars): {r.text[:200]}")
        return found
    except Exception as e:
        print(f"  ✗  {label}: {e}")
        return False


print("\n=== Vedanta Source Connectivity Test ===\n")

tests = [
    (
        "Bhagavad Gita API (BG 2.20)",
        "https://vedicscriptures.github.io/slok/2/20",
        "gambhirananda",
    ),
    (
        "Vedabase Prabhupada (BG 1.1)",
        "https://vedabase.io/en/library/bg/1/1/",
        "purport",
    ),
    (
        "Brahma Sutras Shankara Vol 1 (sacred-texts)",
        "https://sacred-texts.com/hin/sbe34/index.htm",
        "brahma",
    ),
    (
        "Brahma Sutras Ramanuja Vol 2 (sacred-texts)",
        "https://sacred-texts.com/hin/sbe48/index.htm",
        "brahma",
    ),
    (
        "Upanishads Vol 1 (sacred-texts / Müller)",
        "https://sacred-texts.com/hin/sbe01/index.htm",
        "upanishad",
    ),
    (
        "Upanishads Vol 2 (sacred-texts / Müller)",
        "https://sacred-texts.com/hin/sbe15/index.htm",
        "upanishad",
    ),
    (
        "Vivekananda Complete Works Vol 1",
        "https://cwsv.belurmath.org/volume_1/vol_1_frame.htm",
        "vivekananda",
    ),
    (
        "Vivekananda Complete Works Vol 2",
        "https://cwsv.belurmath.org/volume_2/vol_2_frame.htm",
        "vivekananda",
    ),
]

passed = 0
for label, url, fragment in tests:
    if check(label, url, fragment):
        passed += 1

print(f"\n{passed}/{len(tests)} sources reachable.")

if passed == len(tests):
    print("\nAll good — run: python scrape.py --source bg  (to start)")
else:
    print("\nFix failing sources before running full scrape.")
    print("Note: sacred-texts.com occasionally rate-limits; retry after a few minutes.")

# Also do a quick parse sanity check on BG API
print("\n=== Quick parse check: BG 2.20 ===\n")
try:
    r = requests.get(
        "https://vedicscriptures.github.io/slok/2/20",
        headers=HEADERS, timeout=15
    )
    d = r.json()
    print(f"  Sanskrit: {d.get('slok','')[:60]}...")
    print(f"  Gambhirananda: {d.get('gambhirananda',{}).get('et','')[:80]}...")
    print(f"  Keys available: {list(d.keys())}")
except Exception as e:
    print(f"  Parse check failed: {e}")
