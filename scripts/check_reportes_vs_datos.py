# -*- coding: utf-8 -*-
"""Compara cada numero del deck contra el JSON del que deberia salir.

QUE PROBLEMA RESUELVE (2026-09-09)
----------------------------------
diff_reportes_mensual.py caza numeros que quedaron VIEJOS. No caza un numero que
cambio al valor EQUIVOCADO: si alguien tipea 4.9 donde iba 3.9, el diff ve que
cambio respecto del mes pasado y se queda tranquilo.

Este script cierra ese agujero para todo lo que tenga fuente declarada, y --
igual de importante -- LISTA LO QUE NO LA TIENE. Hoy los reportes no se
construyen desde los datos, se tipean; saber que celdas no salen de ningun
archivo del repo es el primer paso para que dejen de ser un acto de fe.

Casos reales que aparecen solos al correrlo:
  - la celda "Rta. Cte." del benchmark (2.6%) no sale de ningun archivo
  - la serie de calidad crediticia del benchmark estuvo hardcodeada en el deck
    desde Abril sin corresponder a ningun dato guardado

EL PROBLEMA DE LAS DOS FECHAS
-----------------------------
El deck es una foto de un dia. Los JSON se siguen moviendo todos los dias. Si se
compara el deck de Agosto contra el JSON de hoy, todo lo que cambio en el medio
aparece como error y el reporte se vuelve inutil.

Paso el 2026-09-09 mientras se armaba esto: el factsheet de Agosto decia
YTW 7.1 y el JSON del dia decia 6.98. Parecia un error del deck. No lo era: el
07-Sep se habia decidido meter TGF al calculo y el numero se regenero DESPUES de
exportar el PDF.

Por eso, ante cada diferencia, el script pregunta a git si ese archivo cambio
DESPUES de la fecha del deck. Si cambio, no lo reporta como error del deck: lo
reporta como "el dato se movio despues" y dice cuando. Corriendolo el dia del
cierre -- que es cuando importa -- las dos fechas coinciden y toda diferencia es
un error de verdad.

USO
---
    python scripts/check_reportes_vs_datos.py <deck.pptx>
    python scripts/check_reportes_vs_datos.py <deck.pptx> --sin-fuente
    python scripts/check_reportes_vs_datos.py <deck.pptx> --deck factsheet

Exit code 1 si hay alguna diferencia real (no explicada por el desfasaje).
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diff_reportes_mensual import (recolectar, norm, TIENE_DIGITO,  # noqa: E402
                                   cargar_ignore)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPA_FILE = os.path.join(ROOT, "scripts", "reportes_shape_map.json")

# "fi_stats.rows[metric=YTW (%)].big"  ->  ['fi_stats', 'rows', '[metric=YTW (%)]', 'big']
PASO = re.compile(r"\[([^\]]+)\]|([^.\[\]]+)")


def resolver(spec):
    """'archivo.json :: ruta.al.campo' -> (valor, archivo). Lanza si no resuelve."""
    if "::" not in spec:
        raise ValueError("falta '::' en la fuente: %s" % spec)
    rel, ruta = [x.strip() for x in spec.split("::", 1)]
    path = os.path.join(ROOT, rel)
    with io.open(path, encoding="utf-8") as f:
        nodo = json.load(f)

    for m in PASO.finditer(ruta):
        filtro, campo = m.group(1), m.group(2)
        if campo is not None:
            nodo = nodo[campo.strip()]
            continue
        if "=" in filtro:                       # [metric=YTW (%)]
            k, v = filtro.split("=", 1)
            elegido = next((x for x in nodo if str(x.get(k.strip())) == v.strip()), None)
            if elegido is None:
                raise KeyError("ningun item con %s=%s" % (k.strip(), v.strip()))
            nodo = elegido
        else:                                    # [0]
            nodo = nodo[int(filtro)]
    return nodo, rel


def formatear(valor, fmt):
    """Numero del JSON -> como se escribe en el deck."""
    fmt = fmt or {}
    dec = fmt.get("dec", 1)
    try:
        s = ("%%.%df" % dec) % float(valor)
    except (TypeError, ValueError):
        return str(valor)
    if fmt.get("coma"):                # el deck mezcla: los charts usan coma
        s = s.replace(".", ",")
    return fmt.get("prefijo", "") + s + fmt.get("sufijo", "")


def cambio_despues(rel_path, cuando):
    """Fecha del ultimo commit que toco el archivo DESPUES de `cuando`, o None."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI|%h|%s", "--since", cuando.isoformat(),
             "--", rel_path],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        linea = out.stdout.strip()
        return linea or None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pptx")
    ap.add_argument("--deck", default=None, help="clave del mapa (default: se infiere)")
    ap.add_argument("--sin-fuente", action="store_true",
                    help="listar los numeros del deck que no tienen fuente declarada")
    a = ap.parse_args()

    if not os.path.exists(a.pptx):
        sys.exit("No existe %s" % a.pptx)

    deck = a.deck or ("factsheet" if "factsheet" in os.path.basename(a.pptx).lower()
                      else "pitchbook")
    fecha_deck = datetime.fromtimestamp(os.path.getmtime(a.pptx))

    with io.open(MAPA_FILE, encoding="utf-8") as f:
        mapa_todo = json.load(f)
    mapa = mapa_todo.get(deck, {})

    contenido = recolectar(a.pptx)
    por_etiqueta = {etq: val for etq, val in contenido.values()}

    coincide, difiere, movido, rotos = [], [], [], []

    for etq, decl in sorted(mapa.items()):
        if etq.startswith("_"):
            continue
        actual = por_etiqueta.get(etq)
        if actual is None:
            rotos.append((etq, "el shape ya no existe en el deck (reordenaron?)"))
            continue

        specs = decl.get("fuentes") or ([decl["fuente"]] if decl.get("fuente") else [])
        fmts = decl.get("formatos") or [decl.get("formato")] * len(specs)
        esperados, archivos = [], set()
        try:
            for spec, fmt in zip(specs, fmts):
                v, rel = resolver(spec)
                esperados.append(formatear(v, fmt))
                archivos.add(rel)
        except Exception as e:
            rotos.append((etq, "no pude resolver la fuente: %s" % e))
            continue

        faltan = [e for e in esperados if e not in actual]
        if not faltan:
            coincide.append((etq, actual))
            continue

        # Difiere. ¿O el dato se movio despues de exportar el deck?
        explicacion = None
        for rel in archivos:
            c = cambio_despues(rel, fecha_deck)
            if c:
                explicacion = (rel, c)
                break
        if explicacion:
            movido.append((etq, actual, faltan, explicacion))
        else:
            difiere.append((etq, actual, faltan, sorted(archivos)))

    # Etiquetas prohibidas: reglas que no son "este numero sale de aca" sino
    # "esto no se dice mas". La primera nace de la regla de benchmark por sleeve
    # (Lucas, 2026-09-08): un blend 60/40 con equity adentro no tiene duracion
    # ni P/E, asi que nombrarlo en la tabla de estadisticas de un sleeve es
    # etiquetar mal numeros que en realidad son del indice puro.
    prohibidas = []
    reglas = (mapa_todo.get("_etiquetas_prohibidas") or {}).get("reglas", [])
    for regla in reglas:
        patron = regla["patron"]
        for etq, val in sorted(por_etiqueta.items()):
            if patron.lower() not in val.lower():
                continue
            if any(etq.startswith(p) for p in regla.get("salvo_en", [])):
                continue
            prohibidas.append((etq, val, regla["motivo"]))

    print("=" * 78)
    print("DECK vs DATOS  [%s]" % deck)
    print("  deck      : %s" % os.path.basename(a.pptx))
    print("  exportado : %s" % fecha_deck.strftime("%Y-%m-%d %H:%M"))
    print("=" * 78)
    print("  %d shapes mapeados | %d coinciden | %d difieren | %d el dato se movio "
          "despues | %d mapeo roto"
          % (len(mapa) - sum(1 for k in mapa if k.startswith("_")),
             len(coincide), len(difiere), len(movido), len(rotos)))

    if difiere:
        print("\n" + "-" * 78)
        print("NO COINCIDEN — el deck dice una cosa y el dato dice otra")
        print("-" * 78)
        for etq, actual, faltan, archivos in difiere:
            print("  %-34s deck: %-22s esperado: %s"
                  % (etq, actual[:22], ", ".join(faltan)))
            print("  %-34s fuente: %s" % ("", ", ".join(archivos)))

    if movido:
        print("\n" + "-" * 78)
        print("EL DATO SE MOVIO DESPUES DE EXPORTAR — no es error del deck")
        print("-" * 78)
        for etq, actual, faltan, (rel, commit) in movido:
            fecha, sha, msg = commit.split("|", 2)
            print("  %-34s deck: %-12s hoy: %s" % (etq, actual[:12], ", ".join(faltan)))
            print("  %-34s %s cambio en %s (%s) %s"
                  % ("", rel, fecha[:10], sha, msg[:40]))

    if prohibidas:
        print("\n" + "-" * 78)
        print("ETIQUETA QUE NO VA")
        print("-" * 78)
        for etq, val, motivo in prohibidas:
            print("  %-34s %s" % (etq, val[:40]))
            print("  %-34s %s" % ("", motivo))

    if rotos:
        print("\n" + "-" * 78)
        print("MAPEO ROTO — hay que arreglar reportes_shape_map.json")
        print("-" * 78)
        for etq, motivo in rotos:
            print("  %-34s %s" % (etq, motivo))

    if a.sin_fuente:
        mapeados = set(mapa)
        # diff_reportes_ignore.json ya declara lo que es estatico por naturaleza
        # (anios cerrados, etiquetas de eje, disclaimers). No es lo mismo que
        # "tiene fuente", pero para triage saca el ruido: sin esto la lista del
        # factsheet son 176 lineas dominadas por la tabla historica.
        ign = set(cargar_ignore(deck))
        todos = [(etq, val) for etq, val in sorted(por_etiqueta.items())
                 if TIENE_DIGITO.search(val) and etq not in mapeados]
        huerfanos = [x for x in todos if x[0] not in ign]
        print("\n" + "-" * 78)
        print("SIN FUENTE CONOCIDA — %d numeros sin fuente declarada "
              "(%d mas ya justificados como estaticos en diff_reportes_ignore.json)"
              % (len(huerfanos), len(todos) - len(huerfanos)))
        print("-" * 78)
        for etq, val in huerfanos:
            print("  %-34s %s" % (etq, val[:56]))

    print()
    if difiere or rotos or prohibidas:
        print("RESULTADO: %d problema(s) — revisar antes de mandar"
              % (len(difiere) + len(rotos) + len(prohibidas)))
        sys.exit(1)
    print("RESULTADO: todo lo mapeado coincide con su fuente")
    sys.exit(0)


if __name__ == "__main__":
    main()
