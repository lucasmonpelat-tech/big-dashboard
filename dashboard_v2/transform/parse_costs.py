"""
Parser: Transactions + UGL -> costs_YYYY-MM-DD.json

Extrae comisiones y fees de:
- Transactions (por trade en los ultimos 30 dias)
- UGL (por taxlot activo — commissions historicas ya incurridas y baked in cost)

Totals agrega para display en el tab "Costos totales" del dashboard.
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


def parse(transactions_path: Path, ugl_path: Path, as_of: str | None = None) -> dict:
    if as_of is None:
        as_of = date.today().isoformat()

    # Transactions
    txn_meta, _, txn_rows = parse_header_and_rows(transactions_path)
    account_id = txn_meta.get("account", "").strip()

    by_transaction = []
    for row in txn_rows:
        commission = to_float(row.get("Commission"), 0.0) or 0.0
        fees = to_float(row.get("Fees"), 0.0) or 0.0
        if commission == 0.0 and fees == 0.0:
            continue  # skip txns sin costos
        by_transaction.append({
            "process_date": to_iso_date(row.get("Process Date")),
            "security_id": to_str(row.get("Security Identifier")),
            "description": to_str(row.get("Transaction Description"), ""),
            "commission": commission,
            "fees": fees,
            "principal": to_float(row.get("Principal")),
        })

    # UGL - por taxlot activo
    ugl_meta, _, ugl_rows = parse_header_and_rows(ugl_path)
    if not account_id:
        account_id = ugl_meta.get("account", "").strip()

    by_taxlot = []
    for row in ugl_rows:
        commission = to_float(row.get("Commission"), 0.0) or 0.0
        fees = to_float(row.get("Fees"), 0.0) or 0.0
        if commission == 0.0 and fees == 0.0:
            continue
        by_taxlot.append({
            "security_id": to_str(row.get("Security Identifier"), ""),
            "taxlot_id": to_str(row.get("Taxlot ID"), ""),
            "description": to_str(row.get("Security Description"), ""),
            "commission": commission,
            "fees": fees,
            "current_cost": to_float(row.get("Current Total Cost"), 0.0),
            "entry_date": to_iso_date(row.get("Entry Date")),
        })

    totals = {
        "commissions_txn_30d": round(sum(t["commission"] for t in by_transaction), 2),
        "fees_txn_30d": round(sum(t["fees"] for t in by_transaction), 2),
        "commissions_taxlots_current": round(sum(t["commission"] for t in by_taxlot), 2),
        "fees_taxlots_current": round(sum(t["fees"] for t in by_taxlot), 2),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "account_id": account_id,
        "source_files": {
            "transactions": relpath_from_root(transactions_path),
            "ugl": relpath_from_root(ugl_path),
        },
        "generated_at": utc_now_iso(),
        "totals": totals,
        "by_transaction": by_transaction,
        "by_taxlot": by_taxlot,
    }


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m dashboard_v2.transform.parse_costs <transactions.xlsx> <ugl.xlsx>")
        sys.exit(1)
    result = parse(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(result["totals"], indent=2))
    print(f"by_transaction: {len(result['by_transaction'])} entries")
    print(f"by_taxlot:      {len(result['by_taxlot'])} entries")
