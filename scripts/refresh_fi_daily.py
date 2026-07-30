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
import math
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
SLEEVE_FILE = ROOT / "data" / "fi_sleeve_real.json"


def _is_month_end(date_str):
    """True solo si date_str es el ultimo dia REAL del mes calendario.

    Bug previo (pre-2026-06-26): consideraba CUALQUIER dia -28/-29/-30/-31
    como month-end → reset anchor prematuro en meses de 31 dias.
    """
    import calendar
    y, m, d = map(int, date_str.split("-"))
    return d == calendar.monthrange(y, m)[1]


def _is_valid_price(value) -> bool:
    """True si value es un numero real positivo. Guard contra NaN-as-truthy.

    Bug fix 2026-06-16: rec.get('price') puede retornar float('nan') que es
    TRUTHY en Python. Sin este check, NaN se asigna como precio valido y
    rompe MV downstream.
    """
    if value is None:
        return False
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v) or v <= 0:
            return False
        return True
    except (TypeError, ValueError):
        return False


def load_daily_prices():
    """{ticker: precio_cierre_anterior} de baha (UCITS) + live_prices (ETFs).

    Guard NaN: si rec['price'] o rec['nav'] es NaN/None/<=0, NO se incluye.
    Esto fuerza el fallback "pershing_frozen" downstream en vez de propagar NaN.
    """
    px = {}
    try:
        ud = json.load(open(ROOT / "data" / "ucits_daily_nav.json", encoding="utf-8"))
        for rec in ud.get("navs", {}).values():
            ticker = rec.get("ticker")
            nav = rec.get("nav")
            if ticker and _is_valid_price(nav):
                px[ticker] = nav
    except Exception as e:
        print(f"  ucits_daily_nav skipped: {e}")
    try:
        lp = json.load(open(ROOT / "data" / "live_prices.json", encoding="utf-8"))
        prices = lp.get("prices", lp)
        for tk, rec in prices.items():
            if isinstance(rec, dict) and _is_valid_price(rec.get("price")):
                px.setdefault(tk, rec["price"])  # baha gana sobre live_prices
    except Exception as e:
        print(f"  live_prices skipped: {e}")
    return px


def fetch_agg_close():
    """Ultimo cierre del bench FI (UCITS USD Acc, alineado con baha).

    2026-06-18: cambiado de AGG (NYSE) a IUAG.L (UCITS London) por decision
    de Lucas para alinearse con lo que ve en baha. UCITS tiene TER mayor y
    cierre Europa, da YTD distinto.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker("IUAG.L").history(period="5d")
        if len(hist):
            return float(hist["Close"].iloc[-1]), None
        return None, "sin datos"
    except Exception as e:
        return None, str(e)[:60]


def _load_buys_since(holdings_file, anchor_date):
    """Lee buys_history de holdings_returns_fixed_income.json (ya confiable,
    merge incremental + filtro PENDING CONFIRM, ver compute_holdings_returns.py),
    filtrando compras con fecha posterior a anchor_date.

    Returns: list de {ticker, date, cost}.
    """
    try:
        d = json.load(open(holdings_file, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for h in d.get("holdings", []):
        for b in h.get("buys_history", []) or []:
            if b.get("date", "") > anchor_date:
                out.append({"ticker": h.get("ticker"), "date": b["date"], "cost": b["cost"]})
    return out


def _modified_dietz_return(mv_start, mv_end, flows, anchor_date, today_iso):
    """Modified Dietz ponderando cada flow por su fecha real dentro del
    periodo -- evita el sesgo de asumir que TODO el flow entro al final
    (formula previa), que se vuelve grande cuando el periodo es largo.
    Ver fix 2026-07-30 (anchor quedo pegado ~1 mes por corte de
    ucits_daily_nav.json, generando un FI YTD negativo ficticio).

    flows: list de {date, cost} (solo BUYS, cost positivo = entra plata).
    Returns: (return_pct_decimal, total_flow_usd).
    """
    d0 = date.fromisoformat(anchor_date)
    d1 = date.fromisoformat(today_iso)
    total_days = (d1 - d0).days
    if total_days <= 0:
        return 0.0, 0.0
    total_flow = 0.0
    weighted_flow = 0.0
    for f in flows:
        try:
            fd = date.fromisoformat(f["date"][:10])
        except Exception:
            continue
        days_remaining = (d1 - fd).days
        weight = max(0.0, min(1.0, days_remaining / total_days))
        total_flow += f["cost"]
        weighted_flow += f["cost"] * weight
    denom = mv_start + weighted_flow
    if denom <= 0:
        return 0.0, total_flow
    ret = (mv_end - mv_start - total_flow) / denom
    return ret, total_flow


def main():
    print(f"[{datetime.now().isoformat()}] Refresh FI daily...")
    data = json.load(open(SLEEVE_FILE, encoding="utf-8"))
    twr = data["twr_series"]
    agg = data["agg_index_series"]
    sleeve = data["sleeve_series_fi"]
    if len(twr) < 2:
        print("  twr_series muy corto, abort.")
        return

    daily_px = load_daily_prices()
    print(f"  Precios cierre anterior: {len(daily_px)} tickers")

    # qty actual de cada FI holding (Pershing positions_latest)
    pl = json.load(open(ROOT / "data" / "positions_latest.json", encoding="utf-8"))
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
        if _is_valid_price(px):
            mv = qty * px
            if _is_valid_price(mv):
                holdings_today.append({"ticker": tk, "qty": qty, "price": px, "mv": mv, "source": "daily_close"})
                mv_today += mv
                continue
        # Fallback: mantener ultimo MV de Pershing
        prev = last_holdings.get(tk)
        if prev and _is_valid_price(prev.get("mv")):
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

    # FIX 2026-07-30: Modified Dietz ponderando cada flow por su fecha real
    # (antes: comparaba qty vs un "anchor_sleeve" separado que se podia
    # quedar viejo por semanas si el refresh diario fallaba -- ej: se quedo
    # pegado en 30-Jun por 1 mes por el corte de ucits_daily_nav.json,
    # generando un FI YTD -1% ficticio el dia que volvio a andar, porque la
    # formula vieja asumia que TODO el flow acumulado en el mes entraba de
    # una al final del periodo). Ahora usa las fechas reales de
    # holdings_returns_fixed_income.json (buys_history, ya confiable).
    days_gap = (date.fromisoformat(today_iso) - date.fromisoformat(anchor["date"])).days
    if days_gap > 5:
        print(f"  WARNING: anchor tiene {days_gap} dias de antiguedad -- revisar por que el refresh diario no corrio antes")
    holdings_file = ROOT / "data" / "holdings_returns_fixed_income.json"
    buys_since_anchor = _load_buys_since(holdings_file, anchor["date"])
    mv_anchor = anchor["mv_usd"]
    twr_today, flow_in = _modified_dietz_return(mv_anchor, mv_today, buys_since_anchor, anchor["date"], today_iso)
    if abs(flow_in) > 1:
        print(f"  flow_in detectado desde {anchor['date']}: ${flow_in:+,.0f} ({len(buys_since_anchor)} buys, Modified Dietz ponderado por fecha)")
    index_today = anchor["index"] * (1 + twr_today)

    # Guard final: abort si calculos resultan NaN/0 (NO sobreescribir el JSON con basura)
    if not _is_valid_price(mv_today) or not _is_valid_price(index_today):
        print(f"  ABORT: mv_today={mv_today} index_today={index_today} invalido. NO se sobreescribe.")
        return

    new_twr_point = {"date": today_iso, "mv_usd": mv_today, "flow_in": round(flow_in, 2),
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
