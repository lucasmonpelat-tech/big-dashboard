"""
compute_attribution.py
======================
Computa la atribucion YTD del fondo BIG: peso x retorno por sleeve.

Output: data/attribution_ytd.json

Logica:
- Equity YTD: equity_sleeve_real.json twr_series (last index / Dec-31 index - 1)
- FI YTD:     fi_sleeve_real.json idem
- Alts YTD:   sum(holding_value * holding_ytd_pct) / sum(holding_value)
              de alts_race.json (real statements, no proxies)
- Cash YTD:   SOFR proxy ~5.3%/yr pro-rated por days_ytd
- Weights:    positions_latest.json (sleeve_value / total_aum)
- Gross:      sum(w * r)
- Net:        Gross - mgmt_fee_1.8%_pro_rated
- Lynk YTD:   lynk_data.json (oficial)
- Residual:   Net - Lynk YTD

Si residuo > 50bp en magnitud, hay algo mal con los inputs.

Cron: corre despues de refresh_equity/fi/alts_daily.

Usage:
    python compute_attribution.py
"""
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUTPUT = ROOT / "data" / "attribution_ytd.json"

YTD_ANCHOR = "2025-12-31"
SOFR_RATE_ANNUAL = 5.3        # cash yield approx (SOFR-ish)
MGMT_FEE_ANNUAL = 1.8         # Lynk management fee (Lucas confirmed)


def load_json(path):
    return json.load(open(path, encoding="utf-8"))


def get_index(series, dt):
    for p in series:
        if p["date"] == dt:
            return p["index"]
    return None


def main():
    today = date.today()
    today_iso = today.isoformat()
    ytd_anchor_dt = date.fromisoformat(YTD_ANCHOR)
    days_ytd = (today - ytd_anchor_dt).days

    # ============ Equity YTD ============
    eq = load_json(ROOT / "data" / "equity_sleeve_real.json")["twr_series"]
    eq_anchor = get_index(eq, YTD_ANCHOR)
    eq_ytd = (eq[-1]["index"] / eq_anchor - 1) * 100 if eq_anchor else None

    # ============ FI YTD ============
    fi = load_json(ROOT / "data" / "fi_sleeve_real.json")["twr_series"]
    fi_anchor = get_index(fi, YTD_ANCHOR)
    fi_ytd = (fi[-1]["index"] / fi_anchor - 1) * 100 if fi_anchor else None

    # ============ Alts YTD (weighted holdings) ============
    ar = load_json(ROOT / "data" / "alts_race.json")
    holdings = [h for h in ar["holdings"] if h.get("status") != "sold"]
    total_alts_mv = sum(h["value_usd"] for h in holdings)

    alts_detail = []
    for h in sorted(holdings, key=lambda x: -x["value_usd"]):
        w = h["value_usd"] / total_alts_mv * 100
        ytd = h.get("ytd_return_pct") or 0
        contrib_pp = w * ytd / 100
        alts_detail.append({
            "ticker": h["ticker"],
            "name": h.get("name", h["ticker"]),
            "value_usd": h["value_usd"],
            "weight_pct": round(w, 2),
            "ytd_pct": round(ytd, 2) if ytd is not None else None,
            "contribution_pp": round(contrib_pp, 3),
            "source": h.get("source", "")[:60],
            "valuation_date": h.get("valuation_date", ""),
        })

    alts_ytd = sum(d["contribution_pp"] for d in alts_detail)

    # ============ Cash YTD ============
    cash_ytd = SOFR_RATE_ANNUAL * days_ytd / 365

    # ============ Weights — positions_latest ============
    pl = load_json(ROOT / "data" / "positions_latest.json")
    total_aum = pl["total_aum"]
    sleeve_mv = {}
    for s in ["Equity", "Fixed Income", "Alternatives", "Cash"]:
        sleeve_mv[s] = sum(
            p["value"] for p in pl["positions"]
            if p["sleeve"] == s and p.get("status") != "sold"
        )

    sleeves = []
    sleeve_specs = [
        ("Equity", eq_ytd),
        ("Fixed Income", fi_ytd),
        ("Alternatives", alts_ytd),
        ("Cash", cash_ytd),
    ]
    for name, ytd_pct in sleeve_specs:
        w_pct = sleeve_mv[name] / total_aum * 100
        contrib = w_pct * ytd_pct / 100
        sleeves.append({
            "name": name,
            "value_usd": round(sleeve_mv[name], 2),
            "weight_pct": round(w_pct, 2),
            "ytd_pct": round(ytd_pct, 2),
            "contribution_pp": round(contrib, 3),
        })

    gross_ytd = sum(s["contribution_pp"] for s in sleeves)
    mgmt_fee = MGMT_FEE_ANNUAL * days_ytd / 365
    net_reconstructed = gross_ytd - mgmt_fee

    # ============ Lynk YTD oficial ============
    ly = load_json(ROOT / "data" / "lynk_data.json")
    lynk_ytd = ly.get("returnYTD")
    lynk_refreshed = ly.get("refreshedAt", "")

    residual = (net_reconstructed - lynk_ytd) if lynk_ytd is not None else None

    # ============ Output ============
    out = {
        "_description": "Atribucion YTD del fondo BIG: peso x retorno por sleeve. Compara contra Lynk oficial. Residuo = inputs imperfectos (otros fees Lynk, alts data lag, cash approx).",
        "refreshedAt": datetime.now().isoformat(),
        "as_of_date": today_iso,
        "ytd_anchor": YTD_ANCHOR,
        "days_ytd": days_ytd,
        "sleeves": sleeves,
        "gross_reconstructed_pct": round(gross_ytd, 3),
        "mgmt_fee_pp": round(-mgmt_fee, 3),
        "mgmt_fee_rate_annual_pct": MGMT_FEE_ANNUAL,
        "net_reconstructed_pct": round(net_reconstructed, 3),
        "lynk_ytd_pct": lynk_ytd,
        "lynk_refreshed_at": lynk_refreshed,
        "residual_pp": round(residual, 3) if residual is not None else None,
        "alts_detail": alts_detail,
        "total_aum": total_aum,
    }
    OUTPUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # Log
    print(f"[{datetime.now().isoformat()}] compute_attribution -> {OUTPUT.name}")
    print(f"  days_ytd: {days_ytd}")
    for s in sleeves:
        print(f"  {s['name']:<13} w={s['weight_pct']:>6.2f}%  ytd={s['ytd_pct']:>+7.2f}%  contrib={s['contribution_pp']:>+7.3f}pp")
    print(f"  GROSS:  {gross_ytd:>+7.3f}%")
    print(f"  - fee:  {-mgmt_fee:>+7.3f}%")
    print(f"  NET:    {net_reconstructed:>+7.3f}%")
    print(f"  Lynk:   {lynk_ytd:>+7.3f}%")
    print(f"  RESIDUAL: {residual:>+7.3f}pp" if residual is not None else "  RESIDUAL: n/a")


if __name__ == "__main__":
    main()
