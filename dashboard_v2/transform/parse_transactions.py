"""
Parser: Transactions_JXD101380.xlsx -> transactions_YYYY-MM-DD.json

Layout REAL del export (13 cols, header en R11) -- verificado 2026-08-28:
  Process Date, Transaction Type, Net Amount (Base Currency), SYMBOL,
  Security Description, Commission, Fees, Principal, Interest,
  Reference Number, Net Amount (Transaction Currency), Settlement Date, Trade Date

CORREGIDO: este docstring describia un layout de 45 columnas con Buy/Sell,
Quantity, CUSIP, ISIN, Transaction Description y Security Identifier. Esas
columnas NO existen en el export -- son del popup "Details" de la web de
NetX360, no del archivo. El parser las buscaba y devolvia None en todo.

OJO con dos cosas del archivo real:
  - Trade Date y Settlement Date pueden venir como "-" si el trade no liquido.
    El cash sale en el trade date pero la posicion recien aparece en el
    settlement (para HLGPI hubo 23 dias de diferencia).
  - Hay filas "Cancel Buy" que anulan una operacion previa. Si no se netean,
    la compra se cuenta dos veces.

Duration por default: "1 Month" (default de NetX360+).
"""
from __future__ import annotations

import re
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


# El export real de NetX360+ trae 13 columnas, no las 45 que describe el
# docstring de arriba: NO hay Buy/Sell, Quantity, CUSIP, ISIN,
# Transaction Description ni Security Identifier. Todo eso viene embebido en el
# texto de "Transaction Type", por ejemplo:
#     "Buy 2134.27900 of L4680C117"
#     "Buy 169.00000 share(s) of GLD at 388.9446"
#     "Cancel Buy -2134.27900 of L4680C117"
# Antes se leian columnas inexistentes y TODOS los campos salian None: el
# 2026-08-27 el canonical tenia 29 transacciones y 0 con buy/sell + security.
# Se extrae del texto, dejando las columnas anchas como fuente preferida por si
# el export vuelve al formato largo.
RE_TXN = re.compile(
    r"^(?P<cancel>Cancel\s+)?(?P<side>Buy|Sell|Sold|Sale)\s+"
    r"(?P<qty>-?[\d,]+\.?\d*)\s*"
    r"(?:share\(s\)\s*)?(?:of\s+)?"
    r"(?P<sec>[A-Z0-9.]+)?"
    r"(?:\s+at\s+(?P<px>[\d,.]+))?",
    re.IGNORECASE,
)


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def extract_from_type(txn_type: str) -> dict:
    """Saca side / qty / security / precio del texto de 'Transaction Type'.

    Devuelve {} para las filas que no son operaciones (INTEREST ON FREE CREDIT,
    WIRED FUNDS FEE, POSITION ADJUSTMENT, FEDERAL FUNDS SENT/RECEIVED, custody
    fees). Esas filas mueven cash pero no son compra/venta de un holding.
    """
    m = RE_TXN.match((txn_type or "").strip())
    if not m:
        return {}
    g = m.groupdict()
    side = "SELL" if g["side"].upper() in ("SELL", "SOLD", "SALE") else "BUY"
    return {
        "buy_sell": side,
        "quantity": _num(g["qty"]),
        "security_id": (g["sec"] or None),
        "price_ccy": _num(g["px"]) if g["px"] else None,
        "is_cancel": bool(g["cancel"]),
    }


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

        # Fallback al texto de "Transaction Type" para lo que el export corto
        # no trae en columnas propias. Las columnas anchas ganan si existen.
        txn_type = to_str(row.get("Transaction Type"), "") or ""
        txn["transaction_type"] = txn_type
        extra = extract_from_type(txn_type)
        txn["is_cancel"] = extra.get("is_cancel", False)
        txn["is_trade"] = bool(extra)
        for campo in ("buy_sell", "quantity", "security_id", "price_ccy"):
            if txn.get(campo) is None and extra.get(campo) is not None:
                txn[campo] = extra[campo]

        # El nombre del fondo esta en "Security Description" (el export corto no
        # tiene "Transaction Description").
        if not txn.get("description"):
            txn["description"] = to_str(row.get("Security Description"), "") or ""

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
