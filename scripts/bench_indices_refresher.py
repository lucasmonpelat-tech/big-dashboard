"""
bench_indices_refresher.py
==========================
Construye series base-100 de varios indices de referencia (S&P 500, MSCI ACWI,
Nasdaq 100, MSCI World) alineadas a la MISMA grilla de fechas y la MISMA fecha
base que el equity sleeve (equity_sleeve_real.json -> twr_series).

Sirve para el grafico "Normalized Performance" estilo Koyfin: BIG Equity Sleeve
vs indices seleccionables, todos rebaseados a 100 en la fecha de inception del
sleeve (primer punto de twr_series).

Logica:
  - lee las fechas de twr_series (month-ends + el punto "today")
  - baja de Yahoo el historico de cada indice cubriendo [base_date, today]
  - para cada fecha del grid toma el cierre on-or-before (asof)
  - rebasa cada serie a 100 en la primera fecha
  - mantiene exactamente las mismas fechas que el sleeve -> comparables 1:1

Inputs:
  data/equity_sleeve_real.json (grilla de fechas)
  Yahoo Finance (yfinance)

Output:
  data/equity_bench_indices.json

Usage:
    python bench_indices_refresher.py
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
SLEEVE_FILE = ROOT / "data" / "equity_sleeve_real.json"
OUTPUT_FILE = ROOT / "data" / "equity_bench_indices.json"

# Indices a graficar. ticker = simbolo Yahoo. ACWI ya esta en el sleeve file,
# pero lo incluimos aca tambien para que el grafico sea autocontenido y todas
# las series salgan de la misma fuente/fechas (consistencia 1:1).
INDICES = {
    "SP500":     {"ticker": "^GSPC", "name": "S&P 500",     "color": "#EF5350"},
    "ACWI":      {"ticker": "ACWI",  "name": "MSCI ACWI",   "color": "#64B5F6"},
    "NASDAQ100": {"ticker": "^NDX",  "name": "Nasdaq 100",  "color": "#BA68C8"},
    # MSCI World removido 2026-05-26: redundante con ACWI (la diferencia es ~11% EM
    # que el sleeve BIG sí toma — comparar contra MSCI World es castigarse en años EM+).
}


def load_grid():
    """Fechas (ISO) del equity sleeve, en orden. La primera es la base."""
    data = json.load(open(SLEEVE_FILE))
    dates = [p["date"] for p in data["twr_series"]]
    return dates


def fetch_history(ticker, start, end):
    """{date_iso: close} de Yahoo para [start, end]. {} si falla."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        out = {}
        for ts, row in hist.iterrows():
            out[ts.strftime("%Y-%m-%d")] = float(row["Close"])
        return out
    except Exception as e:
        print(f"  {ticker:<8} ERROR: {str(e)[:70]}")
        return {}


def asof_close(closes, target_iso):
    """Ultimo cierre en o antes de target_iso. None si no hay."""
    candidates = [d for d in closes if d <= target_iso]
    if not candidates:
        return None
    return closes[max(candidates)]


def build_series(closes, grid):
    """Rebasea a 100 en grid[0] y devuelve [{date, index}] alineado al grid."""
    base = asof_close(closes, grid[0])
    if not base:
        return None
    series = []
    for d in grid:
        px = asof_close(closes, d)
        if px is None:
            continue
        series.append({"date": d, "price": round(px, 4),
                       "index": round(px / base * 100, 4)})
    return series


def main():
    print(f"[{datetime.now().isoformat()}] Bench indices refresher...")
    grid = load_grid()
    base_date = grid[0]
    last_date = grid[-1]
    print(f"  Grid: {len(grid)} fechas, base {base_date} -> {last_date}")

    # bajamos historico con un colchon antes; politica T-1 close: NO incluir el dia actual
    # si todavia no cerro. yfinance trata `end` como exclusivo, asi que end=last_date
    # garantiza que solo bajamos cierres oficiales <= last_date - 1 dia.
    start = (datetime.fromisoformat(base_date) - timedelta(days=7)).strftime("%Y-%m-%d")
    end = last_date  # T-1 close: yfinance.history end es exclusivo

    indices_out = {}
    for key, meta in INDICES.items():
        closes = fetch_history(meta["ticker"], start, end)
        if not closes:
            print(f"  {key:<10} sin datos — se omite")
            continue
        series = build_series(closes, grid)
        if not series:
            print(f"  {key:<10} no se pudo rebasear — se omite")
            continue
        indices_out[key] = {
            "name": meta["name"], "ticker": meta["ticker"],
            "color": meta["color"], "series": series,
        }
        ytd_anchor = next((p for p in series if p["date"] == "2025-12-31"), None)
        last = series[-1]
        ytd = ((last["index"] / ytd_anchor["index"] - 1) * 100) if ytd_anchor else None
        ytd_s = f"{ytd:+.2f}%" if ytd is not None else "n/a"
        print(f"  {key:<10} {len(series)} pts  index {last['index']:.2f}  YTD {ytd_s}")

    # Merge: si un indice fallo este run, preservamos el ultimo bueno
    existing = {}
    if OUTPUT_FILE.exists():
        try:
            existing = json.load(open(OUTPUT_FILE)).get("indices", {})
        except Exception:
            pass
    merged = {**existing, **indices_out}

    out = {
        "_description": "Series base-100 de indices de referencia alineadas a la grilla y fecha base del equity sleeve. Alimenta el grafico Normalized Performance.",
        "refreshedAt": datetime.now().isoformat(),
        "source": "Yahoo Finance via bench_indices_refresher.py",
        "base_date": base_date,
        "indices": merged,
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved: {OUTPUT_FILE}  ({len(merged)} indices)")


if __name__ == "__main__":
    main()
