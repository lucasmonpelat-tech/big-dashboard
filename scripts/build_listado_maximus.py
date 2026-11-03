"""Arma el Listado de posiciones para Maximus (`Listado_Maximus_<Mes> Big Statement.xlsx`).

Copia el listado del mes anterior (conserva formato) y reescribe la columna PERCENT:
    % = mv_usd del holding / (suma de holdings_returns.json + cash)
El cash NO se lista, por eso la suma da ~99,5 y no 100.
Los holdings nuevos van al final; los que ya no estan abiertos se sacan.

Uso:
    python scripts/build_listado_maximus.py --folder 2026-10-31 --mes Octubre
    python scripts/build_listado_maximus.py --folder 2026-09-30 --mes Septiembre --out C:\\tmp   # prueba

--folder es la carpeta de data/canonical. OJO: el cierre de un dia D esta en la carpeta D+1
(el export de la manana trae los precios de D-1): verificar `price_date` en positions.json.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).parent.parent
CARPETA = Path(r"C:\Users\lmonp\Dropbox\Maximus BIG\2026\Export % Maximus")
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
         "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Alts: Maximus ya tiene cargado este id (no es el ISIN de Pershing)
ALT_ID = {"CALP": "LU2837777825", "FLEX": "LU3009548630", "HLEND": "KYG4737U1085",
          "HLGPI": "HLPIF", "GCRED": "GCRED-I", "BPCC": "XS2658535526",
          "GAMCB": "IE00B6WYL972"}
PRIMERA_FILA = 4


def cargar(folder):
    d = json.load(open(ROOT / "data" / "canonical" / folder / "holdings_returns.json", encoding="utf-8"))
    hs = [h for s in d["sleeves"].values() for h in s["holdings"] if h.get("status") == "OPEN"]
    p = json.load(open(ROOT / "data" / "canonical" / folder / "positions.json", encoding="utf-8"))
    cash = next(x["quantity"] for x in p["holdings"] if x.get("security_type") == "Cash")
    return hs, cash, p


def asset_id(h):
    return ALT_ID.get(h["ticker"]) or h.get("isin") or h["ticker"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--mes", required=True, choices=MESES)
    ap.add_argument("--base", help="listado del mes anterior (default: el mas reciente de la carpeta)")
    ap.add_argument("--out", default=str(CARPETA))
    a = ap.parse_args()

    base = Path(a.base) if a.base else max(
        (p for p in CARPETA.glob("Listado_Maximus_*.xlsx") if p.stem != f"Listado_Maximus_{a.mes} Big Statement"),
        key=lambda p: p.stat().st_mtime)
    destino = Path(a.out) / f"Listado_Maximus_{a.mes} Big Statement.xlsx"
    Path(a.out).mkdir(parents=True, exist_ok=True)
    shutil.copy2(base, destino)

    hs, cash, pos = cargar(a.folder)
    total = sum(h["mv_usd"] for h in hs) + cash
    pct = {asset_id(h): (round(100 * h["mv_usd"] / total, 4), h) for h in hs}

    wb = openpyxl.load_workbook(destino)
    ws = wb["Listado"]
    filas = []
    r = PRIMERA_FILA
    while ws.cell(r, 1).value:
        filas.append((ws.cell(r, 1).value, ws.cell(r, 2).value))
        r += 1
    fin_previo = r  # primera fila vacia

    nuevos = [k for k in pct if k not in {f[0] for f in filas}]
    salen = [f for f in filas if f[0] not in pct]
    # orden: los que siguen, en el orden del mes anterior; luego los nuevos
    lista = [(i, n) for i, n in filas if i in pct] + [(k, pct[k][1]["name"]) for k in nuevos]

    # limpiar y reescribir (se conserva el formato de las celdas)
    for rr in range(PRIMERA_FILA, max(fin_previo + 3, PRIMERA_FILA + len(lista) + 3)):
        for c in (1, 2, 4):
            ws.cell(rr, c).value = None
        ws.cell(rr, 9).value = None
    for k, (i, n) in enumerate(lista):
        rr = PRIMERA_FILA + k
        ws.cell(rr, 1).value = i
        ws.cell(rr, 2).value = n
        ws.cell(rr, 4).value = pct[i][0]
    suma = round(sum(pct[i][0] for i, _ in lista), 4)
    ws.cell(PRIMERA_FILA + len(lista) + 1, 4).value = suma
    wb.save(destino)

    print(f"Base: {base.name}")
    print(f"Carpeta canonical: {a.folder} (price_date de IBIT: "
          f"{next((x.get('price_date') for x in pos['holdings'] if x.get('symbol') == 'IBIT'), '?')})")
    print(f"{len(lista)} lineas | suma {suma} | cash {100*cash/total:.3f}% | total ${total:,.0f}")
    if nuevos:
        print("NUEVOS (revisar Asset id/nombre, Maximus puede no tenerlos):",
              [(k, pct[k][1]['name']) for k in nuevos])
    if salen:
        print("SALEN (ya no estan abiertos):", salen)
    print(f"LISTADO_OK {destino}")


if __name__ == "__main__":
    sys.exit(main())
