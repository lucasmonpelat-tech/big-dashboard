# 🔄 Migracion del Pampa BIG Analyzer (2026-06-07)

## Que cambio

**Antes:** `pampa-big-analyzer.html` tenia 3 tablas hardcoded (`BASE_CURRENCY`, `BASE_YIELD`, `LINKS`) que DUPLICABAN datos del dashboard live (`data/funds_metadata.js`). Esto causaba bugs por inconsistencia entre las 2 fuentes (ej: USD-hedge no aplicado en HTML local → currency exposure incorrecta).

**Despues:** El HTML local ahora **importa `data/funds_metadata.js`** via `<script src="...">` y usa las mismas constantes que el dashboard live.

## Resultado

✅ **Single source of truth:** `data/funds_metadata.js` es el unico archivo con lookup tables  
✅ **Imposible que diverjan los datos:** ambas herramientas leen lo mismo  
✅ **HTML local 20% mas chico** (-6.3 KB)  
✅ **USD-hedge bug estructuralmente eliminado**  

## Como abrir el analyzer ahora

**Recomendado:** doble-click en `start_analyzer.bat`. Arranca un HTTP server local + abre Chrome.

**Manual:**
```bash
cd big-dashboard/
python -m http.server 8765
# Abrir: http://localhost:8765/pampa-big-analyzer.html
```

⚠️ **NO funciona con doble-click directo al .html** (file:// bloquea el script import por same-origin policy).

## Estructura tecnica

```
big-dashboard/
├── pampa-big-analyzer.html          ← analyzer (solo logic + render)
├── start_analyzer.bat               ← launcher
└── data/
    └── funds_metadata.js            ← SOURCE OF TRUTH (lookup tables)
        ├── BIG_POSITIONS
        ├── CURRENCY_EXPOSURE
        ├── CURRENT_YIELD
        ├── FACTSHEET_LINKS
        └── COUNTRY_EXPOSURE
```

## Validacion (2026-06-07)

Con BIG_POSITIONS al 31-May-2026, el analyzer dio:

| Moneda | Valor | Match con dashboard live |
|---|---|---|
| USD | 74.50% | ✅ 74.5% |
| EUR | 6.45% | ✅ 6.4% |
| BTC | 3.26% | ✅ 3.3% |
| GBP | 3.22% | ✅ 3.2% |
| GOLD | 3.16% | ✅ 3.2% |
| BRL | 2.38% | ✅ 2.4% |

Total weight: 100.04% (suma OK).

## Script de migracion

El script Python usado para la migracion vive en `C:/Users/lmonp/OneDrive/Desktop/Code/_migrate_html_analyzer.py`. Es one-shot — ya cumplio su rol. Mantenido como referencia historica.

## Backup del HTML pre-migracion

`C:/Users/lmonp/OneDrive/Desktop/Code/pampa-big-analyzer.html.pre-migration.bak` (Code/ NO esta versionado en git, es backup local).
