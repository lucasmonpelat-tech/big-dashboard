"""
price_refresher.py
==================
Fetch live prices from Stooq for all ETFs/BDCs listed in STOOQ_TICKERS.
Outputs a JSON file `data/live_prices.json` that the dashboard can fetch.

Usage:
    python price_refresher.py

Why this script?
- The dashboard HTML tries to fetch Stooq directly via JS (client-side fetch).
- Some browsers block CORS on stooq.com. This Python script acts as a
  server-side refresher, producing a static JSON that JS can load locally.

Run daily (or whenever you want to refresh live prices) via cron / task scheduler.
"""

import requests
import json
import csv
import io
import os
from datetime import datetime
from pathlib import Path

# ==============================================================
# CONFIG - Same mapping as in data/live_prices.js
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


def fetch_yf_quote(symbol: str) -> dict | None:
    """Fetch latest T-1 close quote from Yahoo Finance via yfinance.

    Politica T-1: si el mercado todavia esta abierto cuando este script corre,
    devolvemos el cierre del dia anterior (no el precio intraday).
    """
    if not symbol:
        return None
    try:
        import yfinance as yf
        from datetime import date, timedelta
        t = yf.Ticker(symbol)
        # Ultimos 7 dias para tener buffer (weekends + holidays)
        end = date.today()
        start = end - timedelta(days=14)
        h = t.history(start=start.isoformat(), end=end.isoformat())  # T-1: end exclusivo
        if h is None or h.empty:
            return None
        last = h.iloc[-1]
        last_date = h.index[-1].strftime("%Y-%m-%d")
        return {
            "symbol": symbol,
            "date":   last_date,
            "open":   float(last["Open"]),
            "high":   float(last["High"]),
            "low":    float(last["Low"]),
            "close":  float(last["Close"]),
            "volume": float(last["Volume"]) if "Volume" in last else 0,
        }
    except Exception as e:
        print(f"  X {symbol}: {e}")
        return None


def main():
    print(f"[{datetime.now().isoformat()}] Fetching live prices from Yahoo Finance (T-1 close)...")
    results = {}
    for ticker, cfg in STOOQ_TICKERS.items():
        symbol = cfg.get("symbol")
        if not symbol:
            results[ticker] = None
            print(f"  - {ticker:6s} = skipped (privado, sin ticker publico)")
            continue
        q = fetch_yf_quote(symbol)
        if q:
            results[ticker] = {
                "price": q["close"],
                "date": q["date"],
                "time": None,
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "volume": q["volume"],
                "source": "Yahoo Finance",
            }
            print(f"  OK {ticker:6s} = {q['close']:>10.2f} ({q['date']})")
        else:
            results[ticker] = None
            print(f"  X {ticker:6s} = unavailable")

    # Add refresh metadata
    output = {
        "refreshedAt": datetime.now().isoformat(),
        "prices": results,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nWritten to: {OUTPUT_FILE}")
    print(f"Total: {sum(1 for v in results.values() if v)} prices fetched / {len(results)} tickers")


if __name__ == "__main__":
    main()
