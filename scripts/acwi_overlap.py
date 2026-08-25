"""
acwi_overlap.py
===============
Computes BIG's lookthrough exposure to ACWI top 10 holdings.

Logic:
1. Read ACWI top 10 from data/acwi_holdings/acwi_holdings.csv
2. For each ACWI top 10 stock, sum across BIG equity funds:
   BIG_exposure[stock] = Σ (fund_weight_in_BIG × stock_weight_in_fund)
3. Output: data/acwi_overlap.json for dashboard rendering

Usage:
    python scripts/acwi_overlap.py
"""

import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent

# resolve_ticker vive en build_equity_lookthrough.py junto al resto del
# conocimiento de nombres de holdings, para no tener dos mapas que se
# desincronicen.
sys.path.insert(0, str(Path(__file__).parent))
from build_equity_lookthrough import resolve_ticker  # noqa: E402

TOP_N = 10


def read_acwi_top10():
    """Read ACWI holdings CSV and return top N by weight."""
    import io
    csv_path = ROOT / "data" / "acwi_holdings" / "acwi_holdings.csv"
    holdings = []
    with open(csv_path, encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith("Ticker,"):
            header_idx = i
            break
    if header_idx is None:
        return []

    # Read from header_idx onwards
    csv_text = "".join(lines[header_idx:])
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        try:
            w = row.get("Weight (%)")
            if not w or w == "-" or w == "":
                continue
            weight = float(w.replace(",", ""))
            ticker = (row.get("Ticker") or "").strip('"').strip()
            if not ticker or ticker == "-":
                continue
            holdings.append({
                "ticker": ticker,
                "name": (row.get("Name") or "").strip('"').strip(),
                "sector": (row.get("Sector") or "").strip('"').strip(),
                "weight_acwi": weight,
                "location": (row.get("Location") or "").strip('"').strip(),
            })
        except (ValueError, KeyError, TypeError, AttributeError):
            continue

    holdings.sort(key=lambda x: -x["weight_acwi"])
    return holdings[:TOP_N]


def read_positions():
    """Read positions_latest.json and return equity holdings with BIG weights."""
    with open(ROOT / "data" / "positions_latest.json") as f:
        d = json.load(f)
    equity = [p for p in d["positions"] if p["sleeve"] == "Equity"]
    total_aum = d.get("total_aum", sum(p["value"] for p in d["positions"]))
    return equity, total_aum


def read_fund_holdings():
    """Read top 10 holdings per equity fund."""
    with open(ROOT / "data" / "fund_holdings_top10.json", encoding="utf-8") as f:
        return json.load(f)


def fund_holdings_by_ticker(fund_data):
    """Holdings del fondo indexados por TICKER.

    BUGFIX 2026-08-25: antes esto leia `top_holdings`, que esta indexado por
    ticker pero SOLO tiene data para CSPX y THOR -- los otros 9 fondos quedaron
    con el dict vacio. Resultado: correr este script tiraba a MAGS (y HEWJ) del
    calculo, y MAGS tiene justo las 7 mega-caps del ACWI top 10 a ~14% cada una.
    El total de exposicion BIG caia de 14.13% a 11.64% y el dashboard reportaba
    13.1pp de underweight cuando el real era ~10.6pp.

    Ahora se usa `_factsheet_top10` (indexado por NOMBRE, con los 11 fondos) y
    cada nombre se resuelve a ticker con resolve_ticker(). Los nombres que no
    resuelven se devuelven aparte para poder reportarlos, en vez de perderse.
    """
    block = fund_data.get("_factsheet_top10")
    if not isinstance(block, dict) or not block:
        block = fund_data.get("top_holdings")
    if not isinstance(block, dict):
        return {}, []

    by_ticker = {}
    sin_resolver = []
    for raw, weight in block.items():
        if raw.startswith("_") or not isinstance(weight, (int, float)):
            continue
        tk = resolve_ticker(raw)
        if tk is None:
            sin_resolver.append(raw)
            continue
        # Un fondo puede listar el mismo ticker dos veces (distintas lineas);
        # se acumulan en vez de pisarse.
        by_ticker[tk] = by_ticker.get(tk, 0) + weight
    return by_ticker, sin_resolver


def compute_overlap():
    acwi_top10 = read_acwi_top10()
    equity_positions, total_aum = read_positions()
    fund_holdings = read_fund_holdings()

    # APPLES-TO-APPLES vs ACWI: pesar dentro del Equity Sleeve (100%), no sobre BIG total.
    # ACWI es 100% equity, asi que la comparacion correcta es contra el Equity Sleeve.
    total_equity_value = sum(p["value"] for p in equity_positions)

    # For each ACWI top 10 stock, sum BIG-equity exposure across all funds
    overlap = []
    total_acwi_top10 = sum(h["weight_acwi"] for h in acwi_top10)
    total_big_exposure = 0

    # Holdings por ticker de cada fondo, una sola vez
    por_fondo = {}
    sin_resolver = {}
    for pos in equity_positions:
        fd = fund_holdings.get(pos["ticker"])
        if not isinstance(fd, dict):
            print(f"  WARN: {pos['ticker']} esta en el sleeve pero no en "
                  f"fund_holdings_top10.json -> aporta 0")
            por_fondo[pos["ticker"]] = {}
            continue
        by_ticker, no_res = fund_holdings_by_ticker(fd)
        por_fondo[pos["ticker"]] = by_ticker
        if no_res:
            sin_resolver[pos["ticker"]] = no_res

    for acwi_holding in acwi_top10:
        ticker = acwi_holding["ticker"]
        big_exposure = 0
        contributors = []

        for pos in equity_positions:
            fund_ticker = pos["ticker"]
            # % del fondo DENTRO DEL EQUITY SLEEVE (100%), no sobre BIG total
            fund_weight_in_equity = pos["value"] / total_equity_value * 100

            stock_weight_in_fund = por_fondo.get(fund_ticker, {}).get(ticker, 0)
            if not isinstance(stock_weight_in_fund, (int, float)):
                continue

            # Contribution to Equity Sleeve = fund_weight_in_equity × stock_weight_in_fund / 100
            contribution = fund_weight_in_equity * stock_weight_in_fund / 100
            if contribution > 0:
                big_exposure += contribution
                contributors.append({
                    "fund": fund_ticker,
                    "fund_weight_in_equity_sleeve": round(fund_weight_in_equity, 2),
                    "stock_weight_in_fund": stock_weight_in_fund,
                    "contribution": round(contribution, 3),
                })

        overlap.append({
            "ticker": ticker,
            "name": acwi_holding["name"],
            "sector": acwi_holding["sector"],
            "location": acwi_holding["location"],
            "weight_acwi": acwi_holding["weight_acwi"],
            "weight_big": round(big_exposure, 3),
            "diff_pp": round(big_exposure - acwi_holding["weight_acwi"], 3),
            "contributors": contributors,
        })
        total_big_exposure += big_exposure

    # Chequeos ruidosos: si una fila del ACWI top 10 no matcheo con NINGUN fondo,
    # puede ser real (no la tenemos) o un nombre que no resolvio. Hay que poder
    # distinguirlo de un vistazo en vez de asumir que el 0 es correcto.
    huerfanas = [h["ticker"] for h in overlap if not h["contributors"]]
    if huerfanas:
        print(f"  NOTA: sin exposicion via ningun fondo: {huerfanas}")
    if sin_resolver:
        total_no_res = sum(len(v) for v in sin_resolver.values())
        print(f"  {total_no_res} holdings sin ticker resoluble (normal: solo importan "
              f"los que cruzan con el ACWI top 10)")

    summary = {
        "total_acwi_top10": round(total_acwi_top10, 2),
        "total_big_top10_exposure": round(total_big_exposure, 2),
        "diff_pp": round(total_big_exposure - total_acwi_top10, 2),
    }

    return overlap, summary


def main():
    overlap, summary = compute_overlap()

    print(f"\n{'=' * 110}")
    print(f"BIG LOOKTHROUGH vs ACWI TOP 10")
    print(f"{'=' * 110}")
    print(f"{'Ticker':8s} {'Name':35s} {'Sector':22s} {'ACWI %':>8s} {'BIG %':>8s} {'Diff (pp)':>11s}")
    print("-" * 110)
    for h in overlap:
        diff_sign = "+" if h["diff_pp"] >= 0 else ""
        print(f"{h['ticker']:8s} {h['name'][:35]:35s} {h['sector'][:22]:22s} "
              f"{h['weight_acwi']:>7.2f}% {h['weight_big']:>7.2f}% {diff_sign}{h['diff_pp']:>9.2f}pp")
    print("-" * 110)
    diff_sign = "+" if summary["diff_pp"] >= 0 else ""
    print(f"{'TOTAL':8s} {'':35s} {'':22s} "
          f"{summary['total_acwi_top10']:>7.2f}% {summary['total_big_top10_exposure']:>7.2f}% "
          f"{diff_sign}{summary['diff_pp']:>9.2f}pp")
    print()
    print(f"BIG esta {abs(summary['diff_pp']):.1f}pp {'UNDERWEIGHT' if summary['diff_pp'] < 0 else 'OVERWEIGHT'} en ACWI top 10 vs benchmark.")

    # Save JSON
    out_path = ROOT / "data" / "acwi_overlap.json"
    # BUGFIX 2026-08-25: refreshedAt estaba hardcodeado a "2026-05-12", asi que
    # cada corrida re-estampaba mayo y el archivo mentia sobre su propia edad.
    # as_of del factsheet de cada fondo del sleeve, para poder auditar de un
    # vistazo con que data se calculo (THOR y LGLI suelen ir atrasados).
    fund_holdings = read_fund_holdings()
    equity_positions, _ = read_positions()
    fund_asof = {}
    for pos in sorted(equity_positions, key=lambda p: p["ticker"]):
        fd = fund_holdings.get(pos["ticker"])
        if isinstance(fd, dict):
            fund_asof[pos["ticker"]] = fd.get("_as_of")
    out = {
        "refreshedAt": date.today().isoformat(),
        "fund_asof": fund_asof,
        "source": "ACWI holdings (iShares ACWI factsheet 24-Apr) + fund_holdings_top10.json (CSPX exact, UCITS estimates)",
        "method": "BIG_exposure[stock] = Σ (fund_weight_in_BIG × stock_weight_in_fund / 100)",
        "summary": summary,
        "overlap": overlap,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[OK] Saved to {out_path}")


if __name__ == "__main__":
    main()
