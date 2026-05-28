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

DATA_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = DATA_DIR / "ucits_daily_nav.json"
FI_OUTPUT_FILE = DATA_DIR / "fi_fund_nav.json"

# Credenciales baha: NUNCA hardcodear. Se leen de variables de entorno.
# Local:  set BAHA_EMAIL=... & set BAHA_PASSWORD=...
# Cron:   GitHub Secrets BAHA_EMAIL / BAHA_PASSWORD
BAHA_EMAIL = os.environ.get("BAHA_EMAIL", "")
BAHA_PASSWORD = os.environ.get("BAHA_PASSWORD", "")
LOGIN_URL = "https://www.baha.com/user/login"

# Instrumentos del equity sleeve que se valuan via baha (UCITS sin precio
# diario en Stooq + el ETF aleman 4BRZ que en Stooq solo tiene proxy EWZ malo).
# -> ucits_daily_nav.json (lo consume refresh_equity_daily / refresh_fi_daily para MV).
INSTRUMENTS = {
    "IE00BFMHRK20": {"ticker": "NBGMT", "name": "NB Global Equity Megatrends I USD"},
    "LU1985812756": {"ticker": "MFSCV", "name": "MFS Meridian Contrarian Value I1 USD"},
    "LU2940405447": {"ticker": "JHGSC", "name": "Janus Henderson Horizon Global Smaller Cos F2 USD"},
    "IE00BF4KN675": {"ticker": "LGLI",  "name": "Lazard Global Listed Infrastructure A Acc USD"},
    "IE00B6YCBF59": {"ticker": "THOR",  "name": "Thornburg Equity Income Builder I Acc USD"},
    "DE000A0Q4R85": {"ticker": "4BRZ",  "name": "iShares MSCI Brazil UCITS (DE)"},
}

# Fondos del FI sleeve via baha -> fi_fund_nav.json (SEPARADO de ucits_daily_nav.json
# a proposito: estos NAV pueden estar en EUR y NO deben entrar al calculo de MV USD
# del sleeve; solo los usa refresh_fi_race_daily.py para el RETORNO por fondo (ratio,
# currency-internal). TGF (XS2324777171) es carry proxy, no se scrapea.
FI_INSTRUMENTS = {
    "IE00BDT57R20": {"ticker": "PIMCO-LD",  "name": "PIMCO GIS Low Duration Income Inst USD"},
    "IE00B87KCF77": {"ticker": "PIMCO-INC", "name": "PIMCO GIS Income Fund Inst USD"},
    "IE00B29K0P99": {"ticker": "PIMCO-EM",  "name": "PIMCO GIS Emerging Markets Bond Inst USD"},
    "IE000OE87WX6": {"ticker": "MANIG",     "name": "Manulife Global Fund (FI)"},
    "LU2049315265": {"ticker": "SGCB",      "name": "SG fund (FI)"},
    "IE00089T5MA6": {"ticker": "MANEM",     "name": "Manulife EM (FI)"},
}

# NAV del title: "...<numero> <CCY> - baha.com". Currency-agnostic (USD/EUR/GBP/...).
# Acepta decimal con . o , (baha a veces usa coma). Captura tambien el codigo de moneda.
NAV_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s+([A-Z]{3})\s*[-–]\s*baha", re.IGNORECASE)


def _parse_nav(title):
    """Devuelve (nav_float, currency) o (None, None) si no matchea el title."""
    m = NAV_RE.search(title or "")
    if not m:
        return None, None
    num = m.group(1).replace(",", ".")
    try:
        return float(num), m.group(2).upper()
    except ValueError:
        return None, None


def _do_login(page):
    """Login baha (una sola vez por sesion). baha redirige a /user/login sin sesion."""
    if not (BAHA_EMAIL and BAHA_PASSWORD):
        print("  WARNING: sin BAHA_EMAIL/BAHA_PASSWORD en env -> baha redirige a login, NAVs vacios.")
        return
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


def _scrape_group(page, instruments, label):
    """Scrapea el NAV (del title) de cada ISIN del grupo. Devuelve {isin: {...}}."""
    navs = {}
    print(f"  -- {label} ({len(instruments)} fondos) --")
    for isin, meta in instruments.items():
        url = f"https://www.baha.com/instruments/{isin}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_function(
                    "() => document.title.includes('baha.com') && /[0-9]/.test(document.title)",
                    timeout=15000,
                )
            except Exception:
                page.wait_for_timeout(3000)
            title = page.title()
            nav, ccy = _parse_nav(title)
            if nav is not None:
                fund_id = None
                fm = re.search(r"/(FU_\d+|tts-\d+)", page.url)
                if fm:
                    fund_id = fm.group(1)
                navs[isin] = {
                    "ticker": meta["ticker"], "nav": nav, "currency": ccy,
                    "baha_fund_id": fund_id, "name": meta["name"],
                    "scrapedAt": datetime.now().isoformat(),
                }
                print(f"  {meta['ticker']:<10} {nav:>12.4f} {ccy}  ({title[:46]})")
            else:
                print(f"  {meta['ticker']:<10} NAV no encontrado en title: {title[:60]}")
        except Exception as e:
            print(f"  {meta['ticker']:<10} ERROR: {str(e)[:60]}")
    return navs


def scrape_baha():
    """Login una vez, scrapea equity + FI. Devuelve (equity_navs, fi_navs)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright no instalado. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
        page = ctx.new_page()
        _do_login(page)
        equity_navs = _scrape_group(page, INSTRUMENTS, "EQUITY sleeve")
        fi_navs = _scrape_group(page, FI_INSTRUMENTS, "FI sleeve")
        browser.close()
    return equity_navs, fi_navs


def _merge_and_save(navs, out_file, description, expected):
    """Merge con lo existente (no pisar con vacio si un scrape fallo) y guarda."""
    if len(navs) < expected:
        print(f"  WARNING: {out_file.name}: solo {len(navs)}/{expected} NAVs capturados.")
    existing = {}
    if out_file.exists():
        try:
            existing = json.load(open(out_file, encoding="utf-8")).get("navs", {})
        except Exception:
            pass
    merged = {**existing, **navs}
    out = {
        "_description": description,
        "refreshedAt": datetime.now().isoformat(),
        "source": "baha.com (NAV puntual del title) via baha_nav_refresher.py",
        "navs": merged,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Saved: {out_file}  ({len(merged)} NAVs)")


def main():
    print(f"[{datetime.now().isoformat()}] Scraping baha NAVs (equity + FI)...")
    equity_navs, fi_navs = scrape_baha()

    _merge_and_save(
        equity_navs, OUTPUT_FILE,
        "NAV cierre anterior de cada UCITS/ETF-DE del equity sleeve, de baha.com. "
        "Alimenta el punto 'today' del equity sleeve (YTD al cierre anterior).",
        len(INSTRUMENTS),
    )
    _merge_and_save(
        fi_navs, FI_OUTPUT_FILE,
        "NAV cierre anterior de cada fondo del FI sleeve, de baha.com (puede ser EUR/USD). "
        "SOLO para retorno por fondo (refresh_fi_race_daily.py); NO se usa para MV USD del sleeve.",
        len(FI_INSTRUMENTS),
    )


if __name__ == "__main__":
    main()
