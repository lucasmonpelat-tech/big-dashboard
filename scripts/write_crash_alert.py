# -*- coding: utf-8 -*-
"""Deja una alerta cuando un step del cron se muere SIN dejar la suya.

POR QUE EXISTE (2026-09-15)
---------------------------
Varios steps del cron llevan `continue-on-error: true` para que la falla de uno
no se lleve puesto el resto del pipeline. El precio de eso es que el job termina
en verde igual, asi que el aviso tiene que venir por otro lado: cualquier
archivo con la fecha de hoy en data/_alerts/ dispara el mail inmediato de
send_failure_alert.py.

Los scripts que validan sus datos ya escriben su propia alerta cuando el dato
viene mal. El hueco es el otro caso: cuando el script se muere ANTES de poder
escribirla -- un timeout de Playwright, un cambio de layout que tira excepcion,
la red. Ahi no hay alerta, el job queda verde y nadie se entera hasta que
alguien mira a mano. Y el check de frescura que vigilaria esos archivos
(check_race_freshness.py) no corre en ningun cron: es un chequeo manual.

Entonces el step compara: si el script salio con error y NO dejo su archivo,
llama a este para dejar uno generico. La distincion importa al leer el mail:

    "dato invalido"  -> el proveedor publico algo mal, el archivo viejo se
                        conserva a proposito. Suele arreglarse solo.
    "crash"          -> se rompio el scraper. Hay que mirar los logs.

Uso (desde el yml):
    python scripts/write_crash_alert.py --path data/_alerts/x_2026-09-15.json \\
        --tipo lynk_scrape_crash --rc 1 \\
        --que "el scrape de KPIs de Lynk (lynk_refresher.py)" \\
        --archivo data/lynk_data.json
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--path", required=True, help="Donde escribir la alerta.")
    ap.add_argument("--tipo", required=True, help="Tipo de alerta (va en el JSON).")
    ap.add_argument("--rc", default="?", help="Exit code con el que murio el script.")
    ap.add_argument("--que", required=True, help="Que se murio, en criollo.")
    ap.add_argument("--archivo", default=None,
                    help="Archivo de datos que quedo sin actualizar.")
    a = ap.parse_args()

    carpeta = os.path.dirname(a.path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    issues = [
        "%s murio con exit %s y no alcanzo a dejar su propia alerta." % (a.que, a.rc),
        "No es un dato invalido del proveedor: es una falla del script "
        "(timeout de Playwright, cambio de layout, red). Esos casos dejan su "
        "alerta propia; este no.",
    ]
    if a.archivo:
        issues.append("%s quedo sin actualizar, con su ultimo valor bueno y su "
                      "fecha vieja." % a.archivo)

    run = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")

    payload = {
        "date": date.today().isoformat(),
        "tipo": a.tipo,
        "issues": issues,
        "accion": ("Mirar los logs del run para ver con que excepcion murio. El "
                   "resto del cron siguio normal, asi que el dashboard esta al "
                   "dia salvo por este archivo."),
    }
    if run and repo:
        payload["run_url"] = f"{server}/{repo}/actions/runs/{run}"

    with open(a.path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"[write_crash_alert] alerta de crash escrita en {a.path}")


if __name__ == "__main__":
    main()
