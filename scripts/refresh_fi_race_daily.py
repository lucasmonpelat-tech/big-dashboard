"""
refresh_fi_race_daily.py
========================
Refresca DIARIO los retornos POR FONDO del FI sleeve (tabla "Holding
Contributions" de la pestana FI Race) con el NAV del cierre anterior (T-1),
analogo a refresh_equity_race_daily.py.

PROBLEMA QUE RESUELVE
---------------------
Los fondos FI (PIMCO LD/INC/EM, MANIG, SGCB, MANEM) reportan NAV a baha
DIARIO, pero fi_race.py solo usa la serie de retornos MENSUALES de baha
(data/baha/<ISIN>.json). Por eso la tabla por-fondo quedaba mensual/stale.
Este script extiende el retorno mensual hasta T-1 usando el NAV diario.

COMO FUNCIONA (calibracion de ancla + bridge diario)
----------------------------------------------------
No guardamos historia de NAV por fondo, asi que derivamos un NAV-ancla
*implicito* a partir del NAV vivo y del retorno MENSUAL que ya calculo
fi_race.py:

    nav_ancla_ytd = nav_vivo / (1 + ytd_mensual/100)     # Dec-31 implicito
    nav_ancla_si  = nav_vivo / (1 + si_mensual/100)       # inception implicito

Se calibra UNA vez por mes (cuando fi_race.py avanza stats.latest_month) y
queda fija. De ahi en mas, cada dia:

    ytd_T1 = (nav_vivo_T1 / nav_ancla_ytd - 1) * 100
    si_T1  = (nav_vivo_T1 / nav_ancla_si  - 1) * 100

El dia de calibracion ytd_T1 == ytd_mensual (parcial del mes = 0); a partir
de ahi se mueve con el NAV diario. Cada fin de mes fi_race.py recalibra y
absorbe el error del parcial (chico en bonos). Si no hay NAV vivo para un
fondo (TGF carry, o scrape fallido) se deja el valor mensual intacto.

Las anclas se persisten en fi_race.json -> "_daily_anchors" (por ISIN).

Fuentes:
  - data/fi_race.json     -> holdings[] (ytd/si mensual, weight) + stats.latest_month
  - data/fi_fund_nav.json -> NAV vivo T-1 por ISIN (baha, via baha_nav_refresher.py)

Usage:
    python refresh_fi_race_daily.py
"""
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
RACE_FILE = ROOT / "data" / "fi_race.json"
FUND_NAV_FILE = ROOT / "data" / "fi_fund_nav.json"

# ============================================================================
# ANCLAS DE NAV (clases de ACUMULACION -> el NAV ya trae el cupon reinvertido,
# asi que el retorno del NAV ES el retorno total). Cargar el NAV de CIERRE que
# publica baha, EN LA MISMA MONEDA que el NAV vivo (SGCB en EUR, el resto USD).
#   YTD = NAV_T1 / NAV_DEC31 - 1
#   SI  = NAV_T1 / NAV_INCEPTION - 1     (inception BIG = 30-jun-2025)
# Si un ISIN NO tiene ancla fija aca, se usa la calibracion implicita (fallback)
# desde el retorno mensual de fi_race.py.
#
# PENDIENTE: Lucas pasa los NAV reales de baha. Completar y descomentar.
# ============================================================================
NAV_DEC31 = {
    # Del statement Pershing 31-dic-2025 (precio 30/12/25), clases ACC:
    "IE00B87KCF77": 20.0100,    # PIMCO-INC  (PIMCO Income Institutional ACC USD)
    "IE000OE87WX6": 122.6100,   # MANIG      (Man GLG Global IG Opportunities IVY USD)
    # PENDIENTE baha (no estaban en la cuenta al 31-dic, comprados en 2026):
    # "IE00BDT57R20": None,     # PIMCO-LD   (PIMCO GIS Low Duration Income)
    # "IE00B29K0P99": None,     # PIMCO-EM   (PIMCO GIS EM Local Bond)
    # "LU2049315265": None,     # SGCB       (Schroder GAIA Cat Bond C, EUR)
}
NAV_INCEPTION = {
    # NAV al 30-jun-2025 (inception BIG) por ISIN — opcional, para SI exacto.
    # Si falta, SI cae al fallback (calibracion / mensual).
}


def _calibrated_return(anchors, isin, metric, live, ccy, basis_month, monthly_pct, today_iso):
    """Fallback: ancla implicita calibrada desde el retorno MENSUAL de fi_race.py.

    Calibra una vez por mes (cuando fi_race.py avanza de mes o cambia la moneda) y
    queda fija; de ahi en mas el retorno = live/ancla - 1. El dia de calibracion
    reproduce el mensual exacto (parcial=0). Devuelve (return_pct, anchor_dict) o
    (None, None) si no hay baseline mensual para calibrar.
    """
    field = f"nav_anchor_{metric}"
    a = anchors.get(isin) or {}
    stale = (a.get(field) is None or a.get("basis_month") != basis_month or a.get("currency") != ccy)
    if stale:
        if monthly_pct is None:
            return None, None
        a[field] = live / (1 + monthly_pct / 100.0)
        a["basis_month"] = basis_month
        a["currency"] = ccy
        a["anchor_date"] = today_iso
        anchors[isin] = a
    return (live / a[field] - 1) * 100, a


def main():
    today_iso = date.today().isoformat()
    print(f"[{datetime.now().isoformat()}] Refresh FI race daily ({today_iso})...")

    if not RACE_FILE.exists():
        print(f"  ERROR: {RACE_FILE} no existe. Corre fi_race.py primero.")
        return
    race = json.load(open(RACE_FILE, encoding="utf-8"))

    if not FUND_NAV_FILE.exists():
        print(f"  WARN: {FUND_NAV_FILE} no existe todavia (scraper baha aun no corrio para FI).")
        print("        Se mantiene la tabla mensual sin cambios.")
        return
    fund_navs = json.load(open(FUND_NAV_FILE, encoding="utf-8")).get("navs", {})
    if not fund_navs:
        print("  WARN: fi_fund_nav.json sin navs. Se mantiene mensual.")
        return

    basis_month = (race.get("stats") or {}).get("latest_month")  # ej "2026-04"
    anchors = race.get("_daily_anchors", {})

    updated, exact, calibrated, skipped = [], [], [], []
    for h in race.get("holdings", []):
        isin = h.get("isin")
        rec = fund_navs.get(isin)
        live = rec.get("nav") if rec else None
        ccy = rec.get("currency") if rec else None

        # Sin NAV vivo (TGF carry, MANEM sin baha, o scrape fallido) -> intacto
        if live is None or live <= 0:
            skipped.append(h.get("ticker"))
            continue

        dec31 = NAV_DEC31.get(isin)
        incep = NAV_INCEPTION.get(isin)

        # ---- YTD ----
        if dec31:
            # EXACTO: NAV acumulativo / NAV real de baha al 31-dic (incluye cupon).
            ytd_t1 = (live / dec31 - 1) * 100
            ytd_src = "baha_nav_dec31"
        else:
            # FALLBACK: calibrar ancla implicita desde el YTD mensual de fi_race.py.
            ytd_t1, a_ytd = _calibrated_return(anchors, isin, "ytd", live, ccy,
                                               basis_month, h.get("ytd_return_pct"), today_iso)
            ytd_src = "calibrated" if ytd_t1 is not None else None

        # ---- SI ----
        if incep:
            si_t1 = (live / incep - 1) * 100
        else:
            si_t1, a_si = _calibrated_return(anchors, isin, "si", live, ccy,
                                             basis_month, h.get("si_return_pct"), today_iso)

        if ytd_t1 is None:
            skipped.append(h.get("ticker"))
            continue

        weight = h.get("weight_pct") or 0
        h["ytd_return_pct"] = round(ytd_t1, 2)
        if si_t1 is not None:
            h["si_return_pct"] = round(si_t1, 2)
            h["contribution_pct"] = round(si_t1 * weight / 100.0, 2)
        h["ytd_contribution_pct"] = round(ytd_t1 * weight / 100.0, 2)
        h["nav_t1"] = round(live, 4)
        h["nav_currency"] = ccy
        h["nav_date"] = rec.get("scrapedAt")
        h["return_source"] = ytd_src
        updated.append(h.get("ticker"))
        (exact if ytd_src == "baha_nav_dec31" else calibrated).append(h.get("ticker"))

    race["_daily_anchors"] = anchors
    race["refreshedAt"] = datetime.now().isoformat()
    race["_daily_race_note"] = (
        f"Retornos por fondo recalculados {today_iso} con NAV vivo T-1 (baha). "
        f"YTD exacto (ancla NAV 31-dic): {exact or '—'}. "
        f"YTD calibrado desde mensual {basis_month}: {calibrated or '—'}. "
        f"Sin NAV vivo (carry/scrape): {skipped or '—'}."
    )

    with open(RACE_FILE, "w", encoding="utf-8") as f:
        json.dump(race, f, indent=2, ensure_ascii=False)

    print(f"  Actualizados T-1: {updated}")
    print(f"  YTD exacto (ancla 31-dic): {exact or '—'}")
    print(f"  YTD calibrado (fallback mensual): {calibrated or '—'}")
    if skipped:
        print(f"  Sin NAV vivo (mensual/carry): {skipped}")
    print(f"  Basis month: {basis_month}")
    print(f"  Saved: {RACE_FILE}")


if __name__ == "__main__":
    main()
