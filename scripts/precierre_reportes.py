# -*- coding: utf-8 -*-
"""Chequeo PRE-cierre: lo que se puede resolver antes del dia del cierre.

POR QUE (2026-09-09)
--------------------
Hoy todo se hace el mismo dia y llega todo junto: refrescar factsheets externos,
armar el deck, revisarlo, mandarlo. Cuando aparece que un factsheet esta vencido
ya es tarde para conseguirlo, y se manda con el dato viejo.

Pero casi nada de eso depende del cierre. Corriendo esto alrededor del 25 queda
una semana para resolver lo que falte.

QUE MIRA
--------
1. ANTIGUEDAD DE LAS FUENTES EXTERNAS
   Cada dato que viene de afuera (factsheets de fondos, factsheet del benchmark)
   trae su fecha. Se listan las vencidas y las que se apoyan en un proxy.
   Dos casos abiertos al 2026-09-09:
     - el benchmark de renta fija sale del factsheet de iShares AGG al 30-Jun
     - PIMCO Low Duration UCITS (IE00BDT57R20) no publica factsheet propio: se
       usa el fondo hermano US (PFIIX) como proxy. Cargar el real sube la
       confianza del sub-asset class de 64% a 92.5%

2. QUE LOS shape_id SIGAN SIENDO UN ANCLA VALIDA
   diff_reportes_mensual.py compara por shape_id, que es estable PORQUE el deck
   del mes se copia del anterior. Si alguien reordena o rehace shapes en
   PowerPoint, el ancla se pierde: el diff deja de encontrar el shape y no tiene
   con que comparar. Callado. Se compara el ultimo deck contra el anterior para
   ver si el ancla aguanto.

USO
---
    python scripts/precierre_reportes.py
    python scripts/precierre_reportes.py --dias 120

Exit code 1 si hay algo vencido o si el ancla de shape_id se degrado.
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diff_reportes_mensual import recolectar  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DROPBOX = os.path.join(os.path.expanduser("~"), "Dropbox", "Banca Privada (1)",
                       "AMC PAMPA CAPITAL")
DECKS = {
    "factsheet": os.path.join(DROPBOX, "BIG Factsheets", "2026"),
    "pitchbook": os.path.join(DROPBOX, "BIG Pitch book"),
}

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Cuantos dias puede tener un factsheet antes de molestar. La mayoria de los
# managers publica mensual o trimestral; 100 dias deja pasar un trimestre con
# margen y marca lo que se quedo de verdad.
DIAS_DEFAULT = 100
# Por encima de esto ya no es un aviso, es un problema.
DIAS_GRAVE = 180


MES_EN = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def parsear_fecha(txt):
    """ISO, o '31 March 2026' / 'As at 31 March 2026' como vienen de algunos
    factsheets. Devuelve ISO o None.

    Los archivos de equity traian el as_of scrapeado mal ('16 2017 2018',
    '21 2022 2023'): son filas de una tabla de performance, no una fecha. Esos
    quedan en None a proposito, para que se vean.
    """
    if not txt:
        return None
    t = str(txt).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return t
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", t)
    if m and m.group(2).lower() in MES_EN:
        return "%s-%02d-%02d" % (m.group(3), MES_EN[m.group(2).lower()],
                                 int(m.group(1)))
    return None


def dias_desde(txt):
    iso = parsear_fecha(txt)
    if not iso:
        return None
    try:
        return (date.today() - date.fromisoformat(iso)).days
    except Exception:
        return None


def cargar(rel):
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def fuentes_externas():
    """[(que, fecha_iso, detalle)] de todo dato externo con fecha declarada."""
    out = []

    # Factsheet por fondo: data/funds/<TICKER>.json
    carpeta = os.path.join(ROOT, "data", "funds")
    for nombre in sorted(os.listdir(carpeta)):
        if not nombre.endswith(".json"):
            continue
        d = cargar("data/funds/" + nombre)
        f = d.get("as_of_factsheet")
        tk = d.get("ticker", nombre)
        if not f:
            out.append((("fondo %s" % tk), None,
                        "sin as_of_factsheet — %s" % (d.get("source") or "?")))
        else:
            out.append((("fondo %s" % tk), f, d.get("name", "")[:44]))

    # Composicion sub-asset por fondo, con su nivel de confianza
    lk = cargar("data/fi_subasset_lookup.json")
    for isin, f in lk.get("funds", {}).items():
        conf = f.get("confidence")
        detalle = f.get("name", "")[:40]
        if conf and conf != "high":
            detalle += "  [confianza %s]" % conf
        out.append((("sub-asset %s" % (f.get("name") or isin)[:28]),
                    f.get("factsheet_date"), detalle))

    # Benchmark de renta fija (iShares AGG) y secciones del breakdown
    fb = cargar("data/fi_breakdown_latest.json")
    for seccion, campo in [("fi_stats", "bmk_as_of"),
                           ("credit_quality", "bmk_as_of"),
                           ("sub_asset_class", "agg_as_of"),
                           ("regional", "as_of")]:
        blk = fb.get(seccion) or {}
        # iShares publica el factsheet del AGG todos los meses, asi que 45 dias
        # ya es viejo -- con el umbral general de 100 no se veria nunca.
        det = blk.get("bmk_fuente") or blk.get("agg_fuente") or "seccion del breakdown"
        if campo != "as_of":
            det += "  [cadencia 45d]"
        out.append((("bmk FI / %s" % seccion), blk.get(campo), det))

    # Breakdown de renta variable
    try:
        eb = cargar("data/equity_breakdown_latest.json")
        out.append(("equity breakdown", eb.get("asOf"), "estilo / sectorial / regional"))
    except Exception:
        pass

    return out


def revisar_fuentes(dias_aviso):
    print("=" * 78)
    print("1 - ANTIGUEDAD DE LAS FUENTES EXTERNAS")
    print("=" * 78)

    vencidas, graves, sin_fecha, ok = [], [], [], []
    for que, fecha, detalle in fuentes_externas():
        if not fecha:
            sin_fecha.append((que, detalle))
            continue
        d = dias_desde(fecha)
        cad = re.search(r"\[cadencia (\d+)d\]", detalle)
        umbral = int(cad.group(1)) if cad else dias_aviso
        if d is None:
            sin_fecha.append((que, "fecha no confiable: %r" % fecha))
        elif d >= DIAS_GRAVE:
            graves.append((que, fecha, d, detalle))
        elif d >= umbral:
            vencidas.append((que, fecha, d, detalle))
        else:
            ok.append((que, fecha, d, detalle))

    if graves:
        print("\n  MUY VIEJAS (mas de %d dias)" % DIAS_GRAVE)
        for que, fecha, d, det in sorted(graves, key=lambda x: x[2], reverse=True):
            print("    %-38s %s  %4d dias  %s" % (que, fecha, d, det))
    if vencidas:
        print("\n  VENCIDAS (mas de %d dias)" % dias_aviso)
        for que, fecha, d, det in sorted(vencidas, key=lambda x: x[2], reverse=True):
            print("    %-38s %s  %4d dias  %s" % (que, fecha, d, det))
    if sin_fecha:
        print("\n  SIN FECHA DECLARADA — no se puede saber si estan al dia")
        for que, det in sin_fecha:
            print("    %-38s %s" % (que, det))

    proxies = [(q, f, d, det) for q, f, d, det in ok + vencidas + graves
               if "confianza" in det]
    if proxies:
        print("\n  APOYADAS EN UN PROXY O ESTIMACION")
        for que, fecha, d, det in proxies:
            print("    %-38s %s  %s" % (que, fecha, det))

    print("\n  %d fuentes al dia | %d vencidas | %d muy viejas | %d sin fecha"
          % (len(ok), len(vencidas), len(graves), len(sin_fecha)))
    return len(vencidas) + len(graves) + len(sin_fecha)


def decks_ordenados(carpeta):
    """Los .pptx de la carpeta, del mas nuevo al mas viejo, por mes del nombre."""
    if not os.path.isdir(carpeta):
        return []
    encontrados = []
    for n in os.listdir(carpeta):
        if not n.lower().endswith(".pptx") or n.startswith("~$"):
            continue
        low = n.lower()
        mes = next((i for i, m in enumerate(MESES, 1) if m.lower() in low), None)
        anio = re.search(r"\b(20)?(\d{2})\b(?!.*\d)", n)
        if mes:
            encontrados.append(((int("20" + anio.group(2)) if anio else 0, mes),
                                os.path.join(carpeta, n)))
    encontrados.sort(reverse=True)
    return [p for _, p in encontrados]


def revisar_ancla():
    print("\n" + "=" * 78)
    print("2 - EL shape_id SIGUE SIENDO UN ANCLA VALIDA")
    print("=" * 78)
    print("  (si el ultimo cierre reordeno shapes, el diff del mes que viene se")
    print("   queda sin con que comparar y no avisa)")

    problemas = 0
    for deck, carpeta in DECKS.items():
        archivos = decks_ordenados(carpeta)
        if len(archivos) < 2:
            print("\n  %-10s no hay dos decks para comparar en %s" % (deck, carpeta))
            continue
        nuevo, viejo = archivos[0], archivos[1]
        a, b = recolectar(nuevo), recolectar(viejo)
        comunes = set(a) & set(b)
        total = max(len(a), len(b))
        pct = 100.0 * len(comunes) / total if total else 0

        print("\n  %s" % deck)
        print("    %s  vs  %s" % (os.path.basename(nuevo), os.path.basename(viejo)))
        print("    %d de %d shapes en comun (%.0f%%)" % (len(comunes), total, pct))
        if pct < 85:
            problemas += 1
            print("    PROBLEMA: el ancla se degrado. Revisar si se rehicieron shapes.")
            perdidos = sorted(set(b) - set(a), key=str)[:8]
            for k in perdidos:
                print("      ya no esta: %-34s %s" % (b[k][0], b[k][1][:28]))
        else:
            print("    OK: el ancla aguanta.")
    return problemas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dias", type=int, default=DIAS_DEFAULT,
                    help="a partir de cuantos dias avisar (default %d)" % DIAS_DEFAULT)
    ap.add_argument("--solo-fuentes", action="store_true",
                    help=("saltear el chequeo de decks. Lo usa el job de GitHub: "
                          "los pptx viven en Dropbox y el runner no los ve."))
    ap.add_argument("--alerta", default=None,
                    help="si hay hallazgos, escribir un JSON de alerta en este path")
    a = ap.parse_args()

    print("CHEQUEO PRE-CIERRE  %s\n" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    n_fuentes = revisar_fuentes(a.dias)
    n_ancla = 0 if a.solo_fuentes else revisar_ancla()
    if a.solo_fuentes:
        print("\n" + "=" * 78)
        print("2 - ANCLA DE shape_id: SALTEADO")
        print("=" * 78)
        print("  Los decks estan en Dropbox y este entorno no los ve.")
        print("  Correr localmente: python scripts/precierre_reportes.py")

    print("\n" + "=" * 78)
    if n_fuentes or n_ancla:
        print("RESULTADO: %d fuente(s) para revisar, %d problema(s) de ancla."
              % (n_fuentes, n_ancla))
        print("Hay tiempo hasta el cierre: por eso esto corre el 25 y no el 31.")
        if a.alerta:
            vencidas = []
            for q, f, det in fuentes_externas():
                d = dias_desde(f) if f else None
                if d is not None and d >= a.dias:
                    vencidas.append((q, f, d, det))
            os.makedirs(os.path.dirname(a.alerta), exist_ok=True)
            with io.open(a.alerta, "w", encoding="utf-8") as fh:
                json.dump({
                    "date": date.today().isoformat(),
                    "tipo": "precierre_fuentes_vencidas",
                    "issues": ["%s: %s (%d dias) %s" % (q, f, d, det)
                               for q, f, d, det in sorted(vencidas,
                                                          key=lambda x: x[2],
                                                          reverse=True)],
                    "accion": ("Conseguir los factsheets vencidos ANTES del cierre. "
                               "Quedan unos 6 dias."),
                }, fh, indent=2, ensure_ascii=False)
            print("Alerta escrita en %s" % a.alerta)
        sys.exit(1)
    print("RESULTADO: todo al dia.")
    sys.exit(0)


if __name__ == "__main__":
    main()
