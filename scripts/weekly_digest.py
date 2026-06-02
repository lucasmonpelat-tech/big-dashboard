"""
weekly_digest.py
================
Genera y envia el resumen semanal de performance de BIG por mail.

Corre los SABADOS al final del cron unificado (despues del refresh + commit).
Compara el cierre del VIERNES vs el cierre del VIERNES ANTERIOR.

Fuentes:
  - data/lynk_data.json      -> NAV/YTD/SI actuales
  - data/lynk_nav_series.json -> serie de NAV (5 dias)
  - data/equity_sleeve_real.json -> TWR sleeve + ACWI
  - data/fi_sleeve_real.json -> TWR sleeve FI + AGG
  - data/alts_race.json      -> liquidos (IBIT, GLD)
  - data/equity_contributions_real.json -> per-holding equity
  - data/fi_race.json        -> per-fondo FI

Output:
  - Mail a MAIL_LUCAS + MAIL_FER (SMTP via Gmail con App Password)
  - Estructura: NAV + headline macro + cada asset class + flags
  - Si hay ANTHROPIC_API_KEY -> narrativa "por que se movio X" con Claude API
  - Si no hay -> datos crudos (sigue siendo util)

Env vars requeridos (GitHub Secrets):
  - GMAIL_USER, GMAIL_APP_PASSWORD
  - MAIL_LUCAS, MAIL_FER
  - ANTHROPIC_API_KEY (opcional)

Uso:
    python scripts/weekly_digest.py
"""
import json
import os
import smtplib
import sys
from datetime import datetime, date, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"


# ============================================================================
# Helpers
# ============================================================================

def load_json(name: str) -> dict:
    """Lee un JSON del directorio data/. Devuelve {} si no existe."""
    path = DATA / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"WARN: error leyendo {name}: {e}", file=sys.stderr)
        return {}


def fmt_pct(v, decimals: int = 2, with_sign: bool = True) -> str:
    """Formatea como porcentaje con signo."""
    if v is None:
        return "—"
    sign = "+" if (with_sign and v >= 0) else ""
    return f"{sign}{v:.{decimals}f}%"


def fmt_pp(v, decimals: int = 2) -> str:
    """Formatea como puntos porcentuales."""
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.{decimals}f}pp"


def find_friday_close(series: list, target_date: date, key: str = "value") -> tuple:
    """
    Busca el ultimo punto <= target_date en una serie sorted by date asc.
    Devuelve (fecha_iso, valor) o (None, None).
    Cada punto del serie puede tener key 'value', 'index', 'price', etc.
    """
    if not series:
        return None, None
    s = sorted(series, key=lambda x: x.get("date", ""))
    last = None
    for p in s:
        d_str = p.get("date") or p.get("Date")
        if not d_str:
            continue
        try:
            d = datetime.fromisoformat(d_str[:10]).date()
        except Exception:
            continue
        if d <= target_date:
            v = p.get(key) or p.get("value") or p.get("index") or p.get("price") or p.get("nav")
            if v is not None:
                last = (d.isoformat(), v)
    return last if last else (None, None)


def last_two_fridays(today: date = None) -> tuple:
    """Devuelve (viernes anterior, viernes de esta semana)."""
    if today is None:
        today = date.today()
    # weekday(): Mon=0 ... Fri=4 ... Sun=6
    days_since_friday = (today.weekday() - 4) % 7
    if days_since_friday == 0 and today.weekday() != 4:
        days_since_friday = 7
    this_friday = today - timedelta(days=days_since_friday)
    prev_friday = this_friday - timedelta(days=7)
    return prev_friday, this_friday


# ============================================================================
# Calculo de movimientos
# ============================================================================

def compute_movements() -> dict:
    """
    Computa todo lo que va al digest.
    Devuelve un dict con la estructura:
      {
        "as_of": "2026-05-29",
        "lynk": {nav, ytd, si, week_return},
        "equity": {sleeve_week, acwi_week, alpha_week, top_winner, top_loser},
        "fi":     {sleeve_week, agg_week, alpha_week, top_winner, top_loser, ytw_change},
        "alts":   {btc_week, gold_week, btc_reason_data, gold_reason_data},
        "flags":  [list of flag strings]
      }
    """
    today = date.today()
    prev_fri, this_fri = last_two_fridays(today)
    print(f"Periodo: {prev_fri.isoformat()} -> {this_fri.isoformat()}")

    result = {
        "as_of": this_fri.isoformat(),
        "period_start": prev_fri.isoformat(),
        "lynk": {},
        "equity": {},
        "fi": {},
        "alts": {},
        "flags": [],
    }

    # ----- LYNK -----
    lynk = load_json("lynk_data.json")
    series = load_json("lynk_nav_series.json").get("series", [])
    _, this_nav = find_friday_close(series, this_fri, key="value")
    _, prev_nav = find_friday_close(series, prev_fri, key="value")
    if this_nav and prev_nav:
        week_ret = (this_nav / prev_nav - 1) * 100
    else:
        week_ret = None
        result["flags"].append(f"Serie Lynk incompleta (sin viernes {this_fri.isoformat()} o {prev_fri.isoformat()})")

    result["lynk"] = {
        "nav": lynk.get("nav") or this_nav,
        "nav_prev_friday": prev_nav,
        "ytd": lynk.get("returnYTD"),
        "si": lynk.get("returnSI"),
        "annualized": lynk.get("returnAnnualized"),
        "vol": lynk.get("volatility"),
        "sharpe": lynk.get("sharpe"),
        "week_return": week_ret,
    }

    # ----- EQUITY -----
    eq = load_json("equity_sleeve_real.json")
    twr = eq.get("twr_series", [])
    acwi = eq.get("acwi_index_series", [])
    _, this_eq = find_friday_close(twr, this_fri, key="index")
    _, prev_eq = find_friday_close(twr, prev_fri, key="index")
    _, this_acwi = find_friday_close(acwi, this_fri, key="index")
    _, prev_acwi = find_friday_close(acwi, prev_fri, key="index")
    eq_week = (this_eq / prev_eq - 1) * 100 if (this_eq and prev_eq) else None
    acwi_week = (this_acwi / prev_acwi - 1) * 100 if (this_acwi and prev_acwi) else None
    eq_alpha = (eq_week - acwi_week) if (eq_week is not None and acwi_week is not None) else None

    # Top movers equity (per-holding) — del sleeve_series_equity (snapshots con holdings)
    sleeve_series = eq.get("sleeve_series_equity", [])
    top_winner = top_loser = None
    if sleeve_series:
        s_sorted = sorted(sleeve_series, key=lambda x: x.get("date", ""))
        # tomo los dos snapshots mas recientes que tengan holdings
        snaps_with_holdings = [s for s in s_sorted if s.get("holdings")]
        if len(snaps_with_holdings) >= 2:
            last_snap = snaps_with_holdings[-1]
            # No tenemos snapshot exacto del viernes anterior siempre; uso el penultimo disponible
            prev_snap = snaps_with_holdings[-2]
            price_now = {h["ticker"]: h.get("price") for h in last_snap.get("holdings", [])}
            price_prev = {h["ticker"]: h.get("price") for h in prev_snap.get("holdings", [])}
            moves = []
            for tk, pn in price_now.items():
                pp = price_prev.get(tk)
                if pn and pp and pp > 0:
                    moves.append((tk, (pn / pp - 1) * 100))
            if moves:
                moves.sort(key=lambda x: x[1], reverse=True)
                top_winner = moves[0]
                top_loser = moves[-1]

    result["equity"] = {
        "sleeve_week": eq_week,
        "acwi_week": acwi_week,
        "alpha_week": eq_alpha,
        "top_winner": top_winner,  # (ticker, %) o None
        "top_loser": top_loser,
    }

    # ----- FI -----
    fi = load_json("fi_sleeve_real.json")
    fi_twr = fi.get("twr_series", [])
    agg = fi.get("agg_index_series", [])
    _, this_fi = find_friday_close(fi_twr, this_fri, key="index")
    _, prev_fi = find_friday_close(fi_twr, prev_fri, key="index")
    _, this_agg = find_friday_close(agg, this_fri, key="index")
    _, prev_agg = find_friday_close(agg, prev_fri, key="index")
    fi_week = (this_fi / prev_fi - 1) * 100 if (this_fi and prev_fi) else None
    agg_week = (this_agg / prev_agg - 1) * 100 if (this_agg and prev_agg) else None
    fi_alpha = (fi_week - agg_week) if (fi_week is not None and agg_week is not None) else None

    # YTW ponderado
    fi_race = load_json("fi_race.json")
    pm = fi_race.get("portfolio_metrics", {})
    result["fi"] = {
        "sleeve_week": fi_week,
        "agg_week": agg_week,
        "alpha_week": fi_alpha,
        "ytw_weighted": pm.get("weighted_ytw"),
        "duration_weighted": pm.get("weighted_duration"),
        "spread_vs_ust": pm.get("spread_vs_ust_10y"),
    }

    # ----- ALTS (liquidos) -----
    # IBIT y GLD: usamos live_prices o alts_race
    alts = load_json("alts_race.json")
    live = load_json("live_prices.json").get("prices", {})
    # IBIT
    ibit_p = (live.get("IBIT") or {}).get("price")
    gld_p = (live.get("GLD") or {}).get("price")
    # No tenemos historia de 1 sem facilmente; reportamos el precio y, si esta, el 1W return de alts_race
    btc_holding = None
    gld_holding = None
    for h in alts.get("holdings", []):
        tk = h.get("ticker", "").upper()
        if "IBIT" in tk or "BTC" in tk:
            btc_holding = h
        if "GLD" in tk or tk == "GOLD" or "ORO" in tk.upper():
            gld_holding = h

    result["alts"] = {
        "ibit_price": ibit_p,
        "gld_price": gld_p,
        "btc_holding": btc_holding,
        "gld_holding": gld_holding,
    }

    # ----- FLAGS -----
    if week_ret is not None and abs(week_ret) > 3:
        result["flags"].append(f"NAV BIG se movio {fmt_pct(week_ret)} en la semana (>±3%, materia de comentario)")
    if eq_alpha is not None and eq_alpha < -2:
        result["flags"].append(f"Equity perdio {fmt_pp(eq_alpha)} vs ACWI esta semana")
    if fi_alpha is not None and fi_alpha < -1:
        result["flags"].append(f"FI perdio {fmt_pp(fi_alpha)} vs AGG esta semana")

    return result


# ============================================================================
# Narrative (con o sin Claude API)
# ============================================================================

def generate_narrative(data: dict) -> str:
    """
    Si hay ANTHROPIC_API_KEY, genera narrative de 'por que' con Claude API.
    Si no, devuelve un narrative simple basado en heuristicas.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return generate_narrative_simple(data)

    try:
        return generate_narrative_claude(data, api_key)
    except Exception as e:
        print(f"WARN: Claude API fallo, uso narrative simple: {e}", file=sys.stderr)
        return generate_narrative_simple(data)


def generate_narrative_simple(data: dict) -> str:
    """Headline basado en heuristicas (sin API)."""
    lynk = data["lynk"]
    eq_alpha = data["equity"].get("alpha_week")
    fi_alpha = data["fi"].get("alpha_week")
    wk = lynk.get("week_return")

    parts = []
    if wk is not None:
        if wk > 1:
            parts.append(f"Semana positiva para BIG: NAV {fmt_pct(wk)}.")
        elif wk < -1:
            parts.append(f"Semana negativa para BIG: NAV {fmt_pct(wk)}.")
        else:
            parts.append(f"Semana neutra para BIG: NAV {fmt_pct(wk)}.")

    if eq_alpha is not None:
        if eq_alpha > 0.5:
            parts.append(f"Equity sleeve le gano al ACWI por {fmt_pp(eq_alpha)}.")
        elif eq_alpha < -0.5:
            parts.append(f"Equity sleeve perdio {fmt_pp(eq_alpha)} vs ACWI.")
    if fi_alpha is not None:
        if fi_alpha > 0.3:
            parts.append(f"FI sleeve le gano al AGG por {fmt_pp(fi_alpha)}.")
        elif fi_alpha < -0.3:
            parts.append(f"FI sleeve perdio {fmt_pp(fi_alpha)} vs AGG.")

    return " ".join(parts) if parts else "Sin movimientos relevantes esta semana."


def generate_narrative_claude(data: dict, api_key: str) -> str:
    """Genera headline narrativo usando Claude API."""
    import urllib.request
    import urllib.error

    prompt = (
        f"Sos un analista de un fondo multi-asset (BIG) escribiendo el headline "
        f"de un resumen semanal para el comite. Datos al cierre del viernes "
        f"{data['as_of']} (vs cierre del viernes {data['period_start']}):\n\n"
        f"- BIG NAV: {fmt_pct(data['lynk'].get('week_return'))} en la semana, "
        f"YTD {fmt_pct(data['lynk'].get('ytd'))}\n"
        f"- Equity sleeve: {fmt_pct(data['equity'].get('sleeve_week'))} vs "
        f"ACWI {fmt_pct(data['equity'].get('acwi_week'))} = alpha {fmt_pp(data['equity'].get('alpha_week'))}\n"
        f"- FI sleeve: {fmt_pct(data['fi'].get('sleeve_week'))} vs AGG "
        f"{fmt_pct(data['fi'].get('agg_week'))} = alpha {fmt_pp(data['fi'].get('alpha_week'))}\n"
        f"- YTW FI ponderado: {data['fi'].get('ytw_weighted')}%\n\n"
        f"Escribi en 2-3 oraciones (max 60 palabras), en espanol, tono PM, "
        f"explicando que paso esta semana y por que (contexto macro relevante: "
        f"mercados US, tasas, geopolitica, etc.). No incluyas saludo ni cierre."
    )

    body = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result["content"][0]["text"].strip()


# ============================================================================
# Render HTML + Texto
# ============================================================================

def render_text(data: dict, narrative: str) -> str:
    """Email en texto plano (fallback)."""
    lines = []
    lines.append(f"BIG · Resumen semanal · Cierre {data['as_of']}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("🟢 NAV CIERRE VIERNES")
    L = data["lynk"]
    lines.append(f"  NAV: ${L.get('nav', '?')}")
    lines.append(f"  Semana: {fmt_pct(L.get('week_return'))}")
    lines.append(f"  YTD: {fmt_pct(L.get('ytd'))} | SI: {fmt_pct(L.get('si'))}")
    lines.append("")
    lines.append("📌 HEADLINE")
    lines.append(f"  {narrative}")
    lines.append("")
    lines.append("📊 EQUITY RACE vs ACWI")
    E = data["equity"]
    lines.append(f"  Sleeve: {fmt_pct(E.get('sleeve_week'))}  |  ACWI: {fmt_pct(E.get('acwi_week'))}  |  Alpha: {fmt_pp(E.get('alpha_week'))}")
    if E.get("top_winner"):
        lines.append(f"  Top winner: {E['top_winner'][0]} {fmt_pct(E['top_winner'][1])}")
    if E.get("top_loser"):
        lines.append(f"  Top loser:  {E['top_loser'][0]} {fmt_pct(E['top_loser'][1])}")
    lines.append("")
    lines.append("🔵 FI RACE vs AGG")
    F = data["fi"]
    lines.append(f"  Sleeve: {fmt_pct(F.get('sleeve_week'))}  |  AGG: {fmt_pct(F.get('agg_week'))}  |  Alpha: {fmt_pp(F.get('alpha_week'))}")
    if F.get("ytw_weighted") is not None:
        lines.append(f"  YTW ponderado: {F['ytw_weighted']:.2f}%  |  Duration: {F.get('duration_weighted', '?')}y")
    lines.append("")
    lines.append("🟡 ALTS (líquidos)")
    A = data["alts"]
    if A.get("ibit_price"):
        lines.append(f"  IBIT (BTC): ${A['ibit_price']:.2f}")
    if A.get("gld_price"):
        lines.append(f"  GLD (Oro): ${A['gld_price']:.2f}")
    lines.append("  Privados (CALP/HLEND/etc): sin update intra-semana")
    lines.append("")
    if data.get("flags"):
        lines.append("⚠️  FLAGS / A VIGILAR")
        for f in data["flags"]:
            lines.append(f"  - {f}")
        lines.append("")
    lines.append("--")
    lines.append("Pampa Capital · Routine automatizada")
    return "\n".join(lines)


def render_html(data: dict, narrative: str) -> str:
    """Email en HTML."""
    L = data["lynk"]; E = data["equity"]; F = data["fi"]; A = data["alts"]

    def color_pct(v):
        if v is None:
            return "<span style='color:#888'>—</span>"
        c = "#1a7a3a" if v >= 0 else "#a33"
        sign = "+" if v >= 0 else ""
        return f"<span style='color:{c};font-weight:600'>{sign}{v:.2f}%</span>"

    def color_pp(v):
        if v is None:
            return "<span style='color:#888'>—</span>"
        c = "#1a7a3a" if v >= 0 else "#a33"
        sign = "+" if v >= 0 else ""
        return f"<span style='color:{c};font-weight:600'>{sign}{v:.2f}pp</span>"

    flags_html = ""
    if data.get("flags"):
        items = "".join(f"<li>{f}</li>" for f in data["flags"])
        flags_html = f"""
        <div style="background:#fff8e1;border-left:4px solid #f5a623;padding:12px 16px;margin:18px 0;border-radius:4px">
            <div style="font-weight:600;color:#7a5400;margin-bottom:6px">⚠️ Flags / a vigilar</div>
            <ul style="margin:0;padding-left:20px;color:#5a4400">{items}</ul>
        </div>
        """

    top_winner_html = ""
    top_loser_html = ""
    if E.get("top_winner"):
        top_winner_html = f"<div style='font-size:13px;color:#444'>🏆 Top winner: <strong>{E['top_winner'][0]}</strong> {color_pct(E['top_winner'][1])}</div>"
    if E.get("top_loser"):
        top_loser_html = f"<div style='font-size:13px;color:#444'>🔻 Top loser: <strong>{E['top_loser'][0]}</strong> {color_pct(E['top_loser'][1])}</div>"

    alt_btc = f"<div style='font-size:13px;color:#444'>IBIT (BTC): <strong>${A['ibit_price']:.2f}</strong></div>" if A.get("ibit_price") else ""
    alt_gld = f"<div style='font-size:13px;color:#444'>GLD (Oro): <strong>${A['gld_price']:.2f}</strong></div>" if A.get("gld_price") else ""

    ytw_line = ""
    if F.get("ytw_weighted") is not None:
        ytw_line = f"<div style='font-size:13px;color:#444'>YTW ponderado: <strong>{F['ytw_weighted']:.2f}%</strong> · Duration: <strong>{F.get('duration_weighted', '?')}y</strong></div>"

    nav_str = "?"
    if L.get("nav") is not None:
        try:
            nav_str = f"{float(L['nav']):.3f}"
        except Exception:
            nav_str = str(L["nav"])

    return f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,'Segoe UI',Roboto,sans-serif;color:#1a1a1a;max-width:680px;margin:0 auto;padding:24px;line-height:1.55">

<div style="background:#0d1b2a;color:#e8e0d0;padding:18px 22px;border-radius:6px;margin-bottom:18px">
    <div style="font-size:11px;letter-spacing:0.06em;color:#a0bcd8;font-family:monospace">PAMPA CAPITAL · RESUMEN SEMANAL</div>
    <div style="font-size:22px;font-weight:600;margin-top:4px">BIG · Cierre {data['as_of']}</div>
</div>

<div style="background:#f5f9f0;border-left:4px solid #1a7a3a;padding:14px 18px;border-radius:4px;margin-bottom:18px">
    <div style="font-size:12px;font-weight:600;color:#1a7a3a;letter-spacing:0.04em">🟢 NAV CIERRE VIERNES</div>
    <div style="font-size:24px;font-weight:700;color:#0d1b2a;margin-top:4px">${nav_str}</div>
    <div style="font-size:14px;color:#444;margin-top:4px">Semana: {color_pct(L.get('week_return'))} · YTD: {color_pct(L.get('ytd'), )} · SI: {color_pct(L.get('si'))}</div>
</div>

<div style="background:#e8eef5;border-left:4px solid #0d1b2a;padding:14px 18px;border-radius:4px;margin-bottom:18px">
    <div style="font-size:12px;font-weight:600;color:#0d1b2a;letter-spacing:0.04em">📌 HEADLINE DE LA SEMANA</div>
    <div style="font-size:14px;color:#1a1a1a;margin-top:6px">{narrative}</div>
</div>

<div style="border:1px solid #e0d8c8;border-radius:4px;padding:14px 18px;margin-bottom:14px">
    <div style="font-size:12px;font-weight:600;color:#0d1b2a;letter-spacing:0.04em">📊 EQUITY RACE vs ACWI</div>
    <div style="font-size:14px;margin-top:6px">Sleeve: {color_pct(E.get('sleeve_week'))} · ACWI: {color_pct(E.get('acwi_week'))} · Alpha: {color_pp(E.get('alpha_week'))}</div>
    {top_winner_html}
    {top_loser_html}
</div>

<div style="border:1px solid #e0d8c8;border-radius:4px;padding:14px 18px;margin-bottom:14px">
    <div style="font-size:12px;font-weight:600;color:#0d1b2a;letter-spacing:0.04em">🔵 FI RACE vs AGG</div>
    <div style="font-size:14px;margin-top:6px">Sleeve: {color_pct(F.get('sleeve_week'))} · AGG: {color_pct(F.get('agg_week'))} · Alpha: {color_pp(F.get('alpha_week'))}</div>
    {ytw_line}
</div>

<div style="border:1px solid #e0d8c8;border-radius:4px;padding:14px 18px;margin-bottom:14px">
    <div style="font-size:12px;font-weight:600;color:#0d1b2a;letter-spacing:0.04em">🟡 ALTS (líquidos)</div>
    {alt_btc}
    {alt_gld}
    <div style="font-size:12px;color:#888;margin-top:4px;font-style:italic">Privados (CALP, HLEND, GCRED, BPCC, FLEX, HLGPI): sin update intra-semana — esperar quarterlies</div>
</div>

{flags_html}

<div style="font-size:11px;color:#888;text-align:center;margin-top:24px;padding-top:14px;border-top:1px solid #e0d8c8">
    Pampa Capital · Routine automatizada · Generado por GitHub Actions
</div>

</body></html>"""


# ============================================================================
# Mail send
# ============================================================================

def send_mail(html_body: str, text_body: str, as_of: str):
    """Manda el mail via Gmail SMTP."""
    user = os.environ["GMAIL_USER"]
    pwd = os.environ["GMAIL_APP_PASSWORD"]
    to_lucas = os.environ["MAIL_LUCAS"]
    to_fer = os.environ["MAIL_FER"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 BIG · Resumen semanal · {as_of}"
    msg["From"] = f"Pampa BIG Bot <{user}>"
    msg["To"] = f"{to_lucas}, {to_fer}"

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(user, pwd)
        smtp.sendmail(user, [to_lucas, to_fer], msg.as_string())

    print(f"OK: mail enviado a {to_lucas} y {to_fer}")


# ============================================================================
# Main
# ============================================================================

def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Generando weekly digest...")
    data = compute_movements()
    narrative = generate_narrative(data)
    print(f"Narrative: {narrative}")

    html = render_html(data, narrative)
    text = render_text(data, narrative)

    # Guardar copia local del digest
    out_dir = ROOT / "data" / "_summaries"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"weekly_digest_{data['as_of']}.html").write_text(html, encoding="utf-8")
    (out_dir / f"weekly_digest_{data['as_of']}.txt").write_text(text, encoding="utf-8")
    print(f"Copia guardada en {out_dir}/")

    # Mandar mail (solo si tenemos secrets)
    if all(os.environ.get(k) for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "MAIL_LUCAS", "MAIL_FER")):
        send_mail(html, text, data["as_of"])
    else:
        print("WARN: faltan secrets de SMTP, mail no enviado (pero digest generado).")


if __name__ == "__main__":
    main()
