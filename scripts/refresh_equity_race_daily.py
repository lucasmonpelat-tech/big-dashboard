"""
refresh_equity_race_daily.py
============================
Refresca DIARIO el "Buy-and-hold price race" (data/equity_contributions_real.json)
con el cierre del dia anterior (T-1), sin re-procesar transactions.

Como BIG tradea mensual, los anchors (first_buy_date, first_buy_price, acwi_start,
qty_remaining) NO cambian dia a dia -> solo cambia el end_price (cierre actual) y el
ACWI de hoy. Este script toma esos anchors (que el full-run equity_returns_vs_acwi.py
ya dejo guardados) y recalcula el race:

  return_pct = (close_T-1 - first_buy_price) / first_buy_price * 100
  acwi_return = (acwi_T-1 - acwi_start) / acwi_start * 100
  alpha = return - acwi_return

Fuentes del cierre T-1 (ya las mantiene el cron via refresh_equity_daily.py):
  - equity_sleeve_real.json -> sleeve_series_equity[-1].holdings[].price  (close por ticker)
  - equity_sleeve_real.json -> acwi_index_series[-1].price                (ACWI close)

Holdings CERRADOS (VIRTUS, NBRE, BRK.B): se mantienen fijos (end = last sell), no se tocan.

Usage:
    python refresh_equity_race_daily.py
"""
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
RACE_FILE = ROOT / "data" / "equity_contributions_real.json"
SLEEVE_FILE = ROOT / "data" / "equity_sleeve_real.json"


def status_label(alpha, is_closed):
    if alpha is None:
        return ("unknown", "[?] UNKNOWN")
    suffix_k = "_closed" if is_closed else ""
    suffix_l = " (cerrado)" if is_closed else ""
    if alpha > 0:
        return ("outperform" + suffix_k, "[+] OUTPERFORM" + suffix_l)
    elif alpha < 0:
        return ("underperform" + suffix_k, "[-] UNDERPERFORM" + suffix_l)
    return ("neutral" + suffix_k, "[=] NEUTRAL")


def main():
    today_iso = date.today().isoformat()
    print(f"[{datetime.now().isoformat()}] Refresh equity race daily ({today_iso})...")

    race = json.load(open(RACE_FILE, encoding="utf-8"))
    sleeve = json.load(open(SLEEVE_FILE, encoding="utf-8"))

    # Cierre T-1 por ticker (del ultimo punto del sleeve)
    last_pt = sleeve["sleeve_series_equity"][-1]
    close_by_ticker = {h["ticker"]: h.get("price") for h in last_pt.get("holdings", [])}
    close_date = last_pt["date"]

    # ACWI close T-1
    acwi_end = sleeve["acwi_index_series"][-1]["price"]
    acwi_date = sleeve["acwi_index_series"][-1]["date"]

    updated, frozen_closed, skipped = [], [], []
    for h in race["holdings"]:
        tk = h["ticker"]

        # Cerrados: no se tocan (end = last sell, fijo)
        if h.get("is_closed"):
            frozen_closed.append(tk)
            continue

        fbp = h.get("first_buy_price")
        acwi_start = h.get("acwi_start")
        close_px = close_by_ticker.get(tk)

        if not fbp or close_px is None:
            print(f"  WARN: {tk} sin first_buy_price o sin close fresco -> se mantiene")
            skipped.append(tk)
            continue

        # === Price race con cierre T-1 ===
        return_pct = (close_px - fbp) / fbp * 100
        acwi_return_pct = ((acwi_end / acwi_start - 1) * 100) if acwi_start else None
        alpha = (return_pct - acwi_return_pct) if acwi_return_pct is not None else None
        st, st_label = status_label(alpha, False)

        h["end_price"] = round(close_px, 4)
        h["period_end"] = close_date
        h["mwr_pct"] = round(return_pct, 2)                       # campo que lee la UI (= price race)
        h["acwi_period_return_pct"] = round(acwi_return_pct, 2) if acwi_return_pct is not None else None
        h["alpha_mwr_pp"] = round(alpha, 2) if alpha is not None else None
        h["status"] = st
        h["status_label"] = st_label
        # months_held actualizado al nuevo end
        try:
            d1 = datetime.fromisoformat(h["first_buy_date"]).date()
            d2 = datetime.fromisoformat(close_date).date()
            h["months_held"] = (d2.year - d1.year) * 12 + (d2.month - d1.month)
        except Exception:
            pass
        updated.append(tk)

    # Metadata
    race["refreshedAt"] = datetime.now().isoformat()
    open_ends = [h["period_end"] for h in race["holdings"] if not h.get("is_closed") and h.get("period_end")]
    if open_ends:
        race["period_end"] = max(open_ends)
    race["_daily_refresh_note"] = (
        f"Race recalculado {today_iso} con cierre T-1 ({close_date}) del sleeve "
        f"+ ACWI ({acwi_date}). Anchors (first_buy) del ultimo full-run de transactions."
    )

    with open(RACE_FILE, "w", encoding="utf-8") as f:
        json.dump(race, f, indent=2, ensure_ascii=False)

    print(f"  Actualizados (open, T-1 close): {updated}")
    print(f"  Frozen (cerrados): {frozen_closed}")
    if skipped:
        print(f"  Skipped: {skipped}")
    print(f"  Close date: {close_date} | ACWI date: {acwi_date}")
    print(f"  Saved: {RACE_FILE}")


if __name__ == "__main__":
    main()
