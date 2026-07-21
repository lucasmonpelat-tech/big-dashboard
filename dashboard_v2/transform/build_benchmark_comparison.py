"""
Transform: 4 sources -> data/canonical/YYYY-MM-DD/benchmark_comparison.json

Combina 3 comparisons con TODO ya alineado y con stats calculados:
  1. Total BIG vs 60/40 (Lynk NAV vs AOR ETF)
  2. Equity sleeve vs ACWI (equity_sleeve_real.json)
  3. FI sleeve vs AGG (fi_sleeve_real.json)

Cada comparison provee:
  - series: list de {date, portfolio, benchmark, alpha_bp} alineadas + rebased a 100
  - returns: {1M, 3M, 6M, YTD, LTM, SI} para portfolio y benchmark + alpha_bp
  - stats: tracking_error, info_ratio, sharpe, beta, correlation

Data alignment strategy:
  - Intersect fechas entre portfolio y benchmark
  - Rebase ambos a 100 en la primera fecha común
  - Forward-fill missing values del benchmark (weekends/holidays donde port tiene y bench no)

Fuentes (leídas del dashboard viejo, se mantienen):
  - data/lynk_nav_series.json  (BIG total NAV desde Lynk)
  - data/bmk_6040.json         (AOR ETF proxy 60/40)
  - data/equity_sleeve_real.json  (equity TWR + ACWI pareado)
  - data/fi_sleeve_real.json      (FI TWR + AGG pareado)
"""
from __future__ import annotations
import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

from dashboard_v2.canonical.schemas import SCHEMA_VERSION
from dashboard_v2.transform._common import ROOT, utc_now_iso, relpath_from_root

DATA_DIR = ROOT / "data"
CANONICAL_DIR = DATA_DIR / "canonical"

# Trading days per year para annualización
TRADING_DAYS = 252


# ============================================================
# ALIGNMENT HELPERS
# ============================================================
def _series_to_date_map(series, value_key: str = "value") -> dict[str, float]:
    """Convierte lista de {date, X} a dict {date: X}."""
    out = {}
    for pt in series:
        d = pt.get("date")
        v = pt.get(value_key)
        if d and v is not None and not (isinstance(v, float) and math.isnan(v)):
            out[d] = float(v)
    return out


def _intersect_and_rebase(port_map: dict, bench_map: dict) -> tuple[list[str], list[float], list[float]]:
    """
    Alinea 2 series por fechas comunes, forward-fill si benchmark tiene gaps.
    Rebasa ambas a 100 en la primera fecha común.

    Retorna: (dates_ordenadas, port_rebased, bench_rebased).
    """
    port_dates = sorted(port_map.keys())
    if not port_dates:
        return [], [], []

    # Fechas del bench en orden
    bench_dates = sorted(bench_map.keys())
    bench_dates_set = set(bench_dates)

    # Forward-fill del bench: si port tiene fecha X pero bench no, usar el ultimo bench conocido
    aligned_dates = []
    port_vals = []
    bench_vals = []
    last_bench = None
    bench_idx = 0
    for d in port_dates:
        # Avanzar last_bench hasta el ultimo dia <= d
        while bench_idx < len(bench_dates) and bench_dates[bench_idx] <= d:
            last_bench = bench_map[bench_dates[bench_idx]]
            bench_idx += 1
        if last_bench is None:
            continue  # port empieza antes que bench
        aligned_dates.append(d)
        port_vals.append(port_map[d])
        bench_vals.append(last_bench)

    if not aligned_dates:
        return [], [], []

    # Rebase a 100 en la primera fecha comun
    port_base = port_vals[0]
    bench_base = bench_vals[0]
    if port_base == 0 or bench_base == 0:
        return [], [], []

    port_rebased = [v / port_base * 100 for v in port_vals]
    bench_rebased = [v / bench_base * 100 for v in bench_vals]

    return aligned_dates, port_rebased, bench_rebased


# ============================================================
# RETURN CALCULATIONS
# ============================================================
def _return_between(series_map: dict, d0: str, d1: str) -> float | None:
    """Return % entre d0 y d1. None si alguno falta."""
    v0 = series_map.get(d0)
    v1 = series_map.get(d1)
    if v0 is None or v1 is None or v0 == 0:
        return None
    return (v1 / v0 - 1) * 100


def _find_ref_date(series_map: dict, target: str) -> str | None:
    """Busca el ultimo dia <= target en series_map. Retorna la key o None."""
    dates = sorted(series_map.keys())
    prev = None
    for d in dates:
        if d > target:
            return prev
        prev = d
    return prev


def _returns_by_period(port_map: dict, bench_map: dict, as_of: str) -> dict:
    """Calcula returns 1M, 3M, 6M, YTD, LTM, SI para portfolio y benchmark."""
    if not port_map:
        return {}

    dates_sorted = sorted(port_map.keys())
    inception = dates_sorted[0]
    latest = dates_sorted[-1]

    as_of_dt = datetime.strptime(latest, "%Y-%m-%d").date()

    periods = {
        "1M": (as_of_dt - timedelta(days=30)).isoformat(),
        "3M": (as_of_dt - timedelta(days=91)).isoformat(),
        "6M": (as_of_dt - timedelta(days=182)).isoformat(),
        "YTD": date(as_of_dt.year, 1, 1).isoformat(),
        "LTM": (as_of_dt - timedelta(days=365)).isoformat(),
        "SI": inception,
    }

    out = {}
    for period, ref_target in periods.items():
        ref_port = _find_ref_date(port_map, ref_target)
        ref_bench = _find_ref_date(bench_map, ref_target)
        p_ret = _return_between(port_map, ref_port, latest) if ref_port else None
        b_ret = _return_between(bench_map, ref_bench, latest) if ref_bench else None
        alpha_bp = (
            (p_ret - b_ret) * 100 if (p_ret is not None and b_ret is not None) else None
        )
        out[period] = {
            "portfolio_pct": round(p_ret, 2) if p_ret is not None else None,
            "benchmark_pct": round(b_ret, 2) if b_ret is not None else None,
            "alpha_bp": round(alpha_bp, 1) if alpha_bp is not None else None,
            "ref_date": ref_port,
        }
    return out


# ============================================================
# STATS: TE, IR, Sharpe, Beta, Correlation
# ============================================================
def _daily_returns(vals: list[float]) -> list[float]:
    """Retorna daily returns simples (v[i]/v[i-1] - 1)."""
    return [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]


def _mean(x): return sum(x) / len(x) if x else 0.0
def _stdev(x, ddof=1):
    if len(x) <= ddof: return 0.0
    m = _mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - ddof))
def _cov(x, y, ddof=1):
    if len(x) != len(y) or len(x) <= ddof: return 0.0
    mx, my = _mean(x), _mean(y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (len(x) - ddof)


def _stats(port_rebased: list[float], bench_rebased: list[float]) -> dict:
    """Calcula stats anualizados. Asume 252 trading days/year."""
    if len(port_rebased) < 30:
        return {"insufficient_data": True, "n_days": len(port_rebased)}

    port_ret = _daily_returns(port_rebased)
    bench_ret = _daily_returns(bench_rebased)
    n = min(len(port_ret), len(bench_ret))
    port_ret = port_ret[:n]
    bench_ret = bench_ret[:n]

    # Excess (portfolio - benchmark), daily
    excess = [p - b for p, b in zip(port_ret, bench_ret)]

    # Tracking Error annualized (stdev of excess * sqrt(252))
    te_daily = _stdev(excess)
    te_ann = te_daily * math.sqrt(TRADING_DAYS)

    # Info Ratio = (mean excess * 252) / TE_ann
    mean_excess_ann = _mean(excess) * TRADING_DAYS
    info_ratio = mean_excess_ann / te_ann if te_ann > 0 else 0.0

    # Sharpe (asumiendo Rf=0 para simplicidad — cash yield ~4%, ajuste marginal)
    port_mean_ann = _mean(port_ret) * TRADING_DAYS
    port_vol_ann = _stdev(port_ret) * math.sqrt(TRADING_DAYS)
    sharpe_port = port_mean_ann / port_vol_ann if port_vol_ann > 0 else 0.0

    bench_mean_ann = _mean(bench_ret) * TRADING_DAYS
    bench_vol_ann = _stdev(bench_ret) * math.sqrt(TRADING_DAYS)
    sharpe_bench = bench_mean_ann / bench_vol_ann if bench_vol_ann > 0 else 0.0

    # Beta = cov(port, bench) / var(bench)
    var_bench = _stdev(bench_ret) ** 2
    beta = _cov(port_ret, bench_ret) / var_bench if var_bench > 0 else 0.0

    # Correlation = cov / (stdev_port * stdev_bench)
    denom = _stdev(port_ret) * _stdev(bench_ret)
    corr = _cov(port_ret, bench_ret) / denom if denom > 0 else 0.0

    return {
        "n_days": n,
        "tracking_error_pct_ann": round(te_ann * 100, 2),
        "info_ratio": round(info_ratio, 3),
        "sharpe_portfolio": round(sharpe_port, 3),
        "sharpe_benchmark": round(sharpe_bench, 3),
        "beta": round(beta, 3),
        "correlation": round(corr, 3),
        "volatility_portfolio_pct_ann": round(port_vol_ann * 100, 2),
        "volatility_benchmark_pct_ann": round(bench_vol_ann * 100, 2),
    }


# ============================================================
# BUILD COMPARISONS
# ============================================================
def _build_comparison(
    port_series: list,
    port_value_key: str,
    bench_series: list,
    bench_value_key: str,
    port_name: str,
    bench_name: str,
    port_source: str,
    bench_source: str,
) -> dict:
    port_map = _series_to_date_map(port_series, port_value_key)
    bench_map = _series_to_date_map(bench_series, bench_value_key)

    dates, port_rebased, bench_rebased = _intersect_and_rebase(port_map, bench_map)

    # Series aligned & rebased para el chart
    series_out = [
        {
            "date": d,
            "portfolio": round(port_rebased[i], 4),
            "benchmark": round(bench_rebased[i], 4),
            "alpha_bp": round((port_rebased[i] - bench_rebased[i]) * 100, 2),
        }
        for i, d in enumerate(dates)
    ]

    # Returns por período (usando maps ORIGINALES no rebased para precision)
    returns = _returns_by_period(port_map, bench_map, dates[-1] if dates else "")

    # Stats
    stats = _stats(port_rebased, bench_rebased)

    return {
        "portfolio_name": port_name,
        "benchmark_name": bench_name,
        "portfolio_source": port_source,
        "benchmark_source": bench_source,
        "inception": dates[0] if dates else None,
        "as_of": dates[-1] if dates else None,
        "n_observations": len(dates),
        "series": series_out,
        "returns": returns,
        "stats": stats,
    }


def build(as_of: str | None = None) -> dict:
    if as_of is None:
        as_of = date.today().isoformat()

    # Load 4 fuentes
    with open(DATA_DIR / "lynk_nav_series.json", encoding="utf-8") as f:
        lynk = json.load(f)
    with open(DATA_DIR / "bmk_6040.json", encoding="utf-8") as f:
        bmk = json.load(f)
    with open(DATA_DIR / "equity_sleeve_real.json", encoding="utf-8") as f:
        eq = json.load(f)
    with open(DATA_DIR / "fi_sleeve_real.json", encoding="utf-8") as f:
        fi = json.load(f)

    comparisons = {
        "total_vs_6040": _build_comparison(
            port_series=lynk["series"],
            port_value_key="value",
            bench_series=bmk["series"],
            bench_value_key="value",
            port_name="BIG Total (Lynk NAV)",
            bench_name="60/40 Global (AOR ETF)",
            port_source="data/lynk_nav_series.json",
            bench_source="data/bmk_6040.json",
        ),
        "equity_vs_acwi": _build_comparison(
            port_series=eq["twr_series"],
            port_value_key="index",
            bench_series=eq["acwi_index_series"],
            bench_value_key="index",
            port_name="Equity Sleeve TWR",
            bench_name="ACWI",
            port_source="data/equity_sleeve_real.json -> twr_series",
            bench_source="data/equity_sleeve_real.json -> acwi_index_series",
        ),
        "fi_vs_agg": _build_comparison(
            port_series=fi["twr_series"],
            port_value_key="index",
            bench_series=fi["agg_index_series"],
            bench_value_key="index",
            port_name="FI Sleeve TWR",
            bench_name="AGG (Bloomberg Global Aggregate)",
            port_source="data/fi_sleeve_real.json -> twr_series",
            bench_source="data/fi_sleeve_real.json -> agg_index_series",
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "generated_at": utc_now_iso(),
        "note": "Comparaciones portfolio vs benchmark con fechas alineadas y rebased 100 en fecha comun. Fixes bug del dashboard viejo (arrays x separados sin intersect ni rebase).",
        "comparisons": comparisons,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="Snapshot date. Default: hoy.")
    args = ap.parse_args()

    target = args.date or date.today().isoformat()

    print(f"\n{'=' * 70}")
    print(f"  Build benchmark_comparison.json for {target}")
    print(f"{'=' * 70}\n")

    result = build(as_of=target)

    out_dir = CANONICAL_DIR / target
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "benchmark_comparison.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"  Output: {out_path}")
    print(f"  Size: {out_path.stat().st_size:,} bytes\n")

    for key, comp in result["comparisons"].items():
        print(f"  === {key} ===")
        print(f"    portfolio: {comp['portfolio_name']}")
        print(f"    benchmark: {comp['benchmark_name']}")
        print(f"    inception: {comp['inception']} -> as_of: {comp['as_of']}")
        print(f"    n_days:    {comp['n_observations']}")
        r = comp["returns"]
        print(f"    Returns:")
        for period in ["1M", "3M", "YTD", "LTM", "SI"]:
            v = r.get(period, {})
            p = v.get("portfolio_pct")
            b = v.get("benchmark_pct")
            a = v.get("alpha_bp")
            def _fmt_pct(x): return f"{x:+.2f}%" if x is not None else "  N/A "
            def _fmt_bp(x):  return f"{x:+.1f} bp" if x is not None else "  N/A"
            print(f"      {period:4s}: port={_fmt_pct(p)}  bench={_fmt_pct(b)}  alpha={_fmt_bp(a)}")
        s = comp["stats"]
        print(f"    Stats:")
        print(f"      TE_ann={s.get('tracking_error_pct_ann')}%  IR={s.get('info_ratio')}  Sharpe port={s.get('sharpe_portfolio')} bench={s.get('sharpe_benchmark')}")
        print(f"      Beta={s.get('beta')}  Corr={s.get('correlation')}  Vol port={s.get('volatility_portfolio_pct_ann')}% bench={s.get('volatility_benchmark_pct_ann')}%")
        print()


if __name__ == "__main__":
    main()
