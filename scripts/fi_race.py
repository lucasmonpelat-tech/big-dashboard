"""
fi_race.py
==========
Constructs the BIG Fixed Income Sleeve index and compares vs Bloomberg US Aggregate (AGG).
Also computes yield spread vs US Treasury (10Y UST).

Data sources:
  - UCITS FI funds → baha.com monthly returns (JSON pre-scraped)
  - Tenac Global Fund → YTW/12 monthly carry proxy (no public data)
  - AGG benchmark → Yahoo Finance AGG ETF
  - US Treasury 10Y yield → Yahoo ^TNX

Output: data/fi_race.json
"""

import json
import math
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
BIG_INCEPTION = date(2025, 6, 30)

# ===============================================================
# Current FI Sleeve holdings — SINGLE SOURCE OF TRUTH
# Carga desde:
#   - positions_latest.json   -> isin, ticker, value_usd
#   - data/funds/<TICKER>.json -> name, fi_metrics {ytw, duration, maturity, rating}
# DATA_SOURCE mapea ticker -> metodo de retorno mensual (baha JSON o carry proxy).
# ===============================================================
DATA_SOURCE = {
    # Funds que NO tienen serie de returns en data/baha/ usan carry (ytw/12).
    "TGF": "carry",  # Tenac no publica serie publica
}  # default = "baha"


def _load_fi_holdings():
    positions = json.loads((ROOT / "data" / "positions_latest.json").read_text(encoding="utf-8"))["positions"]
    fi_positions = [p for p in positions if p["sleeve"] == "Fixed Income"]
    holdings = []
    for p in fi_positions:
        ticker = p["ticker"]
        fpath = ROOT / "data" / "funds" / f"{ticker}.json"
        if not fpath.exists():
            print(f"WARN: data/funds/{ticker}.json no existe — saltando {ticker}")
            continue
        fd = json.loads(fpath.read_text(encoding="utf-8"))
        fm = fd.get("fi_metrics", {})
        holdings.append((
            p["isin"],
            ticker,
            fd.get("name", p["name"]),
            p["value"],
            DATA_SOURCE.get(ticker, "baha"),
            fm.get("ytw") or 0,
            fm.get("duration") or 0,
            fm.get("maturity") or 0,
            fm.get("rating", "—"),
        ))
    return holdings


FI_HOLDINGS = _load_fi_holdings()

SPANISH_MONTHS = {'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}


def fetch_yahoo_monthly(ticker: str, start: date, end: date) -> dict:
    """Return {YYYY-MM: return_decimal}, month-end close-based."""
    import yfinance as yf
    h = yf.Ticker(ticker).history(start=start.isoformat(), end=(end + timedelta(days=2)).isoformat())
    if h.empty:
        return {}
    monthly_close = h["Close"].resample("ME").last()
    rets = {}
    prev = None
    for ts, val in monthly_close.items():
        if math.isnan(val):
            continue
        if prev is not None:
            rets[f"{ts.year}-{ts.month:02d}"] = float(val / prev - 1)
        prev = val
    return rets


def fetch_yahoo_daily(ticker: str, start: date, end: date) -> dict:
    import yfinance as yf
    h = yf.Ticker(ticker).history(start=start.isoformat(), end=(end + timedelta(days=3)).isoformat())
    return {ts.strftime("%Y-%m-%d"): float(row["Close"]) for ts, row in h.iterrows()}


def load_baha_monthly(isin: str) -> dict:
    fp = ROOT / "data" / "baha" / f"{isin}.json"
    if not fp.exists():
        return {}
    with open(fp) as f:
        data = json.load(f)
    rets = {}
    for year_str, months_map in data["monthlyReturns"].items():
        for m_name, pct in months_map.items():
            if m_name in SPANISH_MONTHS:
                rets[f"{year_str}-{SPANISH_MONTHS[m_name]:02d}"] = float(pct) / 100
    return rets


def carry_monthly_returns(ytw_annual: float, months_range: list) -> dict:
    """Generate monthly carry returns from annual YTW."""
    monthly = (1 + ytw_annual / 100) ** (1 / 12) - 1
    return {m: monthly for m in months_range}


def month_range(start: date, end: date):
    y, m = start.year, start.month
    while True:
        yield f"{y}-{m:02d}"
        if y == end.year and m == end.month:
            break
        m += 1
        if m > 12:
            m = 1
            y += 1


def compute_sleeve_index(inception: date, end: date) -> dict:
    returns_by_holding = {}
    holding_sources = {}

    months_list = list(month_range(date(inception.year, inception.month, 1), end))

    for isin, ticker, name, value, src, ytw, dur, mat, rating in FI_HOLDINGS:
        if src == "baha":
            rets = load_baha_monthly(isin)
            source = f"baha:{isin}"
        elif src == "carry":
            rets = carry_monthly_returns(ytw, months_list)
            source = f"carry:{ytw:.2f}%/yr"
        else:
            rets = {}
            source = "unknown"
        returns_by_holding[isin] = rets
        holding_sources[isin] = source
        print(f"  {ticker:10s} ({source:25s}): {len(rets)} months")

    total_fi = sum(h[3] for h in FI_HOLDINGS)

    # Build sleeve monthly returns
    start_month = f"{inception.year}-{inception.month:02d}"
    sleeve_rets = {}
    for month in months_list:
        weighted = 0
        known_w = 0
        for isin, ticker, name, value, src, ytw, dur, mat, rating in FI_HOLDINGS:
            w = value / total_fi
            if month in returns_by_holding[isin]:
                weighted += w * returns_by_holding[isin][month]
                known_w += w
        sleeve_rets[month] = weighted / known_w if known_w > 0.5 and known_w < 1 else (weighted if known_w >= 1 else None)

    # Index base 100
    index = {start_month: 100.0}
    val = 100.0
    for month in months_list:
        if month == start_month:
            continue
        r = sleeve_rets.get(month)
        if r is None:
            continue
        val *= (1 + r)
        index[month] = round(val, 4)

    return {
        "monthly_returns": {m: round(r, 6) if r is not None else None for m, r in sleeve_rets.items()},
        "index": index,
        "holding_returns": returns_by_holding,
        "holding_sources": holding_sources,
    }


def compute_agg_index(inception: date, end: date) -> dict:
    rets = fetch_yahoo_monthly("AGG", inception - timedelta(days=40), end)
    start_month = f"{inception.year}-{inception.month:02d}"
    index = {start_month: 100.0}
    val = 100.0
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    for month in months_list:
        if month == start_month:
            continue
        if month in rets:
            val *= (1 + rets[month])
            index[month] = round(val, 4)
    return {"monthly_returns": rets, "index": index}


def compute_ust_yield(end: date) -> dict:
    """Fetch 10Y US Treasury yield (^TNX) - returns daily series + latest."""
    try:
        daily = fetch_yahoo_daily("^TNX", end - timedelta(days=60), end)
        latest_date = max(daily.keys()) if daily else None
        latest_value = daily.get(latest_date) if latest_date else None
        # ^TNX Yahoo convention: sometimes returns yield directly (4.30 for 4.30%),
        # sometimes *10 (43.0). Detect based on magnitude.
        if latest_value is not None:
            latest_yield = latest_value if latest_value < 20 else latest_value / 10
        else:
            latest_yield = None
        return {
            "series": daily,
            "latest_date": latest_date,
            "latest_yield_pct": latest_yield,
        }
    except Exception as e:
        print(f"  UST fetch failed: {e}")
        return {"series": {}, "latest_date": None, "latest_yield_pct": 4.30}  # fallback


def period_return(index_map: dict, from_key: str, to_key: str):
    if from_key in index_map and to_key in index_map:
        return round((index_map[to_key] / index_map[from_key] - 1) * 100, 2)
    return None


def compute_stats(sleeve_idx: dict, agg_idx: dict):
    months = sorted(sleeve_idx.keys())
    if not months:
        return {}
    latest = months[-1]

    def months_back(n):
        idx = len(months) - 1 - n
        return months[idx] if idx >= 0 else None

    ytd_key = f"{int(latest[:4])-1}-12"
    if ytd_key not in sleeve_idx:
        ytd_key = months[0]

    periods = {
        "1M": months_back(1),
        "3M": months_back(3),
        "6M": months_back(6),
        "YTD": ytd_key,
        "SI": months[0],
    }

    result = {"latest_month": latest, "returns": {}}
    for name, from_m in periods.items():
        if from_m is None:
            result["returns"][name] = {"sleeve": None, "agg": None, "alpha": None}
            continue
        s = period_return(sleeve_idx, from_m, latest)
        a = period_return(agg_idx, from_m, latest)
        alpha = round(s - a, 2) if s is not None and a is not None else None
        result["returns"][name] = {"sleeve": s, "agg": a, "alpha": alpha}

    n_months = len(months) - 1
    if n_months > 0:
        si_sleeve = sleeve_idx[latest] / 100
        si_agg = agg_idx.get(latest, 100) / 100
        result["annualized"] = {
            "sleeve": round((si_sleeve ** (12 / n_months) - 1) * 100, 2),
            "agg":    round((si_agg ** (12 / n_months) - 1) * 100, 2) if si_agg else None,
        }
        result["annualized"]["alpha"] = round(
            result["annualized"]["sleeve"] - (result["annualized"]["agg"] or 0), 2
        )

    return result


def compute_holding_contributions(sleeve_data, inception: date, end: date, ust_yield: float) -> list:
    total_fi = sum(h[3] for h in FI_HOLDINGS)
    start_month = f"{inception.year}-{inception.month:02d}"
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    latest = months_list[-1]

    ytd_year = end.year
    ytd_months = [m for m in months_list if int(m[:4]) == ytd_year]

    holdings_perf = []
    for isin, ticker, name, value, src, ytw, dur, mat, rating in FI_HOLDINGS:
        rets = sleeve_data["holding_returns"][isin]
        cum_si = 1.0
        counted_si = 0
        for m in months_list:
            if m == start_month:
                continue
            if m in rets:
                cum_si *= (1 + rets[m])
                counted_si += 1
        si_return = round((cum_si - 1) * 100, 2) if counted_si > 0 else None

        cum_ytd = 1.0
        counted_ytd = 0
        for m in ytd_months:
            if m in rets:
                cum_ytd *= (1 + rets[m])
                counted_ytd += 1
        ytd_return = round((cum_ytd - 1) * 100, 2) if counted_ytd > 0 else None

        weight = round(value / total_fi * 100, 2)
        contribution = round(si_return * weight / 100, 2) if si_return is not None else None
        ytd_contribution = round(ytd_return * weight / 100, 2) if ytd_return is not None else None
        spread_vs_ust = round(ytw - ust_yield, 2) if ust_yield else None

        holdings_perf.append({
            "isin": isin,
            "ticker": ticker,
            "name": name,
            "value_usd": value,
            "weight_pct": weight,
            "si_return_pct": si_return,
            "ytd_return_pct": ytd_return,
            "contribution_pct": contribution,
            "ytd_contribution_pct": ytd_contribution,
            "ytw": ytw,
            "duration": dur,
            "maturity": mat,
            "rating": rating,
            "spread_vs_ust": spread_vs_ust,
            "source": sleeve_data["holding_sources"][isin],
        })
    return holdings_perf


def main():
    today = date.today()
    print(f"[{datetime.now()}] Building BIG FI Sleeve vs Bloomberg US Aggregate (AGG)")
    print(f"  Period: {BIG_INCEPTION} to {today}")

    print("\nBuilding FI sleeve index from:")
    sleeve = compute_sleeve_index(BIG_INCEPTION, today)

    print("\nFetching AGG benchmark...")
    agg = compute_agg_index(BIG_INCEPTION, today)

    print("\nFetching 10Y US Treasury yield...")
    ust = compute_ust_yield(today)
    ust_yield = ust["latest_yield_pct"] or 4.30
    print(f"  UST 10Y: {ust_yield:.2f}% ({ust['latest_date']})")

    stats = compute_stats(sleeve["index"], agg["index"])
    contributions = compute_holding_contributions(sleeve, BIG_INCEPTION, today, ust_yield)

    # Weighted portfolio metrics
    total_fi = sum(h[3] for h in FI_HOLDINGS)
    wtd_ytw = sum(h[5] * h[3] / total_fi for h in FI_HOLDINGS)
    wtd_dur = sum(h[6] * h[3] / total_fi for h in FI_HOLDINGS)
    wtd_mat = sum(h[7] * h[3] / total_fi for h in FI_HOLDINGS)
    portfolio_metrics = {
        "weighted_ytw": round(wtd_ytw, 2),
        "weighted_duration": round(wtd_dur, 2),
        "weighted_maturity": round(wtd_mat, 2),
        "spread_vs_ust_10y": round(wtd_ytw - ust_yield, 2),
        "total_fi_usd": total_fi,
        "ust_10y_yield": round(ust_yield, 2),
    }

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "inception": BIG_INCEPTION.isoformat(),
        "benchmark": "Bloomberg US Aggregate (via AGG ETF)",
        "ust_reference": "10Y US Treasury (^TNX)",
        "portfolio_metrics": portfolio_metrics,
        "stats": stats,
        "sleeve_index": sleeve["index"],
        "agg_index": agg["index"],
        "sleeve_monthly_returns": sleeve["monthly_returns"],
        "agg_monthly_returns": agg["monthly_returns"],
        "holdings": contributions,
    }

    out_path = ROOT / "data" / "fi_race.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 70)
    print("FI SLEEVE vs AGG (Bloomberg US Aggregate)")
    print("=" * 70)
    if stats.get("returns"):
        for p, v in stats["returns"].items():
            s = v["sleeve"]; a = v["agg"]; al = v["alpha"]
            s_str = f"{s:+.2f}%" if s is not None else "   —"
            a_str = f"{a:+.2f}%" if a is not None else "   —"
            al_str = f"{al:+.2f}pp" if al is not None else "   —"
            print(f"  {p:5s} | Sleeve: {s_str:>10s} | AGG: {a_str:>10s} | Alpha: {al_str}")
    if stats.get("annualized"):
        ann = stats["annualized"]
        print(f"\n  Ann.  | Sleeve: {ann['sleeve']:+.2f}% | AGG: {ann['agg']:+.2f}% | Alpha: {ann['alpha']:+.2f}pp")

    print("\n" + "=" * 70)
    print("PORTFOLIO METRICS")
    print("=" * 70)
    print(f"  Weighted YTW:      {portfolio_metrics['weighted_ytw']:.2f}%")
    print(f"  Weighted Duration: {portfolio_metrics['weighted_duration']:.2f} yrs")
    print(f"  Weighted Maturity: {portfolio_metrics['weighted_maturity']:.2f} yrs")
    print(f"  UST 10Y yield:     {portfolio_metrics['ust_10y_yield']:.2f}%")
    print(f"  Spread vs UST 10Y: {portfolio_metrics['spread_vs_ust_10y']:+.2f}pp")

    print("\n" + "=" * 70)
    print("HOLDING CONTRIBUTIONS")
    print("=" * 70)
    for h in sorted(contributions, key=lambda x: -(x.get("contribution_pct") or -999)):
        sc = h["si_return_pct"]; c = h["contribution_pct"]
        sc_s = f"{sc:+.2f}%" if sc is not None else "   —"
        c_s = f"{c:+.2f}pp" if c is not None else "   —"
        print(f"  {h['ticker']:10s} | wt {h['weight_pct']:5.1f}% | YTW {h['ytw']:5.2f}% | SI ret {sc_s:>10s} | contrib {c_s:>10s} | spread {h['spread_vs_ust']:+.2f}pp")

    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
