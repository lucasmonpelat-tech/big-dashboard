"""
lynk_nav_extractor.py
=====================
Extract BIG Fund's full NAV history from Lynk Markets public chart.

Lynk's chart (Recharts) receives a data prop with the complete series —
we hook into the React fiber tree via Playwright to pull it out.

Usage:
    pip install playwright
    playwright install chromium
    python scripts/lynk_nav_extractor.py --email lucas.monpelat@pampa-capital.com

Outputs:
    data/lynk_nav_series.json — {refreshedAt, source, series: [{date, value}, ...]}
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "lynk_nav_series.json"
LYNK_URL = "https://app.lynkmarkets.com/public/products/4w9aANBbvM"

EXTRACT_JS = r"""
() => {
  function getFiber(el) {
    const k = Object.keys(el).find(x => x.startsWith('__reactFiber'));
    return k ? el[k] : null;
  }
  function findData(fiber, max = 30) {
    const seen = new WeakSet();
    let best = null;
    function walk(f, d) {
      if (!f || d > max || seen.has(f)) return;
      seen.add(f);
      const p = f.memoizedProps;
      if (
        p?.data &&
        Array.isArray(p.data) &&
        p.data[0]?.NAV &&
        p.data.length > 100 &&
        typeof p.data[0].date === 'string' &&
        p.data[0].date.includes('T')
      ) {
        if (!best || p.data.length >= best.length) best = p.data;
      }
      if (f.return) walk(f.return, d + 1);
      if (f.child) walk(f.child, d + 1);
      if (f.sibling) walk(f.sibling, d + 1);
    }
    walk(fiber, 0);
    return best;
  }
  const svg = document.querySelector('svg.recharts-surface');
  if (!svg) return null;
  const fiber = getFiber(svg.closest('.recharts-wrapper') || svg.parentElement);
  const raw = findData(fiber);
  if (!raw) return null;
  return raw.map(d => ({ date: d.date.slice(0, 10), value: parseFloat(d.NAV) }));
}
"""


def extract(email: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        print(f"[{datetime.now()}] Loading Lynk...")
        page.goto(LYNK_URL, wait_until="networkidle")

        # Email gate
        try:
            inp = page.locator('input[type="email"]').first
            if inp.is_visible(timeout=3000):
                inp.fill(email)
                page.click('button:has-text("CONTINUE")')
                page.wait_for_load_state("networkidle")
                print("  Email gate passed")
        except Exception:
            pass

        # Wait for chart to render
        page.wait_for_selector("svg.recharts-surface", timeout=15000)
        page.wait_for_timeout(2000)

        series = page.evaluate(EXTRACT_JS)
        browser.close()
        return series


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="lucas.monpelat@pampa-capital.com")
    args = parser.parse_args()

    series = extract(args.email)
    if not series:
        print("ERROR: Could not extract NAV series")
        sys.exit(1)

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "source": "Lynk Markets public chart (extracted via React fiber)",
        "isin": "XS3037627794",
        "inception": series[0]["date"],
        "latest": series[-1],
        "first": series[0],
        "series": series,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    si_return = (series[-1]["value"] / series[0]["value"] - 1) * 100
    print(f"\n  Points: {len(series)}")
    print(f"  First : {series[0]['date']} → {series[0]['value']}")
    print(f"  Last  : {series[-1]['date']} → {series[-1]['value']}")
    print(f"  SI    : {si_return:+.2f}%")
    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
