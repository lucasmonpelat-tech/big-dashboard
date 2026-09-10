"""
build_fi_stats.py
=================
Genera el bloque `fi_stats` de data/fi_breakdown_latest.json: YTW, Duracion y
Vencimiento ponderados del sleeve FI. De ahi salen el factsheet que se manda a
clientes y el S10 del pitch book.

POR QUE EXISTE (2026-09-08)
---------------------------
Estos tres numeros se venian escribiendo A MANO en el JSON. Funcionaba, pero:

  - La regla de que fondos entran vivia en la cabeza de quien lo tipeaba (y en
    un mensaje de commit). El dashboard, que la calculaba por su cuenta, usaba
    otra: incluia TGF y PIMCO-EM y excluia MANEM. Daba YTW 7.20 contra 6.98 del
    factsheet. Dos numeros distintos para lo mismo, sin que nada lo detectara.

  - Las metricas de MANEM (YTW 8.55 hedged a USD, duration 2.35) existian solo
    dentro del agregado y en un mensaje de commit. No habia forma de auditarlas.

Ahora los tres numeros se DERIVAN, y la regla es un campo en el archivo de cada
fondo. Cambiar la regla = cambiar `fi_stats_include` en un data/funds/*.json.

FUENTES
-------
  pesos     data/canonical/<fecha>/holdings_returns.json -> sleeves.fixed_income
  metricas  data/funds/<TICKER>.json -> fi_metrics (ytw / duration / maturity)
  regla     data/funds/<TICKER>.json -> fi_stats_include (bool)

REGLA DE INCLUSION (Lucas, 2026-09-07)
--------------------------------------
Entran solo los fondos cuyas metricas estan en USD o hedgeadas a USD. Quedan
afuera Tenac (TGF) y PIMCO EM Local: moneda local sin hedge por diseno del
mandato, su duracion no es homogenea con la del resto y promediarla mezcla
peras con manzanas.

La calidad crediticia NO sigue esta regla y no la toca este script: Maximus la
publica agregada, con TGF y PIMCO-EM adentro, y no se puede desarmar.

USO
---
    python scripts/build_fi_stats.py                    # ultimo canonical
    python scripts/build_fi_stats.py --as-of 2026-08-31 # cierre de mes (factsheet)
    python scripts/build_fi_stats.py --cierre-anterior  # idem, resolviendo la fecha solo
    python scripts/build_fi_stats.py --check            # no escribe, solo compara

`--check` sale con codigo 1 si lo que hay en el JSON no coincide con lo
calculado. Lo usa validate_data.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
CANONICAL_DIR = ROOT / "data" / "canonical"
FUNDS_DIR = ROOT / "data" / "funds"
BREAKDOWN = ROOT / "data" / "fi_breakdown_latest.json"

# El benchmark (AGG) no se deriva de ninguna fuente local: sale del factsheet
# de iShares y se carga a mano. Se preserva tal cual.
METRICAS = [("YTW (%)", "ytw"), ("Duración", "duration"), ("Vencimiento", "maturity")]

TOLERANCIA = 0.005   # los valores van redondeados a 2 decimales


def cierre_mes_anterior(hoy=None):
    """El ultimo canonical disponible del mes pasado.

    Es la fecha que corresponde para estos stats: las metricas salen de
    factsheets mensuales o trimestrales, asi que el numero es de cierre de mes,
    no del dia. Se busca el ultimo snapshot que exista dentro del mes anterior
    -- el 31 puede caer fin de semana y no tener corrida.
    """
    hoy = hoy or date.today()
    primero = hoy.replace(day=1)
    fin_anterior = primero - timedelta(days=1)
    prefijo = fin_anterior.strftime("%Y-%m")
    delmes = sorted(p.parent.name for p in CANONICAL_DIR.glob("*/holdings_returns.json")
                    if p.parent.name.startswith(prefijo))
    if not delmes:
        sys.exit(f"ERROR: no hay ningun canonical de {prefijo}")
    return delmes[-1]


def snapshot(as_of):
    """Path del holdings_returns.json a usar, y su fecha."""
    if as_of:
        p = CANONICAL_DIR / as_of / "holdings_returns.json"
        if not p.exists():
            sys.exit(f"ERROR: no existe {p}")
        return p, as_of
    snaps = sorted(CANONICAL_DIR.glob("*/holdings_returns.json"))
    if not snaps:
        sys.exit("ERROR: no hay ningun snapshot canonical")
    return snaps[-1], snaps[-1].parent.name


def leer_fondos():
    """{ticker: {ytw, duration, maturity, include, as_of_factsheet, motivo}}."""
    out = {}
    for p in sorted(FUNDS_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("sleeve") != "Fixed Income":
            continue
        fm = d.get("fi_metrics") or {}
        out[d["ticker"]] = {
            "ytw": fm.get("ytw"),
            "duration": fm.get("duration"),
            "maturity": fm.get("maturity"),
            "include": d.get("fi_stats_include"),
            "as_of_factsheet": d.get("as_of_factsheet"),
            "motivo": d.get("fi_stats_exclude_reason"),
        }
    return out


def calcular(as_of):
    path, fecha = snapshot(as_of)
    doc = json.loads(path.read_text(encoding="utf-8"))
    holdings = [h for h in doc["sleeves"]["fixed_income"]["holdings"]
                if (h.get("status") or "OPEN") == "OPEN" and h.get("mv_usd")]
    fondos = leer_fondos()

    total = sum(h["mv_usd"] for h in holdings)
    sin_ficha, sin_flag, incluidos = [], [], []
    for h in holdings:
        f = fondos.get(h["ticker"])
        if f is None:
            sin_ficha.append(h["ticker"])
        elif f["include"] is None:
            sin_flag.append(h["ticker"])
        elif f["include"]:
            incluidos.append((h["ticker"], h["mv_usd"], f))

    if not incluidos:
        sys.exit("ERROR: ningun fondo marcado fi_stats_include=true — revisar data/funds/*.json")

    peso_incluido = sum(mv for _, mv, _ in incluidos)
    valores, faltantes = {}, []
    for etiqueta, campo in METRICAS:
        acum = 0.0
        for tk, mv, f in incluidos:
            v = f.get(campo)
            if v is None:
                faltantes.append(f"{tk}.{campo}")
                continue
            acum += mv * v
        valores[etiqueta] = round(acum / peso_incluido, 2)

    excluidos = {}
    for h in holdings:
        tk = h["ticker"]
        f = fondos.get(tk)
        if f and f["include"] is False:
            excluidos[tk] = f.get("motivo") or "fi_stats_include=false"

    return {
        "as_of": fecha,
        "valores": valores,
        "incluidos": [tk for tk, _, _ in incluidos],
        "excluidos": excluidos,
        "cobertura_pct": round(peso_incluido / total * 100, 2),
        "sleeve_mv": round(total, 2),
        "sin_ficha": sin_ficha,
        "sin_flag": sin_flag,
        "faltantes": faltantes,
        "fichas": {tk: f["as_of_factsheet"] for tk, _, f in incluidos},
    }


def aplicar(r):
    doc = json.loads(BREAKDOWN.read_text(encoding="utf-8"))
    stats = doc.setdefault("fi_stats", {})
    previas = {row["metric"]: row.get("bmk") for row in stats.get("rows", [])}

    stats["title"] = "Estadísticas Renta Fija"
    stats["rows"] = [
        {"metric": etiqueta, "big": r["valores"][etiqueta], "bmk": previas.get(etiqueta)}
        for etiqueta, _ in METRICAS
    ]
    stats["source"] = (
        f"big: DERIVADO por scripts/build_fi_stats.py — pesos del canonical "
        f"{r['as_of']} x metricas de data/funds/<TICKER>.json. Incluye solo fondos en "
        f"USD o hedgeados a USD ({', '.join(r['incluidos'])}), cobertura "
        f"{r['cobertura_pct']}% del sleeve. Regla fijada por Lucas el 2026-09-07, "
        f"guardada en fi_stats_include de cada archivo de fondo. "
        f"bmk (AGG): manual, no lo toca este script."
    )
    stats["_regla_inclusion"] = {
        "incluidos": r["incluidos"],
        "excluidos": r["excluidos"],
        "cobertura_pct_sleeve": r["cobertura_pct"],
        "factsheets_usados": r["fichas"],
        "nota": ("La calidad crediticia NO sigue esta regla: Maximus la publica "
                 "agregada, con TGF y PIMCO-EM adentro, y no se puede desarmar."),
    }
    stats["_generated_at"] = datetime.now().isoformat()
    stats["_generated_from"] = f"canonical/{r['as_of']}/holdings_returns.json"

    BREAKDOWN.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default=None, help="Fecha del canonical (YYYY-MM-DD). Default: el ultimo.")
    ap.add_argument("--cierre-anterior", action="store_true",
                    help=("Usar el ultimo canonical del mes pasado. Es lo que corre "
                          "el cron mensual: estos stats son de cierre de mes."))
    ap.add_argument("--check", action="store_true", help="No escribe; compara y sale 1 si difiere.")
    args = ap.parse_args()

    as_of = args.as_of
    if args.cierre_anterior:
        if as_of:
            sys.exit("ERROR: --as-of y --cierre-anterior son excluyentes")
        as_of = cierre_mes_anterior()
    r = calcular(as_of)

    print(f"fi_stats desde canonical {r['as_of']}  (sleeve ${r['sleeve_mv']:,.2f})")
    print(f"  incluidos : {', '.join(r['incluidos'])}  -> {r['cobertura_pct']}% del sleeve")
    for tk, motivo in r["excluidos"].items():
        print(f"  excluido  : {tk} — {motivo}")
    for etiqueta, _ in METRICAS:
        print(f"  {etiqueta:14} {r['valores'][etiqueta]}")

    problemas = []
    if r["sin_ficha"]:
        problemas.append(f"sin data/funds/<TICKER>.json: {r['sin_ficha']}")
    if r["sin_flag"]:
        problemas.append(f"sin fi_stats_include (no se sabe si entran): {r['sin_flag']}")
    if r["faltantes"]:
        problemas.append(f"metricas faltantes en fondos incluidos: {r['faltantes']}")
    for p in problemas:
        print(f"  WARN: {p}")

    if args.check:
        doc = json.loads(BREAKDOWN.read_text(encoding="utf-8"))
        rows = {row["metric"]: row.get("big") for row in (doc.get("fi_stats") or {}).get("rows", [])}
        difs = [f"{etiqueta}: JSON {rows.get(etiqueta)} vs calculado {r['valores'][etiqueta]}"
                for etiqueta, _ in METRICAS
                if rows.get(etiqueta) is None
                or abs(rows[etiqueta] - r["valores"][etiqueta]) > TOLERANCIA]
        if difs or problemas:
            for d in difs:
                print(f"    [X] {d}")
            sys.exit(1)
        print("\n  OK: fi_breakdown_latest.json coincide con lo calculado.")
        sys.exit(0)

    if r["sin_flag"] or r["faltantes"]:
        sys.exit("\nABORTA: hay fondos sin resolver. Completar data/funds/*.json primero.")

    aplicar(r)
    print(f"\n  Escrito: {BREAKDOWN}")


if __name__ == "__main__":
    main()
