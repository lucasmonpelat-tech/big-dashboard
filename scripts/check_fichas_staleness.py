# -*- coding: utf-8 -*-
"""
check_fichas_staleness.py
=========================
Lista las fichas de fondos (data/funds/<TICKER>.json) de los holdings VIVOS del
ultimo canonical, ordenadas por antiguedad del factsheet, y deja una alerta
mensual con las que estan viejas (> MAX_DIAS) o sin factsheet (provisionales).

POR QUE (2026-11-06): de 29 fichas, 23 eran provisionales o sin fecha, y las mas
viejas (Thornburg feb-26, Janus mar-26, NB y PIMCO EM abr-26) alimentan el tab
Geography y las slides del pitch sin que nadie lo note. Esto NO parsea PDFs:
avisa. El parseo se hace en sesion con Claude cuando Lucas sube el factsheet
nuevo a Research Fondos (regla: metricas siempre del factsheet de la carpeta).

Uso:
    python scripts/check_fichas_staleness.py             # solo imprime
    python scripts/check_fichas_staleness.py --alerta    # ademas escribe data/_alerts/fichas_desactualizadas_<hoy>.json
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FUNDS = ROOT / "data" / "funds"
CANON = ROOT / "data" / "canonical"
ALERTS = ROOT / "data" / "_alerts"
MAX_DIAS = 120


def _fecha(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except Exception:
        return None


def holdings_vivos():
    snaps = sorted(CANON.glob("*/holdings_returns.json"))
    if not snaps:
        return {}, None
    doc = json.loads(snaps[-1].read_text(encoding="utf-8"))
    out = {}
    for sk, sl in (doc.get("sleeves") or {}).items():
        for h in sl.get("holdings", []):
            if (h.get("status") or "OPEN") == "OPEN" and h.get("mv_usd") and h.get("ticker"):
                out[h["ticker"]] = (sk, h["mv_usd"])
    return out, doc.get("as_of")


def revisar(hoy: date):
    vivos, as_of = holdings_vivos()
    total = sum(mv for _, mv in vivos.values()) or 1.0
    filas = []
    for tk, (sleeve, mv) in vivos.items():
        p = FUNDS / f"{tk}.json"
        if not p.exists():
            filas.append({"ticker": tk, "sleeve": sleeve, "peso_pct": round(mv / total * 100, 2),
                          "estado": "SIN FICHA", "dias": None, "fecha": None})
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        fechas = [f for f in (_fecha(d.get("as_of_factsheet")), _fecha(d.get("countries_as_of")),
                               _fecha((d.get("yield") or {}).get("as_of"))) if f]
        mas_nueva = max(fechas) if fechas else None
        dias = (hoy - mas_nueva).days if mas_nueva else None
        provisional = not (d.get("countries_de_factsheet") or (d.get("yield") or {}).get("de_factsheet")
                           or d.get("fi_metrics_de_factsheet"))
        if dias is None:
            estado = "SIN FECHA"
        elif dias > MAX_DIAS:
            estado = f"VIEJA ({dias}d)"
        elif provisional:
            estado = "PROVISIONAL (sin factsheet)"
        else:
            estado = "ok"
        filas.append({"ticker": tk, "sleeve": sleeve, "peso_pct": round(mv / total * 100, 2),
                      "estado": estado, "dias": dias, "fecha": mas_nueva.isoformat() if mas_nueva else None,
                      "source_file": d.get("source_file")})
    filas.sort(key=lambda r: (r["dias"] is not None, -(r["dias"] or 10**6), -r["peso_pct"]))
    return filas, as_of


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--alerta", action="store_true", help="escribe data/_alerts/fichas_desactualizadas_<hoy>.json si hay algo")
    ap.add_argument("--hoy", default=None)
    a = ap.parse_args()
    hoy = date.fromisoformat(a.hoy) if a.hoy else date.today()
    filas, as_of = revisar(hoy)
    print(f"Fichas de los {len(filas)} holdings vivos (canonical {as_of}), hoy {hoy}:")
    print(f"  {'ticker':10}{'sleeve':14}{'peso':>7}  {'fecha':10}  estado")
    for r in filas:
        print(f"  {r['ticker']:10}{r['sleeve']:14}{r['peso_pct']:6.2f}%  {str(r['fecha'] or '-'):10}  {r['estado']}")
    malas = [r for r in filas if r["estado"] != "ok"]
    viejas = [r for r in malas if r["estado"].startswith("VIEJA") or r["estado"] in ("SIN FECHA", "SIN FICHA")]
    print(f"\n  {len(viejas)} vieja(s)/sin fecha, {len(malas) - len(viejas)} provisional(es), {len(filas) - len(malas)} ok.")
    if a.alerta and malas:
        ALERTS.mkdir(parents=True, exist_ok=True)
        issues = [f"{r['ticker']} ({r['sleeve']}, {r['peso_pct']}% del fondo): {r['estado']}"
                  + (f", ultimo dato {r['fecha']}" if r['fecha'] else "") for r in malas]
        payload = {"detected_at": datetime.now().isoformat(), "date": hoy.isoformat(),
                   "tipo": "fichas_desactualizadas", "canonical": as_of,
                   "resumen": f"{len(viejas)} ficha(s) con factsheet de mas de {MAX_DIAS} dias o sin fecha y "
                              f"{len(malas) - len(viejas)} provisional(es). Subir los factsheets nuevos a Research Fondos "
                              f"y pedirle a Claude que actualice las fichas (regla: todo sale del factsheet).",
                   "issues": issues}
        out = ALERTS / f"fichas_desactualizadas_{hoy.isoformat()}.json"
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Alerta escrita: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
