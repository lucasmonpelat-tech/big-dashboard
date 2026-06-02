"""
bmk_refresher.py
================
Computes the 60/40 benchmark return for BIG (since inception 27-Jun-2025).

CAMBIO 2026-06-02: en vez de calcular 0.6*ACWI + 0.4*AGG con rebalance mensual
(que daba tracking error vs el benchmark real ~3pp YTD), ahora usamos AOR
directo - iShares Core Growth Allocation ETF (60% stocks / 40% bonds).

Data source: Yahoo Finance via yfinance (AOR US-listed ETF).
  - AOR = iShares Core Growth Allocation ETF
  - Composicion: ITOT (US Total) + IDEV (Intl Developed) + IEMG (EM) +
    IAGG (Intl Bonds) + AGG (US Aggregate)
  - Es el benchmark 60/40 real mas usado por la industria
  - Replica casi exactamente lo que era el calculo manual ACWI+AGG, pero
    sin tracking error de formula.

Outputs:
    data/bmk_6040.json — daily 60/40 history + period returns
    (formato sin cambios para compatibilidad con dashboard.js)

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
BMK_TICKER = "AOR"  # iShares Core Growth Allocation 60/40


def fetch_yf_history(ticker: str, start: date, end: date) -> list[dict]:
    """Fetch daily OHLC history via yfinance. Returns list of {date, close}."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    h = t.history(start=start.isoformat(), end=(end + timedelta(days=1)).isoformat())
    rows = []
    for ts, row in h.iterrows():
        rows.append({
            "date": ts.strftime("%Y-%m-%d"),
            "close": float(row["Close"]),
        })
    return rows


def build_index_from_etf(hist: list[dict]) -> list[dict]:
    """Normaliza la serie de precios a base 100 (anchor = primer dia)."""
    if not hist:
        return []
    anchor = hist[0]["close"]
    if anchor <= 0:
        return []
    return [
        {"date": r["date"], "value": round(r["close"] / anchor * 100, 4)}
        for r in hist
    ]


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
        print(f"  Fetching {BMK_TICKER} (iShares Core Growth Allocation 60/40) from Yahoo Finance...")
        hist = fetch_yf_history(BMK_TICKER, inception, today)
        print(f"    {len(hist)} bars  ({hist[0]['date']} -> {hist[-1]['date']})")
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if not hist:
        print("ERROR: No history data for AOR")
        return

    series = build_index_from_etf(hist)
    periods = compute_returns(series, inception)

    print(f"\n=== 60/40 Benchmark (AOR — iShares Core Growth Allocation ETF) ===")
    print(f"Latest: {periods['latest_date']} | Value: {periods['latest_value']} (base 100)")
    for k, v in periods["returns"].items():
        print(f"  {k:12s}: {v:+.2f}%" if v is not None else f"  {k:12s}: —")
    print(f"  Volatility  : {periods['volatility']}%")
    print(f"  Sharpe approx: {periods['sharpe_approx']}")

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "source": f"Yahoo Finance {BMK_TICKER} (iShares Core Growth Allocation 60/40)",
        "note": "Single ETF que replica 60% stocks / 40% bonds. Composicion: ITOT + IDEV + IEMG + IAGG + AGG. Reemplaza el calculo viejo 0.6*ACWI + 0.4*AGG.",
        "ticker": BMK_TICKER,
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
