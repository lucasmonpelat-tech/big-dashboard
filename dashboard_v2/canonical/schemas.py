"""
Schemas canonical del dashboard v2.

Cada canonical JSON tiene:
- Metadata: as_of (fecha del snapshot), account_id, source_file(s), generated_at
- Payload: lista de records tipados

No usamos Pydantic/dataclass — plain dicts + validators explicitos para
mantener el pipeline transparente y regenerable desde raw sin dependencias exoticas.

Schema version cambia cuando cambia la forma de un JSON. Los readers en la
capa presentation deben validar el schema_version antes de leer.
"""
from __future__ import annotations

SCHEMA_VERSION = 1

# ============================================================
# POSITIONS
# ============================================================
POSITIONS_SCHEMA = {
    "schema_version": SCHEMA_VERSION,
    "as_of": str,          # YYYY-MM-DD
    "account_id": str,     # JXD101380
    "account_name": str,   # LSERIES DAC
    "base_currency": str,  # USD
    "source_file": str,    # path relativo al repo
    "generated_at": str,   # ISO 8601 UTC
    "holdings": list,      # list of Holding dicts
}

HOLDING_FIELDS = {
    "security_id": str,
    "cusip": (str, type(None)),
    "isin": (str, type(None)),
    "sedol": (str, type(None)),
    "symbol": (str, type(None)),
    "description": str,
    "security_type": str,      # "Cash", "Common Stocks", "Open-end Mutual Funds", ...
    "account_type": str,       # "CASH"
    "position_ccy": str,       # "USD"
    "quantity": float,
    "market_price_ccy": (float, type(None)),
    "market_value_ccy": float,
    "fx_rate_to_usd": float,
    "market_value_usd": float,
    "price_date": (str, type(None)),  # YYYY-MM-DD
    "market_code": str,               # "US", "LU", "IE"
}

# ============================================================
# TRANSACTIONS
# ============================================================
TRANSACTIONS_SCHEMA = {
    "schema_version": SCHEMA_VERSION,
    "as_of": str,
    "account_id": str,
    "duration": str,       # "1 Month" o "2 Years"
    "source_file": str,
    "generated_at": str,
    "transactions": list,
}

TRANSACTION_FIELDS = {
    "process_date": (str, type(None)),
    "trade_date": (str, type(None)),
    "settlement_date": (str, type(None)),
    "buy_sell": (str, type(None)),        # "BUY", "SELL"
    "description": str,
    "security_id": (str, type(None)),
    "cusip": (str, type(None)),
    "isin": (str, type(None)),
    "symbol": (str, type(None)),
    "quantity": (float, type(None)),
    "price_ccy": (float, type(None)),
    "principal": (float, type(None)),
    "commission": (float, type(None)),
    "fees": (float, type(None)),
    "net_amount_txn_ccy": (float, type(None)),
    "net_amount_base_ccy": (float, type(None)),
    "txn_ccy": (str, type(None)),
    "fx_rate_to_base": (float, type(None)),
    "security_type": (str, type(None)),
    "market": (str, type(None)),
    "reference": (str, type(None)),
}

# ============================================================
# PNL (UGL + RGL combinado)
# ============================================================
PNL_SCHEMA = {
    "schema_version": SCHEMA_VERSION,
    "as_of": str,
    "account_id": str,
    "source_files": dict,   # {"ugl": "...", "rgl": "..."}
    "generated_at": str,
    "unrealized": list,     # taxlots activos con G/L unrealized
    "realized": list,       # trades cerrados YTD con G/L realized
    "totals": dict,         # summary: total_unrealized_gl, total_realized_gl_ytd
}

UNREALIZED_TAXLOT_FIELDS = {
    "security_id": str,
    "cusip": (str, type(None)),
    "description": str,
    "security_type": str,
    "asset_category": (str, type(None)),
    "taxlot_id": str,
    "quantity": float,
    "unit_cost": (float, type(None)),
    "current_total_cost": float,
    "market_value": float,
    "last_price": (float, type(None)),
    "gain_loss": float,
    "gain_loss_pct": (float, type(None)),
    "trade_date": (str, type(None)),
    "entry_date": (str, type(None)),
    "settlement_date": (str, type(None)),
    "term": (str, type(None)),           # "SHORT", "LONG"
    "pct_of_portfolio": (float, type(None)),
    "commission": (float, type(None)),
    "fees": (float, type(None)),
    "disposition_method": (str, type(None)),
}

REALIZED_TRADE_FIELDS = {
    "security_id": str,
    "cusip": (str, type(None)),
    "description": str,
    "security_type": str,
    "opening_date": (str, type(None)),   # None si es "Multiple" (summary)
    "closing_date": (str, type(None)),
    "quantity": float,
    "cost_basis": float,
    "proceeds": float,
    "gain_loss": float,
    "gain_loss_pct": (float, type(None)),
    "term": (str, type(None)),
    "disposition_method": (str, type(None)),
    "is_summary": bool,                  # True si Opening/Closing Date = "Multiple"
}

# ============================================================
# COSTS
# ============================================================
COSTS_SCHEMA = {
    "schema_version": SCHEMA_VERSION,
    "as_of": str,
    "account_id": str,
    "source_files": dict,
    "generated_at": str,
    "totals": dict,      # commissions y fees agregados
    "by_transaction": list,
    "by_taxlot": list,
}

COST_BY_TXN_FIELDS = {
    "process_date": (str, type(None)),
    "security_id": (str, type(None)),
    "description": str,
    "commission": float,
    "fees": float,
    "principal": (float, type(None)),
}

COST_BY_TAXLOT_FIELDS = {
    "security_id": str,
    "taxlot_id": str,
    "description": str,
    "commission": float,
    "fees": float,
    "current_cost": float,
    "entry_date": (str, type(None)),
}
