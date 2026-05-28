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


def status_for(alpha):
    if alpha is None:
        return None
    return "outperform" if alpha > 0 else ("underperform" if alpha < 0 else "neutral")


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

    updated, bootstrapped, skipped = [], [], []
    for h in race.get("holdings", []):
        isin = h.get("isin")
        rec = fund_navs.get(isin)
        live = rec.get("nav") if rec else None
        ccy = rec.get("currency") if rec else None

        # Sin NAV vivo (TGF carry, MANEM sin baha, o scrape fallido) -> intacto
        if live is None or live <= 0:
            skipped.append(h.get("ticker"))
            continue

        a = anchors.get(isin)
        need_bootstrap = (
            a is None
            or a.get("basis_month") != basis_month
            or a.get("currency") != ccy
            or not a.get("nav_anchor_ytd")
            or not a.get("nav_anchor_si")
        )

        if need_bootstrap:
            # Calibrar anclas desde el retorno MENSUAL actual (limpio, recien
            # corrido por fi_race.py) + el NAV vivo de hoy.
            ytd_m = h.get("ytd_return_pct")
            si_m = h.get("si_return_pct")
            if ytd_m is None or si_m is None:
                # No hay baseline mensual -> no se puede calibrar, dejar como esta
                skipped.append(h.get("ticker"))
                continue
            a = {
                "nav_anchor_ytd": live / (1 + ytd_m / 100.0),
                "nav_anchor_si": live / (1 + si_m / 100.0),
                "basis_month": basis_month,
                "basis_ytd_pct": ytd_m,
                "basis_si_pct": si_m,
                "currency": ccy,
                "anchor_date": today_iso,
            }
            anchors[isin] = a
            bootstrapped.append(h.get("ticker"))

        # Bridge diario: retorno = nav_vivo / nav_ancla - 1
        ytd_t1 = (live / a["nav_anchor_ytd"] - 1) * 100
        si_t1 = (live / a["nav_anchor_si"] - 1) * 100
        weight = h.get("weight_pct") or 0

        h["ytd_return_pct"] = round(ytd_t1, 2)
        h["si_return_pct"] = round(si_t1, 2)
        h["ytd_contribution_pct"] = round(ytd_t1 * weight / 100.0, 2)
        h["contribution_pct"] = round(si_t1 * weight / 100.0, 2)
        h["nav_t1"] = round(live, 4)
        h["nav_currency"] = ccy
        h["nav_date"] = rec.get("scrapedAt")
        h["return_source"] = "baha_daily_T1"
        updated.append(h.get("ticker"))

    race["_daily_anchors"] = anchors
    race["refreshedAt"] = datetime.now().isoformat()
    race["_daily_race_note"] = (
        f"Retornos por fondo recalculados {today_iso} con NAV vivo T-1 (baha) sobre "
        f"ancla calibrada al cierre mensual {basis_month}. Fondos sin NAV vivo "
        f"(carry/scrape fallido) quedan en su retorno mensual."
    )

    with open(RACE_FILE, "w", encoding="utf-8") as f:
        json.dump(race, f, indent=2, ensure_ascii=False)

    print(f"  Actualizados T-1: {updated}")
    if bootstrapped:
        print(f"  Re-calibrados (nuevo mes/ancla): {bootstrapped}")
    if skipped:
        print(f"  Sin NAV vivo (mensual/carry): {skipped}")
    print(f"  Basis month: {basis_month}")
    print(f"  Saved: {RACE_FILE}")


if __name__ == "__main__":
    main()
