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
import math
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
SLEEVE_FILE = ROOT / "data" / "equity_sleeve_real.json"


def _is_valid_price(value) -> bool:
    """True si value es un numero real positivo (no None, no NaN, no Inf, no <=0).

    Guard critico: rec.get('price') puede retornar float('nan') que es TRUTHY
    en Python (`if nan:` -> True). Sin este check, NaN propaga downstream y
    rompe equity_sleeve, alts_race, attribution. Bug recurrente 2026-06-16.
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


def _find_last_real_month_end(twr_series):
    """Busca hacia ATRAS por FECHA (no por posicion) el ultimo punto que sea
    fin de mes calendario real con mv_usd valido.

    Fix 2026-08-06: la version anterior usaba `twr[-2]` (posicion fija en el
    array), asumiendo que la serie SIEMPRE tiene exactamente "ultimo mes
    cerrado + un dia en curso". Eso se rompe en cuanto otro script
    (interpolate_equity_series.py, que corre TODOS los dias dentro de
    dashboard_v2.transform.run_all) inserta o saca puntos intermedios -- el
    ancla empieza a apuntar a un dia sintetico/interpolado en vez del ultimo
    mes real, y el error se compone dia a dia sin que nadie lo note (mismo
    patron que el bug de julio-2026, ver memoria
    bug_twr_anchor_gap_modified_dietz.md). Buscar por fecha en vez de por
    posicion es inmune a cuantos puntos haya en el medio.
    """
    for pt in reversed(twr_series):
        if _is_month_end(pt["date"]) and pt.get("mv_usd") is not None and not pt.get("interpolated"):
            return pt
    return twr_series[0] if twr_series else None


def _is_month_end(date_str):
    """True solo si date_str es el ULTIMO dia real del mes calendario.

    Bug previo (pre-2026-06-26): consideraba CUALQUIER dia -28/-29/-30/-31
    como month-end. Para meses de 31 dias (Mar/May/Jul/etc), el -28 disparaba
    un reset prematuro del anchor TWR → flow_in y twr quedaban en 0 los
    ultimos 3-4 dias del mes → audit TWR mensual rompia (721 bps en May-26).
    """
    import calendar
    y, m, d = map(int, date_str.split("-"))
    return d == calendar.monthrange(y, m)[1]


def load_daily_prices():
    """{ticker: precio_cierre_anterior} de baha (UCITS) + Stooq (ETFs)."""
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
                px.setdefault(tk, rec["price"])  # baha gana sobre live_prices (ej 4BRZ)
    except Exception as e:
        print(f"  live_prices skipped: {e}")
    return px


def fetch_acwi_close():
    """Ultimo cierre VALIDO de ACWI (Yahoo). Devuelve (price, None) o (None, error).

    Guard NaN (2026-06-19): yfinance ocasionalmente retorna NaN para el ultimo
    close cuando el mercado esta abierto o hay delay. Iteramos hacia atras
    buscando el ultimo close valido (no None/NaN/<=0).
    """
    try:
        import yfinance as yf
        hist = yf.Ticker("ACWI").history(period="10d")
        if not len(hist):
            return None, "sin datos"
        # Iterar de mas reciente a mas viejo buscando un close valido
        for i in range(len(hist) - 1, -1, -1):
            close = hist["Close"].iloc[i]
            if _is_valid_price(close):
                return float(close), None
        return None, "todos los closes invalidos (NaN)"
    except Exception as e:
        return None, str(e)[:60]


def _load_buys_since(holdings_file, anchor_date):
    """Lee buys_history de holdings_returns_equity.json (ya confiable, merge
    incremental + filtro PENDING CONFIRM, ver compute_holdings_returns.py),
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
    ucits_daily_nav.json, generando un Equity YTD deflactado ficticio).

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
        if not _is_valid_price(px):
            # Guard NaN: si no hay precio valido, intentar fallback al ultimo MV conocido
            last_sleeve = sleeve[-1] if sleeve else {}
            last_holding = next(
                (h for h in last_sleeve.get("holdings", []) if h.get("ticker") == tk),
                None,
            )
            if last_holding and _is_valid_price(last_holding.get("mv")):
                fallback_mv = last_holding["mv"]
                fallback_px = last_holding.get("price")
                holdings_today.append({
                    "ticker": tk, "qty": qty, "price": fallback_px,
                    "mv": fallback_mv, "source": "fallback_last_known",
                })
                mv_today += fallback_mv
                print(f"  ! {tk}: sin precio fresco, fallback al ultimo MV ${fallback_mv:,.0f}")
            else:
                print(f"  WARNING: sin precio fresco NI fallback para {tk}, se omite del MV today")
            continue
        mv = qty * px
        if not _is_valid_price(mv):
            print(f"  WARNING: MV calculado NaN para {tk} (qty={qty}, px={px}), se omite")
            continue
        mv_today += mv
        holdings_today.append({"ticker": tk, "qty": qty, "price": px, "mv": mv, "source": "daily_close"})

    # Guard final: si mv_today no es valido, abort sin sobreescribir el JSON
    if not _is_valid_price(mv_today):
        print(f"  ABORT: mv_today calculado NaN/0 ({mv_today}). NO se sobreescribe el JSON.")
        return

    today_iso = date.today().isoformat()

    # Determinar ancla: el ultimo punto month-end REAL, buscado por fecha
    # (fix 2026-08-06, ver _find_last_real_month_end -- antes usaba twr[-2]
    # a ciegas, lo que dejaba de corresponder al ultimo mes real en cuanto
    # interpolate_equity_series.py insertaba/sacaba puntos intermedios).
    anchor = _find_last_real_month_end(twr)
    if anchor is None:
        print("  ABORT: no se encontro ningun anchor month-end valido en twr_series.")
        return

    # FIX 2026-07-30: Modified Dietz ponderando cada flow por su fecha real
    # (antes: comparaba qty vs un "anchor_sleeve" separado que se podia
    # quedar viejo por semanas si el refresh diario fallaba -- ej: se quedo
    # pegado por ~1 mes por el corte de ucits_daily_nav.json, generando un
    # Equity YTD deflactado el dia que volvio a andar, porque la formula
    # vieja asumia que TODO el flow acumulado en el mes entraba de una al
    # final del periodo). Ahora usa las fechas reales de
    # holdings_returns_equity.json (buys_history, ya confiable).
    days_gap = (date.fromisoformat(today_iso) - date.fromisoformat(anchor["date"])).days
    if days_gap > 5:
        print(f"  WARNING: anchor tiene {days_gap} dias de antiguedad -- revisar por que el refresh diario no corrio antes")
    holdings_file = ROOT / "data" / "holdings_returns_equity.json"
    buys_since_anchor = _load_buys_since(holdings_file, anchor["date"])
    mv_anchor = anchor["mv_usd"]
    twr_today, flow_in = _modified_dietz_return(mv_anchor, mv_today, buys_since_anchor, anchor["date"], today_iso)
    if abs(flow_in) > 1:
        print(f"  flow_in detectado desde {anchor['date']}: ${flow_in:+,.0f} ({len(buys_since_anchor)} buys, Modified Dietz ponderado por fecha)")
    index_today = anchor["index"] * (1 + twr_today)

    new_twr_point = {"date": today_iso, "mv_usd": mv_today, "flow_in": round(flow_in, 2),
                     "twr": twr_today, "index": round(index_today, 4)}
    new_sleeve_point = {"date": today_iso, "mv_usd": mv_today, "holdings": holdings_today}

    # Un punto por dia calendario: si ya hay un punto de HOY (re-corrida el
    # mismo dia), se reemplaza; si no, se agrega uno nuevo. Nunca se descarta
    # el punto de AYER para calcular el de hoy -- eso es lo que rompia el
    # ancla de _find_last_real_month_end() dia tras dia (ver arriba).
    if twr[-1]["date"] == today_iso:
        twr[-1] = new_twr_point
        sleeve[-1] = new_sleeve_point
    else:
        twr.append(new_twr_point)
        sleeve.append(new_sleeve_point)

    # ACWI today (Yahoo, rebaseado al primer punto)
    acwi_price, err = fetch_acwi_close()
    base_price = acwi[0]["price"]
    # Guard: tanto acwi_price como base_price deben ser validos (no NaN)
    if _is_valid_price(acwi_price) and _is_valid_price(base_price):
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
