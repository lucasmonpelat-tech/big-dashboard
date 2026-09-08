"""
refresh_fi_race_daily.py
========================
Refresca DIARIO el archivo data/fi_race.json. Hace DOS cosas distintas:

  A) RETORNOS por fondo (ytd/si) con el NAV del cierre anterior T-1, extendiendo
     la serie mensual. Es el proposito original, explicado mas abajo.

  B) PESOS, MV y METRICAS por fondo, releidos de su fuente de verdad en cada
     corrida. Se agrego el 2026-09-08 -- ver el bloque "PESOS Y METRICAS" mas
     abajo para el por que. Resumen: eran datos fosiles de un script borrado,
     y quedaron mal DOS veces.

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

import race_weights

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
    # De baha 31-dic-2025 (Lucas, busqueda por ISIN), clases Inst/Acc USD:
    "IE00BDT57R20": 13.8000,    # PIMCO-LD   (PIMCO GIS Low Duration Income, Inst Acc USD)
    "IE00B29K0P99": 17.9400,    # PIMCO-EM   (PIMCO GIS Emerging Local Bond, Inst Acc USD)
    "LU2049315265": 2079.2600,  # SGCB       (Schroder GAIA Cat Bond C Accumulation, USD)
    "IE00089T5MA6": 108.5400,   # MANEM      (Man EM Corporate Credit Alternative IV USD)
}
NAV_INCEPTION = {
    # NAV al 30-jun-2025 (inception BIG) por ISIN — opcional, para SI exacto.
    # Si falta, SI cae al fallback (calibracion / mensual).
}


# ============================================================================
# PESOS Y METRICAS: se re-derivan de la fuente, NO se arrastran del archivo
# ============================================================================
# POR QUE EXISTE (2026-09-08)
# ---------------------------
# fi_race.json tenia DOS bloques de datos fosiles, los dos por la misma causa:
# el unico script que los escribia (fi_race.py, el rebuild completo) se borro el
# 2026-08-20, y este script -- el unico que quedo en el cron -- solo tocaba
# YTD/SI. Todo lo demas quedo congelado mientras refreshedAt se seguia
# actualizando cada dia: el archivo PARECIA fresco.
#
#   1) weight_pct / value_usd  congelados desde 2026-05-05. Al 31-Ago decia
#      PIMCO-LD 38.66% y PIMCO-INC 19.42% cuando la realidad era casi al reves
#      (28.56% / 29.08%), y el sleeve $10.35M contra $11.05M reales. Es la
#      segunda vez que pasa lo mismo -- la primera fue en Agosto y se parcheo
#      en el HTML en vez de en el origen, asi que volvio.
#
#   2) ytw / duration / maturity / rating  eran una copia de data/funds/*.json
#      hecha una vez. MANEM entro con ceros y ahi se quedo, aun despues de
#      pasar de $20K a $270K y de que cargaramos su factsheet.
#
# La regla que sale de esto: si un campo tiene una fuente de verdad en otro
# lado, se relee de la fuente en cada corrida. Nada se arrastra.
#
#   weight_pct / value_usd            <- canonical holdings_returns.json
#   ytw / duration / maturity/rating  <- data/funds/<TICKER>.json
#   fi_stats_include                  <- data/funds/<TICKER>.json (regla Lucas
#                                        2026-09-07: solo USD o hedgeado a USD)


def refrescar_ust_y_spreads(race):
    """UST 10Y en vivo + spread_vs_ust = ytw - UST, recalculado para todos.

    POR QUE (2026-09-08)
    --------------------
    `spread_vs_ust` era otro campo fosil: los valores guardados salian de un UST
    de 4.56%, y el 08-sep el 10Y estaba en 4.79%. O sea que TODOS los spreads
    del tab FI venian ~23bp corridos.

    Ademas MANEM tenia spread -4.56%: se habia calculado con ytw=0 (0 - 4.56)
    cuando el fondo todavia no tenia factsheet cargado. El HTML lo tapaba con la
    regla "si ytw=0 y duration=0, mostrar guion". Al cargarle el factsheet real
    esa regla dejo de aplicar y el -4.56% habria quedado a la vista.

    Se recalcula el spread de todos contra el UST del dia. Si Yahoo no responde,
    se reutiliza el ultimo UST conocido y se marca stale -- pero NO se inventa
    un spread contra un numero que no sabemos si es de hoy.
    """
    ref = race.get("ust_reference")
    # Historicamente ust_reference era un string ("10Y US Treasury (^TNX)"), asi
    # que el HTML leia race.ust_reference.value y siempre le daba undefined.
    # Ahora es un objeto con el valor adentro.
    previo = ref.get("value") if isinstance(ref, dict) else None

    ust, fecha, fuente = None, None, None
    try:
        import yfinance as yf
        hist = yf.Ticker("^TNX").history(period="5d")
        if not hist.empty:
            ust = round(float(hist["Close"].iloc[-1]), 3)
            fecha = str(hist.index[-1].date())
            fuente = "Yahoo ^TNX"
    except Exception as e:
        print(f"  WARN UST 10Y: {e}")

    if ust is None:
        if previo is None:
            print("  WARN: sin UST 10Y y sin valor previo -- spreads sin tocar.")
            return
        ust, fuente = previo, "ultimo conocido (Yahoo no respondio)"
        fecha = ref.get("date") if isinstance(ref, dict) else None
        print(f"  WARN: UST 10Y no se pudo refrescar, se usa el previo {ust}%")

    race["ust_reference"] = {
        "label": "10Y US Treasury (^TNX)",
        "value": ust,
        "date": fecha,
        "source": fuente,
    }

    n = 0
    for h in race.get("holdings", []):
        ytw = h.get("ytw")
        if ytw is None or ytw <= 0:
            # Sin YTW no hay spread posible. Se BORRA en vez de dejar el viejo:
            # un spread calculado contra un ytw que ya no existe es peor que
            # ningun spread (el HTML muestra guion cuando falta).
            h.pop("spread_vs_ust", None)
            continue
        h["spread_vs_ust"] = round(ytw - ust, 2)
        n += 1
    print(f"  UST 10Y {ust}% ({fecha}, {fuente}) -> {n} spreads recalculados")


def _metricas_por_ticker():
    """{ticker: {ytw, duration, maturity, rating, fi_stats_include}} de data/funds."""
    out = {}
    for p in sorted((ROOT / "data" / "funds").glob("*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("sleeve") != "Fixed Income":
            continue
        fm = d.get("fi_metrics") or {}
        out[d.get("ticker")] = {
            "ytw": fm.get("ytw"),
            "duration": fm.get("duration"),
            "maturity": fm.get("maturity"),
            "rating": fm.get("rating"),
            "fi_stats_include": d.get("fi_stats_include"),
            "as_of_factsheet": d.get("as_of_factsheet"),
        }
    return out


def refrescar_pesos_y_metricas(race):
    """Reescribe weight_pct/value_usd desde canonical y las metricas desde data/funds."""
    race_weights.aplicar(race, "fixed_income")

    metricas = _metricas_por_ticker()
    faltan = []
    for h in race.get("holdings", []):
        m = metricas.get(h.get("ticker"))
        if not m:
            faltan.append(h.get("ticker"))
            continue
        for campo in ("ytw", "duration", "maturity", "rating"):
            if m.get(campo) is not None:
                h[campo] = m[campo]
        # El HTML necesita saber que fondos entran en los KPI ponderados. La
        # regla vive en data/funds/*.json; aca solo se transporta.
        h["fi_stats_include"] = m.get("fi_stats_include")
        h["metrics_as_of"] = m.get("as_of_factsheet")
    race["_metrics_source"] = "data/funds/<TICKER>.json (fi_metrics)"
    if faltan:
        print(f"  WARN: sin data/funds/<TICKER>.json: {faltan}")

    # Va al final: el spread se calcula contra el ytw que se acaba de escribir.
    refrescar_ust_y_spreads(race)


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

    # Pesos, MV y metricas por fondo: SIEMPRE releidos de su fuente (ver el
    # bloque de arriba). Va antes de los retornos porque contribution_pct se
    # calcula con el peso, y con el peso viejo salia mal.
    refrescar_pesos_y_metricas(race)

    # FIX 2026-07-02: preferir ucits_daily_nav.json (donde estan los NAVs vivos
    # actualizados por baha_nav_refresher). fi_fund_nav.json quedaba vacio pq
    # el pipeline se consolido en ucits_daily_nav. Fallback al legacy si existe.
    ucits_file = ROOT / "data" / "ucits_daily_nav.json"
    fund_navs = {}
    if ucits_file.exists():
        try:
            ucits = json.load(open(ucits_file, encoding="utf-8")).get("navs", {})
            for isin_key, rec in ucits.items():
                # ucits_daily_nav guarda por ISIN. Normalizar formato: {isin: {nav, currency}}
                fund_navs[isin_key] = {
                    "nav": rec.get("nav"),
                    "currency": rec.get("currency", "USD"),
                    "ticker": rec.get("ticker"),
                }
            if fund_navs:
                print(f"  Loaded {len(fund_navs)} NAVs desde ucits_daily_nav.json")
        except Exception as e:
            print(f"  WARN ucits_daily_nav: {e}")

    if not fund_navs and FUND_NAV_FILE.exists():
        legacy = json.load(open(FUND_NAV_FILE, encoding="utf-8")).get("navs", {})
        fund_navs.update(legacy)
        print(f"  Fallback: {len(fund_navs)} NAVs desde fi_fund_nav.json (legacy)")

    if not fund_navs:
        print("  WARN: sin NAVs FI (ucits_daily_nav.json y fi_fund_nav.json vacios). Se mantiene mensual.")
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
        f"Pesos y MV releidos de {race.get('_weights_source', 'n/d')}; "
        f"metricas (ytw/duration/maturity/rating) de data/funds/<TICKER>.json. "
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
