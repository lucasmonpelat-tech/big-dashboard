"""
build_alts_external.py
======================
Genera data/alts_external.json (y sincroniza el override de YTD) a partir de
data/alts_carlyle_statement.json, que pasa a ser el UNICO input manual de los
holdings alternativos externos a Pershing.

Por que existe (2026-08-26)
---------------------------
CALP se custodia fuera de Pershing, asi que su dato se carga a mano. Estaba
replicado en 3 archivos manuales, cada uno leido por un widget distinto:

  alts_external.json          -> transform -> canonical -> tabla del Overview
                                              y widget "Holdings del Sleeve"
  alts_carlyle_statement.json -> refresh_alts_daily.py -> alts_race.json
                                              (Alts Race + pie del sleeve)
  alts_factsheet_ytd.json     -> el front, columnas "Return YTD" / "YTD as-of"

Nada los sincronizaba. Al cargar el statement de Julio hubo que tocar tres
archivos en tres intentos, y en el medio el dashboard mostro el Overview con
Julio y el Alts Race con Junio. Peor: si se actualizaba uno solo, la
divergencia quedaba para siempre — ningun cron la reconcilia.

Ahora: se edita SOLO alts_carlyle_statement.json (que ademas tiene el historial
completo) y este script deriva el resto.

Los campos que NO vienen del statement (cost basis, fecha de compra,
buys_history, ruta del PDF) se preservan del alts_external.json existente: son
estaticos, no cambian statement a statement.

Uso:
    python scripts/build_alts_external.py            # escribe
    python scripts/build_alts_external.py --check    # solo reporta, no escribe

Despues de correrlo hay que regenerar el canonical para que el cambio llegue a
los widgets:
    python -m dashboard_v2.transform.run_all
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

STATEMENT_JSON = DATA / "alts_carlyle_statement.json"
EXTERNAL_JSON = DATA / "alts_external.json"
FACTSHEET_YTD_JSON = DATA / "alts_factsheet_ytd.json"

# Campos estaticos que se preservan del alts_external.json previo: describen la
# COMPRA de BIG, no el statement del mes.
CAMPOS_ESTATICOS = ("cusip", "unit_cost_usd", "cost_basis_usd",
                    "first_buy_date", "source_file", "sleeve", "buys_history")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ultimo_statement(entries):
    """El statement mas reciente por as_of (no asume que la lista este ordenada)."""
    return max(entries, key=lambda s: str(s.get("as_of") or ""))


def build_holding(ticker, stmt, previo):
    """Arma la entrada de alts_external.json para un ticker."""
    mv = stmt.get("mv_usd")
    cost = previo.get("cost_basis_usd")

    h = {
        "ticker": ticker,
        "name": stmt.get("fund_name") or previo.get("name"),
        "isin": stmt.get("isin") or previo.get("isin"),
    }
    for c in CAMPOS_ESTATICOS:
        h[c] = previo.get(c)

    # Del statement (lo que cambia mes a mes)
    h["qty"] = stmt.get("shares")
    h["last_price_usd"] = stmt.get("nav_per_share")
    h["mv_usd"] = mv
    h["unrealized_gl_usd"] = round(mv - cost, 2) if (mv is not None and cost is not None) else None
    h["return_pct"] = stmt.get("si_return_pct")
    h["ytd_pct"] = stmt.get("ytd_return_pct")
    h["as_of"] = stmt.get("as_of")
    h["source"] = stmt.get("source_doc") or previo.get("source")

    # Chequeo de coherencia del propio statement: shares x NAV deberia dar el MV
    # declarado. Si no cierra, es un typo al cargarlo a mano.
    qty, nav = h["qty"], h["last_price_usd"]
    if qty and nav and mv:
        calc = qty * nav
        if abs(calc - mv) > 1.0:
            print(f"  WARN {ticker}: shares x NAV = {calc:,.2f} pero el statement "
                  f"declara mv_usd = {mv:,.2f} (dif ${abs(calc - mv):,.2f}). "
                  f"Revisar el PDF antes de seguir.")
    return h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="Solo reporta que cambiaria, no escribe")
    args = ap.parse_args()

    stmts = load(STATEMENT_JSON).get("statements", {})
    if not stmts:
        raise SystemExit(f"ERROR: {STATEMENT_JSON.name} no tiene 'statements'")

    ext = load(EXTERNAL_JSON)
    previos = {h.get("ticker"): h for h in ext.get("holdings", [])}

    nuevos, cambios = [], []
    for ticker, entries in stmts.items():
        if not entries:
            print(f"  WARN {ticker}: sin statements, se saltea")
            continue
        stmt = ultimo_statement(entries)
        previo = previos.get(ticker, {})
        if not previo:
            print(f"  NOTA {ticker}: no estaba en alts_external.json — se agrega. "
                  f"Faltan los campos estaticos (cost basis, buys_history): cargarlos a mano.")
        h = build_holding(ticker, stmt, previo)
        nuevos.append(h)

        for campo in ("as_of", "mv_usd", "last_price_usd", "qty", "ytd_pct", "return_pct"):
            antes, ahora = previo.get(campo), h.get(campo)
            if antes != ahora:
                cambios.append(f"{ticker}.{campo}: {antes} -> {ahora}")

    # Los que estaban en alts_external y no tienen statement se preservan tal cual
    sin_stmt = [h for t, h in previos.items() if t not in stmts]
    for h in sin_stmt:
        print(f"  NOTA {h.get('ticker')}: sin statement en {STATEMENT_JSON.name}, "
              f"se deja como estaba")
    nuevos.extend(sin_stmt)

    # ---- sincronizar el override de YTD (solo las entradas con statement) ----
    ytd_doc = load(FACTSHEET_YTD_JSON)
    ovr = ytd_doc.setdefault("overrides", {})
    for h in nuevos:
        isin = h.get("isin")
        if not isin or h.get("ticker") not in stmts:
            continue
        o = ovr.setdefault(isin, {})
        # Solo los campos que hacen a la CORRECCION. `name` y `source` son prosa
        # escrita a mano (suelen explicar de donde sale el numero, mejor que el
        # nombre del PDF) y el guard del validador no los mira: no se pisan.
        for campo, valor in (("ticker", h["ticker"]),
                             ("ytd_pct", h["ytd_pct"]),
                             ("as_of", h["as_of"])):
            if o.get(campo) != valor:
                cambios.append(f"factsheet_ytd[{h['ticker']}].{campo}: {o.get(campo)} -> {valor}")
                o[campo] = valor

    if not cambios:
        print("  Sin cambios: alts_external.json y el override de YTD ya reflejan "
              "el ultimo statement.")
        return

    print(f"  {len(cambios)} cambio(s):")
    for c in cambios:
        print(f"    - {c}")

    if args.check:
        print("\n  --check: no se escribio nada.")
        return

    ext["holdings"] = nuevos
    ext["_description"] = (
        "GENERADO por scripts/build_alts_external.py desde alts_carlyle_statement.json. "
        "NO editar a mano: los cambios se pisan. Para actualizar un holding externo, "
        "agregar el statement nuevo en alts_carlyle_statement.json y correr el script."
    )
    ext["_generated_from"] = STATEMENT_JSON.name
    ext["_updated"] = max((h.get("as_of") or "") for h in nuevos) or ext.get("_updated")
    EXTERNAL_JSON.write_text(json.dumps(ext, indent=2, ensure_ascii=False), encoding="utf-8")
    FACTSHEET_YTD_JSON.write_text(json.dumps(ytd_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n  Escritos: {EXTERNAL_JSON.name} + {FACTSHEET_YTD_JSON.name}")
    print("  Ahora corre `python -m dashboard_v2.transform.run_all` para regenerar")
    print("  el canonical, si no el widget 'Holdings del Sleeve' queda atras.")


if __name__ == "__main__":
    main()
