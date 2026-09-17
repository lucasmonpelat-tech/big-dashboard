# -*- coding: utf-8 -*-
"""La serie de NAV de Lynk, ya corregida. UNICA puerta de entrada.

POR QUE EXISTE (2026-09-17)
---------------------------
Lynk publica mal el NAV cada tanto, y no solo hacia adelante: el 14-Sep-2026
REESCRIBIO el 12-Ago, que llevaba un mes publicado bien (106.861 -> 103.215).

El primer arreglo fue filtrar el dato en build_benchmark_comparison.py. Andaba,
pero estaba en el lugar equivocado: SIETE scripts leen lynk_nav_series.json, y
uno de ellos arma el Excel de NAV que va al administrador del fondo. Un parche
por consumidor significa que el proximo script que alguien escriba va a leer la
serie cruda otra vez y nadie se va a acordar de esto.

Entonces la correccion vive ACA, una vez, y los consumidores piden la serie por
esta puerta. Si mañana aparece otro dato malo, se agrega a
data/lynk_puntos_malos.json y se arregla en todos lados junto.

QUE HACE Y QUE NO
-----------------
CORRIGE cuando sabemos el valor real (el caso normal: lo sabemos por el CAV
oficial de ProCapital y porque el propio Lynk lo publicaba asi antes).

EXCLUYE solo si no hay valor conocido. Es el ultimo recurso: deja un agujero en
la serie, y un agujero no se puede mandar al administrador.

Nunca INVENTA un NAV. No interpola ni promedia: o hay una fuente que dice cual
era el numero, o el dia se saltea y se avisa.

La serie cruda en disco NO se toca. Siempre se puede ver que mando Lynk y que
mostramos nosotros, que es la unica forma de reclamarles con evidencia.

USO
---
    from lynk_series import cargar_serie            # desde scripts/
    from scripts.lynk_series import cargar_serie    # desde dashboard_v2/

    serie, correcciones = cargar_serie()
    # serie:        [{date, value}, ...] lista para usar
    # correcciones: [{fecha, de, a, fuente}, ...] para mostrar o loguear
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
SERIE_FILE = ROOT / "data" / "lynk_nav_series.json"
PUNTOS_MALOS_FILE = ROOT / "data" / "lynk_puntos_malos.json"


def cargar_puntos_malos() -> dict:
    """{fecha: entrada} de los NAV malos que Lynk todavia no corrigio.

    Si el archivo no esta o no se puede leer, devuelve vacio y la serie sale tal
    cual viene de Lynk. Nunca rompe al que la pide: un dashboard con un dato
    dudoso sirve mas que un dashboard que no carga.
    """
    try:
        doc = json.loads(PUNTOS_MALOS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {p["fecha"]: p for p in doc.get("puntos_malos", [])
            if p.get("fecha") and not p.get("corregido_por_lynk")}


def corregir(series: list, puntos: dict | None = None) -> tuple[list, list]:
    """Aplica las correcciones a una serie ya cargada. (serie, correcciones)."""
    puntos = cargar_puntos_malos() if puntos is None else puntos
    if not puntos:
        return series, []

    out, correcciones = [], []
    for p in series:
        malo = puntos.get(p.get("date"))
        if not malo:
            out.append(p)
            continue

        # Solo se corrige si el dato en disco es efectivamente el malo. Si Lynk
        # ya lo arreglo, se deja pasar: la entrada quedo vieja en el JSON y
        # pisarla seria reintroducir el problema al reves.
        publicado = malo.get("nav_publicado")
        if publicado is not None and p.get("value") != publicado:
            out.append(p)
            continue

        correcto = malo.get("valor_correcto")
        if correcto is None:
            # Sin valor conocido no se inventa: se saltea.
            correcciones.append({"fecha": p["date"], "de": p.get("value"),
                                 "a": None, "fuente": "sin valor conocido — dia excluido"})
            continue

        out.append({**p, "value": correcto})
        correcciones.append({
            "fecha": p["date"],
            "de": p.get("value"),
            "a": correcto,
            "fuente": malo.get("fuente_del_valor_correcto", ""),
        })

    return out, correcciones


def cargar_serie(path: Path | None = None) -> tuple[list, list]:
    """La serie de NAV lista para usar. (serie, correcciones)."""
    doc = json.loads((path or SERIE_FILE).read_text(encoding="utf-8"))
    return corregir(doc.get("series") or [])


def describir(correcciones: list) -> str:
    """Una linea por correccion, para imprimir en el log de cualquier script."""
    return "\n".join(
        "  [NAV corregido] %s: %s -> %s" % (c["fecha"], c["de"], c["a"])
        if c["a"] is not None else
        "  [NAV excluido]  %s: %s (sin valor conocido)" % (c["fecha"], c["de"])
        for c in correcciones
    )
