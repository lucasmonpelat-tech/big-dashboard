"""
baha_nav_refresher.py
=====================
Scrapea el NAV del cierre anterior de cada UCITS/ETF-DE del equity sleeve
desde baha.com (publico, sin login). El NAV aparece en el document.title:
  "Neuberger Berman... 23.37 USD - baha.com"

Estos NAVs alimentan el punto "today" del equity sleeve (precio del cierre
anterior) en portfolio_reconstructor.py -> YTD live al cierre anterior.

baha es publico: NO requiere email/login (a diferencia de Lynk).

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python baha_nav_refresher.py

Outputs:
    data/ucits_daily_nav.json
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "ucits_daily_nav.json"

# Credenciales baha: NUNCA hardcodear. Se leen de variables de entorno.
# Local:  set BAHA_EMAIL=... & set BAHA_PASSWORD=...
# Cron:   GitHub Secrets BAHA_EMAIL / BAHA_PASSWORD
BAHA_EMAIL = os.environ.get("BAHA_EMAIL", "")
BAHA_PASSWORD = os.environ.get("BAHA_PASSWORD", "")
LOGIN_URL = "https://www.baha.com/user/login"

# Instrumentos del equity sleeve que se valuan via baha (UCITS sin precio
# diario en Stooq + el ETF aleman 4BRZ que en Stooq solo tiene proxy EWZ malo).
INSTRUMENTS = {
    "IE00BFMHRK20": {"ticker": "NBGMT", "name": "NB Global Equity Megatrends I USD"},
    "LU1985812756": {"ticker": "MFSCV", "name": "MFS Meridian Contrarian Value I1 USD"},
    "LU2940405447": {"ticker": "JHGSC", "name": "Janus Henderson Horizon Global Smaller Cos F2 USD"},
    "IE00BF4KN675": {"ticker": "LGLI",  "name": "Lazard Global Listed Infrastructure A Acc USD"},
    "IE00B6YCBF59": {"ticker": "THOR",  "name": "Thornburg Equity Income Builder I Acc USD"},
    "DE000A0Q4R85": {"ticker": "4BRZ",  "name": "iShares MSCI Brazil UCITS (DE)"},
}

# NAV del title: "...<numero> USD - baha.com"
NAV_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s+USD\s*[-–]\s*baha", re.IGNORECASE)


def scrape_baha() -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright no instalado. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    navs = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        page = ctx.new_page()

        # ---- LOGIN (baha requiere sesion; sin login redirige a /user/login) ----
        if BAHA_EMAIL and BAHA_PASSWORD:
            try:
                print("  Login baha...")
                page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                # Paso 1: email
                page.fill("#Email", BAHA_EMAIL)
                page.click("#sendEmail")
                page.wait_for_timeout(2500)
                # Paso 2: password (aparece tras el email)
                pwd = page.locator('input[type="password"]').first
                pwd.wait_for(state="visible", timeout=10000)
                pwd.fill(BAHA_PASSWORD)
                # Submit: boton de login o Enter
                try:
                    page.click('button[type="submit"], input[type="submit"]', timeout=3000)
                except Exception:
                    pwd.press("Enter")
                page.wait_for_load_state("networkidle", timeout=20000)
                page.wait_for_timeout(2000)
                if "/user/login" in page.url:
                    print("  WARNING: login no confirmado (sigue en /user/login). Revisar credenciales.")
                else:
                    print("  Login OK")
            except Exception as e:
                print(f"  Login ERROR: {str(e)[:80]}")
        else:
            print("  WARNING: sin BAHA_EMAIL/BAHA_PASSWORD en env -> baha redirige a login, NAVs vacios.")

        for isin, meta in INSTRUMENTS.items():
            url = f"https://www.baha.com/instruments/{isin}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # baha redirige a la pagina del fondo y setea el title (con el NAV)
                # via JS. Esperar a que el title tenga "baha.com" + un numero.
                try:
                    page.wait_for_function(
                        "() => document.title.includes('baha.com') && /[0-9]/.test(document.title)",
                        timeout=15000,
                    )
                except Exception:
                    page.wait_for_timeout(3000)
                title = page.title()
                m = NAV_RE.search(title)
                if m:
                    nav = float(m.group(1))
                    fund_id = None
                    fm = re.search(r"/(FU_\d+|tts-\d+)", page.url)
                    if fm:
                        fund_id = fm.group(1)
                    navs[isin] = {
                        "ticker": meta["ticker"], "nav": nav,
                        "baha_fund_id": fund_id, "name": meta["name"],
                    }
                    print(f"  {meta['ticker']:<8} {nav:>10.4f} USD  ({title[:50]})")
                else:
                    print(f"  {meta['ticker']:<8} NAV no encontrado en title: {title[:60]}")
            except Exception as e:
                print(f"  {meta['ticker']:<8} ERROR: {str(e)[:60]}")
        browser.close()
    return navs


def main():
    print(f"[{datetime.now().isoformat()}] Scraping baha NAVs...")
    navs = scrape_baha()
    if len(navs) < len(INSTRUMENTS):
        print(f"WARNING: solo {len(navs)}/{len(INSTRUMENTS)} NAVs capturados.")

    # Merge con el existente (no pisar si un scrape fallo — mantener el ultimo bueno)
    existing = {}
    if OUTPUT_FILE.exists():
        try:
            existing = json.load(open(OUTPUT_FILE)).get("navs", {})
        except Exception:
            pass
    merged = {**existing, **navs}

    out = {
        "_description": "NAV cierre anterior de cada UCITS/ETF-DE del equity sleeve, de baha.com. Alimenta el punto 'today' del equity sleeve (YTD al cierre anterior).",
        "refreshedAt": datetime.now().isoformat(),
        "source": "baha.com (NAV puntual del title) via baha_nav_refresher.py",
        "navs": merged,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {OUTPUT_FILE}  ({len(merged)} NAVs)")


if __name__ == "__main__":
    main()
