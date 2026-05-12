"""
refresh_pimco.py
================
Refresh PIMCO fund data using Playwright (PIMCO blocks curl/anti-bot).

Extracts for each of the 3 PIMCO funds:
  - Yield to Maturity (YTW)
  - Current Yield
  - Effective Duration
  - Effective Maturity
  - Top 10 Country exposure
  - Sector allocation
  - Credit quality breakdown
  - As-of date

Output: data/funds/PIMCO-LD.json, PIMCO-INC.json, PIMCO-EM.json (same schema as parse_factsheet.py)

Usage:
    pip install playwright
    playwright install chromium
    python scripts/refresh_pimco.py
"""

import json
import re
import sys
from pathlib import Path
from datetime import date, datetime

ROOT = Path(__file__).parent.parent

PIMCO_FUNDS = [
    {
        "ticker": "PIMCO-LD",
        "isin": "IE00BDT57R20",
        "name": "PIMCO GIS Low Duration Income I",
        "url": "https://www.pimco.com/sg/en/investments/gis/low-duration-income-fund/inst-usd-accumulation",
    },
    {
        "ticker": "PIMCO-INC",
        "isin": "IE00B87KCF77",
        "name": "PIMCO GIS Income I",
        "url": "https://www.pimco.com/sg/en/investments/gis/income-fund/inst-usd-accumulation",
    },
    {
        "ticker": "PIMCO-EM",
        "isin": "IE00B29K0P99",
        "name": "PIMCO GIS EM Local Bond I",
        "url": "https://www.pimco.com/gb/en/investments/gis/emerging-local-bond-fund/inst-usd-accumulation",
    },
]


def find_pct(text, label, max_distance=200):
    """Find a percentage value following a label."""
    idx = text.lower().find(label.lower())
    if idx < 0:
        return None
    chunk = text[idx:idx + max_distance]
    # First number with optional % sign
    m = re.search(r"(\d{1,2}\.\d{1,2})\s*%?", chunk)
    return float(m.group(1)) if m else None


def find_years(text, label, max_distance=200):
    """Find a years value following a label."""
    idx = text.lower().find(label.lower())
    if idx < 0:
        return None
    chunk = text[idx:idx + max_distance]
    m = re.search(r"(\d{1,2}\.\d{1,2})", chunk)
    return float(m.group(1)) if m else None


def find_section_after(text, label, end_markers, max_chars=2000):
    """Find a section starting at `label` and ending at any `end_markers`."""
    idx = text.lower().find(label.lower())
    if idx < 0:
        return None
    chunk = text[idx:idx + max_chars]
    for em in end_markers:
        end_idx = chunk.lower().find(em.lower(), len(label))
        if end_idx > 0:
            chunk = chunk[:end_idx]
            break
    return chunk


def parse_country_breakdown(text):
    """Parse 'Top 10 Country' section. Returns dict[country] -> pct."""
    chunk = find_section_after(text, "Top 10 Country", ["Effective Duration", "Sector", "Top 10 Sector"])
    if not chunk:
        return None
    countries = {}
    for line in chunk.split("\n"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z\s]+?)\s+(-?\d{1,2}\.\d{1,2})$", line)
        if m:
            name = m.group(1).strip()
            pct = float(m.group(2))
            if name.lower() in ["fx", "total", "country"]:
                continue
            countries[name] = pct
            if len(countries) >= 12:
                break
    return countries if countries else None


def parse_sector_breakdown(text):
    """Parse 'Sector' allocation."""
    chunk = find_section_after(text, "Sector Allocation", ["Country", "Credit Quality", "Duration", "Maturity"])
    if not chunk:
        chunk = find_section_after(text, "Sector Exposure", ["Country", "Credit Quality", "Duration"])
    if not chunk:
        return None
    sectors = {}
    for line in chunk.split("\n"):
        line = line.strip()
        m = re.match(r"^([A-Za-z\s/\-&]+?)\s+(-?\d{1,3}\.\d{1,2})$", line)
        if m:
            name = m.group(1).strip()
            pct = float(m.group(2))
            sectors[name] = pct
    return sectors if sectors else None


def extract_pimco_data(page):
    """Extract all metrics from a loaded PIMCO fund page."""
    text = page.inner_text("body")

    data = {
        "fi_metrics": {},
        "top_holdings": None,
        "sectors": parse_sector_breakdown(text),
        "regions": parse_country_breakdown(text),
        "as_of_factsheet": None,
    }

    # YTW / YTM
    ytw = find_pct(text, "Yield To Maturity")
    if ytw:
        data["fi_metrics"]["ytw"] = ytw

    # Current Yield
    cur_yld = find_pct(text, "Current Yield")
    if cur_yld:
        data["fi_metrics"]["current_yield"] = cur_yld

    # Underlying Portfolio Yield
    upy = find_pct(text, "Underlying Portfolio Yield")
    if upy:
        data["fi_metrics"]["underlying_portfolio_yield"] = upy

    # Effective Duration
    dur = find_years(text, "Effective Duration")
    if dur:
        data["fi_metrics"]["duration"] = dur

    # Effective Maturity
    matur = find_years(text, "Effective Maturity")
    if matur:
        data["fi_metrics"]["maturity"] = matur

    # As-of date
    m = re.search(r"As of (\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        data["as_of_factsheet"] = m.group(1)

    return data


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    out_dir = ROOT / "data" / "funds"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Refreshing PIMCO data via Playwright...")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
        )
        for fund in PIMCO_FUNDS:
            print(f"  {fund['ticker']}... ", end="", flush=True)
            try:
                page = context.new_page()
                page.goto(fund["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)  # wait for JS-loaded data

                extracted = extract_pimco_data(page)

                result = {
                    "ticker": fund["ticker"],
                    "isin": fund["isin"],
                    "name": fund["name"],
                    "sleeve": "Fixed Income",
                    "source": fund["url"],
                    "parsed_at": date.today().isoformat(),
                    **extracted,
                }

                out_path = out_dir / f"{fund['ticker']}.json"
                with open(out_path, "w") as f:
                    json.dump(result, f, indent=2)

                fi = result["fi_metrics"]
                print(f"OK | YTW={fi.get('ytw')}, Dur={fi.get('duration')}, Venc={fi.get('maturity')}, CurYld={fi.get('current_yield')}")

                page.close()
            except Exception as e:
                print(f"ERROR: {e}")

        browser.close()

    print()
    print(f"[OK] PIMCO data saved to {out_dir}/")


if __name__ == "__main__":
    main()
