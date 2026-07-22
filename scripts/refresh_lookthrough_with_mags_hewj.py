"""
Refresh 4 JSONs de lookthrough Equity incorporando MAGS y HEWJ.

Approach: scaling incremental. Los 9 fondos originales (que ya están agregados
en los JSONs actuales) se re-escalan al nuevo peso en el sleeve (95.29% en vez
de 100%), y las contribuciones ponderadas de MAGS y HEWJ se suman por categoría.

Data MAGS (Roundhill Magnificent Seven, mid-Jul-26):
  META 15.4%, AAPL 15.1%, AMZN 14.2%, MSFT 14.2%, NVDA 14.0%, GOOGL 13.8%, TSLA 13.2%
  Sector: Tech 43.3% (AAPL+MSFT+NVDA), Comm 29.2% (META+GOOGL), Cons.Cyc 27.4% (AMZN+TSLA)
  Regional: 100% US, Style: Growth 90% / Blend 10%

Data HEWJ (iShares MSCI Japan Hedged, Jul-17-26) — es 99.81% EWJ:
  Top 10: Mitsubishi UFJ 4.64, Tokyo Electron 3.65, Toyota 3.43, Sumitomo Mitsui 3.05,
          Hitachi 2.61, Sony 2.53, SoftBank 2.52, Advantest 2.52, Mizuho 2.34, Recruit 2.12
  Sector: Tech 24.9, Industrials 22.85, Financial 17.63, Cons.Cyc 11.17, Comm 8.10,
          Health 5.25, Cons.Def 3.38, Basic Mat 3.08, Real Estate 1.85, Utilities 0.95, Energy 0.83
  Regional: 100% Japan, Style: Blend 60% / Value 25% / Growth 15%

Nuevos weights sleeve (11 fondos, del holdings_returns.json 2026-07-22):
  CSPX 32.00, NBGMT 16.56, MFSCV 14.35, THOR 7.24, JHGSC 6.58, LGLI 6.06,
  ARGT 4.39, 4BRZ 4.08, ILF 4.03, MAGS 2.39, HEWJ 2.33
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

DATA = Path(__file__).resolve().parents[1] / "data"
TODAY = "2026-07-22"

# Nuevos pesos del sleeve (%)
W = {
    "CSPX": 32.00, "NBGMT": 16.56, "MFSCV": 14.35, "THOR": 7.24, "JHGSC": 6.58,
    "LGLI": 6.06, "ARGT": 4.39, "4BRZ": 4.08, "ILF": 4.03, "MAGS": 2.39, "HEWJ": 2.33,
}
W_MAGS = W["MAGS"]
W_HEWJ = W["HEWJ"]
W_9_OLD_TOTAL = 100.0  # los 9 fondos del JSON viejo suman 100 (era el universo)
W_9_NEW_TOTAL = sum(W[k] for k in ("CSPX","NBGMT","MFSCV","THOR","JHGSC","LGLI","ARGT","4BRZ","ILF"))
SCALE = W_9_NEW_TOTAL / W_9_OLD_TOTAL  # 0.9528

print(f"[weights] 9 originales pesan {W_9_NEW_TOTAL:.2f}% del sleeve (antes 100%)")
print(f"[weights] MAGS {W_MAGS}% + HEWJ {W_HEWJ}% = {W_MAGS+W_HEWJ:.2f}%")
print(f"[weights] scale factor 9 originales = {SCALE:.4f}\n")

# === MAGS breakdowns ===
MAGS_STYLE      = {"Value": 0, "Growth": 90, "Blend": 10}
MAGS_SECTORIAL  = {"Technology": 43.3, "Comm. Serv.": 29.2, "Cons. Cyc.": 27.4}
MAGS_REGIONAL   = {"N. America": 100}
MAGS_TOP10 = {  # top holdings dentro del ETF
    "NVIDIA CORP": 14.0, "APPLE INC": 15.1, "MICROSOFT CORP": 14.2,
    "AMAZON.COM INC": 14.2, "ALPHABET INC CLASS A": 13.8,
    "META PLATFORMS INC CLASS A": 15.4, "TESLA INC": 13.2,
}

# === HEWJ breakdowns (via EWJ que es 99.81% del ETF) ===
HEWJ_STYLE      = {"Value": 25, "Growth": 15, "Blend": 60}
HEWJ_SECTORIAL  = {
    "Technology": 24.9, "Industrials": 22.85, "Financial": 17.63,
    "Cons. Cyc.": 11.17, "Comm. Serv.": 8.10, "Health": 5.25,
    "Cons. Def.": 3.38, "Basic Mat.": 3.08, "Real estate": 1.85,
    "Utilities": 0.95, "Energy": 0.83,
}
HEWJ_REGIONAL = {"Japan": 100}
HEWJ_TOP10 = {
    "Mitsubishi UFJ Financial Group": 4.64,
    "Tokyo Electron": 3.65,
    "Toyota Motor": 3.43,
    "Sumitomo Mitsui Financial Group": 3.05,
    "Hitachi": 2.61,
    "Sony Group": 2.53,
    "SoftBank Group": 2.52,
    "Advantest": 2.52,
    "Mizuho Financial Group": 2.34,
    "Recruit Holdings": 2.12,
}


def _rescaled(old_big: float, mags_pct: dict, hewj_pct: dict, category: str) -> float:
    """Rescale old_big (que asume 9 fondos = 100%) + sumar contribs MAGS/HEWJ.
    contrib = (weight_fondo / 100) × pct_categoria_en_fondo → resulta en pp del sleeve.
    """
    v = old_big * SCALE
    v += (W_MAGS / 100.0) * mags_pct.get(category, 0)
    v += (W_HEWJ / 100.0) * hewj_pct.get(category, 0)
    return round(v, 1)


def _normalize_rows(rows: list[dict], key: str, target_total: int = 100) -> list[dict]:
    """Ajusta la primera row para que el total llegue a exactamente 100 (evita
    round-up excess de 101/102 tras rescale). Cambio de <=0.5 en la row más grande."""
    total = sum(r[key] for r in rows)
    if abs(total - target_total) < 0.05:
        return rows
    delta = target_total - total
    # Aplicar delta a la row con valor más alto
    idx = max(range(len(rows)), key=lambda i: rows[i][key])
    rows[idx][key] = round(rows[idx][key] + delta, 1)
    return rows


# ============================================================
# 1. equity_breakdown_latest.json
# ============================================================
print("=" * 60)
print("1. equity_breakdown_latest.json")
print("=" * 60)
bd = json.load(open(DATA / "equity_breakdown_latest.json", encoding="utf-8"))

# STYLE
for r in bd["style"]["rows"]:
    r["big"] = _rescaled(r["big"], MAGS_STYLE, HEWJ_STYLE, r["category"])
_normalize_rows(bd["style"]["rows"], "big")
print("Style:", [(r["category"], r["big"]) for r in bd["style"]["rows"]])

# SECTORIAL
for r in bd["sectorial"]["rows"]:
    r["big"] = _rescaled(r["big"], MAGS_SECTORIAL, HEWJ_SECTORIAL, r["category"])
_normalize_rows(bd["sectorial"]["rows"], "big")
print("Sectorial:", [(r["category"], r["big"]) for r in bd["sectorial"]["rows"]])

# REGIONAL
for r in bd["regional"]["rows"]:
    r["big"] = _rescaled(r["big"], MAGS_REGIONAL, HEWJ_REGIONAL, r["category"])
_normalize_rows(bd["regional"]["rows"], "big")
print("Regional:", [(r["category"], r["big"]) for r in bd["regional"]["rows"]])

# Actualizar metadata
bd["asOf"] = TODAY
bd["source"] = bd.get("source", "") + f" | UPDATED {TODAY}: agregados MAGS + HEWJ via rescale + contribuciones ponderadas."
bd["verification"] = bd.get("verification", {})
bd["verification"]["sleeve_weights_used"] = {k: v / 100 for k, v in W.items()}
bd["verification"][f"refresh_{TODAY}"] = "Rescale 9 fondos originales × 0.9528 + MAGS (100% US, Growth) + HEWJ (100% Japan, Blend/Value)"

with open(DATA / "equity_breakdown_latest.json", "w", encoding="utf-8") as f:
    json.dump(bd, f, indent=2, ensure_ascii=False)
print(f"[OK] Saved equity_breakdown_latest.json")


# ============================================================
# 2. acwi_overlap.json
# ============================================================
print("\n" + "=" * 60)
print("2. acwi_overlap.json")
print("=" * 60)
ov = json.load(open(DATA / "acwi_overlap.json", encoding="utf-8"))

# MAGS names → ACWI overlap names
MAGS_NAME_TO_TICKER = {
    "NVIDIA CORP": "NVDA", "APPLE INC": "AAPL", "MICROSOFT CORP": "MSFT",
    "AMAZON.COM INC": "AMZN", "ALPHABET INC CLASS A": "GOOGL",
    "META PLATFORMS INC CLASS A": "META", "TESLA INC": "TSLA",
}
mags_stock_pct_by_ticker = {MAGS_NAME_TO_TICKER[k]: v for k, v in MAGS_TOP10.items()}

total_big = 0
for h in ov.get("overlap", []):
    tk = h["ticker"]
    # Rescale contributors originales (fund_weight_in_equity_sleeve) al nuevo peso
    new_contribs = []
    for c in h.get("contributors", []):
        fund = c["fund"]
        old_fw = c["fund_weight_in_equity_sleeve"]
        new_fw = W.get(fund, old_fw * SCALE)  # si el fondo está en W, usar peso exacto
        stock_w = c["stock_weight_in_fund"]
        c["fund_weight_in_equity_sleeve"] = new_fw
        c["contribution"] = round(new_fw * stock_w / 100, 3)
        new_contribs.append(c)
    # Agregar MAGS si es Mag7
    if tk in mags_stock_pct_by_ticker:
        stock_w = mags_stock_pct_by_ticker[tk]
        contribution = round(W_MAGS * stock_w / 100, 3)
        new_contribs.append({
            "fund": "MAGS",
            "fund_weight_in_equity_sleeve": W_MAGS,
            "stock_weight_in_fund": stock_w,
            "contribution": contribution,
        })
    h["contributors"] = new_contribs
    h["weight_big"] = round(sum(c["contribution"] for c in new_contribs), 3)
    h["diff_pp"] = round(h["weight_big"] - h["weight_acwi"], 3)
    total_big += h["weight_big"]

# Update summary
ov["summary"]["total_big_top10_exposure"] = round(total_big, 2)
ov["summary"]["diff_pp"] = round(total_big - ov["summary"]["total_acwi_top10"], 2)
ov["refreshedAt"] = TODAY
ov["source"] = ov.get("source", "") + f" | UPDATED {TODAY}: MAGS agregado como contributor a los 7 Mag stocks"

with open(DATA / "acwi_overlap.json", "w", encoding="utf-8") as f:
    json.dump(ov, f, indent=2, ensure_ascii=False)

print(f"BIG top 10 exposure: {ov['summary']['total_big_top10_exposure']}% (antes 12.45%)")
print(f"Diff (BIG - ACWI): {ov['summary']['diff_pp']}pp (antes -12.30pp)")
print(f"[OK] Saved acwi_overlap.json")


# ============================================================
# 3. fund_holdings_top10.json
# ============================================================
print("\n" + "=" * 60)
print("3. fund_holdings_top10.json")
print("=" * 60)
ft = json.load(open(DATA / "fund_holdings_top10.json", encoding="utf-8"))

ft["MAGS"] = {
    "_description": "Roundhill Magnificent Seven ETF — equal weight (~14.3%) rebalanced quarterly",
    "_as_of": "2026-07-15",
    "_factsheet_top10": {**MAGS_TOP10, "_note": "MAGS rebalancea a equal-weight cada trimestre. Data mid-Jul-26 (post-Jun rebalance)."},
    "name": "Roundhill Magnificent Seven ETF",
}
ft["HEWJ"] = {
    "_description": "iShares Currency Hedged MSCI Japan ETF — 99.81% EWJ (unhedged) + JPY hedge",
    "_as_of": "2026-07-17",
    "_factsheet_top10": {**HEWJ_TOP10, "_note": "Holdings desde EWJ (que HEWJ replica 99.81%). Top 10 aprox = 27.4% del NAV."},
    "name": "iShares Currency Hedged MSCI Japan ETF",
}
ft["_lastUpdate"] = TODAY

with open(DATA / "fund_holdings_top10.json", "w", encoding="utf-8") as f:
    json.dump(ft, f, indent=2, ensure_ascii=False)
print(f"Cards ahora: {[k for k in ft.keys() if not k.startswith('_')]}")
print(f"[OK] Saved fund_holdings_top10.json")


# ============================================================
# 4. equity_top10_consolidated.json
# ============================================================
print("\n" + "=" * 60)
print("4. equity_top10_consolidated.json (rescale + top holdings)")
print("=" * 60)
c = json.load(open(DATA / "equity_top10_consolidated.json", encoding="utf-8"))

# Rescale existing top 15
for h in c["consolidated_top10"]:
    h["weight_in_sleeve_pct"] = round(h["weight_in_sleeve_pct"] * SCALE, 2)

# Agregar contribuciones de MAGS a los Mag7
mag7_names_in_c = {  # nombres tal cual están en el JSON viejo
    "NVIDIA CORP": ["NVIDIA CORP", "NVIDIA"],
    "APPLE INC": ["APPLE INC"],
    "MICROSOFT CORP": ["MICROSOFT CORP", "MICROSOFT"],
    "AMAZON.COM INC": ["AMAZON.COM INC", "AMAZON"],
    "ALPHABET INC CLASS A": ["ALPHABET INC CLASS A", "GOOGL"],
    "META PLATFORMS INC CLASS A": ["META PLATFORMS INC CLASS A", "META"],
    "TESLA INC": ["TESLA INC", "TESLA"],
}
existing_upper = {h["name"].upper(): h for h in c["consolidated_top10"]}

for stock_name, mags_weight in MAGS_TOP10.items():
    aliases = mag7_names_in_c[stock_name]
    matched = None
    for alias in aliases:
        for k in existing_upper:
            if alias.upper() in k or k in alias.upper():
                matched = existing_upper[k]
                break
        if matched: break
    contribution = round(W_MAGS * mags_weight / 100, 3)
    if matched:
        matched["weight_in_sleeve_pct"] = round(matched["weight_in_sleeve_pct"] + contribution, 2)
        matched.setdefault("funds", []).append({
            "fund": "MAGS", "weight_in_fund": mags_weight
        })
    else:
        # No existía en top 15 previo — agregar como nuevo
        c["consolidated_top10"].append({
            "rank": 999,  # se re-rankeará al final
            "name": stock_name,
            "weight_in_sleeve_pct": contribution,
            "funds": [{"fund": "MAGS", "weight_in_fund": mags_weight}],
        })

# Agregar contribuciones HEWJ a top holdings de Japan (todas nuevas)
for stock_name, hewj_weight in HEWJ_TOP10.items():
    contribution = round(W_HEWJ * hewj_weight / 100, 3)
    # Chequear si ya está en consolidated (por ejemplo Toyota podría estar via NBGMT — inspeccionar)
    matched = None
    for h in c["consolidated_top10"]:
        if stock_name.upper() in h["name"].upper() or h["name"].upper() in stock_name.upper():
            matched = h
            break
    if matched:
        matched["weight_in_sleeve_pct"] = round(matched["weight_in_sleeve_pct"] + contribution, 2)
        matched.setdefault("funds", []).append({
            "fund": "HEWJ", "weight_in_fund": hewj_weight
        })
    else:
        c["consolidated_top10"].append({
            "rank": 999,
            "name": stock_name,
            "weight_in_sleeve_pct": contribution,
            "funds": [{"fund": "HEWJ", "weight_in_fund": hewj_weight}],
        })

# Reranking: sort desc por weight_in_sleeve_pct, tomar top 15
c["consolidated_top10"].sort(key=lambda h: -h["weight_in_sleeve_pct"])
c["consolidated_top10"] = c["consolidated_top10"][:15]
for i, h in enumerate(c["consolidated_top10"], start=1):
    h["rank"] = i

c["refreshedAt"] = TODAY
c["method"] = c.get("method", "") + f" | UPDATED {TODAY}: MAGS + HEWJ agregados como contributors."

with open(DATA / "equity_top10_consolidated.json", "w", encoding="utf-8") as f:
    json.dump(c, f, indent=2, ensure_ascii=False)

print("Top 15 consolidated after refresh:")
for h in c["consolidated_top10"]:
    funds_str = " · ".join(f"{f['fund']} {f['weight_in_fund']:.1f}%" for f in h.get("funds", []))
    print(f"  #{h['rank']:2d} {h['name'][:35]:35s} {h['weight_in_sleeve_pct']:>5.2f}%  via: {funds_str}")
print(f"[OK] Saved equity_top10_consolidated.json")

print("\n" + "=" * 60)
print("DONE — 4 JSONs actualizados con MAGS y HEWJ")
print("=" * 60)
