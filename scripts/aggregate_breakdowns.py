"""
aggregate_breakdowns.py
=======================
Toma los per-fund JSONs (output de parse_factsheet.py) + Pershing positions,
y genera breakdowns BIG-level ponderados.

Reads:
  data/funds/{TICKER}.json         (per-fund parsed data)
  data/positions_latest.json       (BIG weights from Pershing)

Outputs:
  data/breakdowns/equity_sectorial.json
  data/breakdowns/equity_regional.json
  data/breakdowns/fi_credit_quality.json
  data/breakdowns/acwi_overlap.json
  ... etc

Usage:
    python scripts/aggregate_breakdowns.py
"""

import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ROOT = Path(__file__).parent.parent


def load_positions():
    with open(ROOT / "data" / "positions_latest.json") as f:
        d = json.load(f)
    # Build ticker -> weight map for equity sleeve
    eq_weights = {}
    fi_weights = {}
    eq_total = 0
    fi_total = 0
    for p in d["positions"]:
        if p["sleeve"] == "Equity":
            eq_weights[p["ticker"]] = p["pct"]
            eq_total += p["pct"]
        elif p["sleeve"] == "Fixed Income":
            fi_weights[p["ticker"]] = p["pct"]
            fi_total += p["pct"]
    return {
        "equity_weights": eq_weights,
        "equity_total": eq_total,
        "fi_weights": fi_weights,
        "fi_total": fi_total,
        "as_of": d.get("as_of"),
    }


def load_fund_data(ticker):
    """Load per-fund parsed JSON. Returns None if not found."""
    fp = ROOT / "data" / "funds" / f"{ticker}.json"
    if not fp.exists():
        return None
    with open(fp, encoding="utf-8") as f:
        return json.load(f)


def aggregate_equity_sectorial(positions):
    """Weighted sector breakdown for BIG equity sleeve.

    For each equity fund: load its sector breakdown, weight by (fund_weight / equity_total).
    """
    eq_weights = positions["equity_weights"]
    eq_total = positions["equity_total"]
    if eq_total == 0:
        return None

    weighted_sectors = defaultdict(float)
    funds_with_data = []
    funds_missing = []
    for ticker, pct in eq_weights.items():
        fund_data = load_fund_data(ticker)
        if not fund_data or not fund_data.get("sectors"):
            funds_missing.append(ticker)
            continue
        funds_with_data.append(ticker)
        # Weight within equity sleeve
        weight_in_sleeve = pct / eq_total
        for sector, sector_pct in fund_data["sectors"].items():
            weighted_sectors[sector] += weight_in_sleeve * sector_pct

    total_covered = sum(eq_weights[t] for t in funds_with_data)
    coverage_pct = total_covered / eq_total * 100 if eq_total else 0

    return {
        "method": "Weighted sector exposure across equity sleeve",
        "funds_with_data": funds_with_data,
        "funds_missing": funds_missing,
        "coverage_pct": round(coverage_pct, 1),
        "sectors": {k: round(v, 2) for k, v in sorted(weighted_sectors.items(), key=lambda x: -x[1])},
    }


def aggregate_equity_regional(positions):
    """Weighted regional breakdown for BIG equity sleeve."""
    eq_weights = positions["equity_weights"]
    eq_total = positions["equity_total"]
    if eq_total == 0:
        return None

    weighted_regions = defaultdict(float)
    funds_with_data = []
    funds_missing = []
    for ticker, pct in eq_weights.items():
        fund_data = load_fund_data(ticker)
        if not fund_data or not fund_data.get("regions"):
            funds_missing.append(ticker)
            continue
        funds_with_data.append(ticker)
        weight_in_sleeve = pct / eq_total
        for region, region_pct in fund_data["regions"].items():
            weighted_regions[region] += weight_in_sleeve * region_pct

    total_covered = sum(eq_weights[t] for t in funds_with_data)
    coverage_pct = total_covered / eq_total * 100 if eq_total else 0

    return {
        "method": "Weighted regional exposure across equity sleeve",
        "funds_with_data": funds_with_data,
        "funds_missing": funds_missing,
        "coverage_pct": round(coverage_pct, 1),
        "regions": {k: round(v, 2) for k, v in sorted(weighted_regions.items(), key=lambda x: -x[1])},
    }


def aggregate_acwi_overlap(positions):
    """Recompute ACWI top 10 lookthrough from per-fund top_holdings."""
    # Read ACWI top 10
    acwi_json = ROOT / "data" / "acwi_overlap.json"
    if not acwi_json.exists():
        return None
    with open(acwi_json) as f:
        acwi_data = json.load(f)
    acwi_top10 = [(h["ticker"], h["name"], h["weight_acwi"]) for h in acwi_data["overlap"]]

    eq_weights = positions["equity_weights"]
    overlap = []
    total_big = 0
    for ticker_acwi, name, weight_acwi in acwi_top10:
        big_exposure = 0
        contributors = []
        for ticker_big, big_pct in eq_weights.items():
            fund_data = load_fund_data(ticker_big)
            if not fund_data:
                continue
            holdings = fund_data.get("top_holdings") or {}
            # Try to find this ACWI stock in fund's holdings (fuzzy name match)
            for h_name, h_pct in holdings.items():
                name_lower = h_name.lower()
                acwi_name_lower = name.lower()
                # Match by partial name (e.g., "Apple" matches "APPLE INC")
                base = acwi_name_lower.split()[0]
                if base in name_lower or ticker_acwi.lower() in name_lower:
                    contribution = big_pct * h_pct / 100
                    big_exposure += contribution
                    contributors.append({"fund": ticker_big, "weight": h_pct, "contribution": round(contribution, 3)})
                    break

        overlap.append({
            "ticker": ticker_acwi,
            "name": name,
            "weight_acwi": weight_acwi,
            "weight_big": round(big_exposure, 3),
            "diff_pp": round(big_exposure - weight_acwi, 3),
            "contributors": contributors,
        })
        total_big += big_exposure

    total_acwi = sum(h[2] for h in acwi_top10)
    return {
        "summary": {
            "total_acwi_top10": round(total_acwi, 2),
            "total_big_top10_exposure": round(total_big, 2),
            "diff_pp": round(total_big - total_acwi, 2),
        },
        "overlap": overlap,
    }


def aggregate_fi_metrics(positions):
    """Weighted YTW / Duration / Maturity / Current Yield for FI sleeve."""
    fi_weights = positions["fi_weights"]
    fi_total = positions["fi_total"]
    if fi_total == 0:
        return None

    accumulators = defaultdict(lambda: {"sum": 0, "weight_sum": 0})
    funds_with_data = []
    funds_missing = []
    for ticker, pct in fi_weights.items():
        fund_data = load_fund_data(ticker)
        if not fund_data or not fund_data.get("fi_metrics"):
            funds_missing.append(ticker)
            continue
        fi_m = fund_data["fi_metrics"]
        weight_in_sleeve = pct / fi_total
        funds_with_data.append(ticker)
        for k, v in fi_m.items():
            if isinstance(v, (int, float)):
                accumulators[k]["sum"] += v * weight_in_sleeve
                accumulators[k]["weight_sum"] += weight_in_sleeve

    metrics = {}
    for k, acc in accumulators.items():
        if acc["weight_sum"] > 0:
            metrics[k] = round(acc["sum"], 2)

    return {
        "method": "Weighted FI metrics (YTW/Dur/Venc/CurYld) across FI sleeve",
        "funds_with_data": funds_with_data,
        "funds_missing": funds_missing,
        "metrics": metrics,
    }


def main():
    out_dir = ROOT / "data" / "breakdowns"
    out_dir.mkdir(parents=True, exist_ok=True)

    positions = load_positions()
    print(f"Positions: as_of={positions['as_of']}, eq_total={positions['equity_total']:.2f}%, fi_total={positions['fi_total']:.2f}%")
    print()

    aggregates = {
        "equity_sectorial": aggregate_equity_sectorial(positions),
        "equity_regional": aggregate_equity_regional(positions),
        "acwi_overlap_recomputed": aggregate_acwi_overlap(positions),
        "fi_metrics": aggregate_fi_metrics(positions),
    }

    for name, data in aggregates.items():
        if data is None:
            print(f"  {name}: SKIP (no data)")
            continue
        out_path = out_dir / f"{name}.json"
        with open(out_path, "w") as f:
            json.dump({
                "refreshedAt": datetime.now().isoformat(),
                "source": "aggregate_breakdowns.py from per-fund factsheet JSONs",
                **data,
            }, f, indent=2)
        # Print summary
        if name == "equity_sectorial":
            print(f"  {name}: {len(data.get('funds_with_data', []))}/{len(data.get('funds_with_data', []))+len(data.get('funds_missing', []))} funds with data | coverage {data['coverage_pct']}%")
        if name == "acwi_overlap_recomputed":
            s = data.get("summary", {})
            print(f"  {name}: ACWI top10={s.get('total_acwi_top10')}%, BIG={s.get('total_big_top10_exposure')}%, diff={s.get('diff_pp')}pp")
        if name == "fi_metrics":
            print(f"  {name}: {len(data.get('funds_with_data', []))} FI funds | metrics={data.get('metrics')}")
        if name == "equity_regional":
            print(f"  {name}: {len(data.get('funds_with_data', []))} funds | coverage {data.get('coverage_pct')}%")

    print()
    print(f"[OK] Saved to {out_dir}/")


if __name__ == "__main__":
    main()
