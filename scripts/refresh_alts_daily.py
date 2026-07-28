"""
refresh_alts_daily.py
=====================
Refresh diario del sleeve Alts. Cron-friendly.

Diferencias clave vs refresh_equity_daily.py / refresh_fi_daily.py:
- Alts vive en alts_race.json (no en *_sleeve_real.json).
- IBIT, GLD: precio T-1 real via Pershing/NetX360 (canonical positions.json),
  MISMO feed que el resto del universo BIG. (FIX 2026-07-28: antes usaban
  Stooq via live_prices.json, un feed distinto al canonical -- Lucas:
  "quiero que este todo con Pershing", esto generaba 2 numeros de sleeve YTD
  ligeramente distintos entre alts_race.json y el dashboard.)
- BPCC tiene precio T-1 desde Pershing pero no se mueve diariamente sin
  re-importar el Excel -> se mantiene como last-known.
- HLEND, GCRED, FLEX, HLGPI = illiquidos puros -> carry-forward del ultimo
  statement / Pershing price.
- CALP = external -> lee alts_carlyle_statement.json (statement mas reciente).
- NBPEA = sold (qty 0) -> se mantiene como holding cerrado pero excluido del
  total activo.

Que actualiza en alts_race.json:
  - holdings[*].value_usd      (solo liquidos T-1)
  - holdings[*].valuation_date (solo liquidos -> hoy del Stooq cierre)
  - holdings[*].weight_pct     (recalc para todos los activos)
  - holdings[*].days_since_valuation  (nuevo campo, alimenta freshness panel)
  - refreshedAt
  - _daily_refresh_note

NO toca: sleeve_index (mensual), sleeve_monthly_returns, portfolio_metrics,
ytd_return_pct, si_return_pct (esos vienen de statements).

Usage:
    python refresh_alts_daily.py
"""

import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
ALTS_FILE = ROOT / "data" / "alts_race.json"
POSITIONS_FILE = ROOT / "data" / "positions_latest.json"
CANONICAL_DIR = ROOT / "data" / "canonical"
YEAR_START_ANCHORS_FILE = ROOT / "data" / "year_start_anchors.json"
CARLYLE_FILE = ROOT / "data" / "alts_carlyle_statement.json"
ICAPITAL_FILE = ROOT / "data" / "alts_icapital_statements.json"
BPCC_FILE = ROOT / "data" / "alts_bpcc_statement.json"


def latest_canonical_positions():
    """Ultimo data/canonical/{date}/positions.json disponible (Pershing/NetX360)."""
    if not CANONICAL_DIR.exists():
        return None, None
    dates = sorted(p.name for p in CANONICAL_DIR.iterdir() if p.is_dir())
    for d in reversed(dates):
        f = CANONICAL_DIR / d / "positions.json"
        if f.exists():
            try:
                return json.load(open(f, encoding="utf-8")), d
            except Exception:
                continue
    return None, None


def load_pershing_liquid_prices():
    """{isin: {price, mv_usd, price_date}} para IBIT/GLD via canonical
    positions.json (mismo feed Pershing/NetX360 que el resto del universo)."""
    positions, snapshot_date = latest_canonical_positions()
    if positions is None:
        return {}
    out = {}
    for h in positions.get("holdings", []):
        isin = h.get("isin")
        if isin and h.get("market_price_ccy") and h.get("market_value_usd"):
            out[isin] = {
                "price": h["market_price_ccy"],
                "mv_usd": h["market_value_usd"],
                "price_date": h.get("price_date") or snapshot_date,
            }
    return out


def load_year_start_anchors():
    """{isin: price_2025_dec_31} para YTD spot real."""
    try:
        d = json.load(open(YEAR_START_ANCHORS_FILE, encoding="utf-8"))
        return {isin: v.get("price_2025_dec_31")
                for isin, v in d.get("anchors_2026", {}).items()}
    except Exception:
        return {}


def load_carlyle_latest():
    """Ultimo statement Carlyle por as_of. Devuelve dict {ticker:'CALP', mv,
    valuation_date, ytd, si} o None."""
    try:
        cs = json.load(open(CARLYLE_FILE, encoding="utf-8"))
    except Exception:
        return None
    statements = cs.get("statements", {}).get("CALP", [])
    if not statements:
        return None
    latest = max(statements, key=lambda s: s.get("as_of", ""))
    return {
        "ticker": "CALP",
        "mv_usd": latest.get("mv_usd"),
        "valuation_date": latest.get("as_of"),
        "ytd_return_pct": latest.get("ytd_return_pct"),
        "si_return_pct": latest.get("si_return_pct"),
    }


def load_icapital_latest():
    """Ultimo statement por holding del archivo iCapital (HLEND + GCRED).
    Devuelve dict {ticker: {mv_usd, valuation_date, ytd_return_pct, si_return_pct}} o {}."""
    try:
        cs = json.load(open(ICAPITAL_FILE, encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for ticker, statements in cs.get("statements", {}).items():
        if not statements:
            continue
        latest = max(statements, key=lambda s: s.get("as_of", ""))
        out[ticker] = {
            "mv_usd": latest.get("mv_usd"),
            "valuation_date": latest.get("as_of"),
            "ytd_return_pct": latest.get("ytd_return_pct"),
            "si_return_pct": latest.get("si_return_pct"),
            "nav_per_share": latest.get("nav_per_share"),
        }
    return out


def load_bpcc_latest():
    """Ultimo statement Pershing para BPCC (nota estructurada, precio
    per-100-face). Devuelve dict {mv_usd, valuation_date, ytd_return_pct} o
    None. SI NO se lee de aca -- se deja al calculo normal via Pershing UGL
    (cost-basis), porque hubo compras adicionales en distintos lotes/precios
    que un price-return simple no captura bien."""
    try:
        cs = json.load(open(BPCC_FILE, encoding="utf-8"))
    except Exception:
        return None
    statements = cs.get("statements", {}).get("BPCC", [])
    if not statements:
        return None
    latest = max(statements, key=lambda s: s.get("as_of", ""))
    return {
        "mv_usd": latest.get("mv_usd"),
        "valuation_date": latest.get("as_of"),
        "ytd_return_pct": latest.get("ytd_return_pct"),
    }


def days_between(iso_date, today_iso):
    """Dias entre iso_date y today_iso. None si iso_date invalido."""
    if not iso_date:
        return None
    try:
        d1 = datetime.fromisoformat(iso_date[:10])
        d2 = datetime.fromisoformat(today_iso)
        return (d2 - d1).days
    except Exception:
        return None


def main():
    today_iso = date.today().isoformat()
    print(f"[{datetime.now().isoformat()}] Refresh Alts daily ({today_iso})...")

    # Inputs
    pl = json.load(open(POSITIONS_FILE, encoding="utf-8"))
    alts_qty = {p["ticker"]: p for p in pl["positions"]
                if p["sleeve"] == "Alternatives"}
    pershing_liquid = load_pershing_liquid_prices()  # {isin: {price, mv_usd, price_date}}
    ytd_anchors = load_year_start_anchors()
    carlyle = load_carlyle_latest()
    icapital = load_icapital_latest()  # {HLEND: {...}, GCRED: {...}}
    bpcc = load_bpcc_latest()

    print(f"  Holdings Alts en positions: {len(alts_qty)}")
    print(f"  Pershing (canonical) precios disponibles: {len(pershing_liquid)}")
    if carlyle:
        print(f"  Carlyle (CALP) statement: {carlyle['valuation_date']} -> ${carlyle['mv_usd']:,.0f}")
    for tk, st in icapital.items():
        print(f"  iCapital ({tk}) statement: {st['valuation_date']} -> ${st['mv_usd']:,.0f}")
    if bpcc:
        print(f"  Pershing (BPCC) statement: {bpcc['valuation_date']} -> ${bpcc['mv_usd']:,.0f}")

    # Cargar alts_race.json
    ar = json.load(open(ALTS_FILE, encoding="utf-8"))

    sources_summary = {"daily_close_pershing": [], "pershing_last": [],
                       "carlyle_statement": [], "icapital_statement": [],
                       "frozen_statement": [],
                       "sold_skipped": [], "pending_confirm": []}

    for h in ar["holdings"]:
        tk = h["ticker"]

        # Sold (NBPEA) -> no toca, queda cerrado
        if h.get("status") == "sold":
            sources_summary["sold_skipped"].append(tk)
            h["days_since_valuation"] = None
            continue

        # Pending confirm (HLGPI) -> mantener
        if h.get("status") == "pending_confirm":
            h["days_since_valuation"] = days_between(
                h.get("valuation_date"), today_iso)
            sources_summary["pending_confirm"].append(tk)
            continue

        # CALP -> external (Carlyle statement)
        if tk == "CALP" and carlyle:
            h["value_usd"] = round(carlyle["mv_usd"], 2)
            h["valuation_date"] = carlyle["valuation_date"]
            if carlyle.get("ytd_return_pct") is not None:
                h["ytd_return_pct"] = carlyle["ytd_return_pct"]
            if carlyle.get("si_return_pct") is not None:
                h["si_return_pct"] = carlyle["si_return_pct"]
            h["source"] = f"Carlyle statement ({carlyle['valuation_date']})"
            h["days_since_valuation"] = days_between(
                carlyle["valuation_date"], today_iso)
            sources_summary["carlyle_statement"].append(tk)
            continue

        # HLEND, GCRED -> iCapital statements (manager NAV via BNY)
        if tk in icapital:
            st = icapital[tk]
            h["value_usd"] = round(st["mv_usd"], 2)
            h["valuation_date"] = st["valuation_date"]
            if st.get("ytd_return_pct") is not None:
                h["ytd_return_pct"] = st["ytd_return_pct"]
            # SI: si el statement lo trae, usarlo; sino, marcar None (N/A en dashboard)
            if st.get("si_return_pct") is not None:
                h["si_return_pct"] = st["si_return_pct"]
            h["source"] = f"iCapital statement ({st['valuation_date']})"
            h["days_since_valuation"] = days_between(
                st["valuation_date"], today_iso)
            sources_summary["icapital_statement"].append(tk)
            continue

        # BPCC -> statement Pershing real (nota per-100-face). Reemplaza el
        # carry estimado sintetico (9.4%/yr) por price return real desde el
        # anchor 31-Dic-2025 (ver alts_bpcc_statement.json).
        if tk == "BPCC" and bpcc:
            h["value_usd"] = round(bpcc["mv_usd"], 2)
            h["valuation_date"] = bpcc["valuation_date"]
            if bpcc.get("ytd_return_pct") is not None:
                h["ytd_return_pct"] = bpcc["ytd_return_pct"]
            # SI se deja sin tocar -> lo completa sync_alts_ugl.py con Pershing
            # UGL (cost-basis), correcto porque hubo compras en distintos lotes.
            h["source"] = f"Pershing statement ({bpcc['valuation_date']})"
            h["days_since_valuation"] = days_between(
                bpcc["valuation_date"], today_iso)
            sources_summary["icapital_statement"].append(tk)
            continue

        # Holding liquido (IBIT, GLD): precio T-1 real via Pershing/NetX360
        # (canonical positions.json) -> recalc MV + YTD spot desde anchor real.
        # FIX 2026-07-28: antes usaba Stooq (live_prices.json) + anchor
        # yfinance, un feed distinto al resto del universo BIG. Ahora mismo
        # feed Pershing que todo lo demas + anchor real ya locked.
        pos = alts_qty.get(tk)
        isin = h.get("isin")
        if tk in ("IBIT", "GLD") and isin and isin in pershing_liquid:
            pl_rec = pershing_liquid[isin]
            h["value_usd"] = round(pl_rec["mv_usd"], 2)
            h["valuation_date"] = pl_rec["price_date"] or today_iso
            h["source"] = f"Pershing T-1 ({pl_rec['price_date'] or today_iso})"
            h["days_since_valuation"] = days_between(
                h["valuation_date"], today_iso)
            anchor = ytd_anchors.get(isin)
            if anchor:
                ytd_spot = round((pl_rec["price"] / anchor - 1) * 100, 2)
                old_ytd = h.get("ytd_return_pct")
                h["ytd_return_pct"] = ytd_spot
                if old_ytd is not None and abs(old_ytd - ytd_spot) > 0.5:
                    print(f"  [ytd_spot Pershing] {tk}: {old_ytd:+.2f}% -> {ytd_spot:+.2f}%")
            sources_summary["daily_close_pershing"].append(tk)
            continue

        # Holding con valor en Pershing pero sin feed diario propio (FLEX, HLGPI)
        # -> usar value de positions_latest.json (que es T-1 de Pershing)
        if pos and pos.get("value") and pos.get("price_as_of"):
            h["value_usd"] = round(pos["value"], 2)
            h["valuation_date"] = pos["price_as_of"]
            # 2026-06-10: FLEX y HLGPI entraron Mayo-2026, sin valuation oficial
            # todavia (privados reportan trimestral/semi-anual). Lucas confirma 0%.
            if tk in ("FLEX", "HLGPI"):
                h["source"] = f"Entrada {tk} mayo-2026, sin valuation oficial aun (0%)"
                h["ytd_return_pct"] = 0.0
                h["si_return_pct"] = 0.0
            else:
                # Otros pending statement
                h["source"] = f"Pershing T-1 ({pos['price_as_of']}) - SI/YTD pending statement"
                h["ytd_return_pct"] = None
                h["si_return_pct"] = None
            h["days_since_valuation"] = days_between(
                h["valuation_date"], today_iso)
            sources_summary["pershing_last"].append(tk)
            continue

        # Illiquido puro: NO hay precio diario ni Pershing T-1 -> carry-forward
        # Idem: marcar YTD/SI como None hasta tener statement
        h["days_since_valuation"] = days_between(
            h.get("valuation_date"), today_iso)
        h["ytd_return_pct"] = None
        h["si_return_pct"] = None
        sources_summary["frozen_statement"].append(tk)

    # Recalc weights con el nuevo total activo
    active = [h for h in ar["holdings"] if h.get("status") != "sold"]
    total_active = sum(h["value_usd"] for h in active)
    for h in ar["holdings"]:
        if h.get("status") == "sold":
            h["weight_pct"] = 0.0
        else:
            h["weight_pct"] = round(h["value_usd"] / total_active * 100, 2)

    # Recalcular YTD del sleeve via weighted holding contribution real (de statements).
    # Esto sobreescribe el sleeve_index proxy que tenia spikes irreales (-5%/+5%
    # mensuales que no reflejan el comportamiento de illiquidos PE/PC).
    # Source of truth: statements (Carlyle + iCapital) + live prices (IBIT/GLD/BPCC).
    #
    # NOTA: 1M/3M/6M y SI se mantienen del sleeve_index proxy (a pesar de ser
    # imperfectos). Para fixearlos hay que reconstruir el sleeve_index mensual desde
    # los monthly returns por holding -- en el roadmap pero requiere historial MV
    # por holding (que no tenemos pre-Q1 2026 para todos).
    ytd_weighted = sum(
        (h["value_usd"] / total_active) * (h.get("ytd_return_pct") or 0)
        for h in active
    )
    stats = ar.setdefault("stats_vs_6040", {})
    returns = stats.setdefault("returns", {})
    returns.setdefault("YTD", {})["sleeve"] = round(ytd_weighted, 2)

    ar["refreshedAt"] = datetime.now().isoformat()
    ar["_daily_refresh_note"] = (
        f"Refresh diario {today_iso}: "
        f"{len(sources_summary['daily_close_pershing'])} liquidos via Pershing T-1, "
        f"{len(sources_summary['pershing_last'])} via Pershing T-1, "
        f"{len(sources_summary['carlyle_statement'])} via Carlyle statement, "
        f"{len(sources_summary['frozen_statement'])} frozen statement. "
        f"Total activo: ${total_active:,.0f}."
    )

    with open(ALTS_FILE, "w", encoding="utf-8") as f:
        json.dump(ar, f, indent=2, ensure_ascii=False)

    # Log
    print(f"\n  Fuentes por holding:")
    for src, tks in sources_summary.items():
        if tks:
            print(f"    {src:<22} {tks}")
    print(f"\n  Total Alts activo: ${total_active:,.0f}")
    print(f"  Saved: {ALTS_FILE}")


if __name__ == "__main__":
    main()
