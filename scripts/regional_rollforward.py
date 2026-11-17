# -*- coding: utf-8 -*-
"""
regional_rollforward.py
=======================
Estimacion SEMANAL del regional del Equity sleeve (widget "Distribucion Regional" y cuadro
"BIG vs Modelo Mikla Core Equities vs ACWI" del tab Equity).

POR QUE EXISTE (2026-11-17, pedido de Lucas: "una vez por semana, los lunes")
------------------------------------------------------------------------------
El regional OFICIAL sale del deck de Maximus y se carga una vez por mes, al cierre
(data/equity_breakdown_latest.json, a mano). Entre cierres queda viejo: el 13-Nov se
vendio 4BRZ (Brasil) y se compro EMXC, y el widget siguio mostrando LatAm 10,1%.

COMO SE CALCULA (roll-forward, NO un calculo nuevo por fondo)
-------------------------------------------------------------
Se parte del regional de Maximus al cierre (asOf del archivo) y se le aplica lo que
cambio en la cartera desde esa fecha:

    BIG_hoy[region] = BIG_cierre[region] + sum_fondos( (peso_hoy - peso_cierre) x geografia_fondo[region] )

- Fondos PASIVOS con geografia exacta (CSPX, DYNF, MAGS, HEWJ, ILF, ARGT, 4BRZ, EMXC): se usa
  el pais de su ficha (data/funds/<TICKER>.json -> countries).
- Fondos ACTIVOS (NB, MFS, Thornburg, Janus) y cualquier otro: publican poco (distribucion de
  ingresos, top 5 de paises...), asi que su cambio de peso se reparte con la MISMA mezcla que
  tenia BIG en el cierre. No se inventa una geografia que el fondo no publico.
Los pesos de cada fondo son los del canonical (MV Pershing) a la fecha del cierre y al
ultimo canonical. Como ambos conjuntos de pesos suman 100%, el resultado suma 100%.

El ACWI no se toca (es el del archivo base). Cuando se carga un cierre nuevo de Maximus
(asOf distinto), el front deja de usar esta estimacion y vuelve al dato oficial.

Es una ESTIMACION: el front la rotula como tal. Salida: data/regional_estimado.json

Uso:
    python scripts/regional_rollforward.py            # escribe
    python scripts/regional_rollforward.py --dry-run
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BASE = DATA / "equity_breakdown_latest.json"
OUT = DATA / "regional_estimado.json"

# Fondos con geografia exacta (ficha por pais). El resto se trata como activo.
PASIVOS = {"CSPX", "DYNF", "MAGS", "HEWJ", "ILF", "ARGT", "4BRZ", "EMXC"}
# Para estos, el pais "OTHER" de la ficha es de la misma region que el fondo (ILF: Panama, etc.).
OTHER_ES_LATAM = {"ILF", "ARGT", "4BRZ"}

NORTE_AMERICA = {"US", "CA"}
EUROPA_DEV = {"FR", "DE", "NL", "CH", "ES", "IT", "SE", "DK", "NO", "FI", "BE", "IE", "AT", "PT", "EU"}
LATAM = {"BR", "MX", "CL", "CO", "PE", "AR"}
ASIA_EM = {"CN", "TW", "KR", "IN", "TH", "MY", "ID", "PH"}


def region(code: str, tk: str) -> str:
    if code in NORTE_AMERICA:
        return "N. America"
    if code in EUROPA_DEV:
        return "Europe dev."
    if code in ("UK", "GB"):
        return "UK"
    if code == "JP":
        return "Japan"
    if code in LATAM or (code == "OTHER" and tk in OTHER_ES_LATAM):
        return "LatAm"
    if code in ASIA_EM:
        return "Asia EM"
    return "Otros"


def geografia(tk: str) -> dict[str, float]:
    """{region: % del fondo} segun la ficha."""
    f = json.loads((DATA / "funds" / f"{tk}.json").read_text(encoding="utf-8"))
    paises = f.get("countries") or {}
    tot = sum(paises.values()) or 100.0
    out: dict[str, float] = {}
    for code, v in paises.items():
        r = region(code, tk)
        out[r] = out.get(r, 0.0) + v / tot * 100
    return out


def pesos(canonical_dir: Path) -> dict[str, float]:
    """{ticker: % del sleeve Equity} del canonical (holdings OPEN con MV)."""
    doc = json.loads((canonical_dir / "holdings_returns.json").read_text(encoding="utf-8"))
    hs = [h for h in doc["sleeves"]["equity"]["holdings"] if (h.get("status") or "OPEN") == "OPEN" and h.get("mv_usd")]
    tot = sum(h["mv_usd"] for h in hs)
    return {h["ticker"]: h["mv_usd"] / tot * 100 for h in hs}


def canonical_hasta(fecha: str | None = None) -> Path:
    dirs = sorted(d for d in (DATA / "canonical").iterdir()
                  if d.is_dir() and (d / "holdings_returns.json").exists() and (fecha is None or d.name <= fecha))
    return dirs[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    bd = json.loads(BASE.read_text(encoding="utf-8"))
    as_of = bd.get("asOf") or bd.get("as_of")
    rows = bd["regional"]["rows"]
    base = {r["category"]: r["big"] for r in rows}
    mezcla_base = {k: v / sum(base.values()) for k, v in base.items()}

    c_base, c_hoy = canonical_hasta(as_of), canonical_hasta()
    w0, w1 = pesos(c_base), pesos(c_hoy)

    delta = {k: 0.0 for k in base}
    mov = []
    for tk in sorted(set(w0) | set(w1)):
        d = w1.get(tk, 0.0) - w0.get(tk, 0.0)
        pasivo = tk in PASIVOS
        if pasivo:
            for r, v in geografia(tk).items():
                delta[r] = delta.get(r, 0.0) + d * v / 100
        else:
            for r, m in mezcla_base.items():
                delta[r] += d * m
        mov.append({"fondo": tk, "peso_cierre_pct": round(w0.get(tk, 0.0), 2), "peso_hoy_pct": round(w1.get(tk, 0.0), 2),
                    "cambio_pp": round(d, 2), "tratamiento": "pasivo (ficha por pais)" if pasivo else "activo (mezcla del cierre)"})

    nuevas = []
    for r in rows:
        big = round(r["big"] + delta.get(r["category"], 0.0), 2)
        nuevas.append({"category": r["category"], "big": big, "acwi": r["acwi"],
                       "big_cierre": r["big"], "cambio_pp": round(big - r["big"], 2)})
    if min(x["big"] for x in nuevas) < -0.05:
        raise SystemExit("ERROR: una region quedo negativa (" + str([(x['category'], x['big']) for x in nuevas]) + "). No se escribe.")
    # correccion de redondeo: que sume exactamente 100 (se ajusta la fila mas grande)
    ajuste = round(100 - sum(x["big"] for x in nuevas), 2)
    if abs(ajuste) > 0.1:
        raise SystemExit(f"ERROR: las regiones suman {100 - ajuste}, no 100. No se escribe.")
    max(nuevas, key=lambda x: x["big"])["big"] = round(max(nuevas, key=lambda x: x["big"])["big"] + ajuste, 2)

    out = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "estimado_al": c_hoy.name,
        "base_asOf": as_of,
        "base_fuente": "equity_breakdown_latest.json (Maximus, cierre de mes). Esta estimacion deja de usarse cuando asOf cambia.",
        "metodo": ("Roll-forward: regional de Maximus al cierre + (peso hoy - peso al cierre) x geografia del fondo. "
                   "Pasivos con pais de su ficha; fondos activos con la mezcla que tenia BIG en el cierre. "
                   "ACWI sin cambios. Es una ESTIMACION, no el dato oficial."),
        "pesos_cierre_canonical": c_base.name,
        "rows": nuevas,
        "totals": {"big": round(sum(x["big"] for x in nuevas), 2), "acwi": bd["regional"]["totals"]["acwi"]},
        "movimientos": [m for m in mov if abs(m["cambio_pp"]) >= 0.05],
    }
    print(f"Regional estimado al {c_hoy.name} (base Maximus {as_of}, pesos del {c_base.name})")
    for x in nuevas:
        print(f"  {x['category']:12} cierre {x['big_cierre']:6.2f} -> hoy {x['big']:6.2f}  ({x['cambio_pp']:+.2f} pp)   ACWI {x['acwi']}")
    print("  suma:", out["totals"]["big"])
    for m in out["movimientos"]:
        print(f"    {m['fondo']:7} {m['peso_cierre_pct']:5.2f}% -> {m['peso_hoy_pct']:5.2f}%  {m['cambio_pp']:+.2f}  [{m['tratamiento']}]")
    if a.dry_run:
        print("--dry-run: no se escribio nada")
        return
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Escrito:", OUT)


if __name__ == "__main__":
    main()
