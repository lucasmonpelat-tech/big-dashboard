"""
sync_ucits_nav_from_pershing.py
================================
Reemplaza baha_nav_refresher.py como fuente de data/ucits_daily_nav.json.

Motivo (2026-07-28): baha_nav_refresher.py (Playwright + login) nunca funciono
en CI desde que se creo (22-May-2026) -- NBGMT/MFSCV quedaron con el NAV semilla
congelado 2+ meses, silenciado por el patron "merge preserva el ultimo valor
bueno". El precio de Pershing (via NetX360, ya bajado a diario por
dashboard_v2/ingest/netx360_auto.py -> data/canonical/{date}/positions.json) es
mas simple, mas confiable (sin login/Cloudflare) y es el precio real que marca
el custodio -- decision de Lucas 2026-07-28.

Lee el positions.json canonical MAS RECIENTE ya commiteado en el repo (no hace
falta que sea el de hoy: el precio de Pershing ya viene con lag T-2/T-3 tipico)
y escribe data/ucits_daily_nav.json con el MISMO schema que generaba
baha_nav_refresher.py, para que TODOS los consumers (refresh_equity_daily,
refresh_fi_daily, refresh_equity_race_daily, refresh_holdings_returns_daily,
refresh_fi_race_daily, portfolio_reconstructor) sigan funcionando sin cambios.

Si el price_date del positions.json usado queda mas viejo que MAX_STALE_BDAYS
dias habiles, escribe data/_alerts/ucits_price_stale_YYYY-MM-DD.json.

Usage:
    python sync_ucits_nav_from_pershing.py
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
CANONICAL_DIR = ROOT / "data" / "canonical"
OUTPUT_FILE = ROOT / "data" / "ucits_daily_nav.json"
ALERTS_DIR = ROOT / "data" / "_alerts"

MAX_STALE_BDAYS = 5

# ISINs que antes scrapeaba baha_nav_refresher.py (equity sleeve UCITS + 4BRZ).
INSTRUMENTS = {
    "IE00BFMHRK20": {"ticker": "NBGMT", "name": "NB Global Equity Megatrends I USD"},
    "LU1985812756": {"ticker": "MFSCV", "name": "MFS Meridian Contrarian Value I1 USD"},
    "LU2940405447": {"ticker": "JHGSC", "name": "Janus Henderson Horizon Global Smaller Cos F2 USD"},
    "IE00BF4KN675": {"ticker": "LGLI",  "name": "Lazard Global Listed Infrastructure A Acc USD"},
    "IE00B6YCBF59": {"ticker": "THOR",  "name": "Thornburg Equity Income Builder I Acc USD"},
    "DE000A0Q4R85": {"ticker": "4BRZ",  "name": "iShares MSCI Brazil UCITS (DE)"},
}


def _bdays_between(d1: date, d2: date) -> int:
    """Dias habiles (lun-vie) entre d1 y d2, aproximado (sin feriados)."""
    if d2 <= d1:
        return 0
    n = 0
    d = d1
    while d < d2:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def latest_canonical_positions():
    """Ultimo data/canonical/{date}/positions.json disponible en el repo."""
    if not CANONICAL_DIR.exists():
        return None, None
    dates = sorted(p.name for p in CANONICAL_DIR.iterdir() if p.is_dir())
    for d in reversed(dates):
        f = CANONICAL_DIR / d / "positions.json"
        if f.exists():
            try:
                return json.load(open(f, encoding="utf-8")), d
            except Exception:
                continue
    return None, None


def main():
    print(f"[{datetime.now().isoformat()}] Sync UCITS NAV desde Pershing (canonical positions.json)...")
    positions, snapshot_date = latest_canonical_positions()
    if positions is None:
        print("  ERROR: no hay ningun canonical positions.json disponible. Abortando.")
        return

    print(f"  Usando snapshot: {snapshot_date}")
    by_isin = {h["isin"]: h for h in positions.get("holdings", []) if h.get("isin")}

    navs = {}
    stale = {}
    today = date.today()
    for isin, meta in INSTRUMENTS.items():
        h = by_isin.get(isin)
        if not h or not h.get("market_price_ccy"):
            print(f"  {meta['ticker']:<8} sin posicion/precio en el snapshot -- se omite")
            continue
        price_date_iso = h.get("price_date")
        navs[isin] = {
            "ticker": meta["ticker"],
            "nav": h["market_price_ccy"],
            "currency": h.get("position_ccy", "USD"),
            "baha_fund_id": None,
            "name": meta["name"],
            "price_date": price_date_iso,
            "source": "pershing_netx360",
            "scrapedAt": datetime.now().isoformat(),
        }
        bdays_old = None
        if price_date_iso:
            try:
                bdays_old = _bdays_between(date.fromisoformat(price_date_iso), today)
            except ValueError:
                pass
        flag = ""
        if bdays_old is not None and bdays_old > MAX_STALE_BDAYS:
            stale[meta["ticker"]] = {"isin": isin, "price_date": price_date_iso, "bdays_old": bdays_old}
            flag = f"  [STALE {bdays_old}bd]"
        print(f"  {meta['ticker']:<8} {h['market_price_ccy']:>12.4f}  price_date={price_date_iso}{flag}")

    if len(navs) < len(INSTRUMENTS):
        print(f"  WARNING: solo {len(navs)}/{len(INSTRUMENTS)} instrumentos con precio en el snapshot.")

    out = {
        "_description": "NAV T-1 (aprox) de cada UCITS/ETF-DE del equity sleeve, desde el precio "
                         "oficial de Pershing (custodio) via NetX360. Reemplaza el scrape de baha.com "
                         "(nunca funciono en CI, ver git history pre-2026-07-28).",
        "refreshedAt": datetime.now().isoformat(),
        "source": f"Pershing/NetX360 via canonical/{snapshot_date}/positions.json (sync_ucits_nav_from_pershing.py)",
        "snapshot_date": snapshot_date,
        "navs": navs,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"Saved: {OUTPUT_FILE}  ({len(navs)} NAVs)")

    if stale:
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        alert_file = ALERTS_DIR / f"ucits_price_stale_{today.isoformat()}.json"
        with open(alert_file, "w", encoding="utf-8") as f:
            json.dump({
                "date": today.isoformat(),
                "source": "sync_ucits_nav_from_pershing.py",
                "error": f"El precio de Pershing (NetX360) para estos UCITS tiene mas de "
                         f"{MAX_STALE_BDAYS} dias habiles: {', '.join(stale.keys())}. "
                         "Probable falla del download diario de NetX360 (positions.xlsx) "
                         "varios dias seguidos.",
                "accion": "Revisar netx360_download_*.json en data/_alerts/ de los ultimos dias "
                          "y/o correr dashboard_v2/ingest/netx360_auto.py manualmente.",
                "detail": stale,
            }, f, indent=2, ensure_ascii=False)
        print(f"  ALERTA stale -> {alert_file.name}: {list(stale.keys())}")


if __name__ == "__main__":
    main()
