# Dashboard V2 - BIG Fund

Arquitectura limpia por capas. Cada capa tiene UNA sola responsabilidad.

## 🏗️ Capas

```
ingest/         → Layer 1: scrapers puros (Playwright, requests)
                  Solo descarga raw data, no procesa nada.
                  Guarda snapshots inmutables en data/raw/YYYY-MM-DD/

transform/      → Layer 2: raw → canonical
                  Toma raw data + valida + calcula + normaliza.
                  Output: data/canonical/*.json regenerable desde raw.

canonical/      → Layer 3: schemas + validators
                  Define el shape de los JSONs canónicos.

presentation/   → Layer 4: HTML/JS puro
                  Solo lee canonical, NO hace cálculos.

tests/          → Unit tests de transform + validators
```

## 📜 Reglas duras

1. Cada capa hace UNA cosa
2. Snapshots inmutables (raw del día D no se re-escribe nunca)
3. Canonical regenerable desde raw (idempotencia)
4. Validators automáticos en cada canonical
5. Trazabilidad: cada número tiene un `source` field
6. Sin cálculos en JavaScript client-side
7. Testing en transform layer

## 🎯 Tabs prioridad

1. Overview (NAV, AUM, YTD, SI)
2. Positions (cost basis + PnL)
3. PnL Timeline
4. Rendimientos vs benchmark
5. Currency + Sectorial + Regional
6. Costos totales
7. Historia BIG

## 🔍 Fuentes

- **Pershing NetX360+**: cost basis, transactions, positions (via Playwright automation)
- **Lynk**: NAV series del fondo
- **baha**: UCITS fund NAVs (auxiliar)
- **factsheets**: sectorial/regional/currency de cada fondo (mensual manual)
