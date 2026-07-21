"""
snapshot_year_start_prices.py
==============================
Fase A del fix YTD del race:
Guarda snapshot de precios de cada fondo al 31-Dec del anio actual.
Se corre 1 vez al ano (31-Dec o 1-Ene).

Uso:
    # Guardar snapshot del 31-Dec-2026 (para YTD 2027)
    python scripts/snapshot_year_start_prices.py --year 2026

    # O correr automatico el 1-Ene con --auto (usa año anterior)
    python scripts/snapshot_year_start_prices.py --auto

Actualiza year_start_anchors.json agregando `anchors_YYYY+1` con precios.
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path("C:/Users/lmonp/OneDrive/Desktop/Code/big-dashboard/data")
ANCHORS = ROOT / "year_start_anchors.json"
UCITS_NAV = ROOT / "ucits_daily_nav.json"
POSITIONS = ROOT / "positions_latest.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="Anio del snapshot (ej 2026 para YTD 2027)")
    ap.add_argument("--auto", action="store_true", help="Usar year = current - 1 (default para cron 1-Ene)")
    args = ap.parse_args()

    if args.auto:
        year = date.today().year - 1
    elif args.year:
        year = args.year
    else:
        raise ValueError("Especificar --year o --auto")

    print(f"[{datetime.now().isoformat(timespec='seconds')}] Snapshot precios 31-Dec-{year}")

    # 1) Leer anchors actuales
    anchors_all = json.loads(ANCHORS.read_text(encoding="utf-8"))
    new_key = f"anchors_{year+1}"

    # 2) Leer UCITS NAV (baha) para tener precios T-1
    ucits = json.loads(UCITS_NAV.read_text(encoding="utf-8"))
    navs = ucits.get("navs", {})

    # 3) Leer Pershing positions para tener precios de ETFs listados
    positions = json.loads(POSITIONS.read_text(encoding="utf-8"))
    ticker_to_price = {}
    for p in positions.get("positions", []):
        ticker = p.get("ticker")
        price = p.get("price")
        if ticker and price:
            ticker_to_price[ticker] = price

    # 4) Construir snapshot combinando fuentes
    #    Prioridad: baha (para UCITS) > Pershing (para ETFs US listados)
    ticker_to_isin = {info["ticker"]: isin for isin, info in
                      anchors_all.get("anchors_2026", {}).items()}

    snapshot = {}
    for isin, info in anchors_all.get("anchors_2026", {}).items():
        ticker = info["ticker"]
        price = None
        source = None
        # Priorizar baha si es UCITS
        if isin in navs and "nav" in navs[isin]:
            price = navs[isin]["nav"]
            source = "baha"
        # Fallback: Pershing precio T-1
        elif ticker in ticker_to_price:
            price = ticker_to_price[ticker]
            source = "pershing"
        snapshot[isin] = {
            "ticker": ticker,
            "name": info["name"],
            "price_dec_31": price,
            "source": source,
            "snapshot_date": f"{year}-12-31",
        }
        print(f"  {ticker}: {price} ({source})")

    # 5) Guardar
    if new_key in anchors_all:
        print(f"  WARN: {new_key} ya existia, sobreescribiendo")
    anchors_all[new_key] = snapshot
    anchors_all["_updated"] = datetime.now().isoformat()

    ANCHORS.write_text(
        json.dumps(anchors_all, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nGuardado en {ANCHORS.name}: key '{new_key}'")


if __name__ == "__main__":
    main()
