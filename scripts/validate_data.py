"""
validate_data.py
================
Validador de consistencia de datos del BIG Dashboard.

Caza errores SILENCIOSOS — los que no rompen nada visiblemente pero corrompen
los numeros (ej: un ISIN mal escrito hace que un fondo desaparezca de un tab
sin tirar error).

Chequea:
  1. ORPHAN ISINs   — ISINs en los dicts que ya no estan en cartera
  2. MISSING ISINs  — fondos en cartera que faltan en un dict donde deberian estar
  3. EXPOSURE SUMS  — CURRENCY/COUNTRY deben sumar ~100% por fondo

El universo de "que hay en cartera" sale de data/positions_latest.json, que se
refresca solo todos los dias. Hasta el 2026-08-24 salia del array manual
BIG_POSITIONS (funds_metadata.js), que quedaba viejo y generaba errores falsos.

Exit code 0 = todo OK. Exit code 1 = hay errores (gatea el deploy).

Usage:
    python scripts/validate_data.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
META_JS = ROOT / "data" / "funds_metadata.js"
POSITIONS_JSON = ROOT / "data" / "positions_latest.json"

SLEEVE_LABEL = {"equity": "Equity", "fixed_income": "Fixed Income",
                "alternatives": "Alternatives"}

# Claves que existen en los dicts pero no son fondos en cartera: no tiene
# sentido pedirles factsheet ni exposicion, y tampoco marcarlas como
# huerfanas cuando no aparecen en las posiciones.
NON_FUND_KEYS = {"CASH-USD"}

# ---- Holdings externos a Pershing (statements manuales) ---------------------
# Un holding "external_statement" (hoy solo CALP, custodiado fuera de Pershing)
# se carga A MANO y su dato termina replicado en 4 archivos, cada uno leido por
# un widget distinto. Si se actualiza uno solo, el dashboard muestra data
# mezclada (Overview con el mes nuevo, Alts Race con el viejo) y NADA lo
# reconcilia: ningun cron los sincroniza y el deploy pasa igual.
# Paso el 2026-08-26 al cargar el statement de Julio de CALP.
ALTS_EXTERNAL_JSON = ROOT / "data" / "alts_external.json"
ALTS_STATEMENT_JSON = ROOT / "data" / "alts_carlyle_statement.json"
ALTS_FACTSHEET_YTD_JSON = ROOT / "data" / "alts_factsheet_ytd.json"

# Los MV se copian textual del mismo statement, asi que tienen que ser
# identicos. Tolerancia sub-centavo: absorbe ruido de float (~1e-9) pero un
# centavo real de diferencia FALLA. Con 0.01 no fallaba: |0.01| no es > 0.01.
MV_TOLERANCE_USD = 0.005
PCT_TOLERANCE = 0.005

# Tolerancia para sumas de exposicion (%)
SUM_TOLERANCE = 1.5
# Tolerancia para comparar valores USD entre las dos fuentes de posiciones
VALUE_TOLERANCE_USD = 1.0


def read_meta_js():
    """Lee funds_metadata.js como texto."""
    return META_JS.read_text(encoding="utf-8")


def extract_block(text, const_name):
    """Extrae el cuerpo de un `const NAME = {...}` o `const NAME = [...]`."""
    # Encuentra el inicio
    m = re.search(rf"const\s+{re.escape(const_name)}\s*=\s*", text)
    if not m:
        return None
    start = m.end()
    open_char = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def extract_isin_keys(block):
    """Extrae las keys (ISINs) de un bloque tipo objeto JS: '"KEY": ...'."""
    if not block:
        return []
    # Match keys: "XXXX": al inicio de cada entry
    return re.findall(r'"([A-Za-z0-9\-]+)"\s*:', block)


def read_positions():
    """Universo de fondos en cartera, desde positions_latest.json.

    CAMBIO 2026-08-24: antes esto salia de BIG_POSITIONS, un array a mano
    dentro de funds_metadata.js con un snapshot congelado (ultimo update real
    2026-06-10). Como positions_latest.json se refresca solo todos los dias
    desde Pershing/NetX360, el array manual quedaba viejo y el validador
    escupia 30+ errores falsos por puro drift. BIG_POSITIONS se borro junto
    con el dashboard v1; la unica fuente de verdad de que hay en cartera es
    este JSON.
    """
    if not POSITIONS_JSON.exists():
        return []
    pj = json.loads(POSITIONS_JSON.read_text(encoding="utf-8"))
    out = [
        {
            "isin": pos["isin"],
            "ticker": pos.get("ticker", "?"),
            "sleeve": pos.get("sleeve", "?"),
            "value": pos.get("value"),
        }
        for pos in pj.get("positions", [])
        if pos.get("isin")
    ]

    # positions_latest.json es el espejo del export de Pershing, y hay
    # holdings que NO estan en Pershing (CALP se custodia afuera). Sin esto,
    # CALP -- 32% del sleeve alts -- daria "ISIN huerfano" en cada dict.
    seen = {o["isin"] for o in out}
    for h in _canonical_holdings():
        if h["isin"] and h["isin"] not in seen:
            out.append(h)
            seen.add(h["isin"])
    return out


def _canonical_holdings():
    """Holdings abiertos del ultimo snapshot canonical (incluye externos)."""
    snaps = sorted((ROOT / "data" / "canonical").glob("*/holdings_returns.json"))
    if not snaps:
        return []
    d = json.loads(snaps[-1].read_text(encoding="utf-8"))
    out = []
    for sleeve_key, sleeve in d.get("sleeves", {}).items():
        for h in sleeve.get("holdings", []):
            if (h.get("status") or "OPEN") != "OPEN":
                continue
            out.append({
                "isin": h.get("isin"),
                "ticker": h.get("ticker", "?"),
                "sleeve": SLEEVE_LABEL.get(sleeve_key, sleeve_key),
                "value": h.get("mv_usd"),
            })
    return out


def extract_exposure_sums(block):
    """Para CURRENCY/COUNTRY/SECTOR: devuelve {isin: suma_de_p}."""
    if not block:
        return {}
    sums = {}
    # Cada entry: "ISIN": [ ... {..p:NN..} ... ]  o  "ISIN": { exposures: [...] }
    # Partimos por las keys de ISIN
    entries = re.split(r'(?="[A-Za-z0-9\-]+"\s*:)', block)
    for entry in entries:
        key_m = re.match(r'\s*"([A-Za-z0-9\-]+)"\s*:', entry)
        if not key_m:
            continue
        isin = key_m.group(1)
        # sumar todos los p:NN del entry
        ps = [float(x) for x in re.findall(r"p:\s*([\d.]+)", entry)]
        if ps:
            sums[isin] = round(sum(ps), 2)
    return sums


def latest_canonical():
    """(path, dict) del snapshot canonical mas reciente, o (None, None)."""
    snaps = sorted((ROOT / "data" / "canonical").glob("*/holdings_returns.json"))
    if not snaps:
        return None, None
    return snaps[-1], json.loads(snaps[-1].read_text(encoding="utf-8"))


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_external_statements(errors, warnings):
    """Los 4 archivos de un holding externo tienen que contar la misma historia.

    Compara, para cada holding del canonical con _mv_source == "external_statement":
      canonical  <-> alts_external.json        (as_of + mv_usd)
      canonical  <-> alts_carlyle_statement    (as_of + mv_usd del ultimo statement)
      canonical  <-> alts_factsheet_ytd        (as_of + ytd_pct)

    NO se hardcodea ningun ticker: el universo sale del propio canonical.
    """
    print("\n" + "-" * 70)
    print("  4 — Holdings externos: los 4 archivos en sincronia")
    print("-" * 70)

    canon_path, canon = latest_canonical()
    if not canon:
        warnings.append("no hay snapshot canonical — skip check de externos")
        print("  [WARN] sin snapshot canonical")
        return

    externos = [
        h for sl in canon.get("sleeves", {}).values()
        for h in sl.get("holdings", [])
        if h.get("_mv_source") == "external_statement"
    ]
    if not externos:
        print("  [OK]    no hay holdings con _mv_source='external_statement'")
        return

    ext_data = _load(ALTS_EXTERNAL_JSON) or {}
    ext_by_isin = {h.get("isin"): h for h in ext_data.get("holdings", []) if h.get("isin")}
    stmts = (_load(ALTS_STATEMENT_JSON) or {}).get("statements", {})
    ytd_ovr = (_load(ALTS_FACTSHEET_YTD_JSON) or {}).get("overrides", {})

    def diff(a, b, tol):
        if a is None or b is None:
            return a != b
        return abs(a - b) > tol

    for h in externos:
        tk, isin = h.get("ticker"), h.get("isin")
        c_asof, c_mv, c_ytd = h.get("_as_of"), h.get("mv_usd"), h.get("ytd_pct")
        problemas = []

        # --- alts_external.json: es de donde el transform DERIVA el canonical ---
        e = ext_by_isin.get(isin)
        if e is None:
            errors.append(f"externos[{tk}]: no esta en alts_external.json (el canonical lo tiene)")
        else:
            if e.get("as_of") != c_asof:
                problemas.append(f"alts_external.as_of={e.get('as_of')} vs canonical._as_of={c_asof}")
            if diff(e.get("mv_usd"), c_mv, MV_TOLERANCE_USD):
                problemas.append(f"alts_external.mv_usd={e.get('mv_usd')} vs canonical={c_mv}")

        # --- alts_carlyle_statement.json: historial de statements ---
        arr = stmts.get(tk)
        if not arr:
            warnings.append(f"externos[{tk}]: sin entrada en {ALTS_STATEMENT_JSON.name} "
                            f"(no se puede cruzar el statement)")
        else:
            last = max(arr, key=lambda s: str(s.get("as_of") or ""))
            if last.get("as_of") != c_asof:
                problemas.append(f"statement.as_of={last.get('as_of')} vs canonical._as_of={c_asof}")
            if diff(last.get("mv_usd"), c_mv, MV_TOLERANCE_USD):
                problemas.append(f"statement.mv_usd={last.get('mv_usd')} vs canonical={c_mv}")

        # --- alts_factsheet_ytd.json: override de YTD que consume el front ---
        o = ytd_ovr.get(isin)
        if o is None:
            warnings.append(f"externos[{tk}]: sin override en {ALTS_FACTSHEET_YTD_JSON.name}")
        else:
            if o.get("as_of") != c_asof:
                problemas.append(f"factsheet_ytd.as_of={o.get('as_of')} vs canonical._as_of={c_asof}")
            if diff(o.get("ytd_pct"), c_ytd, PCT_TOLERANCE):
                problemas.append(f"factsheet_ytd.ytd_pct={o.get('ytd_pct')} vs canonical={c_ytd}")

        if problemas:
            print(f"  [ERROR] {tk:6} DIVERGENTE ({len(problemas)})")
            for p in problemas:
                errors.append(f"externos[{tk}]: {p}")
        else:
            print(f"  [OK]    {tk:6} as_of={c_asof}  MV=${c_mv:,.2f}  (4 archivos coinciden)")

    if any(e.startswith("externos[") for e in errors):
        print()
        print("         Si el canonical quedo atras: corre refresh_dashboard_v2.bat")
        print("         (o `python -m dashboard_v2.transform.run_all`) para regenerarlo.")
        print(f"         Canonical usado: {canon_path.parent.name}")


def main():
    print("=" * 70)
    print("  BIG Dashboard — Data Consistency Validator")
    print("=" * 70)

    text = read_meta_js()
    errors = []
    warnings = []

    # ---- Universo de fondos en cartera (positions_latest.json) ----
    positions = read_positions()
    if not positions:
        print("[FATAL] No pude leer positions_latest.json (o vino vacio)")
        sys.exit(1)
    big_isins = {pp["isin"] for pp in positions}
    equity_isins = {pp["isin"] for pp in positions if pp["sleeve"] == "Equity"}
    fi_isins = {pp["isin"] for pp in positions if pp["sleeve"] == "Fixed Income"}
    print(f"\npositions_latest.json: {len(positions)} fondos "
          f"({len(equity_isins)} equity, {len(fi_isins)} FI, "
          f"{len(big_isins) - len(equity_isins) - len(fi_isins)} alts/cash)")

    # ---- 1 & 2: ORPHAN / MISSING ISINs en cada dict ----
    # (dict_name, debe_cubrir_isins, label, severity)
    #   severity "error"   -> gatea el deploy
    #   severity "warning" -> solo avisa (dicts opcionales / data muerta)
    checks = [
        ("FACTSHEET_LINKS", big_isins - {"CASH-USD"}, "todos (menos cash)", "error"),
        ("CURRENCY_EXPOSURE", big_isins, "todos los fondos", "error"),
        ("CURRENT_YIELD", big_isins, "todos los fondos", "error"),
        ("COUNTRY_EXPOSURE", big_isins, "todos los fondos", "error"),
        # FI_METRICS migrado a data/funds/<TICKER>.json — chequeado abajo en check separado.
        # SECTOR_EXPOSURE: borrado el 2026-05-15 (era data muerta).
    ]

    print("\n" + "-" * 70)
    print("  1 & 2 — Cobertura de ISINs por diccionario")
    print("-" * 70)
    for dict_name, should_cover, label, severity in checks:
        block = extract_block(text, dict_name)
        if block is None:
            errors.append(f"{dict_name}: no se encontro el bloque")
            continue
        keys = set(extract_isin_keys(block))

        orphans = keys - big_isins - NON_FUND_KEYS
        missing = should_cover - keys
        bucket = errors if severity == "error" else warnings

        status = "OK"
        if orphans:
            status = severity.upper()
            for o in sorted(orphans):
                bucket.append(f"{dict_name}: ISIN huerfano '{o}' (no esta en positions_latest.json)")
        if missing:
            status = severity.upper() if status == "OK" else status
            for m in sorted(missing):
                tk = next((p["ticker"] for p in positions if p["isin"] == m), "?")
                bucket.append(f"{dict_name}: falta ISIN '{m}' ({tk}) — esperado [{label}]")

        flag = {"OK": "[OK]   ", "ERROR": "[ERROR]", "WARNING": "[WARN] "}[status]
        print(f"  {flag} {dict_name:20s} {len(keys):2d} keys  "
              f"(orphans: {len(orphans)}, missing: {len(missing)})")

    # ---- 2b: FI_METRICS migrado a data/funds/<TICKER>.json ----
    print("\n" + "-" * 70)
    print("  2b — FI metrics en data/funds/*.json (single source de YTW/Dur/Maturity)")
    print("-" * 70)
    funds_dir = ROOT / "data" / "funds"
    fi_funds = [p for p in positions if p["sleeve"] == "Fixed Income"]
    fi_missing_json = []
    fi_missing_metrics = []
    for fp in fi_funds:
        fpath = funds_dir / f"{fp['ticker']}.json"
        if not fpath.exists():
            fi_missing_json.append(fp["ticker"])
            errors.append(f"data/funds/{fp['ticker']}.json no existe (FI fund {fp['isin']})")
            continue
        try:
            d = json.loads(fpath.read_text(encoding="utf-8"))
            # Skip fi_metrics validation para fondos pendientes de factsheet
            # (posiciones piloto recien abiertas). Marcador: as_of_factsheet == null.
            if d.get("as_of_factsheet") is None:
                continue
            fm = d.get("fi_metrics", {})
            for required in ["ytw", "duration", "maturity"]:
                if fm.get(required) is None:
                    fi_missing_metrics.append(f"{fp['ticker']}.json falta fi_metrics.{required}")
                    errors.append(f"data/funds/{fp['ticker']}.json: falta fi_metrics.{required}")

            # ---- Check de plausibilidad para CAT BONDS / ILS ----
            # Los cat bonds son floating-rate (SOFR+spread) -> duration de tasa ~0,
            # weighted avg life ~2-3y, sin rating crediticio tradicional. Si un cat
            # bond reporta duration de bono tradicional (>1.5y) o rating IG, es
            # señal de datos placeholder/cruzados (paso con SGCB: dur 4.03 / BBB+).
            name_l = (d.get("name") or "").lower()
            is_cat = d.get("is_cat_bond") or "cat bond" in name_l or "ils" in name_l or "insurance-linked" in name_l
            if is_cat:
                dur = fm.get("duration")
                if dur is not None and dur > 1.5:
                    errors.append(f"data/funds/{fp['ticker']}.json: CAT BOND con duration {dur}y (>1.5) — "
                                  f"implausible, los cat bonds son floating (dur ~0). Verificar factsheet real.")
                rating = (fm.get("rating") or "").upper()
                IG = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"}
                if rating in IG:
                    errors.append(f"data/funds/{fp['ticker']}.json: CAT BOND con rating IG '{rating}' — "
                                  f"implausible, los cat bonds son sub-IG/sin rating (usar 'NR'). Verificar factsheet.")
        except Exception as e:
            errors.append(f"data/funds/{fp['ticker']}.json: error de parse — {e}")

    if fi_missing_json or fi_missing_metrics:
        print(f"  [ERROR] {len(fi_funds)} FI funds — {len(fi_missing_json)} sin JSON, {len(fi_missing_metrics)} sin metricas completas")
    else:
        print(f"  [OK]    {len(fi_funds)} FI funds — todos tienen JSON con fi_metrics completas (ytw/duration/maturity)")

    # ---- 3: EXPOSURE SUMS ----
    print("\n" + "-" * 70)
    print("  3 — Sumas de exposicion (~100% por fondo)")
    print("-" * 70)
    for dict_name in ["CURRENCY_EXPOSURE", "COUNTRY_EXPOSURE"]:
        block = extract_block(text, dict_name)
        sums = extract_exposure_sums(block)
        bad = {k: v for k, v in sums.items() if abs(v - 100) > SUM_TOLERANCE}
        if bad:
            for isin, total in sorted(bad.items()):
                tk = next((p["ticker"] for p in positions if p["isin"] == isin), "?")
                errors.append(f"{dict_name}: '{isin}' ({tk}) suma {total}% (deberia ser ~100%)")
            print(f"  [ERROR] {dict_name:20s} {len(bad)} fondos no suman 100%")
        else:
            print(f"  [OK]    {dict_name:20s} {len(sums)} fondos suman ~100%")

    # ---- 4: HOLDINGS EXTERNOS (statements manuales, 4 archivos) ----
    check_external_statements(errors, warnings)

    # ---- REPORTE FINAL ----
    print("\n" + "=" * 70)
    if warnings:
        print(f"  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
    if errors:
        print(f"  ERRORES ({len(errors)}):")
        for e in errors:
            print(f"    [X] {e}")
        print("=" * 70)
        print(f"\n  RESULTADO: {len(errors)} error(es) — REVISAR antes de deploy")
        sys.exit(1)
    else:
        print("  RESULTADO: TODO OK — data consistente, safe to deploy")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()
