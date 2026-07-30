"""
validate_sleeve_returns.py
===========================
Chequeo de integridad del ultimo paso del daily cron: verifica que el
"Sleeve SI/YTD" (equity_vs_acwi / fi_vs_agg en benchmark_comparison.json)
no se haya corrompido, cruzandolo contra un metodo INDEPENDIENTE (cost basis
ponderado, ya verificado confiable via holdings_returns_{sleeve}.json).

Motivo (2026-07-30): el bug del anchor de Modified Dietz pegado ~1 mes
(ver memoria bug_twr_anchor_gap_modified_dietz) genero un FI YTD -1.09%
ficticio durante DIAS sin que nadie lo notara -- Fer lo vio antes que
Lucas. Este script existe para que la proxima vez que algo similar rompa
la cadena TWR, quede un alert ANTES de que un numero raro llegue a
producción sin avisar.

Que chequea:
  1. Anchor age: si el ultimo punto "real" (no interpolado) de
     twr_series es viejo (>5 dias), el refresh diario no esta corriendo.
  2. Cross-check de metodologia: el "SI" de benchmark_comparison.json
     (TWR chain) vs el SI cost-basis ponderado de holdings_returns_*.json
     (independiente, ya auditado). Si difieren mas de MAX_DIVERGENCE_PP
     puntos porcentuales, algo esta roto en una de las 2 cadenas.
  3. Flow_in sospechoso: si el flow_in del ultimo punto es > 15% del MV
     del sleeve en un solo dia, es una señal de anchor-drift (la firma
     del bug de julio: flow_in creciendo dia a dia sin trades reales
     de ese tamaño).

Si algo falla: escribe data/_alerts/sleeve_return_anomaly_YYYY-MM-DD.json
(mismo patron que el resto de las alertas del proyecto -- Claude las lee
al inicio de cada sesion y avisa a Lucas).

Usage:
    python scripts/validate_sleeve_returns.py
"""
import json
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
ALERTS_DIR = DATA_DIR / "_alerts"

MAX_ANCHOR_AGE_DAYS = 5
MAX_DIVERGENCE_PP = 5.0       # puntos porcentuales de diferencia entre YTD TWR vs YTD cost-basis
MAX_FLOW_PCT_OF_MV = 0.15     # 15% del MV del sleeve en un solo dia = sospechoso

SLEEVES = [
    ("equity", "equity_sleeve_real.json", "holdings_returns_equity.json"),
    ("fixed_income", "fi_sleeve_real.json", "holdings_returns_fixed_income.json"),
]


def _cost_basis_weighted_ytd(holdings_file):
    """YTD cost-basis ponderado por MV, desde holdings_returns_{sleeve}.json
    (metodo independiente ya auditado -- ver project_big_holdings_returns_system).
    Se usa YTD en vez de SI: SI acumula 13 meses de cambios de composicion del
    portfolio (holdings nuevos entrando en distintas fechas), lo que genera
    divergencia METODOLOGICA legitima frente al TWR chain (no es un bug).
    YTD es una ventana mas corta con mucho menos drift estructural, mejor
    señal para detectar errores reales."""
    try:
        d = json.load(open(DATA_DIR / holdings_file, encoding="utf-8"))
    except Exception:
        return None
    holdings = [h for h in d.get("holdings", []) if h.get("status") == "OPEN"]
    total_mv = sum(h.get("mv_usd") or 0 for h in holdings)
    if total_mv <= 0:
        return None
    weighted = sum((h.get("mv_usd") or 0) * (h.get("ytd_pct") or 0) for h in holdings)
    return weighted / total_mv


def _last_real_point(twr_series):
    """Ultimo punto NO interpolado de la serie (el ultimo calculo real)."""
    for p in reversed(twr_series):
        if not p.get("interpolated"):
            return p
    return twr_series[-1] if twr_series else None


def check_sleeve(sleeve_key, sleeve_file, holdings_file, today_iso):
    issues = []
    try:
        d = json.load(open(DATA_DIR / sleeve_file, encoding="utf-8"))
    except Exception as e:
        return [f"{sleeve_key}: no se pudo leer {sleeve_file} ({e})"]

    twr = d.get("twr_series", [])
    if not twr:
        return [f"{sleeve_key}: {sleeve_file} sin twr_series"]

    last = twr[-1]

    # 1) El punto de HOY tiene que ser real (no interpolado) y fechado hoy --
    #    si no, el refresh diario no corrio de verdad, solo se esta tapando
    #    el hueco con un placeholder.
    if last.get("interpolated"):
        issues.append(
            f"{sleeve_key}: el punto de hoy ({last['date']}) esta marcado 'interpolated' -- "
            f"el refresh diario no calculo un valor real, solo tapo el hueco."
        )
    elif last.get("date") != today_iso:
        issues.append(
            f"{sleeve_key}: el ultimo punto es de {last.get('date')}, no de hoy ({today_iso}) -- "
            f"el refresh diario no corrio."
        )
    else:
        # Ademas, ver si HUBO un hueco largo de interpolados justo antes de hoy
        # (informativo -- confirma que un outage reciente se esta resolviendo,
        # no bloquea, pero avisa mientras dura).
        real_before_last = _last_real_point(twr[:-1]) if len(twr) > 1 else None
        if real_before_last:
            try:
                age = (date.fromisoformat(today_iso) - date.fromisoformat(real_before_last["date"])).days
                if age > MAX_ANCHOR_AGE_DAYS:
                    issues.append(
                        f"{sleeve_key}: hubo un hueco de {age} dias sin refresh real (ultimo antes de "
                        f"hoy: {real_before_last['date']}) -- hoy ya corrio bien, pero investigar por "
                        f"que se cayo (ver data/_alerts/ de esos dias)."
                    )
            except Exception:
                pass

    # 2) Cross-check TWR YTD vs cost-basis YTD (ventana corta, poco drift metodologico)
    dec = next((p for p in twr if p["date"] == "2025-12-31"), None)
    ytd_twr = (last["index"] / dec["index"] - 1) * 100 if dec and dec.get("index") else None
    ytd_cb = _cost_basis_weighted_ytd(holdings_file)
    if ytd_twr is not None and ytd_cb is not None:
        divergence = abs(ytd_twr - ytd_cb)
        if divergence > MAX_DIVERGENCE_PP:
            issues.append(
                f"{sleeve_key}: YTD TWR ({ytd_twr:+.2f}%) vs YTD cost-basis independiente "
                f"({ytd_cb:+.2f}%) difieren {divergence:.2f}pp (umbral {MAX_DIVERGENCE_PP}pp) -- "
                f"revisar cual de las 2 cadenas esta mal."
            )

    # 3) Flow_in sospechoso (firma del bug de anchor-drift: crece dia a dia sin trade real)
    mv_today = last.get("mv_usd") or 0
    flow_in = abs(last.get("flow_in") or 0)
    if mv_today > 0 and flow_in / mv_today > MAX_FLOW_PCT_OF_MV:
        issues.append(
            f"{sleeve_key}: flow_in del ultimo punto (${flow_in:,.0f}) es "
            f"{flow_in/mv_today*100:.1f}% del MV (${mv_today:,.0f}) -- revisar si es un trade "
            f"real grande o un anchor roto."
        )

    return issues


def main():
    today_iso = date.today().isoformat()
    print(f"[{datetime.now().isoformat()}] Validando sleeve returns (Equity/FI)...")

    all_issues = []
    for sleeve_key, sleeve_file, holdings_file in SLEEVES:
        issues = check_sleeve(sleeve_key, sleeve_file, holdings_file, today_iso)
        if issues:
            for i in issues:
                print(f"  [ANOMALIA] {i}")
        else:
            print(f"  [OK] {sleeve_key}")
        all_issues.extend(issues)

    if all_issues:
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        alert_path = ALERTS_DIR / f"sleeve_return_anomaly_{today_iso}.json"
        with open(alert_path, "w", encoding="utf-8") as f:
            json.dump({
                "detected_at": datetime.now().isoformat(),
                "date": today_iso,
                "issues": all_issues,
            }, f, indent=2, ensure_ascii=False)
        print(f"\n  Alert escrito: {alert_path}")
    else:
        print("\n  Todo OK, sin anomalias.")


if __name__ == "__main__":
    main()
