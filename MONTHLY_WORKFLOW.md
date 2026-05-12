# 📅 Workflow Mensual — BIG Dashboard

> Guía paso a paso para refresh mensual del HTML dashboard.

---

## 🎯 Día 1 del mes (después del cierre)

### Paso 1 — Manual drops (los que no se automatizan)

Dropeá los siguientes PDFs en sus carpetas (renombralos con la fecha):

**Privates (vienen por email):**
```
factsheets/alternatives/CALP_YYYYMMDD.pdf      # Carlyle
factsheets/alternatives/NBPEA_YYYYMMDD.pdf     # NB PE Access
factsheets/alternatives/FLEX_YYYYMMDD.pdf      # Flex-Lexington
factsheets/alternatives/HLEND_YYYYMMDD.pdf     # HPS Lending
factsheets/alternatives/BPCC_YYYYMMDD.pdf      # Barings BPCC
factsheets/alternatives/GCRED_YYYYMMDD.pdf     # Golub Capital
factsheets/fi/TGF_YYYYMMDD.pdf                 # Tenac
```

**URLs no encontradas (URL discovery pending):**
```
factsheets/equity/LGLI_YYYYMMDD.pdf           # Lazard Listed Infra
factsheets/equity/ARGT_YYYYMMDD.pdf           # Global X Argentina (small position)
factsheets/fi/MANIG_YYYYMMDD.pdf              # Man GLG IG Opps
factsheets/fi/SGCB_YYYYMMDD.pdf               # Schroder Cat Bond
```

### Paso 2 — Pedirme refresh PIMCO

```
"Refrescá los 3 PIMCO via Chrome MCP"
```

Yo:
1. Navego a las 3 páginas PIMCO via Chrome MCP
2. Extraigo YTW / Duration / Maturity / Current Yield / Countries / Sector duration
3. Guardo en data/funds/PIMCO-LD.json, PIMCO-INC.json, PIMCO-EM.json

### Paso 3 — Correr pipeline automatizado

```bash
$ python scripts/refresh_monthly.py
```

Esto:
- Descarga 7 fondos equity (CSPX, NBGMT, MFSCV, THOR, JHGSC, 4BRZ, ILF)
- Parsea TODOS los PDFs (auto + tus drops manuales)
- Agrega per-fund → BIG-level breakdowns
- Output: data/breakdowns/*.json
- Tiempo: ~5-10 seg

### Paso 4 — Deploy

```bash
Click cohete 🚀 (deploy.bat)
```

→ Push a GitHub → 1-2 min después la URL pública tiene todos los datos al mes.

---

## ⏱️ Tiempo total mensual

| Paso | Tu tiempo | Mi tiempo |
|---|---:|---:|
| 1. Drop manuales (7 privates + 4 sin URL) | 5 min (renombrar y arrastrar) | 0 |
| 2. PIMCO Chrome MCP | 30s (pedírmelo) | 2 min |
| 3. `refresh_monthly.py` | 1 seg (1 comando) | 10 seg automático |
| 4. Click cohete | 1 seg | 1-2 min GitHub |
| **TOTAL** | **~7 min activo** | **~5 min agente** |

---

## 📊 Cobertura del fondo BIG por categoría

| Sleeve | Auto | Chrome MCP | Manual drop | Email manual |
|---|:-:|:-:|:-:|:-:|
| Equity (29.5%) | 7 fondos (88%) | 0 | 2 (LGLI, ARGT) | 0 |
| Fixed Income (38.9%) | 0 | 3 PIMCO (66%) | 2 (MANIG, SGCB) | 1 (Tenac) |
| Alternatives (28.8%) | 0 | 0 | 0 | 6 privates |
| Cash (2.8%) | live Stooq | n/a | n/a | n/a |

---

## 🔍 Lo que NO está cubierto y por qué

- **IBIT, GLD:** son commodities/crypto, solo precio relevante (live via Stooq, no necesita factsheet)
- **Privates 6 fondos:** no publican factsheet web (legal/regulatorio en PE/PC)
- **URL discovery pendiente** (3-4 fondos): Lazard, Man GLG, Schroders, Global X — necesitan más búsqueda manual o sesión autenticada

---

## 🛠️ Scripts del pipeline

```
scripts/
├── refresh_monthly.py           # Master orchestrator
├── download_factsheets.py        # Auto-download (7 equity)
├── parse_factsheet.py            # Universal PDF parser
├── aggregate_breakdowns.py       # per-fund × Pershing weights → BIG
├── refresh_pimco.py              # Playwright (limited — use Chrome MCP via Claude instead)
├── lynk_nav_extractor.py         # Lynk NAV (separate)
├── pershing_parser.py            # Pershing Excel (when Lucas provides)
└── equity_returns_vs_acwi.py     # Lucas methodology Return vs ACWI
```

---

**Última actualización:** 2026-05-12
**Próxima revisión:** 1ro Junio 2026 (después del cierre Mayo)
