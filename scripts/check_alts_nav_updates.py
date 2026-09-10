# -*- coding: utf-8 -*-
"""Avisa cuando Pershing re-marca el NAV de un alternativo iliquido.

QUE RESUELVE (2026-09-10)
-------------------------
Los privados del sleeve Alts no cotizan: Pershing los re-marca cada tanto, sin
avisar y sin periodicidad fija. Hasta ahora la unica forma de enterarse era
abrir el dashboard y notar que un numero se movio. Pedido de Lucas: que avise
solo.

QUE MIRA Y QUE NO
-----------------
Entran los iliquidos: private credit, infraestructura y private equity.

Quedan AFUERA, a proposito:
  - IBIT y GLD  -> son ETF liquidos, se mueven todos los dias. Avisar de eso
                   seria ruido puro y la alarma se volveria ignorable.
  - CALP        -> no viene de Pershing. Se carga a mano desde los statements de
                   Carlyle, y para eso ya esta el check 4 del validador.

CADA FONDO AVISA DISTINTO, Y AHI ESTA LA GRACIA
-----------------------------------------------
No se puede usar la misma senal para todos:

  BPCC   price_date avanza CASI TODOS LOS DIAS pero el precio se queda quieto
         semanas (129.34 desde el 24-Ago, 130.25 desde el 28-Ago). Vigilar la
         fecha daria una falsa alarma diaria.

  FLEX   el precio si cambia con la re-marca (31.43 -> 31.77 el 29-Ago). Pero su
         MV tambien cambio el 08-Sep SIN re-marca, porque entro una compra nueva.
         Mirar el MV a secas confundiria las dos cosas.

  GCRED  no tienen precio: Pershing los reporta solo con un valor estimado, y la
  HLEND  "cantidad" ES el valor (qty == mv). Ahi la unica senal posible es el MV.

Entonces: se mira el PRECIO en los que tienen precio, y el MV en los que no. Un
cambio de cantidad sin cambio de precio es una compra o una venta, no una
re-marca, y se reporta aparte para no mezclarlo.

USO
---
    python scripts/check_alts_nav_updates.py
    python scripts/check_alts_nav_updates.py --desde 2026-08-01   # historico
    python scripts/check_alts_nav_updates.py --alerta data/_alerts/...json

Exit code 1 si hubo alguna re-marca (para que el step del cron lo detecte).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
CANONICAL = ROOT / "data" / "canonical"

# Liquidos: cotizan todos los dias. Si entraran, la alarma sonaria siempre.
LIQUIDOS = {"IBIT": "ETF de Bitcoin, cotiza a diario",
            "GLD": "ETF de oro, cotiza a diario"}

# Cuanto tiene que moverse para avisar. 0.01% filtra el ruido de redondeo sin
# tapar una re-marca real: la de FLEX fue 1.08% y la de BPCC 0.70%.
UMBRAL_PCT = 0.01


def snapshots():
    return sorted(p.parent.name for p in CANONICAL.glob("*/positions.json"))


def universo():
    """{pershing_id: ticker} de los alternativos iliquidos que vienen de Pershing."""
    hrs = sorted(CANONICAL.glob("*/holdings_returns.json"))
    if not hrs:
        return {}, []
    doc = json.loads(hrs[-1].read_text(encoding="utf-8"))
    alts = (doc.get("sleeves") or {}).get("alternatives") or {}
    ids, excluidos = {}, []
    for h in alts.get("holdings", []):
        tk = h.get("ticker")
        if (h.get("status") or "OPEN") != "OPEN":
            continue
        if tk in LIQUIDOS:
            excluidos.append((tk, LIQUIDOS[tk]))
            continue
        if h.get("_mv_source") == "external_statement":
            excluidos.append((tk, "no viene de Pershing: statement manual (check 4 del validador)"))
            continue
        pid = h.get("pershing_id")
        if pid:
            ids[pid] = tk
        else:
            excluidos.append((tk, "sin pershing_id — no se puede seguir en el feed"))
    return ids, excluidos


def foto(fecha, ids):
    """{ticker: {precio, price_date, mv, qty}} de ese snapshot."""
    f = CANONICAL / fecha / "positions.json"
    if not f.exists():
        return {}
    d = json.loads(f.read_text(encoding="utf-8"))
    out = {}
    for h in d.get("holdings", []):
        tk = ids.get(h.get("security_id"))
        if not tk:
            continue
        out[tk] = {
            "precio": h.get("market_price_ccy"),
            "price_date": h.get("price_date"),
            "mv": h.get("market_value_usd"),
            "qty": h.get("quantity"),
        }
    return out


def variacion(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b - a) / abs(a) * 100


def comparar(ant, act):
    """(remarcas, movimientos_de_cantidad) entre dos fotos."""
    remarcas, cantidades = [], []
    for tk, hoy in act.items():
        antes = ant.get(tk)
        if not antes:
            continue

        # Cambio de cantidad = compra o venta. NO es una re-marca; se reporta
        # aparte para que no se confundan.
        if antes.get("qty") is not None and hoy.get("qty") is not None \
                and abs((hoy["qty"] or 0) - (antes["qty"] or 0)) > 0.0001:
            cantidades.append({
                "ticker": tk, "qty_antes": antes["qty"], "qty_ahora": hoy["qty"],
                "mv_antes": antes["mv"], "mv_ahora": hoy["mv"],
            })
            # Con la cantidad moviendose, el MV no sirve como senal de re-marca.
            # Si igual tiene precio, se sigue evaluando abajo por precio.
            if hoy.get("precio") is None:
                continue

        tiene_precio = hoy.get("precio") is not None and antes.get("precio") is not None
        campo = "precio" if tiene_precio else "mv"
        v_ant, v_act = antes.get(campo), hoy.get(campo)
        pct = variacion(v_ant, v_act)
        if pct is None or abs(pct) < UMBRAL_PCT:
            continue

        remarcas.append({
            "ticker": tk,
            "senal": "precio" if tiene_precio else "valor estimado (no publica precio)",
            "antes": v_ant,
            "ahora": v_act,
            "var_pct": round(pct, 2),
            "price_date_antes": antes.get("price_date"),
            "price_date_ahora": hoy.get("price_date"),
            "mv_antes": antes.get("mv"),
            "mv_ahora": hoy.get("mv"),
        })
    return remarcas, cantidades


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--desde", default=None,
                    help="Revisar todos los snapshots desde esta fecha (YYYY-MM-DD).")
    ap.add_argument("--alerta", default=None,
                    help="Si hubo re-marcas, escribir el JSON de alerta en este path.")
    a = ap.parse_args()

    ids, excluidos = universo()
    if not ids:
        sys.exit("ERROR: no pude armar el universo de alternativos")

    fechas = snapshots()
    if len(fechas) < 2:
        sys.exit("ERROR: hacen falta al menos dos snapshots canonical")

    pares = ([(fechas[i - 1], fechas[i]) for i in range(1, len(fechas))
              if fechas[i] >= a.desde] if a.desde else [(fechas[-2], fechas[-1])])

    print("=" * 74)
    print("  RE-MARCAS DE NAV — alternativos iliquidos (Pershing)")
    print("=" * 74)
    print("  siguiendo: %s" % ", ".join(sorted(ids.values())))
    for tk, motivo in sorted(excluidos):
        print("  fuera:     %-7s %s" % (tk, motivo))
    print()

    todas = []
    for f_ant, f_act in pares:
        rem, cant = comparar(foto(f_ant, ids), foto(f_act, ids))
        for r in rem:
            r["detectado_en"] = f_act
            r["contra"] = f_ant
            todas.append(r)
            print("  [NAV]  %-7s %s: %s -> %s  (%+.2f%%)   [%s vs %s]"
                  % (r["ticker"], r["senal"], r["antes"], r["ahora"], r["var_pct"],
                     f_act, f_ant))
            if r["mv_antes"] is not None and r["mv_ahora"] is not None:
                print("         MV $%s -> $%s  (%+,.2f)".replace(",", "")
                      % (f"{r['mv_antes']:,.2f}", f"{r['mv_ahora']:,.2f}",
                         r["mv_ahora"] - r["mv_antes"]))
        for c in cant:
            print("  [qty]  %-7s cantidad %s -> %s (compra/venta, no re-marca)   [%s]"
                  % (c["ticker"], c["qty_antes"], c["qty_ahora"], f_act))

    print()
    if not todas:
        print("  Sin re-marcas.")
        sys.exit(0)

    print("  %d re-marca(s)." % len(todas))
    if a.alerta:
        os.makedirs(os.path.dirname(a.alerta), exist_ok=True)
        with open(a.alerta, "w", encoding="utf-8") as f:
            json.dump({
                "date": date.today().isoformat(),
                "tipo": "alts_nav_remarcado",
                "issues": [
                    "%s: %s %s -> %s (%+.2f%%). MV $%s -> $%s. Detectado el %s."
                    % (r["ticker"], r["senal"], r["antes"], r["ahora"], r["var_pct"],
                       f"{r['mv_antes']:,.2f}" if r["mv_antes"] else "?",
                       f"{r['mv_ahora']:,.2f}" if r["mv_ahora"] else "?",
                       r["detectado_en"])
                    for r in todas
                ],
                "accion": ("Pershing re-marco el NAV de un alternativo iliquido. "
                           "Revisar que el movimiento sea razonable y, si "
                           "corresponde, avisarle al equipo."),
                "detalle": todas,
            }, f, indent=2, ensure_ascii=False)
        print("  Alerta escrita en %s" % a.alerta)
    sys.exit(1)


if __name__ == "__main__":
    main()
