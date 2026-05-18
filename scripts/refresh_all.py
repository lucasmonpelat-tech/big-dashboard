"""
refresh_all.py
==============
Convenience script: runs all refreshers in sequence.

    python refresh_all.py

This will:
 1. Fetch live prices from Stooq    → data/live_prices.json
 2. Scrape Lynk Markets NAV          → data/lynk_data.json
 3. Download factsheet PDFs          → factsheets/

Run daily for fresh prices, weekly/monthly for factsheets.
"""

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

scripts = [
    ("Prices (Stooq)",        "price_refresher.py", []),
    ("Benchmark 60/40 (Yahoo)","bmk_refresher.py",   []),
    ("Lynk NAV summary",      "lynk_refresher.py",  []),
    ("Lynk NAV series (chart)","lynk_nav_extractor.py", []),
    ("Factsheets",            "download_factsheets.py", []),
]

for label, script, args in scripts:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / script)] + args,
        cwd=SCRIPT_DIR.parent,
    )
    if result.returncode != 0:
        print(f"⚠ {label} failed (exit {result.returncode}) — continuing")

print(f"\n{'='*60}")
print("  All refreshers completed.")
print(f"{'='*60}\n")
