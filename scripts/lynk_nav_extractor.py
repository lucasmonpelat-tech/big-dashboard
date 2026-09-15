"""
lynk_nav_extractor.py
=====================
Extract BIG Fund's full NAV history from Lynk Markets public chart.

Lynk's chart (Recharts) receives a data prop with the complete series —
we hook into the React fiber tree via Playwright to pull it out.

Usage:
    pip install playwright
    playwright install chromium
    python scripts/lynk_nav_extractor.py --email lucas.monpelat@pampa-capital.com

Outputs:
    data/lynk_nav_series.json — {refreshedAt, source, series: [{date, value}, ...]}
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_FILE = Path(__file__).parent.parent / "data" / "lynk_nav_series.json"
LYNK_URL = "https://app.lynkmarkets.com/public/products/4w9aANBbvM"

# Salto diario maximo que se acepta sin chistar.
#
# BIG es 40 renta fija / 30 equity / 30 alternativos. Para moverse 3% en un dia
# el sleeve de equity tendria que hacer -10%. En 303 dias de historia el mayor
# movimiento REAL fue 1.87% (7-8 May-2026); los unicos que pasan 3% son el
# 12-Ago-2026 (-3.41% y +3.63% al dia siguiente), que es un print roto de Lynk.
#
# Si algun dia salta por un movimiento de mercado genuino y extremo, el costo es
# barato: no se pisa el archivo y llega un mail. Se revisa y se corre de nuevo.
SALTO_MAX_PCT = 3.0

# Saltos YA CONOCIDOS que no deben bloquear la escritura.
#
# Sin esta lista la guarda se auto-sabotea: el 12-Ago malo YA esta en la serie
# que publica Lynk y en el archivo que tenemos guardado. Si bloqueara por el,
# bloquearia TODOS los dias, el archivo quedaria congelado para siempre y lo
# unico que llegaria seria un mail diario identico que se vuelve ignorable.
# Seria fabricar el mismo fosil que la guarda viene a evitar: un archivo que
# parece vivo y no se actualiza.
#
# Entonces: estos no frenan la escritura, pero se IMPRIMEN en cada corrida para
# que no se olviden. Sacar la fecha de aca en cuanto Lynk corrija el dato.
SALTOS_ACEPTADOS = {
    "2026-08-12": "print roto de Lynk (-3.41%), reclamado 2026-09-15, sin corregir",
    "2026-08-13": "rebote del mismo print roto (+3.63%)",
}

EXTRACT_JS = r"""
() => {
  function getFiber(el) {
    const k = Object.keys(el).find(x => x.startsWith('__reactFiber'));
    return k ? el[k] : null;
  }
  function findData(fiber, max = 30) {
    const seen = new WeakSet();
    let best = null;
    function walk(f, d) {
      if (!f || d > max || seen.has(f)) return;
      seen.add(f);
      const p = f.memoizedProps;
      if (
        p?.data &&
        Array.isArray(p.data) &&
        p.data[0]?.NAV &&
        p.data.length > 100 &&
        typeof p.data[0].date === 'string' &&
        p.data[0].date.includes('T')
      ) {
        if (!best || p.data.length >= best.length) best = p.data;
      }
      if (f.return) walk(f.return, d + 1);
      if (f.child) walk(f.child, d + 1);
      if (f.sibling) walk(f.sibling, d + 1);
    }
    walk(fiber, 0);
    return best;
  }
  const svg = document.querySelector('svg.recharts-surface');
  if (!svg) return null;
  const fiber = getFiber(svg.closest('.recharts-wrapper') || svg.parentElement);
  const raw = findData(fiber);
  if (!raw) return null;
  return raw.map(d => ({ date: d.date.slice(0, 10), value: parseFloat(d.NAV) }));
}
"""


def extract(email: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed:")
        print("  pip install playwright")
        print("  playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        print(f"[{datetime.now()}] Loading Lynk...")
        page.goto(LYNK_URL, wait_until="networkidle")

        # Email gate
        try:
            inp = page.locator('input[type="email"]').first
            if inp.is_visible(timeout=3000):
                inp.fill(email)
                page.click('button:has-text("CONTINUE")')
                page.wait_for_load_state("networkidle")
                print("  Email gate passed")
        except Exception:
            pass

        # Wait for chart to render
        page.wait_for_selector("svg.recharts-surface", timeout=15000)
        page.wait_for_timeout(2000)

        series = page.evaluate(EXTRACT_JS)
        browser.close()
        return series


def validar_serie(series, previa=None):
    """Devuelve (errores, avisos). errores vacio = la serie se puede escribir.

    POR QUE EXISTE (2026-09-15)
    ---------------------------
    Este script NO tenia ninguna validacion: escribia lo que viniera del grafico
    y pisaba lynk_nav_series.json, que es la serie historica completa del NAV de
    BIG y de donde salen retornos, volatilidad y el grafico del dashboard.

    El 15-Sep Lynk publico el NAV del lunes 14 en 0. Si este script hubiera
    corrido ese dia, metia el 0 en la serie y en el campo `latest`. No corrio de
    pura suerte: el scrape de KPIs fallo antes y se llevo puesto el job entero.
    O sea que la unica cosa que nos protegio fue un bug distinto.

    Como el step lleva continue-on-error, la falla no rompe el cron: se preserva
    el archivo anterior y se avisa por mail via data/_alerts/.

    QUE CHEQUEA
    -----------
      1. NAV <= 0 o fuera de rango: el caso del 14-Sep.
      2. Saltos diarios absurdos: una 40/30/30 con alternativos no se mueve
         >3% en un dia. El 12-Ago de Lynk (-3.41% y +3.63% al dia siguiente)
         es un print roto que sigue en su serie -- este check lo habria marcado.
      3. La serie se acorta: si hoy trae menos puntos que el archivo que ya
         tenemos, algo se perdio del lado de Lynk y no queremos pisar historia.
    """
    errors, avisos = [], []

    if len(series) < 2:
        return [f"serie demasiado corta: {len(series)} punto(s)"], avisos

    # 1. Valores. Un NAV en 0 o fuera de rango es fatal venga de donde venga,
    #    aunque sea un punto viejo: significa que Lynk reescribio historia mal.
    for p in series:
        v = p.get("value")
        if not isinstance(v, (int, float)) or v != v:   # v != v atrapa NaN
            errors.append(f"{p.get('date')}: valor no numerico ({v!r})")
        elif not (10 <= v <= 10000):
            errors.append(f"{p.get('date')}: NAV fuera de rango ({v})")

    if errors:
        return errors, avisos

    # 2. Saltos diarios. Los ya conocidos avisan pero no bloquean (ver
    #    SALTOS_ACEPTADOS: si bloquearan, el archivo no se actualizaria nunca mas).
    for i in range(1, len(series)):
        a, b = series[i - 1]["value"], series[i]["value"]
        if not a:
            continue
        pct = (b / a - 1) * 100
        if abs(pct) <= SALTO_MAX_PCT:
            continue
        fecha = series[i]["date"]
        linea = ("salto diario irreal %s -> %s: %.3f -> %.3f (%+.2f%%)"
                 % (series[i - 1]["date"], fecha, a, b, pct))
        if fecha in SALTOS_ACEPTADOS:
            avisos.append(f"{linea}  [conocido: {SALTOS_ACEPTADOS[fecha]}]")
        else:
            errors.append(linea)

    # 3. La serie no puede encogerse: seria perder historia.
    if previa and len(series) < len(previa):
        errors.append(
            "la serie se acorto: %d puntos ahora contra %d guardados. "
            "No se pisa el archivo." % (len(series), len(previa))
        )

    return errors, avisos


def escribir_alerta(path, errors, series):
    """Alerta en data/_alerts/ -> send_failure_alert.py la manda por mail."""
    if not path:
        return
    import os
    from datetime import date
    carpeta = os.path.dirname(path)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date.today().isoformat(),
            "tipo": "lynk_serie_nav_invalida",
            "issues": errors,
            "accion": ("La serie historica de NAV que publica Lynk tiene datos "
                       "invalidos. lynk_nav_series.json NO se piso: se conserva "
                       "la ultima version buena. Verificar contra "
                       "api.lynkmarkets.com/financial/<id> y reclamarle a Lynk "
                       "si el dato malo es de ellos."),
            "ultimos_puntos": series[-5:] if series else [],
        }, f, indent=2, ensure_ascii=False)
    print(f"  Alerta escrita en {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="lucas.monpelat@pampa-capital.com")
    parser.add_argument("--alerta", default=None,
                        help="Si la serie es invalida, escribir el JSON de alerta aca.")
    args = parser.parse_args()

    series = extract(args.email)
    if not series:
        print("ERROR: Could not extract NAV series")
        escribir_alerta(args.alerta, ["no se pudo extraer la serie del grafico"], [])
        sys.exit(1)

    # ===== GUARDA =====
    # Mejor conservar la serie vieja que pisarla con un dato roto del proveedor.
    previa = None
    if OUTPUT_FILE.exists():
        try:
            previa = json.loads(OUTPUT_FILE.read_text(encoding="utf-8")).get("series")
        except Exception:
            previa = None

    errors, avisos = validar_serie(series, previa)

    # Los conocidos no frenan nada, pero se imprimen siempre: un dato malo que
    # se deja pasar en silencio deja de existir para todos.
    for a in avisos:
        print(f"  AVISO: {a}")

    if errors:
        print("\nERROR: serie invalida — NO se sobreescribe lynk_nav_series.json.")
        for e in errors:
            print(f"  - {e}")
        print("\nEl archivo anterior se preserva. Revisar si el dato malo es de "
              "Lynk (api.lynkmarkets.com/financial/4w9aANBbvM) antes de tocar nada.")
        escribir_alerta(args.alerta, errors, series)
        sys.exit(1)

    output = {
        "refreshedAt": datetime.now().isoformat(),
        "source": "Lynk Markets public chart (extracted via React fiber)",
        "isin": "XS3037627794",
        "inception": series[0]["date"],
        "latest": series[-1],
        "first": series[0],
        "series": series,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    si_return = (series[-1]["value"] / series[0]["value"] - 1) * 100
    print(f"\n  Points: {len(series)}")
    print(f"  First : {series[0]['date']} → {series[0]['value']}")
    print(f"  Last  : {series[-1]['date']} → {series[-1]['value']}")
    print(f"  SI    : {si_return:+.2f}%")
    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
