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
    print(f"\n  [5/6] Benchmark comparison...")
    try:
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
