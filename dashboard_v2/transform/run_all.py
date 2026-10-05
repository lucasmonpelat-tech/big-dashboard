"""
Orquestador: corre los 4 parsers para un snapshot, valida, escribe canonical JSONs.

Uso:
    # Desde el snapshot de hoy en data/raw/YYYY-MM-DD/netx360/
    python -m dashboard_v2.transform.run_all

    # De un snapshot especifico
    python -m dashboard_v2.transform.run_all --date 2026-07-17

Output: data/canonical/YYYY-MM-DD/{positions,transactions,pnl,costs}.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dashboard_v2.canonical import validators
from dashboard_v2.transform import (
    parse_positions,
    parse_transactions,
    parse_pnl,
    parse_costs,
    build_benchmark_comparison,
    build_holdings_returns,
    snapshot_year_start,
)
from dashboard_v2.transform._common import ROOT

RAW_DIR = ROOT / "data" / "raw"
CANONICAL_DIR = ROOT / "data" / "canonical"


def find_snapshot(target_date: str) -> dict[str, Path]:
    """Retorna dict con paths a los 4 XLSX del dia."""
    day_dir = RAW_DIR / target_date / "netx360"
    if not day_dir.exists():
        raise FileNotFoundError(f"Snapshot dir no existe: {day_dir}")

    files = {"positions": None, "transactions": None, "ugl": None, "rgl": None}
    for f in day_dir.glob("*.xlsx"):
        name = f.name.lower()
        if name.startswith("positions"):
            files["positions"] = f
        elif name.startswith("transactions"):
            files["transactions"] = f
        elif "unrealized" in name:
            files["ugl"] = f
        elif "realized" in name:
            files["rgl"] = f

    missing = [k for k, v in files.items() if v is None]
    if missing:
        raise FileNotFoundError(
            f"Snapshot {target_date} incompleto. Faltan: {missing}. Encontrados: {list(day_dir.glob('*.xlsx'))}"
        )
    return files


def write_json(data: dict, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _diagnostico_xlsx(path) -> dict:
    """Que trae realmente el XLSX de Positions (hojas, dimensiones, primeras
    filas). Va a la alerta: asi, cuando el export viene vacio, se ve POR QUE
    sin tener que entrar al runner (los XLSX crudos no se commitean)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb[wb.sheetnames[0]]
        filas = []
        for r in range(1, min(ws.max_row, 14) + 1):
            filas.append([str(ws.cell(row=r, column=c).value)[:30]
                          for c in range(1, min(ws.max_column, 8) + 1)
                          if ws.cell(row=r, column=c).value is not None])
        return {"archivo": Path(path).name, "bytes": Path(path).stat().st_size,
                "hojas": wb.sheetnames, "max_row": ws.max_row, "max_col": ws.max_column,
                "primeras_filas": filas}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


def _bday_anterior(iso: str) -> str:
    from datetime import date as _d, timedelta as _td
    d = _d.fromisoformat(iso) - _td(days=1)
    while d.weekday() >= 5:
        d -= _td(days=1)
    return d.isoformat()


def _ultimo_positions_real(target_date: str):
    """(fecha, positions) del ultimo canonical ANTERIOR que sea un export real
    (ni fallback ni reconstruido). Es la plantilla de metadatos (ISIN, simbolo,
    descripcion, fecha de precio de los privados)."""
    import json as _json
    for d in sorted((p.name for p in CANONICAL_DIR.iterdir() if p.is_dir()), reverse=True):
        if d >= target_date:
            continue
        f = CANONICAL_DIR / d / "positions.json"
        if not f.exists():
            continue
        try:
            pos = _json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if pos.get("holdings") and not pos.get("_fallback_from"):
            return d, pos
    return None, None


def _reconstruir_desde_ugl(plantilla: dict, d_plantilla: str, unrealized: list, target_date: str) -> dict:
    """Positions del dia armado con el UGL (cantidad, valor y precio por
    security_id, sumando los lotes) y los metadatos de la ultima plantilla real.

    Verificado el 2026-09-30 (dia con los dos exports buenos): el UGL reproduce
    cantidad y valor de las 26 posiciones al centavo; solo CSPX difiere 0.3% en
    el precio (824.79 vs 827.29, cotiza en Londres). Es mucho mejor que repetir
    el dia anterior: el UGL SI trae los precios del dia."""
    from collections import defaultdict
    from datetime import date as _d
    agg = defaultdict(lambda: {"q": 0.0, "mv": 0.0, "px": None, "cusip": None, "desc": "", "type": ""})
    for t in unrealized:
        a = agg[t.get("security_id")]
        a["q"] += t.get("quantity") or 0.0
        a["mv"] += t.get("market_value") or 0.0
        if t.get("last_price") is not None:
            a["px"] = t["last_price"]
        a["cusip"] = t.get("cusip") or a["cusip"]
        a["desc"] = t.get("description") or a["desc"]
        a["type"] = t.get("security_type") or a["type"]

    por_clave = {}
    for h in plantilla["holdings"]:
        for k in (h.get("security_id"), h.get("cusip")):
            if k:
                por_clave[k] = h
    fecha_precio = _bday_anterior(target_date)
    try:
        isins_conocidos = {k: v.get("isin") for k, v in
                           json.load(open(ROOT / "data" / "isin_overrides.json", encoding="utf-8")).get("overrides", {}).items()}
    except Exception:
        isins_conocidos = {}

    out_h, usados, nuevos = [], set(), []
    for sid, a in agg.items():
        h = por_clave.get(sid) or por_clave.get(a["cusip"])
        if h is None:
            nuevos.append(sid)
            out_h.append({
                "security_id": sid, "cusip": a["cusip"], "isin": isins_conocidos.get(sid), "sedol": None,
                "symbol": sid if (sid and sid.isalpha() and len(sid) <= 5) else None,
                "description": a["desc"], "security_type": a["type"], "account_type": "",
                "position_ccy": "USD", "quantity": a["q"], "market_price_ccy": a["px"],
                "market_value_ccy": a["mv"], "fx_rate_to_usd": 1.0, "market_value_usd": a["mv"],
                "price_date": fecha_precio, "market_code": "",
            })
            continue
        usados.add(id(h))
        n = dict(h)
        px_old = h.get("market_price_ccy")
        n["quantity"] = a["q"]
        n["market_value_usd"] = round(a["mv"], 2)
        fx = h.get("fx_rate_to_usd") or 1.0
        n["market_value_ccy"] = round(a["mv"] / fx, 2)
        if px_old is not None:   # HLEND/GCRED: sin precio ni fecha, asi se quedan
            px_new = a["px"] if a["px"] is not None else px_old
            n["market_price_ccy"] = px_new
            if abs(px_new - px_old) > 1e-9:
                pd_old = h.get("price_date")
                es_privado = bool(pd_old) and (_d.fromisoformat(target_date) - _d.fromisoformat(pd_old)).days > 7
                # Privado re-marcado: no sabemos a que fecha corresponde el
                # nuevo NAV -> sin fecha, antes que una inventada.
                n["price_date"] = None if es_privado else fecha_precio
        out_h.append(n)

    cerradas = [h.get("symbol") or h.get("security_id") for h in plantilla["holdings"] if id(h) not in usados]
    out = dict(plantilla)
    out["holdings"] = out_h
    out["as_of"] = target_date
    out["_reconstruido_desde_ugl"] = True
    out["_fallback_from"] = d_plantilla
    out["_fallback_nuevos_sin_metadatos"] = nuevos
    out["_fallback_posiciones_cerradas"] = cerradas
    return out


def _fallback_si_vacio(positions: dict, target_date: str, unrealized: list | None = None,
                       xlsx_path=None) -> dict:
    """Un export de Positions vacio NO es una cartera vacia.

    El 2026-10-01 el XLSX de Positions de NetX360 vino sin filas (los otros 3
    exports vinieron bien) y los dias siguientes tambien. Sin esto el dashboard
    salia con $0 en Equity y FI. Orden de preferencia:
      1. Reconstruir desde el UGL del dia (cantidad, valor y precio frescos) con
         los metadatos de la ultima plantilla real.
      2. Si no hay UGL, repetir el canonical anterior (precios viejos).
    Escribe SIEMPRE la alerta positions_vacias_<fecha>.json, con el diagnostico
    del XLSX para ver por que vino vacio."""
    import json as _json
    from datetime import datetime as _dt
    n = len(positions.get("holdings", []))
    mv = sum((h.get("market_value_usd") or 0) for h in positions.get("holdings", []))
    d_plant, plant = _ultimo_positions_real(target_date)
    if plant is None:
        return positions
    mv_prev = sum((h.get("market_value_usd") or 0) for h in plant["holdings"])
    if n > 0 and (mv_prev <= 0 or mv >= 0.5 * mv_prev):
        return positions
    motivo = ("sin filas" if n == 0 else f"{n} filas por ${mv:,.0f}, menos de la mitad de la ultima cartera real (${mv_prev:,.0f})")
    if unrealized:
        out = _reconstruir_desde_ugl(plant, d_plant, unrealized, target_date)
        como = (f"reconstruido desde el UGL del {target_date} (cantidades, valores y precios del dia) "
                f"con los metadatos del {d_plant}")
    else:
        out = dict(plant)
        out["as_of"] = target_date
        out["_fallback_from"] = d_plant
        como = f"copia del canonical del {d_plant} (precios y cantidades de ese dia: SIN UGL para reconstruir)"
    mv_out = sum((h.get("market_value_usd") or 0) for h in out["holdings"])
    out["_fallback_motivo"] = f"Export de Positions del {target_date} {motivo}. Cartera {como}."
    print(f"    !! Positions de NetX360 {motivo}. {como} ({len(out['holdings'])} holdings, ${mv_out:,.0f}).")
    alerts = ROOT / "data" / "_alerts"
    alerts.mkdir(parents=True, exist_ok=True)
    with open(alerts / f"positions_vacias_{target_date}.json", "w", encoding="utf-8") as f:
        _json.dump({
            "date": target_date, "tipo": "positions_vacias", "detected_at": _dt.now().isoformat(),
            "detalle": out["_fallback_motivo"],
            "valor_total_usd": round(mv_out, 2),
            "nuevos_sin_metadatos": out.get("_fallback_nuevos_sin_metadatos"),
            "posiciones_cerradas": out.get("_fallback_posiciones_cerradas"),
            "diagnostico_xlsx": _diagnostico_xlsx(xlsx_path) if xlsx_path else None,
            "accion": "Revisar el XLSX de Positions de NetX360 (netx360_auto.py, tab positions-account). Mientras tanto el "
                      "dashboard muestra la cartera reconstruida con el UGL del dia. Si el export vuelve a venir bien, el "
                      "cron lo toma solo.",
        }, f, indent=2, ensure_ascii=False)
    return out


def run(target_date: str) -> dict:
    print(f"\n{'=' * 70}")
    print(f"  Transform {target_date}")
    print(f"{'=' * 70}")

    files = find_snapshot(target_date)
    print(f"\n  Snapshot:")
    for k, v in files.items():
        print(f"    {k}: {v.name}")

    out_dir = CANONICAL_DIR / target_date
    results = {}
    all_errors = []

    # 1. Positions
    print(f"\n  [1/4] Positions...")
    positions = parse_positions.parse(files["positions"], as_of=target_date)
    unrealized = None
    if not positions.get("holdings"):
        try:
            unrealized = parse_pnl.parse(files["ugl"], files["rgl"], as_of=target_date).get("unrealized")
        except Exception as e:  # noqa: BLE001
            print(f"    (no pude leer el UGL para reconstruir: {e})")
    positions = _fallback_si_vacio(positions, target_date, unrealized=unrealized, xlsx_path=files["positions"])
    errs = validators.validate_positions(positions)
    if errs:
        print(f"    VALIDATION ERRORS: {len(errs)}")
        for e in errs[:5]:
            print(f"      - {e}")
        all_errors.extend(errs)
    write_json(positions, out_dir / "positions.json")
    print(f"    OK: {len(positions['holdings'])} holdings")
    results["positions"] = len(positions["holdings"])

    # 2. Transactions
    print(f"\n  [2/4] Transactions...")
    transactions = parse_transactions.parse(files["transactions"], as_of=target_date)
    errs = validators.validate_transactions(transactions)
    if errs:
        print(f"    VALIDATION ERRORS: {len(errs)}")
        for e in errs[:5]:
            print(f"      - {e}")
        all_errors.extend(errs)
    write_json(transactions, out_dir / "transactions.json")
    print(f"    OK: {len(transactions['transactions'])} transactions (duration: {transactions['duration']})")
    results["transactions"] = len(transactions["transactions"])

    # 3. PnL (UGL + RGL)
    print(f"\n  [3/4] PnL...")
    pnl = parse_pnl.parse(files["ugl"], files["rgl"], as_of=target_date)
    errs = validators.validate_pnl(pnl)
    if errs:
        print(f"    VALIDATION ERRORS: {len(errs)}")
        for e in errs[:5]:
            print(f"      - {e}")
        all_errors.extend(errs)
    write_json(pnl, out_dir / "pnl.json")
    print(f"    OK: {pnl['totals']['num_taxlots']} taxlots, "
          f"{pnl['totals']['num_realized_trades']} realized YTD")
    print(f"    Unrealized G/L: ${pnl['totals']['total_unrealized_gl']:,.2f}")
    print(f"    Realized YTD:   ${pnl['totals']['total_realized_gl_ytd']:,.2f}")
    results["pnl"] = pnl["totals"]

    # 4. Costs
    print(f"\n  [4/6] Costs...")
    costs = parse_costs.parse(files["transactions"], files["ugl"], as_of=target_date)
    errs = validators.validate_costs(costs)
    if errs:
        print(f"    VALIDATION ERRORS: {len(errs)}")
        for e in errs[:5]:
            print(f"      - {e}")
        all_errors.extend(errs)
    write_json(costs, out_dir / "costs.json")
    print(f"    OK: commissions 30d ${costs['totals']['commissions_txn_30d']:.2f}, "
          f"fees 30d ${costs['totals']['fees_txn_30d']:.2f}")
    results["costs"] = costs["totals"]

    # 5. Benchmark comparison (Total vs 60/40, Equity vs ACWI, FI vs AGG)
    # PREVIO: interpolar sleeve TWR series para tener granularidad diaria.
    # Sin esto, el pipeline viejo genera solo 1 punto por mes (o por evento)
    # y los cálculos multi-period (1M/3M/6M) agarran fechas incorrectas
    # cuando el pivot cae en un día sin data.
    print(f"\n  [5/6] Benchmark comparison...")
    try:
        import subprocess
        import sys as _sys
        interp_script = ROOT / "scripts" / "interpolate_equity_series.py"
        if interp_script.exists():
            print(f"    Pre-step: interpolate sleeve TWR series (fill gaps daily)")
            subprocess.run([_sys.executable, str(interp_script)], check=False, capture_output=True)
        bc = build_benchmark_comparison.build(as_of=target_date)
        write_json(bc, out_dir / "benchmark_comparison.json")
        print(f"    OK: 3 comparisons alineadas + rebased a 100")
    except Exception as e:
        print(f"    FAIL: {e}")
        all_errors.append(f"benchmark_comparison: {e}")

    # 6a. Snapshot year_start (refresh anchors)
    print(f"\n  [6/7] Refreshing year_start anchors...")
    try:
        from datetime import date as _d
        current_year = int(target_date[:4])
        anchor_year = current_year
        ya = snapshot_year_start.build_snapshot(anchor_year=anchor_year, today=target_date)
        anchors_key = f"anchors_{anchor_year}"
        n_ok = sum(1 for v in ya.get(anchors_key, {}).values()
                   if v.get(f"mv_{anchor_year - 1}_dec_31") is not None)
        n_tot = len(ya.get(anchors_key, {}))
        # Write anchors
        import json as _json
        (Path(build_holdings_returns.DATA_DIR) / "year_start_anchors.json").write_text(
            _json.dumps(ya, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"    OK: {n_ok}/{n_tot} anchors OK")
    except Exception as e:
        print(f"    FAIL: {e}")
        all_errors.append(f"year_start_anchors: {e}")

    # 6b. Holdings returns (MV correcto Pershing UGL + bench DW por holding + MWR YTD real)
    print(f"\n  [7/7] Holdings returns...")
    try:
        hr = build_holdings_returns.build(target_date)
        write_json(hr, out_dir / "holdings_returns.json")
        eq_n = len(hr.get("sleeves", {}).get("equity", {}).get("holdings", []))
        fi_n = len(hr.get("sleeves", {}).get("fixed_income", {}).get("holdings", []))
        alt_n = len(hr.get("sleeves", {}).get("alternatives", {}).get("holdings", []))
        print(f"    OK: {eq_n} equity + {fi_n} FI + {alt_n} alts holdings con MV Pershing UGL")
    except Exception as e:
        print(f"    FAIL: {e}")
        all_errors.append(f"holdings_returns: {e}")

    # Summary
    print(f"\n{'=' * 70}")
    if all_errors:
        print(f"  RESULT: FAIL ({len(all_errors)} validation errors)")
        print(f"{'=' * 70}")
        return {"ok": False, "errors": all_errors, "results": results}

    print(f"  RESULT: OK ({len(list(out_dir.glob('*.json')))} JSONs escritos)")
    print(f"  Output: {out_dir}")
    print(f"{'=' * 70}")
    return {"ok": True, "results": results, "out_dir": str(out_dir)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="Snapshot date YYYY-MM-DD. Default: hoy.")
    args = ap.parse_args()

    target_date = args.date or date.today().isoformat()

    try:
        result = run(target_date)
        sys.exit(0 if result["ok"] else 1)
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
