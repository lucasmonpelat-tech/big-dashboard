"""
Parser: Positions_JXD101380.xlsx -> positions_YYYY-MM-DD.json

Layout (21 cols, header en R9):
  Security Identifier, Symbol, ISIN, Sedol, CUSIP, Description,
  Market Value (Position CCY), Trade Date Quantity, Position CCY,
  Security Type, Account Type, Transaction Type,
  Market Price (Position CCY), Price Date, Change,
  Accrued Interest (Position CCY), FX Rate (To USDE),
  Market Value (USDE), Accrued Interest (USDE), Market Code, As of Date

Retorna: dict conforme al POSITIONS_SCHEMA.
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
    """
    xlsx_path: Positions_JXD101380.xlsx
    as_of: fecha del snapshot (YYYY-MM-DD). Si None, se toma de la metadata "As of".
    """
    metadata, columns, rows = parse_header_and_rows(xlsx_path)

    # Account info desde metadata
    account_id = metadata.get("account", "").strip()
    account_name = metadata.get("client", "").strip()
    base_currency = metadata.get("base currency", "USD").strip()

    # As of date
    if as_of is None:
        as_of_raw = metadata.get("as of", "")
        as_of = to_iso_date(as_of_raw) or date.today().isoformat()

    holdings = []
    for row in rows:
        # Skip rows de disclaimers legales al final del XLSX (Positions_XXX.xlsx tiene ~8 al final)
        # Se distinguen por security_type vacio Y quantity/MV cero.
        sec_type_raw = row.get("Security Type")
        if not sec_type_raw or not str(sec_type_raw).strip():
            continue

        holding = {
            "security_id": to_str(row.get("Security Identifier"), ""),
            "cusip": to_str(row.get("CUSIP")),
            "isin": to_str(row.get("ISIN")),
            "sedol": to_str(row.get("Sedol")),
            "symbol": to_str(row.get("Symbol")),
            "description": to_str(row.get("Description"), ""),
            "security_type": to_str(row.get("Security Type"), ""),
            "account_type": to_str(row.get("Account Type"), ""),
            "position_ccy": to_str(row.get("Position CCY"), base_currency),
            "quantity": to_float(row.get("Trade Date Quantity"), 0.0),
            "market_price_ccy": to_float(row.get("Market Price (Position CCY)")),
            "market_value_ccy": to_float(row.get("Market Value (Position CCY)"), 0.0),
            "fx_rate_to_usd": to_float(row.get("FX Rate (To USDE)"), 1.0),
            "market_value_usd": to_float(row.get("Market Value (USDE)"), 0.0),
            "price_date": to_iso_date(row.get("Price Date")),
            "market_code": to_str(row.get("Market Code"), ""),
        }
        holdings.append(holding)

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "account_id": account_id,
        "account_name": account_name,
        "base_currency": base_currency,
        "source_file": relpath_from_root(xlsx_path),
        "generated_at": utc_now_iso(),
        "holdings": holdings,
    }


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m dashboard_v2.transform.parse_positions <path/to/Positions_XXX.xlsx>")
        sys.exit(1)

    result = parse(Path(sys.argv[1]))
    print(json.dumps(result, indent=2, ensure_ascii=False))
