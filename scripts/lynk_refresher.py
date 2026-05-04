"""
lynk_refresher.py
=================
Scrape the Lynk Markets public product page for the latest NAV, AUM,
and performance metrics.

Lynk does require an email gate, but the public page loads all data
client-side via Next.js server components. We need to navigate past the
email gate and extract metrics from the rendered HTML.

Approach: Use Playwright (headless browser) to render the page and extract
data from the DOM.

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python lynk_refresher.py --email lucas.monpelat@pampa-capital.com

Outputs:
    data/lynk_data.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "lynk_data.json"
LYNK_URL = "https://app.lynkmarkets.com/public/products/4w9aANBbvM"


def scrape_with_playwright(email: str) -> dict:
    """Render the Lynk page via headless Chromium and extract metrics."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed. Run:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print(f"[{datetime.now().isoformat()}] Loading Lynk...")
        page.goto(LYNK_URL, wait_until="networkidle")

        # Email gate
        try:
            email_input = page.locator('input[type="email"]').first
            if email_input.is_visible(timeout=3000):
                email_input.fill(email)
                page.click('button:has-text("CONTINUE")')
                page.wait_for_load_state("networkidle")
                print("  ✓ Email gate passed")
        except Exception:
            print("  (no email gate — already public)")

        # Let the chart render
        page.wait_for_timeout(2500)

        # Extract via page text
        body = page.inner_text("body")
        browser.close()

    return parse_lynk_body(body)


def parse_lynk_body(body: str) -> dict:
    """Parse the plain text dump of the Lynk page."""
    import re
    result = {
        "refreshedAt": datetime.now().isoformat(),
        "isin": None,
        "aum": None,
        "nav": None,
        "change24h": None,
        "returnYTD": None,
        "returnSI": None,
        "returnAnnualized": None,
        "volatility": None,
        "sharpe": None,
    }

    def fmatch(pattern, text, default=None, cast=float):
        m = re.search(pattern, text)
        if not m:
            return default
        try:
            return cast(m.group(1).replace(",", ""))
        except Exception:
            return default

    # ISIN
    m = re.search(r"ISIN\s*([A-Z0-9]{12})", body)
    if m: result["isin"] = m.group(1)

    # AUM (e.g. "AUM$26,535,696.12")
    result["aum"] = fmatch(r"AUM\s*\$?([\d,]+\.?\d*)", body)

    # NAV (e.g. "NAV105.8552")
    result["nav"] = fmatch(r"NAV\s*([\d\.]+)", body)

    # 24hs change
    result["change24h"] = fmatch(r"24\s*HS\s*CHANGE\s*([-\d\.]+)%", body, cast=float)

    # Cumulative returns
    result["returnSI"] = fmatch(r"CUMULATIVE\s*RETURN\s*S\.I\.\s*([-\d\.]+)%", body)
    result["returnYTD"] = fmatch(r"CUMULATIVE\s*RETURN\s*YTD\s*([-\d\.]+)%", body)
    result["returnAnnualized"] = fmatch(r"ANNUALIZED\s*RETURN\s*([-\d\.]+)%", body)

    # Risk metrics
    result["volatility"] = fmatch(r"VOLATILITY\s*([-\d\.]+)%", body)
    result["sharpe"] = fmatch(r"SHARPE\s*RATIO\s*([-\d\.]+)", body)

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="lucas.monpelat@pampa-capital.com",
                        help="Email for Lynk gate")
    args = parser.parse_args()

    data = scrape_with_playwright(args.email)

    print("\nExtracted:")
    for k, v in data.items():
        print(f"  {k:20s}: {v}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
