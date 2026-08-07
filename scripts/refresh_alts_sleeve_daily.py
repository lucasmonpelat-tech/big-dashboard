"""
refresh_alts_sleeve_daily.py
=============================
Recalcula SOLO el punto "today" del Alts sleeve TWR (data/alts_sleeve_real.json)
con el mismo patron que refresh_equity_daily.py / refresh_fi_daily.py.

A diferencia de Equity/FI, Alts no tiene "qty x precio" simple (CALP/GCRED/HLEND/
BPCC son statements, no precios de mercado diarios) -- por eso este script corre
DESPUES de refresh_alts_daily.py en el cron, y usa el total_alts_usd que ese
script ya calculo en alts_race.json (que combina precios T-1 de IBIT/GLD con
el ultimo statement disponible de CALP/GCRED/HLEND/BPCC/HLGPI/FLEX).

NO re-reconstruye la historia (eso es la reconstruccion completa 2026-07-31 con
statements Pershing + Carlyle, ver _rebuild_note en el JSON). Solo extiende
twr_series con Modified Dietz desde el ultimo anchor (mismo mecanismo que
Equity/FI, incluido el WARNING si el anchor tiene mas de 5 dias de antiguedad).

Ademas actualiza sleeve_index/sleeve_monthly_returns del mes en curso en
data/alts_race.json -- alts_race.py (que originalmente poblaba esos campos con
la reconstruccion completa) NO esta en el cron diario, asi que sin este paso
quedarian congelados en el valor de la ultima vez que alguien lo corrio a mano.

Debe correr ANTES de sync_alts_ugl.py en el cron, para que sus stats de
1M/3M/6M/YTD/SI (que lee de sleeve_index) se calculen ya con el punto de hoy.

Usage:
    python scripts/refresh_alts_sleeve_daily.py
"""
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
SLEEVE_FILE = ROOT / "data" / "alts_sleeve_real.json"
ALTS_RACE_FILE = ROOT / "data" / "alts_race.json"
HOLDINGS_FILE = ROOT / "data" / "holdings_returns_alternatives.json"


def _is_month_end(date_str):
    import calendar
    y, m, d = map(int, date_str.split("-"))
    return d == calendar.monthrange(y, m)[1]


def _find_last_real_month_end(twr_series):
    """Busca hacia ATRAS por FECHA (no por posicion) el ultimo punto que sea
    fin de mes calendario real con mv_usd valido. Mismo fix que
    refresh_equity_daily.py / refresh_fi_daily.py (2026-08-06): usar `twr[-2]`
    a ciegas rompe en cuanto la serie tiene algun punto intermedio inesperado."""
    for pt in reversed(twr_series):
        if _is_month_end(pt["date"]) and pt.get("mv_usd") is not None:
            return pt
    return twr_series[0] if twr_series else None


def _load_buys_since(anchor_date):
    try:
        d = json.load(open(HOLDINGS_FILE, encoding="utf-8"))
    except Exception:
        return []
    out = []
    for h in d.get("holdings", []):
        for b in h.get("buys_history", []) or []:
            if b.get("date", "") > anchor_date:
                out.append({"ticker": h.get("ticker"), "date": b["date"], "cost": b["cost"]})
    return out


def _modified_dietz_return(mv_start, mv_end, flows, anchor_date, today_iso):
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
    print(f"[{datetime.now().isoformat()}] Refresh Alts sleeve daily...")
    data = json.load(open(SLEEVE_FILE, encoding="utf-8"))
    twr = data["twr_series"]
    if len(twr) < 2:
        print("  twr_series muy corto, abort.")
        return

    try:
        ar = json.load(open(ALTS_RACE_FILE, encoding="utf-8"))
        mv_today = sum(h["value_usd"] for h in ar.get("holdings", []))
    except Exception as e:
        print(f"  ABORT: no se pudo leer total_alts desde alts_race.json ({e}). NO se sobreescribe el JSON.")
        return

    if not mv_today or mv_today <= 0:
        print(f"  ABORT: mv_today invalido ({mv_today}). NO se sobreescribe el JSON.")
        return

    today_iso = date.today().isoformat()

    anchor = _find_last_real_month_end(twr)
    if anchor is None:
        print("  ABORT: no se encontro ningun anchor month-end valido en twr_series.")
        return

    days_gap = (date.fromisoformat(today_iso) - date.fromisoformat(anchor["date"])).days
    if days_gap > 5:
        print(f"  WARNING: anchor tiene {days_gap} dias de antiguedad -- revisar por que el refresh diario no corrio antes")

    buys_since_anchor = _load_buys_since(anchor["date"])
    mv_anchor = anchor["mv_usd"]
    twr_today, flow_in = _modified_dietz_return(mv_anchor, mv_today, buys_since_anchor, anchor["date"], today_iso)
    if abs(flow_in) > 1:
        print(f"  flow_in detectado desde {anchor['date']}: ${flow_in:+,.0f} ({len(buys_since_anchor)} buys, Modified Dietz ponderado por fecha)")
    index_today = anchor["index"] * (1 + twr_today)

    new_point = {"date": today_iso, "mv_usd": round(mv_today, 2), "flow_in": round(flow_in, 2),
                 "twr": twr_today, "index": round(index_today, 4)}

    # Un punto por dia calendario -- ver refresh_equity_daily.py (mismo fix 2026-08-06).
    if twr[-1]["date"] == today_iso:
        twr[-1] = new_point
    else:
        twr.append(new_point)

    data["refreshedAt"] = datetime.now().isoformat()
    data["_daily_refresh_note"] = f"Punto {today_iso} recalculado con total_alts_usd de alts_race.json (T-1 IBIT/GLD + ultimo statement CALP/GCRED/HLEND/BPCC/HLGPI/FLEX)."

    with open(SLEEVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Propagar el punto de hoy a alts_race.json (sleeve_index/sleeve_monthly_returns
    # del mes en curso) -- ver docstring, alts_race.py no corre en el cron diario.
    current_month = today_iso[:7]
    ar["sleeve_index"][current_month] = round(index_today, 4)
    months_sorted = sorted(ar["sleeve_index"].keys())
    idx_pos = months_sorted.index(current_month)
    if idx_pos > 0:
        prev_month_val = ar["sleeve_index"][months_sorted[idx_pos - 1]]
        ar["sleeve_monthly_returns"][current_month] = round(index_today / prev_month_val - 1, 6)
    with open(ALTS_RACE_FILE, "w", encoding="utf-8") as f:
        json.dump(ar, f, indent=2, ensure_ascii=False)

    dec_t = next((p for p in twr if p["date"] == "2025-12-31"), None)
    if dec_t:
        ytd = (twr[-1]["index"] / dec_t["index"] - 1) * 100
        print(f"\n  Alts YTD: {ytd:+.2f}%")
    print(f"  Saved: {SLEEVE_FILE}  (MV today ${mv_today:,.0f})")
    print(f"  Saved: {ALTS_RACE_FILE}  (sleeve_index[{current_month}] = {index_today:.4f})")


if __name__ == "__main__":
    main()
