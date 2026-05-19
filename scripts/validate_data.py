"""
validate_data.py
================
Validador de consistencia de datos del BIG Dashboard.

Caza errores SILENCIOSOS — los que no rompen nada visiblemente pero corrompen
los numeros (ej: un ISIN mal escrito hace que un fondo desaparezca de un tab
sin tirar error).

Chequea:
  1. ORPHAN ISINs   — ISINs en los dicts que NO existen en BIG_POSITIONS
  2. MISSING ISINs  — fondos de BIG_POSITIONS que faltan en un dict donde deberian estar
  3. DUAL SOURCE    — BIG_POSITIONS (funds_metadata.js) vs positions_latest.json: mismos ISINs y valores
  4. EXPOSURE SUMS  — CURRENCY/COUNTRY/SECTOR deben sumar ~100% por fondo

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


def extract_big_positions(text):
    """Extrae lista de dicts de BIG_POSITIONS con isin/ticker/sleeve/value."""
    block = extract_block(text, "BIG_POSITIONS")
    if not block:
        return []
    positions = []
    # Cada entry: { isin: "...", ticker: "...", name: "...", sleeve: "...", value: NNN, ... }
    for entry in re.finditer(r"\{[^}]*\}", block):
        e = entry.group(0)
        isin = re.search(r'isin:\s*"([^"]+)"', e)
        ticker = re.search(r'ticker:\s*"([^"]+)"', e)
        sleeve = re.search(r'sleeve:\s*"([^"]+)"', e)
        value = re.search(r"value:\s*([\d.]+)", e)
        if isin:
            positions.append({
                "isin": isin.group(1),
                "ticker": ticker.group(1) if ticker else "?",
                "sleeve": sleeve.group(1) if sleeve else "?",
                "value": float(value.group(1)) if value else None,
            })
    return positions


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


def main():
    print("=" * 70)
    print("  BIG Dashboard — Data Consistency Validator")
    print("=" * 70)

    text = read_meta_js()
    errors = []
    warnings = []

    # ---- BIG_POSITIONS ----
    positions = extract_big_positions(text)
    if not positions:
        print("\n[FATAL] No pude parsear BIG_POSITIONS")
        sys.exit(1)
    big_isins = {p["isin"] for p in positions}
    equity_isins = {p["isin"] for p in positions if p["sleeve"] == "Equity"}
    fi_isins = {p["isin"] for p in positions if p["sleeve"] == "Fixed Income"}
    print(f"\nBIG_POSITIONS: {len(positions)} fondos "
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

        orphans = keys - big_isins
        missing = should_cover - keys
        bucket = errors if severity == "error" else warnings

        status = "OK"
        if orphans:
            status = severity.upper()
            for o in sorted(orphans):
                bucket.append(f"{dict_name}: ISIN huerfano '{o}' (no existe en BIG_POSITIONS)")
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
        except Exception as e:
            errors.append(f"data/funds/{fp['ticker']}.json: error de parse — {e}")

    if fi_missing_json or fi_missing_metrics:
        print(f"  [ERROR] {len(fi_funds)} FI funds — {len(fi_missing_json)} sin JSON, {len(fi_missing_metrics)} sin metricas completas")
    else:
        print(f"  [OK]    {len(fi_funds)} FI funds — todos tienen JSON con fi_metrics completas (ytw/duration/maturity)")

    # ---- 3: DUAL SOURCE — BIG_POSITIONS vs positions_latest.json ----
    print("\n" + "-" * 70)
    print("  3 — Dual source: funds_metadata.js vs positions_latest.json")
    print("-" * 70)
    if not POSITIONS_JSON.exists():
        warnings.append("positions_latest.json no existe — skip dual-source check")
        print("  [WARN] positions_latest.json no existe")
    else:
        pj = json.loads(POSITIONS_JSON.read_text(encoding="utf-8"))
        json_positions = {p["isin"]: p for p in pj.get("positions", [])}
        meta_positions = {p["isin"]: p for p in positions}

        only_meta = set(meta_positions) - set(json_positions)
        only_json = set(json_positions) - set(meta_positions)
        for o in sorted(only_meta):
            errors.append(f"dual-source: '{o}' ({meta_positions[o]['ticker']}) "
                          f"en funds_metadata.js pero NO en positions_latest.json")
        for o in sorted(only_json):
            errors.append(f"dual-source: '{o}' en positions_latest.json pero NO en funds_metadata.js")

        # Valores
        value_mismatches = 0
        for isin in set(meta_positions) & set(json_positions):
            mv = meta_positions[isin]["value"]
            jv = json_positions[isin].get("value")
            if mv is not None and jv is not None and abs(mv - jv) > VALUE_TOLERANCE_USD:
                value_mismatches += 1
                errors.append(f"dual-source: '{isin}' ({meta_positions[isin]['ticker']}) "
                              f"value distinto — meta=${mv:,.2f} vs json=${jv:,.2f}")

        if not only_meta and not only_json and value_mismatches == 0:
            print(f"  [OK]    Las 2 fuentes coinciden ({len(meta_positions)} fondos, mismos ISINs y valores)")
        else:
            print(f"  [ERROR] {len(only_meta)} solo-meta, {len(only_json)} solo-json, "
                  f"{value_mismatches} valores distintos")

    # ---- 4: EXPOSURE SUMS ----
    print("\n" + "-" * 70)
    print("  4 — Sumas de exposicion (~100% por fondo)")
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
