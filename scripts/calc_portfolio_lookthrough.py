"""
calc_portfolio_lookthrough.py
==============================
Calcula ponderados de portfolio BIG con:
- Sectorial RV (agregando look-through de fondos activos + ETFs)
- Regional RV
- Currency exposure total
- Rating breakdown RF
- Yield ponderado

Fuente pesos: positions_latest.json (al 30-Jun-2026)
Fuente look-through: data/factsheets_scraped/equity_factsheets_2026-06.json + fi_factsheets_2026-06.json
Fallback para holdings sin data: funds_metadata.js (CURRENCY_EXPOSURE / CURRENT_YIELD)

Output: JSON estructurado con todos los ponderados listos para el Factsheet.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("C:/Users/lmonp/OneDrive/Desktop/Code/big-dashboard")
POSITIONS = ROOT / "data/positions_latest.json"
EQ_JSON = ROOT / "data/factsheets_scraped/equity_factsheets_2026-06.json"
FI_JSON = ROOT / "data/factsheets_scraped/fi_factsheets_2026-06.json"
FUNDS_META = ROOT / "data/funds_metadata.js"
OUT = ROOT / "data/factsheets_scraped/portfolio_lookthrough_2026-06.json"


# Ticker -> ISIN mapping
TICKER_TO_ISIN = {
    "CSPX": "IE00B5BMR087", "NBGMT": "IE00BFMHRK20", "MFSCV": "LU1985812756",
    "THOR": "IE00B6YCBF59", "JHGSC": "LU2940405447", "LGLI": "IE00BF4KN675",
    "ARGT": "US37950E2596", "ILF": "US4642873909", "4BRZ": "DE000A0Q4R85",
    "CALP": "LU2827810776", "IBIT": "US46438F1012", "GLD": "US78463V1070",
    "HLEND": "KYG4737U1085", "BPCC": "XS2658535526", "FLEX": "LU2966298809",
    "HLGPI": "LU2847068389", "GCRED": "GCRED-I",
    "PIMCO-LD": "IE00BDT57R20", "PIMCO-INC": "IE00B87KCF77", "MANIG": "IE000OE87WX6",
    "PIMCO-EM": "IE00B29K0P99", "TGF": "XS2324777171", "SGCB": "LU2049315265",
    "MANEM": "IE00089T5MA6",
}

# Map factsheet regional -> categoria factsheet BIG (Nort Am/Latin Am/Europe dev/UK/Japan/China/Others)
def normalize_region(region_name: str) -> str:
    r = region_name.lower()
    if "north america" in r or "united states" == r or "canada" == r or "us " in r:
        return "North Am"
    if "united kingdom" == r or "uk" == r:
        return "UK"
    if "argentina" in r or "brazil" in r or "chile" in r or "mexico" in r or "colombia" in r or "peru" in r or "uruguay" in r or "latin" in r:
        return "Latin Am"
    if "japan" in r:
        return "Japan"
    if "china" in r:
        return "China"
    if "france" in r or "germany" in r or "netherlands" in r or "italy" in r or "spain" in r or "switzerland" in r or "sweden" in r or "portugal" in r or "denmark" in r or "continental europe" in r or "europe dev" in r:
        return "Europe dev"
    if "africa" in r or "middle east" in r:
        return "Africa/ME"
    if "asia" in r or "korea" in r or "australia" in r or "non-us developed" in r:
        return "Asia/Others dev"
    if "emerging" in r or "emrg" in r:
        return "EM Others"
    return "Others"


def normalize_sector(sector: str) -> str:
    """Normaliza sectores GICS a nombres factsheet BIG"""
    s = sector.lower()
    if "info" in s and "tech" in s: return "Technology"
    if "financ" in s: return "Financial"
    if "commun" in s or "telecom" in s: return "Comm. Serv."
    if "consumer disc" in s or "cons. cyc" in s or "cons cyc" in s: return "Cons. Cyc."
    if "consumer stap" in s or "cons. def" in s or "cons def" in s: return "Cons. Def."
    if "health" in s: return "Health"
    if "industri" in s: return "Industrials"
    if "utilit" in s: return "Utilities"
    if "material" in s or "basic mat" in s: return "Basic Mat."
    if "energy" in s: return "Energy"
    if "real estate" in s: return "Real Estate"
    if "cash" in s: return "Cash"
    return "Other"


def main():
    positions = json.loads(POSITIONS.read_text(encoding="utf-8"))
    eq_data = json.loads(EQ_JSON.read_text(encoding="utf-8"))
    fi_data = json.loads(FI_JSON.read_text(encoding="utf-8"))
    js = FUNDS_META.read_text(encoding="utf-8")

    # Parsear CURRENCY_EXPOSURE del funds_metadata.js (para Alts + fallback)
    cur_meta = {}
    m = re.search(r"const\s+CURRENCY_EXPOSURE\s*=\s*(\{.*?\});", js, re.DOTALL)
    if m:
        block = m.group(1)
        # Acepta tanto '...' como "..." para las keys
        for entry in re.finditer(
            r"['\"]([A-Z0-9-]+)['\"]\s*:\s*\{\s*exposures\s*:\s*\[(.*?)\]",
            block, re.DOTALL,
        ):
            isin = entry.group(1)
            exps = []
            for e in re.finditer(r"c\s*:\s*['\"]([^'\"]+)['\"]\s*,\s*p\s*:\s*([\d.]+)", entry.group(2)):
                exps.append((e.group(1), float(e.group(2))))
            cur_meta[isin] = exps

    yield_meta = {}
    m = re.search(r"const\s+CURRENT_YIELD\s*=\s*(\{.*?\});", js, re.DOTALL)
    if m:
        block = m.group(1)
        for entry in re.finditer(r"['\"]([A-Z0-9-]+)['\"]\s*:\s*\{\s*y\s*:\s*(null|[\d.]+)", block):
            isin = entry.group(1)
            y = None if entry.group(2) == "null" else float(entry.group(2))
            yield_meta[isin] = y

    print(f"Fund metadata: {len(cur_meta)} currency, {len(yield_meta)} yield entries")

    # Pesos actuales (30-Jun)
    total_aum = positions["total_aum"]
    weights = {}  # ticker -> pct
    sleeves = {}  # ticker -> sleeve
    for p in positions["positions"]:
        ticker = p.get("ticker", "")
        if not ticker or ticker == "CASH":
            continue
        weights[ticker] = p["value"] / total_aum * 100
        sleeves[ticker] = p.get("sleeve", "")

    print(f"\nAUM total: ${total_aum:,.2f}")
    print(f"Holdings con peso: {len(weights)}")

    # ============= SECTORIAL RV (solo equity sleeve) =============
    eq_tickers = [t for t, s in sleeves.items() if s == "Equity"]
    total_equity_pct = sum(weights[t] for t in eq_tickers)
    print(f"\nEquity sleeve: {len(eq_tickers)} holdings, {total_equity_pct:.2f}% del portfolio")

    sect_totals = defaultdict(float)
    sect_missing = []
    for t in eq_tickers:
        w = weights[t]
        eq_entry = eq_data["funds"].get(t)
        if not eq_entry or not eq_entry.get("sectorial"):
            sect_missing.append((t, w))
            continue
        for sec, pct in eq_entry["sectorial"].items():
            norm = normalize_sector(sec)
            # w es pct del BIG, pct es pct dentro del fondo
            sect_totals[norm] += w * pct / 100

    # Renormalizar a 100% (sobre lo cubierto)
    sect_covered = sum(sect_totals.values())
    print(f"  Sectorial RV cubierto: {sect_covered:.2f}% del portfolio")
    if sect_missing:
        print(f"  Missing sectorial:")
        for t, w in sect_missing:
            print(f"    - {t} ({w:.2f}%)")

    # Normalizar a % del equity sleeve
    sect_normalized = {}
    if total_equity_pct:
        for sec, v in sect_totals.items():
            sect_normalized[sec] = v / total_equity_pct * 100

    # ============= REGIONAL RV =============
    reg_totals = defaultdict(float)
    reg_missing = []
    for t in eq_tickers:
        w = weights[t]
        eq_entry = eq_data["funds"].get(t)
        if not eq_entry or not eq_entry.get("regional"):
            reg_missing.append((t, w))
            continue
        for reg, pct in eq_entry["regional"].items():
            norm = normalize_region(reg)
            reg_totals[norm] += w * pct / 100

    reg_normalized = {}
    if total_equity_pct:
        for reg, v in reg_totals.items():
            reg_normalized[reg] = v / total_equity_pct * 100

    # ============= CURRENCY (all holdings) =============
    cur_totals = defaultdict(float)
    cur_missing = []
    for t, w in weights.items():
        isin = TICKER_TO_ISIN.get(t)
        # 1) Buscar en factsheet scraped
        cur_from_fs = None
        if t in eq_data["funds"]:
            cur_from_fs = eq_data["funds"][t].get("currency")
        elif t in fi_data["funds"]:
            cur_from_fs = fi_data["funds"][t].get("currency")

        # 2) Fallback: funds_metadata.js
        if cur_from_fs and isinstance(cur_from_fs, dict):
            for c, pct in cur_from_fs.items():
                if isinstance(pct, (int, float)):
                    cur_totals[c] += w * pct / 100
        elif isin and isin in cur_meta:
            for c, pct in cur_meta[isin]:
                cur_totals[c] += w * pct / 100
        else:
            cur_missing.append((t, w))

    cur_sum = sum(cur_totals.values())
    cur_normalized = {c: v / cur_sum * 100 for c, v in cur_totals.items()} if cur_sum else {}

    # ============= YIELD PONDERADO (uses fi_metrics ytw + funds_metadata) =============
    y_totals = 0.0
    y_by_holding = []
    for t, w in weights.items():
        y_val = None
        # 1) fi_metrics.ytw en scraped
        if t in fi_data["funds"]:
            m = fi_data["funds"][t].get("fi_metrics")
            if m and m.get("ytw"):
                y_val = m["ytw"]
        # 2) fallback funds_metadata
        if y_val is None:
            isin = TICKER_TO_ISIN.get(t)
            if isin and isin in yield_meta:
                y_val = yield_meta[isin]
        if y_val:
            contrib = w * y_val / 100
            y_totals += contrib
            y_by_holding.append({"ticker": t, "weight": round(w, 2), "yield": y_val, "contrib": round(contrib, 4)})

    # ============= RATING BREAKDOWN RF =============
    fi_tickers = [t for t, s in sleeves.items() if s == "Fixed Income"]
    total_fi_pct = sum(weights[t] for t in fi_tickers)
    rating_totals = defaultdict(float)
    rating_missing = []
    for t in fi_tickers:
        w = weights[t]
        fi_entry = fi_data["funds"].get(t)
        if not fi_entry or not fi_entry.get("rating_breakdown"):
            rating_missing.append((t, w))
            continue
        for rat, pct in fi_entry["rating_breakdown"].items():
            if isinstance(pct, (int, float)):
                rating_totals[rat] += w * pct / 100

    rating_normalized = {}
    if total_fi_pct:
        rating_covered = sum(rating_totals.values())
        for r, v in rating_totals.items():
            rating_normalized[r] = v / total_fi_pct * 100

    # ============= OUTPUT =============
    out = {
        "as_of": "2026-06-30",
        "total_aum": total_aum,
        "total_equity_pct": round(total_equity_pct, 2),
        "total_fi_pct": round(total_fi_pct, 2),
        "sectorial_rv": {k: round(v, 2) for k, v in sorted(sect_normalized.items(), key=lambda x: -x[1])},
        "regional_rv": {k: round(v, 2) for k, v in sorted(reg_normalized.items(), key=lambda x: -x[1])},
        "currency_portfolio": {k: round(v, 2) for k, v in sorted(cur_normalized.items(), key=lambda x: -x[1])},
        "current_yield_weighted": round(y_totals, 2),
        "yield_by_holding": y_by_holding,
        "rating_rf": {k: round(v, 2) for k, v in sorted(rating_normalized.items(), key=lambda x: -x[1])},
        "gaps": {
            "sectorial_rv_missing": [{"ticker": t, "weight": round(w, 2)} for t, w in sect_missing],
            "regional_rv_missing": [{"ticker": t, "weight": round(w, 2)} for t, w in reg_missing],
            "currency_missing": [{"ticker": t, "weight": round(w, 2)} for t, w in cur_missing],
            "rating_rf_missing": [{"ticker": t, "weight": round(w, 2)} for t, w in rating_missing],
        },
    }

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nGuardado: {OUT.name}")

    print(f"\n=== SECTORIAL RV (Equity sleeve, look-through pesos 30-Jun) ===")
    for sec, v in sorted(out["sectorial_rv"].items(), key=lambda x: -x[1])[:12]:
        print(f"  {sec:15s}: {v:>5.2f}%")

    print(f"\n=== REGIONAL RV ===")
    for reg, v in sorted(out["regional_rv"].items(), key=lambda x: -x[1])[:10]:
        print(f"  {reg:20s}: {v:>5.2f}%")

    print(f"\n=== CURRENCY PORTFOLIO ===")
    for c, v in sorted(out["currency_portfolio"].items(), key=lambda x: -x[1])[:12]:
        print(f"  {c:10s}: {v:>5.2f}%")

    print(f"\n=== CURRENT YIELD PONDERADO: {out['current_yield_weighted']:.2f}% ===")

    if out["rating_rf"]:
        print(f"\n=== RATING RF (parcial - solo cobertura FI) ===")
        for r, v in sorted(out["rating_rf"].items(), key=lambda x: -x[1])[:8]:
            print(f"  {r:10s}: {v:>5.2f}%")

    # Gaps
    if any(out["gaps"].values()):
        print(f"\n=== GAPS ===")
        for key, gaps in out["gaps"].items():
            if gaps:
                print(f"  {key}:")
                for g in gaps:
                    print(f"    {g['ticker']} ({g['weight']:.2f}%)")


if __name__ == "__main__":
    main()
