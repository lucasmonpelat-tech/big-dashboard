"""
refresh_monthly.py
==================
Master script — orquesta el refresh mensual completo del HTML dashboard.

Pasos:
  1. Descargar factsheets (download_factsheets.py)
  2. Parsear cada PDF (parse_factsheet.py)
  3. Agregar a BIG-level breakdowns (aggregate_breakdowns.py)
  4. (Optional) PIMCO Chrome MCP refresh
  5. Reportar estado final con status badges

Usage:
    python scripts/refresh_monthly.py [--month YYYY-MM]
    (default: previous month)
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime, date
import json
import argparse

ROOT = Path(__file__).parent.parent
SCRIPTS = ROOT / "scripts"


def run(cmd, label):
    """Run a subcommand, capture output, print result."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print(result.stdout if result.stdout else "")
    if result.returncode != 0:
        print(f"  [ERROR] returncode={result.returncode}")
        print(result.stderr[:1000] if result.stderr else "")
        return False
    return True


def status_report():
    """Print final status of data freshness."""
    print(f"\n{'='*70}")
    print(f"  STATUS FINAL")
    print(f"{'='*70}")

    # Check funds/ folder
    funds_dir = ROOT / "data" / "funds"
    if funds_dir.exists():
        fund_files = list(funds_dir.glob("*.json"))
        print(f"\n  Parsed fund JSONs: {len(fund_files)}")
        for fp in sorted(fund_files):
            try:
                with open(fp) as f:
                    d = json.load(f)
                n_h = len(d.get("top_holdings") or {})
                n_s = len(d.get("sectors") or {})
                n_r = len(d.get("regions") or {})
                fi = d.get("fi_metrics") or {}
                ftxt = f"YTW={fi.get('ytw')}" if fi else ""
                print(f"    {fp.stem:12s} | h={n_h} s={n_s} r={n_r} {ftxt}")
            except Exception:
                pass

    # Check breakdowns/
    bd_dir = ROOT / "data" / "breakdowns"
    if bd_dir.exists():
        bd_files = list(bd_dir.glob("*.json"))
        print(f"\n  BIG-level breakdowns: {len(bd_files)}")
        for fp in sorted(bd_files):
            print(f"    {fp.stem}")

    # Check lynk_data freshness
    lynk = ROOT / "data" / "lynk_data.json"
    if lynk.exists():
        with open(lynk) as f:
            d = json.load(f)
        print(f"\n  Lynk last refresh: {d.get('refreshedAt', '?')}")

    print(f"\n  Done at: {datetime.now().isoformat()}")
    print(f"\n  Next step: click deploy.bat (rocket) to push live")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: previous month)")
    ap.add_argument("--skip-download", action="store_true", help="Skip factsheet download")
    args = ap.parse_args()

    start = datetime.now()
    print(f"BIG Dashboard — Monthly Refresh")
    print(f"Started: {start.isoformat()}")

    # Step 1: Download factsheets
    if not args.skip_download:
        cmd = [sys.executable, str(SCRIPTS / "download_factsheets.py")]
        if args.month:
            cmd.extend(["--month", args.month])
        run(cmd, "STEP 1/3 — Download factsheets")

    # Step 2: Parse all PDFs
    run([sys.executable, str(SCRIPTS / "parse_factsheet.py")], "STEP 2/3 — Parse factsheets")

    # Step 3: Aggregate to BIG-level
    run([sys.executable, str(SCRIPTS / "aggregate_breakdowns.py")], "STEP 3/3 — Aggregate breakdowns")

    # Status
    status_report()

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n  Total elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
