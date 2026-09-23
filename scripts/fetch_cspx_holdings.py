# -*- coding: utf-8 -*-
"""Baja el top 20 de CSPX (iShares Core S&P 500 UCITS) desde iShares.

POR QUE EXISTE (2026-09-23)
---------------------------
El overlap contra ACWI comparaba la cartera usando `fund_holdings_top10.json`,
que -- como dice el nombre -- tiene solo el top ~10 de cada fondo. De CSPX habia
11 nombres: el 39% del fondo. Todo lo que quedaba afuera contaba como CERO.

Se vio cuando Micron entro al top 10 de ACWI: figuraba con BIG 0.00% aunque lo
tenemos via CSPX. El underweight salia sobreestimado para cualquier nombre del
indice que no estuviera en el top de alguno de nuestros fondos. Pedido de Lucas:
cargar mas profundidad de CSPX, que es el 32.6% del sleeve y el que mas mueve la
aguja.

CUANTO SE GUARDA: se bajan los ~500 holdings (hace falta para validar que el
archivo venga entero) y se guardan los primeros TOP_N=20 -- pedido de Lucas:
"solo necesito top 10 o 20". Guardar los 504 no aportaba: todos los nombres del
top 10 de ACWI que existen en el S&P 500 caen dentro del top 9 de CSPX.

Los otros fondos siguen con su top 10 del factsheet: son activos y no publican
la cartera entera.

DE DONDE SALE
-------------
La pagina UK de iShares no expone un CSV de holdings como la de EE.UU. El boton
"Detailed Holdings and Analytics" pega contra una API interna que devuelve la
cartera completa en columnas paralelas. Esa es la que se usa aca.

El parametro asOfDate se omite a proposito: sin el, la API devuelve la ultima
fecha publicada. Fijarlo seria congelar el archivo, que es justo el problema que
esto viene a resolver.

USO
---
    python scripts/fetch_cspx_holdings.py
    python scripts/fetch_cspx_holdings.py --check   # no escribe, solo reporta
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
DESTINO = ROOT / "data" / "fund_holdings_full" / "CSPX.json"

PRODUCT_URL = ("https://www.ishares.com/uk/individual/en/products/253743/"
               "ishares-sp-500-b-ucits-etf-acc-fund")
API = ("https://www.ishares.com/varnish-api/uk-retail01-product-data/product-data/api/v2/"
       "get-product-data?appSubType=ISHARES&appType=PRODUCT_PAGE&component=holdings.all"
       "&locale=en_GB&portfolioId=253743&targetSite=ishares-uk&userType=individual"
       "&excludeContent=true&includeConfig=true")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept": "application/json,*/*",
    "Referer": PRODUCT_URL,
}

# El S&P 500 tiene ~500 nombres (algo mas por clases duales tipo GOOGL/GOOG).
# Se BAJAN todos -- hace falta para validar que el archivo venga completo -- pero
# se GUARDAN solo los primeros TOP_N.
MIN_HOLDINGS = 400
SUMA_MINIMA = 95.0

# Cuantos holdings se guardan (decision de Lucas, 2026-09-23: "solo necesito top
# 10 o 20"). Guardar los 504 no aportaba nada: el overlap compara contra el top
# 10 de ACWI, y TODOS esos nombres que existen en el S&P 500 caen dentro del top
# 9 de CSPX. 20 deja margen por si el indice rota.
#
# El limite: un nombre del top 10 de ACWI que en CSPX estuviera mas abajo del
# puesto 20 contaria CERO. Hoy no pasa con ninguno. El unico que no aparece es
# Taiwan Semi, y no por profundidad sino porque no es del S&P 500.
TOP_N = 20

MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
         "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _fecha_iso(formateada: str) -> str | None:
    """'22/Sept/2026' -> '2026-09-22'."""
    m = re.match(r"(\d{1,2})/([A-Za-z]+)/(\d{4})", (formateada or "").strip())
    if not m:
        return None
    dia, mes, anio = m.groups()
    n = MESES.get(mes[:3].lower())
    return f"{anio}-{n:02d}-{int(dia):02d}" if n else None


def _columna(dp: dict, nombre: str) -> list:
    """La API devuelve columnas paralelas: cada campo es una lista alineada."""
    bloque = dp.get(nombre) or {}
    v = bloque.get("value")
    if not isinstance(v, list):
        v = bloque.get("formattedValue")
    return v if isinstance(v, list) else []


def bajar() -> dict:
    r = requests.get(API, headers=HEADERS, timeout=60)
    r.raise_for_status()
    d = r.json()
    try:
        cont = d["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]
        dp = cont["dataPointsByNameMap"]
    except (KeyError, TypeError):
        raise ValueError("la API respondio con otra estructura — reviso iShares el formato?")

    as_of = _fecha_iso((dp.get("asOfDate") or {}).get("formattedValue", ""))
    tickers = _columna(dp, "ticker")
    pesos = _columna(dp, "holdingPercent")
    clases = _columna(dp, "assetClass")
    nombres = _columna(dp, "issueName")
    sectores = _columna(dp, "sectorName")

    if not tickers or len(tickers) != len(pesos):
        raise ValueError(f"columnas desalineadas: {len(tickers)} tickers vs {len(pesos)} pesos")

    holdings, detalle = {}, {}
    for i, tk in enumerate(tickers):
        if (clases[i] if i < len(clases) else "") != "Equity":
            continue                      # fuera cash, futuros y colaterales
        tk = (tk or "").strip()
        if not tk or tk == "-":
            continue
        try:
            w = float(pesos[i])
        except (TypeError, ValueError):
            continue
        # Un ticker puede venir en dos lineas: se acumulan, no se pisan.
        holdings[tk] = round(holdings.get(tk, 0) + w, 6)
        detalle.setdefault(tk, {"name": nombres[i] if i < len(nombres) else "",
                                "sector": sectores[i] if i < len(sectores) else ""})

    return {"as_of": as_of, "fondo": d.get("fundName"), "moneda": d.get("currencyCode"),
            "holdings": holdings, "detalle": detalle}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="No escribir, solo reportar.")
    a = ap.parse_args()

    print("[cspx] Descargando holdings de iShares...")
    try:
        r = bajar()
    except (requests.RequestException, ValueError) as e:
        sys.exit(f"ERROR: {e}. Se conserva el archivo anterior.")

    h = r["holdings"]
    suma = round(sum(h.values()), 2)
    print(f"  {r['fondo']} | as of {r['as_of']} | {len(h)} holdings | pesos suman {suma}%")

    if len(h) < MIN_HOLDINGS:
        sys.exit(f"ERROR: solo {len(h)} holdings (esperaba >= {MIN_HOLDINGS}). "
                 f"Se conserva el anterior.")
    if suma < SUMA_MINIMA:
        sys.exit(f"ERROR: los pesos suman {suma}% (esperaba >= {SUMA_MINIMA}). "
                 f"Se conserva el anterior.")

    ordenados = sorted(h.items(), key=lambda kv: -kv[1])
    print("  top 5: " + ", ".join(f"{t} {w:.2f}%" for t, w in ordenados[:5]))
    guardados = dict(ordenados[:TOP_N])
    cobertura = round(sum(guardados.values()), 2)
    print(f"  se guardan los primeros {len(guardados)}: {cobertura}% del fondo")

    if DESTINO.exists():
        try:
            ant = json.loads(DESTINO.read_text(encoding="utf-8"))
            print(f"  el que habia: as of {ant.get('as_of')} | "
                  f"{len(ant.get('holdings') or {})} holdings guardados")
            if ant.get("as_of") == r["as_of"]:
                print("  misma fecha: no hay nada nuevo.")
                return
        except Exception:
            pass

    if a.check:
        print("  --check: no se escribe nada.")
        return

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps({
        "_doc": (f"Top {TOP_N} de CSPX, para el overlap contra ACWI. Se bajan los ~500 "
                 "holdings del fondo (para validar que el archivo venga completo) y se "
                 "guardan los primeros: todos los nombres del top 10 de ACWI que existen "
                 "en el S&P 500 caen dentro del top 9 de CSPX. Un nombre de ACWI que en "
                 "CSPX estuviera debajo del puesto 20 contaria cero. "
                 "Generado por scripts/fetch_cspx_holdings.py, NO editar a mano."),
        "ticker": "CSPX",
        "isin": "IE00B5BMR087",
        "name": r["fondo"],
        "moneda": r["moneda"],
        "as_of": r["as_of"],
        "generado": datetime.now().date().isoformat(),
        "source": "iShares product-data API (holdings.all), portfolioId 253743",
        "source_url": PRODUCT_URL,
        "n_holdings_guardados": len(guardados),
        "cobertura_pct": cobertura,
        "n_holdings_en_el_fondo": len(h),
        "suma_pesos_fondo": suma,
        "holdings": guardados,
        "detalle": {tk: r["detalle"][tk] for tk in guardados if tk in r["detalle"]},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  -> {DESTINO.relative_to(ROOT)}")
    sincronizar_top10(h, r["as_of"])
    print("  Correr despues scripts/acwi_overlap.py para rehacer el overlap.")


def sincronizar_top10(holdings: dict, as_of: str) -> None:
    """Deja el top 10 de la tarjeta de CSPX derivado de la cartera completa.

    POR QUE: la tarjeta "Top 10 por Fondo" sale de fund_holdings_top10.json, que
    se carga aparte. Con la cartera completa cargada, CSPX pasaba a tener DOS
    fuentes: la tarjeta mostraba Jul-2026 (NVDA 7.54%) y el calculo de exposicion
    usaba Sep-2026 (8.26%). El mismo fondo con dos numeros distintos en la misma
    pantalla es lo que venimos sacando de todos lados.

    Con esto hay un solo escritor: el top 10 de la tarjeta se DERIVA de la
    cartera completa. Los otros fondos no se tocan -- se siguen cargando a mano
    del factsheet, porque no publican la cartera entera.
    """
    p = ROOT / "data" / "fund_holdings_top10.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  WARN: no pude actualizar el top 10 de la tarjeta ({e})")
        return

    top = dict(sorted(holdings.items(), key=lambda kv: -kv[1])[:10])
    entrada = doc.get("CSPX")
    if not isinstance(entrada, dict):
        print("  WARN: CSPX no esta en fund_holdings_top10.json, no se toca")
        return

    entrada["_as_of"] = as_of
    entrada["_factsheet_top10"] = {tk: round(w, 2) for tk, w in top.items()}
    entrada["_factsheet_top10"]["_note"] = (
        "Derivado de data/fund_holdings_full/CSPX.json por "
        "scripts/fetch_cspx_holdings.py. No editar a mano.")
    doc["CSPX"] = entrada
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  tarjeta CSPX sincronizada: top 10 al {as_of}")


if __name__ == "__main__":
    main()
