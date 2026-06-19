"""
equity_race.py
==============
Constructs the BIG Equity Sleeve index (base 100 at BIG inception) and
computes performance vs MSCI ACWI benchmark for the "Equity Race" tab.

Data sources:
  1. ETFs with public tickers → Yahoo Finance (daily): CSPX, ILF, ARGT, 4BRZ
  2. UCITS without public tickers → baha.com monthly returns (pre-scraped JSON)
     located at data/baha/<ISIN>.json
  3. Benchmark → MSCI ACWI via ACWI ETF (Yahoo daily)

Weights = current portfolio weights (from BIG_POSITIONS equity holdings).
Approach: compute monthly TWR for each holding, blend with current weights,
compound to get equity sleeve index base 100.

Output: data/equity_race.json
"""

import json
import math
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent

BIG_INCEPTION = date(2025, 6, 30)  # First Lynk NAV = 100

# ---------------------------------------------------------------------
# Current Equity Sleeve weights (from data/funds_metadata.js)
# These are weights within the equity sleeve (should sum to ~100%)
# ---------------------------------------------------------------------
EQUITY_HOLDINGS = [
    # (isin, ticker, name, value_usd, yahoo_ticker or None)
    # Values from Pershing May 5, 2026
    ("IE00B5BMR087", "CSPX",  "iShares Core S&P 500 UCITS",              2657592.48, "CSPX.L"),  # UCITS real (London), no proxy SPY
    ("IE00BFMHRK20", "NBGMT", "NB Global Equity Megatrends I",           1227372.60, None),
    ("LU1985812756", "MFSCV", "MFS Meridian Contrarian Value I1",        1146067.83, None),
    ("IE00B6YCBF59", "THOR",  "Thornburg Equity Income Builder I",       610432.34,  None),
    ("LU2940405447", "JHGSC", "Janus Henderson Global Smaller Cos F2",   570389.10,  None),
    ("IE00BF4KN675", "LGLI",  "Lazard Global Listed Infrastructure A",   535776.76,  None),
    ("DE000A0Q4R85", "4BRZ",  "iShares MSCI Brazil UCITS (DE)",          383356.47,  "4BRZ.DE"),   # UCITS DE real, no proxy EWZ
    ("US37950E2596", "ARGT",  "Global X MSCI Argentina ETF",             359520.00,  "ARGT"),
    ("US4642873909", "ILF",   "iShares Latin America 40 ETF",            357600.00,  "ILF"),
]

# Override: para CSPX usar el UCITS real (CSPX.L) en lugar del proxy SPY
# 2026-06-18: Lucas pidio datos correctos. SPY da YTD +10.6% pero CSPX.L da +9.21%
# (diff por TER, FX y dividend treatment del UCITS USD Acc vs SPY USD Dist).
YAHOO_OVERRIDES = {
    "IE00B5BMR087": "CSPX.L",   # iShares Core S&P 500 UCITS USD Acc (London)
    "DE000A0Q4R85": "4BRZ.DE",  # iShares MSCI Brazil UCITS DE (Xetra)
}

SPANISH_MONTHS = {
    'ene': 1, 'feb': 2, 'mar': 3, 'abr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'ago': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dic': 12,
}


def fetch_yahoo_monthly(ticker: str, start: date, end: date) -> dict:
    """Return {YYYY-MM: return_pct_decimal} for a ticker via yfinance.
    Last price of each month used."""
    import yfinance as yf
    h = yf.Ticker(ticker).history(start=start.isoformat(), end=(end + timedelta(days=2)).isoformat())
    if h.empty:
        return {}
    # Resample to month-end
    monthly_close = h["Close"].resample("ME").last()
    rets = {}
    prev = None
    for ts, val in monthly_close.items():
        if math.isnan(val):
            continue
        if prev is not None:
            month_key = f"{ts.year}-{ts.month:02d}"
            rets[month_key] = float(val / prev - 1)
        prev = val
    return rets


def load_baha_monthly(isin: str) -> dict:
    """Return {YYYY-MM: return_decimal} from scraped baha JSON."""
    fp = ROOT / "data" / "baha" / f"{isin}.json"
    if not fp.exists():
        return {}
    with open(fp) as f:
        data = json.load(f)
    rets = {}
    for year_str, months_map in data["monthlyReturns"].items():
        year = int(year_str)
        for m_name, pct in months_map.items():
            if m_name not in SPANISH_MONTHS:
                continue
            m = SPANISH_MONTHS[m_name]
            rets[f"{year}-{m:02d}"] = float(pct) / 100.0
    return rets


def month_range(start: date, end: date):
    """Yield YYYY-MM strings inclusive between start and end."""
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
    """Build the equity sleeve TWR index base 100 at inception."""
    # Load returns for each holding
    returns_by_holding = {}
    holding_sources = {}
    for isin, ticker, name, value, yf_ticker in EQUITY_HOLDINGS:
        if yf_ticker and isin not in YAHOO_OVERRIDES:
            rets = fetch_yahoo_monthly(yf_ticker, inception - timedelta(days=40), end)
            source = f"Yahoo:{yf_ticker}"
        elif isin in YAHOO_OVERRIDES:
            rets = fetch_yahoo_monthly(YAHOO_OVERRIDES[isin], inception - timedelta(days=40), end)
            source = f"Yahoo:{YAHOO_OVERRIDES[isin]} (proxy)"
        else:
            rets = load_baha_monthly(isin)
            source = f"baha:{isin}"
        returns_by_holding[isin] = rets
        holding_sources[isin] = source
        print(f"  {ticker:8s} ({source:25s}): {len(rets)} months")

    # Determine total equity value for weight normalization
    total_equity = sum(h[3] for h in EQUITY_HOLDINGS)

    # Start at June 2025 (inception month, returns for July 2025 onward)
    # For partial month: skip first incomplete month
    months_list = list(month_range(date(inception.year, inception.month, 1), end))

    # Build sleeve monthly returns
    sleeve_rets = {}
    for month in months_list:
        weighted_ret = 0
        known_weight = 0
        missing = []
        for isin, ticker, name, value, _ in EQUITY_HOLDINGS:
            weight = value / total_equity
            if month in returns_by_holding[isin]:
                weighted_ret += weight * returns_by_holding[isin][month]
                known_weight += weight
            else:
                missing.append(ticker)
        if known_weight > 0.5:
            # Normalize: assume missing holdings returned market avg (known_weight sum)
            sleeve_rets[month] = weighted_ret / known_weight if known_weight < 1 else weighted_ret
            if missing:
                print(f"    {month}: missing {missing}, normalized")
        else:
            sleeve_rets[month] = None

    # Build base-100 index
    index = {}
    val = 100.0
    start_month = f"{inception.year}-{inception.month:02d}"
    index[start_month] = 100.0
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


def compute_acwi_index(inception: date, end: date) -> dict:
    """MSCI ACWI index base 100 at inception (monthly)."""
    rets = fetch_yahoo_monthly("ACWI", inception - timedelta(days=40), end)
    index = {}
    val = 100.0
    start_month = f"{inception.year}-{inception.month:02d}"
    index[start_month] = 100.0
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    for month in months_list:
        if month == start_month:
            continue
        if month in rets:
            val *= (1 + rets[month])
            index[month] = round(val, 4)
    return {
        "monthly_returns": rets,
        "index": index,
    }


def period_return(index_map: dict, from_key: str, to_key: str):
    if from_key in index_map and to_key in index_map:
        return round((index_map[to_key] / index_map[from_key] - 1) * 100, 2)
    return None


def compute_stats(sleeve_idx: dict, acwi_idx: dict) -> dict:
    """Multi-period returns + alpha."""
    months = sorted(sleeve_idx.keys())
    if not months:
        return {}
    latest = months[-1]

    # Reference keys
    def months_back(n):
        target_idx = len(months) - 1 - n
        if target_idx < 0:
            return None
        return months[target_idx]

    ytd_key = f"{int(latest[:4])-1}-12"  # Dec of prev year
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
            result["returns"][name] = {"sleeve": None, "acwi": None, "alpha": None}
            continue
        s = period_return(sleeve_idx, from_m, latest)
        a = period_return(acwi_idx, from_m, latest)
        alpha = round(s - a, 2) if s is not None and a is not None else None
        result["returns"][name] = {"sleeve": s, "acwi": a, "alpha": alpha}

    # Annualized SI
    n_months = len(months) - 1
    if n_months > 0:
        si_sleeve = sleeve_idx[latest] / 100
        si_acwi = acwi_idx.get(latest, 100) / 100
        result["annualized"] = {
            "sleeve": round((si_sleeve ** (12 / n_months) - 1) * 100, 2),
            "acwi":   round((si_acwi ** (12 / n_months) - 1) * 100, 2) if si_acwi else None,
        }
        result["annualized"]["alpha"] = round(
            result["annualized"]["sleeve"] - (result["annualized"]["acwi"] or 0), 2
        )

    return result


def compute_holding_contributions(sleeve_data, inception: date, end: date) -> list:
    """For each holding: compute SI return, YTD return, weight, contribution to sleeve."""
    total_equity = sum(h[3] for h in EQUITY_HOLDINGS)
    start_month = f"{inception.year}-{inception.month:02d}"
    # Last available month in data
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    latest = months_list[-1]

    # YTD cutoff: first month of current year. YTD compounds from Jan {current_year} onward
    ytd_year = end.year
    ytd_months = [m for m in months_list if int(m[:4]) == ytd_year]

    holdings_perf = []
    for isin, ticker, name, value, _ in EQUITY_HOLDINGS:
        rets = sleeve_data["holding_returns"][isin]

        # SI return (from start_month+1 to latest)
        cum_si = 1.0
        counted_si = 0
        for m in months_list:
            if m == start_month:
                continue
            if m in rets:
                cum_si *= (1 + rets[m])
                counted_si += 1
        si_return = round((cum_si - 1) * 100, 2) if counted_si > 0 else None

        # YTD return (compound returns for current year months only)
        cum_ytd = 1.0
        counted_ytd = 0
        for m in ytd_months:
            if m in rets:
                cum_ytd *= (1 + rets[m])
                counted_ytd += 1
        ytd_return = round((cum_ytd - 1) * 100, 2) if counted_ytd > 0 else None

        weight = round(value / total_equity * 100, 2)
        contribution = round(si_return * weight / 100, 2) if si_return is not None else None
        ytd_contribution = round(ytd_return * weight / 100, 2) if ytd_return is not None else None

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
            "source": sleeve_data["holding_sources"][isin],
            "months_counted": counted_si,
            "ytd_months_counted": counted_ytd,
        })
    return holdings_perf


def main():
    today = date.today()
    print(f"[{datetime.now()}] Building BIG Equity Sleeve vs MSCI ACWI")
    print(f"  Period: {BIG_INCEPTION} to {today}")
    print()

    print("Building sleeve index from:")
    sleeve = compute_sleeve_index(BIG_INCEPTION, today)

    print("\nFetching ACWI benchmark...")
    acwi = compute_acwi_index(BIG_INCEPTION, today)

    stats = compute_stats(sleeve["index"], acwi["index"])
    contributions = compute_holding_contributions(sleeve, BIG_INCEPTION, today)

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "inception": BIG_INCEPTION.isoformat(),
        "benchmark": "MSCI ACWI (via ACWI ETF - Yahoo)",
        "stats": stats,
        "sleeve_index": sleeve["index"],
        "acwi_index": acwi["index"],
        "sleeve_monthly_returns": sleeve["monthly_returns"],
        "acwi_monthly_returns": acwi["monthly_returns"],
        "holdings": contributions,
    }

    out_path = ROOT / "data" / "equity_race.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 60)
    print("EQUITY SLEEVE vs MSCI ACWI")
    print("=" * 60)
    if stats.get("returns"):
        for period, vals in stats["returns"].items():
            s = vals["sleeve"]
            a = vals["acwi"]
            alpha = vals["alpha"]
            s_str = f"{s:+.2f}%" if s is not None else "   —"
            a_str = f"{a:+.2f}%" if a is not None else "   —"
            alpha_str = f"{alpha:+.2f}pp" if alpha is not None else "   —"
            print(f"  {period:5s} | Sleeve: {s_str:>10s} | ACWI: {a_str:>10s} | Alpha: {alpha_str}")
    if stats.get("annualized"):
        ann = stats["annualized"]
        print(f"\n  Ann.  | Sleeve: {ann['sleeve']:+.2f}% | ACWI: {ann['acwi']:+.2f}% | Alpha: {ann['alpha']:+.2f}pp")

    print("\n" + "=" * 60)
    print("HOLDING CONTRIBUTIONS")
    print("=" * 60)
    for h in sorted(contributions, key=lambda x: -(x.get("contribution_pct") or -999)):
        sc = h["si_return_pct"]
        c = h["contribution_pct"]
        sc_s = f"{sc:+.2f}%" if sc is not None else "   —"
        c_s = f"{c:+.2f}pp" if c is not None else "   —"
        print(f"  {h['ticker']:7s} | wt {h['weight_pct']:5.1f}% | SI ret {sc_s:>10s} | contrib {c_s:>10s}")

    print(f"\nSaved to: {out_path}")


if __name__ == "__main__":
    main()
