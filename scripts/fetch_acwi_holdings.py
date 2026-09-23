# -*- coding: utf-8 -*-
"""Baja el CSV de holdings de ACWI (iShares) que usa el overlap del sleeve Equity.

POR QUE EXISTE (2026-09-23)
---------------------------
data/acwi_holdings/acwi_holdings.csv se bajaba A MANO. La copia que habia era de
Abril-2026: cinco meses de pesos del indice congelados, contra los que se comparaba
la cartera todos los dias. El archivo declaraba su fecha, asi que no mentia, pero
nadie lo iba a refrescar.

Ojo con la URL: la pagina de producto de iShares responde 403 a un GET directo, y
el `.ajax?fileType=csv` que se ve en otros ETF devuelve el HTML de la pagina. La
que funciona es la ruta limpia `latest-holdings.csv`, que se saca de los links de
la propia pagina.

QUE VALIDA ANTES DE PISAR EL ARCHIVO
------------------------------------
Un CSV que llega cortado o convertido en pagina de error es peor que uno viejo:
el overlap seguiria corriendo, con menos nombres y pesos que no suman. Entonces
se exige que tenga la fila de cabecera, una cantidad razonable de equities y que
los pesos sumen cerca de 100. Si algo no da, se conserva el que ya estaba.

USO
---
    python scripts/fetch_acwi_holdings.py
    python scripts/fetch_acwi_holdings.py --check   # no escribe, solo reporta
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DESTINO = ROOT / "data" / "acwi_holdings" / "acwi_holdings.csv"

URL = ("https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/"
       "latest-holdings.csv")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "text/csv,*/*",
    "Referer": "https://www.ishares.com/us/products/239600/ishares-msci-acwi-etf/",
}

MIN_EQUITIES = 1500      # ACWI tiene ~2200; menos que esto es un archivo cortado
SUMA_MINIMA = 95.0       # los pesos de equity suman ~99 (el resto es cash/derivados)


def analizar(texto: str) -> dict:
    """{as_of, n_equities, suma_pesos} o revienta con un motivo claro."""
    lineas = texto.splitlines()
    try:
        i = next(n for n, l in enumerate(lineas) if l.startswith("Ticker,"))
    except StopIteration:
        raise ValueError("no tiene la fila de cabecera 'Ticker,' — "
                         "seguro vino el HTML de la pagina, no el CSV")

    m = re.search(r'Fund Holdings as of,"([^"]+)"', texto)
    as_of = m.group(1) if m else None

    filas = list(csv.DictReader(io.StringIO("\n".join(lineas[i:]))))
    eq = [f for f in filas if (f.get("Asset Class") or "").strip() == "Equity"]
    suma = 0.0
    for f in eq:
        try:
            suma += float((f.get("Weight (%)") or "0").replace(",", ""))
        except ValueError:
            pass
    return {"as_of": as_of, "n_equities": len(eq), "suma_pesos": round(suma, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="No escribir, solo reportar.")
    a = ap.parse_args()

    print(f"[acwi] Descargando {URL}")
    try:
        r = requests.get(URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        sys.exit(f"ERROR: no pude bajar el CSV ({e}). Se conserva el que estaba.")

    texto = r.content.decode("utf-8-sig", errors="replace")
    try:
        info = analizar(texto)
    except ValueError as e:
        sys.exit(f"ERROR: {e}. Se conserva el que estaba.")

    print(f"  bajado: {len(r.content):,} bytes | as of {info['as_of']} | "
          f"{info['n_equities']} equities | pesos suman {info['suma_pesos']}%")

    if info["n_equities"] < MIN_EQUITIES:
        sys.exit(f"ERROR: solo {info['n_equities']} equities (esperaba >= {MIN_EQUITIES}): "
                 f"el archivo vino cortado. Se conserva el que estaba.")
    if info["suma_pesos"] < SUMA_MINIMA:
        sys.exit(f"ERROR: los pesos suman {info['suma_pesos']}% (esperaba >= {SUMA_MINIMA}): "
                 f"faltan holdings. Se conserva el que estaba.")

    if DESTINO.exists():
        anterior = analizar(DESTINO.read_text(encoding="utf-8-sig"))
        print(f"  el que habia: as of {anterior['as_of']} | {anterior['n_equities']} equities")
        if anterior["as_of"] == info["as_of"]:
            print("  misma fecha que el actual: no hay nada nuevo.")
            return

    if a.check:
        print("  --check: no se escribe nada.")
        return

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_bytes(r.content)
    print(f"  -> {DESTINO.relative_to(ROOT)}")
    print("  Correr despues scripts/acwi_overlap.py para rehacer el overlap.")


if __name__ == "__main__":
    main()
