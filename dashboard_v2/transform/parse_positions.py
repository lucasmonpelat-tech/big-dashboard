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


def _security_types_previos() -> dict:
    """{security_id|cusip: security_type} del ultimo canonical positions.json
    que traiga tipos (export real con layout viejo, o uno ya reparado)."""
    import json
    from dashboard_v2.transform._common import ROOT
    canon = ROOT / "data" / "canonical"
    if not canon.exists():
        return {}
    for d in sorted((p.name for p in canon.iterdir() if p.is_dir()), reverse=True):
        f = canon / d / "positions.json"
        if not f.exists():
            continue
        try:
            hs = json.load(open(f, encoding="utf-8")).get("holdings", [])
        except Exception:
            continue
        out = {}
        for h in hs:
            t = h.get("security_type")
            if t:
                for k in (h.get("security_id"), h.get("cusip")):
                    if k:
                        out[k] = t
        if out:
            return out
    return {}


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

    # LAYOUT NUEVO (Pershing, 2026-10-01): el export dejo de traer "Security
    # Type", "Transaction Type", "Change" y "Accrued Interest", y agrego columnas
    # de margen (Margin Override Type, House/Fed Requirement). El filtro de
    # disclaimers de abajo usaba "Security Type" vacio, asi que con el layout
    # nuevo descartaba TODAS las filas: 4 dias de positions.json con 0 holdings
    # (y el cron en "success"). Ahora los disclaimers se reconocen por lo que
    # son -- filas sin identificador o sin cantidad -- y el tipo, si no viene,
    # se hereda del ultimo canonical que lo tenia (lo usan la clasificacion por
    # sleeve y el front: "Cash", "Corporate Bonds", "Limited Partnerships").
    tiene_tipo = "Security Type" in columns
    tipos_previos = {} if tiene_tipo else _security_types_previos()

    holdings = []
    for row in rows:
        sid = to_str(row.get("Security Identifier"), "")
        qty_raw = row.get("Trade Date Quantity")
        if not sid or qty_raw is None or qty_raw == "" or qty_raw == "-":
            continue   # disclaimers / disclosures / filas vacias del final
        if tiene_tipo:
            sec_type_raw = row.get("Security Type")
            if not sec_type_raw or not str(sec_type_raw).strip():
                continue
            sec_type = to_str(sec_type_raw, "")
        else:
            desc_up = (to_str(row.get("Description"), "") or "").upper()
            sec_type = tipos_previos.get(sid) or tipos_previos.get(to_str(row.get("CUSIP")) or "") \
                or ("Cash" if "CURRENCY" in desc_up else "")

        holding = {
            "security_id": to_str(row.get("Security Identifier"), ""),
            "cusip": to_str(row.get("CUSIP")),
            "isin": to_str(row.get("ISIN")),
            "sedol": to_str(row.get("Sedol")),
            "symbol": to_str(row.get("Symbol")),
            "description": to_str(row.get("Description"), ""),
            "security_type": sec_type,
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
