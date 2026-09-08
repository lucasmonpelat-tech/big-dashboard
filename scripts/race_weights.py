"""
race_weights.py
===============
Un solo lugar para responder "cuanto pesa cada holding dentro de su sleeve".

POR QUE EXISTE (2026-09-08)
---------------------------
Los tres archivos *_race.json guardan `weight_pct` y `value_usd`, pero el unico
script que los escribia era el rebuild completo de cada sleeve (equity_race.py /
fi_race.py), borrados el 2026-08-20. Los scripts que quedaron en el cron solo
tocan retornos. Resultado: los pesos se congelaron mientras `refreshedAt` se
seguia actualizando todos los dias. El archivo PARECE fresco y no lo esta.

Ya rompio dos veces, las dos en FI:
    Ago-2026  PIMCO-LD/INC invertidos en el pie y en Holding Contributions.
              Se parcheo en el HTML, no en el origen.
    Sep-2026  volvio igual: fi_race decia LD 38.66% / INC 19.42% cuando la
              realidad era 28.56% / 29.08%, y el sleeve $10.35M contra $11.05M.

Parchear el consumidor no alcanza porque los race JSON los lee mas de un
consumidor. Por eso los pesos se re-derivan en el ORIGEN, y de una sola fuente:
el canonical, que es el mismo numero que ya muestra la tabla "Holdings del
Sleeve".

QUE NO HACE
-----------
No agrega ni saca holdings. Si un fondo esta en el canonical y no en el race
(o al reves), lo REPORTA y sigue: completar la lista implica reconstruir
anchors y retornos por fondo, que es trabajo del rebuild de cada sleeve, no de
un refresh diario. Inventar un holding con retornos en null corromperia
holdings_returns aguas abajo.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
CANONICAL_DIR = ROOT / "data" / "canonical"

# race JSON -> sleeve dentro de holdings_returns.json
SLEEVE_DE_RACE = {
    "equity_race.json": "equity",
    "fi_race.json": "fixed_income",
    "alts_race.json": "alternatives",
}


def pesos_canonical(sleeve_key):
    """({isin: mv}, {ticker: mv}, total, fecha) del ultimo snapshot canonical."""
    snaps = sorted(CANONICAL_DIR.glob("*/holdings_returns.json"))
    if not snaps:
        return {}, {}, 0.0, None
    doc = json.loads(snaps[-1].read_text(encoding="utf-8"))
    sleeve = (doc.get("sleeves") or {}).get(sleeve_key) or {}
    por_isin, por_ticker = {}, {}
    for h in sleeve.get("holdings", []):
        if (h.get("status") or "OPEN") != "OPEN" or not h.get("mv_usd"):
            continue
        if h.get("isin"):
            por_isin[h["isin"]] = h["mv_usd"]
        if h.get("ticker"):
            por_ticker[h["ticker"]] = h["mv_usd"]
    total = sum(por_ticker.values())
    return por_isin, por_ticker, total, doc.get("as_of")


def comparar(race, sleeve_key):
    """Compara los pesos del race contra el canonical SIN escribir nada.

    Devuelve un dict con:
      as_of        fecha del canonical usado
      total        MV del sleeve segun canonical
      filas        [(ticker, peso_race, peso_canonical, gap_pp)]
      sobran       tickers en el race que el canonical no tiene (posicion cerrada?)
      faltan       tickers en el canonical que el race no tiene (fondo nuevo?)
      isines       [(ticker, isin_race, isin_canonical)] cuando difieren
    """
    por_isin, por_ticker, total, fecha = pesos_canonical(sleeve_key)
    isin_canonical = {}
    snaps = sorted(CANONICAL_DIR.glob("*/holdings_returns.json"))
    if snaps:
        doc = json.loads(snaps[-1].read_text(encoding="utf-8"))
        for h in ((doc.get("sleeves") or {}).get(sleeve_key) or {}).get("holdings", []):
            if h.get("ticker") and h.get("isin"):
                isin_canonical[h["ticker"]] = h["isin"]

    filas, sobran, isines = [], [], []
    vistos = set()

    for h in race.get("holdings", []):
        tk = h.get("ticker")
        mv = por_isin.get(h.get("isin"))
        if mv is None:
            # No matcheo por ISIN pero si por ticker: el race tiene OTRO ISIN
            # para el mismo fondo. Hoy no rompe porque casi todo cruza por
            # ticker, pero cualquier consumidor que cruce por ISIN pierde el
            # holding en silencio. Paso con CALP: LU2837777825 (alta Maximus)
            # contra LU2827810776 (statement oficial de Carlyle).
            mv = por_ticker.get(tk)
            if mv is not None and tk in isin_canonical and h.get("isin"):
                isines.append((tk, h.get("isin"), isin_canonical[tk]))
        if mv is None:
            sobran.append(tk)
            continue
        vistos.add(tk)
        esperado = round(mv / total * 100, 2) if total else 0.0
        actual = h.get("weight_pct")
        gap = None if actual is None else round(actual - esperado, 2)
        filas.append((tk, actual, esperado, gap))

    faltan = [tk for tk in por_ticker if tk not in vistos]
    return {"as_of": fecha, "total": total, "filas": filas,
            "sobran": sobran, "faltan": faltan, "isines": isines}


def aplicar(race, sleeve_key, verbose=True):
    """Reescribe weight_pct/value_usd en el race desde el canonical. Devuelve el reporte."""
    r = comparar(race, sleeve_key)
    if not r["total"]:
        if verbose:
            print("  WARN: sin canonical — pesos sin tocar (mejor viejo que inventado).")
        return r

    por_isin, por_ticker, total, _ = pesos_canonical(sleeve_key)
    movidos = []
    for h in race.get("holdings", []):
        mv = por_isin.get(h.get("isin"))
        if mv is None:
            mv = por_ticker.get(h.get("ticker"))
        if mv is None:
            continue
        antes = h.get("weight_pct")
        ahora = round(mv / total * 100, 2)
        h["weight_pct"] = ahora
        h["value_usd"] = round(mv, 2)
        if antes is not None and abs(ahora - antes) >= 0.5:
            movidos.append(f"{h.get('ticker')} {antes:.2f}%->{ahora:.2f}%")

    race["_weights_source"] = f"canonical/{r['as_of']}/holdings_returns.json"

    if verbose:
        print(f"  Pesos desde canonical {r['as_of']}: sleeve ${total:,.2f}")
        if movidos:
            print(f"  Movimientos >=0.5pp: {', '.join(movidos)}")
        if r["sobran"]:
            print(f"  WARN: en el race pero NO en el canonical: {r['sobran']} "
                  f"(posicion cerrada? peso sin actualizar)")
        if r["faltan"]:
            print(f"  WARN: en el canonical pero NO en el race: {r['faltan']} "
                  f"(fondo nuevo — necesita el rebuild del sleeve, no este refresh)")
    return r
