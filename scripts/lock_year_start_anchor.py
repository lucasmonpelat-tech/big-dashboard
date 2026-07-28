"""
lock_year_start_anchor.py
==========================
Planta un anchor 31-Dic REAL y VERIFICADO para un ISIN, con anchor_locked=True.
Una vez trabado, snapshot_year_start.py (corrida diaria del pipeline v2) copia
el registro tal cual y NUNCA lo vuelve a recalcular (fix 2026-07-28, ver
dashboard_v2/transform/snapshot_year_start.py).

Usar cuando Lucas consigue el NAV real al 31-Dic-2025 de un fondo (de baha
historico, factsheet del fondo, etc.) -- reemplaza cualquier anchor derivado
circularmente del ytd_source_pct congelado (bug encontrado 2026-07-28 con
NBGMT/MFSCV).

Usage:
    python scripts/lock_year_start_anchor.py --isin LU1985812756 --price 265.40 \\
        --source "baha historico 31-Dic-2025, chequeado manualmente por Lucas"
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
ANCHORS_FILE = DATA_DIR / "year_start_anchors.json"
YTD_ANCHOR_DATE = "2026-01-01"


def qty_pre_ytd(isin: str) -> float | None:
    """Suma qty de taxlots con entry_date < 2026-01-01 para este ISIN, desde el
    canonical positions.json + pnl.json mas reciente."""
    canonical_dir = DATA_DIR / "canonical"
    dates = sorted(p.name for p in canonical_dir.iterdir() if p.is_dir())
    for d in reversed(dates):
        pos_f = canonical_dir / d / "positions.json"
        pnl_f = canonical_dir / d / "pnl.json"
        if not (pos_f.exists() and pnl_f.exists()):
            continue
        pos = json.load(open(pos_f, encoding="utf-8"))
        pnl = json.load(open(pnl_f, encoding="utf-8"))
        h = next((x for x in pos.get("holdings", []) if x.get("isin") == isin), None)
        if not h:
            continue
        cusip = h.get("cusip")
        sid = h.get("security_id")
        total = 0.0
        found = False
        for t in pnl.get("unrealized", []):
            t_cusip = t.get("cusip") or t.get("security_id")
            ed = t.get("entry_date")
            if not t_cusip or not ed:
                continue
            if t_cusip in (cusip, sid) and ed < YTD_ANCHOR_DATE:
                total += t.get("quantity", 0) or 0
                found = True
        if found:
            return round(total, 4)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--isin", required=True)
    ap.add_argument("--price", required=True, type=float, help="NAV real al 31-Dic-2025")
    ap.add_argument("--source", required=True, help="De donde salio el numero (para auditoria)")
    ap.add_argument("--anchor-year", default=2026, type=int)
    args = ap.parse_args()

    ya = json.load(open(ANCHORS_FILE, encoding="utf-8"))
    key = f"anchors_{args.anchor_year}"
    anchors = ya.setdefault(key, {})
    existing = anchors.get(args.isin, {})

    qty_pre = qty_pre_ytd(args.isin)
    if qty_pre is None:
        print(f"ERROR: no encontre taxlots pre-2026 para {args.isin} en ningun canonical snapshot.")
        return

    mv_prev = round(qty_pre * args.price, 2)

    anchors[args.isin] = {
        "ticker": existing.get("ticker"),
        "name": existing.get("name"),
        f"price_{args.anchor_year - 1}_dec_31": args.price,
        f"qty_{args.anchor_year - 1}_dec_31": qty_pre,
        f"mv_{args.anchor_year - 1}_dec_31": mv_prev,
        "anchor_locked": True,
        "ytd_source": "manual_verified",
        "note": f"Anchor real verificado el {datetime.now().date()}. Fuente: {args.source}",
    }
    with open(ANCHORS_FILE, "w", encoding="utf-8") as f:
        json.dump(ya, f, indent=2, ensure_ascii=False)

    print(f"OK: {args.isin} ({existing.get('ticker')}) anchor_locked=True")
    print(f"  price_{args.anchor_year - 1}_dec_31 = {args.price}")
    print(f"  qty_{args.anchor_year - 1}_dec_31   = {qty_pre}")
    print(f"  mv_{args.anchor_year - 1}_dec_31    = {mv_prev}")


if __name__ == "__main__":
    main()
