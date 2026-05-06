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


def status_from_contribution(contrib_pp: float, is_closed: bool) -> str:
    """Classify holding by contribution magnitude."""
    if is_closed:
        return "closed"
    if contrib_pp >= 1.0:
        return "winner"
    if contrib_pp >= 0:
        return "lagging"
    return "loser"


def status_emoji(status: str) -> str:
    return {
        "winner":  "[W] Winner",
        "lagging": "[~] Lagging",
        "loser":   "[L] Loser",
        "closed":  "[X] Closed",
    }.get(status, "")


def compute_contributions(sleeve_real_path: Path, sleeve_key: str):
    with open(sleeve_real_path) as f:
        data = json.load(f)
    series = data[sleeve_key]
    months = [pt["date"] for pt in series]
    if len(months) < 2:
        raise ValueError(f"Need at least 2 month-end points; got {len(months)}")

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
        # If only 1 point, contribution is 0 (just entered or just exited)
        period_start = points[0]["month"]
        period_end = points[-1]["month"]
        is_closed = period_end != final_month

        # Compute cumulative price return + weighted contribution
        cum_factor = 1.0
        weighted_contrib = 0.0
        weight_sum = 0.0
        n_months_for_return = 0
        for i in range(1, len(points)):
            prev = points[i - 1]
            curr = points[i]
            # Price return (handles in-month buys imperfectly but acceptable)
            if prev["price"] and prev["price"] > 0:
                ret = (curr["price"] / prev["price"]) - 1
            else:
                ret = 0
            cum_factor *= (1 + ret)
            n_months_for_return += 1
            # Weight at start of month
            if prev["sleeve_mv"] and prev["sleeve_mv"] > 0:
                w = prev["mv"] / prev["sleeve_mv"]
                weighted_contrib += w * ret
                weight_sum += w

        # Avg weight (across all months held)
        avg_weight = sum(
            p["mv"] / p["sleeve_mv"] for p in points if p["sleeve_mv"] and p["sleeve_mv"] > 0
        ) / len(points) if len(points) > 0 else 0

        twr_pct = (cum_factor - 1) * 100
        contrib_pp = weighted_contrib * 100
        status = status_from_contribution(contrib_pp, is_closed)

        contributions.append({
            "ticker": ticker,
            "name": NAME_BY_TICKER.get(ticker, ticker),
            "period_start": period_start,
            "period_end": period_end,
            "months_held": len(points),
            "twr_pct": round(twr_pct, 2),
            "avg_weight_pct": round(avg_weight * 100, 2),
            "contribution_pp": round(contrib_pp, 2),
            "is_closed": is_closed,
            "status": status,
            "status_label": status_emoji(status),
            "final_mv_usd": round(points[-1]["mv"], 2) if not is_closed else 0,
        })

    # Sort by contribution descending
    contributions.sort(key=lambda c: -c["contribution_pp"])
    return contributions, data


def print_report(sleeve_label: str, contributions: list, src_data: dict):
    print(f"\n{'=' * 100}")
    print(f"{sleeve_label.upper()} SLEEVE — REAL TWR CONTRIBUTIONS")
    print(f"Source: {src_data.get('source', 'Pershing transactions')}")
    print(f"Period: {contributions[0]['period_start']} -> {max(c['period_end'] for c in contributions)}")
    print(f"{'=' * 100}")
    print(f"{'Status':12s} {'Ticker':10s} {'Months':>7s} {'AvgWeight':>10s} {'TWR%':>9s} {'Contrib pp':>11s}  Period")
    print("-" * 100)
    for c in contributions:
        print(
            f"{c['status_label']:14s} "
            f"{c['ticker']:10s} "
            f"{c['months_held']:>7d} "
            f"{c['avg_weight_pct']:>9.2f}% "
            f"{c['twr_pct']:>+8.2f}% "
            f"{c['contribution_pp']:>+10.2f}pp "
            f"{c['period_start']} -> {c['period_end']}"
        )

    total_contrib = sum(c["contribution_pp"] for c in contributions)
    print("-" * 100)
    print(f"{'TOTAL':14s} {'':10s} {'':>7s} {'':>10s} {'':>9s} {total_contrib:>+10.2f}pp")


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
