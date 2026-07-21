"""
Validators para cada canonical JSON.

Cada validate_*() retorna una lista de errores (vacia = OK).
Uso: en run_all.py despues de escribir cada JSON, correr el validator
y abortar si hay errores.
"""
from __future__ import annotations
from datetime import datetime
from . import schemas as S


def _check_type(value, expected_type, path: str) -> list[str]:
    """Chequea tipo. Tuple de tipos = union (ej: (float, type(None))) para nullable."""
    if isinstance(expected_type, tuple):
        if not isinstance(value, expected_type):
            return [f"{path}: expected {expected_type}, got {type(value).__name__}"]
    else:
        if not isinstance(value, expected_type):
            return [f"{path}: expected {expected_type.__name__}, got {type(value).__name__}"]
    return []


def _check_iso_date(value: str, path: str) -> list[str]:
    """Espera YYYY-MM-DD."""
    if value is None:
        return []
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return []
    except (ValueError, TypeError):
        return [f"{path}: not YYYY-MM-DD ({value!r})"]


def _check_record(record: dict, fields_schema: dict, path: str) -> list[str]:
    errors = []
    for field, ftype in fields_schema.items():
        if field not in record:
            errors.append(f"{path}: missing field '{field}'")
        else:
            errors.extend(_check_type(record[field], ftype, f"{path}.{field}"))
    return errors


def validate_positions(data: dict) -> list[str]:
    errors = []
    # Top-level fields
    for f, ftype in S.POSITIONS_SCHEMA.items():
        if f == "schema_version":
            if data.get(f) != S.SCHEMA_VERSION:
                errors.append(f"positions: schema_version mismatch (expected {S.SCHEMA_VERSION}, got {data.get(f)})")
            continue
        if f not in data:
            errors.append(f"positions: missing '{f}'")
            continue
        errors.extend(_check_type(data[f], ftype, f"positions.{f}"))

    errors.extend(_check_iso_date(data.get("as_of"), "positions.as_of"))

    # Holdings
    holdings = data.get("holdings", [])
    if not isinstance(holdings, list):
        errors.append("positions.holdings: not a list")
        return errors
    if not holdings:
        errors.append("positions.holdings: empty (expected at least Cash + 1 security)")

    # Invariante: sum(market_value_usd) > 0 y matchea grossly
    total_mv = 0.0
    for i, h in enumerate(holdings):
        errors.extend(_check_record(h, S.HOLDING_FIELDS, f"positions.holdings[{i}]"))
        if isinstance(h.get("market_value_usd"), (int, float)):
            total_mv += h["market_value_usd"]
    if total_mv <= 0:
        errors.append(f"positions: total market_value_usd is {total_mv} (expected > 0)")

    return errors


def validate_transactions(data: dict) -> list[str]:
    errors = []
    for f, ftype in S.TRANSACTIONS_SCHEMA.items():
        if f == "schema_version":
            if data.get(f) != S.SCHEMA_VERSION:
                errors.append(f"transactions: schema_version mismatch")
            continue
        if f not in data:
            errors.append(f"transactions: missing '{f}'")
            continue
        errors.extend(_check_type(data[f], ftype, f"transactions.{f}"))
    errors.extend(_check_iso_date(data.get("as_of"), "transactions.as_of"))

    txns = data.get("transactions", [])
    if not isinstance(txns, list):
        errors.append("transactions.transactions: not a list")
        return errors
    for i, t in enumerate(txns):
        errors.extend(_check_record(t, S.TRANSACTION_FIELDS, f"transactions[{i}]"))
    return errors


def validate_pnl(data: dict) -> list[str]:
    errors = []
    for f, ftype in S.PNL_SCHEMA.items():
        if f == "schema_version":
            if data.get(f) != S.SCHEMA_VERSION:
                errors.append(f"pnl: schema_version mismatch")
            continue
        if f not in data:
            errors.append(f"pnl: missing '{f}'")
            continue
        errors.extend(_check_type(data[f], ftype, f"pnl.{f}"))

    for i, u in enumerate(data.get("unrealized", [])):
        errors.extend(_check_record(u, S.UNREALIZED_TAXLOT_FIELDS, f"pnl.unrealized[{i}]"))
    for i, r in enumerate(data.get("realized", [])):
        errors.extend(_check_record(r, S.REALIZED_TRADE_FIELDS, f"pnl.realized[{i}]"))

    # Invariante: totals deben sumar OK
    totals = data.get("totals", {})
    if "total_unrealized_gl" not in totals:
        errors.append("pnl.totals: missing total_unrealized_gl")
    if "total_realized_gl_ytd" not in totals:
        errors.append("pnl.totals: missing total_realized_gl_ytd")

    return errors


def validate_costs(data: dict) -> list[str]:
    errors = []
    for f, ftype in S.COSTS_SCHEMA.items():
        if f == "schema_version":
            if data.get(f) != S.SCHEMA_VERSION:
                errors.append(f"costs: schema_version mismatch")
            continue
        if f not in data:
            errors.append(f"costs: missing '{f}'")
            continue
        errors.extend(_check_type(data[f], ftype, f"costs.{f}"))

    for i, t in enumerate(data.get("by_transaction", [])):
        errors.extend(_check_record(t, S.COST_BY_TXN_FIELDS, f"costs.by_transaction[{i}]"))
    for i, tl in enumerate(data.get("by_taxlot", [])):
        errors.extend(_check_record(tl, S.COST_BY_TAXLOT_FIELDS, f"costs.by_taxlot[{i}]"))

    return errors
