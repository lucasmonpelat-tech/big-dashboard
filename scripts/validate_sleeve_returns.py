"""
validate_sleeve_returns.py
===========================
Chequeo de integridad del ultimo paso del daily cron: verifica que el TWR de
Equity/FI/Alts (equity_sleeve_real.json, fi_sleeve_real.json,
alts_sleeve_real.json) no se haya corrompido.

Motivo (2026-07-30): el bug del anchor de Modified Dietz pegado ~1 mes
(ver memoria bug_twr_anchor_gap_modified_dietz) genero un FI YTD -1.09%
ficticio durante DIAS sin que nadie lo notara -- Fer lo vio antes que Lucas.
Este script existe para que la proxima vez que algo similar rompa la cadena
TWR, quede un alert ANTES de que un numero raro llegue a produccion sin
avisar.

FIX 2026-08-10: la version anterior comparaba el YTD del TWR contra un YTD
"cost-basis" independiente (holdings_returns_{sleeve}.json). Lucas: ese
cross-check usa una metodologia DISTINTA a proposito (no pondera por fecha
de cada flujo), asi que diverge del TWR cada vez que entra plata nueva en
distintos momentos del año -- generaba alertas falsas sin señal real, y
Lucas prefiere UN numero preciso (el TWR) con chequeos de integridad
directos sobre ESE calculo, en vez de compararlo contra otro método que
mide algo distinto a proposito. Se reemplaza el cross-check por chequeos
que apuntan directo a las 2 causas raiz que ya rompieron el TWR esta
temporada:
  (a) anchor drift -- el ancla usada para Modified Dietz deja de ser el
      ultimo mes-end real (ver refresh_equity_daily.py _find_last_real_month_end).
  (b) transacciones pendientes de confirmar contadas mas de una vez en
      buys_history (Pershing repite la fila con fecha nueva cada dia
      mientras siga pendiente).

Que chequea:
  1. Anchor age: si el ultimo punto "real" (no interpolado) de twr_series
     es viejo (>5 dias), el refresh diario no esta corriendo.
  2. Salto de indice dia a dia implausible: compara el ultimo punto real
     contra el real anterior (ignorando interpolados) -- un salto mayor a
     MAX_DAILY_INDEX_MOVE_PP en un dia es la firma de un anchor roto o un
     mv_usd mal calculado, no de un movimiento de mercado real para un
     sleeve diversificado.
  3. Flow_in sospechoso: si el flow_in del ultimo punto es > 15% del MV
     del sleeve en un solo dia, es señal de anchor-drift o double-count.
  4. Transacciones pendientes duplicadas en buys_history: mismo ticker +
     mismo costo (redondeado) apareciendo con 2+ fechas distintas dentro
     de una ventana corta -- firma exacta del bug de HLGPI/FLEX
     (2026-08-07): Pershing repite una fila no confirmada todos los dias
     con el Process Date de ESE dia, y sin filtro eso se cuenta como
     compra nueva cada vez.

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
MAX_DAILY_INDEX_MOVE_PP = 5.0   # % de cambio dia a dia en el indice, entre 2 puntos REALES consecutivos
MAX_FLOW_PCT_OF_MV = 0.15       # 15% del MV del sleeve en un solo dia = sospechoso

SLEEVES = [
    ("equity", "equity_sleeve_real.json", "holdings_returns_equity.json"),
    ("fixed_income", "fi_sleeve_real.json", "holdings_returns_fixed_income.json"),
    ("alternatives", "alts_sleeve_real.json", "holdings_returns_alternatives.json"),
]


def _last_real_point(twr_series):
    """Ultimo punto NO interpolado de la serie (el ultimo calculo real)."""
    for p in reversed(twr_series):
        if not p.get("interpolated"):
            return p
    return twr_series[-1] if twr_series else None


def _real_points_desc(twr_series):
    """Generador de puntos NO interpolados, del mas reciente al mas viejo."""
    for p in reversed(twr_series):
        if not p.get("interpolated"):
            yield p


def check_duplicate_pending_buys(holdings_file):
    """Detecta la misma compra (ticker + costo redondeado) apareciendo en
    2+ dias CALENDARIO CONSECUTIVOS -- firma exacta de una transaccion
    pendiente de confirmar que Pershing repite todos los dias con el
    Process Date de ESE dia mientras no se confirme (ver
    compute_holdings_returns.py, fix 2026-08-07: caso real HLGPI/FLEX,
    mismo monto 3 dias seguidos).

    Exige dias CONSECUTIVOS (no solo "dentro de una ventana") para evitar
    falsos positivos con correcciones legitimas de Pershing que reusan el
    mismo monto en fechas separadas por mas de 1 dia (ej: el fund exchange
    PIMCO-INC<->PIMCO-LD de $4,535,807 cancelado el 30-ene y re-emitido el
    2-feb-2026, verificado contra el statement oficial -- 3 dias de gap,
    no consecutivo, no es un duplicado)."""
    try:
        d = json.load(open(DATA_DIR / holdings_file, encoding="utf-8"))
    except Exception:
        return []
    issues = []
    for h in d.get("holdings", []):
        buys = h.get("buys_history", []) or []
        by_cost = {}
        for b in buys:
            key = round(b.get("cost", 0), 2)
            by_cost.setdefault(key, []).append(b.get("date"))
        for cost, dates in by_cost.items():
            if len(dates) < 2:
                continue
            try:
                dates_sorted = sorted(date.fromisoformat(dd) for dd in dates if dd)
            except Exception:
                continue
            # buscar 2+ fechas consecutivas (gap de exactamente 1 dia) dentro de la lista
            consecutive_run = [dates_sorted[0]]
            for dd in dates_sorted[1:]:
                if (dd - consecutive_run[-1]).days == 1:
                    consecutive_run.append(dd)
                else:
                    if len(consecutive_run) >= 2:
                        break
                    consecutive_run = [dd]
            if len(consecutive_run) >= 2:
                fechas = ', '.join(dd.isoformat() for dd in consecutive_run)
                issues.append(
                    f"{h.get('ticker')}: el mismo monto (${cost:,.0f}) aparece en "
                    f"{len(consecutive_run)} dias CONSECUTIVOS en buys_history ({fechas}) -- "
                    f"probable transaccion pendiente de confirmar contada mas de una vez."
                )
    return issues


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

    # 2) Salto de indice dia a dia implausible entre 2 puntos REALES
    #    consecutivos (ignora los interpolados de en medio -- esos ya se
    #    reportan aparte en el chequeo de hueco). Firma directa de anchor
    #    drift o mv_usd mal calculado: un sleeve diversificado no deberia
    #    moverse mas de unos pocos % de un dia real al siguiente.
    real_points = list(_real_points_desc(twr))
    if len(real_points) >= 2:
        cur, prev = real_points[0], real_points[1]
        if cur.get("index") and prev.get("index"):
            move_pct = (cur["index"] / prev["index"] - 1) * 100
            if abs(move_pct) > MAX_DAILY_INDEX_MOVE_PP:
                issues.append(
                    f"{sleeve_key}: el indice salto {move_pct:+.2f}% entre {prev['date']} y "
                    f"{cur['date']} (umbral {MAX_DAILY_INDEX_MOVE_PP}pp) -- revisar el anchor y el "
                    f"mv_usd de ese dia, no parece un movimiento de mercado real."
                )

    # 3) Flow_in sospechoso (firma del bug de anchor-drift/double-count:
    #    crece sin trades reales de ese tamaño)
    mv_today = last.get("mv_usd") or 0
    flow_in = abs(last.get("flow_in") or 0)
    if mv_today > 0 and flow_in / mv_today > MAX_FLOW_PCT_OF_MV:
        issues.append(
            f"{sleeve_key}: flow_in del ultimo punto (${flow_in:,.0f}) es "
            f"{flow_in/mv_today*100:.1f}% del MV (${mv_today:,.0f}) -- revisar si es un trade "
            f"real grande o un anchor roto."
        )

    # 4) Transacciones pendientes duplicadas en buys_history (fix 2026-08-10,
    #    firma exacta del bug de HLGPI/FLEX)
    issues.extend(check_duplicate_pending_buys(holdings_file))

    # 5) El flujo del mes explica los cambios de posicion (fix FLEX 2026-09-25)
    try:
        issues.extend(check_flows_vs_positions(sleeve_key, twr, holdings_file))
    except Exception as e:
        issues.append(f"{sleeve_key}: no se pudo correr el chequeo flujo vs posiciones ({e})")

    return issues


MAX_FLOW_GAP_PCT_OF_MV = 0.005   # 0.5% del MV: por encima, el flujo no explica el cambio de posiciones
MIN_FLOW_GAP_USD = 5000

_SLEEVE_NAME = {"equity": "Equity", "fixed_income": "Fixed Income", "alternatives": "Alternatives"}


def _is_month_end(d):
    import calendar
    y, m, dd = map(int, d.split("-"))
    return dd == calendar.monthrange(y, m)[1]


def _canonical_positions(pred):
    """(fecha, {security_id: (qty, price)}) del snapshot canonical mas reciente
    cuya fecha cumple pred. None si no hay."""
    dirs = sorted(p.name for p in (DATA_DIR / "canonical").iterdir() if p.is_dir())
    for d in reversed(dirs):
        if not pred(d):
            continue
        f = DATA_DIR / "canonical" / d / "positions.json"
        if not f.exists():
            continue
        out = {}
        for h in json.load(open(f, encoding="utf-8")).get("holdings", []):
            sid = h.get("security_id") or h.get("cusip")
            if sid:
                out[sid] = (h.get("quantity") or 0.0, h.get("market_price_ccy"))
        return d, out
    return None


def _tracked_tickers(holdings_file):
    """Tickers OPEN que el sleeve incluye en su MV (holdings_returns_<sleeve>)."""
    try:
        d = json.load(open(DATA_DIR / holdings_file, encoding="utf-8"))
        return {h.get("ticker") for h in d.get("holdings", []) if (h.get("status") or "OPEN") == "OPEN"}
    except Exception:
        return set()


def check_flows_vs_positions(sleeve_key, twr, holdings_file=None):
    """5) El flujo acumulado del mes tiene que explicar los cambios de cantidad
    de las posiciones del sleeve desde el anchor (fin de mes).

    POR QUE EXISTE (2026-09-25)
    ---------------------------
    El 08-Sep entro el 2do tramo de FLEX ($130k): la posicion paso de 16,415 a
    20,507 cuotas y el MV del sleeve subio $130k. Pershing lo asento con el
    settlement retro-fechado al 04-Ago, asi que el lector de flujos (que
    filtraba por settlement > anchor) no lo conto en septiembre -- ni en
    agosto, porque el 31-Ago el asiento no existia. Los $130k quedaron como
    "retorno": el YTD de Alts mostro 6.44% cuando era 4.85%. Ningun chequeo lo
    vio: el salto diario fue 1.1% (umbral 5pp) y el flow_in era 0.

    QUE MIRA
    --------
    Σ (qty_hoy - qty_anchor) x precio_hoy por posicion del sleeve, contra el
    flow_in del ultimo punto. Es el mismo numero medido por otro camino (las
    posiciones en vez de las transacciones), no otra metodologia de retorno.
    Se excluyen las posiciones sin precio (HLEND/GCRED: la "cantidad" es el
    valor en dolares y cambia cuando Pershing re-marca, no por flujos). Para
    el anchor se prueban el ultimo snapshot <= anchor y el primero > anchor, y
    solo avisa si NINGUNO de los dos cuadra: un trade justo el dia del cierre
    puede caer de un lado u otro y no es un error.
    """
    issues = []
    anchor = None
    for p in reversed(twr):
        if _is_month_end(p["date"]) and p.get("mv_usd") is not None and not p.get("interpolated"):
            anchor = p
            break
    if anchor is None or not twr:
        return issues
    last = twr[-1]
    flow_in = last.get("flow_in") or 0.0
    mv_today = last.get("mv_usd") or 0.0
    if mv_today <= 0:
        return issues

    import sys as _s
    _s.path.insert(0, str(ROOT / "scripts"))
    from compute_holdings_returns import PERSHING_TO_MY as M
    sleeve_name = _SLEEVE_NAME[sleeve_key]
    en_sleeve = {sid for sid, (tk, sl) in M.items() if sl == sleeve_name}

    hoy = _canonical_positions(lambda d: True)
    if not hoy:
        return issues
    d_hoy, pos_hoy = hoy

    # Solo se comparan las posiciones que el sleeve INCLUYE en su MV. Una
    # posicion de Pershing mapeada al sleeve pero que el TWR no rastrea (no
    # esta en holdings_returns_<sleeve>, sin NAV diario) queda fuera del MV y
    # del flujo a la vez: no infla el retorno, pero su plata no se mide. Se
    # avisa aparte, porque el arreglo es distinto (dar de alta el fondo, no
    # tocar el flujo). Caso GAM cat bond, comprado 11-Sep-2026, $200k.
    tracked = _tracked_tickers(holdings_file) if holdings_file else set()
    if tracked:
        fuera = sorted({M[sid][0] for sid in en_sleeve
                        if sid in pos_hoy and (pos_hoy[sid][0] or 0) > 0 and M[sid][0] not in tracked})
        if fuera:
            issues.append(
                f"{sleeve_key}: posicion(es) en Pershing mapeadas a este sleeve que el TWR NO incluye "
                f"(ni en MV ni en flujo): {', '.join(fuera)}. Su retorno no se esta midiendo -- hay que "
                f"darlas de alta en holdings_returns/ucits_daily_nav como al resto."
            )
        en_sleeve = {sid for sid in en_sleeve if M[sid][0] in tracked}
    candidatos = [c for c in (_canonical_positions(lambda d: d <= anchor["date"]),
                              _canonical_positions(lambda d: d > anchor["date"])) if c]
    if not candidatos:
        return issues

    tol = max(MAX_FLOW_GAP_PCT_OF_MV * mv_today, MIN_FLOW_GAP_USD)
    resultados = []
    for d_anc, pos_anc in candidatos:
        esperado, detalle = 0.0, []
        for sid in en_sleeve:
            q1, px1 = pos_hoy.get(sid, (0.0, None))
            q0, px0 = pos_anc.get(sid, (0.0, None))
            px = px1 if px1 is not None else px0
            if px is None:
                continue  # sin precio: la cantidad es un valor, no cuotas
            dq = (q1 or 0.0) - (q0 or 0.0)
            if abs(dq) > 1e-6:
                esperado += dq * px
                detalle.append(f"{M[sid][0]} {dq:+,.2f} x {px:,.2f}")
        resultados.append((d_anc, esperado, detalle))
        if abs(esperado - flow_in) <= tol:
            return issues  # cuadra con este anchor: OK

    d_anc, esperado, detalle = resultados[0]
    issues.append(
        f"{sleeve_key}: el flow_in del mes (${flow_in:+,.0f} desde {anchor['date']}) no explica "
        f"los cambios de posicion (Σ Δqty x precio = ${esperado:+,.0f}, snapshot {d_anc} -> {d_hoy}; "
        f"tolerancia ${tol:,.0f}). Movimientos: {'; '.join(detalle) or 'ninguno'}. Si hay un trade "
        f"que el flujo no cuenta, el TWR lo esta tomando como retorno (caso FLEX 08-Sep-2026)."
    )
    return issues


def main():
    today_iso = date.today().isoformat()
    print(f"[{datetime.now().isoformat()}] Validando sleeve returns (Equity/FI/Alts)...")

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
