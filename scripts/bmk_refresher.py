"""
bmk_refresher.py
================
Computes the 60/40 benchmark return for BIG (since inception 27-Jun-2025).

Data source: Yahoo Finance via yfinance (ACWI + AGG US-listed ETFs)
Fallback/target: Bahia feed (TODO — user to provide URL/credentials)

Outputs:
    data/bmk_6040.json — daily 60/40 history + period returns

Usage:
    python scripts/bmk_refresher.py
    python scripts/bmk_refresher.py --inception 2025-06-27 --today 2026-04-22
"""

import argparse
import json
import math
from datetime import datetime, date, timedelta
from pathlib import Path

INCEPTION = date(2025, 6, 27)


def fetch_yf_history(ticker: str, start: date, end: date) -> list[dict]:
    """Fetch daily OHLC history via yfinance. Returns list of {date, close}."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    # Add 1 day to 'end' so yfinance includes the last day
    h = t.history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat())
    rows = []
    for ts, row in h.iterrows():
        rows.append({
            "date": ts.strftime("%Y-%m-%d"),
            "close": float(row["Close"]),
        })
    return rows


def compute_6040(acwi_hist, agg_hist):
    """Build 60/40 daily index (base 100), rebalanced monthly."""
    acwi_by_date = {r["date"]: r["close"] for r in acwi_hist}
    agg_by_date = {r["date"]: r["close"] for r in agg_hist}
    common_dates = sorted(set(acwi_by_date.keys()) & set(agg_by_date.keys()))
    if not common_dates:
        return []

    series = []
    d0 = common_dates[0]
    anchor_acwi = acwi_by_date[d0]
    anchor_agg = agg_by_date[d0]
    anchor_value = 100.0
    last_month = d0[:7]

    for d in common_dates:
        month = d[:7]
        if month != last_month:
            anchor_acwi = acwi_by_date[d]
            anchor_agg = agg_by_date[d]
            anchor_value = series[-1]["value"] if series else 100.0
            last_month = month
        acwi_ret = acwi_by_date[d] / anchor_acwi
        agg_ret = agg_by_date[d] / anchor_agg
        value = anchor_value * (0.60 * acwi_ret + 0.40 * agg_ret)
        series.append({"date": d, "value": round(value, 4)})
    return series


def compute_returns(series, inception: date):
    if not series:
        return {}
    latest = series[-1]
    latest_value = latest["value"]
    latest_date = date.fromisoformat(latest["date"])

    def find_ref(target_date):
        target_str = target_date.isoformat()
        for point in reversed(series):
            if point["date"] <= target_str:
                return point["value"]
        return None

    def ret(v_then):
        if v_then is None or v_then == 0:
            return None
        return round((latest_value / v_then - 1) * 100, 2)

    ytd_anchor = find_ref(date(latest_date.year, 1, 1))

    returns = {
        "1W": ret(find_ref(latest_date - timedelta(days=7))),
        "1M": ret(find_ref(latest_date - timedelta(days=30))),
        "3M": ret(find_ref(latest_date - timedelta(days=91))),
        "6M": ret(find_ref(latest_date - timedelta(days=182))),
        "YTD": ret(ytd_anchor),
        "SI": round((latest_value / 100 - 1) * 100, 2),
    }
    days = (latest_date - inception).days
    if days > 0:
        ann = round(((latest_value / 100) ** (365.25 / days) - 1) * 100, 2)
    else:
        ann = None
    returns["Annualized"] = ann

    # Vol annualized
    daily_rets = []
    for i in range(1, len(series)):
        prev = series[i - 1]["value"]
        cur = series[i]["value"]
        if prev > 0:
            daily_rets.append(cur / prev - 1)
    if daily_rets:
        mean = sum(daily_rets) / len(daily_rets)
        var = sum((r - mean) ** 2 for r in daily_rets) / len(daily_rets)
        vol = round(math.sqrt(var) * math.sqrt(252) * 100, 2)
    else:
        vol = None

    # Sharpe (approx, rf=4.3%)
    if ann is not None and vol is not None and vol > 0:
        sharpe = round((ann - 4.3) / vol, 2)
    else:
        sharpe = None

    return {
        "latest_date": latest["date"],
        "latest_value": latest_value,
        "returns": returns,
        "volatility": vol,
        "sharpe_approx": sharpe,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inception", default="2025-06-27")
    parser.add_argument("--today", default=None)
    args = parser.parse_args()
    inception = date.fromisoformat(args.inception)
    today = date.fromisoformat(args.today) if args.today else date.today()

    print(f"[{datetime.now()}] Computing 60/40 benchmark...")
    print(f"  Period: {inception} to {today}")

    try:
        print("  Fetching ACWI from Yahoo Finance...")
        acwi_hist = fetch_yf_history("ACWI", inception, today)
        print(f"    {len(acwi_hist)} bars")

        print("  Fetching AGG from Yahoo Finance...")
        agg_hist = fetch_yf_history("AGG", inception, today)
        print(f"    {len(agg_hist)} bars")
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if not acwi_hist or not agg_hist:
        print("ERROR: No history data")
        return

    series = compute_6040(acwi_hist, agg_hist)
    periods = compute_returns(series, inception)

    print(f"\n=== 60/40 Benchmark (ACWI 60% + AGG 40%, monthly rebalance) ===")
    print(f"Latest: {periods['latest_date']} | Value: {periods['latest_value']} (base 100)")
    for k, v in periods["returns"].items():
        print(f"  {k:12s}: {v:+.2f}%" if v is not None else f"  {k:12s}: —")
    print(f"  Volatility  : {periods['volatility']}%")
    print(f"  Sharpe approx: {periods['sharpe_approx']}")

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "source": "Yahoo Finance ACWI+AGG (monthly rebalance 60/40)",
        "note": "Proxy for MSCI ACWI + Bloomberg US Agg. Target: replace with Bahia feed.",
        "inception": args.inception,
        "periods": periods,
        "series_length": len(series),
        "series": series,
    }
    out = Path(__file__).parent.parent / "data" / "bmk_6040.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nWritten to: {out}")


if __name__ == "__main__":
    main()
