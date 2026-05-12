"""
download_factsheets.py
======================
Descarga automatizada de factsheets de cada fondo BIG.

Usage:
    python scripts/download_factsheets.py [--month YYYY-MM]

Lee data/factsheet_urls.json, descarga cada PDF, guarda en factsheets/<sleeve>/<ticker>_<date>.pdf

Si el URL tiene pattern {YYYYMMDD}, se reemplaza con la fecha del último día del mes especificado
(o último día del mes anterior por default).
"""

import json
import argparse
import subprocess
from pathlib import Path
from datetime import date, timedelta
import calendar

ROOT = Path(__file__).parent.parent


def last_day_of_month(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def previous_month_end():
    today = date.today()
    if today.month == 1:
        return last_day_of_month(today.year - 1, 12)
    return last_day_of_month(today.year, today.month - 1)


def download_pdf(url, output_path):
    """Download a PDF via curl with browser user agent."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        "curl", "-sL",
        "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
        "-o", str(output_path),
        url
    ], capture_output=True, text=True, timeout=60)

    # Verify it's actually a PDF
    if not output_path.exists() or output_path.stat().st_size < 5000:
        return False, "File too small (likely error page)"
    with open(output_path, "rb") as f:
        head = f.read(8)
    if not head.startswith(b"%PDF"):
        output_path.unlink(missing_ok=True)
        return False, "Not a PDF (might be HTML/security checkpoint)"
    return True, "OK"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: previous month)")
    ap.add_argument("--ticker", help="Solo descargar este ticker")
    args = ap.parse_args()

    if args.month:
        y, m = map(int, args.month.split("-"))
        target_date = last_day_of_month(y, m)
    else:
        target_date = previous_month_end()
    date_str = target_date.strftime("%Y%m%d")
    print(f"Target factsheet date: {target_date} (YYYYMMDD = {date_str})")

    with open(ROOT / "data" / "factsheet_urls.json") as f:
        catalog = json.load(f)

    funds = catalog["funds"]
    results = {"downloaded": [], "skipped": [], "failed": []}

    for ticker, info in funds.items():
        if ticker.startswith("_"):
            continue
        if args.ticker and ticker != args.ticker:
            continue

        url = info.get("factsheet_url", "")
        sleeve = info.get("sleeve", "Unknown").lower().replace(" ", "_")
        source_type = info.get("source_type", "")

        # Skip manual sources
        if "manual" in source_type:
            results["skipped"].append(f"{ticker} (manual email — not automatable)")
            continue

        # Skip Chrome MCP sources (PIMCO etc. - need browser session)
        if "chrome_mcp" in source_type:
            results["skipped"].append(f"{ticker} (Chrome MCP only — anti-bot blocked)")
            continue

        # Replace date pattern if present
        download_url = url.replace("{YYYYMMDD}", date_str)
        if "{YYYYMMDD}" in url:
            print(f"  {ticker}: pattern resolved -> {download_url[:80]}")
        if "TODO" in url or "XXXX" in url:
            results["failed"].append(f"{ticker} (URL pattern incomplete — needs manual ID lookup)")
            continue

        output_path = ROOT / "factsheets" / sleeve / f"{ticker}_{date_str}.pdf"
        if output_path.exists():
            print(f"  {ticker}: already downloaded ({output_path.name})")
            results["downloaded"].append(ticker)
            continue

        print(f"  {ticker}: downloading...", end="", flush=True)
        ok, msg = download_pdf(download_url, output_path)
        if ok:
            print(f" OK [{output_path.stat().st_size//1024} KB]")
            results["downloaded"].append(ticker)
        else:
            print(f" FAILED ({msg})")
            results["failed"].append(f"{ticker}: {msg}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"SUMMARY")
    print(f"{'=' * 70}")
    print(f"Downloaded ({len(results['downloaded'])}): {', '.join(results['downloaded'])}")
    print(f"Skipped ({len(results['skipped'])}):")
    for s in results["skipped"]:
        print(f"  - {s}")
    print(f"Failed ({len(results['failed'])}):")
    for f in results["failed"]:
        print(f"  - {f}")


if __name__ == "__main__":
    main()
