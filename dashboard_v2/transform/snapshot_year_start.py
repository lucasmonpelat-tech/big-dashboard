"""
Snapshot al 31-Dic del año anterior — congelado, se corre 1 vez al año.

Este script reconstruye el MV/price/qty al 31-Dic del año previo por holding,
usando Pershing UGL (data hoy) + YTD source (from year_start_anchors o baha monthlyReturns).

Uso ONE-TIME para 2026:
    python -m dashboard_v2.transform.snapshot_year_start --anchor-year 2026 --today 2026-07-17

Uso auto anual (31-Dic-26 el pipeline v2):
    python -m dashboard_v2.transform.snapshot_year_start --anchor-year 2027 --today 2026-12-31
    # ese día el "hoy" es EL 31-Dic-2026 → mv_31_dic_26 = mv_usd exacto de Pershing UGL

Metodología:
  ytd_source_pct = TWR YTD del NAV del fondo (según baha o year_start_anchors legacy)
  price_hoy_implicito = mv_hoy / qty_hoy (Pershing UGL)
  price_31_dic_year_minus_1 = price_hoy / (1 + ytd/100)
  qty_31_dic_year_minus_1 = sum(qty taxlots con entry_date < YTD_ANCHOR)
  mv_31_dic_year_minus_1 = qty × price

Sale: enriquece data/year_start_anchors.json con mv/price/qty por ISIN.

Nota: Este script depende de baha SOLO ONE-TIME para llenar YTD faltantes.
Después del 31-Dic-2026, el snapshot se genera desde Pershing UGL directo (sin baha).
"""
from __future__ import annotations
import argparse
import json
from datetime import date
from pathlib import Path

from dashboard_v2.transform._common import ROOT

DATA_DIR = ROOT / "data"
CANONICAL_DIR = DATA_DIR / "canonical"


def _compound_monthly_returns_ytd(monthly_returns: dict, year: str) -> float | None:
    """Compound de los monthly returns del año hasta el último disponible.
    monthly_returns[year] = {'ene': 1.16, 'feb': 1.86, ...}
    Retorna return YTD en % (ej: 5.88)."""
    months_order = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
    year_data = monthly_returns.get(year, {}) if isinstance(monthly_returns, dict) else {}
    if not year_data:
        return None
    r = 1.0
    for m in months_order:
        v = year_data.get(m)
        if v is None:
            break
        try:
            r *= (1 + float(v) / 100)
        except (TypeError, ValueError):
            break
    if r == 1.0:
        return None
    return round((r - 1) * 100, 2)


def get_ytd_for_isin(isin: str, anchors: dict, prev_year_str: str) -> tuple[float | None, str]:
    """Obtiene YTD source para un ISIN. Prioridad:
      1. anchors[isin]['ytd_source_pct']
      2. data/baha/{isin}.json → compound monthlyReturns
    Retorna (ytd_pct, source_note)."""
    # 1. Anchor existente
    a = anchors.get(isin, {})
    if a.get('ytd_source_pct') is not None:
        return float(a['ytd_source_pct']), "year_start_anchors"

    # 2. baha
    baha_path = DATA_DIR / "baha" / f"{isin}.json"
    if baha_path.exists():
        try:
            d = json.load(open(baha_path, encoding='utf-8'))
            mr = d.get('monthlyReturns', {})
            current_year = str(int(prev_year_str) + 1)  # ej: prev_year=2025 → current=2026
            ytd = _compound_monthly_returns_ytd(mr, current_year)
            if ytd is not None:
                return ytd, f"baha:{isin} monthly compound"
        except Exception:
            pass

    return None, "no_source"


def build_snapshot(anchor_year: int, today: str) -> dict:
    """Enriquece year_start_anchors con mv/price/qty al 31-Dic-(anchor_year-1).
    anchor_year: año del snapshot (ej: 2026 → snapshot al 31-Dic-2025)."""
    prev_year = anchor_year - 1
    prev_year_str = str(prev_year)
    ytd_anchor = f"{anchor_year}-01-01"

    # Load anchors + positions + pnl
    anchors_file = DATA_DIR / "year_start_anchors.json"
    ya = json.load(open(anchors_file, encoding='utf-8'))
    anchors_key = f"anchors_{anchor_year}"
    anchors = ya.get(anchors_key, {})

    pos = json.load(open(CANONICAL_DIR / today / "positions.json", encoding='utf-8'))
    pnl = json.load(open(CANONICAL_DIR / today / "pnl.json", encoding='utf-8'))

    # Aggregate taxlots pre-YTD por CUSIP (matchea entre positions y pnl para todos los holdings)
    qty_pre_ytd_by_cusip = {}
    for t in pnl.get('unrealized', []):
        cusip = t.get('cusip') or t.get('security_id')
        ed = t.get('entry_date')
        qty = t.get('quantity', 0) or 0
        if not cusip or not ed:
            continue
        if ed < ytd_anchor:  # taxlot pre-YTD
            qty_pre_ytd_by_cusip[cusip] = qty_pre_ytd_by_cusip.get(cusip, 0) + qty

    updates = {}
    for h in pos.get('holdings', []):
        isin = h.get('isin')
        sid = h.get('security_id')
        if not isin or not sid:
            continue
        mv_hoy = h.get('market_value_usd')
        qty_hoy = h.get('quantity')
        if not (mv_hoy and qty_hoy and qty_hoy > 0):
            continue

        price_hoy = mv_hoy / qty_hoy
        # Match by cusip (positions.cusip → pnl.cusip), fallback a security_id
        cusip = h.get('cusip')
        qty_pre = qty_pre_ytd_by_cusip.get(cusip, 0) if cusip else 0
        if qty_pre == 0:
            qty_pre = qty_pre_ytd_by_cusip.get(sid, 0)

        # YTD source
        ytd_pct, ytd_source = get_ytd_for_isin(isin, anchors, prev_year_str)

        if ytd_pct is None or qty_pre <= 0:
            # No podemos calcular anchor: sin ytd o sin taxlots pre-year
            updates[isin] = {
                "ticker": (anchors.get(isin, {}).get('ticker')) or h.get('symbol') or sid,
                "name": (anchors.get(isin, {}).get('name')) or (h.get('description') or '')[:40],
                "ytd_source_pct": ytd_pct,
                f"price_{prev_year}_dec_31": None,
                f"qty_{prev_year}_dec_31": qty_pre if qty_pre > 0 else None,
                f"mv_{prev_year}_dec_31": None,
                "note": f"no_anchor_data: ytd_source={ytd_source}, qty_pre={qty_pre}",
            }
            continue

        price_prev = round(price_hoy / (1 + ytd_pct / 100), 6)
        mv_prev = round(qty_pre * price_prev, 2)

        updates[isin] = {
            "ticker": (anchors.get(isin, {}).get('ticker')) or h.get('symbol') or sid,
            "name": (anchors.get(isin, {}).get('name')) or (h.get('description') or '')[:60],
            "ytd_source_pct": ytd_pct,
            f"price_{prev_year}_dec_31": price_prev,
            f"qty_{prev_year}_dec_31": round(qty_pre, 4),
            f"mv_{prev_year}_dec_31": mv_prev,
            "ytd_source": ytd_source,
        }

    ya[anchors_key] = updates
    return ya


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor-year", type=int, default=2026)
    ap.add_argument("--today", default=None,
                    help="Fecha del snapshot Pershing UGL a usar. Default: hoy.")
    args = ap.parse_args()

    today = args.today or date.today().isoformat()

    print(f"\n{'=' * 70}")
    print(f"  Snapshot year_start_anchors para año {args.anchor_year}")
    print(f"  Usando Pershing UGL del {today}")
    print(f"{'=' * 70}\n")

    ya = build_snapshot(args.anchor_year, today)
    anchors_key = f"anchors_{args.anchor_year}"
    anchors = ya[anchors_key]

    # Show summary
    n_ok = sum(1 for v in anchors.values() if v.get(f"mv_{args.anchor_year - 1}_dec_31") is not None)
    n_total = len(anchors)
    print(f"Anchors ok: {n_ok}/{n_total}")
    print(f"\nDetalle:")
    for isin, v in anchors.items():
        mv = v.get(f"mv_{args.anchor_year - 1}_dec_31")
        ytd = v.get('ytd_source_pct')
        note = v.get('note') or v.get('ytd_source', '')
        status = "OK" if mv is not None else "MISS"
        ytd_str = f"{ytd:+.2f}%" if ytd is not None else "  N/A "
        mv_str = f"${mv:>12,.0f}" if mv is not None else "     N/A "
        print(f"  [{status}] {v['ticker']:12s} ISIN={isin:14s} ytd={ytd_str:>8s} mv_prev={mv_str}  src={note}")

    # Write anchors file
    ya['_updated'] = today
    ya['_source'] = "Pershing UGL + year_start_anchors legacy + baha monthlyReturns"
    out = DATA_DIR / "year_start_anchors.json"
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(ya, f, indent=2, ensure_ascii=False)
    print(f"\nEscrito: {out}")


if __name__ == "__main__":
    main()
