"""
sync_positions_latest_from_canonical.py
========================================
Refresca data/positions_latest.json (qty/price/value por ticker) desde el
canonical mas reciente (data/canonical/{date}/positions.json, Pershing via
NetX360 -- fresco todos los dias via el cron).

Por que hace falta: positions_latest.json es un archivo LEGACY que varios
scripts todavia usan como "override" de qty/MV para el ultimo punto de sus
series (refresh_equity_daily.py, refresh_fi_daily.py, refresh_alts_daily.py
-- este ultimo ya no lo necesita, ver nota mas abajo). Hasta 2026-07-28 este
archivo se actualizaba SOLO cuando alguien lo subia a mano -- quedo
congelado en 2026-06-24 (un mes), causando que PIMCO-LD/MANIG/SGCB
mostraran qty vieja (compras recientes sin capturar) en equity_sleeve_real
.json / fi_sleeve_real.json, aun despues de haber arreglado
holdings_returns_*.json (2026-07-28, commit b3809bb) -- son pipelines
independientes que ambos dependian de la MISMA fuente stale.

Usage:
    python scripts/sync_positions_latest_from_canonical.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
CANONICAL_DIR = ROOT / "data" / "canonical"
OUT_FILE = ROOT / "data" / "positions_latest.json"

sys.path.insert(0, str(Path(__file__).parent))
from compute_holdings_returns import PERSHING_TO_MY  # noqa: E402

# Bonos que cotizan per-100-face-value -- el campo 'price' de este archivo
# legacy va dividido /100 (convencion ya usada por refresh_fi_daily.py /
# refresh_alts_daily.py / portfolio_reconstructor.py para estos 2 tickers).
PAR_VALUE_TICKERS = {"TGF", "BPCC"}


def latest_canonical_positions():
    if not CANONICAL_DIR.exists():
        return None, None
    dates = sorted(p.name for p in CANONICAL_DIR.iterdir() if p.is_dir())
    for d in reversed(dates):
        f = CANONICAL_DIR / d / "positions.json"
        if f.exists():
            try:
                return json.load(open(f, encoding="utf-8")), d
            except Exception:
                continue
    return None, None


def identify(h):
    """Matchea un holding canonical contra PERSHING_TO_MY por symbol/cusip/security_id."""
    for key in (h.get("symbol"), h.get("cusip"), h.get("security_id")):
        if key and key in PERSHING_TO_MY:
            return PERSHING_TO_MY[key]
    return None, None


def main():
    positions, snapshot_date = latest_canonical_positions()
    if positions is None:
        print("  ERROR: no hay ningun canonical positions.json disponible. Abortando.")
        return

    print(f"[{datetime.now().isoformat()}] Sync positions_latest.json desde canonical ({snapshot_date})")

    out_positions = []
    skipped = []
    for h in positions.get("holdings", []):
        ticker, sleeve = identify(h)
        if not ticker or sleeve in (None, "SKIP", "Cash"):
            if (h.get("market_value_usd") or 0) != 0:
                skipped.append(h.get("symbol") or h.get("cusip") or h.get("description"))
            continue
        price = h.get("market_price_ccy")
        if ticker in PAR_VALUE_TICKERS and price:
            price = price / 100
        out_positions.append({
            "ticker": ticker,
            "sleeve": sleeve,
            "qty": h.get("quantity"),
            "price": price,
            "value": h.get("market_value_usd"),
            "price_as_of": h.get("price_date") or snapshot_date,
        })

    total_aum = sum(p["value"] or 0 for p in out_positions)
    out = {
        "as_of": snapshot_date,
        "as_of_date": snapshot_date,
        "refreshedAt": datetime.now().isoformat(),
        "source": f"canonical/{snapshot_date}/positions.json (Pershing via NetX360)",
        "total_aum": round(total_aum, 2),
        "n_positions": len(out_positions),
        "positions": out_positions,
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    print(f"  {len(out_positions)} posiciones sincronizadas. Total AUM: ${total_aum:,.0f}")
    if skipped:
        print(f"  Omitidos (sin match en PERSHING_TO_MY, con MV>0): {skipped}")
    print(f"  Saved: {OUT_FILE}")


if __name__ == "__main__":
    main()
