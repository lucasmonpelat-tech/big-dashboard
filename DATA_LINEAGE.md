# 🗺️ DATA LINEAGE — BIG Fund Dashboard

> Documento maestro: cada métrica del HTML, su fuente primaria, método de refresh y frecuencia esperada.
> **Regla de oro:** ningún dato del HTML proviene de Maximus. Solo primary sources.

---

## 🎨 Status Codes

| Estado | Significado |
|---|---|
| 🟢 LIVE | Auto-refresh en cada apertura del dashboard |
| 🟡 ON-DEMAND | Lucas pide refresh, yo ejecuto via Chrome MCP / script |
| 🟠 SCHEDULED | Refresh manual con frecuencia esperada |
| 🔴 STALE | Excede frecuencia esperada — necesita refresh ya |

---

## 📑 Catálogo de Fuentes

### 1. **Lynk Markets** (`app.lynkmarkets.com`)
- **Tipo:** API pública (link público al producto BIG)
- **Refresh:** Diario (automatizable)
- **Refresh actual:** ON-DEMAND vía Chrome MCP
- **Provee:** NAV oficial, AUM, YTD, SI, Annualized, Volatility, Sharpe, serie diaria de NAV desde 30-Jun-25
- **Files generados:**
  - `data/lynk_data.json` (snapshot métricas)
  - `data/lynk_nav_series.json` (serie completa)
- **Script:** `scripts/lynk_nav_extractor.py` (Playwright) o Chrome MCP directo

### 2. **Pershing** (custodial, Excel manual)
- **Tipo:** Manual (Lucas descarga Excel)
- **Refresh:** Semanal (positions) + Mensual (transactions)
- **Provee:**
  - `Positions_JXD101380.xlsx` → composición actual del portfolio
  - `Transactions_JXD101380 History.xlsx` → historial de trades para TWR real
- **Files generados:**
  - `data/positions_latest.json` (parsed)
  - `data/equity_sleeve_real.json` (TWR real)
  - `data/equity_contributions_real.json` (real holding contributions)
- **Script:**
  - `scripts/pershing_parser.py` (positions)
  - `scripts/portfolio_reconstructor.py` (transactions → TWR)
  - `scripts/holding_contributions_real.py` (per-holding TWR contribs)

### 3. **baha.com**
- **Tipo:** Web scraping con login (Chrome MCP)
- **Refresh:** Mensual (precios) + cada 1-2 días para spot prices
- **Provee:**
  - Precios diarios UCITS (PIMCO, Man, Schroder, Tenac, MFS, NB, Janus, Lazard, Thornburg)
  - Monthly returns históricos por fondo
- **Files generados:**
  - `data/baha/<ISIN>.json` (per-fund history)
  - `data/live_prices.js` MANUAL_NAV section
- **Refresh:** Chrome MCP on-demand

### 4. **Stooq.com** (`stooq.com/q/l/`)
- **Tipo:** API CSV pública, sin auth
- **Refresh:** Cada apertura del dashboard (auto via JS)
- **Provee:** Precios diarios de ETFs US-listed (CSPX, ILF, ARGT, GLD, IBIT, 4BRZ, BDCs)
- **Files generados:** Ninguno (in-memory, llamada cada apertura)
- **Script:** `data/live_prices.js` (función `fetchAllLivePrices()`)

### 5. **PIMCO website** (`pimco.com/sg/en` o `pimco.com/gb/en`)
- **Tipo:** Web scraping (Chrome MCP)
- **Refresh:** Trimestral (PIMCO publica end-of-quarter)
- **Provee:** YTW, Effective Duration, Effective Maturity, Current Yield, Underlying Portfolio Yield, sector breakdown, country breakdown, credit quality, top 10 holdings
- **Para:** PIMCO Income, PIMCO LD, PIMCO EM Local
- **Files generados:**
  - `data/funds_metadata.js` → FI_METRICS y CURRENT_YIELDS
- **Refresh:** Chrome MCP on-demand (próx update factsheets ~10-15 May para Q1)

### 6. **FT.com Markets** (`markets.ft.com/data/funds/tearsheet/`)
- **Tipo:** Web scraping (Chrome MCP)
- **Refresh:** Mensual
- **Provee:** Regional breakdown, sector breakdown, top holdings, fund summary stats
- **Para todos los UCITS:** NBGMT, MFSCV, THOR, JHGSC, LGLI
- **Files generados:** Alimenta `data/equity_breakdown_apr26.json`
- **Refresh:** Chrome MCP on-demand

### 7. **iShares website**
- **Tipo:** Web scraping public (Chrome MCP o WebFetch)
- **Refresh:** Mensual
- **Provee:** Holdings, sector breakdown para ETFs iShares (CSPX, 4BRZ, ILF)

### 8. **Global X / Other ETF issuers**
- Para ARGT y otros ETFs específicos
- Web scraping on-demand

### 9. **Yahoo Finance** (`yfinance` Python lib)
- **Tipo:** Python library
- **Refresh:** On-demand (cada vez que corre equity_race.py / fi_race.py)
- **Provee:** Precios diarios de ACWI, AGG (benchmarks), proxies
- **Files generados:**
  - `data/equity_race.json` (BIG sleeve vs ACWI)
  - `data/fi_race.json` (BIG FI vs AGG)
- **Scripts:** `scripts/equity_race.py`, `scripts/fi_race.py`

### 10. **Manual (Tenac, Carlyle, Flex-Lex, NB PE, BPCC, HLEND, GCRED)**
- **Tipo:** Email / contacto directo con manager
- **Refresh:** Mensual o trimestral (depende del fondo)
- **Provee:** NAV de privates/iliquids
- **Files generados:** `data/funds_metadata.js` (BIG_POSITIONS values manuales)

---

## 📊 Mapeo HTML → Source

### Tab: 📊 Overview
| Métrica | Source | File | Refresh ideal | Status |
|---|---|---|---|---|
| NAV BIG | Lynk | lynk_data.json | Diario | 🟡 |
| AUM BIG | Lynk | lynk_data.json | Diario | 🟡 |
| YTD / SI / Annualized | Lynk | lynk_data.json | Diario | 🟡 |
| Volatility / Sharpe | Lynk | lynk_data.json | Diario | 🟡 |

### Tab: 💼 Positions
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Holdings list (24 posiciones) | Pershing | positions_latest.json + funds_metadata.js | Semanal | 🟠 |
| Live ETF prices | Stooq | (in-memory) | Cada apertura | 🟢 |
| UCITS NAV | baha | live_prices.js MANUAL_NAV | Semanal | 🟠 |
| TER cada fondo | funds_metadata.js | static + funds metadata | Trimestral | 🟠 |

### Tab: 💱 Currency
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Currency exposure agregada | computed | live (BIG_POSITIONS × CURRENCY_EXPOSURE) | Live | 🟢 |
| **CURRENCY_EXPOSURE per fund** | factsheets | funds_metadata.js | Trimestral | 🔴 STALE (~6 meses) |

### Tab: 🌍 Geography
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Country exposure aggregated | computed | live | Live | 🟢 |
| **COUNTRY_EXPOSURE per fund** | factsheets | funds_metadata.js | Trimestral | 🔴 STALE |

### Tab: 💰 Yield
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Weighted yield del portfolio | computed | live (BIG_POSITIONS × CURRENT_YIELDS) | Live | 🟢 |
| CURRENT_YIELDS per fund | PIMCO website + factsheets | funds_metadata.js | Trimestral | 🟠 (PIMCO 31-Mar) |

### Tab: 📈 YTM / FI
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Weighted YTW / Dur / Venc | computed | live (BIG_POSITIONS × FI_METRICS) | Live | 🟢 |
| FI_METRICS per fund | PIMCO website | funds_metadata.js | Trimestral | 🟠 (PIMCO 31-Mar; Man/Schroder/Tenac flagged verify) |

### Tab: 📉 Performance
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| NAV chart (Jul-25 → hoy) | Lynk | lynk_nav_series.json | Diario | 🟡 |

### Tab: 📝 Trade Log
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Trades hardcoded | inline JS | dashboard.js | Manual | 🔴 NEEDS AUTOMATION |

### Tab: 🏁 Equity Race
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| Multi-period returns | Yahoo (ACWI) + baha | equity_race.json | Mensual | 🟢 (5-May) |
| Sleeve TWR REAL | Pershing transactions | equity_sleeve_real.json | Mensual | 🟡 (27-Apr) |
| Real Holding Contributions | Computed from above | equity_contributions_real.json | Mensual | 🟡 (6-May) |
| Backtest contributions | computed | live | Live | 🟢 |
| Equity Breakdown (style/sector/regional) | FT.com per fund | equity_breakdown_apr26.json | Mensual | 🟢 (regional 7-May PRIMARY; sectorial pending) |

### Tab: 💎 FI Race
| Métrica | Source | File | Refresh | Status |
|---|---|---|---|---|
| FI sleeve vs AGG | yfinance + baha | fi_race.json | Mensual | 🟢 (5-May) |
| FI Sleeve REAL TWR | NO existe | — | — | 🔴 NEEDS BUILD |
| FI Holding Contributions REAL | NO existe | — | — | 🔴 NEEDS BUILD |
| FI Breakdown | factsheets | fi_breakdown_apr26.json | Mensual | 🔴 STALE (Maximus deprecated, rebuild pending) |

---

## 🚦 Refresh Schedule Sugerido

| Frecuencia | Source / File | Quien lo dispara |
|---|---|---|
| **Diario** | Lynk NAV (lynk_data.json + lynk_nav_series.json) | Lucas pide o automático mañana via cron |
| **Semanal** | Pershing positions Excel | Lucas exporta lunes y me pasa |
| **Mensual** | Pershing transactions Excel + factsheets via FT.com | Lucas exporta cierre de mes |
| **Trimestral** | PIMCO website FI_METRICS + CURRENT_YIELDS + CURRENCY/COUNTRY exposure per fund | Lucas pide cuando sale factsheet (~15 días post-cierre Q) |
| **Live** | Stooq ETF prices, todos los cómputos derivados | Auto en cada apertura del HTML |

---

## 🔧 Refresh Scripts Disponibles

| Script | Qué hace | Frecuencia | Source |
|---|---|---|---|
| `scripts/lynk_nav_extractor.py` | Extrae NAV serie diaria de Lynk | Diario | Lynk public |
| `scripts/pershing_parser.py` | Parsea Positions Excel → JSON | Semanal | Pershing Excel |
| `scripts/portfolio_reconstructor.py` | Reconstruye sleeve TWR desde Transactions | Mensual | Pershing Trans Excel |
| `scripts/holding_contributions_real.py` | Computa per-holding TWR contributions | Mensual | equity_sleeve_real.json |
| `scripts/equity_race.py` | BIG equity vs ACWI multi-period | Mensual | baha + yfinance |
| `scripts/fi_race.py` | BIG FI vs AGG | Mensual | baha + yfinance |
| `scripts/price_refresher.py` | Stooq prices wrapper | On-demand | Stooq |
| `scripts/refresh_all.py` | Master script | On-demand | All |

---

## 🚧 Pendientes (Phase 2-3)

### Datos
- [ ] **CURRENCY_EXPOSURE per fund** — refresh desde factsheets (6 meses old)
- [ ] **COUNTRY_EXPOSURE per fund** — refresh desde factsheets
- [ ] **Equity SECTORIAL breakdown** — primary desde FT.com per fund (regional ya hecho)
- [ ] **Equity STYLE box** — Morningstar style box por fondo
- [ ] **FI Credit Quality** — desde factsheets PIMCO/Man/Schroder
- [ ] **FI Sub-asset class** — desde factsheets PIMCO
- [ ] **FI_METRICS Man GLG / Schroder / Tenac** — flagged "verify"

### Builds nuevos
- [ ] **FI Sleeve REAL TWR** — extender portfolio_reconstructor.py para FI
- [ ] **FI Holding Contributions REAL** — mismo proceso que equity
- [ ] **Trade Log auto** — parsear Transactions Excel
- [ ] **Tab Data Health** — visualización del status de cada source

### Automation
- [ ] **Cron diario:** Lynk NAV refresh automático
- [ ] **Refresh script per source** — `refresh_lynk.py`, `refresh_baha.py`, `refresh_pimco.py`, `refresh_ftcom.py`

---

**Last update:** 2026-05-07
**Next review:** Cuando completemos Phase 2 (sectorial + FI breakdowns desde primary)
