"""
Transform: positions.json + pnl.json + bench indices + race -> canonical/holdings_returns.json

Metodología (Jul-2026, decidida por Lucas):
- **Holding SI return**: Pershing UGL (MWR: gl/cost). Match por CUSIP en pnl.json.
- **Holding YTD return**: PRICE return desde 31-Dic-2025 (source: equity_race.json /
  fi_race.json, ya calculado por scripts/equity_race_baha.py + fi_race_baha.py).
- **Bench SI return**: PRICE return simple desde primera compra del activo
  (price_today / price_at_first_buy - 1). NO dollar-weighted.
- **Bench YTD return**: PRICE return simple desde 31-Dic-2025 hasta hoy.
- **Alpha SI/YTD**: return_holding - return_bench.

Sources:
- data/canonical/YYYY-MM-DD/positions.json  (holdings actuales con ISIN + MV)
- data/canonical/YYYY-MM-DD/pnl.json         (taxlots UGL Pershing agrupables)
- data/holdings_returns_equity.json          (legacy — solo para buys_history histórico)
- data/holdings_returns_fixed_income.json    (idem)
- data/holdings_returns_alternatives.json    (idem)
- data/equity_bench_indices.json             (ACWI daily prices)
- data/fi_bench_indices.json                 (AGG daily prices)
- data/equity_race.json                      (holdings SI/YTD price-based via baha/yfinance)
- data/fi_race.json                          (idem)

Output:
- data/canonical/YYYY-MM-DD/holdings_returns.json — single file con equity + fi + alts,
  con MV/return correctos por holding + bench price-based por período.

Notas:
- Para holdings que no están en race (alts como CALP, HLEND, IBIT), fallback a método
  legacy dollar-weighted en Bench SI y YTD None (no anchor disponible).
"""
from __future__ import annotations
import argparse
import json
from datetime import date, datetime
from pathlib import Path

from dashboard_v2.canonical.schemas import SCHEMA_VERSION
from dashboard_v2.transform._common import ROOT, utc_now_iso, relpath_from_root

DATA_DIR = ROOT / "data"
CANONICAL_DIR = DATA_DIR / "canonical"

YTD_ANCHOR = "2026-01-01"


def _load_bench_prices(path: Path, ticker: str) -> dict[str, float]:
    """
    Retorna dict {YYYY-MM-DD: price} para el ticker del bench.
    equity_bench_indices.json: {indices: {ACWI: {series: [{date, price, index}]}}}
    fi_bench_indices.json:     idem con AGG.
    """
    if not path.exists():
        return {}
    d = json.load(open(path, encoding='utf-8'))
    idx = d.get("indices", {}).get(ticker, {})
    series = idx.get("series", [])
    return {pt["date"]: float(pt["price"]) for pt in series if pt.get("date") and pt.get("price") is not None}


def _price_on_or_before(prices: dict, target_date: str) -> float | None:
    """Forward-fill: retorna el price en target_date o el último día hábil previo."""
    if not prices or not target_date:
        return None
    dates = sorted(prices.keys())
    prev = None
    for d in dates:
        if d > target_date:
            return prev
        prev = prices[d]
    return prev


def _agg_by_security(pnl_data: dict) -> dict:
    """Agrupa taxlots UGL por security_id. Separa pre-YTD y YTD para MWR YTD.
    Retorna dict{security_id: {
        qty, cost, mv, gl,          # totales
        buys,                       # todos los buys (para Bench DW SI)
        cost_pre_ytd, buys_ytd      # separados para MWR YTD:
                                    #   cost_pre_ytd = cost basis capital comprometido antes del 2026-01-01
                                    #   buys_ytd = list de {date, cost} de compras del año 2026
    }}
    """
    out = {}
    for t in pnl_data.get("unrealized", []):
        # Indexar por CUSIP (matchea entre positions y pnl). Fallback a security_id.
        key = t.get("cusip") or t.get("security_id")
        if not key:
            continue
        if key not in out:
            out[key] = {"qty": 0.0, "cost": 0.0, "mv": 0.0, "gl": 0.0,
                        "buys": [], "cost_pre_ytd": 0.0, "buys_ytd": []}
        out[key]["qty"] += t.get("quantity", 0) or 0
        out[key]["cost"] += t.get("current_total_cost", 0) or 0
        out[key]["mv"] += t.get("market_value", 0) or 0
        out[key]["gl"] += t.get("gain_loss", 0) or 0
        ed = t.get("entry_date")
        tc = t.get("current_total_cost")
        if ed and tc and tc > 0:
            out[key]["buys"].append({"date": ed, "cost": float(tc)})
            # Split pre-YTD / YTD
            if ed >= YTD_ANCHOR:
                out[key]["buys_ytd"].append({"date": ed, "cost": float(tc)})
            else:
                out[key]["cost_pre_ytd"] += float(tc)
    return out


def _find_position(positions_data: dict, ticker_or_name: str, isin: str = None) -> dict | None:
    """Buscar en positions.holdings por ISIN primero, después por description substring largo.
    Nota: usamos 40 chars mínimo para evitar false matches
    (ej: NBPEA "NEUBERGER BERMAN GLOBAL PRIVATE EQUITY" vs
         NBGMT "NEUBERGER BERMAN GLOBAL EQUITY MEGATRENDS" — coinciden los primeros 22 chars).
    """
    for h in positions_data.get("holdings", []):
        if isin and h.get("isin") == isin:
            return h
    # Fallback: substring largo (40 chars) para evitar falsos positivos
    if ticker_or_name:
        name_up = ticker_or_name.upper().strip()
        # 40 chars, o el nombre completo si es más corto
        n = name_up[:40] if len(name_up) >= 40 else name_up
        for h in positions_data.get("holdings", []):
            if n in (h.get("description") or "").upper():
                return h
    return None


def _compute_bench_dw(buys: list[dict], bench_prices: dict, mv_today: float) -> tuple[float, float]:
    """
    Bench dollar-weighted return: si hubiera comprado el bench en las mismas fechas y USD
    que los buys, cuánto valdría hoy y cuál es el return.
    Returns (return_pct, bench_mv_today).
    """
    if not buys or not bench_prices:
        return None, None

    # Precio bench hoy = último precio disponible
    dates_sorted = sorted(bench_prices.keys())
    bench_today_price = bench_prices[dates_sorted[-1]]

    # Para cada buy: shares sintéticas = cost_usd / bench_price_on_date
    total_cost = 0
    total_shares_synthetic = 0
    for b in buys:
        d = b.get("date")
        cost = b.get("cost", 0) or 0
        if not d or cost <= 0:
            continue
        p = _price_on_or_before(bench_prices, d)
        if p is None or p <= 0:
            continue
        total_shares_synthetic += cost / p
        total_cost += cost

    if total_cost <= 0 or total_shares_synthetic <= 0:
        return None, None

    bench_mv_today = total_shares_synthetic * bench_today_price
    bench_return_pct = (bench_mv_today / total_cost - 1) * 100
    return round(bench_return_pct, 2), round(bench_mv_today, 2)


def _compute_bench_price_return(bench_prices: dict, anchor_date: str) -> float | None:
    """
    Price return simple: (price_today / price_at_anchor) - 1.
    Retorna % o None si falta data.
    Si anchor_date es previa al inicio de la serie (ej: activo comprado 2025-07-07
    pero ACWI series arranca 2025-07-31), usa la primera fecha disponible.
    """
    if not bench_prices or not anchor_date:
        return None
    dates_sorted = sorted(bench_prices.keys())
    if not dates_sorted:
        return None
    price_today = bench_prices[dates_sorted[-1]]
    price_anchor = _price_on_or_before(bench_prices, anchor_date)
    # Fallback: si anchor previa a la serie, usar primer precio disponible
    if price_anchor is None and anchor_date < dates_sorted[0]:
        price_anchor = bench_prices[dates_sorted[0]]
    if price_anchor is None or price_anchor <= 0 or price_today is None:
        return None
    return round((price_today / price_anchor - 1) * 100, 2)


def build_holding(h_legacy: dict, positions_data: dict, pnl_agg: dict,
                  bench_prices: dict, v0_by_isin: dict, bench_label: str,
                  race_by_isin: dict) -> dict:
    """Calcula UN holding.
    - MV/cost/return_pct (SI): Pershing UGL (MWR gl/cost).
    - ytd_pct: price return desde 31-Dic-25 (source: race_by_isin[isin].ytd_return_pct).
    - bench_dw_pct (Bench SI): price return desde primera compra del activo.
    - bench_ytd_pct: price return desde 31-Dic-25 hasta hoy.
    Fallback a métodos legacy si el ISIN no está en race (alts).
    v0_by_isin: dict {isin: mv_2025_dec_31} para MWR YTD real cuando NO tenemos race YTD."""
    ticker = h_legacy.get("ticker") or ""
    name = (h_legacy.get("name") or "").strip()
    # NOTA: NO heredamos status del legacy — el script viejo tiene bugs
    # (ej: PIMCO-INC marcado CLOSED aunque tenga MV en positions).
    # Status lo derivamos abajo desde positions (fuente de verdad).
    buys = h_legacy.get("buys_history", []) or []

    # ISIN puede estar en el name (ISIN#XXX) o inferido del ticker
    isin = None
    name_upper = name.upper()
    if "ISIN#" in name_upper:
        idx = name_upper.find("ISIN#")
        isin_candidate = name_upper[idx + 5:idx + 17].strip()
        if len(isin_candidate) == 12 and isin_candidate[:2].isalpha():
            isin = isin_candidate

    # Match en positions (fuente de verdad para MV/cost + status)
    pos = _find_position(positions_data, name, isin)
    if pos is None:
        # NO esta en positions -> holding CLOSED de verdad, o legacy stale sin match
        mv = h_legacy.get("mv_usd")
        cost = h_legacy.get("cost_basis_usd")
        gl = h_legacy.get("unrealized_gl_usd")
        return_pct = h_legacy.get("return_pct")
        qty = h_legacy.get("qty")
        source_note = "legacy_fallback"
        # CLOSED de verdad (no lo tiene el portfolio)
        status = "CLOSED"
    else:
        # Match en pnl_agg por CUSIP (que sí matchea entre positions y pnl)
        # security_id de positions puede diferir del de pnl (ej: CSPX:GB vs CSTNL)
        cusip = pos.get("cusip")
        sid = pos.get("security_id")
        agg = pnl_agg.get(cusip, {}) if cusip else {}
        if not agg:
            agg = pnl_agg.get(sid, {})
        mv = pos.get("market_value_usd") or agg.get("mv") or h_legacy.get("mv_usd")
        cost = agg.get("cost") or h_legacy.get("cost_basis_usd")
        gl = agg.get("gl") or (mv - cost if (mv and cost) else h_legacy.get("unrealized_gl_usd"))
        return_pct = round((gl / cost) * 100, 2) if (gl is not None and cost and cost > 0) else h_legacy.get("return_pct")
        qty = pos.get("quantity") or agg.get("qty") or h_legacy.get("qty")
        source_note = "pershing_ugl"
        # SI aparece en positions con MV > 0 -> OPEN (ignora status del legacy que puede estar mal)
        status = "OPEN" if (mv or 0) > 0 else "CLOSED"
        # Si legacy no tiene buys_history (viene CLOSED sin history), reconstruir desde taxlots UGL
        if not buys and agg.get("buys"):
            buys = sorted(agg["buys"], key=lambda b: b["date"])
        # ISIN de positions es fuente de verdad (legacy puede tenerlo None)
        if pos.get("isin"):
            isin = pos.get("isin")

    # ===== Bench SI (Jul-2026: PRICE return desde primera compra) =====
    # Nueva metodología (Lucas Jul-2026): NO dollar-weighted. Simple buy-and-hold del bench
    # desde el first_buy_date del activo.
    #   bench_si_pct = (price_today / price_at_first_buy) - 1
    # first_buy_date sale de buys_history legacy o del primer taxlot en pnl (fallback).
    first_buy_date = h_legacy.get("first_buy_date")
    if not first_buy_date and buys:
        first_buy_date = min((b["date"] for b in buys if b.get("date")), default=None)
    bench_dw_pct = _compute_bench_price_return(bench_prices, first_buy_date) if first_buy_date else None
    alpha_real_pp = (
        round(return_pct - bench_dw_pct, 2)
        if (return_pct is not None and bench_dw_pct is not None)
        else None
    )

    # ===== Holding YTD (Jul-2026: PRICE return desde 31-Dic-25) =====
    # Source primaria: equity_race.json / fi_race.json (baha/yfinance price series).
    # Fallback: MWR YTD (Simple Dietz con V0 anchor) — solo si no está en race.
    ytd_pct = None
    bench_ytd_dw_pct = None
    alpha_ytd_pp = None

    race_h = race_by_isin.get(isin) if isin else None
    if race_h is not None and race_h.get("ytd_return_pct") is not None:
        ytd_pct = round(float(race_h["ytd_return_pct"]), 2)
    elif pos and agg:
        cost_pre_ytd = agg.get("cost_pre_ytd", 0) or 0
        buys_ytd_list = agg.get("buys_ytd", [])
        buys_ytd_total = sum(b["cost"] for b in buys_ytd_list)
        has_pre_ytd_position = cost_pre_ytd > 0
        has_anchor = isin in v0_by_isin if isin else False
        if has_pre_ytd_position and not has_anchor:
            v0_real = None
            capital_ytd = 0
        else:
            v0_real = v0_by_isin.get(isin, 0) if isin else 0
            capital_ytd = v0_real + buys_ytd_total
        if capital_ytd > 0 and mv is not None:
            ytd_pct = round((mv - v0_real - buys_ytd_total) / capital_ytd * 100, 2)

    # ===== Bench YTD (Jul-2026: PRICE return desde 31-Dic-25) =====
    bench_ytd_dw_pct = _compute_bench_price_return(bench_prices, "2025-12-31")

    if ytd_pct is not None and bench_ytd_dw_pct is not None:
        alpha_ytd_pp = round(ytd_pct - bench_ytd_dw_pct, 2)

    return {
        "ticker": ticker,
        "name": name,
        "isin": isin,
        "status": status,
        "qty": qty,
        "mv_usd": round(mv, 2) if mv is not None else None,
        "cost_basis_usd": round(cost, 2) if cost is not None else None,
        "unrealized_gl_usd": round(gl, 2) if gl is not None else None,
        "return_pct": return_pct,
        "bench_label": bench_label,
        "bench_dw_pct": bench_dw_pct,
        "alpha_real_pp": alpha_real_pp,
        "ytd_pct": ytd_pct,
        "bench_ytd_pct": bench_ytd_dw_pct,
        "alpha_ytd_pp": alpha_ytd_pp,
        "first_buy_date": h_legacy.get("first_buy_date"),
        "n_trades": h_legacy.get("n_trades"),
        "buys_history": buys,
        "_mv_source": source_note,
    }


def _load_year_start_anchors() -> dict:
    """Retorna dict {isin: mv_2025_dec_31} para MWR YTD real cuando anchor está disponible."""
    p = DATA_DIR / "year_start_anchors.json"
    if not p.exists():
        return {}
    ya = json.load(open(p, encoding='utf-8'))
    anchors = ya.get('anchors_2026', {})
    out = {}
    for isin, v in anchors.items():
        mv = v.get('mv_2025_dec_31')
        if mv is not None:
            out[isin] = float(mv)
    return out


def _load_race_by_isin(path: Path) -> dict:
    """Retorna dict {isin: {si_return_pct, ytd_return_pct, first_buy_date, source}}
    desde equity_race.json / fi_race.json (source: baha/yfinance price series)."""
    if not path.exists():
        return {}
    try:
        d = json.load(open(path, encoding='utf-8'))
    except Exception:
        return {}
    out = {}
    for h in d.get("holdings", []) or []:
        isin = h.get("isin")
        if not isin:
            continue
        out[isin] = {
            "si_return_pct": h.get("si_return_pct"),
            "ytd_return_pct": h.get("ytd_return_pct"),
            "first_buy_date": h.get("first_buy_date"),
            "source": h.get("source"),
        }
    return out


def build(as_of: str) -> dict:
    # Load canonical v2
    with open(CANONICAL_DIR / as_of / "positions.json", encoding='utf-8') as f:
        positions = json.load(f)
    with open(CANONICAL_DIR / as_of / "pnl.json", encoding='utf-8') as f:
        pnl = json.load(f)
    pnl_agg = _agg_by_security(pnl)
    v0_by_isin = _load_year_start_anchors()

    # Race JSONs (SI/YTD price-based por ISIN) — Jul-2026 nueva metodología
    equity_race = _load_race_by_isin(DATA_DIR / "equity_race.json")
    fi_race = _load_race_by_isin(DATA_DIR / "fi_race.json")

    # Load legacy (solo para buys_history histórico — TODO: migrar)
    # 4to elemento: race dict por sleeve (alts no tiene race, dict vacío)
    hr_files = {
        "equity":       (DATA_DIR / "holdings_returns_equity.json", "ACWI",
                         DATA_DIR / "equity_bench_indices.json", equity_race),
        "fixed_income": (DATA_DIR / "holdings_returns_fixed_income.json", "AGG",
                         DATA_DIR / "fi_bench_indices.json", fi_race),
        "alternatives": (DATA_DIR / "holdings_returns_alternatives.json", "ACWI",
                         DATA_DIR / "equity_bench_indices.json", {}),
    }

    out = {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "generated_at": utc_now_iso(),
        "note": "Holdings con MV/return DIRECTO de Pershing UGL (canonical v2 pnl.json). Bench DW calculado desde buys_history + bench indices. Fixes bug de precio staleado del compute_holdings_returns.py viejo.",
        "sources": {
            "positions": relpath_from_root(CANONICAL_DIR / as_of / "positions.json"),
            "pnl":       relpath_from_root(CANONICAL_DIR / as_of / "pnl.json"),
        },
        "sleeves": {},
    }

    for sleeve_key, (hr_path, bench_label, bench_path, race_by_isin) in hr_files.items():
        if not hr_path.exists():
            out["sleeves"][sleeve_key] = {"holdings": [], "error": f"{hr_path.name} no existe"}
            continue

        hr = json.load(open(hr_path, encoding='utf-8'))
        bench_prices = _load_bench_prices(bench_path, bench_label)

        holdings_out = []
        for h_legacy in hr.get("holdings", []):
            # NO filtrar por status legacy — puede estar mal (ej: PIMCO-INC marcado CLOSED
            # pero está en portfolio). El status real lo determina build_holding via positions.
            hr_out = build_holding(h_legacy, positions, pnl_agg,
                                   bench_prices, v0_by_isin, bench_label,
                                   race_by_isin)
            # Solo incluimos OPEN (los CLOSED reales quedan fuera del widget)
            if hr_out.get("status") == "OPEN":
                holdings_out.append(hr_out)

        # Merge EXTERNAL holdings (data manual desde statements — no en Pershing UGL)
        # Ejemplo: CALP (Carlyle) viene con statement directo del manager.
        ext_path = DATA_DIR / "alts_external.json"
        if ext_path.exists():
            ext = json.load(open(ext_path, encoding='utf-8'))
            for eh in ext.get("holdings", []):
                if eh.get("sleeve") != sleeve_key:
                    continue
                # Ya está en holdings_out? Skip (Pershing UGL tiene prioridad si aparece)
                if any(h.get("isin") == eh.get("isin") for h in holdings_out if h.get("isin")):
                    continue
                # Calcular Bench SI (price return desde first_buy) + Bench YTD (desde 31-Dic-25)
                buys = eh.get("buys_history") or []
                first_buy_date = eh.get("first_buy_date")
                if not first_buy_date and buys:
                    first_buy_date = min((b["date"] for b in buys if b.get("date")), default=None)
                bench_dw_pct = _compute_bench_price_return(bench_prices, first_buy_date) if first_buy_date else None
                alpha_real_pp = None
                if eh.get("return_pct") is not None and bench_dw_pct is not None:
                    alpha_real_pp = round(eh["return_pct"] - bench_dw_pct, 2)
                bench_ytd_pct = _compute_bench_price_return(bench_prices, "2025-12-31")
                alpha_ytd_pp = None
                if eh.get("ytd_pct") is not None and bench_ytd_pct is not None:
                    alpha_ytd_pp = round(eh["ytd_pct"] - bench_ytd_pct, 2)
                holdings_out.append({
                    "ticker": eh.get("ticker"),
                    "name": eh.get("name"),
                    "isin": eh.get("isin"),
                    "status": "OPEN",
                    "qty": eh.get("qty"),
                    "mv_usd": eh.get("mv_usd"),
                    "cost_basis_usd": eh.get("cost_basis_usd"),
                    "unrealized_gl_usd": eh.get("unrealized_gl_usd"),
                    "return_pct": eh.get("return_pct"),
                    "bench_label": bench_label,
                    "bench_dw_pct": bench_dw_pct,
                    "alpha_real_pp": alpha_real_pp,
                    "ytd_pct": eh.get("ytd_pct"),
                    "bench_ytd_pct": bench_ytd_pct,
                    "alpha_ytd_pp": alpha_ytd_pp,
                    "first_buy_date": first_buy_date,
                    "buys_history": buys,
                    "_mv_source": "external_statement",
                    "_source_note": eh.get("source"),
                    "_as_of": eh.get("as_of"),
                })

        # Sort by MV desc
        holdings_out.sort(key=lambda h: h.get("mv_usd") or 0, reverse=True)

        out["sleeves"][sleeve_key] = {
            "bench_label": bench_label,
            "n_open": len(holdings_out),
            "holdings": holdings_out,
        }

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="Snapshot date YYYY-MM-DD. Default: hoy.")
    args = ap.parse_args()

    target = args.date or date.today().isoformat()

    print(f"\n{'=' * 70}")
    print(f"  Build holdings_returns.json for {target}")
    print(f"{'=' * 70}\n")

    result = build(target)
    out_dir = CANONICAL_DIR / target
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "holdings_returns.json"
    with open(out_path, "w", encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Output: {out_path} ({out_path.stat().st_size:,} bytes)\n")

    for skey, sdata in result["sleeves"].items():
        print(f"=== {skey} ({sdata.get('bench_label', '')}) — {sdata.get('n_open', 0)} holdings ===")
        for h in (sdata.get("holdings") or [])[:5]:
            ret = h.get("return_pct")
            bdw = h.get("bench_dw_pct")
            alpha = h.get("alpha_real_pp")
            def _fmt(v, suf="%"): return f"{v:+.2f}{suf}" if v is not None else "N/A"
            def _fmt_bp(v): return f"{v*100:+.0f} bp" if v is not None else "N/A"
            print(f"  {h['ticker']:10s} MV=${h['mv_usd']:>12,.0f}  ret={_fmt(ret):>8s}  bench_dw={_fmt(bdw):>8s}  alpha={_fmt_bp(alpha):>10s}  src={h.get('_mv_source')}")
        print()


if __name__ == "__main__":
    main()
