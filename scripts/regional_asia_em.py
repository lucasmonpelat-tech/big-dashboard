# -*- coding: utf-8 -*-
"""
regional_asia_em.py
===================
Agrega la fila "Asia EM" al bloque Regional de data/equity_breakdown_latest.json
(widget "Estilo / Sectorial / Regional" del tab Equity), restandola de "Otros".

POR QUE EXISTE (2026-11-11, pedido de Lucas)
--------------------------------------------
El regional que publica Maximus tiene 6 categorias (N. America, Europe dev.,
LatAm, UK, Japan, Otros) y NO separa Asia emergente: esta adentro de "Otros", al
igual que Australasia, Medio Oriente, Asia desarrollada y el cash. Para BIG el
Asia EM es una cuenta que no existe en ninguna fuente, asi que se calcula aca.

COMO SE CALCULA
---------------
ACWI (exacto): suma de las posiciones de renta variable del iShares ACWI
  (data/acwi_holdings/acwi_holdings.csv, columna Location) en China, Taiwan,
  Korea (South), India, Thailand, Malaysia, Indonesia y Philippines (el bloque
  Asia de MSCI Emerging Markets), normalizada al total de renta variable.

BIG (PISO, no exacto): look-through con lo que cada fondo PUBLICA.
  - Fondos con top 10 por empresa (data/fund_holdings_top10.json): se suman las
    empresas de Asia EM del top 10 (hoy: Wuxi y Alibaba en NB Megatrends; TSMC y
    Samsung en Thornburg).
  - EMXC: ETF pasivo, se usa el % de Asia EM de su ficha (data/funds/EMXC.json).
  - Todo lo que esta fuera del top 10 de un fondo activo NO se cuenta: por eso es
    un piso. No se estima nada que el fondo no haya publicado.
  Los pesos de cada fondo en el sleeve son los del canonical de la fecha asOf del
  archivo (no los de hoy), para que sea coherente con el resto del bloque.

El monto de Asia EM se resta de "Otros" (los totales no cambian). Es idempotente:
si la fila ya existe, se recalcula y se vuelve a restar sobre el "Otros" original.

Uso:
    python scripts/regional_asia_em.py            # escribe
    python scripts/regional_asia_em.py --dry-run  # solo muestra
Correr SIEMPRE despues de refrescar equity_breakdown_latest.json (mensual).
"""
from __future__ import annotations
import argparse, csv, io, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BREAKDOWN = DATA / "equity_breakdown_latest.json"
LABEL = "Asia EM"

ACWI_LOCATIONS = ["China", "Taiwan", "Korea (South)", "India", "Thailand", "Malaysia", "Indonesia", "Philippines"]
# Codigos de pais de las fichas (data/funds) que son Asia EM
FICHA_CODES = {"CN", "TW", "KR", "IN", "TH", "MY", "ID", "PH"}
# Empresas de Asia EM en los top 10 (nombre tal cual esta en _factsheet_top10)
ASIA_EM_NAMES = re.compile(
    r"(?i)taiwan_semi|^tsmc|samsung|sk_?hynix|alibaba|tencent|wuxi|byd|baidu|jd\.?com|pdd|meituan|"
    r"reliance|infosys|hdfc|icici|tata|mediatek|hon_?hai|xiaomi|naver|hyundai|netease|ping_?an|"
    r"china_|zomato|bharti|larsen|coupang|^kia")


def acwi_asia_em():
    """(% normalizado a renta variable, fecha de holdings, fuente)."""
    p = DATA / "acwi_holdings" / "acwi_holdings.csv"
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    fecha = next((re.search(r'"([^"]+)"', l).group(1) for l in lines if l.startswith("Fund Holdings as of")), "?")
    i = next(k for k, l in enumerate(lines) if l.startswith("Ticker,"))
    rows = [r for r in csv.DictReader(io.StringIO("\n".join(lines[i:]))) if r.get("Asset Class") == "Equity"]

    def w(r):
        try:
            return float(r["Weight (%)"].replace(",", ""))
        except Exception:
            return 0.0
    total = sum(w(r) for r in rows)
    asia = sum(w(r) for r in rows if r.get("Location") in ACWI_LOCATIONS)
    return asia / total * 100, fecha, "iShares ACWI holdings (Location), equity normalizado"


def sleeve_weights(as_of: str):
    """Pesos del sleeve Equity en el ultimo canonical <= as_of."""
    dirs = sorted(d.name for d in (DATA / "canonical").iterdir()
                  if d.is_dir() and d.name <= as_of and (d / "holdings_returns.json").exists())
    d = dirs[-1]
    doc = json.loads((DATA / "canonical" / d / "holdings_returns.json").read_text(encoding="utf-8"))
    hs = [h for h in doc["sleeves"]["equity"]["holdings"] if (h.get("status") or "OPEN") == "OPEN" and h.get("mv_usd")]
    tot = sum(h["mv_usd"] for h in hs)
    return {h["ticker"]: h["mv_usd"] / tot * 100 for h in hs}, d


def big_asia_em(as_of: str):
    W, canon = sleeve_weights(as_of)
    top10 = json.loads((DATA / "fund_holdings_top10.json").read_text(encoding="utf-8"))
    detalle, total = [], 0.0
    for tk, w in sorted(W.items(), key=lambda kv: -kv[1]):
        pct_fondo, fuente = 0.0, ""
        if tk == "EMXC":
            f = json.loads((DATA / "funds" / "EMXC.json").read_text(encoding="utf-8"))
            pct_fondo = sum(v for k, v in (f.get("countries") or {}).items() if k in FICHA_CODES)
            fuente = "ficha EMXC (paises)"
        else:
            names = (top10.get(tk) or {}).get("_factsheet_top10") or {}
            hits = {n: v for n, v in names.items() if ASIA_EM_NAMES.search(n)}
            pct_fondo = sum(hits.values())
            fuente = "top 10: " + ", ".join(f"{n} {v}" for n, v in hits.items()) if hits else ""
        if pct_fondo:
            c = w * pct_fondo / 100
            total += c
            detalle.append({"fondo": tk, "peso_sleeve_pct": round(w, 2), "asia_em_en_fondo_pct": round(pct_fondo, 2),
                            "aporte_pp": round(c, 2), "fuente": fuente,
                            "top10_as_of": (top10.get(tk) or {}).get("_as_of")})
    return total, detalle, canon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    bd = json.loads(BREAKDOWN.read_text(encoding="utf-8"))
    reg = bd["regional"]
    rows = reg["rows"]
    as_of = bd.get("asOf") or bd.get("as_of")

    acwi, acwi_fecha, acwi_fuente = acwi_asia_em()
    big, detalle, canon = big_asia_em(as_of)
    big, acwi = round(big, 2), round(acwi, 2)

    otros = next(r for r in rows if r["category"] == "Otros")
    previa = next((r for r in rows if r["category"] == LABEL), None)
    otros_big0 = round(otros["big"] + (previa["big"] if previa else 0), 2)
    otros_acwi0 = round(otros["acwi"] + (previa["acwi"] if previa else 0), 2)
    if big > otros_big0 or acwi > otros_acwi0:
        raise SystemExit(f"ERROR: Asia EM (BIG {big} / ACWI {acwi}) supera 'Otros' ({otros_big0} / {otros_acwi0}). No se escribe.")

    nueva = {"category": LABEL, "big": big, "acwi": acwi}
    rows[:] = [r for r in rows if r["category"] != LABEL]
    rows.insert(rows.index(otros), nueva)
    otros["big"], otros["acwi"] = round(otros_big0 - big, 2), round(otros_acwi0 - acwi, 2)

    reg["asia_em"] = {
        "definicion": "China, Taiwan, Corea, India, Tailandia, Malasia, Indonesia y Filipinas (bloque Asia de MSCI EM). Se resta de 'Otros'.",
        "acwi": {"valor": acwi, "fuente": acwi_fuente, "holdings_al": acwi_fecha},
        "big": {"valor": big, "tipo": "PISO (solo lo que cada fondo publica en su top 10 + EMXC)", "pesos_canonical": canon, "detalle": detalle,
                "no_incluye": "Janus Henderson y las posiciones fuera del top 10 de NB Megatrends y Thornburg (fondos activos que no publican el resto)."},
        "otros_original": {"big": otros_big0, "acwi": otros_acwi0},
    }
    base = (reg.get("footnote") or "").strip()
    base = re.sub(r"\s*\|?\s*Asia EM:.*$", "", base)
    base = base.replace("Otros incluye Asia EM y ME (NBGMT)", "Otros incluye ME (NBGMT)")
    reg["footnote"] = (base + " | Asia EM: BIG es un PISO (top 10 de NB y Thornburg + EMXC; no incluye Janus ni el resto de cada fondo activo); "
                       f"ACWI exacto de iShares al {acwi_fecha}. Se resta de Otros.").strip(" |")

    print(f"Asia EM  BIG {big}% (piso)  |  ACWI {acwi}%  |  Otros BIG {otros_big0} -> {otros['big']}  ACWI {otros_acwi0} -> {otros['acwi']}")
    for d in detalle:
        print(f"   {d['fondo']:6} peso sleeve {d['peso_sleeve_pct']:5.2f}% x {d['asia_em_en_fondo_pct']:5.2f}% = {d['aporte_pp']:.2f}pp  ({d['fuente']})")
    print("   suma BIG:", round(sum(r['big'] for r in rows), 2), "| suma ACWI:", round(sum(r['acwi'] for r in rows), 2))
    if a.dry_run:
        print("--dry-run: no se escribio nada")
        return
    BREAKDOWN.write_text(json.dumps(bd, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Escrito:", BREAKDOWN)


if __name__ == "__main__":
    main()
