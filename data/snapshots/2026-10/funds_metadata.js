/* ==========================================================================
   BIG FUND METADATA — constantes globales del dashboard v2
   Quedan solo: BENCH_YIELD, ALTS_LIQUIDITY, MAXIMUS_AS_OF / PORT_PERF_DETAIL
   y LYNK_DATA (valores estaticos; los numeros vivos salen de lynk_data.json).

   Los datos POR FONDO (yield, paises, moneda, metricas de renta fija, link al
   factsheet) NO viven aca desde el 2026-09-18: estan en data/funds/<TICKER>.json,
   una ficha por fondo cargada desde el factsheet de Research Fondos.
   ========================================================================== */

// ============================================================
// POSITIONS — BORRADO 2026-08-24
// El array BIG_POSITIONS vivia aca: un snapshot a mano del export de
// Pershing que habia que actualizar a pulmon y quedo congelado en
// 2026-06-10. Lo consumia solo el dashboard v1 (borrado en el mismo
// commit). La fuente de verdad de que hay en cartera es
// data/positions_latest.json (refresh diario) + el snapshot canonical
// data/canonical/<fecha>/holdings_returns.json (incluye CALP, que se
// custodia fuera de Pershing).
// ============================================================

// ============================================================
// YIELD, PAISES, MONEDA Y LINKS DE FACTSHEET POR FONDO — MOVIDOS 2026-09-18
// Vivian aca como CURRENT_YIELD / COUNTRY_EXPOSURE / CURRENCY_EXPOSURE /
// FACTSHEET_LINKS: una segunda copia a mano de datos que ya estaban en
// data/funds/<TICKER>.json, y no coincidian (PIMCO Income: 4.38% aca, 4.57%
// alla; paises "US 60%" aca contra 91.57% del factsheet).
//
// Ahora hay UNA ficha por fondo: data/funds/<TICKER>.json, cargada desde el
// factsheet que Lucas sube a Research Fondos. El tab Geography la lee via
// data/funds_index.json (scripts/build_funds_index.py).
//
// NO volver a agregar datos por fondo en este archivo.
// ============================================================

// ============================================================
// YIELD DEL BENCHMARK 60/40 (tab Geography · Yield)
// ============================================================
// Estaba escrito a mano adentro del index.html como `0.60 * 2.0 + 0.40 * 4.5`.
// Un supuesto sin fecha y sin dueño, enterrado en el medio del render: no habia
// forma de saber de cuando era ni quien lo iba a actualizar.
//
// Aca al menos tiene fecha y se ve al lado del resto de la metadata que se
// revisa junto. El dashboard lo muestra con su as_of.
//
// Para refrescar: dividend yield de ACWI (MSCI/iShares) y yield to maturity del
// Bloomberg Global Aggregate (proxy AGG de iShares).
const BENCH_YIELD = {
    acwi:  2.0,           // MSCI ACWI dividend yield
    agg:   4.5,           // Bloomberg Global Agg YTM (proxy AGG)
    as_of: "2026-05-14"   // ultima revision de estos dos numeros
};

// ============================================================
// ALTS LIQUIDITY PROFILE (per holding)
// Categorias: daily | quarterly | annual | long_lock
// notice = dias de notice required pre-redemption
// gate = max % redimible por window (null = sin gate)
// ============================================================
const ALTS_LIQUIDITY = {
    // Daily — ETFs cotizados
    "US46438F1012": { profile: "daily",     ticker: "IBIT",  redemption: "Daily (ETF listado)" },
    "US78463V1070": { profile: "daily",     ticker: "GLD",   redemption: "Daily (ETF listado)" },

    // Private Credit — 1y lock-up + quarterly windows post-unlock
    "KYG4737U1085": { profile: "lock_up", ticker: "HLEND", redemption: "1y lock + Quarterly windows + 5% gate (HPS)",
                      lock_type: "1y lock + Quarterly", purchase_date: "2025-09-22", unlock_date: "2026-09-22" },
    "XS2658535526": { profile: "lock_up", ticker: "BPCC",  redemption: "1y lock + Quarterly windows + 5% gate (Barings)",
                      lock_type: "1y lock + Quarterly", purchase_date: "2025-07-25", unlock_date: "2026-07-25" },
    "GCRED-I":      { profile: "lock_up", ticker: "GCRED", redemption: "1y lock + Quarterly windows (Golub)",
                      lock_type: "1y lock + Quarterly", purchase_date: "2025-09-22", unlock_date: "2026-09-22" },

    // 1-year hard lock-up — privates
    "LU2966298809": { profile: "lock_up", ticker: "FLEX",  redemption: "1y lock + annual exits (Flex-Lex)",
                      lock_type: "1y hard lock", purchase_date: "2026-05-07", unlock_date: "2027-05-07" },
    "LU2827810776": { profile: "lock_up", ticker: "CALP",  redemption: "1y soft-lock (Carlyle)",
                      lock_type: "1y soft lock", purchase_date: "2025-08-29", unlock_date: "2026-08-29" },
    "LU2847068389": { profile: "lock_up", ticker: "HLGPI", redemption: "1y hard lock (Hamilton Lane)",
                      lock_type: "1y hard lock", purchase_date: "2026-06-17", unlock_date: "2027-06-17",
                      tranches: [
                          { date: "2026-05-27", unlock: "2027-05-27", amount: 500000 },
                          { date: "2026-06-17", unlock: "2027-06-17", amount: 600000 },
                      ]
    },
};

// ============================================================
// FIXED INCOME YTM / DURATION / MATURITY
//
// SINGLE SOURCE OF TRUTH: data/funds/<TICKER>.json (campo fi_metrics).
// Antes vivian aca como FI_METRICS pero se duplicaban con los JSONs
// y con scripts/fi_race.py. Refactorizado el 2026-05-15.
//
// Para acceder a estos valores en el frontend, hace fetch al JSON del fondo.
// Para refrescar valores: editar el JSON correspondiente, bumpear as_of_factsheet.
// ============================================================
// const FI_METRICS = {} — moved to data/funds/*.json

// ============================================================
// PORTFOLIO PERFORMANCE (Maximus backtest — Risk & Capture Metrics)
// Bumpear MAXIMUS_AS_OF cuando rehagas el factsheet mensual.
// SLA: 90 dias. Despues de ese plazo el badge se pone rojo.
// ============================================================
const MAXIMUS_AS_OF = "2026-03-31";  // Ultima actualizacion del backtest Maximus
const PORT_PERF_DETAIL = {
    big: {
        m1: -3.32, m3: -1.20, m6: -0.88, ytd: -1.20, y1: 6.87, y3: 10.57, y5: 6.60,
        vol3: 5.71, vol5: 7.20, sharpe3: 1.12, sharpe5: 0.44,
        maxdd3: -3.32, maxdd5: -13.48,
        upCap3: 75.64, upCap5: 73.70, downCap3: 57.98, downCap5: 61.58
    },
    bmk: {
        m1: -4.49, m3: -1.44, m6: 0.77, ytd: -1.44, y1: 13.88, y3: 11.78, y5: 6.25,
        vol3: 8.47, vol5: 9.62, sharpe3: 0.90, sharpe5: 0.29,
        maxdd3: -9.94, maxdd5: -21.11,
        upCap3: 100, upCap5: 100, downCap3: 100, downCap5: 100
    }
};

// ============================================================
// LYNK LIVE DATA — SOLO valores estaticos (isin, inception, url).
// Los numeros (nav/aum/returns) los sobreescribe dashboard.js leyendo
// data/lynk_data.json (cron diario lynk_refresher.py 13:00 ART).
// Si el fetch falla, los campos quedan null -> dashboard muestra "—".
// Last sync to lynk_data.json: 2026-05-27 (NAV 105.198, YTD 1.37%)
// ============================================================
window.LYNK_DATA = {
    nav: 105.198,
    change24h: 0.10,
    aum: 26518282.14,
    returnYTD: 1.37,
    returnSI: 5.20,
    returnAnnualized: 5.82,
    volatility: 5.41,
    sharpe: 0.24,
    lastUpdate: "2026-05-26",
    inception: "2025-06-30",
    isin: "XS3037627794",
    url: "https://app.lynkmarkets.com/public/products/4w9aANBbvM"
};
const LYNK_DATA = window.LYNK_DATA;

// ============================================================
// SECTOR EXPOSURE — REMOVIDO el 2026-05-15
//
// Era data muerta: nunca se consumio en dashboard.js, era incompleto
// (solo 6 de 9 equity funds). Si en el futuro se necesita sector
// breakdown del equity sleeve, ya lo tenemos en data/equity_breakdown_latest.json
// (que SI alimenta el tab Equity Race con datos de FT.com primary).
// ============================================================
// const SECTOR_EXPOSURE = {} — removido (ver historia git pre-2026-05-15)
