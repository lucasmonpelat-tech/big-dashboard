"""
build_equity_lookthrough.py
===========================
Regenera el look-through consolidado del sleeve Equity:

    data/equity_top10_consolidated.json   (top 15 companies del sleeve)

Formula: para cada fondo, contribucion = peso_fondo_en_sleeve x peso_holding_en_fondo.
Las companies con el mismo nombre canonico se SUMAN entre fondos.

Por que existe este script (2026-08-25)
---------------------------------------
El JSON lo venia armando `refresh_lookthrough_with_mags_hewj.py`, un one-off con
los pesos del sleeve HARDCODEADOS al 2026-07-22. Eso dejaba tres problemas:

  1. `sleeve_weights` quedo con los 9 fondos viejos sumando 100.1% -- MAGS y
     HEWJ ni figuraban, asi que su exposicion (5.2% del sleeve) no sumaba nada.
     MAGS aparecia como "contributor" con weight_in_fund pero SIN contribution.
  2. Los 9 fondos originales se ponderaban con pesos viejos (CSPX 34.0% cuando
     hoy es 31.7%), inflando cada contribucion.
  3. Sintoma visible: Apple daba total 2.11 cuando su unica componente
     declarada (CSPX) aportaba 2.21.

Mismo patron que el bug de pesos congelados del FI Race. Ahora los pesos salen
SIEMPRE de la data del dia, asi que el script se puede correr cuando sea.

Fuente de holdings por fondo
----------------------------
`fund_holdings_top10.json` tiene DOS campos paralelos por fondo:
  - `top_holdings`     -> por TICKER. Solo CSPX y THOR tienen data real.
  - `_factsheet_top10` -> por NOMBRE. Tiene los 11 fondos.
Este script usa `_factsheet_top10` (el que tiene data) y resuelve cada nombre a
una company canonica con ALIASES. Un nombre que no matchea NO se descarta: se
prettifica y se reporta al final, para que no desaparezca en silencio.

Usage:
    python scripts/build_equity_lookthrough.py
    python scripts/build_equity_lookthrough.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TOP_N = 15

# Companies que aparecen en MAS DE UN fondo con nombres distintos. Sin este mapa
# quedarian como filas separadas y el top se subestimaria. clave = nombre tal
# cual viene en el factsheet, valor = company canonica.
ALIASES = {
    # Mega-caps US: CSPX las lista por ticker, MAGS por razon social
    "NVDA": "NVIDIA (NVDA)",
    "NVIDIA CORP": "NVIDIA (NVDA)",
    "MSFT": "Microsoft (MSFT)",
    "MICROSOFT CORP": "Microsoft (MSFT)",
    "AAPL": "Apple (AAPL)",
    "APPLE INC": "Apple (AAPL)",
    "AMZN": "Amazon (AMZN)",
    "AMAZON.COM INC": "Amazon (AMZN)",
    "META": "Meta (META)",
    "META PLATFORMS INC CLASS A": "Meta (META)",
    "TSLA": "Tesla (TSLA)",
    "TESLA INC": "Tesla (TSLA)",
    # Alphabet: CSPX lista las dos clases por separado, MAGS solo la A
    "GOOGL": "Alphabet (GOOGL)",
    "GOOG": "Alphabet (GOOGL)",
    "ALPHABET INC CLASS A": "Alphabet (GOOGL)",
    # Broadcom: CSPX por ticker, THOR con sufijo
    "AVGO": "Broadcom (AVGO)",
    "Broadcom_AVGO": "Broadcom (AVGO)",
    "BRK.B": "Berkshire Hathaway (BRK.B)",
    # LatAm: mismos nombres en ILF y 4BRZ
    "Vale": "Vale (VALE)",
    "Nu_Holdings": "Nu Holdings (NU)",
    "Itau_Unibanco": "Itau Unibanco (ITUB)",
    # Petrobras: ADR + las dos clases locales son la MISMA compania
    "Petrobras_ADR": "Petrobras (PBR)",
    "Petrobras_PETR3": "Petrobras (PBR)",
    "Petrobras_PETR4": "Petrobras (PBR)",
}

TICKER_SUFFIX = re.compile("_([A-Z][A-Z0-9.]{0,5})$")

# --- Resolucion a TICKER (nivel clase de accion) ------------------------------
# OJO: esto NO es lo mismo que ALIASES. ALIASES junta clases de la misma company
# (GOOGL + GOOG -> "Alphabet") porque para el top consolidado interesa la
# COMPANY. Aca interesa la CLASE, porque el ACWI lista GOOGL y GOOG como dos
# filas con pesos distintos. Usar el mapa equivocado mezcla las dos y da mal.
TICKER_BY_NAME = {
    "NVDA": "NVDA", "NVIDIA CORP": "NVDA",
    "AAPL": "AAPL", "APPLE INC": "AAPL",
    "MSFT": "MSFT", "MICROSOFT CORP": "MSFT",
    "AMZN": "AMZN", "AMAZON.COM INC": "AMZN",
    "META": "META", "META PLATFORMS INC CLASS A": "META",
    "TSLA": "TSLA", "TESLA INC": "TSLA",
    "GOOGL": "GOOGL", "ALPHABET INC CLASS A": "GOOGL",
    "GOOG": "GOOG",
    "AVGO": "AVGO", "Broadcom_AVGO": "AVGO",
    "BRK.B": "BRK.B",
}

# El ACWI lista algunas companies por su ticker local y los factsheets por el
# ADR. Son el mismo papel a efectos de exposicion.
TICKER_EQUIV = {
    "TSM": "2330",     # Taiwan Semiconductor: ADR en NYSE vs listing en Taiwan
}


def resolve_ticker(raw):
    """Nombre de factsheet -> ticker, o None si no se puede determinar.

    Devolver None es correcto y esperado para la mayoria (Michelin, Snam, etc):
    solo importa resolver lo que puede cruzarse contra el ACWI top 10.
    """
    if raw in TICKER_BY_NAME:
        tk = TICKER_BY_NAME[raw]
    else:
        m = TICKER_SUFFIX.search(raw)
        if m:
            tk = m.group(1)
        elif raw.isupper() and len(raw) <= 6 and " " not in raw:
            tk = raw
        else:
            return None
    return TICKER_EQUIV.get(tk, tk)


def prettify(raw):
    """Nombre de factsheet -> nombre legible. 'MercadoLibre_MELI' -> 'MercadoLibre (MELI)'."""
    m = TICKER_SUFFIX.search(raw)
    if m:
        return raw[: m.start()].replace("_", " ") + " (" + m.group(1) + ")"
    return raw.replace("_", " ")


def canonical(raw):
    """(company canonica, si matcheo el mapa explicito)."""
    if raw in ALIASES:
        return ALIASES[raw], True
    return prettify(raw), False


def sleeve_weights():
    """Peso de cada fondo DENTRO del sleeve Equity (suma 100), con data de hoy."""
    d = json.loads((DATA / "holdings_returns_equity.json").read_text(encoding="utf-8"))
    open_h = [h for h in d["holdings"]
              if (h.get("status") or "OPEN") == "OPEN" and h.get("mv_usd")]
    total = sum(h["mv_usd"] for h in open_h)
    if not total:
        raise SystemExit("ERROR: el sleeve Equity vino con MV total 0")
    return {h["ticker"]: h["mv_usd"] / total * 100 for h in open_h}, total, d.get("period_end")


def fund_top_holdings(fund):
    """Holdings del fondo: prioriza _factsheet_top10 (tiene los 11) sobre top_holdings."""
    for field in ("_factsheet_top10", "top_holdings"):
        block = fund.get(field)
        if isinstance(block, dict):
            real = {k: v for k, v in block.items()
                    if not k.startswith("_") and isinstance(v, (int, float))}
            if real:
                return real, field
    return {}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Muestra el resultado, no escribe")
    args = ap.parse_args()

    W, sleeve_mv, period_end = sleeve_weights()
    funds = json.loads((DATA / "fund_holdings_top10.json").read_text(encoding="utf-8"))

    print(f"Sleeve Equity: ${sleeve_mv:,.0f} | {len(W)} fondos | period_end={period_end}")

    sin_holdings = [t for t in W if t not in funds]
    if sin_holdings:
        print(f"  WARN: fondos del sleeve SIN entrada en fund_holdings_top10.json: {sin_holdings}")
        print("        no van a aportar nada al consolidado.")

    companies = {}
    asof = {}

    for ticker, weight in sorted(W.items(), key=lambda kv: -kv[1]):
        fund = funds.get(ticker)
        if not isinstance(fund, dict):
            continue
        holdings, field = fund_top_holdings(fund)
        if not holdings:
            print(f"  WARN: {ticker} sin holdings usables -> aporta 0")
            continue
        asof[ticker] = fund.get("_as_of")
        print(f"  {ticker:6} peso {weight:5.2f}%  {len(holdings):2} holdings  ({field}, as_of {asof[ticker]})")

        for raw, w_in_fund in holdings.items():
            name, _matched = canonical(raw)
            contribution = weight * w_in_fund / 100
            c = companies.setdefault(name, {"name": name, "weight_in_sleeve_pct": 0.0, "by_fund": {}})
            c["weight_in_sleeve_pct"] += contribution
            # Un mismo fondo puede listar la company DOS veces (Alphabet GOOGL+GOOG
            # en CSPX, Petrobras PETR3+PETR4 en 4BRZ). Se acumulan en una sola
            # linea por fondo en vez de repetir el fondo.
            slot = c["by_fund"].setdefault(ticker, {"fund": ticker, "weight_in_fund": 0.0,
                                                    "contribution": 0.0})
            slot["weight_in_fund"] += w_in_fund
            slot["contribution"] += contribution

    ranked = sorted(companies.values(), key=lambda c: -c["weight_in_sleeve_pct"])[:TOP_N]
    for i, c in enumerate(ranked, 1):
        c["rank"] = i
        c["weight_in_sleeve_pct"] = round(c["weight_in_sleeve_pct"], 3)
        funds_list = sorted(c.pop("by_fund").values(), key=lambda f: -f["contribution"])
        for f in funds_list:
            f["weight_in_fund"] = round(f["weight_in_fund"], 2)
            f["contribution"] = round(f["contribution"], 3)
        c["funds"] = funds_list

    out = {
        "refreshedAt": date.today().isoformat(),
        "generatedBy": "scripts/build_equity_lookthrough.py",
        "method": ("Look-through: para cada fondo, peso_sleeve x peso_holding_en_fondo. "
                   "Companies con el mismo nombre canonico se suman across fondos. "
                   "Pesos del sleeve tomados de holdings_returns_equity.json (data del dia), "
                   "holdings de _factsheet_top10 en fund_holdings_top10.json."),
        "sleeve_mv_usd": round(sleeve_mv, 2),
        "sleeve_weights": {k: round(v, 2) for k, v in sorted(W.items(), key=lambda kv: -kv[1])},
        "fund_asof": asof,
        "consolidated_top10": ranked,
    }

    print()
    print(f"  {'#':>2}  {'company':28} {'% sleeve':>9}  fondos")
    for c in ranked:
        detalle = ", ".join(f"{f['fund']} {f['contribution']:.2f}" for f in c["funds"])
        print(f"  {c['rank']:>2}. {c['name']:28} {c['weight_in_sleeve_pct']:>9.3f}  {detalle}")

    suma_pesos = sum(W.values())
    print()
    print(f"  Check: pesos del sleeve suman {suma_pesos:.2f}% (debe ser 100.00)")

    # La mayoria de las companies aparecen en un solo fondo -- eso es normal y no
    # se reporta. Lo que SI importa es detectar dos filas separadas que en
    # realidad son la misma company escrita distinto (alias faltante en ALIASES):
    # eso parte la exposicion en dos y la subestima.
    # Clave = las DOS primeras palabras. Con una sola daba falsos positivos
    # obvios ("Banco Bradesco" vs "Banco Macro", "Deutsche Post" vs "Deutsche
    # Telekom"), y un warning que grita en falso es un warning que se ignora.
    posibles = {}
    for name in companies:
        palabras = name.split("(")[0].split()[:2]
        clave = "".join(ch for ch in "".join(palabras).upper() if ch.isalnum())
        if len(clave) >= 5:
            posibles.setdefault(clave, set()).add(name)
    dudosos = {k: sorted(v) for k, v in posibles.items() if len(v) > 1}
    if dudosos:
        print("  OJO posibles alias faltantes (misma company en 2 filas):")
        for k, names in sorted(dudosos.items()):
            print(f"    {k}: {names}")
    else:
        print("  Check: sin companies duplicadas por nombre")

    if args.dry_run:
        print()
        print("  --dry-run: no se escribio nada")
        return

    path = DATA / "equity_top10_consolidated.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"  OK escrito: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
