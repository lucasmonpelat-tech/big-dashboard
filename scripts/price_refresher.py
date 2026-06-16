"""
price_refresher.py
==================
Fetch live prices from Yahoo Finance (T-1 close) for all ETFs/BDCs listed in STOOQ_TICKERS.
Outputs a JSON file `data/live_prices.json` that the dashboard can fetch.

Usage:
    python price_refresher.py

NaN/None GUARD (added 2026-06-16 tras incident):
- Si yfinance retorna NaN/None para un ticker, NO sobreescribimos el valor previo.
- Mantenemos el ultimo precio valido conocido y marcamos como stale.
- Evita que un dia con data source roto propague NaN downstream (rompiendo
  equity sleeve, alts race, attribution, etc).

Run daily (or whenever you want to refresh live prices) via cron / task scheduler.
"""

import requests
import json
import csv
import io
import os
import math
from datetime import datetime
from pathlib import Path

# ==============================================================
# CONFIG - Tickers a refreshear
# ==============================================================
STOOQ_TICKERS = {
    # MIGRADO 2026-06-09 de Stooq -> Yahoo Finance (yfinance).
    # Stooq agrego anti-bot challenge JS (proof-of-work) que rompio el scraper.
    # yfinance es mas estable y ya lo usamos para bench_indices, bmk_6040, etc.
    # Politica T-1 close: NO incluir el dia actual si todavia no cerro.
    "ILF":   {"symbol": "ILF",     "currency": "USD"},
    "ARGT":  {"symbol": "ARGT",    "currency": "USD"},
    "GLD":   {"symbol": "GLD",     "currency": "USD"},
    "IBIT":  {"symbol": "IBIT",    "currency": "USD"},
    "CSPX":  {"symbol": "CSPX.L",  "currency": "USD"},  # London UCITS, denominated USD
    "THOR":  {"symbol": "TIBIX",   "currency": "USD"},
    "4BRZ":  {"symbol": "EWZ",     "currency": "USD"},  # US-listed proxy de MSCI Brazil
    # Privados (BDCs) — no listados en Yahoo. Se manejan via fallback "last known price"
    # en el script consumer (refresh_equity/alts_daily.py).
    "HLEND": {"symbol": None,      "currency": "USD"},
    "BPCC":  {"symbol": None,      "currency": "USD"},
    "GCRED": {"symbol": None,      "currency": "USD"},
}

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "live_prices.json"


def _is_valid_price(value) -> bool:
    """True si el valor es un numero real (no None, no NaN, no Inf)."""
    if value is None:
        return False
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return False
        if v <= 0:
            return False
        return True
    except (TypeError, ValueError):
        return False


def fetch_yf_quote(symbol: str) -> dict | None:
    """Fetch latest T-1 close quote from Yahoo Finance via yfinance.

    Politica T-1: si el mercado todavia esta abierto cuando este script corre,
    devolvemos el cierre del dia anterior (no el precio intraday).

    Retorna None si:
    - yfinance error / no data
    - El ultimo close es NaN/None/Inf/<=0 (data source roto)
    """
    if not symbol:
        return None
    try:
        import yfinance as yf
        from datetime import date, timedelta
        t = yf.Ticker(symbol)
        end = date.today()
        start = end - timedelta(days=14)
        h = t.history(start=start.isoformat(), end=end.isoformat())  # T-1: end exclusivo
        if h is None or h.empty:
            return None
        # Iterar de la mas reciente hacia atras buscando un close valido
        # (a veces yfinance devuelve NaN en filas recientes pero datos validos atras)
        for i in range(len(h) - 1, -1, -1):
            close_val = h.iloc[i].get("Close")
            if _is_valid_price(close_val):
                last_date = h.index[i].strftime("%Y-%m-%d")
                row = h.iloc[i]
                return {
                    "symbol": symbol,
                    "date":   last_date,
                    "open":   float(row["Open"]) if _is_valid_price(row.get("Open")) else float(close_val),
                    "high":   float(row["High"]) if _is_valid_price(row.get("High")) else float(close_val),
                    "low":    float(row["Low"])  if _is_valid_price(row.get("Low"))  else float(close_val),
                    "close":  float(close_val),
                    "volume": float(row["Volume"]) if _is_valid_price(row.get("Volume")) else 0,
                }
        # Ningun close valido en la serie -> data source roto
        return None
    except Exception as e:
        print(f"  X {symbol}: {e}")
        return None


def load_previous_prices() -> dict:
    """Carga el ultimo live_prices.json para tener fallback en caso de NaN."""
    try:
        if OUTPUT_FILE.exists():
            prev = json.load(open(OUTPUT_FILE, encoding="utf-8"))
            return prev.get("prices", {})
    except Exception as e:
        print(f"  WARN: no pude leer live_prices previo: {e}")
    return {}


def main():
    print(f"[{datetime.now().isoformat()}] Fetching live prices from Yahoo Finance (T-1 close)...")
    previous = load_previous_prices()
    results = {}
    stale_count = 0
    fresh_count = 0

    for ticker, cfg in STOOQ_TICKERS.items():
        symbol = cfg.get("symbol")
        if not symbol:
            # Privados sin ticker publico -> no se refreshea aca
            results[ticker] = None
            print(f"  - {ticker:6s} = skipped (privado, sin ticker publico)")
            continue

        q = fetch_yf_quote(symbol)

        if q and _is_valid_price(q["close"]):
            # PRECIO VALIDO: actualizar
            results[ticker] = {
                "price": q["close"],
                "date": q["date"],
                "time": None,
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "volume": q["volume"],
                "source": "Yahoo Finance",
                "stale": False,
            }
            fresh_count += 1
            print(f"  OK {ticker:6s} = {q['close']:>10.2f} ({q['date']})")
        else:
            # GUARD: precio invalido/NaN -> mantener el valor previo si existe
            prev = previous.get(ticker)
            if prev and _is_valid_price(prev.get("price")):
                results[ticker] = {
                    **prev,
                    "stale": True,
                    "stale_since": datetime.now().isoformat(),
                    "stale_reason": "yfinance retorno NaN/None",
                }
                stale_count += 1
                print(f"  ! {ticker:6s} = {prev['price']:>10.2f} (STALE, manteniendo previo de {prev.get('date','?')})")
            else:
                # No hay precio previo tampoco -> None
                results[ticker] = None
                print(f"  X {ticker:6s} = unavailable (sin precio previo)")

    # Add refresh metadata
    output = {
        "refreshedAt": datetime.now().isoformat(),
        "prices": results,
        "_meta": {
            "fresh": fresh_count,
            "stale": stale_count,
            "guard_note": "Tickers con stale=true mantienen ultimo precio valido (yfinance retorno NaN)",
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"\nWritten to: {OUTPUT_FILE}")
    print(f"Total: {fresh_count} fresh + {stale_count} stale (fallback) / {len(results)} tickers")
    if stale_count > 0:
        print(f"WARN: {stale_count} tickers usando precio previo (data source con NaN/None).")


if __name__ == "__main__":
    main()
