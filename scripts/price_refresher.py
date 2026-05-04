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
    # Working
    "ILF":   {"symbol": "ilf.us",    "market": "US",    "currency": "USD"},
    "ARGT":  {"symbol": "argt.us",   "market": "US",    "currency": "USD"},
    "GLD":   {"symbol": "gld.us",    "market": "US",    "currency": "USD"},
    "IBIT":  {"symbol": "ibit.us",   "market": "US",    "currency": "USD"},
    "CSPX":  {"symbol": "cspx.uk",   "market": "UK",    "currency": "USD"},
    # Alternative ticker candidates (Stooq sometimes lists under different suffixes)
    "THOR":  {"symbol": "tibix.us",  "market": "US",    "currency": "USD"},  # Class I
    "4BRZ":  {"symbol": "ewz.us",    "market": "US",    "currency": "USD"},  # iShares MSCI Brazil ETF (US-listed proxy)
    # BDC names on Stooq — try alternative formats
    "HLEND": {"symbol": "hlen.us",   "market": "US",    "currency": "USD"},
    "BPCC":  {"symbol": "bpcc.f",    "market": "F",     "currency": "USD"},
    "GCRED": {"symbol": "gcrd.us",   "market": "US",    "currency": "USD"},
}

STOOQ_URL_TEMPLATE = "https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=csv"
OUTPUT_FILE = Path(__file__).parent.parent / "data" / "live_prices.json"


def fetch_stooq_quote(symbol: str) -> dict | None:
    """Fetch a single quote from Stooq. Returns None on failure."""
    url = STOOQ_URL_TEMPLATE.format(symbol=symbol)
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        rows = list(csv.reader(io.StringIO(r.text)))
        if len(rows) < 2:
            return None
        header, data = rows[0], rows[1]
        rec = dict(zip(header, data))
        # Stooq returns "N/D" for invalid/unknown
        if rec.get("Close") in ("N/D", None, ""):
            return None
        return {
            "symbol": rec.get("Symbol"),
            "date":   rec.get("Date"),
            "time":   rec.get("Time"),
            "open":   float(rec["Open"]) if rec.get("Open", "N/D") != "N/D" else None,
            "high":   float(rec["High"]) if rec.get("High", "N/D") != "N/D" else None,
            "low":    float(rec["Low"]) if rec.get("Low", "N/D") != "N/D" else None,
            "close":  float(rec["Close"]),
            "volume": float(rec["Volume"]) if rec.get("Volume", "N/D") != "N/D" else 0,
        }
    except Exception as e:
        print(f"  X {symbol}: {e}")
        return None


def main():
    print(f"[{datetime.now().isoformat()}] Fetching live prices from Stooq...")
    results = {}
    for ticker, cfg in STOOQ_TICKERS.items():
        q = fetch_stooq_quote(cfg["symbol"])
        if q:
            results[ticker] = {
                "price": q["close"],
                "date": q["date"],
                "time": q["time"],
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "volume": q["volume"],
                "source": "Stooq",
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
