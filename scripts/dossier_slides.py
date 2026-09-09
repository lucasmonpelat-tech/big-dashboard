# -*- coding: utf-8 -*-
"""Arma, por slide, el material que necesita un revisor para mirarla en serio.

POR QUE ASI Y NO "MIRA SI ESTA BIEN" (2026-09-09)
-------------------------------------------------
Pedirle a un revisor -- persona o agente -- que mire una slide y opine, devuelve
ruido: encuentra cosas que no son, y se le pasan las que si. La pregunta abierta
no sirve.

Lo que si sirve es darle las dos mitades y pedirle que las cruce:
  "esta es la imagen, estos son los numeros que segun el mapa tienen que estar
   ahi, y estos son los que aparecen en la slide sin fuente conocida.
   Listame las discrepancias."

Eso convierte el juicio estetico en una comparacion.

QUE GENERA
----------
Por cada slide, en el directorio de salida:
    slideNN.png          la imagen renderizada
    slideNN.md           el dossier: valores esperados, texto extraido, huerfanos

Las dos cosas juntas alcanzan para revisar una slide sin abrir PowerPoint.

QUE COSAS SOLO SE VEN EN LA IMAGEN
----------------------------------
El texto del XML puede estar perfecto y la slide estar mal igual:
  - una etiqueta de grafico con valores de Julio al lado de una tabla de Agosto
  - un valor desalineado respecto de su encabezado (factsheet slide 2 shapes
    61/62; pitch book slide 10 shape 36 -- heredados del template desde Abril)
Nada de eso deja rastro en el texto. Por eso va la imagen.

Y OJO CON EL PDF
----------------
No sirve buscar strings en el PDF: las autoshapes del pitch book se exportan
vectorizadas y no devuelven texto (en la slide 10 no se extrae ni "ASSET
ALLOCATION"). El texto de este dossier sale del .pptx, no del PDF.

USO
---
    python scripts/dossier_slides.py <deck.pptx> --out DIR
    python scripts/dossier_slides.py <deck.pptx> --out DIR --slides 2,10
"""
import argparse
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diff_reportes_mensual import recolectar, TIENE_DIGITO, cargar_ignore  # noqa: E402
from check_reportes_vs_datos import resolver, formatear, MAPA_FILE  # noqa: E402
from render_slides import render  # noqa: E402


def slide_de(etiqueta):
    """'s10 chart id=211 ...' -> 10"""
    try:
        return int(etiqueta.split()[0][1:])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pptx")
    ap.add_argument("--out", required=True)
    ap.add_argument("--deck", default=None)
    ap.add_argument("--slides", default=None)
    ap.add_argument("--dpi", type=int, default=150)
    a = ap.parse_args()

    deck = a.deck or ("factsheet" if "factsheet" in os.path.basename(a.pptx).lower()
                      else "pitchbook")
    solo = {int(x) for x in a.slides.split(",")} if a.slides else None

    os.makedirs(a.out, exist_ok=True)
    print("Renderizando...")
    render(a.pptx, a.out, a.dpi, solo)

    with io.open(MAPA_FILE, encoding="utf-8") as f:
        mapa = json.load(f).get(deck, {})
    ign = set(cargar_ignore(deck))

    contenido = recolectar(a.pptx)
    por_etiqueta = {etq: val for etq, val in contenido.values()}

    # agrupar por slide
    esperado_por_slide, texto_por_slide = {}, {}
    for etq, decl in mapa.items():
        if etq.startswith("_"):
            continue
        n = slide_de(etq)
        if n is None:
            continue
        specs = decl.get("fuentes") or ([decl["fuente"]] if decl.get("fuente") else [])
        fmts = decl.get("formatos") or [decl.get("formato")] * len(specs)
        vals = []
        for spec, fmt in zip(specs, fmts):
            try:
                v, _ = resolver(spec)
                vals.append((formatear(v, fmt), spec))
            except Exception as e:
                vals.append(("<no resuelve: %s>" % e, spec))
        esperado_por_slide.setdefault(n, []).append((etq, vals, decl.get("nota")))

    for etq, val in por_etiqueta.items():
        n = slide_de(etq)
        if n is not None:
            texto_por_slide.setdefault(n, []).append((etq, val))

    escritos = 0
    for n in sorted(set(list(esperado_por_slide) + list(texto_por_slide))):
        if solo and n not in solo:
            continue
        png = os.path.join(a.out, "slide%02d.png" % n)
        if not os.path.exists(png):
            continue
        L = []
        L.append("# %s - slide %d\n" % (deck, n))
        L.append("Imagen: `slide%02d.png`\n" % n)

        esp = esperado_por_slide.get(n, [])
        L.append("\n## Valores con fuente declarada\n")
        if not esp:
            L.append("\n_Ninguno mapeado en esta slide todavia._\n")
        else:
            L.append("\n| shape | en la slide | esperado segun el dato | fuente |")
            L.append("\n|---|---|---|---|")
            for etq, vals, nota in sorted(esp):
                actual = por_etiqueta.get(etq, "<no esta>")
                L.append("\n| `%s` | %s | %s | %s |"
                         % (etq, actual,
                            " + ".join(v for v, _ in vals),
                            "<br>".join(s.split("::")[-1].strip() for _, s in vals)))
                if nota:
                    L.append("\n| | | | _%s_ |" % nota)
            L.append("\n")

        huerf = [(e, v) for e, v in sorted(texto_por_slide.get(n, []))
                 if TIENE_DIGITO.search(v)
                 and e not in mapa and e not in ign]
        L.append("\n## Numeros SIN fuente declarada (%d)\n" % len(huerf))
        L.append("\nNo se pueden verificar contra un archivo. Mirar que sean "
                 "coherentes con el resto de la slide.\n")
        for e, v in huerf:
            L.append("\n- `%s` -> %s" % (e, v[:70]))

        dest = os.path.join(a.out, "slide%02d.md" % n)
        with io.open(dest, "w", encoding="utf-8") as f:
            f.write("".join(L) + "\n")
        escritos += 1

    print("\n  %d dossier(s) escritos en %s" % (escritos, a.out))


if __name__ == "__main__":
    main()
