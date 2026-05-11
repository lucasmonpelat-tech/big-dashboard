"""
holding_contributions_real.py
=============================
Computes REAL TWR contributions per holding using Pershing transaction history.

Reads:    data/{sleeve}_sleeve_real.json (sleeve_series_{sleeve} block per month)
Outputs:  data/{sleeve}_contributions_real.json

For each holding:
  - period_start / period_end (real holding window)
  - months_held
  - twr_pct: cumulative price return during the period
  - avg_weight_pct: avg weight in the sleeve while held
  - contribution_pp: weighted contribution to sleeve TWR
  - is_closed: True if the position was fully sold
  - status: 🏆 winner / ⚠️ lagging / 🔴 loser / ⚰️ closed

Usage:
    python scripts/holding_contributions_real.py
    (processes equity by default; pass --sleeve fi for fixed income once available)
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent

NAME_BY_TICKER = {
    # Equity
    "CSPX":   "iShares Core S&P 500 UCITS",
    "BRK.B":  "Berkshire Hathaway B (CLOSED 16-Apr-26)",
    "NBGMT":  "NB Global Equity Megatrends I",
    "MFSCV":  "MFS Meridian Contrarian Value I1",
    "JHGSC":  "Janus Henderson Global Smaller Cos F2",
    "LGLI":   "Lazard Global Listed Infrastructure A",
    "NBRE":   "NB US Real Estate (CLOSED Feb-26)",
    "VIRTUS": "Virtus US Small Cap (CLOSED Feb-26)",
    "THOR":   "Thornburg Equity Income Builder I",
    "ILF":    "iShares Latin America 40 ETF",
    "4BRZ":   "iShares MSCI Brazil UCITS (DE)",
    "ARGT":   "Global X MSCI Argentina ETF",
    # Fixed Income
    "PIMCO-INC": "PIMCO GIS Income I",
    "PIMCO-LD":  "PIMCO GIS Low Duration Income I",
    "PIMCO-EM":  "PIMCO GIS EM Local Bond I",
    "MANIG":     "Man GLG Global IG Opportunities",
    "SGCB":      "Schroder GAIA Cat Bond Class C",
    "TGF":       "Tenac Global Fund (TGF)",
    "WELL":      "Wellington Credit (CLOSED)",
    "BPCC":      "Barings Private Credit (BPCC)",
}


def status_from_alpha(alpha_pp: float, is_closed: bool) -> str:
    """Classify holding by alpha vs ACWI during holding period."""
    suffix = "_closed" if is_closed else ""
    if alpha_pp is None:
        return "unknown"
    if alpha_pp > 0:
        return "outperform" + suffix
    if alpha_pp < 0:
        return "underperform" + suffix
    return "neutral" + suffix


def status_emoji(status: str) -> str:
    return {
        "outperform":         "[+] OUTPERFORM",
        "outperform_closed":  "[+/X] OUTPERFORM (cerrado)",
        "underperform":       "[-] UNDERPERFORM",
        "underperform_closed":"[-/X] UNDERPERFORM (cerrado)",
        "neutral":            "[=] NEUTRAL",
        "neutral_closed":     "[=/X] NEUTRAL (cerrado)",
        "unknown":            "[?] UNKNOWN",
    }.get(status, "")


def compute_contributions(sleeve_real_path: Path, sleeve_key: str):
    with open(sleeve_real_path) as f:
        data = json.load(f)
    series = data[sleeve_key]
    months = [pt["date"] for pt in series]
    if len(months) < 2:
        raise ValueError(f"Need at least 2 month-end points; got {len(months)}")

    # Build ACWI index lookup: date -> index value
    # Note: ACWI series only available for equity sleeve comparison
    acwi_by_date = {}
    if "acwi_index_series" in data:
        for pt in data["acwi_index_series"]:
            acwi_by_date[pt["date"]] = pt.get("index", pt.get("price"))

    # Build per-ticker timeline
    by_ticker = defaultdict(list)
    for pt in series:
        sleeve_mv = pt["mv_usd"]
        for h in pt["holdings"]:
            by_ticker[h["ticker"]].append({
                "month": pt["date"],
                "qty": h["qty"],
                "price": h["price"],
                "mv": h["mv"],
                "sleeve_mv": sleeve_mv,
            })

    contributions = []
    final_month = months[-1]
    for ticker, points in by_ticker.items():
        if len(points) < 1:
            continue
        period_start = points[0]["month"]
        period_end = points[-1]["month"]
        is_closed = period_end != final_month

        cum_factor = 1.0
        weighted_contrib = 0.0
        for i in range(1, len(points)):
            prev = points[i - 1]
            curr = points[i]
            ret = (curr["price"] / prev["price"]) - 1 if prev["price"] and prev["price"] > 0 else 0
            cum_factor *= (1 + ret)
            if prev["sleeve_mv"] and prev["sleeve_mv"] > 0:
                w = prev["mv"] / prev["sleeve_mv"]
                weighted_contrib += w * ret

        avg_weight = sum(
            p["mv"] / p["sleeve_mv"] for p in points if p["sleeve_mv"] and p["sleeve_mv"] > 0
        ) / len(points) if len(points) > 0 else 0

        twr_pct = (cum_factor - 1) * 100
        contrib_pp = weighted_contrib * 100

        # ============================================================
        # MONEY-WEIGHTED RETURN — Modified Dietz (estándar institucional)
        # Considera el TIMING de cada compra/venta para computar avg capital
        #
        # MWR = (V_end + W_total - D_total) / (Σ D_i × w_i - Σ W_i × w_i)
        # donde w_i = (T - t_i) / T = tiempo restante en período al hacer flow
        # ============================================================
        cash_in = 0.0          # total compras
        sells_received = 0.0   # total ventas (NO incluye MV final)
        deposits_t = []        # (month_idx, amount) for each buy
        withdrawals_t = []     # (month_idx, amount) for each sell
        prev_qty = 0.0
        for i, p in enumerate(points):
            qty_change = p["qty"] - prev_qty
            if qty_change > 0:
                amt = qty_change * p["price"]
                cash_in += amt
                deposits_t.append((i, amt))
            elif qty_change < 0:
                amt = abs(qty_change) * p["price"]
                sells_received += amt
                withdrawals_t.append((i, amt))
            prev_qty = p["qty"]

        final_qty = points[-1]["qty"]
        final_mv = final_qty * points[-1]["price"] if final_qty > 0 else 0
        cash_out = sells_received + final_mv

        net_pnl_usd = cash_out - cash_in

        # Modified Dietz: weight cash flows by time remaining
        n_periods = len(points) - 1
        if n_periods <= 0:
            mwr_pct = None
        else:
            weighted_buys = sum(amt * (n_periods - t) / n_periods for t, amt in deposits_t)
            weighted_sells = sum(amt * (n_periods - t) / n_periods for t, amt in withdrawals_t)
            avg_capital = weighted_buys - weighted_sells  # V_begin = 0
            mwr_pct = (net_pnl_usd / avg_capital * 100) if avg_capital > 0 else None

        # ACWI period return for same exact months
        acwi_period_return_pct = None
        alpha_pp_twr = None
        alpha_pp_mwr = None
        if acwi_by_date:
            acwi_start = acwi_by_date.get(period_start)
            acwi_end = acwi_by_date.get(period_end)
            if acwi_start and acwi_end and acwi_start > 0:
                acwi_period_return_pct = (acwi_end / acwi_start - 1) * 100
                alpha_pp_twr = twr_pct - acwi_period_return_pct
                if mwr_pct is not None:
                    alpha_pp_mwr = mwr_pct - acwi_period_return_pct

        # Status based on MONEY-WEIGHTED alpha (lo que pidió Lucas)
        status = status_from_alpha(alpha_pp_mwr if alpha_pp_mwr is not None else alpha_pp_twr, is_closed)

        contributions.append({
            "ticker": ticker,
            "name": NAME_BY_TICKER.get(ticker, ticker),
            "period_start": period_start,
            "period_end": period_end,
            "months_held": len(points),
            "twr_pct": round(twr_pct, 2),
            "mwr_pct": round(mwr_pct, 2) if mwr_pct is not None else None,
            "net_pnl_usd": round(net_pnl_usd, 0),
            "cash_in_usd": round(cash_in, 0),
            "cash_out_usd": round(cash_out, 0),
            "acwi_period_return_pct": round(acwi_period_return_pct, 2) if acwi_period_return_pct is not None else None,
            "alpha_twr_pp": round(alpha_pp_twr, 2) if alpha_pp_twr is not None else None,
            "alpha_mwr_pp": round(alpha_pp_mwr, 2) if alpha_pp_mwr is not None else None,
            "avg_weight_pct": round(avg_weight * 100, 2),
            "contribution_pp": round(contrib_pp, 2),
            "is_closed": is_closed,
            "status": status,
            "status_label": status_emoji(status),
            "final_mv_usd": round(points[-1]["mv"], 2) if not is_closed else 0,
        })

    # Sort by Money-Weighted alpha vs ACWI descending (most outperformers first)
    contributions.sort(key=lambda c: -(c["alpha_mwr_pp"] if c["alpha_mwr_pp"] is not None else -999))
    return contributions, data


def print_report(sleeve_label: str, contributions: list, src_data: dict):
    print(f"\n{'=' * 150}")
    print(f"{sleeve_label.upper()} SLEEVE — REAL MONEY-WEIGHTED RETURN + ALPHA vs ACWI")
    print(f"Source: {src_data.get('source', 'Pershing transactions')}")
    print(f"Period: {contributions[0]['period_start']} -> {max(c['period_end'] for c in contributions)}")
    print(f"{'=' * 150}")
    print(f"{'Status':32s} {'Ticker':10s} {'Months':>7s} {'$ In':>12s} {'$ Out':>12s} {'NetPnL':>11s} {'MWR%':>8s} {'TWR%':>8s} {'ACWI':>8s} {'Alpha(MWR)':>11s}")
    print("-" * 150)
    for c in contributions:
        mwr_str = f"{c['mwr_pct']:>+7.2f}%" if c['mwr_pct'] is not None else "    —  "
        acwi_str = f"{c['acwi_period_return_pct']:>+7.2f}%" if c['acwi_period_return_pct'] is not None else "    —  "
        alpha_str = f"{c['alpha_mwr_pp']:>+9.2f}pp" if c['alpha_mwr_pp'] is not None else "    —     "
        print(
            f"{c['status_label']:32s} "
            f"{c['ticker']:10s} "
            f"{c['months_held']:>7d} "
            f"${c['cash_in_usd']:>10,.0f} "
            f"${c['cash_out_usd']:>10,.0f} "
            f"${c['net_pnl_usd']:>+9,.0f} "
            f"{mwr_str} "
            f"{c['twr_pct']:>+7.2f}% "
            f"{acwi_str} "
            f"{alpha_str}"
        )

    total_contrib = sum(c["contribution_pp"] for c in contributions)
    total_pnl = sum(c["net_pnl_usd"] for c in contributions)
    print("-" * 150)
    print(f"TOTAL contrib sleeve: {total_contrib:+.2f}pp | TOTAL net PnL: ${total_pnl:+,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleeve", default="equity", choices=["equity", "fi"])
    args = ap.parse_args()

    sleeve_map = {
        "equity": ("data/equity_sleeve_real.json", "sleeve_series_equity", "Equity"),
        "fi":     ("data/fi_sleeve_real.json",     "sleeve_series_fi",     "Fixed Income"),
    }
    src_rel, key, label = sleeve_map[args.sleeve]
    src_path = ROOT / src_rel
    if not src_path.exists():
        print(f"[ERROR] Missing {src_rel} - run portfolio_reconstructor first")
        return 1

    contributions, src_data = compute_contributions(src_path, key)
    print_report(label, contributions, src_data)

    out_path = ROOT / "data" / f"{args.sleeve}_contributions_real.json"
    out = {
        "refreshedAt": datetime.now().isoformat(),
        "sleeve": label,
        "source": "Pershing transaction history (real TWR per holding)",
        "period_start": min(c["period_start"] for c in contributions),
        "period_end": max(c["period_end"] for c in contributions),
        "total_contribution_pp": round(sum(c["contribution_pp"] for c in contributions), 2),
        "holdings": contributions,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[OK] Saved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
