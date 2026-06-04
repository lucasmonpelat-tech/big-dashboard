# 🐛 Parser bugs — monthly-breakdowns workflow

Status: PENDIENTE (Lucas decidió no arreglar por ahora, no son blockers)

## Origen
Workflow `monthly-breakdowns.yml` corre día 15 de cada mes.
Disparado manual primera vez 2026-06-04. Fact sheets parseados: ACWI + AGG (Marzo 31, 2026).

## Bugs detectados en run #1 (2026-06-04)

### `fetch_acwi_breakdowns.py` — geographic
- Una key dice `"Holdings are subject to change. Germany"` → el regex está capturando texto de footnote como si fuera país
- Faltan países: China (2.87%), Taiwan (2.54%), France (2.27%), Switzerland (2.09%)
- **Fix probable**: filtrar líneas que contengan "Holdings are subject to change" o `Allocations are subject to change` antes del regex de país. Y revisar threshold de "Other" para no cortar la lista prematuramente.

### `fetch_agg_breakdowns.py` — credit_ratings ⚠️ MÁS CRÍTICO
- Regex no encuentra la tabla CREDIT RATINGS
- Output: `credit_ratings: {}`
- **Datos reales del fact sheet** (Mar 31, 2026):
  - Cash and/or Derivatives: 0.79
  - AAA Rated: 2.28
  - AA Rated: 73.34
  - A Rated: 11.93
  - BBB Rated: 11.66
  - BB Rated: 0.00
  - Not Rated: 0.00

### `fetch_agg_breakdowns.py` — sectors ⚠️
- Regex no encuentra la tabla TOP SECTORS
- Output: `sectors: {}`
- **Datos reales del fact sheet** (Mar 31, 2026):
  - Treasury: 46.09
  - MBS Pass-Through: 23.70
  - Industrial: 14.16
  - Financial Institutions: 7.88
  - Utility: 2.45
  - CMBS: 1.42
  - Sovereign: 1.03
  - Other: 0.95
  - Supranational: 0.92
  - Cash and/or Derivatives: 0.79
  - Local Authority: 0.60

### `fetch_agg_breakdowns.py` — maturity (menor)
- "20+ Years" devuelve 5.26 (confunde con "15-20 Years")
- **Valor real**: 10.19

## Impacto
- Pitch Book S10 chart idx 45 (Calidad Crediticia ACWI) → se queda sin data fresca del AGG (mantiene Abril)
- Pitch Book S10 chart idx 46 (Sectorial RF ACWI) → idem
- **Mientras tanto**: el `compute_fi_subasset.py` (que sí funciona, suma 99.98%) cubre el BIG-side

## Cuándo arreglar
Cuando Lucas tenga tiempo o cuando alguien se queje del breakdown ACWI/AGG en el pitch book.

Los datos hardcoded en el lookup table FI ya cubren el chart Sectorial RF BIG (lo más visible).
