"""
validate_data.py
================
Validador de consistencia de datos del BIG Dashboard.

Caza errores SILENCIOSOS — los que no rompen nada visiblemente pero corrompen
los numeros (ej: un ISIN mal escrito hace que un fondo desaparezca de un tab
sin tirar error).

Chequea:
  1. ORPHAN ISINs   — ISINs en los dicts que ya no estan en cartera
  2. MISSING ISINs  — fondos en cartera que faltan en un dict donde deberian estar
  3. EXPOSURE SUMS  — CURRENCY/COUNTRY deben sumar ~100% por fondo

El universo de "que hay en cartera" sale de data/positions_latest.json, que se
refresca solo todos los dias. Hasta el 2026-08-24 salia del array manual
BIG_POSITIONS (funds_metadata.js), que quedaba viejo y generaba errores falsos.

Exit code 0 = todo OK. Exit code 1 = hay errores (gatea el deploy).

Usage:
    python scripts/validate_data.py
"""

import json
import re
import sys
from pathlib import Path

import build_fi_stats
import check_reportes_vs_datos
import race_weights

ROOT = Path(__file__).parent.parent
META_JS = ROOT / "data" / "funds_metadata.js"
POSITIONS_JSON = ROOT / "data" / "positions_latest.json"

SLEEVE_LABEL = {"equity": "Equity", "fixed_income": "Fixed Income",
                "alternatives": "Alternatives"}

# Claves que existen en los dicts pero no son fondos en cartera: no tiene
# sentido pedirles factsheet ni exposicion, y tampoco marcarlas como
# huerfanas cuando no aparecen en las posiciones.
NON_FUND_KEYS = {"CASH-USD"}

# ---- Holdings externos a Pershing (statements manuales) ---------------------
# Un holding "external_statement" (hoy solo CALP, custodiado fuera de Pershing)
# se carga A MANO y su dato termina replicado en 4 archivos, cada uno leido por
# un widget distinto. Si se actualiza uno solo, el dashboard muestra data
# mezclada (Overview con el mes nuevo, Alts Race con el viejo) y NADA lo
# reconcilia: ningun cron los sincroniza y el deploy pasa igual.
# Paso el 2026-08-26 al cargar el statement de Julio de CALP.
ALTS_EXTERNAL_JSON = ROOT / "data" / "alts_external.json"
ALTS_STATEMENT_JSON = ROOT / "data" / "alts_carlyle_statement.json"
ALTS_FACTSHEET_YTD_JSON = ROOT / "data" / "alts_factsheet_ytd.json"

# Los MV se copian textual del mismo statement, asi que tienen que ser
# identicos. Tolerancia sub-centavo: absorbe ruido de float (~1e-9) pero un
# centavo real de diferencia FALLA. Con 0.01 no fallaba: |0.01| no es > 0.01.
MV_TOLERANCE_USD = 0.005
PCT_TOLERANCE = 0.005

# Tolerancia para sumas de exposicion (%)
SUM_TOLERANCE = 1.5

# Cuanto puede diferir el weight_pct de un race JSON contra el canonical, en
# puntos porcentuales. 0.5 absorbe el redondeo a 2 decimales y el desfasaje de
# horas entre el transform temprano y el final del cron; un peso realmente
# congelado siempre driftea varios puntos.
WEIGHT_TOLERANCE_PP = 0.5
# Tolerancia para comparar valores USD entre las dos fuentes de posiciones
VALUE_TOLERANCE_USD = 1.0


def read_meta_js():
    """Lee funds_metadata.js como texto."""
    return META_JS.read_text(encoding="utf-8")


def extract_block(text, const_name):
    """Extrae el cuerpo de un `const NAME = {...}` o `const NAME = [...]`."""
    # Encuentra el inicio
    m = re.search(rf"const\s+{re.escape(const_name)}\s*=\s*", text)
    if not m:
        return None
    start = m.end()
    open_char = text[start]
    close_char = "}" if open_char == "{" else "]"
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return None


def extract_isin_keys(block):
    """Extrae las keys (ISINs) de un bloque tipo objeto JS: '"KEY": ...'."""
    if not block:
        return []
    # Match keys: "XXXX": al inicio de cada entry
    return re.findall(r'"([A-Za-z0-9\-]+)"\s*:', block)


def read_positions():
    """Universo de fondos en cartera, desde positions_latest.json.

    CAMBIO 2026-08-24: antes esto salia de BIG_POSITIONS, un array a mano
    dentro de funds_metadata.js con un snapshot congelado (ultimo update real
    2026-06-10). Como positions_latest.json se refresca solo todos los dias
    desde Pershing/NetX360, el array manual quedaba viejo y el validador
    escupia 30+ errores falsos por puro drift. BIG_POSITIONS se borro junto
    con el dashboard v1; la unica fuente de verdad de que hay en cartera es
    este JSON.
    """
    if not POSITIONS_JSON.exists():
        return []
    pj = json.loads(POSITIONS_JSON.read_text(encoding="utf-8"))
    out = [
        {
            "isin": pos["isin"],
            "ticker": pos.get("ticker", "?"),
            "sleeve": pos.get("sleeve", "?"),
            "value": pos.get("value"),
        }
        for pos in pj.get("positions", [])
        if pos.get("isin")
    ]

    # positions_latest.json es el espejo del export de Pershing, y hay
    # holdings que NO estan en Pershing (CALP se custodia afuera). Sin esto,
    # CALP -- 32% del sleeve alts -- daria "ISIN huerfano" en cada dict.
    seen = {o["isin"] for o in out}
    for h in _canonical_holdings():
        if h["isin"] and h["isin"] not in seen:
            out.append(h)
            seen.add(h["isin"])
    return out


def _canonical_holdings():
    """Holdings abiertos del ultimo snapshot canonical (incluye externos)."""
    snaps = sorted((ROOT / "data" / "canonical").glob("*/holdings_returns.json"))
    if not snaps:
        return []
    d = json.loads(snaps[-1].read_text(encoding="utf-8"))
    out = []
    for sleeve_key, sleeve in d.get("sleeves", {}).items():
        for h in sleeve.get("holdings", []):
            if (h.get("status") or "OPEN") != "OPEN":
                continue
            out.append({
                "isin": h.get("isin"),
                "ticker": h.get("ticker", "?"),
                "sleeve": SLEEVE_LABEL.get(sleeve_key, sleeve_key),
                "value": h.get("mv_usd"),
            })
    return out


def extract_exposure_sums(block):
    """Para CURRENCY/COUNTRY/SECTOR: devuelve {isin: suma_de_p}."""
    if not block:
        return {}
    sums = {}
    # Cada entry: "ISIN": [ ... {..p:NN..} ... ]  o  "ISIN": { exposures: [...] }
    # Partimos por las keys de ISIN
    entries = re.split(r'(?="[A-Za-z0-9\-]+"\s*:)', block)
    for entry in entries:
        key_m = re.match(r'\s*"([A-Za-z0-9\-]+)"\s*:', entry)
        if not key_m:
            continue
        isin = key_m.group(1)
        # sumar todos los p:NN del entry
        ps = [float(x) for x in re.findall(r"p:\s*([\d.]+)", entry)]
        if ps:
            sums[isin] = round(sum(ps), 2)
    return sums


def latest_canonical():
    """(path, dict) del snapshot canonical mas reciente, o (None, None)."""
    snaps = sorted((ROOT / "data" / "canonical").glob("*/holdings_returns.json"))
    if not snaps:
        return None, None
    return snaps[-1], json.loads(snaps[-1].read_text(encoding="utf-8"))


def _load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_external_statements(errors, warnings):
    """Los 4 archivos de un holding externo tienen que contar la misma historia.

    Compara, para cada holding del canonical con _mv_source == "external_statement":
      canonical  <-> alts_external.json        (as_of + mv_usd)
      canonical  <-> alts_carlyle_statement    (as_of + mv_usd del ultimo statement)
      canonical  <-> alts_factsheet_ytd        (as_of + ytd_pct)

    NO se hardcodea ningun ticker: el universo sale del propio canonical.
    """
    print("\n" + "-" * 70)
    print("  4 — Holdings externos: los 4 archivos en sincronia")
    print("-" * 70)

    canon_path, canon = latest_canonical()
    if not canon:
        warnings.append("no hay snapshot canonical — skip check de externos")
        print("  [WARN] sin snapshot canonical")
        return

    externos = [
        h for sl in canon.get("sleeves", {}).values()
        for h in sl.get("holdings", [])
        if h.get("_mv_source") == "external_statement"
    ]
    if not externos:
        print("  [OK]    no hay holdings con _mv_source='external_statement'")
        return

    ext_data = _load(ALTS_EXTERNAL_JSON) or {}
    ext_by_isin = {h.get("isin"): h for h in ext_data.get("holdings", []) if h.get("isin")}
    stmts = (_load(ALTS_STATEMENT_JSON) or {}).get("statements", {})
    ytd_ovr = (_load(ALTS_FACTSHEET_YTD_JSON) or {}).get("overrides", {})

    def diff(a, b, tol):
        if a is None or b is None:
            return a != b
        return abs(a - b) > tol

    for h in externos:
        tk, isin = h.get("ticker"), h.get("isin")
        c_asof, c_mv, c_ytd = h.get("_as_of"), h.get("mv_usd"), h.get("ytd_pct")
        problemas = []

        # --- alts_external.json: es de donde el transform DERIVA el canonical ---
        e = ext_by_isin.get(isin)
        if e is None:
            errors.append(f"externos[{tk}]: no esta en alts_external.json (el canonical lo tiene)")
        else:
            if e.get("as_of") != c_asof:
                problemas.append(f"alts_external.as_of={e.get('as_of')} vs canonical._as_of={c_asof}")
            if diff(e.get("mv_usd"), c_mv, MV_TOLERANCE_USD):
                problemas.append(f"alts_external.mv_usd={e.get('mv_usd')} vs canonical={c_mv}")

        # --- alts_carlyle_statement.json: historial de statements ---
        arr = stmts.get(tk)
        if not arr:
            warnings.append(f"externos[{tk}]: sin entrada en {ALTS_STATEMENT_JSON.name} "
                            f"(no se puede cruzar el statement)")
        else:
            last = max(arr, key=lambda s: str(s.get("as_of") or ""))
            if last.get("as_of") != c_asof:
                problemas.append(f"statement.as_of={last.get('as_of')} vs canonical._as_of={c_asof}")
            if diff(last.get("mv_usd"), c_mv, MV_TOLERANCE_USD):
                problemas.append(f"statement.mv_usd={last.get('mv_usd')} vs canonical={c_mv}")

        # --- alts_factsheet_ytd.json: override de YTD que consume el front ---
        o = ytd_ovr.get(isin)
        if o is None:
            warnings.append(f"externos[{tk}]: sin override en {ALTS_FACTSHEET_YTD_JSON.name}")
        else:
            if o.get("as_of") != c_asof:
                problemas.append(f"factsheet_ytd.as_of={o.get('as_of')} vs canonical._as_of={c_asof}")
            if diff(o.get("ytd_pct"), c_ytd, PCT_TOLERANCE):
                problemas.append(f"factsheet_ytd.ytd_pct={o.get('ytd_pct')} vs canonical={c_ytd}")

        if problemas:
            print(f"  [ERROR] {tk:6} DIVERGENTE ({len(problemas)})")
            for p in problemas:
                errors.append(f"externos[{tk}]: {p}")
        else:
            print(f"  [OK]    {tk:6} as_of={c_asof}  MV=${c_mv:,.2f}  (4 archivos coinciden)")

    if any(e.startswith("externos[") for e in errors):
        print()
        print("         Si el canonical quedo atras: corre refresh_dashboard_v2.bat")
        print("         (o `python -m dashboard_v2.transform.run_all`) para regenerarlo.")
        print(f"         Canonical usado: {canon_path.parent.name}")


def check_derivados_sincronizados(errors, warnings):
    """benchmark_comparison tiene que reflejar la ultima data cruda.

    POR QUE EXISTE (2026-09-04)
    ---------------------------
    Lucas vio el dashboard con Return YTD +3.79% cuando el valor real era
    +4.45%. La data cruda estaba perfecta -- lynk_nav_series tenia el NAV del
    03-sep -- pero benchmark_comparison.json, que es de donde el KPI toma el
    numero, habia quedado de una corrida anterior con el NAV del 02-sep.

    Lo peligroso: el validador daba "TODO OK". Cada archivo por separado se veia
    bien; lo que estaba roto era la relacion entre ellos. Justo el tipo de error
    que este validador existe para cazar.

    Causa de ese dia: dos corridas en paralelo (ver concurrency en
    daily-refresh.yml) dejaron el estado partido -- crudo nuevo, derivado viejo.
    El concurrency lo previene, pero cualquier otra falla a mitad de camino
    puede dejar el mismo desfasaje, asi que se chequea el resultado.

    No se hardcodea nada: cada comparison declara su propio `portfolio_source`.
    """
    print("\n" + "-" * 70)
    print("  5 — Derivados sincronizados con la data cruda")
    print("-" * 70)

    canon_path, _ = latest_canonical()
    if not canon_path:
        warnings.append("sin snapshot canonical — skip check de derivados")
        print("  [WARN] sin snapshot canonical")
        return
    bc_path = canon_path.parent / "benchmark_comparison.json"
    bc = _load(bc_path)
    if not bc:
        warnings.append(f"no pude leer {bc_path.name}")
        print(f"  [WARN] no pude leer {bc_path.name}")
        return

    def ultimo_de(source: str):
        """Resuelve 'data/x.json -> campo' al ultimo punto de esa serie."""
        partes = [p.strip() for p in source.split("->")]
        doc = _load(ROOT / partes[0])
        if not doc:
            return None, None
        campo = partes[1] if len(partes) > 1 else None
        serie = doc.get(campo) if campo else (doc.get("navSeries") or doc.get("series"))
        if not serie:
            return None, None
        ult = serie[-1]
        valor = ult.get("value") if ult.get("value") is not None else ult.get("index")
        return ult.get("date"), valor

    for nombre, comp in (bc.get("comparisons") or {}).items():
        source = comp.get("portfolio_source")
        serie = comp.get("series") or []
        if not source or not serie:
            warnings.append(f"derivados[{nombre}]: sin portfolio_source o sin serie")
            continue

        d_crudo, v_crudo = ultimo_de(source)
        if d_crudo is None:
            warnings.append(f"derivados[{nombre}]: no pude leer la fuente '{source}'")
            print(f"  [WARN] {nombre:22} fuente ilegible")
            continue

        d_deriv = serie[-1].get("date")
        v_deriv = serie[-1].get("portfolio")

        problemas = []
        if d_deriv != d_crudo:
            problemas.append(f"ultima fecha {d_deriv} vs {d_crudo} en la fuente")
        if (v_crudo is not None and v_deriv is not None
                and abs(v_crudo - v_deriv) > PCT_TOLERANCE):
            problemas.append(f"ultimo valor {v_deriv} vs {v_crudo} en la fuente")

        if problemas:
            print(f"  [ERROR] {nombre:22} DESFASADO")
            for p in problemas:
                errors.append(f"derivados[{nombre}]: {p} — "
                              f"benchmark_comparison quedo atras de {source}")
        else:
            print(f"  [OK]    {nombre:22} {d_deriv} (coincide con la fuente)")

    if any(e.startswith("derivados[") for e in errors):
        print()
        print("         El dashboard muestra lo DERIVADO, no lo crudo: si esto")
        print("         esta desfasado, en pantalla se ve un numero viejo aunque")
        print("         el scrape haya andado bien.")
        print("         Regenerar: python -m dashboard_v2.transform.run_all")


def check_pesos_race(errors, warnings):
    """Los race JSON no pueden tener los pesos congelados.

    POR QUE EXISTE (2026-09-08)
    ---------------------------
    Es el bug que mas veces volvio. Los tres *_race.json guardan weight_pct y
    value_usd, pero el unico script que los escribia era el rebuild completo de
    cada sleeve, borrado el 2026-08-20. Los refresh diarios solo tocan retornos,
    asi que los pesos se congelan mientras refreshedAt se sigue actualizando: el
    archivo parece fresco y no lo esta.

        Ago-2026  PIMCO-LD/INC invertidos en el pie de FI. Se parcheo el HTML.
        Sep-2026  volvio igual (38.66% vs 28.56% real) + el sleeve $700K corto.
                  Y ademas equity_race drifteaba hasta 1.8pp sin que nadie mirara.

    Las dos veces se detecto a ojo, comparando dos widgets. Este check lo hace
    solo: compara cada peso contra el canonical, que es la misma fuente que ya
    muestra la tabla "Holdings del Sleeve".

    Tolerancia 0.5pp: absorbe el redondeo a 2 decimales y el desfasaje de horas
    entre el transform temprano y el final del cron, pero un peso viejo de
    verdad (que siempre driftea varios puntos) falla.
    """
    print("\n" + "-" * 70)
    print("  6 - Pesos de los race JSON vs el canonical")
    print("-" * 70)

    for archivo, sleeve_key in race_weights.SLEEVE_DE_RACE.items():
        race = _load(ROOT / "data" / archivo)
        if not race:
            warnings.append(f"pesos[{archivo}]: no pude leerlo")
            print(f"  [WARN] {archivo:20} ilegible")
            continue

        r = race_weights.comparar(race, sleeve_key)
        if not r["total"]:
            warnings.append(f"pesos[{archivo}]: sin canonical para comparar")
            print(f"  [WARN] {archivo:20} sin canonical")
            continue

        desviados = [(tk, a, e, g) for tk, a, e, g in r["filas"]
                     if g is None or abs(g) > WEIGHT_TOLERANCE_PP]
        for tk, actual, esperado, gap in desviados:
            errors.append(
                f"pesos[{archivo}]: {tk} pesa {actual}% pero el canonical "
                f"({r['as_of']}) dice {esperado}% - {gap:+}pp. El peso quedo "
                f"congelado: nadie lo reescribe desde que se borro el rebuild "
                f"del sleeve. Correr el refresh diario de ese sleeve."
            )
        # Lista incompleta: NO es error de este check. Completarla necesita
        # reconstruir anchors y retornos por fondo (trabajo del rebuild del
        # sleeve), no algo que un refresh diario pueda hacer. Pero tiene que
        # verse en cada corrida, porque un fondo ausente del race se cae de la
        # clasificacion por sleeve del dashboard.
        for tk in r["faltan"]:
            warnings.append(
                f"pesos[{archivo}]: {tk} esta en el canonical pero NO en el race "
                f"- le falta el rebuild del sleeve. Desde el 2026-09-09 el "
                f"dashboard clasifica por sleeve leyendo el canonical, asi que "
                f"esto ya no afecta lo que se ve: quedo como deuda del archivo."
            )
        for tk in r["sobran"]:
            warnings.append(
                f"pesos[{archivo}]: {tk} esta en el race pero NO en el canonical "
                f"- posicion cerrada que quedo colgada. Su peso no se actualiza."
            )
        # Mismo fondo, dos ISIN. Hoy no rompe nada porque el pipeline cruza casi
        # todo por ticker, pero es una bomba de tiempo: el dia que un consumidor
        # cruce por ISIN, el holding desaparece callado -- justo el error
        # silencioso que este validador existe para cazar.
        for tk, isin_race, isin_canon in r["isines"]:
            errors.append(
                f"pesos[{archivo}]: {tk} tiene ISIN '{isin_race}' pero el canonical "
                f"dice '{isin_canon}'. Un solo fondo no puede tener dos ISIN dando "
                f"vueltas: cualquier cruce por ISIN lo pierde en silencio. "
                f"Unificar en el del statement oficial."
            )

        if desviados or r["isines"]:
            print(f"  [ERROR] {archivo:20} {len(desviados)} peso(s) desfasado(s) "
                  f"> {WEIGHT_TOLERANCE_PP}pp, {len(r['isines'])} ISIN discrepante(s)")
        else:
            extra = ""
            if r["faltan"] or r["sobran"]:
                extra = f"  (faltan: {r['faltan'] or '-'}, sobran: {r['sobran'] or '-'})"
            print(f"  [OK]    {archivo:20} {len(r['filas'])} pesos coinciden "
                  f"con canonical {r['as_of']}{extra}")


def check_fi_stats_derivado(errors, warnings):
    """YTW/Duracion/Vencimiento del factsheet tienen que salir de las fuentes.

    POR QUE EXISTE (2026-09-08)
    ---------------------------
    Estos tres numeros se escribian a mano en fi_breakdown_latest.json y de ahi
    iban al factsheet de clientes y al S10 del pitch book. El dashboard, en
    paralelo, los calculaba con OTRA regla de inclusion: metia TGF y PIMCO-EM
    (moneda local sin hedge) y dejaba afuera MANEM porque venia con ceros.
    Daba YTW 7.20 / Dur 4.64 / Venc 6.61 contra 6.98 / 4.46 / 6.01 del reporte.

    Nadie lo detectaba porque los dos numeros se ven razonables por separado.
    Solo aparece si comparas el dashboard contra el PDF que le mandaste a un
    cliente - y a esa altura ya es tarde.

    Ahora los dos leen la misma regla (fi_stats_include en data/funds/*.json) y
    este check verifica que el JSON publicado siga coincidiendo con lo que sale
    de las fuentes.
    """
    print("\n" + "-" * 70)
    print("  7 - fi_stats derivado de data/funds + canonical")
    print("-" * 70)

    try:
        r = build_fi_stats.calcular(None)
    except SystemExit as e:
        warnings.append(f"fi_stats: no se pudo calcular - {e}")
        print(f"  [WARN] no se pudo calcular: {e}")
        return

    doc = _load(ROOT / "data" / "fi_breakdown_latest.json") or {}
    filas = {f["metric"]: f.get("big") for f in (doc.get("fi_stats") or {}).get("rows", [])}

    for etiqueta, _ in build_fi_stats.METRICAS:
        publicado = filas.get(etiqueta)
        calculado = r["valores"][etiqueta]
        if publicado is None:
            errors.append(f"fi_stats: falta la fila '{etiqueta}' en fi_breakdown_latest.json")
            print(f"  [ERROR] {etiqueta:14} ausente")
        elif abs(publicado - calculado) > build_fi_stats.TOLERANCIA:
            errors.append(
                f"fi_stats: '{etiqueta}' publicado {publicado} vs {calculado} "
                f"calculado desde data/funds x canonical {r['as_of']} - "
                f"el factsheet y el dashboard van a mostrar numeros distintos. "
                f"Regenerar: python scripts/build_fi_stats.py"
            )
            print(f"  [ERROR] {etiqueta:14} {publicado} vs {calculado} calculado")
        else:
            print(f"  [OK]    {etiqueta:14} {publicado}")

    for tk in r["sin_flag"]:
        errors.append(
            f"fi_stats: {tk} no declara fi_stats_include en data/funds/{tk}.json - "
            f"no se sabe si entra en YTW/Duracion/Vencimiento. Definirlo "
            f"(true si esta en USD o hedgeado a USD)."
        )
    for m in r["faltantes"]:
        errors.append(f"fi_stats: falta {m} en data/funds - entra en el promedio como cero")
    if r["sin_ficha"]:
        warnings.append(f"fi_stats: sin data/funds/<TICKER>.json: {r['sin_ficha']}")

    print(f"  Incluidos: {', '.join(r['incluidos'])} - {r['cobertura_pct']}% del sleeve")


def check_mapa_reportes(errors, warnings):
    """Las rutas del mapa shape->fuente tienen que seguir resolviendo.

    POR QUE ESTA ACA Y NO EN EL SCRIPT DEL DECK (2026-09-09)
    --------------------------------------------------------
    scripts/reportes_shape_map.json dice de que campo de que JSON sale cada
    numero del factsheet y del pitch book. check_reportes_vs_datos.py lo usa el
    dia del cierre.

    El problema: si alguien renombra un campo o cambia una categoria (paso el
    2026-09-08 al fundir "US Treasury" dentro de "Govt-related"), el mapa apunta
    a un campo que ya no existe. Y no se entera nadie hasta el cierre, que es
    justo cuando no hay tiempo.

    Este check NO mira ningun deck -- los .pptx viven en Dropbox y aca no estan.
    Solo verifica que cada ruta declarada siga resolviendo contra los JSON del
    repo. Es barato y corre en cada deploy.
    """
    print("\n" + "-" * 70)
    print("  8 - Rutas del mapa shape->fuente de los reportes")
    print("-" * 70)

    mapa_path = ROOT / "scripts" / "reportes_shape_map.json"
    mapa = _load(mapa_path)
    if not mapa:
        warnings.append("no pude leer reportes_shape_map.json")
        print("  [WARN] no pude leerlo")
        return

    total, rotas = 0, 0
    for deck, entradas in mapa.items():
        if deck.startswith("_") or not isinstance(entradas, dict):
            continue
        for etq, decl in entradas.items():
            if etq.startswith("_"):
                continue
            specs = decl.get("fuentes") or ([decl["fuente"]] if decl.get("fuente") else [])
            for spec in specs:
                total += 1
                try:
                    check_reportes_vs_datos.resolver(spec)
                except Exception as e:
                    rotas += 1
                    errors.append(
                        "mapa reportes [%s] %s: la ruta '%s' ya no resuelve (%s). "
                        "Alguien renombro un campo o cambio una categoria; el "
                        "chequeo del deck se queda sin con que comparar."
                        % (deck, etq, spec, e))

    if rotas:
        print("  [ERROR] %d de %d rutas no resuelven" % (rotas, total))
    else:
        print("  [OK]    %d rutas resuelven contra los JSON del repo" % total)


def check_anchors_trabados(errors, warnings):
    """Un anchor con precio pero sin anchor_locked se pierde en la proxima corrida.

    POR QUE EXISTE (2026-09-10)
    ---------------------------
    year_start_anchors.json guarda el precio de cada fondo al 31-Dic, que es la
    base del YTD. NO es un archivo que se edite y quede: el pipeline lo
    RECONSTRUYE entero todos los dias (dashboard_v2/transform/snapshot_year_start.py,
    llamado desde run_all). Lo que no puede derivar de sus fuentes lo deja en null.

    Por eso existe `anchor_locked`: un anchor trabado se copia tal cual y no se
    recalcula nunca. Sin esa marca, un precio cargado a mano dura hasta la
    proxima corrida del cron.

    Paso el 2026-09-09: se cargaron a mano los anchors de MAGS (65.96) y HEWJ
    (52.4146) sin trabarlos. A la manana siguiente el cron los habia puesto en
    null y el YTD de los dos habia quedado congelado en el valor de la vispera.
    Doce horas, y el sintoma era identico al bug que se estaba arreglando.

    La forma correcta de cargar uno es scripts/lock_year_start_anchor.py, que
    ademas deja registrada la fuente.
    """
    print("\n" + "-" * 70)
    print("  9 - Anchors 31-Dic trabados (si no, el cron los borra)")
    print("-" * 70)

    doc = _load(ROOT / "data" / "year_start_anchors.json")
    if not doc:
        warnings.append("no pude leer year_start_anchors.json")
        print("  [WARN] no pude leerlo")
        return

    anchors = doc.get("anchors_2026") or {}
    sueltos, trabados, sin_precio = [], 0, 0
    for isin, a in anchors.items():
        precio = a.get("price_2025_dec_31")
        if precio is None:
            sin_precio += 1
        elif a.get("anchor_locked"):
            trabados += 1
        else:
            sueltos.append((a.get("ticker", isin), isin, precio))

    for tk, isin, precio in sueltos:
        errors.append(
            "anchors: %s (%s) tiene price_2025_dec_31=%s pero NO anchor_locked. "
            "snapshot_year_start.py reconstruye este archivo todos los dias y lo "
            "va a pisar con null en la proxima corrida del cron; el YTD del fondo "
            "queda congelado. Trabarlo: python scripts/lock_year_start_anchor.py "
            "--isin %s --price %s --source \"...\"" % (tk, isin, precio, isin, precio)
        )

    if sueltos:
        print("  [ERROR] %d anchor(s) con precio pero sin trabar" % len(sueltos))
    else:
        print("  [OK]    %d trabados, %d sin precio (nada en riesgo de perderse)"
              % (trabados, sin_precio))


def main():
    print("=" * 70)
    print("  BIG Dashboard — Data Consistency Validator")
    print("=" * 70)

    text = read_meta_js()
    errors = []
    warnings = []

    # ---- Universo de fondos en cartera (positions_latest.json) ----
    positions = read_positions()
    if not positions:
        print("[FATAL] No pude leer positions_latest.json (o vino vacio)")
        sys.exit(1)
    big_isins = {pp["isin"] for pp in positions}
    equity_isins = {pp["isin"] for pp in positions if pp["sleeve"] == "Equity"}
    fi_isins = {pp["isin"] for pp in positions if pp["sleeve"] == "Fixed Income"}
    print(f"\npositions_latest.json: {len(positions)} fondos "
          f"({len(equity_isins)} equity, {len(fi_isins)} FI, "
          f"{len(big_isins) - len(equity_isins) - len(fi_isins)} alts/cash)")

    # ---- 1 & 2: ORPHAN / MISSING ISINs en cada dict ----
    # (dict_name, debe_cubrir_isins, label, severity)
    #   severity "error"   -> gatea el deploy
    #   severity "warning" -> solo avisa (dicts opcionales / data muerta)
    checks = [
        ("FACTSHEET_LINKS", big_isins - {"CASH-USD"}, "todos (menos cash)", "error"),
        ("CURRENCY_EXPOSURE", big_isins, "todos los fondos", "error"),
        ("CURRENT_YIELD", big_isins, "todos los fondos", "error"),
        ("COUNTRY_EXPOSURE", big_isins, "todos los fondos", "error"),
        # FI_METRICS migrado a data/funds/<TICKER>.json — chequeado abajo en check separado.
        # SECTOR_EXPOSURE: borrado el 2026-05-15 (era data muerta).
    ]

    print("\n" + "-" * 70)
    print("  1 & 2 — Cobertura de ISINs por diccionario")
    print("-" * 70)
    for dict_name, should_cover, label, severity in checks:
        block = extract_block(text, dict_name)
        if block is None:
            errors.append(f"{dict_name}: no se encontro el bloque")
            continue
        keys = set(extract_isin_keys(block))

        orphans = keys - big_isins - NON_FUND_KEYS
        missing = should_cover - keys
        bucket = errors if severity == "error" else warnings

        status = "OK"
        if orphans:
            status = severity.upper()
            for o in sorted(orphans):
                bucket.append(f"{dict_name}: ISIN huerfano '{o}' (no esta en positions_latest.json)")
        if missing:
            status = severity.upper() if status == "OK" else status
            for m in sorted(missing):
                tk = next((p["ticker"] for p in positions if p["isin"] == m), "?")
                bucket.append(f"{dict_name}: falta ISIN '{m}' ({tk}) — esperado [{label}]")

        flag = {"OK": "[OK]   ", "ERROR": "[ERROR]", "WARNING": "[WARN] "}[status]
        print(f"  {flag} {dict_name:20s} {len(keys):2d} keys  "
              f"(orphans: {len(orphans)}, missing: {len(missing)})")

    # ---- 2b: FI_METRICS migrado a data/funds/<TICKER>.json ----
    print("\n" + "-" * 70)
    print("  2b — FI metrics en data/funds/*.json (single source de YTW/Dur/Maturity)")
    print("-" * 70)
    funds_dir = ROOT / "data" / "funds"
    fi_funds = [p for p in positions if p["sleeve"] == "Fixed Income"]
    fi_missing_json = []
    fi_missing_metrics = []
    for fp in fi_funds:
        fpath = funds_dir / f"{fp['ticker']}.json"
        if not fpath.exists():
            fi_missing_json.append(fp["ticker"])
            errors.append(f"data/funds/{fp['ticker']}.json no existe (FI fund {fp['isin']})")
            continue
        try:
            d = json.loads(fpath.read_text(encoding="utf-8"))
            # Skip fi_metrics validation para fondos pendientes de factsheet
            # (posiciones piloto recien abiertas). Marcador: as_of_factsheet == null.
            if d.get("as_of_factsheet") is None:
                continue
            fm = d.get("fi_metrics", {})
            for required in ["ytw", "duration", "maturity"]:
                if fm.get(required) is None:
                    fi_missing_metrics.append(f"{fp['ticker']}.json falta fi_metrics.{required}")
                    errors.append(f"data/funds/{fp['ticker']}.json: falta fi_metrics.{required}")

            # ---- Check de plausibilidad para CAT BONDS / ILS ----
            # Los cat bonds son floating-rate (SOFR+spread) -> duration de tasa ~0,
            # weighted avg life ~2-3y, sin rating crediticio tradicional. Si un cat
            # bond reporta duration de bono tradicional (>1.5y) o rating IG, es
            # señal de datos placeholder/cruzados (paso con SGCB: dur 4.03 / BBB+).
            name_l = (d.get("name") or "").lower()
            is_cat = d.get("is_cat_bond") or "cat bond" in name_l or "ils" in name_l or "insurance-linked" in name_l
            if is_cat:
                dur = fm.get("duration")
                if dur is not None and dur > 1.5:
                    errors.append(f"data/funds/{fp['ticker']}.json: CAT BOND con duration {dur}y (>1.5) — "
                                  f"implausible, los cat bonds son floating (dur ~0). Verificar factsheet real.")
                rating = (fm.get("rating") or "").upper()
                IG = {"AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"}
                if rating in IG:
                    errors.append(f"data/funds/{fp['ticker']}.json: CAT BOND con rating IG '{rating}' — "
                                  f"implausible, los cat bonds son sub-IG/sin rating (usar 'NR'). Verificar factsheet.")
        except Exception as e:
            errors.append(f"data/funds/{fp['ticker']}.json: error de parse — {e}")

    if fi_missing_json or fi_missing_metrics:
        print(f"  [ERROR] {len(fi_funds)} FI funds — {len(fi_missing_json)} sin JSON, {len(fi_missing_metrics)} sin metricas completas")
    else:
        print(f"  [OK]    {len(fi_funds)} FI funds — todos tienen JSON con fi_metrics completas (ytw/duration/maturity)")

    # ---- 3: EXPOSURE SUMS ----
    print("\n" + "-" * 70)
    print("  3 — Sumas de exposicion (~100% por fondo)")
    print("-" * 70)
    for dict_name in ["CURRENCY_EXPOSURE", "COUNTRY_EXPOSURE"]:
        block = extract_block(text, dict_name)
        sums = extract_exposure_sums(block)
        bad = {k: v for k, v in sums.items() if abs(v - 100) > SUM_TOLERANCE}
        if bad:
            for isin, total in sorted(bad.items()):
                tk = next((p["ticker"] for p in positions if p["isin"] == isin), "?")
                errors.append(f"{dict_name}: '{isin}' ({tk}) suma {total}% (deberia ser ~100%)")
            print(f"  [ERROR] {dict_name:20s} {len(bad)} fondos no suman 100%")
        else:
            print(f"  [OK]    {dict_name:20s} {len(sums)} fondos suman ~100%")

    # ---- 4: HOLDINGS EXTERNOS (statements manuales, 4 archivos) ----
    check_external_statements(errors, warnings)

    # ---- 5: DERIVADOS SINCRONIZADOS CON LA DATA CRUDA ----
    check_derivados_sincronizados(errors, warnings)

    # ---- 6: PESOS DE LOS RACE JSON (fosiles del rebuild borrado) ----
    check_pesos_race(errors, warnings)

    # ---- 7: fi_stats DERIVADO (misma regla que el dashboard) ----
    check_fi_stats_derivado(errors, warnings)

    # ---- 8: EL MAPA DE LOS REPORTES SIGUE APUNTANDO A ALGO ----
    check_mapa_reportes(errors, warnings)

    # ---- 9: ANCHORS TRABADOS (el cron reconstruye ese archivo) ----
    check_anchors_trabados(errors, warnings)

    # ---- REPORTE FINAL ----
    print("\n" + "=" * 70)
    if warnings:
        print(f"  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")
    if errors:
        print(f"  ERRORES ({len(errors)}):")
        for e in errors:
            print(f"    [X] {e}")
        print("=" * 70)
        print(f"\n  RESULTADO: {len(errors)} error(es) — REVISAR antes de deploy")
        sys.exit(1)
    else:
        print("  RESULTADO: TODO OK — data consistente, safe to deploy")
        print("=" * 70)
        sys.exit(0)


if __name__ == "__main__":
    main()
