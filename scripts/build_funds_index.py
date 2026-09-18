# -*- coding: utf-8 -*-
"""data/funds/*.json -> data/funds_index.json. La unica lectura de las fichas.

POR QUE EXISTE (2026-09-18)
---------------------------
Los datos de cada fondo vivian en TRES lugares, cargados a mano por separado:

  data/funds/<TICKER>.json   slide 10, factsheet, 9 scripts
  data/funds_metadata.js     tab Geography (CURRENT_YIELD, COUNTRY_EXPOSURE)
  data/factsheets_scraped/   un script de junio que ya no corria

y no coincidian. PIMCO Income: 4.57% en uno, 4.38% en el otro. Schroder Cat
Bond: 9.7% vs 7.8%. Y los paises del tab eran estimaciones redondas a mano
(PIMCO Income "US 60%") mientras el factsheet decia 91.57% -- el dato bueno
estaba cargado en el otro archivo y nadie lo leia.

Ahora hay UNA ficha por fondo (data/funds/<TICKER>.json), que sale del
factsheet que Lucas sube a Research Fondos. Este script es el unico que sabe
interpretarlas; el tab y el validador le preguntan a el.

REGLAS
------
Yield, segun el tipo de activo (decision de Lucas 2026-09-18):
  Renta fija     YTM = fi_metrics.ytw. El MISMO campo que usa la slide 10: no
                 se guarda dos veces, asi no hay forma de que diverjan.
  Resto          el bloque "yield" de la ficha: dividend yield (renta
                 variable), distribution rate (alternativos), N/A (PE iliquido).
  Sin numero     "valor": null con un tipo que lo explica (GAM: "Ref. Rate +
                 4.88%"). NUNCA se inventa.

Paises: la ficha los guarda como vienen (refresh_pimco.py escribe nombres
completos, las estimaciones previas usan codigos). Aca se normalizan a codigo.
Si una ficha trae solo el top-N del factsheet, el resto va a OTHER para que
sume 100 y el grafico no infle a los que si estan.

Cada dato lleva de_factsheet: el tab muestra cuanto del portfolio todavia
descansa en estimaciones sin respaldo.

USO
---
    python scripts/build_funds_index.py            # escribe data/funds_index.json
    python scripts/build_funds_index.py --check    # solo reporta
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
FUNDS_DIR = ROOT / "data" / "funds"
INDEX = ROOT / "data" / "funds_index.json"

# Nombre del factsheet -> el codigo que usa el tab (y su paleta de colores).
NOMBRE_A_CODIGO = {
    "united states": "US", "usa": "US", "u.s.": "US",
    "united kingdom": "UK", "great britain": "UK",
    "germany": "DE", "france": "FR", "spain": "ES", "italy": "IT",
    "netherlands": "NL", "switzerland": "CH", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "ireland": "IE", "belgium": "BE", "austria": "AT",
    "finland": "FI", "portugal": "PT", "luxembourg": "LU",
    "czech republic": "CZ", "poland": "PL", "hungary": "HU", "romania": "RO",
    "japan": "JP", "china": "CN", "hong kong": "HK", "taiwan": "TW",
    "south korea": "KR", "korea": "KR", "india": "IN", "indonesia": "ID",
    "malaysia": "MY", "thailand": "TH", "philippines": "PH", "singapore": "SG",
    "vietnam": "VN", "australia": "AU", "new zealand": "NZ",
    "canada": "CA", "mexico": "MX", "brazil": "BR", "chile": "CL",
    "colombia": "CO", "peru": "PE", "argentina": "AR", "uruguay": "UY",
    "south africa": "ZA", "turkey": "TR", "israel": "IL", "egypt": "EG",
    "saudi arabia": "SA", "united arab emirates": "AE", "qatar": "QA",
    "russia": "RU", "nigeria": "NG",
}

# Codigos que no son un pais pero que el tab ya sabe mostrar.
AGREGADOS = {"OTHER", "GLOBAL", "EM", "EU", "LatAm"}

TOL = 1.5  # misma tolerancia que usa el validador para exposiciones


def codigo(nombre: str) -> str | None:
    """Codigo del pais, o None si no se reconoce."""
    n = (nombre or "").strip()
    if n in AGREGADOS or (len(n) == 2 and n.isupper()):
        return n
    return NOMBRE_A_CODIGO.get(n.lower())


def cargar_fichas() -> list[dict]:
    fichas = []
    for p in sorted(FUNDS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            sys.exit(f"ERROR: {p.name} no es JSON valido ({e})")
        d["_archivo"] = p.name
        fichas.append(d)
    return fichas


def resolver_yield(d: dict) -> dict:
    fm = d.get("fi_metrics") or {}
    if d.get("sleeve") == "Fixed Income" and fm.get("ytw") is not None:
        return {
            "valor": fm["ytw"],
            "tipo": "YTM",
            "as_of": d.get("as_of_factsheet"),
            "fuente": d.get("source") or d["_archivo"],
            "de_factsheet": True,
        }
    y = d.get("yield")
    if y:
        return {k: y.get(k) for k in ("valor", "tipo", "as_of", "fuente", "de_factsheet", "nota")}
    return {"valor": None, "tipo": "sin dato", "as_of": None,
            "fuente": None, "de_factsheet": False}


def resolver_paises(d: dict) -> tuple[list, list]:
    """([{c, p}], [nombres que no se pudieron mapear])."""
    crudos = d.get("countries") or {}
    agregado, sin_mapear = {}, []
    for nombre, pct in crudos.items():
        c = codigo(nombre)
        if c is None:
            sin_mapear.append(nombre)
            c = "OTHER"
        agregado[c] = agregado.get(c, 0) + pct
    total = sum(agregado.values())
    # Fichas con solo el top-N del factsheet: el resto es OTHER, no se pierde.
    if agregado and total < 100 - TOL:
        agregado["OTHER"] = agregado.get("OTHER", 0) + (100 - total)
    lista = [{"c": c, "p": round(p, 2)} for c, p in
             sorted(agregado.items(), key=lambda x: -x[1])]
    return lista, sin_mapear


def construir() -> tuple[dict, list]:
    index, avisos = {}, []
    for d in cargar_fichas():
        isin = d.get("isin")
        if not isin:
            avisos.append(f"{d['_archivo']}: sin ISIN, no se puede indexar")
            continue
        paises, sin_mapear = resolver_paises(d)
        for n in sin_mapear:
            avisos.append(f"{d['_archivo']}: pais '{n}' sin codigo, se agrupo en OTHER")
        index[isin] = {
            "ticker": d.get("ticker"),
            "name": d.get("name"),
            "sleeve": d.get("sleeve"),
            "archivo": d["_archivo"],
            "as_of_factsheet": d.get("as_of_factsheet"),
            "yield": resolver_yield(d),
            "countries": paises,
            "countries_de_factsheet": bool(d.get("countries_de_factsheet")),
            "countries_as_of": d.get("countries_as_of"),
            "countries_nota": d.get("countries_nota"),
        }
    return index, avisos


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="No escribir, solo reportar.")
    a = ap.parse_args()

    index, avisos = construir()
    sin_resp_y = [v["ticker"] for v in index.values() if not v["yield"].get("de_factsheet")]
    sin_resp_p = [v["ticker"] for v in index.values()
                  if v["countries"] and not v["countries_de_factsheet"]]

    print(f"funds_index: {len(index)} fichas")
    print(f"  yield sin factsheet  ({len(sin_resp_y)}): {', '.join(sorted(sin_resp_y))}")
    print(f"  paises sin factsheet ({len(sin_resp_p)}): {', '.join(sorted(sin_resp_p))}")
    for av in avisos:
        print(f"  WARN: {av}")

    if a.check:
        return
    INDEX.write_text(json.dumps({
        "_doc": ("Generado por scripts/build_funds_index.py desde data/funds/*.json. "
                 "NO editar a mano: se pisa en cada corrida. Para cambiar un dato, "
                 "editar la ficha del fondo."),
        "generado": date.today().isoformat(),
        "fondos": index,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  -> {INDEX.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
