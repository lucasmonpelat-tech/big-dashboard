"""
bench_series.py
===============
Serie base-100 de un benchmark de sleeve (ACWI para Equity, IUAG.L "AGG" para
FI) con UN PUNTO REAL POR DIA DE MERCADO, no solo fin de mes + hoy.

POR QUE (2026-10-14)
--------------------
Hasta hoy refresh_equity_daily / refresh_fi_daily bajaban solo el ultimo cierre
y lo escribian SOBRE el ultimo punto del mes (acwi[-1] = new). Resultado: la
serie guardaba un unico cierre real por mes (el de fin de mes) mas el de hoy, y
interpolate_equity_series.py rellenaba el medio con una recta. Septiembre-2026
tenia 1 solo punto real de ACWI. Consecuencias:
  - el alpha 1M/3M/6M de "Equity vs ACWI" y "FI vs AGG" se calculaba contra
    un benchmark inventado para la fecha de referencia;
  - la volatilidad / tracking error del benchmark salian de una recta.
Ahora cada corrida trae ~1 mes de cierres (yfinance) y los UPSERTea todos como
puntos reales; los dias sin mercado quedan interpolados entre reales vecinos.

CONVENCION DE FECHAS (no cambiar sin mirar los sleeves)
-------------------------------------------------------
Los sleeves (twr_series) etiquetan con la fecha de la CORRIDA un punto armado
con los cierres del dia habil ANTERIOR ("precios cierre anterior"). Para que
el benchmark quede alineado dia a dia con el portfolio, el cierre del dia X se
guarda con etiqueta X+1 (calendario). Es exactamente lo que producia la corrida
diaria de siempre (martes -> cierre del lunes etiquetado martes; sabado ->
cierre del viernes etiquetado sabado). El punto de "hoy" es el ultimo cierre
disponible, como antes.
"""
from __future__ import annotations

import math
from datetime import date, timedelta


def _ok(v) -> bool:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return not (math.isnan(v) or math.isinf(v)) and v > 0


def fetch_closes(ticker: str, period: str = "1mo") -> tuple[dict, str | None]:
    """{YYYY-MM-DD (fecha del cierre): close} solo con closes validos.
    Devuelve ({}, error) si yfinance no trae nada."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=period)
        if not len(hist):
            return {}, "sin datos"
        out = {}
        for idx, close in hist["Close"].items():
            if _ok(close):
                out[idx.date().isoformat()] = float(close)
        return out, (None if out else "todos los closes invalidos (NaN)")
    except Exception as e:
        return {}, str(e)[:60]


def _label(close_date_iso: str) -> str:
    """Etiqueta en la serie = fecha del cierre + 1 dia (ver docstring)."""
    return (date.fromisoformat(close_date_iso) + timedelta(days=1)).isoformat()


def upsert_bench_series(series: list[dict], closes: dict, today_iso: str) -> dict:
    """Inserta/actualiza como puntos REALES todos los cierres de `closes`
    (etiquetados close+1) hasta `today_iso` inclusive, y vuelve a interpolar
    los puntos marcados `interpolated` entre sus vecinos reales.

    Muta `series` en el lugar (lista de {date, price, index[, interpolated]}).
    Devuelve un resumen {"upserted": n, "reinterpolated": m, "last": {...}}.
    """
    if not series or not closes:
        return {"upserted": 0, "reinterpolated": 0, "last": series[-1] if series else None}
    base_price = series[0].get("price")
    if not _ok(base_price):
        return {"upserted": 0, "reinterpolated": 0, "last": series[-1], "error": "base_price invalido"}
    first_label = series[0]["date"]
    by_date = {p["date"]: p for p in series}

    upserted = 0
    for close_iso in sorted(closes):
        lab = _label(close_iso)
        if lab <= first_label or lab > today_iso:
            continue
        px = closes[close_iso]
        idx = round(px / base_price * 100, 4)
        p = by_date.get(lab)
        if p is None:
            p = {"date": lab}
            by_date[lab] = p
        changed = p.get("interpolated") or not _ok(p.get("price")) or abs(float(p["price"]) - px) > 1e-3
        p["price"] = round(px, 4)
        p["index"] = idx
        p.pop("interpolated", None)
        if changed:
            upserted += 1

    # Si hoy no tiene punto (ej. el ultimo cierre es de hace 2 dias), el punto
    # de hoy repite el ultimo cierre real, como hacia la corrida de siempre.
    hoy = by_date.get(today_iso)
    if today_iso > first_label and (hoy is None or hoy.get("interpolated")):
        reales = [p for p in by_date.values()
                  if p["date"] <= today_iso and not p.get("interpolated") and _ok(p.get("price"))]
        last_real = max(reales, key=lambda p: p["date"])
        by_date[today_iso] = {"date": today_iso, "price": last_real["price"], "index": last_real["index"]}

    ordered = [by_date[d] for d in sorted(by_date)]

    # Re-interpolar los puntos sinteticos entre vecinos reales (lineal en
    # price e index). Los que no tienen vecino real a ambos lados se dejan.
    reales = [p for p in ordered if not p.get("interpolated") and _ok(p.get("index"))]
    reinterp = 0
    for p in ordered:
        if not p.get("interpolated"):
            continue
        antes = [r for r in reales if r["date"] < p["date"]]
        despues = [r for r in reales if r["date"] > p["date"]]
        if not antes or not despues:
            continue
        a, b = antes[-1], despues[0]
        span = (date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days or 1
        t = (date.fromisoformat(p["date"]) - date.fromisoformat(a["date"])).days / span
        p["index"] = round(a["index"] + (b["index"] - a["index"]) * t, 4)
        p["price"] = round(a["price"] + (b["price"] - a["price"]) * t, 4)
        reinterp += 1

    series[:] = ordered
    return {"upserted": upserted, "reinterpolated": reinterp, "last": series[-1]}
