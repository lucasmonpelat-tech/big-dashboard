"""
refresh_holdings_returns_daily.py
==================================
Refresh diario T-1 de holdings_returns_{equity,fixed_income,alternatives}.json.

Funciona en TANDEM con compute_holdings_returns.py (que corre solo cuando hay
nuevo Pershing dump). Este script SOLO actualiza precios y returns; NO toca:
  - qty
  - cost_basis_usd
  - buys_history
  - holdings CLOSED (esos se setean del RGL Pershing y no cambian)

Lo que ACTUALIZA:
  - mv_usd        = qty * precio_T-1
  - return_pct    = (mv_usd - cost_basis) / cost_basis * 100
  - bench_dw_pct  = recalculado con ACWI/AGG T-1 actuales
  - alpha_real_pp = return_pct - bench_dw_pct

Inputs:
  data/holdings_returns_*.json (estructura ya inicializada por compute_holdings_returns)
  data/live_prices.json        (precios ETF/funds T-1)
  data/ucits_daily_nav.json    (NAVs baha de UCITS)
  yfinance ACWI + AGG history

Run from cron diariamente despues de price_refresher + ucits scraper.

Usage:
    python scripts/refresh_holdings_returns_daily.py
"""

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _is_valid(v):
    if v is None:
        return False
    try:
        x = float(v)
        return not (math.isnan(x) or math.isinf(x)) and x > 0
    except (TypeError, ValueError):
        return False


def load_daily_prices():
    """Carga precios T-1: UCITS via baha + ETF via live_prices.json.

    Mapping ticker en holdings_returns_*.json -> precio.
    """
    px = {}

    # UCITS NAVs (baha)
    try:
        ud = json.load(open(ROOT / "data" / "ucits_daily_nav.json", encoding="utf-8"))
        for rec in ud.get("navs", {}).values():
            ticker = rec.get("ticker")
            nav = rec.get("nav")
            if ticker and _is_valid(nav):
                px[ticker] = nav
    except Exception as e:
        print(f"  WARN: ucits_daily_nav skipped: {e}")

    # ETFs via live_prices (yfinance/Stooq)
    try:
        lp = json.load(open(ROOT / "data" / "live_prices.json", encoding="utf-8"))
        prices = lp.get("prices", lp)
        for tk, rec in prices.items():
            if isinstance(rec, dict) and _is_valid(rec.get("price")):
                # baha gana sobre live_prices (caso 4BRZ)
                px.setdefault(tk, rec["price"])
    except Exception as e:
        print(f"  WARN: live_prices skipped: {e}")

    return px


def fetch_bench_close(ticker):
    """Cierre T-1 de un benchmark via yfinance."""
    try:
        import yfinance as yf
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=14)
        h = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
        if h is None or h.empty:
            return None
        # Buscar el ultimo close valido (skip NaN)
        for i in range(len(h) - 1, -1, -1):
            close = h.iloc[i].get("Close")
            if _is_valid(close):
                return float(close)
        return None
    except Exception as e:
        print(f"  ERR fetching {ticker}: {e}")
        return None


def fetch_bench_history(ticker, start_iso):
    """Trae history de un bench desde start_iso hasta hoy. Returns dict {date: close}."""
    try:
        import yfinance as yf
        from datetime import date, timedelta
        end = date.today() + timedelta(days=1)
        h = yf.Ticker(ticker).history(start=start_iso, end=end.isoformat())
        out = {}
        for ts, row in h.iterrows():
            close = row.get("Close")
            if _is_valid(close):
                out[ts.strftime("%Y-%m-%d")] = float(close)
        return out
    except Exception as e:
        print(f"  ERR history {ticker}: {e}")
        return {}


def load_ytd_per_holding():
    """Lee YTD por ticker de los archivos existentes (equity_race, fi_race, alts_race)."""
    ytd = {}
    for fname in ['equity_race.json', 'fi_race.json', 'alts_race.json']:
        try:
            d = json.load(open(ROOT / 'data' / fname, encoding='utf-8'))
            for h in d.get('holdings', []):
                tk = h.get('ticker')
                v = h.get('ytd_return_pct')
                if tk and v is not None:
                    ytd[tk] = v
        except Exception:
            pass
    return ytd


def fetch_bench_ytd_spot(ticker, ytd_anchor='2025-12-31'):
    """YTD spot del bench usando yfinance."""
    try:
        import yfinance as yf
        import pandas as pd
        from datetime import date as _date, timedelta as _td
        t = yf.Ticker(ticker)
        end = _date.today()
        h = t.history(start='2025-12-28', end=(end + _td(days=2)).isoformat(), auto_adjust=True)
        if h is None or h.empty:
            return None
        try:
            h.index = h.index.tz_localize(None)
        except Exception:
            pass
        anchor_idx = h.index.get_indexer([pd.Timestamp(ytd_anchor)], method='nearest')[0]
        anchor = h.iloc[anchor_idx]['Close']
        last = h.iloc[-1]['Close']
        if not _is_valid(anchor) or not _is_valid(last):
            return None
        return (last / anchor - 1) * 100
    except Exception as e:
        print(f"  ERR fetching {ticker} YTD: {e}")
        return None


def get_bench_price_on_or_before(bench_hist, target_date_iso):
    """Encuentra el precio del bench en target_date o el dia anterior mas cercano."""
    if target_date_iso in bench_hist:
        return bench_hist[target_date_iso]
    dates = sorted(bench_hist.keys())
    prev = None
    for d in dates:
        if d <= target_date_iso:
            prev = d
        else:
            break
    return bench_hist.get(prev) if prev else None


def compute_bench_dw_from_buys(buys_history, bench_hist, today_iso):
    """Recalcula bench Dollar-Weighted usando buys_history cachedo en el JSON."""
    bench_now = get_bench_price_on_or_before(bench_hist, today_iso)
    if not bench_now:
        return None

    total_cost = 0
    total_value_now = 0
    for buy in buys_history:
        bench_then = get_bench_price_on_or_before(bench_hist, buy['date'])
        if not bench_then or bench_then <= 0:
            continue
        cost = buy['cost']
        if cost <= 0:
            continue
        value_now = cost * (bench_now / bench_then)
        total_cost += cost
        total_value_now += value_now

    if total_cost <= 0:
        return None
    return (total_value_now / total_cost - 1) * 100


def main():
    today = date.today()
    today_iso = today.isoformat()
    print(f"[{datetime.now().isoformat()}] Refresh holdings returns daily ({today_iso})")

    # 1. Load fresh prices
    daily_px = load_daily_prices()
    print(f"  Daily prices: {len(daily_px)} tickers")

    # 2. Find earliest buy date across all holdings to fetch bench history
    earliest_buy = None
    for sleeve in ['equity', 'fixed_income', 'alternatives']:
        path = ROOT / "data" / f"holdings_returns_{sleeve}.json"
        if not path.exists():
            continue
        d = json.load(open(path, encoding='utf-8'))
        for h in d.get('holdings', []):
            for b in h.get('buys_history', []):
                if earliest_buy is None or b['date'] < earliest_buy:
                    earliest_buy = b['date']
    if not earliest_buy:
        earliest_buy = (today - timedelta(days=400)).isoformat()
    print(f"  Earliest buy date: {earliest_buy}")

    # 3. Fetch bench history (ACWI + AGG) y YTD spot
    print(f"  Fetching ACWI + AGG history since {earliest_buy}...")
    acwi_hist = fetch_bench_history('ACWI', earliest_buy)
    agg_hist  = fetch_bench_history('IUAG.L',  earliest_buy)  # iShares Core US Aggregate UCITS USD Acc
    print(f"    ACWI: {len(acwi_hist)} pts, AGG: {len(agg_hist)} pts")

    # Bench YTD spot (un numero por sleeve)
    acwi_ytd_spot = fetch_bench_ytd_spot('ACWI')
    agg_ytd_spot  = fetch_bench_ytd_spot('IUAG.L')  # UCITS USD Acc — alineado con baha
    print(f"    ACWI YTD: {acwi_ytd_spot:+.2f}%" if acwi_ytd_spot is not None else "    ACWI YTD: N/A")
    print(f"    AGG YTD:  {agg_ytd_spot:+.2f}%" if agg_ytd_spot is not None else "    AGG YTD: N/A")

    # YTD per holding de archivos race
    ytd_per_holding = load_ytd_per_holding()
    print(f"    YTD per holding loaded: {len(ytd_per_holding)} tickers")

    # 4. Update each sleeve
    for sleeve_key in ['equity', 'fixed_income', 'alternatives']:
        path = ROOT / "data" / f"holdings_returns_{sleeve_key}.json"
        if not path.exists():
            print(f"  [{sleeve_key}] file no existe, skip")
            continue

        d = json.load(open(path, encoding='utf-8'))
        bench_hist = agg_hist if sleeve_key == 'fixed_income' else acwi_hist
        bench_label = 'AGG' if sleeve_key == 'fixed_income' else 'ACWI'

        updated = 0
        skipped = 0
        for h in d.get('holdings', []):
            if h.get('status') != 'OPEN':
                continue  # CLOSED son del RGL, no se tocan
            ticker = h['ticker']
            qty = h.get('qty', 0)
            cost = h.get('cost_basis_usd', 0)
            if not qty or not cost:
                skipped += 1
                continue

            # Update MV con precio T-1
            new_price = daily_px.get(ticker)
            if _is_valid(new_price):
                mv_new = qty * new_price
                h['mv_usd'] = round(mv_new, 2)
                h['return_pct'] = round((mv_new - cost) / cost * 100, 2)
                h['unrealized_gl_usd'] = round(mv_new - cost, 2)
                h['last_price_pershing'] = round(new_price, 4)
            # Si no hay precio fresco, mantener el MV/return previos (no sobreescribir con basura)

            # Recalcular bench DW con bench actual
            buys = h.get('buys_history', [])
            if buys:
                bench_dw = compute_bench_dw_from_buys(buys, bench_hist, today_iso)
                if bench_dw is not None:
                    h['bench_dw_pct'] = round(bench_dw, 2)
                    h['alpha_real_pp'] = round(h['return_pct'] - bench_dw, 2)
                    h['bench_label'] = bench_label

            # Refresh YTD: del activo y bench
            h_ytd = ytd_per_holding.get(ticker)
            bench_ytd_spot = agg_ytd_spot if sleeve_key == 'fixed_income' else acwi_ytd_spot
            if h_ytd is not None:
                h['ytd_pct'] = round(h_ytd, 2)
            if bench_ytd_spot is not None:
                h['bench_ytd_pct'] = round(bench_ytd_spot, 2)
            if h_ytd is not None and bench_ytd_spot is not None:
                h['alpha_ytd_pp'] = round(h_ytd - bench_ytd_spot, 2)

            h['period_end'] = today_iso
            updated += 1

        d['refreshedAt'] = datetime.now().isoformat()
        d['period_end'] = today_iso
        d['_daily_refresh_note'] = f"Daily refresh {today_iso}: MV con precios T-1, bench DW recalculado. Cost basis y qty fijos del ultimo Pershing dump."

        path.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"  [{sleeve_key}] {updated} OPEN updated, {skipped} skipped")


if __name__ == '__main__':
    main()
