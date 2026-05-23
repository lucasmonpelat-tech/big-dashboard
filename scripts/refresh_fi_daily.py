"""
refresh_fi_daily.py
===================
Recalcula SOLO el punto "today" del FI sleeve (fi_sleeve_real.json)
con precios del cierre anterior. Para el cron diario.

NO re-reconstruye desde transacciones (eso es mensual via portfolio_reconstructor
+ Excel Pershing). Solo actualiza el ultimo punto:
  - MV = qty (positions_latest, Pershing) x precio_cierre_anterior
        UCITS/funds -> ucits_daily_nav.json (baha)  [hoy ningun FI matchea]
        ETFs        -> live_prices.json (Stooq)     [hoy ningun FI matchea]
  - Fallback: si no hay precio fresco para un ticker, MANTENER el ultimo MV de
    Pershing del ultimo punto de sleeve_series_fi (src: "pershing_frozen").
    Esto evita romper el FI mientras los fondos no tengan precio fresco baha.
  - TWR del tramo = MV_today / MV_ultimo_monthend - 1 (flow=0, sin trades intra-mes)
  - AGG -> precio cierre anterior de Yahoo, rebaseado al primer punto

Inputs (todos en el repo o se bajan):
  data/fi_sleeve_real.json, data/ucits_daily_nav.json,
  data/live_prices.json, data/positions_latest.json, Yahoo (AGG)

Usage:
    python refresh_fi_daily.py
"""

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
SLEEVE_FILE = ROOT / "data" / "fi_sleeve_real.json"


def _is_month_end(date_str):
    return date_str.endswith(("-28", "-29", "-30", "-31"))


def load_daily_prices():
    """{ticker: precio_cierre_anterior} de baha (UCITS) + Stooq (ETFs)."""
    px = {}
    try:
        ud = json.load(open(ROOT / "data" / "ucits_daily_nav.json"))
        for rec in ud.get("navs", {}).values():
            if rec.get("ticker") and rec.get("nav"):
                px[rec["ticker"]] = rec["nav"]
    except Exception as e:
        print(f"  ucits_daily_nav skipped: {e}")
    try:
        lp = json.load(open(ROOT / "data" / "live_prices.json"))
        prices = lp.get("prices", lp)
        for tk, rec in prices.items():
            if isinstance(rec, dict) and rec.get("price"):
                px.setdefault(tk, rec["price"])  # baha gana sobre Stooq
    except Exception as e:
        print(f"  live_prices skipped: {e}")
    return px


def fetch_agg_close():
    """Ultimo cierre de AGG (Yahoo). Devuelve (price, None) o (None, error)."""
    try:
        import yfinance as yf
        hist = yf.Ticker("AGG").history(period="5d")
        if len(hist):
            return float(hist["Close"].iloc[-1]), None
        return None, "sin datos"
    except Exception as e:
        return None, str(e)[:60]


def main():
    print(f"[{datetime.now().isoformat()}] Refresh FI daily...")
    data = json.load(open(SLEEVE_FILE))
    twr = data["twr_series"]
    agg = data["agg_index_series"]
    sleeve = data["sleeve_series_fi"]
    if len(twr) < 2:
        print("  twr_series muy corto, abort.")
        return

    daily_px = load_daily_prices()
    print(f"  Precios cierre anterior: {len(daily_px)} tickers")

    # qty actual de cada FI holding (Pershing positions_latest)
    pl = json.load(open(ROOT / "data" / "positions_latest.json"))
    fi_qty = {p["ticker"]: p.get("qty") for p in pl["positions"] if p["sleeve"] == "Fixed Income"}

    # Indice del ultimo sleeve point para fallback (price/mv frozen)
    last_sleeve = sleeve[-1] if sleeve else None
    last_holdings = {h["ticker"]: h for h in (last_sleeve or {}).get("holdings", [])}

    # MV today: sum(qty x precio_fresco) -- si no hay precio fresco, MANTENER mv del ultimo punto
    holdings_today = []
    mv_today = 0.0
    for tk, qty in fi_qty.items():
        if not qty or qty <= 0:
            continue
        px = daily_px.get(tk)
        if px is not None:
            mv = qty * px
            holdings_today.append({"ticker": tk, "qty": qty, "price": px, "mv": mv, "source": "daily_close"})
            mv_today += mv
        else:
            # Fallback: mantener ultimo MV de Pershing
            prev = last_holdings.get(tk)
            if prev and prev.get("mv") is not None:
                holdings_today.append({
                    "ticker": tk,
                    "qty": qty,
                    "price": prev.get("price"),
                    "mv": prev["mv"],
                    "source": "pershing_frozen",
                })
                mv_today += prev["mv"]
                print(f"  fallback pershing_frozen: {tk}  mv ${prev['mv']:,.0f}")
            else:
                print(f"  WARNING: sin precio fresco NI frozen para {tk}, se omite del MV today")

    today_iso = date.today().isoformat()

    # Determinar ancla: el ultimo punto month-end (no el "today" previo)
    if _is_month_end(twr[-1]["date"]):
        anchor = twr[-1]            # ultimo punto es fin de mes -> agregamos today nuevo
        append_new = True
    else:
        anchor = twr[-2]           # ultimo punto es un "today" previo -> lo reemplazamos
        append_new = False

    mv_anchor = anchor["mv_usd"]
    twr_today = (mv_today / mv_anchor - 1) if mv_anchor else 0
    index_today = anchor["index"] * (1 + twr_today)

    new_twr_point = {"date": today_iso, "mv_usd": mv_today, "flow_in": 0,
                     "twr": twr_today, "index": round(index_today, 4)}
    new_sleeve_point = {"date": today_iso, "mv_usd": mv_today, "holdings": holdings_today}

    if append_new:
        twr.append(new_twr_point)
        sleeve.append(new_sleeve_point)
    else:
        twr[-1] = new_twr_point
        sleeve[-1] = new_sleeve_point

    # AGG today (Yahoo, rebaseado al primer punto)
    agg_price, err = fetch_agg_close()
    base_price = agg[0]["price"]
    if agg_price and base_price:
        agg_index = round(agg_price / base_price * 100, 4)
        new_agg = {"date": today_iso, "price": round(agg_price, 4), "index": agg_index}
        if _is_month_end(agg[-1]["date"]):
            agg.append(new_agg)
        else:
            agg[-1] = new_agg
        print(f"  AGG cierre: ${agg_price:.2f} -> index {agg_index}")
    else:
        print(f"  AGG no actualizado ({err}) — se mantiene el ultimo punto")

    data["refreshedAt"] = datetime.now().isoformat()
    data["_daily_refresh_note"] = f"Punto {today_iso} recalculado con precios cierre anterior (baha+Stooq+Yahoo, fallback pershing_frozen). qty de Pershing {pl.get('as_of','?')}."

    with open(SLEEVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # YTD para el log
    dec_t = next((p for p in twr if p["date"] == "2025-12-31"), None)
    dec_a = next((p for p in agg if p["date"] == "2025-12-31"), None)
    if dec_t and dec_a:
        big_ytd = (twr[-1]["index"] / dec_t["index"] - 1) * 100
        agg_ytd = (agg[-1]["index"] / dec_a["index"] - 1) * 100
        print(f"\n  FI YTD: {big_ytd:+.2f}%  |  AGG YTD: {agg_ytd:+.2f}%  |  Alpha: {big_ytd-agg_ytd:+.2f}pp")
    print(f"  Saved: {SLEEVE_FILE}  (MV today ${mv_today:,.0f})")


if __name__ == "__main__":
    main()
