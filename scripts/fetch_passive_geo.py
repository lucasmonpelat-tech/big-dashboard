# -*- coding: utf-8 -*-
"""
fetch_passive_geo.py
====================
Baja los holdings de los ETFs PASIVOS del Equity sleeve desde iShares y deja en cada ficha
(data/funds/<TICKER>.json -> countries) el peso EXACTO por pais (campo "Location" del CSV de holdings,
equity normalizado a 100). Alimenta la estimacion semanal del regional (scripts/regional_rollforward.py).

POR QUE (2026-11-17, pedido de Lucas: "como hacemos para que el calculo sea lo mas exacto posible")
---------------------------------------------------------------------------------------------------
Las fichas de EMXC e ILF tenian paises APROXIMADOS (EMXC: Taiwan 27 / India 21 / Korea 19...; el real al
16-Nov es Taiwan 34 / Korea 22 / India 17). Con el CSV de holdings se suma posicion por posicion.

FONDOS
  EMXC  iShares MSCI EM ex China      CSV propio (producto 288504)
  ILF   iShares Latin America 40      CSV propio (producto 239761)
  DYNF  iShares US Equity Factor Rot. CSV propio (producto 307283)
  CSPX  iShares Core S&P 500 UCITS    se usa el CSV de IVV (mismo indice, producto 239726): PROXY
  HEWJ  (no se baja) = EWJ + forwards: Japon 100% por look-through. El CSV dice "United States" porque
        el fondo tiene el ETF EWJ listado en NYSE: NO usar su Location.
  ARGT, MAGS: Global X, por definicion Argentina / EE.UU. (sin cambios en la ficha).

Si un fondo falla (403, formato distinto, suma < 95%) se conserva la ficha anterior. Idempotente.

Uso:  python scripts/fetch_passive_geo.py [--check]
"""
from __future__ import annotations
import argparse, csv, io, json, re, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
FUNDS = ROOT / "data" / "funds"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"), "Accept": "text/csv,*/*"}
MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

# ficha -> (url base, nombre de la columna de peso, nota)
FONDOS = {
    "EMXC": ("https://www.ishares.com/us/products/288504/ishares-msci-emerging-markets-ex-china-etf", "Weight (%)", ""),
    "ILF":  ("https://www.ishares.com/us/products/239761/ishares-latin-america-40-etf", "Weight (%)", ""),
    "DYNF": ("https://www.ishares.com/us/products/307283/ishares-u-s-equity-factor-rotation-active-etf", "Weight (%)", ""),
    "CSPX": ("https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf", "Market Weight",
             "PROXY: CSV de IVV (iShares Core S&P 500 ETF), mismo indice que CSPX (UCITS); el UCITS no publica Location."),
}
CODIGOS = {
    "United States": "US", "Canada": "CA", "United Kingdom": "UK", "Japan": "JP", "Germany": "DE", "France": "FR",
    "Netherlands": "NL", "Switzerland": "CH", "Spain": "ES", "Italy": "IT", "Sweden": "SE", "Denmark": "DK",
    "Norway": "NO", "Finland": "FI", "Belgium": "BE", "Ireland": "IE", "Austria": "AT", "Portugal": "PT",
    "Taiwan": "TW", "Korea (South)": "KR", "India": "IN", "China": "CN", "Thailand": "TH", "Malaysia": "MY",
    "Indonesia": "ID", "Philippines": "PH", "Brazil": "BR", "Mexico": "MX", "Chile": "CL", "Colombia": "CO",
    "Peru": "PE", "Argentina": "AR", "South Africa": "ZA", "Saudi Arabia": "SA", "United Arab Emirates": "AE",
    "Poland": "PL", "Greece": "GR", "Kuwait": "KW", "Qatar": "QA", "Turkey": "TR", "Hungary": "HU",
    "Czech Republic": "CZ", "Egypt": "EG", "Russian Federation": "RU",
}


def _f(s) -> float:
    try:
        return float((s or "").replace(",", ""))
    except ValueError:
        return 0.0


def bajar(base: str, col_peso: str):
    r = requests.get(base + "/latest-holdings.csv", headers={**HEADERS, "Referer": base + "/"}, timeout=60)
    r.raise_for_status()
    lineas = r.content.decode("utf-8-sig", errors="replace").splitlines()
    m = next((re.search(r'"([^"]+)"', l) for l in lineas if l.startswith("Fund Holdings as of")), None)
    f = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", m.group(1)) if m else None
    if not f:
        raise ValueError("sin fecha 'Fund Holdings as of'")
    as_of = f"{f.group(3)}-{MESES[f.group(1)[:3].lower()]:02d}-{int(f.group(2)):02d}"
    i = next((k for k, l in enumerate(lineas) if l.startswith("Ticker,")), None)
    if i is None:
        raise ValueError("sin cabecera 'Ticker,'")
    pesos: dict[str, float] = {}
    n = 0
    for row in csv.DictReader(io.StringIO("\n".join(lineas[i:]))):
        if (row.get("Asset Class") or "").strip() != "Equity":
            continue
        n += 1
        loc = (row.get("Location") or "").strip()
        pesos[loc] = pesos.get(loc, 0.0) + _f(row.get(col_peso))
    total = sum(pesos.values())
    if n < 20 or total < 95:
        raise ValueError(f"archivo incompleto ({n} equities, suma {total:.1f}%)")
    return as_of, n, total, pesos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    fallos = 0
    for tk, (base, col, nota) in FONDOS.items():
        try:
            as_of, n, total, pesos = bajar(base, col)
        except Exception as e:
            print(f"[{tk}] ERROR: {e}. Se conserva la ficha anterior.")
            fallos += 1
            continue
        paises: dict[str, float] = {}
        for loc, w in pesos.items():
            cod = CODIGOS.get(loc, "OTHER")
            paises[cod] = paises.get(cod, 0.0) + w / total * 100
        paises = {k: round(v, 2) for k, v in sorted(paises.items(), key=lambda kv: -kv[1]) if v >= 0.005}
        resto = round(100 - sum(paises.values()), 2)
        if abs(resto) >= 0.01:
            paises["OTHER"] = round(paises.get("OTHER", 0) + resto, 2)
        top = ", ".join(f"{k} {v}" for k, v in list(paises.items())[:6])
        print(f"[{tk}] al {as_of}: {n} equities | {top}")
        if a.check:
            continue
        p = FUNDS / f"{tk}.json"
        ficha = json.loads(p.read_text(encoding="utf-8"))
        ficha["countries"] = paises
        ficha["countries_de_factsheet"] = True
        ficha["countries_as_of"] = as_of
        ficha["countries_nota"] = (f"EXACTO: suma posicion por posicion del CSV de holdings de iShares (campo Location) al {as_of}, "
                                   f"{n} acciones, normalizado a 100. Generado por scripts/fetch_passive_geo.py. {nota}").strip()
        p.write_text(json.dumps(ficha, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.exit(1 if fallos == len(FONDOS) else 0)


if __name__ == "__main__":
    main()
