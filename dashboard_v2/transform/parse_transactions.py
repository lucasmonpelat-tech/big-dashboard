"""
Parser: Transactions_JXD101380.xlsx -> transactions_YYYY-MM-DD.json

Layout (45 cols, header en R11):
  Process Date, Transaction Type, Transaction Description, Net Amount (Base Currency),
  Executing IP, Record IP, SYMBOL, Buy/Sell, Quantity, Price (Transaction Currency),
  FX Rate (To Base), Commission, Fees, Principal, ..., CUSIP, ISIN, SEDOL,
  Transaction Currency, Net Amount (Transaction Currency), Settlement Date, Trade Date,
  ..., Security Identifier, Security Type, ...

Duration por default: "1 Month" (default de NetX360+).
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


def parse(xlsx_path: Path, as_of: str | None = None) -> dict:
    metadata, columns, rows = parse_header_and_rows(xlsx_path)

    account_id = metadata.get("account", "").strip()
    duration = metadata.get("duration", "").strip() or "1 Month"

    if as_of is None:
        as_of = date.today().isoformat()

    txns = []
    for row in rows:
        txn = {
            "process_date": to_iso_date(row.get("Process Date")),
            "trade_date": to_iso_date(row.get("Trade Date")),
            "settlement_date": to_iso_date(row.get("Settlement Date")),
            "buy_sell": to_str(row.get("Buy/Sell")),
            "description": to_str(row.get("Transaction Description"), ""),
            "security_id": to_str(row.get("Security Identifier")),
            "cusip": to_str(row.get("CUSIP")),
            "isin": to_str(row.get("ISIN")),
            "symbol": to_str(row.get("SYMBOL")),
            "quantity": to_float(row.get("Quantity")),
            "price_ccy": to_float(row.get("Price (Transaction Currency)")),
            "principal": to_float(row.get("Principal")),
            "commission": to_float(row.get("Commission"), 0.0),
            "fees": to_float(row.get("Fees"), 0.0),
            "net_amount_txn_ccy": to_float(row.get("Net Amount (Transaction Currency)")),
            "net_amount_base_ccy": to_float(row.get("Net Amount (Base Currency)")),
            "txn_ccy": to_str(row.get("Transaction Currency")),
            "fx_rate_to_base": to_float(row.get("FX Rate (To Base)")),
            "security_type": to_str(row.get("Security Type")),
            "market": to_str(row.get("Market")),
            "reference": to_str(row.get("Reference Number")),
        }
        txns.append(txn)

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "account_id": account_id,
        "duration": duration,
        "source_file": relpath_from_root(xlsx_path),
        "generated_at": utc_now_iso(),
        "transactions": txns,
    }


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m dashboard_v2.transform.parse_transactions <xlsx>")
        sys.exit(1)
    print(json.dumps(parse(Path(sys.argv[1])), indent=2, ensure_ascii=False))
