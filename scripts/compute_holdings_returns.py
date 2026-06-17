"""
compute_holdings_returns.py
============================
Calcula returns por holding usando cost basis ponderado (matchea Pershing).

Methodology (2026-06-17, decided con Lucas):
- Cost basis y Market Value: del UGL Pershing (Current Total Cost + Market Value)
- Realized G/L para CLOSED: del RGL Pershing
- ACWI Dollar-Weighted (Equity) y AGG Dollar-Weighted (FI): calculado con
  transactions (cada buy ponderado por monto, return desde su fecha hasta hoy)
- Alpha REAL: Return % - ACWI/AGG DW

Outputs:
    data/holdings_returns_equity.json
    data/holdings_returns_fi.json
    data/holdings_returns_alts.json

Inputs:
    Pershing UGL xlsx (cost basis + MV de OPEN)
    Pershing RGL xlsx (Realized G/L de CLOSED)
    Pershing Transactions xlsx (timing de buys para ACWI DW)
    Yahoo Finance: ACWI + AGG historical

Usage:
    python scripts/compute_holdings_returns.py \
        --ugl "C:/path/UGL.xlsx" \
        --rgl "C:/path/RGL.xlsx" \
        --tx  "C:/path/Transactions.xlsx"
"""

import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent

# Mapping: Pershing identifier (Symbol o CUSIP) -> mi ticker
PERSHING_TO_MY = {
    # Equity
    'CSTNL':       ('CSPX',     'Equity'),
    'CSPX:GB':     ('CSPX',     'Equity'),
    'G6430T809':   ('NBGMT',    'Equity'),
    'L6366L196':   ('MFSCV',    'Equity'),
    'G8T49N214':   ('THOR',     'Equity'),
    'L468AA656':   ('JHGSC',    'Equity'),
    'G5S05E528':   ('LGLI',     'Equity'),
    'IDMBF':       ('4BRZ',     'Equity'),
    '4BRZ:DE':     ('4BRZ',     'Equity'),
    'ARGT':        ('ARGT',     'Equity'),
    'ILF':         ('ILF',      'Equity'),
    # Fixed Income
    'G7113P361':   ('PIMCO-INC', 'Fixed Income'),
    'G7S11T150':   ('PIMCO-LD',  'Fixed Income'),
    'G7097Y503':   ('PIMCO-EM',  'Fixed Income'),
    'G5896H580':   ('MANIG',     'Fixed Income'),
    'G594CD616':   ('MANEM',     'Fixed Income'),
    'G5478EAA2':   ('TGF',       'Fixed Income'),
    'L8147L735':   ('SGCB',      'Fixed Income'),
    # Alternatives
    'L4680C117':   ('HLGPI',    'Alternatives'),
    'L4R58Q111':   ('FLEX',     'Alternatives'),
    '449LP0055':   ('HLEND',    'Alternatives'),
    '379LP0083':   ('GCRED',    'Alternatives'),
    'G7151GAA7':   ('BPCC',     'Alternatives'),
    'GLD':         ('GLD',      'Alternatives'),
    'IBIT':        ('IBIT',     'Alternatives'),
    # Cash
    'USD999997':   ('CASH',     'Cash'),
    # Closed (no aparecen en positions actuales)
    'BRK B':       ('BRK.B',    'Equity'),
    'G5441Y310':   ('NBRE',     'Equity'),
    'G9373W177':   ('VIRTUS',   'Equity'),
    'L6712R194':   ('NBPEA',    'Alternatives'),
    'L9690L577':   ('WELLCRED', 'Fixed Income'),
    # Sweep cash (no se trackea, lo skipeamos)
    'L4060F300':   ('__SWEEP_FRX__', 'SKIP'),
    'L4058R662':   ('__SWEEP_FRX2__', 'SKIP'),
}


def _is_valid(v):
    if v is None:
        return False
    try:
        x = float(v)
        return not (math.isnan(x) or math.isinf(x))
    except (TypeError, ValueError):
        return False


def _identify_ticker(row):
    """Map a Pershing row to (my_ticker, sleeve). Try Symbol, then CUSIP."""
    for col in ['Symbol', 'SYMBOL', 'CUSIP', 'Cusip', 'Security Identifier']:
        if col in row.index and pd.notna(row[col]):
            key = str(row[col]).strip()
            if key in PERSHING_TO_MY:
                return PERSHING_TO_MY[key]
    return None, None


def load_ugl_open(ugl_path):
    """Lee UGL Pershing y agrega taxlots a holding level (rows con Trade Date == 'Multiple').

    Returns: dict {my_ticker: {qty, mv, cost, gl, gl_pct, sleeve}}
    """
    df = pd.read_excel(ugl_path, header=14)
    df = df.dropna(subset=['Security Identifier', 'Cusip'])

    # Tomar solo agregados por seguridad (Trade Date = 'Multiple') o single taxlots
    multi = df[df['Trade Date'].astype(str) == 'Multiple']
    multi_cusips = set(multi['Cusip'].unique())
    single = df[~df['Cusip'].isin(multi_cusips)]
    clean = pd.concat([multi, single])

    out = {}
    skipped = []
    for _, row in clean.iterrows():
        ticker, sleeve = _identify_ticker(row)
        if not ticker or sleeve == 'SKIP':
            skipped.append((row.get('Symbol') or row.get('Cusip'), row.get('Security Description', '?')))
            continue
        out[ticker] = {
            'qty':    float(row['Quantity']),
            'mv':     float(row['Market Value']),
            'cost':   float(row['Current Total Cost']),
            'gl':     float(row['Gain/Loss']),
            'gl_pct': float(row['Gain/Loss %']),
            'sleeve': sleeve,
            'last_price': float(row.get('Last Price', 0)) if pd.notna(row.get('Last Price')) else None,
            'desc': str(row.get('Security Description', ''))[:60],
        }
    return out, skipped


def load_rgl_closed(rgl_path):
    """Lee RGL Pershing y agrega lots cerrados a holding level.

    Returns: dict {my_ticker: {cost, proceeds, gl, gl_pct, sleeve, n_lots,
                               opening_date, closing_date}}
    """
    df = pd.read_excel(rgl_path, header=14)
    df = df.dropna(subset=['Security Identifier'])

    # Para CLOSED: tomar la fila agregada (Quantity Total - Opening = 0)
    # o el row "Multiple" que agrega todo
    # En el sample que vi, BRK B tiene Quantity y Total Quantity Opening/Closing
    out = {}
    for _, row in df.iterrows():
        ticker, sleeve = _identify_ticker(row)
        if not ticker or sleeve == 'SKIP':
            continue
        cost = float(row.get('Cost Basis', 0)) if pd.notna(row.get('Cost Basis')) else 0
        proceeds = float(row.get('Proceeds', 0)) if pd.notna(row.get('Proceeds')) else 0
        gl = float(row.get('Gain/Loss', 0)) if pd.notna(row.get('Gain/Loss')) else 0
        gl_pct = float(row.get('Gain/Loss %', 0)) if pd.notna(row.get('Gain/Loss %')) else 0
        if cost == 0:
            continue
        # Agregar si ya existe (multiples lots cerrados)
        if ticker in out:
            existing = out[ticker]
            existing['cost'] += cost
            existing['proceeds'] += proceeds
            existing['gl'] += gl
            existing['n_lots'] += 1
            # Recalcular gl_pct ponderado
            existing['gl_pct'] = existing['gl'] / existing['cost'] * 100 if existing['cost'] else 0
        else:
            out[ticker] = {
                'cost': cost,
                'proceeds': proceeds,
                'gl': gl,
                'gl_pct': gl_pct,
                'sleeve': sleeve,
                'n_lots': 1,
                'opening_date': str(row.get('Opening Date', '?'))[:10],
                'closing_date': str(row.get('Closing Date', '?'))[:10],
                'desc': str(row.get('Security Description', ''))[:60],
            }
    return out


def load_transactions(tx_path):
    """Lee transactions y agrupa por ticker.

    Returns: dict {my_ticker: list of {date, qty, price, cost (abs), side}}
    """
    tx = pd.read_excel(tx_path, header=10)
    tx_trades = tx[tx['Buy/Sell'].isin(['BUY', 'SELL'])].copy()

    out = {}
    for _, row in tx_trades.iterrows():
        ticker, sleeve = _identify_ticker(row)
        if not ticker or sleeve == 'SKIP':
            continue
        date_raw = row.get('Process Date') or row.get('Trade Date')
        if pd.isna(date_raw):
            continue
        try:
            d = pd.Timestamp(date_raw).date()
        except Exception:
            continue
        qty = abs(float(row['Quantity']))
        price = float(row['Price (Transaction Currency)']) if pd.notna(row['Price (Transaction Currency)']) else 0
        net = float(row['Net Amount (Base Currency)']) if pd.notna(row['Net Amount (Base Currency)']) else 0
        side = row['Buy/Sell']
        cost = abs(net) if side == 'BUY' else 0  # solo cost de buys para DW
        out.setdefault(ticker, []).append({
            'date': d.isoformat(),
            'qty': qty,
            'price': price,
            'cost': cost,
            'side': side,
            'net': net,
        })
    # Ordenar por fecha
    for tk, trades in out.items():
        trades.sort(key=lambda x: x['date'])
    return out


def fetch_bench_history(ticker, start_date, end_date):
    """Trae cierres T-1 de yfinance para el benchmark (ACWI o AGG).

    Returns: dict {date_iso: close_price}
    """
    import yfinance as yf
    t = yf.Ticker(ticker)
    h = t.history(start=start_date.isoformat(), end=(end_date + timedelta(days=2)).isoformat())
    out = {}
    for ts, row in h.iterrows():
        close = row.get('Close')
        if _is_valid(close) and close > 0:
            out[ts.strftime('%Y-%m-%d')] = float(close)
    return out


def get_bench_price_on_or_before(bench_hist, target_date_iso):
    """Encuentra el precio del bench en target_date_iso o el dia anterior mas cercano."""
    if target_date_iso in bench_hist:
        return bench_hist[target_date_iso]
    # Buscar el dia previo mas cercano
    dates = sorted(bench_hist.keys())
    target = target_date_iso
    prev = None
    for d in dates:
        if d <= target:
            prev = d
        else:
            break
    return bench_hist.get(prev) if prev else None


def compute_bench_dw(transactions_list, bench_hist, today_iso):
    """Calcula benchmark dollar-weighted return.

    Para cada BUY:
        - bench_then = precio del bench en la fecha del buy
        - bench_now  = precio del bench hoy
        - buy_value_now = buy_cost * (bench_now / bench_then)

    Bench DW return = (sum(buy_value_now) - sum(buy_cost)) / sum(buy_cost) * 100

    Solo considera BUYs (no SELLs) porque queremos saber el return del bench
    si TODA la plata hubiera entrado en el bench en las fechas reales.
    """
    bench_now = get_bench_price_on_or_before(bench_hist, today_iso)
    if not bench_now:
        return None

    total_cost = 0
    total_value_now = 0
    for tx in transactions_list:
        if tx['side'] != 'BUY':
            continue
        bench_then = get_bench_price_on_or_before(bench_hist, tx['date'])
        if not bench_then or bench_then <= 0:
            continue
        cost = tx['cost']
        if cost <= 0:
            continue
        value_now = cost * (bench_now / bench_then)
        total_cost += cost
        total_value_now += value_now

    if total_cost <= 0:
        return None
    return (total_value_now / total_cost - 1) * 100


def get_first_buy_date(transactions_list):
    buys = [t for t in transactions_list if t['side'] == 'BUY']
    if not buys:
        return None
    return buys[0]['date']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ugl', required=True)
    parser.add_argument('--rgl', required=True)
    parser.add_argument('--tx',  required=True)
    parser.add_argument('--today', default=None, help='YYYY-MM-DD (default: today)')
    args = parser.parse_args()

    today = date.fromisoformat(args.today) if args.today else date.today()
    today_iso = today.isoformat()

    print(f"[{datetime.now().isoformat()}] Computing holdings returns (cost basis methodology)")
    print(f"  Today: {today_iso}")

    # 1. Load UGL (OPEN holdings)
    open_data, skipped = load_ugl_open(args.ugl)
    print(f"\n  UGL: {len(open_data)} OPEN holdings cargados")
    if skipped:
        print(f"  Skipped: {[s[0] for s in skipped]}")

    # 2. Load RGL (CLOSED holdings)
    closed_data = load_rgl_closed(args.rgl)
    print(f"  RGL: {len(closed_data)} CLOSED holdings cargados")

    # 3. Load Transactions
    tx_by_ticker = load_transactions(args.tx)
    print(f"  TX: {len(tx_by_ticker)} tickers con transactions")

    # 4. Fetch ACWI and AGG history (1 year before earliest tx to cover all buys)
    all_dates = [d['date'] for trades in tx_by_ticker.values() for d in trades]
    if all_dates:
        earliest = min(all_dates)
        bench_start = date.fromisoformat(earliest) - timedelta(days=30)
    else:
        bench_start = today - timedelta(days=400)

    print(f"\n  Fetching benchmark history (since {bench_start})...")
    acwi_hist = fetch_bench_history('ACWI', bench_start, today)
    agg_hist  = fetch_bench_history('AGG',  bench_start, today)
    print(f"    ACWI: {len(acwi_hist)} pts")
    print(f"    AGG:  {len(agg_hist)} pts")

    # 5. Compute returns por holding
    by_sleeve = {'Equity': [], 'Fixed Income': [], 'Alternatives': [], 'Cash': []}

    # OPEN holdings
    for ticker, data in open_data.items():
        sleeve = data['sleeve']
        if sleeve == 'Cash':
            continue
        txs = tx_by_ticker.get(ticker, [])
        bench_hist = agg_hist if sleeve == 'Fixed Income' else acwi_hist
        bench_label = 'AGG' if sleeve == 'Fixed Income' else 'ACWI'
        bench_dw = compute_bench_dw(txs, bench_hist, today_iso) if txs else None
        first_buy = get_first_buy_date(txs)

        alpha_real = None
        if data['gl_pct'] is not None and bench_dw is not None:
            alpha_real = data['gl_pct'] - bench_dw

        row = {
            'ticker': ticker,
            'sleeve': sleeve,
            'status': 'OPEN',
            'name': data['desc'],
            'qty': data['qty'],
            'mv_usd': data['mv'],
            'cost_basis_usd': data['cost'],
            'unrealized_gl_usd': data['gl'],
            'return_pct': data['gl_pct'],
            'bench_label': bench_label,
            'bench_dw_pct': round(bench_dw, 2) if bench_dw is not None else None,
            'alpha_real_pp': round(alpha_real, 2) if alpha_real is not None else None,
            'first_buy_date': first_buy,
            'period_end': today_iso,
            'n_trades': len(txs),
        }
        by_sleeve[sleeve].append(row)

    # CLOSED holdings
    for ticker, data in closed_data.items():
        sleeve = data['sleeve']
        if sleeve == 'Cash':
            continue
        txs = tx_by_ticker.get(ticker, [])
        first_buy = get_first_buy_date(txs)
        # For closed: get last sell date
        sells = [t for t in txs if t['side'] == 'SELL']
        last_sell = sells[-1]['date'] if sells else data.get('closing_date', '?')

        row = {
            'ticker': ticker,
            'sleeve': sleeve,
            'status': 'CLOSED',
            'name': data['desc'],
            'cost_basis_usd': data['cost'],
            'proceeds_usd': data['proceeds'],
            'realized_gl_usd': data['gl'],
            'realized_gl_pct': round(data['gl_pct'], 2),
            'first_buy_date': first_buy or data.get('opening_date'),
            'last_sell_date': last_sell,
            'n_lots': data['n_lots'],
        }
        by_sleeve[sleeve].append(row)

    # 6. Output
    refreshed = datetime.now().isoformat()
    for sleeve, holdings in by_sleeve.items():
        if sleeve == 'Cash':
            continue
        out_path = ROOT / 'data' / f'holdings_returns_{sleeve.lower().replace(" ","_")}.json'
        # Sort: OPEN by mv desc, CLOSED at end by realized_gl_pct
        open_h = sorted([h for h in holdings if h['status'] == 'OPEN'], key=lambda x: -x.get('mv_usd', 0))
        closed_h = sorted([h for h in holdings if h['status'] == 'CLOSED'], key=lambda x: -x.get('realized_gl_pct', 0))
        out = {
            'refreshedAt': refreshed,
            'method': 'Cost basis ponderado (UGL Pershing) + Bench Dollar-Weighted (transactions). Alpha Real = Return - Bench DW.',
            'sleeve': sleeve,
            'period_end': today_iso,
            'n_open': len(open_h),
            'n_closed': len(closed_h),
            'holdings': open_h + closed_h,
        }
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"\n  [{sleeve}] {len(open_h)} OPEN + {len(closed_h)} CLOSED -> {out_path.name}")

    # Print summary
    print(f"\n{'='*100}")
    print("RESUMEN POR SLEEVE")
    print('=' * 100)
    for sleeve in ['Equity', 'Fixed Income', 'Alternatives']:
        holdings = by_sleeve[sleeve]
        if not holdings:
            continue
        print(f"\n--- {sleeve} ---")
        print(f"{'Ticker':<10} {'Status':<8} {'MV':>12} {'Return %':>10} {'Bench DW':>10} {'Alpha':>10}")
        for h in sorted(holdings, key=lambda x: (x['status'] != 'OPEN', -x.get('mv_usd', 0) if x['status']=='OPEN' else -x.get('realized_gl_pct', 0))):
            if h['status'] == 'OPEN':
                mv_s = f"${h['mv_usd']:,.0f}"
                ret = h.get('return_pct')
                bdw = h.get('bench_dw_pct')
                alpha = h.get('alpha_real_pp')
                ret_s = f"{ret:+.2f}%" if ret is not None else 'N/A'
                bdw_s = f"{bdw:+.2f}%" if bdw is not None else 'N/A'
                alpha_s = f"{alpha:+.2f}pp" if alpha is not None else 'N/A'
                print(f"{h['ticker']:<10} {'OPEN':<8} {mv_s:>12} {ret_s:>10} {bdw_s:>10} {alpha_s:>10}")
            else:
                rg = h.get('realized_gl_pct')
                rg_s = f"{rg:+.2f}%" if rg is not None else 'N/A'
                print(f"{h['ticker']:<10} {'CLOSED':<8} {'':>12} {rg_s:>10} (realized){'':>5}")


if __name__ == '__main__':
    main()
