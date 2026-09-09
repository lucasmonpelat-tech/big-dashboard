# -*- coding: utf-8 -*-
"""Corre TODOS los chequeos del cierre de reportes y resume en una sola pantalla.

POR QUE (2026-09-09)
--------------------
Los chequeos son cinco scripts distintos con rutas largas de Dropbox y hay que
acordarse del orden y de contra que mes comparar. Con eso, la probabilidad de
correrlos todos un dia de cierre a las 8 de la noche es baja.

Aca se pasa el mes y listo. El script encuentra los dos decks, encuentra los del
mes anterior para comparar, corre todo y devuelve un resumen.

QUE CORRE
---------
    1. precierre_reportes.py            antiguedad de las fuentes + ancla shape_id
    2. diff_reportes_mensual.py    x2   que numeros quedaron igual que el mes pasado
    3. check_reportes_vs_datos.py  x2   cada numero contra su fuente + etiquetas
    4. check_reportes_cruzados.py       que los dos reportes digan lo mismo
    5. dossier_slides.py           x2   render de las 22 slides + material de revision

Tarda ~7 segundos en total y no consume tokens: es todo local.

SOBRE LOS EXIT CODES
--------------------
Un exit 1 de un chequeo NO es que se rompio: es "hay algo para mirar". El
resumen final distingue las dos cosas. Solo se considera error de verdad cuando
el script no pudo ni correr.

USO
---
    python scripts/verificar_reportes.py                 # el mes mas reciente
    python scripts/verificar_reportes.py --mes Agosto
    python scripts/verificar_reportes.py --mes Agosto --detalle
"""
import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
DROPBOX = os.path.join(os.path.expanduser("~"), "Dropbox", "Banca Privada (1)",
                       "AMC PAMPA CAPITAL")
CARPETAS = {
    "factsheet": os.path.join(DROPBOX, "BIG Factsheets", "2026"),
    "pitchbook": os.path.join(DROPBOX, "BIG Pitch book"),
}
SALIDA = os.path.join(DROPBOX, "_verificacion")

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def decks(carpeta):
    """[(anio, mes, path)] de la carpeta, del mas nuevo al mas viejo."""
    if not os.path.isdir(carpeta):
        return []
    out = []
    for n in os.listdir(carpeta):
        if not n.lower().endswith(".pptx") or n.startswith("~$"):
            continue
        low = n.lower()
        mes = next((i for i, m in enumerate(MESES, 1) if m.lower() in low), None)
        if not mes:
            continue
        anio = re.search(r"\b(20)?(\d{2})\b(?!.*\d)", n)
        out.append((int("20" + anio.group(2)) if anio else 0, mes,
                    os.path.join(carpeta, n)))
    out.sort(reverse=True)
    return out


def elegir(carpeta, mes_pedido):
    """(deck_del_mes, deck_anterior). Cualquiera puede ser None."""
    todos = decks(carpeta)
    if not todos:
        return None, None
    if mes_pedido:
        idx = next((i for i, (_, m, _) in enumerate(todos)
                    if MESES[m - 1].lower() == mes_pedido.lower()), None)
        if idx is None:
            return None, None
    else:
        idx = 0
    actual = todos[idx][2]
    anterior = todos[idx + 1][2] if idx + 1 < len(todos) else None
    return actual, anterior


def correr(nombre, args, detalle):
    t = time.perf_counter()
    # encoding utf-8 explicito: los chequeos hacen
    # sys.stdout.reconfigure(encoding="utf-8"), asi que escriben UTF-8. Sin esto
    # Python los decodifica con la codificacion del sistema (cp1252) y las rayas
    # largas llegan como "a€"" -- despues no hay forma de limpiarlas.
    r = subprocess.run([sys.executable] + args, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    dt = time.perf_counter() - t
    salida = (r.stdout or "") + (r.stderr or "")
    # Un traceback = el script no pudo correr. Un exit 1 limpio = encontro algo.
    reventó = "Traceback (most recent call last)" in salida
    estado = "ROTO" if reventó else ("REVISAR" if r.returncode else "OK")
    print("  [%-7s] %-34s %4.1f s" % (estado, nombre, dt))
    if detalle or reventó:
        for linea in salida.splitlines():
            print("      | " + linea)
    return estado, salida, dt


def resumen_de(salida):
    """Las lineas del output que valen para el resumen final.

    diff_reportes_mensual.py no imprime un 'RESULTADO:', asi que se cuentan los
    items de sus dos secciones que importan: lo que quedo igual que el mes
    pasado, y los separadores decimales raros -- que es la huella que dejo la
    columna 'Inicio' cuando se mando congelada.
    """
    lineas = salida.splitlines()
    utiles = []

    for linea in lineas:
        s = linea.strip()
        if s.startswith("RESULTADO:") or re.match(r"^\d+ fuentes al dia", s):
            utiles.append(s)

    def contar(encabezado):
        try:
            i = next(n for n, l in enumerate(lineas) if l.startswith(encabezado))
        except StopIteration:
            return 0
        n, items = i + 2, 0          # +2: salta el encabezado y su linea de guiones
        while n < len(lineas):
            l = lineas[n]
            if not l.strip() or l.startswith(("-" * 10, "=" * 10)):
                break
            if l.startswith("  ") and "(nada" not in l:
                items += 1
            n += 1
        return items

    iguales = contar("A REVISAR")
    formato = contar("FORMATO")
    if iguales:
        utiles.append("%d numero(s) quedaron IGUAL que el mes pasado, sin justificar"
                      % iguales)
    if formato:
        utiles.append("%d con separador decimal distinto al de sus vecinos "
                      "(la huella del 'Inicio')" % formato)
    return utiles


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mes", default=None,
                    help="Mes en castellano (Agosto). Default: el deck mas reciente.")
    ap.add_argument("--detalle", action="store_true",
                    help="Mostrar la salida completa de cada chequeo.")
    ap.add_argument("--salida", default=SALIDA,
                    help="Donde dejar los renders y dossiers.")
    a = ap.parse_args()

    fs, fs_ant = elegir(CARPETAS["factsheet"], a.mes)
    pb, pb_ant = elegir(CARPETAS["pitchbook"], a.mes)

    if not fs and not pb:
        sys.exit("No encontre ningun deck%s. Revisar %s"
                 % ((" de " + a.mes) if a.mes else "", DROPBOX))

    print("=" * 74)
    print("  VERIFICACION DE REPORTES DE CLIENTE")
    print("=" * 74)
    for etq, act, ant in [("factsheet", fs, fs_ant), ("pitch book", pb, pb_ant)]:
        print("  %-11s %s" % (etq, os.path.basename(act) if act else "(no encontrado)"))
        print("  %-11s vs %s" % ("", os.path.basename(ant) if ant else
                                 "(sin mes anterior: se saltea el diff)"))
    print("=" * 74 + "\n")

    tareas = [("antiguedad de fuentes + ancla", ["scripts/precierre_reportes.py"])]
    if fs and fs_ant:
        tareas.append(("diff vs mes anterior  factsheet",
                       ["scripts/diff_reportes_mensual.py", fs, fs_ant]))
    if pb and pb_ant:
        tareas.append(("diff vs mes anterior  pitchbook",
                       ["scripts/diff_reportes_mensual.py", pb, pb_ant]))
    if fs:
        tareas.append(("deck vs datos  factsheet",
                       ["scripts/check_reportes_vs_datos.py", fs, "--sin-fuente"]))
    if pb:
        tareas.append(("deck vs datos  pitchbook",
                       ["scripts/check_reportes_vs_datos.py", pb, "--sin-fuente"]))
    if fs and pb:
        tareas.append(("los dos reportes dicen lo mismo",
                       ["scripts/check_reportes_cruzados.py", fs, pb]))
    if fs:
        tareas.append(("render + dossier  factsheet",
                       ["scripts/dossier_slides.py", fs, "--out",
                        os.path.join(a.salida, "factsheet")]))
    if pb:
        tareas.append(("render + dossier  pitchbook",
                       ["scripts/dossier_slides.py", pb, "--out",
                        os.path.join(a.salida, "pitchbook")]))

    total, resultados = 0.0, []
    for nombre, args in tareas:
        estado, salida, dt = correr(nombre, args, a.detalle)
        total += dt
        resultados.append((nombre, estado, salida))

    rotos = [n for n, e, _ in resultados if e == "ROTO"]
    revisar = [(n, s) for n, e, s in resultados if e == "REVISAR"]

    print("\n" + "=" * 74)
    print("  RESUMEN  (%.1f s)" % total)
    print("=" * 74)

    if revisar:
        print("\n  PARA MIRAR ANTES DE MANDAR:\n")
        for nombre, salida in revisar:
            print("   * %s" % nombre)
            for linea in resumen_de(salida):
                # La consola de Windows va en cp1252 y algunos chequeos escriben
                # rayas largas; sin esto salen como interrogantes.
                print("       %s" % linea.replace("—", "-").replace("→", "->"))
    if rotos:
        print("\n  CHEQUEOS QUE NO PUDIERON CORRER: %s" % ", ".join(rotos))
        print("  (eso si es un error del script, no del deck)")
    if not revisar and not rotos:
        print("\n  Todo limpio.")

    print("\n  Renders y dossiers en:")
    print("    %s" % a.salida)
    print("  Abri el slideNN.png junto a su slideNN.md para revisar a ojo lo que")
    print("  ningun chequeo puede ver: tortas y barras DIBUJADAS a mano, cuya")
    print("  geometria no sale de ningun dato (solo 5 de las 22 slides tienen")
    print("  un chart real).")
    print()

    sys.exit(1 if (rotos or revisar) else 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
