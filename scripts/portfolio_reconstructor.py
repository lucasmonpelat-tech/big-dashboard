"""
portfolio_reconstructor.py
==========================
Rebuilds the BIG Fund equity sleeve timeline from Pershing transaction history.

Reads Transactions_JXD101380 History.xlsx and:
  1. Parses all BUY/SELL trades (handles multiple line formats including BRK B, parValue bonds)
  2. Builds position-over-time (qty) for each security
  3. Classifies each security by sleeve (Equity / FI / Alts / Cash)
  4. Values positions month-end using:
     - ETFs with Yahoo ticker → daily price
     - UCITS → baha monthly returns + latest NAV anchor
     - Privates → interpolated from known values
  5. Sums equity sleeve MV monthly
  6. Outputs data/equity_sleeve_real.json

Usage:
    python scripts/portfolio_reconstructor.py "C:\\path\\to\\Transactions_JXD101380 History.xlsx"
"""

import openpyxl
import re
import json
import sys
from datetime import datetime, date, timedelta
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ==============================================================
# SECURITY CLASSIFICATION
# ==============================================================
# symbol / cusip → (sleeve, ticker_pretty, isin, yahoo_ticker_for_price)
SECURITY_MAP = {
    # EQUITY
    "CSPX:GB":   ("Equity", "CSPX",  "IE00B5BMR087", "SPY"),       # SPY as proxy for S&P500
    "BRK B":     ("Equity", "BRK.B", "US0846707026", "BRK-B"),     # Berkshire Class B
    "G6430T809": ("Equity", "NBGMT", "IE00BFMHRK20", None),        # NB Megatrends (UCITS)
    "L6366L196": ("Equity", "MFSCV", "LU1985812756", None),        # MFS Contrarian
    "L468AA656": ("Equity", "JHGSC", "LU2940405447", None),        # Janus Global Small Cos
    "G5S05E528": ("Equity", "LGLI",  "IE00BF4KN675", None),        # Lazard Infra
    "G5441Y310": ("Equity", "NBRE",  "LU1648392275", None),        # NB US Real Estate (closed Feb-2026)
    "G9373W177": ("Equity", "VIRTUS","LU2020382479", None),        # Virtus US Small Cap (closed Feb-2026)
    "G8T49N214": ("Equity", "THOR",  "IE00B6YCBF59", None),        # Thornburg
    "ILF":       ("Equity", "ILF",   "US4642873909", "ILF"),
    "4BRZ:DE":   ("Equity", "4BRZ",  "DE000A0Q4R85", "EWZ"),       # use EWZ as proxy
    "ARGT":      ("Equity", "ARGT",  "US37950E2596", "ARGT"),

    # ALTS
    "GLD":       ("Alternatives", "GLD",   "US78463V1070", "GLD"),
    "IBIT":      ("Alternatives", "IBIT",  "US46438F1012", "IBIT"),
    "L6712R194": ("Alternatives", "NBPEA", "LU2659193242", None),  # NB PE Access (closed Apr-21)
    "L4R58Q111": ("Alternatives", "FLEX",  "LU2XXX",       None),  # Franklin Lex PE (new)
    "L4680C117": ("Alternatives", "HLGPIF","LU2XXX",       None),  # Hamilton Lane Infra (new)
    "449LP0055": ("Alternatives", "HLEND", "KYG4737U1085", None),  # HPS Corporate Lending
    "379LP0083": ("Alternatives", "GCRED", "GCRED-I",      None),  # Golub Capital

    # FIXED INCOME
    "G7113P361": ("Fixed Income", "PIMCO-INC", "IE00B87KCF77", None),
    "G7S11T150": ("Fixed Income", "PIMCO-LD",  "IE00BDT57R20", None),
    "G7097Y503": ("Fixed Income", "PIMCO-EM",  "IE00B29K0P99", None),
    "G5896H580": ("Fixed Income", "MANIG",     "IE000OE87WX6", None),
    "L8147L735": ("Fixed Income", "SGCB",      "LU2049315265", None),
    "L9690L577": ("Fixed Income", "WELL",      "LU-WELL",      None),  # Wellington Credit (closed)
    "G7151GAA7": ("Fixed Income", "BPCC",      "XS2658535526", None),  # Barings (parValue)
    "G5478EAA2": ("Fixed Income", "TGF",       "XS2324777171", None),  # Tenac (parValue)

    # CASH / MMF
    "L4060F300": ("Cash", "FMM1", "LU-FMM1", None),
    "L4058R662": ("Cash", "FMM2", "LU-FMM2", None),
}


def parse_transactions(xlsx_path: Path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    # Find header row
    hdr = None
    for i, row in enumerate(ws.iter_rows(values_only=True), 1):
        if row[0] == "Process Date":
            hdr = i
            break
    if hdr is None:
        raise ValueError("Header row not found")

    trades = []
    # Regex patterns to cover all formats in Pershing:
    # Buy 14410.58400 share(s) of G8T49N214 at 42.3300
    # Sell -2572.00000 share(s) of BRK B at 472.4350      (has space in symbol)
    # Buy 280.00000 of CSPX:GB at 707.5200                (no "share(s)")
    # Buy 40588.00000 parValue of G7151GAA7 at 123.1900  (parValue for bonds)
    # Correct Sell -178660.05000 share(s) of G7113P361 at 20.1500
    # Cancel Sell 225102.06400 share(s) of G7113P361 at 20.1500
    patterns = [
        re.compile(r"^(Buy|Sell|Correct Buy|Correct Sell)\s+(-?[\d.]+)\s+(?:share\(s\)|parValue)\s+of\s+([A-Z0-9: .]+?)\s+at\s+([\d.]+)$"),
        re.compile(r"^(Buy|Sell|Correct Buy|Correct Sell)\s+(-?[\d.]+)\s+of\s+([A-Z0-9: .]+?)\s+at\s+([\d.]+)$"),
    ]
    cancels = re.compile(r"^Cancel\s+(Buy|Sell)\s+(-?[\d.]+)\s+.*?of\s+([A-Z0-9: .]+?)\s+at\s+([\d.]+)$")

    for row in ws.iter_rows(min_row=hdr + 1, values_only=True):
        date_cell, typ, desc, net_base, *_ = row
        if not date_cell or not typ:
            continue
        typ_s = str(typ).strip()

        # Skip non-trade rows (fees, dividends, etc.)
        is_trade = any(k in typ_s for k in ["Buy", "Sell"])
        if not is_trade:
            continue

        # Skip cancels (they'd double-count a non-executed trade)
        if typ_s.startswith("Cancel"):
            continue

        action = None
        qty = None
        sym = None
        price = None
        for pat in patterns:
            m = pat.match(typ_s)
            if m:
                action, qty, sym, price = m.groups()
                break
        if not action:
            continue

        trade_date = date_cell if isinstance(date_cell, datetime) else None
        if not trade_date:
            continue

        side = "SELL" if "Sell" in action else "BUY"
        qty_val = abs(float(qty))
        # Correct Sell/Buy are adjustments — treat as normal trade direction
        # But they might cancel previous trades; for simplicity treat as independent

        trades.append({
            "date": trade_date.date(),
            "side": side,
            "sym": sym.strip(),
            "qty": qty_val,
            "price": float(price),
            "net_usd": float(net_base) if net_base else 0,
            "desc": (desc or "")[:50],
            "raw_type": typ_s,
        })

    return trades


def build_positions_over_time(trades):
    """Build {sym: [{date, qty_after, avg_cost}]} timeline."""
    # Group by sym, sort by date
    by_sym = defaultdict(list)
    for t in trades:
        by_sym[t["sym"]].append(t)

    timelines = {}
    for sym, ts in by_sym.items():
        ts_sorted = sorted(ts, key=lambda x: x["date"])
        qty = 0.0
        cost_basis = 0.0
        timeline = []
        for t in ts_sorted:
            if t["side"] == "BUY":
                qty += t["qty"]
                cost_basis += t["qty"] * t["price"]
            else:  # SELL
                if qty > 0:
                    cost_basis *= max(1 - t["qty"] / qty, 0)  # proportional cost reduction
                qty -= t["qty"]
            avg_cost = cost_basis / qty if qty > 0 else None
            timeline.append({
                "date": t["date"],
                "qty_after": qty,
                "avg_cost": avg_cost,
                "trade_price": t["price"],
            })
        timelines[sym] = timeline
    return timelines


def month_end_dates(start: date, end: date):
    """Yield month-end dates between start and end (inclusive)."""
    y, m = start.year, start.month
    while True:
        # Last day of month
        if m == 12:
            next_y, next_m = y + 1, 1
        else:
            next_y, next_m = y, m + 1
        last_day = date(next_y, next_m, 1) - timedelta(days=1)
        if last_day > end:
            break
        if last_day >= start:
            yield last_day
        y, m = next_y, next_m


def qty_at_date(timeline, target: date):
    """Return qty held at end of target date."""
    qty = 0.0
    for t in timeline:
        if t["date"] <= target:
            qty = t["qty_after"]
        else:
            break
    return qty


def fetch_yahoo_daily(ticker: str, start: date, end: date):
    """Return {date_iso: close} via yfinance."""
    import yfinance as yf
    h = yf.Ticker(ticker).history(start=start.isoformat(), end=(end + timedelta(days=3)).isoformat())
    return {ts.strftime("%Y-%m-%d"): float(row["Close"]) for ts, row in h.iterrows()}


def load_baha_monthly_returns(isin: str):
    """Return {YYYY-MM: decimal return}."""
    fp = ROOT / "data" / "baha" / f"{isin}.json"
    if not fp.exists():
        return {}
    spanish_months = {'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}
    with open(fp) as f:
        data = json.load(f)
    rets = {}
    for year_str, months_map in data["monthlyReturns"].items():
        for m_name, pct in months_map.items():
            if m_name in spanish_months:
                rets[f"{year_str}-{spanish_months[m_name]:02d}"] = float(pct) / 100
    return rets


def build_ucits_nav_series(isin: str, anchor_nav: float, anchor_month: str):
    """Given a UCITS anchor NAV at month X, derive NAV at all other months
    using monthly returns (backward and forward)."""
    rets = load_baha_monthly_returns(isin)
    if not rets:
        return {}
    all_months = sorted(set(list(rets.keys()) + [anchor_month]))
    nav_by_month = {anchor_month: anchor_nav}
    # Forward from anchor
    cur = anchor_nav
    for m in [x for x in all_months if x > anchor_month]:
        if m in rets:
            cur *= (1 + rets[m])
            nav_by_month[m] = cur
    # Backward from anchor (inverse compounding)
    cur = anchor_nav
    for m in reversed([x for x in all_months if x < anchor_month]):
        next_m_month = m[:7]
        # rets[X] represents return DURING X; so nav at end of X-1 = nav_X / (1 + ret_X)
        # Walking backward, find return for month AFTER this one
        next_idx = all_months.index(m) + 1
        if next_idx < len(all_months):
            next_m = all_months[next_idx]
            if next_m in rets:
                cur = cur / (1 + rets[next_m])
                nav_by_month[m] = cur
    return nav_by_month


# Known current NAVs (as of April 2026) for UCITS (from Pershing positions export and baha)
# Used as anchor for NAV series reconstruction
UCITS_ANCHOR_NAV = {
    # isin → (nav, month anchor "YYYY-MM")
    "IE00BFMHRK20": (23.88, "2026-04"),   # NB Megatrends
    "LU1985812756": (290.16, "2026-04"),  # MFS Contrarian
    "LU2940405447": (54.47, "2026-04"),   # Janus Global Small Cos
    "IE00BF4KN675": (20.2315, "2026-04"), # Lazard Infra
    "IE00B6YCBF59": (42.33, "2026-04"),   # Thornburg
    # Non-equity sleeves (for completeness)
    "IE00B87KCF77": (20.22, "2026-04"),
    "IE00BDT57R20": (13.95, "2026-04"),
    "IE000OE87WX6": (124.31, "2026-04"),
    "IE00B29K0P99": (18.40, "2026-04"),
    "XS2324777171": (157.816, "2026-04"),
    "LU2049315265": (2111.85, "2026-04"),
    # Closed / illiquid positions (sale price as anchor)
    "LU1648392275": (27.88, "2026-02"),   # NB US RE sold at 27.88 in Feb
    "LU2020382479": (34.04, "2026-02"),   # Virtus US SC sold at 34.04 in Feb
    "LU2659193242": (12.2061, "2026-04"), # NB Global PE sold at 12.2061
}


def main():
    if len(sys.argv) > 1:
        xlsx = Path(sys.argv[1])
    else:
        xlsx = Path("C:/Users/lmonp/Downloads/Transactions_JXD101380 History.xlsx")
    print(f"[{datetime.now()}] Parsing: {xlsx.name}")

    trades = parse_transactions(xlsx)
    print(f"  Parsed {len(trades)} trades")

    # Check unique securities
    all_syms = set(t["sym"] for t in trades)
    print(f"  Unique securities: {len(all_syms)}")
    unknown = [s for s in all_syms if s not in SECURITY_MAP]
    if unknown:
        print(f"  WARNING — unknown securities: {unknown}")

    # Group trades by sleeve
    trades_by_sleeve = defaultdict(list)
    for t in trades:
        meta = SECURITY_MAP.get(t["sym"])
        if not meta:
            continue
        t["sleeve"] = meta[0]
        t["ticker"] = meta[1]
        t["isin"] = meta[2]
        t["yahoo"] = meta[3]
        trades_by_sleeve[meta[0]].append(t)
    for sl in ["Equity", "Alternatives", "Fixed Income", "Cash"]:
        print(f"  {sl}: {len(trades_by_sleeve[sl])} trades")

    # Build position timelines
    timelines = build_positions_over_time(trades)

    # Build month-end valuation for equity only
    first_date = min(t["date"] for t in trades)
    last_date = max(t["date"] for t in trades)
    print(f"\n  Period: {first_date} to {last_date}")

    # Pre-fetch Yahoo prices for equity ETFs
    yahoo_cache = {}
    for sym, meta in SECURITY_MAP.items():
        sleeve, ticker, isin, yf_ticker = meta
        if sleeve != "Equity" or not yf_ticker:
            continue
        print(f"  Fetching {yf_ticker} (for {ticker})...")
        yahoo_cache[sym] = fetch_yahoo_daily(yf_ticker, first_date - timedelta(days=10), last_date + timedelta(days=5))

    # Build UCITS NAV series (equity only)
    ucits_nav_cache = {}
    for sym, meta in SECURITY_MAP.items():
        sleeve, ticker, isin, yf_ticker = meta
        if sleeve != "Equity" or yf_ticker:
            continue
        if isin in UCITS_ANCHOR_NAV:
            nav, anchor_m = UCITS_ANCHOR_NAV[isin]
            ucits_nav_cache[sym] = build_ucits_nav_series(isin, nav, anchor_m)
            print(f"  UCITS NAV series for {ticker}: {len(ucits_nav_cache[sym])} months")

    # Compute month-end equity sleeve MV
    # Include month-ends PLUS today's date (to reflect latest data)
    month_ends = list(month_end_dates(first_date, last_date))
    today_date = date.today()
    # If today is after last month_end, add today as final data point (partial month)
    if month_ends and today_date > month_ends[-1]:
        month_ends.append(today_date)
    sleeve_series = []

    for me_date in month_ends:
        total_mv = 0.0
        holdings_at_date = []
        for sym, meta in SECURITY_MAP.items():
            sleeve, ticker, isin, yf_ticker = meta
            if sleeve != "Equity":
                continue
            if sym not in timelines:
                continue
            qty = qty_at_date(timelines[sym], me_date)
            if qty <= 0.0001:
                continue
            # Get price at me_date
            price = None
            if yf_ticker and sym in yahoo_cache:
                yc = yahoo_cache[sym]
                # Find latest price on or before me_date
                for d_offset in range(0, 10):
                    check_d = me_date - timedelta(days=d_offset)
                    key = check_d.isoformat()
                    if key in yc:
                        price = yc[key]
                        break
            elif sym in ucits_nav_cache:
                month_key = f"{me_date.year}-{me_date.month:02d}"
                price = ucits_nav_cache[sym].get(month_key)
            if price is None:
                # Fallback: use last known trade price
                for t in reversed(timelines[sym]):
                    if t["date"] <= me_date:
                        price = t["trade_price"]
                        break
            if price is None:
                continue
            mv = qty * price
            total_mv += mv
            holdings_at_date.append({
                "ticker": ticker,
                "qty": qty,
                "price": price,
                "mv": mv,
            })
        sleeve_series.append({
            "date": me_date.isoformat(),
            "mv_usd": total_mv,
            "holdings": holdings_at_date,
        })

    # Print summary table
    print("\n" + "=" * 90)
    print(f"{'Date':12s} | {'Total Equity MV':>18s} | {'Holdings':>10s} | Composition")
    print("=" * 90)
    for pt in sleeve_series:
        comp = ", ".join(f"{h['ticker']}:${h['mv']/1000:.0f}K" for h in sorted(pt["holdings"], key=lambda x: -x["mv"])[:6])
        print(f"{pt['date']:12s} | ${pt['mv_usd']:>16,.0f} | {len(pt['holdings']):>10d} | {comp}")

    # ================================================================
    # Compute TWR (Time-Weighted Return) — flow-adjusted monthly returns
    # For each month:
    #   TWR_m = (MV_end - Net_Flows_In_during_m) / MV_start
    # Net_Flows_In: positive when equity sleeve receives cash (new buys),
    #               negative when sleeve loses cash (sells going to other sleeves)
    # ================================================================
    # Compute monthly net flows for equity sleeve
    equity_flows_by_month = defaultdict(float)
    for t in trades:
        if t.get("sleeve") != "Equity":
            continue
        month_key = f"{t['date'].year}-{t['date'].month:02d}"
        # t["net_usd"]: negative for BUY (money spent), positive for SELL
        # Flow_In for equity sleeve = -net_usd (buy = +flow, sell = -flow)
        flow_in = -(t["net_usd"] or 0)
        equity_flows_by_month[month_key] += flow_in

    print("\n" + "=" * 90)
    print("EQUITY SLEEVE TWR CALCULATION")
    print("=" * 90)
    print(f"{'Date':12s} | {'MV End':>14s} | {'Flow In':>14s} | {'TWR %':>8s} | {'Cum Index':>10s}")
    cum_index = 100.0
    twr_series = []
    prev_mv = None
    for pt in sleeve_series:
        me_date = pt["date"]
        mv = pt["mv_usd"]
        month_key = me_date[:7]
        flow = equity_flows_by_month.get(month_key, 0)
        if prev_mv is not None and prev_mv > 0:
            twr = (mv - flow) / prev_mv - 1
        else:
            twr = 0
        cum_index *= (1 + twr)
        print(f"{me_date:12s} | ${mv:>12,.0f} | ${flow:>12,.0f} | {twr*100:>+7.2f}% | {cum_index:>10.2f}")
        twr_series.append({"date": me_date, "mv_usd": mv, "flow_in": flow, "twr": twr, "index": round(cum_index, 4)})
        prev_mv = mv

    # Fetch ACWI benchmark same period
    print("\n" + "=" * 90)
    print("FETCHING ACWI FOR COMPARISON")
    acwi_daily = fetch_yahoo_daily("ACWI", first_date - timedelta(days=5), last_date + timedelta(days=5))
    acwi_by_month = {}
    for me_date in month_ends:
        for d_offset in range(0, 10):
            check = (me_date - timedelta(days=d_offset)).isoformat()
            if check in acwi_daily:
                acwi_by_month[me_date.isoformat()] = acwi_daily[check]
                break

    # ACWI index base 100 aligned to first sleeve index date
    first_idx_date = twr_series[0]["date"]
    acwi_base = acwi_by_month.get(first_idx_date)
    acwi_index_series = []
    if acwi_base:
        for pt in twr_series:
            acwi_val = acwi_by_month.get(pt["date"])
            if acwi_val:
                acwi_index_series.append({
                    "date": pt["date"],
                    "price": acwi_val,
                    "index": round(acwi_val / acwi_base * 100, 4),
                })

    print("\n" + "=" * 90)
    print("SLEEVE vs ACWI (TWR-adjusted, flow-normalized)")
    print("=" * 90)
    print(f"{'Date':12s} | {'Sleeve':>10s} | {'ACWI':>10s} | {'Alpha':>10s}")
    for s_pt, a_pt in zip(twr_series, acwi_index_series):
        alpha = s_pt["index"] - a_pt["index"]
        print(f"{s_pt['date']:12s} | {s_pt['index']:>10.2f} | {a_pt['index']:>10.2f} | {alpha:>+10.2f}pp")

    if twr_series and acwi_index_series:
        final_sleeve = twr_series[-1]["index"]
        final_acwi = acwi_index_series[-1]["index"]
        print("\n" + "=" * 90)
        print(f"SI SLEEVE TWR:   {final_sleeve - 100:+.2f}%")
        print(f"SI ACWI:         {final_acwi - 100:+.2f}%")
        print(f"ALPHA SI:        {final_sleeve - final_acwi:+.2f}pp")
        status = "🏆 GANANDO" if final_sleeve > final_acwi else "🔴 PERDIENDO"
        print(f"STATUS:          {status}")

    out = {
        "refreshedAt": datetime.now().isoformat(),
        "source": "Reconstructed from Pershing Transactions export",
        "first_trade_date": first_date.isoformat(),
        "last_trade_date": last_date.isoformat(),
        "n_trades": len(trades),
        "unknown_securities": unknown,
        "sleeve_series_equity": sleeve_series,
        "twr_series": twr_series,
        "acwi_index_series": acwi_index_series,
        "equity_flows_by_month": dict(equity_flows_by_month),
        "timelines_summary": {
            sym: {
                "ticker": SECURITY_MAP[sym][1] if sym in SECURITY_MAP else "?",
                "sleeve": SECURITY_MAP[sym][0] if sym in SECURITY_MAP else "?",
                "last_qty": timelines[sym][-1]["qty_after"],
                "n_trades": len(timelines[sym]),
            } for sym in timelines
        },
    }

    out_path = ROOT / "data" / "equity_sleeve_real.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
