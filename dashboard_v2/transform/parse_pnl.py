"""
Parser: UGL + RGL XLSX -> pnl_YYYY-MM-DD.json

Combina Unrealized Gain/Loss (holdings actuales por taxlot) y Realized Gain/Loss
(trades cerrados YTD) en un solo canonical.

UGL: 52 cols, header en R15, un row por taxlot.
RGL: 44 cols, header en R15, un row por trade cerrado + rows summary "Multiple".
     Los rows summary tienen Opening Date="Multiple" o Closing Date="Multiple".

totals: totales agregados para dashboard.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date

from dashboard_v2.canonical.schemas import SCHEMA_VERSION
from dashboard_v2.transform._common import (
    parse_header_and_rows,
    to_float,
    to_str,
    to_iso_date,
    utc_now_iso,
    relpath_from_root,
)


def _parse_ugl(xlsx_path: Path) -> tuple[dict, list[dict]]:
    metadata, _, rows = parse_header_and_rows(xlsx_path)
    account_id = metadata.get("account", "").strip()

    unrealized = []
    for row in rows:
        # SKIP rows summary: el UGL emite 1 row por security con TOTALES agregados
        # (taxlot_id vacio) + N rows de taxlots individuales. Sumar todos duplica.
        # Detectamos summary por taxlot_id vacio o entry_date/trade_date en blanco.
        taxlot_id_raw = row.get("Taxlot ID")
        taxlot_id_clean = (str(taxlot_id_raw).strip() if taxlot_id_raw is not None else "")
        if not taxlot_id_clean:
            continue

        # Segunda salvaguarda: si trade_date+entry_date estan vacios, es summary
        # (Cash es excepcion: taxlot_id "19510101" hardcoded, sin trade_date pero SI entry_date)
        entry_date_raw = row.get("Entry Date")
        trade_date_raw = row.get("Trade Date")
        if entry_date_raw is None and trade_date_raw is None:
            continue

        taxlot = {
            "security_id": to_str(row.get("Security Identifier"), ""),
            "cusip": to_str(row.get("Cusip")),
            "description": to_str(row.get("Security Description"), ""),
            "security_type": to_str(row.get("Security Type"), ""),
            "asset_category": to_str(row.get("Asset Category")),
            "taxlot_id": taxlot_id_clean,
            "quantity": to_float(row.get("Quantity"), 0.0),
            "unit_cost": to_float(row.get("Unit Cost")),
            "current_total_cost": to_float(row.get("Current Total Cost"), 0.0),
            "market_value": to_float(row.get("Market Value"), 0.0),
            "last_price": to_float(row.get("Last Price")),
            "gain_loss": to_float(row.get("Gain/Loss"), 0.0),
            "gain_loss_pct": to_float(row.get("Gain/Loss %")),
            "trade_date": to_iso_date(row.get("Trade Date")),
            "entry_date": to_iso_date(row.get("Entry Date")),
            "settlement_date": to_iso_date(row.get("Settlement Date")),
            "term": to_str(row.get("Term")),
            "pct_of_portfolio": to_float(row.get("% of Portfolio")),
            "commission": to_float(row.get("Commission"), 0.0),
            "fees": to_float(row.get("Fees"), 0.0),
            "disposition_method": to_str(row.get("Disposition Method")),
        }
        unrealized.append(taxlot)

    return {"account_id": account_id}, unrealized


def _parse_rgl(xlsx_path: Path) -> tuple[dict, list[dict]]:
    metadata, _, rows = parse_header_and_rows(xlsx_path)
    account_id = metadata.get("account", "").strip()

    realized = []
    for row in rows:
        opening_raw = row.get("Opening Date")
        closing_raw = row.get("Closing Date")
        opening_str = str(opening_raw) if opening_raw is not None else ""
        closing_str = str(closing_raw) if closing_raw is not None else ""
        is_summary = "Multiple" in opening_str or "Multiple" in closing_str

        trade = {
            "security_id": to_str(row.get("Security Identifier"), ""),
            "cusip": to_str(row.get("Cusip")),
            "description": to_str(row.get("Security Description"), ""),
            "security_type": to_str(row.get("Security Type"), ""),
            "opening_date": to_iso_date(opening_raw),
            "closing_date": to_iso_date(closing_raw),
            "quantity": to_float(row.get("Quantity"), 0.0),
            "cost_basis": to_float(row.get("Cost Basis"), 0.0),
            "proceeds": to_float(row.get("Proceeds"), 0.0),
            "gain_loss": to_float(row.get("Gain/Loss"), 0.0),
            "gain_loss_pct": to_float(row.get("Gain/Loss %")),
            "term": to_str(row.get("Term")),
            "disposition_method": to_str(row.get("Disposition Method")),
            "is_summary": is_summary,
        }
        realized.append(trade)

    return {"account_id": account_id}, realized


def parse(ugl_path: Path, rgl_path: Path, as_of: str | None = None) -> dict:
    ugl_meta, unrealized = _parse_ugl(ugl_path)
    rgl_meta, realized = _parse_rgl(rgl_path)

    account_id = ugl_meta["account_id"] or rgl_meta["account_id"]
    if as_of is None:
        as_of = date.today().isoformat()

    # Totales: solo sumar rows non-summary para no double-count
    total_realized_gl_ytd = sum(
        r["gain_loss"] for r in realized if not r["is_summary"]
    )
    total_unrealized_gl = sum(t["gain_loss"] for t in unrealized)

    totals = {
        "total_unrealized_gl": round(total_unrealized_gl, 2),
        "total_realized_gl_ytd": round(total_realized_gl_ytd, 2),
        "num_taxlots": len(unrealized),
        "num_realized_trades": len([r for r in realized if not r["is_summary"]]),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "account_id": account_id,
        "source_files": {
            "ugl": relpath_from_root(ugl_path),
            "rgl": relpath_from_root(rgl_path),
        },
        "generated_at": utc_now_iso(),
        "unrealized": unrealized,
        "realized": realized,
        "totals": totals,
    }


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m dashboard_v2.transform.parse_pnl <ugl.xlsx> <rgl.xlsx>")
        sys.exit(1)
    result = parse(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(result["totals"], indent=2))
    print(f"unrealized: {len(result['unrealized'])} taxlots")
    print(f"realized:   {len(result['realized'])} trades")
