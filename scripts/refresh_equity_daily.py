"""
refresh_equity_daily.py
=======================
Recalcula SOLO el punto "today" del equity sleeve (equity_sleeve_real.json)
con precios del cierre anterior. Para el cron diario.

NO re-reconstruye desde transacciones (eso es mensual via portfolio_reconstructor
+ Excel Pershing). Solo actualiza el ultimo punto:
  - MV = qty (positions_latest, Pershing) x precio_cierre_anterior
        UCITS/4BRZ -> ucits_daily_nav.json (baha)
        ETFs       -> live_prices.json (Stooq)
  - TWR del tramo = MV_today / MV_ultimo_monthend - 1 (flow=0, sin trades intra-mes)
  - ACWI -> precio cierre anterior de Yahoo, rebaseado al primer punto

Inputs (todos en el repo o se bajan):
  data/equity_sleeve_real.json, data/ucits_daily_nav.json,
  data/live_prices.json, data/positions_latest.json, Yahoo (ACWI)

Usage:
    python refresh_equity_daily.py
"""

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
SLEEVE_FILE = ROOT / "data" / "equity_sleeve_real.json"


def _is_month_end(date_str):
    return date_str.endswith(("-28", "-29", "-30", "-31"))


def load_daily_prices():
    """{ticker: precio_cierre_anterior} de baha (UCITS) + Stooq (ETFs)."""
    px = {}
    try:
        ud = json.load(open(ROOT / "data" / "ucits_daily_nav.json", encoding="utf-8"))
        for rec in ud.get("navs", {}).values():
            if rec.get("ticker") and rec.get("nav"):
                px[rec["ticker"]] = rec["nav"]
    except Exception as e:
        print(f"  ucits_daily_nav skipped: {e}")
    try:
        lp = json.load(open(ROOT / "data" / "live_prices.json", encoding="utf-8"))
        prices = lp.get("prices", lp)
        for tk, rec in prices.items():
            if isinstance(rec, dict) and rec.get("price"):
                px.setdefault(tk, rec["price"])  # baha gana sobre Stooq (ej 4BRZ)
    except Exception as e:
        print(f"  live_prices skipped: {e}")
    return px


def fetch_acwi_close():
    """Ultimo cierre de ACWI (Yahoo). Devuelve (price, None) o (None, error)."""
    try:
        import yfinance as yf
        hist = yf.Ticker("ACWI").history(period="5d")
        if len(hist):
            return float(hist["Close"].iloc[-1]), None
        return None, "sin datos"
    except Exception as e:
        return None, str(e)[:60]


def main():
    print(f"[{datetime.now().isoformat()}] Refresh equity daily...")
    data = json.load(open(SLEEVE_FILE, encoding="utf-8"))
    twr = data["twr_series"]
    acwi = data["acwi_index_series"]
    sleeve = data["sleeve_series_equity"]
    if len(twr) < 2:
        print("  twr_series muy corto, abort.")
        return

    daily_px = load_daily_prices()
    print(f"  Precios cierre anterior: {len(daily_px)} tickers")

    # qty actual de cada equity holding (Pershing positions_latest)
    pl = json.load(open(ROOT / "data" / "positions_latest.json", encoding="utf-8"))
    eq_qty = {p["ticker"]: p.get("qty") for p in pl["positions"] if p["sleeve"] == "Equity"}

    # MV today = sum(qty x precio_fresco)
    holdings_today = []
    mv_today = 0.0
    for tk, qty in eq_qty.items():
        if not qty or qty <= 0:
            continue
        px = daily_px.get(tk)
        if px is None:
            print(f"  WARNING: sin precio fresco para {tk}, se omite del MV today")
            continue
        mv = qty * px
        mv_today += mv
        holdings_today.append({"ticker": tk, "qty": qty, "price": px, "mv": mv, "source": "daily_close"})

    today_iso = date.today().isoformat()

    # Determinar ancla: el ultimo punto month-end (no el "today" previo)
    if _is_month_end(twr[-1]["date"]):
        anchor = twr[-1]            # ultimo punto es fin de mes -> agregamos today nuevo
        append_new = True
    else:
        anchor = twr[-2]           # ultimo punto es un "today" previo -> lo reemplazamos
        append_new = False

    # FIX: compute flow_in entre anchor y today comparando qty (Modified Dietz, flow al final).
    # Sin esto, los buy/sell intra-mes inflan/desinflan el TWR (bug: spurious +1.87% en May 2026
    # por la compra de NBGMT el 7-May que no estaba descontada).
    # 2026-06-10: cambio a "ultimo <= anchor date" porque sleeve_series_equity puede tener
    # gaps (no siempre tiene exactamente el month-end).
    anchor_sleeve = None
    for s in sleeve:
        if s["date"] <= anchor["date"]:
            anchor_sleeve = s
    anchor_holdings = {h["ticker"]: h for h in (anchor_sleeve or {}).get("holdings", [])}
    flow_in = 0.0
    for tk, qty_today in eq_qty.items():
        if not qty_today or qty_today <= 0:
            continue
        qty_anchor = (anchor_holdings.get(tk) or {}).get("qty") or 0
        delta = qty_today - qty_anchor
        if abs(delta) > 0.001:
            # precio: usar el fresco si existe, sino el del anchor
            px = daily_px.get(tk) or (anchor_holdings.get(tk) or {}).get("price") or 0
            flow_in += delta * px
    if abs(flow_in) > 1:
        print(f"  flow_in detectado desde {anchor['date']}: ${flow_in:+,.0f}")

    mv_anchor = anchor["mv_usd"]
    twr_today = ((mv_today - flow_in) / mv_anchor - 1) if mv_anchor else 0
    index_today = anchor["index"] * (1 + twr_today)

    new_twr_point = {"date": today_iso, "mv_usd": mv_today, "flow_in": round(flow_in, 2),
                     "twr": twr_today, "index": round(index_today, 4)}
    new_sleeve_point = {"date": today_iso, "mv_usd": mv_today, "holdings": holdings_today}

    if append_new:
        twr.append(new_twr_point)
        sleeve.append(new_sleeve_point)
    else:
        twr[-1] = new_twr_point
        sleeve[-1] = new_sleeve_point

    # ACWI today (Yahoo, rebaseado al primer punto)
    acwi_price, err = fetch_acwi_close()
    base_price = acwi[0]["price"]
    if acwi_price and base_price:
        acwi_index = round(acwi_price / base_price * 100, 4)
        new_acwi = {"date": today_iso, "price": round(acwi_price, 4), "index": acwi_index}
        if _is_month_end(acwi[-1]["date"]):
            acwi.append(new_acwi)
        else:
            acwi[-1] = new_acwi
        print(f"  ACWI cierre: ${acwi_price:.2f} -> index {acwi_index}")
    else:
        print(f"  ACWI no actualizado ({err}) — se mantiene el ultimo punto")

    data["refreshedAt"] = datetime.now().isoformat()
    data["_daily_refresh_note"] = f"Punto {today_iso} recalculado con precios cierre anterior (baha+Stooq+Yahoo). qty de Pershing {pl.get('as_of','?')}."

    with open(SLEEVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # YTD para el log
    dec_t = next((p for p in twr if p["date"] == "2025-12-31"), None)
    dec_a = next((p for p in acwi if p["date"] == "2025-12-31"), None)
    if dec_t and dec_a:
        big_ytd = (twr[-1]["index"] / dec_t["index"] - 1) * 100
        acwi_ytd = (acwi[-1]["index"] / dec_a["index"] - 1) * 100
        print(f"\n  Equity YTD: {big_ytd:+.2f}%  |  ACWI YTD: {acwi_ytd:+.2f}%  |  Alpha: {big_ytd-acwi_ytd:+.2f}pp")
    print(f"  Saved: {SLEEVE_FILE}  (MV today ${mv_today:,.0f})")


if __name__ == "__main__":
    main()
