"""
alts_race.py
============
Construye el BIG Alternatives Sleeve index y lo compara contra:
  - HFRX Global Hedge Fund Index proxy (liquid alts benchmark)
  - 60/40 (60% ACWI + 40% AGG) — el benchmark "BIG should beat"

Sub-asset class composition de Alts (al 2026-05-05):
  - Private Equity:   CALP, NBPEA, FLEX
  - Private Credit:   HLEND, BPCC, GCRED
  - Liquid alts:      IBIT (Bitcoin), GLD (Gold)

Sources:
  - IBIT, GLD: Yahoo Finance (monthly close)
  - Privates: monthly return proxy basado en sub-asset class index:
      * PE  -> S&P Listed Private Equity Index (PSP ETF) proxy with PE smoothing
      * PC  -> Cliffwater Direct Lending CDLI proxy ~9.5%/yr carry
      (privates do not publish public monthly NAVs; we use carry/proxy)
  - 60/40 -> 0.6*ACWI + 0.4*AGG monthly returns blended

Output: data/alts_race.json
"""

import json
import math
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
BIG_INCEPTION = date(2025, 6, 30)

# ==============================================================
# Alternatives Sleeve holdings (al 2026-05-05 Pershing)
# ==============================================================
# (isin, ticker, name, value_usd, sub_class, source_type, assumed_annual_return_pct)
ALTS_HOLDINGS = [
    ("LU2837777825", "CALP",  "Carlyle AlpInvest Private Markets",         2722180, "private_equity", "pe_proxy",       12.0),
    ("US46438F1012", "IBIT",  "iShares Bitcoin Trust",                      744326, "crypto",         "yahoo_monthly",  None),
    # NBPEA REMOVIDO 2026-06-10: vendido total 2026-04-30, $862K proceeds.
    ("US78463V1070", "GLD",   "SPDR Gold Shares",                           748729, "commodity",      "yahoo_monthly",  None),
    ("KYG4737U1085", "HLEND", "HPS Corporate Lending Fund",                 753336, "private_credit", "pc_carry",        9.5),
    ("XS2658535526", "BPCC",  "Barings Private Credit Corporation",         595348, "private_credit", "pc_carry",        9.5),
    ("FLEX-LEX",      "FLEX",  "Flex-Lexington Partners Secondaries",        501806, "private_equity", "pe_proxy",       12.0),
    ("LU2847068389",  "HLGPI", "Hamilton Lane Global Private Infrastructure", 500000, "private_infra", "pe_proxy",       11.0),
    ("GCRED-I",       "GCRED", "Golub Capital Private Credit",               490583, "private_credit", "pc_carry",        9.5),
]


def fetch_yahoo_monthly(ticker, start, end):
    """Returns {YYYY-MM: monthly_return_decimal}."""
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


def pe_proxy_monthly_returns(months_list, annual_pct):
    """
    Private Equity proxy: PSP ETF (S&P Listed PE) when available, fallback to smoothed monthly.
    Smoothing: use 70% of PSP return + 30% carry (privates report smoothed NAVs vs listed).
    """
    try:
        psp = fetch_yahoo_monthly("PSP", BIG_INCEPTION - timedelta(days=60), date.today())
    except Exception:
        psp = {}

    monthly_carry = (1 + annual_pct / 100) ** (1 / 12) - 1
    out = {}
    for m in months_list:
        if m in psp:
            # Smoothed: 70% PSP, 30% carry (typical PE NAV smoothing factor)
            out[m] = 0.7 * psp[m] + 0.3 * monthly_carry
        else:
            out[m] = monthly_carry
    return out


def pc_carry_monthly_returns(months_list, annual_pct):
    """Private Credit: stable carry ~annual_pct/12 (BDCs report mostly income return)."""
    monthly = (1 + annual_pct / 100) ** (1 / 12) - 1
    return {m: monthly for m in months_list}


def month_range(start, end):
    y, m = start.year, start.month
    while True:
        yield f"{y}-{m:02d}"
        if y == end.year and m == end.month:
            break
        m += 1
        if m > 12:
            m = 1
            y += 1


def compute_sleeve_index(inception, end):
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    returns_by_holding = {}
    holding_sources = {}

    for isin, ticker, name, value, sub_class, src, ann_pct in ALTS_HOLDINGS:
        if src == "yahoo_monthly":
            rets = fetch_yahoo_monthly(ticker, inception - timedelta(days=60), end)
            source = f"yahoo:{ticker}"
        elif src == "pe_proxy":
            rets = pe_proxy_monthly_returns(months_list, ann_pct)
            source = f"PE proxy (PSP 70% + carry 30% @ {ann_pct}%)"
        elif src == "pc_carry":
            rets = pc_carry_monthly_returns(months_list, ann_pct)
            source = f"PC carry @ {ann_pct}%/yr"
        else:
            rets = {}
            source = "unknown"
        returns_by_holding[isin] = rets
        holding_sources[isin] = source
        print(f"  {ticker:8s} ({sub_class:16s}, {source[:40]}): {len(rets)} months")

    total_alts = sum(h[3] for h in ALTS_HOLDINGS)

    start_month = f"{inception.year}-{inception.month:02d}"
    sleeve_rets = {}
    for month in months_list:
        weighted = 0
        known_w = 0
        for isin, ticker, name, value, sub_class, src, ann_pct in ALTS_HOLDINGS:
            w = value / total_alts
            if month in returns_by_holding[isin]:
                weighted += w * returns_by_holding[isin][month]
                known_w += w
        sleeve_rets[month] = weighted / known_w if 0.5 < known_w < 1 else (weighted if known_w >= 1 else None)

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


def compute_benchmark_index(ticker_or_blend, inception, end, blend_def=None):
    """
    Builds an index Base 100 for a benchmark.
    If blend_def is provided: {ticker: weight} -> compute weighted monthly returns
    Else: fetch single ticker via Yahoo.
    """
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    start_month = f"{inception.year}-{inception.month:02d}"
    index = {start_month: 100.0}

    if blend_def:
        # blended monthly returns
        all_rets = {t: fetch_yahoo_monthly(t, inception - timedelta(days=60), end) for t in blend_def}
        val = 100.0
        for month in months_list:
            if month == start_month:
                continue
            r = 0
            ok = True
            for t, w in blend_def.items():
                if month not in all_rets[t]:
                    ok = False
                    break
                r += w * all_rets[t][month]
            if ok:
                val *= (1 + r)
                index[month] = round(val, 4)
        return {"index": index}
    else:
        rets = fetch_yahoo_monthly(ticker_or_blend, inception - timedelta(days=60), end)
        val = 100.0
        for month in months_list:
            if month == start_month:
                continue
            if month in rets:
                val *= (1 + rets[month])
                index[month] = round(val, 4)
        return {"index": index, "monthly_returns": rets}


def period_return(idx, fm, tm):
    if fm in idx and tm in idx:
        return round((idx[tm] / idx[fm] - 1) * 100, 2)
    return None


def compute_stats(sleeve_idx, bm_idx, bm_name="benchmark"):
    months = sorted(sleeve_idx.keys())
    if not months:
        return {}
    latest = months[-1]

    def months_back(n):
        idx = len(months) - 1 - n
        return months[idx] if idx >= 0 else None

    ytd_key = f"{int(latest[:4]) - 1}-12"
    if ytd_key not in sleeve_idx:
        ytd_key = months[0]

    periods = {
        "1M":  months_back(1),
        "3M":  months_back(3),
        "6M":  months_back(6),
        "YTD": ytd_key,
        "SI":  months[0],
    }

    result = {"latest_month": latest, "returns": {}}
    for p, fm in periods.items():
        if fm is None:
            result["returns"][p] = {"sleeve": None, bm_name: None, "alpha": None}
            continue
        s = period_return(sleeve_idx, fm, latest)
        b = period_return(bm_idx, fm, latest)
        alpha = round(s - b, 2) if s is not None and b is not None else None
        result["returns"][p] = {"sleeve": s, bm_name: b, "alpha": alpha}

    n_months = len(months) - 1
    if n_months > 0:
        si_s = sleeve_idx[latest] / 100
        si_b = bm_idx.get(latest, 100) / 100
        result["annualized"] = {
            "sleeve":  round((si_s ** (12 / n_months) - 1) * 100, 2),
            bm_name:   round((si_b ** (12 / n_months) - 1) * 100, 2) if si_b else None,
        }
        result["annualized"]["alpha"] = round(
            result["annualized"]["sleeve"] - (result["annualized"][bm_name] or 0), 2
        )
    return result


def compute_holding_contributions(sleeve_data, inception, end):
    total_alts = sum(h[3] for h in ALTS_HOLDINGS)
    start_month = f"{inception.year}-{inception.month:02d}"
    months_list = list(month_range(date(inception.year, inception.month, 1), end))
    ytd_year = end.year
    ytd_months = [m for m in months_list if int(m[:4]) == ytd_year]

    holdings_perf = []
    for isin, ticker, name, value, sub_class, src, ann_pct in ALTS_HOLDINGS:
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

        weight = round(value / total_alts * 100, 2)
        contribution = round(si_return * weight / 100, 2) if si_return is not None else None
        ytd_contribution = round(ytd_return * weight / 100, 2) if ytd_return is not None else None

        holdings_perf.append({
            "isin": isin,
            "ticker": ticker,
            "name": name,
            "sub_class": sub_class,
            "value_usd": value,
            "weight_pct": weight,
            "si_return_pct": si_return,
            "ytd_return_pct": ytd_return,
            "contribution_pct": contribution,
            "ytd_contribution_pct": ytd_contribution,
            "assumed_annual_pct": ann_pct,
            "source": sleeve_data["holding_sources"][isin],
        })
    return holdings_perf


def main():
    today = date.today()
    print(f"[{datetime.now()}] Building BIG Alts Sleeve vs HFRX & 60/40")
    print(f"  Period: {BIG_INCEPTION} to {today}")

    print("\nBuilding Alts sleeve index from:")
    sleeve = compute_sleeve_index(BIG_INCEPTION, today)

    print("\nFetching benchmarks:")
    print("  HFRX Global Hedge Fund (using HFRXGL or proxy via QAI ETF if available)...")
    # HFRX not publicly available — use IQ Hedge Multi-Strategy ETF (QAI) as the closest proxy
    try:
        hfrx = compute_benchmark_index("QAI", BIG_INCEPTION, today)
    except Exception as e:
        print(f"    QAI fetch failed: {e}, using empty fallback")
        hfrx = {"index": {f"{BIG_INCEPTION.year}-{BIG_INCEPTION.month:02d}": 100.0}}

    print("  60/40 blend (60% ACWI + 40% AGG)...")
    bmk6040 = compute_benchmark_index(None, BIG_INCEPTION, today, blend_def={"ACWI": 0.6, "AGG": 0.4})

    stats_vs_hfrx = compute_stats(sleeve["index"], hfrx["index"], bm_name="hfrx")
    stats_vs_6040 = compute_stats(sleeve["index"], bmk6040["index"], bm_name="bmk6040")
    contributions = compute_holding_contributions(sleeve, BIG_INCEPTION, today)

    total_alts = sum(h[3] for h in ALTS_HOLDINGS)
    # Sub-asset class breakdown
    sub_class_mv = {}
    for isin, ticker, name, value, sub_class, src, ann_pct in ALTS_HOLDINGS:
        sub_class_mv[sub_class] = sub_class_mv.get(sub_class, 0) + value
    sub_class_pct = {k: round(v / total_alts * 100, 2) for k, v in sub_class_mv.items()}

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "inception": BIG_INCEPTION.isoformat(),
        "benchmark_primary": "60/40 blend (60% ACWI + 40% AGG)",
        "benchmark_secondary": "HFRX Global HF proxy (QAI ETF)",
        "portfolio_metrics": {
            "total_alts_usd": total_alts,
            "sub_class_breakdown_pct": sub_class_pct,
            "n_holdings": len(ALTS_HOLDINGS),
        },
        "stats_vs_6040": stats_vs_6040,
        "stats_vs_hfrx": stats_vs_hfrx,
        "sleeve_index": sleeve["index"],
        "bmk6040_index": bmk6040["index"],
        "hfrx_index": hfrx["index"],
        "sleeve_monthly_returns": sleeve["monthly_returns"],
        "holdings": contributions,
    }

    out_path = ROOT / "data" / "alts_race.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print("\n" + "=" * 70)
    print("ALTS SLEEVE vs 60/40 (primary) and HFRX (secondary)")
    print("=" * 70)
    if stats_vs_6040.get("returns"):
        for p, v in stats_vs_6040["returns"].items():
            s = v["sleeve"]; b = v["bmk6040"]; al = v["alpha"]
            s_str = f"{s:+.2f}%" if s is not None else "   -"
            b_str = f"{b:+.2f}%" if b is not None else "   -"
            al_str = f"{al:+.2f}pp" if al is not None else "   -"
            print(f"  {p:5s} | Alts: {s_str:>10s} | 60/40: {b_str:>10s} | Alpha: {al_str}")

    print("\n" + "=" * 70)
    print("HOLDING CONTRIBUTIONS (Since Inception)")
    print("=" * 70)
    for h in sorted(contributions, key=lambda x: -(x.get("contribution_pct") or -999)):
        sc = h["si_return_pct"]; c = h["contribution_pct"]
        sc_s = f"{sc:+.2f}%" if sc is not None else "   -"
        c_s = f"{c:+.2f}pp" if c is not None else "   -"
        print(f"  {h['ticker']:8s} ({h['sub_class']:16s}) | wt {h['weight_pct']:5.1f}% | SI ret {sc_s:>10s} | contrib {c_s:>10s}")

    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
