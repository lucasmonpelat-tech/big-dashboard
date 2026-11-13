# -*- coding: utf-8 -*-
"""Baja los holdings actuales de DYNF (iShares U.S. Equity Factor Rotation Active ETF)
desde la pagina de iShares y deja el top 10 de la tarjeta / lookthrough al dia.

POR QUE EXISTE (2026-11-13, pedido de Lucas: "los holdings de DYNF desde la pagina
de iShares, sacalos de ahi una vez por mes")
-----------------------------------------------------------------------------------
DYNF es activo con rotacion de factores (turnover >100%/ano) y pesa ~13,6% del
sleeve Equity. Su top 10 estaba al 30-Jun (deck trimestral) y es ~1/3 de la
exposicion de BIG a AAPL/NVDA/MSFT/AMZN en el widget "BIG vs ACWI - Top 10 Lookthrough".

DE DONDE SALE: <pagina de producto>/latest-holdings.csv (mismo metodo que el ACWI;
la pagina de producto da 403 a GET directo, el CSV no). ID de producto 307283.

USO
---
    python scripts/fetch_dynf_holdings.py
    python scripts/fetch_dynf_holdings.py --check   # no escribe, solo reporta
Despues correr build_equity_lookthrough.py y acwi_overlap.py.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DESTINO = ROOT / "data" / "fund_holdings_full" / "DYNF.json"
TOP10 = ROOT / "data" / "fund_holdings_top10.json"

PRODUCT_URL = "https://www.ishares.com/us/products/307283/ishares-u-s-equity-factor-rotation-active-etf"
URL = PRODUCT_URL + "/latest-holdings.csv"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/csv,*/*",
    "Referer": PRODUCT_URL + "/",
}
MIN_EQUITIES = 150      # el fondo tiene ~270 (205 en Jun)
SUMA_MINIMA = 95.0
TOP_N = 10
MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
         "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def analizar(texto: str) -> dict:
    lineas = texto.splitlines()
    m = next((re.search(r'"([^"]+)"', l) for l in lineas if l.startswith("Fund Holdings as of")), None)
    if not m:
        raise ValueError("no encuentro 'Fund Holdings as of' en el CSV")
    f = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", m.group(1))
    if not f or f.group(1)[:3].lower() not in MESES:
        raise ValueError(f"fecha ilegible: {m.group(1)}")
    as_of = f"{f.group(3)}-{MESES[f.group(1)[:3].lower()]:02d}-{int(f.group(2)):02d}"
    i = next((k for k, l in enumerate(lineas) if l.startswith("Ticker,")), None)
    if i is None:
        raise ValueError("no encuentro la cabecera 'Ticker,' (¿cambio el formato?)")
    holdings, detalle = {}, {}
    for r in csv.DictReader(io.StringIO("\n".join(lineas[i:]))):
        if (r.get("Asset Class") or "").strip() != "Equity":
            continue
        tk = (r.get("Ticker") or "").strip()
        try:
            w = float((r.get("Weight (%)") or "0").replace(",", ""))
        except ValueError:
            continue
        if not tk or tk == "-":
            continue
        holdings[tk] = round(holdings.get(tk, 0) + w, 6)
        detalle.setdefault(tk, {"name": (r.get("Name") or "").strip(), "sector": (r.get("Sector") or "").strip(),
                                "location": (r.get("Location") or "").strip()})
    return {"as_of": as_of, "holdings": holdings, "detalle": detalle}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    print("[dynf] Descargando holdings de iShares...")
    try:
        r = requests.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        res = analizar(r.content.decode("utf-8-sig", errors="replace"))
    except (requests.RequestException, ValueError) as e:
        sys.exit(f"ERROR: {e}. Se conserva el archivo anterior.")

    h = res["holdings"]
    suma = round(sum(h.values()), 2)
    print(f"  as of {res['as_of']} | {len(h)} equities | pesos suman {suma}%")
    if len(h) < MIN_EQUITIES:
        sys.exit(f"ERROR: solo {len(h)} equities (esperaba >= {MIN_EQUITIES}). Se conserva el anterior.")
    if suma < SUMA_MINIMA:
        sys.exit(f"ERROR: pesos suman {suma}% (esperaba >= {SUMA_MINIMA}). Se conserva el anterior.")

    orden = sorted(h.items(), key=lambda kv: -kv[1])
    top = dict(orden[:TOP_N])
    cobertura = round(sum(top.values()), 2)
    print("  top 10: " + ", ".join(f"{t} {w:.2f}" for t, w in top.items()) + f"  (= {cobertura}%)")

    if DESTINO.exists():
        try:
            ant = json.loads(DESTINO.read_text(encoding="utf-8"))
            if ant.get("as_of") == res["as_of"]:
                print(f"  misma fecha ({ant['as_of']}): no hay nada nuevo.")
                return
        except Exception:
            pass
    if a.check:
        print("  --check: no se escribe nada.")
        return

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps({
        "_doc": "Top 10 de DYNF desde el CSV de holdings de iShares. Generado por scripts/fetch_dynf_holdings.py, NO editar a mano.",
        "ticker": "DYNF", "isin": "US09290C1036",
        "name": "iShares U.S. Equity Factor Rotation Active ETF",
        "as_of": res["as_of"], "generado": datetime.now().date().isoformat(),
        "source": "iShares latest-holdings.csv, producto 307283", "source_url": PRODUCT_URL,
        "n_equities_en_el_fondo": len(h), "suma_pesos_fondo": suma, "cobertura_pct": cobertura,
        "holdings": top, "detalle": {t: res["detalle"][t] for t in top},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  -> {DESTINO.relative_to(ROOT)}")

    doc = json.loads(TOP10.read_text(encoding="utf-8"))
    e = doc.get("DYNF")
    if not isinstance(e, dict):
        print("  WARN: DYNF no esta en fund_holdings_top10.json")
        return
    e["_as_of"] = res["as_of"]
    e["source"] = (f"iShares latest-holdings.csv de DYNF al {res['as_of']} (top 10 = {cobertura}%, "
                   f"{len(h)} posiciones de renta variable). Automatico mensual: scripts/fetch_dynf_holdings.py.")
    e["_factsheet_top10"] = {t: round(w, 2) for t, w in top.items()}
    e["_factsheet_top10"]["_note"] = ("Derivado de data/fund_holdings_full/DYNF.json por "
                                      "scripts/fetch_dynf_holdings.py. No editar a mano.")
    doc["DYNF"] = e
    TOP10.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  tarjeta DYNF sincronizada al {res['as_of']}")


if __name__ == "__main__":
    main()
