"""
should_run_refresh.py
=====================
Decide si corresponde correr el daily-refresh. Lo usan el guard del propio
workflow y el watchdog, para no tener dos copias de la logica.

Imprime "si" o "no" en stdout (mas el motivo en stderr) y sale con codigo 0.

POR QUE NO ALCANZA CON "¿ya corrio hoy?"
----------------------------------------
Desde 2026-09-01 hay varios disparadores (cron-job.org, tarea local, schedule
de GitHub, watchdog) y el primero puede caer ANTES de que Lynk publique el NAV
del dia. Si el guard solo mirara last_run.json, esa corrida temprana marcaria
el dia como hecho y BLOQUEARIA los intentos posteriores -- quedando data vieja
todo el dia sin forma de arreglarse sola. Justo lo contrario de lo que se
buscaba.

Por eso el dia se considera hecho solo si ademas el NAV de Lynk llego fresco.

QUE ES "FRESCO"
---------------
Lynk publica el cierre del dia habil anterior (T-1). EXCEPTO los sabados, que
traen T-2: el cierre del viernes recien aparece el lunes. Verificado sobre 5
sabados consecutivos, sin una sola excepcion:

    sab 01-ago -> NAV 30-jul (jue)      sab 22-ago -> NAV 20-ago (jue)
    sab 08-ago -> NAV 06-ago (jue)      sab 29-ago -> NAV 27-ago (jue)
    sab 15-ago -> NAV 13-ago (jue)

Uso:
    python scripts/should_run_refresh.py
    python scripts/should_run_refresh.py --hoy 2026-09-05   # para probar
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
LAST_RUN = ROOT / "data" / "_alerts" / "last_run.json"
NAV_SERIES = ROOT / "data" / "lynk_nav_series.json"


def dia_habil_anterior(d: date) -> date:
    """El dia habil (lun-vie) inmediatamente anterior a d."""
    d -= timedelta(days=1)
    while d.weekday() >= 5:          # 5=sab, 6=dom
        d -= timedelta(days=1)
    return d


def nav_esperado(hoy: date) -> date:
    """Que fecha de NAV deberia tener Lynk publicada hoy."""
    esperado = dia_habil_anterior(hoy)
    if hoy.weekday() == 5:           # sabado: Lynk todavia no trae el viernes
        esperado = dia_habil_anterior(esperado)
    return esperado


def leer_last_run() -> str | None:
    try:
        return json.loads(LAST_RUN.read_text(encoding="utf-8")).get("date")
    except Exception:
        return None


def leer_ultimo_nav() -> str | None:
    try:
        d = json.loads(NAV_SERIES.read_text(encoding="utf-8"))
        serie = d.get("navSeries") or d.get("series") or []
        return serie[-1]["date"] if serie else None
    except Exception:
        return None


def decidir(hoy: date) -> tuple[bool, str]:
    hoy_iso = hoy.isoformat()
    ultimo_run = leer_last_run()
    ultimo_nav = leer_ultimo_nav()
    esperado = nav_esperado(hoy).isoformat()

    if ultimo_run != hoy_iso:
        return True, f"todavia no corrio hoy (ultimo run: {ultimo_run})"

    if ultimo_nav is None:
        return True, "no pude leer la serie de NAV -- corro por las dudas"

    if ultimo_nav < esperado:
        return True, (f"ya corrio hoy PERO el NAV quedo viejo "
                      f"(tiene {ultimo_nav}, se esperaba {esperado}): "
                      f"Lynk debe haber publicado tarde, se reintenta")

    return False, f"ya corrio hoy y el NAV esta fresco ({ultimo_nav})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoy", default=None, help="Fecha a evaluar (YYYY-MM-DD). Default: hoy.")
    args = ap.parse_args()
    hoy = date.fromisoformat(args.hoy) if args.hoy else date.today()

    correr, motivo = decidir(hoy)
    print("si" if correr else "no")
    print(f"[should_run_refresh] {hoy} ({['Lun','Mar','Mie','Jue','Vie','Sab','Dom'][hoy.weekday()]}): "
          f"{'CORRER' if correr else 'SALTEAR'} -- {motivo}", file=sys.stderr)


if __name__ == "__main__":
    main()
