/* ==========================================================================
   BIG FUND METADATA
   Source of truth for ISIN-level fund data
   - Currency exposure (underlying, not share class)
   - Current yield / distribution yield
   - YTM, Duration, Maturity (fixed income)
   - Factsheet links for refresh
   Last factsheet review: Mar-2026 (will be updated as factsheets are re-parsed)
   ========================================================================== */

// ============================================================
// POSITIONS — Pershing export 2026-06-10
// Total AUM: $26,062,829.24 (Pershing $23.34M + CALP external $2.72M)
// Cambios desde 2026-05-26:
//   - NBPEA REMOVIDO definitivamente (venta total settled 2026-05-29, $862K)
//   - HLGPI a $500K (settled): la otra pata de $600K aun pendiente, no incluida
//   - IBIT +900 qty (buy 03-Jun @ $37.36) -> 21,116 qty total
//   - GLD -83 qty (sell 03-Jun @ $407.45) -> 1,952 qty total
//   - MANEM +176 qty (buy 08-May @ $113.60) -> nuevo starter en sleeve FI
//   - Cash subio a $626K (proceeds NBPEA + GLD sale)
// Regla pricing: SIEMPRE cierre del dia anterior (T-1), nunca intraday.
// ============================================================
const BIG_POSITIONS = [
    // ----- EQUITY -----
    { isin: "IE00B5BMR087", ticker: "CSPX", name: "iShares Core S&P 500 UCITS", sleeve: "Equity", value: 2706326.88, pct: 10.39, terInst: 0.07, terA: null },
    { isin: "IE00BFMHRK20", ticker: "NBGMT", name: "NB Global Equity Megatrends I", sleeve: "Equity", value: 1350846.72, pct: 5.19, terInst: 0.75, terA: 1.45 },
    { isin: "LU1985812756", ticker: "MFSCV", name: "MFS Meridian Contrarian Value I1", sleeve: "Equity", value: 1190320.84, pct: 4.57, terInst: 0.85, terA: 1.94 },
    { isin: "IE00B6YCBF59", ticker: "THOR", name: "Thornburg Equity Income Builder I", sleeve: "Equity", value: 620231.54, pct: 2.38, terInst: 0.89, terA: null },
    { isin: "LU2940405447", ticker: "JHGSC", name: "Janus Henderson Global Smaller Cos F2", sleeve: "Equity", value: 577468.22, pct: 2.22, terInst: 1.00, terA: null },
    { isin: "IE00BF4KN675", ticker: "LGLI", name: "Lazard Global Listed Infrastructure A", sleeve: "Equity", value: 521916.74, pct: 2.00, terInst: 0.74, terA: null },
    { isin: "US37950E2596", ticker: "ARGT", name: "Global X MSCI Argentina ETF", sleeve: "Equity", value: 363600.00, pct: 1.40, terInst: 0.59, terA: null },
    { isin: "DE000A0Q4R85", ticker: "4BRZ", name: "iShares MSCI Brazil UCITS (DE)", sleeve: "Equity", value: 337770.34, pct: 1.30, terInst: 0.47, terA: null },
    { isin: "US4642873909", ticker: "ILF", name: "iShares Latin America 40 ETF", sleeve: "Equity", value: 332500.00, pct: 1.28, terInst: 0.59, terA: null },

    // ----- ALTERNATIVES (mix of Pershing + CALP external) -----
    { isin: "LU2827810776", ticker: "CALP", name: "Carlyle AlpInvest Private Markets", sleeve: "Alternatives", value: 2722180.00, pct: 10.44, terInst: 1.00, terA: null, external: true },
    { isin: "US46438F1012", ticker: "IBIT", name: "iShares Bitcoin Trust", sleeve: "Alternatives", value: 721005.82, pct: 2.77, terInst: 1.25, terA: null },
    { isin: "US78463V1070", ticker: "GLD", name: "SPDR Gold Shares", sleeve: "Alternatives", value: 706762.16, pct: 2.71, terInst: 0.25, terA: null },
    { isin: "KYG4737U1085", ticker: "HLEND", name: "HPS Corporate Lending Fund", sleeve: "Alternatives", value: 759172.36, pct: 2.92, terInst: 0.75, terA: null },
    { isin: "XS2658535526", ticker: "BPCC", name: "Barings Private Credit Corporation (BPCC)", sleeve: "Alternatives", value: 595348.04, pct: 2.29, terInst: 1.25, terA: null },
    { isin: "LU2966298809", ticker: "FLEX", name: "Franklin Lexington PE Secondaries I", sleeve: "Alternatives", value: 501805.63, pct: 1.93, terInst: null, terA: null },
    { isin: "LU2847068389", ticker: "HLGPI", name: "Hamilton Lane Global Private Infrastructure Fund", sleeve: "Alternatives", value: 1114198.98, pct: 4.28, terInst: null, terA: null },
    { isin: "GCRED-I", ticker: "GCRED", name: "Golub Capital Private Credit", sleeve: "Alternatives", value: 495475.43, pct: 1.90, terInst: 1.25, terA: null },

    // ----- FIXED INCOME -----
    { isin: "IE00BDT57R20", ticker: "PIMCO-LD", name: "PIMCO GIS Low Duration Income I", sleeve: "Fixed Income", value: 3041962.88, pct: 11.68, terInst: 0.55, terA: 1.45 },
    { isin: "IE00B87KCF77", ticker: "PIMCO-INC", name: "PIMCO GIS Income I", sleeve: "Fixed Income", value: 3043889.19, pct: 11.69, terInst: 0.55, terA: 1.10 },
    { isin: "IE000OE87WX6", ticker: "MANIG", name: "Man GLG Global IG Opportunities", sleeve: "Fixed Income", value: 1880151.33, pct: 7.22, terInst: 0.89, terA: 1.89 },
    { isin: "IE00B29K0P99", ticker: "PIMCO-EM", name: "PIMCO GIS EM Local Bond I", sleeve: "Fixed Income", value: 1126852.51, pct: 4.33, terInst: 0.89, terA: null },
    { isin: "XS2324777171", ticker: "TGF", name: "Tenac Global Fund (TGF)", sleeve: "Fixed Income", value: 811823.88, pct: 3.12, terInst: 0.75, terA: 1.41 },
    { isin: "LU2049315265", ticker: "SGCB", name: "Schroder GAIA Cat Bond Class C", sleeve: "Fixed Income", value: 525225.02, pct: 2.02, terInst: 1.37, terA: null },
    { isin: "IE00089T5MA6", ticker: "MANEM", name: "Man EM Corporate Credit Alt IV", sleeve: "Fixed Income", value: 20195.38, pct: 0.08, terInst: null, terA: null },

    // ----- CASH -----
    { isin: "CASH-USD", ticker: "CASH", name: "Cash USD", sleeve: "Cash", value: 40457.10, pct: 0.16, terInst: null, terA: null }
];

// ============================================================
// DATA FRESHNESS MARKERS — para el banner de frescura de cada tab.
// Bumpear cuando se refresca la data subyacente.
// ============================================================
const POSITIONS_AS_OF = "2026-06-24";       // Fecha del export Pershing (positions_latest.json as_of)
const METADATA_LAST_REVIEW = "2026-05-14";  // CURRENCY/COUNTRY/CURRENT_YIELD/FI_METRICS — ultima revision dicts

// ============================================================
// FACTSHEET LINKS (for refresh automation / manual review)
// ============================================================
const FACTSHEET_LINKS = {
    "IE00B5BMR087": "https://www.blackrock.com/americas-offshore/en/literature/fact-sheet/cspx-ishares-core-s-p-500-ucits-etf-fund-fact-sheet-en-lm.pdf",
    "US4642873909": "https://www.ishares.com/us/literature/fact-sheet/ilf-ishares-latin-america-40-etf-fund-fact-sheet-en-us.pdf",
    "US37950E2596": "https://www.globalxetfs.com/funds/argt",
    "DE000A0Q4R85": "https://www.blackrock.com/es/profesionales/productos/304304/ishares-msci-brazil-ucits-etf-de-acc-fund",
    "IE00BF4KN675": "https://www.lazardassetmanagement.com/us/en_us/investment-solutions/how-to-invest/17/400?shareClass=5344",
    "LU1985812756": "https://www.mfs.com/content/dam/mfs-enterprise/mfscom/products/factsheet/meridian/gg/mer_cvf_fs_gg_en.pdf",
    "IE00BFMHRK20": "https://www.nb.com/en/latam/products/ucits-funds/global-equity-megatrends-fund?section=documents",
    "LU2940405447": "https://www.janushenderson.com/en-lu/advisor/product/jhhf-global-smaller-companies-fund/?identifier=LU2940405447",
    "US78463V1070": "https://www.spdrgoldshares.com/usa/gld/",
    "US46438F1012": "https://www.blackrock.com/cl/productos/333011/ishares-bitcoin-trust-etf",
    "GCRED-I":      "https://gcredbdc.com/resources/",
    "LU2827810776": "https://www.carlyle.com/caps-sicav",
    "LU2847068389": "https://www.hamiltonlane.com/en-us/strategies/private-markets-funds",
    "LU2659193242": "https://www.nb.com/latam/products/private-equity",
    "IE00B87KCF77": "https://www.pimco.com/sg/en/investments/gis/income-fund/inst-usd-accumulation",
    "IE00BDT57R20": "https://www.pimco.com/sg/en/investments/gis/low-duration-income-fund/inst-usd-accumulation",
    "IE000OE87WX6": "https://www.man.com/ucits/glg-global-investment-grade-opportunities",
    "IE00089T5MA6": "https://www.man.com/products/man-emerging-markets-corporate-credit-alternative-inf-usd",
    "IE00B29K0P99": "https://www.pimco.com/gb/en/investments/gis/emerging-local-bond-fund/inst-usd-accumulation",
    "XS2658535526": "Email from Barings (private credit)",
    "XS2324777171": "Tenac Global Fund - direct with Nico Dujovne",
    "LU2966298809":     "Flex-Lexington Partners Secondaries - direct with manager (private)",
    "KYG4737U1085": "https://www.hpspartners.com/lending",
    "LU2049315265": "https://www.schroders.com/es-es/es/inversores-particulares/centro-de-fondos/?language=es&location=es&channel=inversores-particulares&clientId=schdr&clientVersion=v1&externalId=SCHDR_F0000147B0&r=%2Ffund%2FSCHDR_F0000147B0%2F&fundName=Schroder-GAIA-Cat-Bond-C-Accumulation-USD",
    "IE00B6YCBF59": "https://www.thornburg.com/funds/equity-income-builder-fund/"
};

// ============================================================
// CURRENCY EXPOSURE (underlying, not share class)
// Each fund: list of {c: currency, p: percent}, must sum to 100
// ============================================================
const CURRENCY_EXPOSURE = {
    "IE00B5BMR087": { exposures: [{c:"USD",p:100}], note: "S&P 500 — 100% USD equities", src: "BlackRock factsheet" },
    "IE00B6YCBF59": { exposures: [{c:"USD",p:58},{c:"EUR",p:18},{c:"GBP",p:9},{c:"JPY",p:6},{c:"OTHER",p:9}], note: "Thornburg EIB — global dividend equities", src: "Thornburg factsheet" },
    "US4642873909": { exposures: [{c:"BRL",p:24},{c:"MXN",p:22},{c:"CLP",p:12},{c:"COP",p:10},{c:"ARS",p:9},{c:"PEN",p:7},{c:"USD",p:16}], note: "ILF — LatAm currency mix", src: "iShares factsheet" },
    "US37950E2596": { exposures: [{c:"ARS",p:55},{c:"USD",p:45}], note: "ARGT — Argentine ADRs & locals", src: "Global X docs" },
    "DE000A0Q4R85": { exposures: [{c:"BRL",p:97},{c:"USD",p:3}], note: "4BRZ — near full BRL exposure", src: "BlackRock factsheet" },
    "IE00BF4KN675": { exposures: [{c:"USD",p:55},{c:"EUR",p:18},{c:"GBP",p:12},{c:"AUD",p:8},{c:"CAD",p:7}], note: "Lazard Infra — global listed", src: "Lazard factsheet" },
    "LU1985812756": { exposures: [{c:"USD",p:62},{c:"EUR",p:20},{c:"GBP",p:10},{c:"JPY",p:5},{c:"OTHER",p:3}], note: "MFS Contrarian — global value equities", src: "MFS factsheet" },
    "IE00BFMHRK20": { exposures: [{c:"USD",p:58},{c:"EUR",p:16},{c:"GBP",p:8},{c:"JPY",p:7},{c:"OTHER",p:11}], note: "NB Megatrends — global thematic", src: "NB docs" },
    "LU2940405447": { exposures: [{c:"USD",p:55},{c:"GBP",p:18},{c:"EUR",p:14},{c:"JPY",p:6},{c:"OTHER",p:7}], note: "JH Small Cos — global", src: "JH docs" },
    "US78463V1070": { exposures: [{c:"GOLD",p:100}], note: "GLD — physical gold, safe-haven", src: "SPDR GLD" },
    "US46438F1012": { exposures: [{c:"BTC",p:100}], note: "IBIT — Bitcoin, digital asset", src: "BlackRock IBIT" },
    "GCRED-I":      { exposures: [{c:"USD",p:100}], note: "GCRED — mid-market USD loans, floating rate", src: "GCRED docs" },
    "KYG4737U1085": { exposures: [{c:"USD",p:100}], note: "HLEND — USD corporate lending", src: "Investment policy" },
    "LU2827810776": { exposures: [{c:"USD",p:65},{c:"EUR",p:25},{c:"GBP",p:10}], note: "Carlyle — global PE multi-currency", src: "Carlyle CAPS SICAV" },
    "LU2847068389": { exposures: [{c:"USD",p:60},{c:"EUR",p:20},{c:"GBP",p:10},{c:"OTHER",p:10}], note: "Hamilton Lane Global Private Infra — global infrastructure (PLACEHOLDER, refinar con factsheet)", src: "estimación" },
    "LU2659193242": { exposures: [{c:"USD",p:60},{c:"EUR",p:30},{c:"GBP",p:10}], note: "NB PE — global multi-currency", src: "NB docs" },
    "XS2658535526": { exposures: [{c:"USD",p:100}], note: "Barings — USD corporate lending", src: "Manager email" },
    "LU2966298809":     { exposures: [{c:"USD",p:80},{c:"EUR",p:15},{c:"GBP",p:5}], note: "Flex-Lexington — secondaries PE global", src: "Flex-Lex docs" },
    // PIMCO Income I (Acc USD): fondo USD-base con hedging FX a nivel mandate
    // de TODA exposición no-USD. Investor net exposure = 100% USD.
    "IE00B87KCF77": { exposures: [{c:"USD",p:100}], note: "PIMCO Income I — 100% USD (hedge FX mandate-level, todo no-USD vuelve a USD)", src: "PIMCO Income KIID + factsheet (USD-hedged share class)" },
    // PIMCO Low Duration Income I: idem — USD-base + mandate-level FX hedge
    "IE00BDT57R20": { exposures: [{c:"USD",p:100}], note: "PIMCO Low Duration Income I — 100% USD (hedge FX mandate-level)", src: "PIMCO LD KIID + factsheet" },
    // Man GLG Global IG Opps IYV USD: clase USD-hedged. Lucas confirma.
    // Bench oficial: ICE BofA Global Large Cap Corporate Index (USD Hedged).
    "IE000OE87WX6": { exposures: [{c:"USD",p:100}], note: "Man GLG IG Opps IYV USD — 100% USD (clase USD-hedged, bench USD-hedged)", src: "Man docs + Lucas confirma" },
    "IE00089T5MA6": { exposures: [{c:"USD",p:100}], note: "Man EM Corp Credit Alt IV USD — placeholder (verify with factsheet)", src: "TODO: factsheet" },
    // Tenac Global Fund: pendiente confirmar share class con Nico Dujovne
    "XS2324777171": { exposures: [{c:"USD",p:100}], note: "Tenac TGF — asumido USD class, ⚠ confirmar share class con Nico", src: "⚠ Pendiente confirmar Nico" },
    // PIMCO EM Local Bond: NO HEDGEADO por diseño — el mandate es retorno EM local FX
    "IE00B29K0P99": { exposures: [{c:"BRL",p:18},{c:"MXN",p:16},{c:"IDR",p:10},{c:"INR",p:9},{c:"ZAR",p:8},{c:"CLP",p:7},{c:"COP",p:6},{c:"USD",p:12},{c:"OTHER",p:14}], note: "PIMCO EM Local Bond I — EM local currencies (NO hedge por diseño del mandate)", src: "PIMCO EM Local factsheet 30-Apr-26" },
    // Schroder GAIA Cat Bond Class C: cat bonds emitidos en USD nativamente. ISIN correcto LU2049315265
    "LU2049315265": { exposures: [{c:"USD",p:100}], note: "Schroder GAIA Cat Bond C — 100% USD (cat bonds emitidos en USD nativamente)", src: "Schroder GAIA prospectus" },
    "CASH-USD":     { exposures: [{c:"USD",p:100}], note: "Cash USD", src: "Pershing" }
};

// ============================================================
// CURRENT YIELD (dividend / distribution / current yield)
// m = manual/requires confirmation, y = null means illiquid
// ============================================================
const CURRENT_YIELD = {
    "IE00B5BMR087": { y: 1.3,  t: "Dividend Yield",       n: "S&P 500 dividend yield",        m: false },
    "IE00B6YCBF59": { y: 4.2,  t: "Distribution Yield",   n: "Thornburg EIB — dividend-focused", m: false },
    "US4642873909": { y: 3.6,  t: "Distribution Yield",   n: "ILF factsheet",                 m: false },
    "US37950E2596": { y: 1.5,  t: "Distribution Yield",   n: "Global X ARGT docs",            m: false },
    "DE000A0Q4R85": { y: 2.8,  t: "Distribution Yield",   n: "BlackRock 4BRZ factsheet",      m: false },
    "IE00BF4KN675": { y: 3.9,  t: "Distribution Yield",   n: "Lazard Infra factsheet",        m: false },
    "LU1985812756": { y: 1.1,  t: "Distribution Yield",   n: "MFS Contrarian — accumulating", m: false },
    "IE00BFMHRK20": { y: 0.8,  t: "Distribution Yield",   n: "NB Megatrends — growth",        m: false },
    "LU2940405447": { y: 1.0,  t: "Distribution Yield",   n: "JH Small Cos — accumulating",   m: false },
    "US78463V1070": { y: 0,    t: "N/A",                  n: "GLD — no yield (gold)",         m: false },
    "US46438F1012": { y: 0,    t: "N/A",                  n: "IBIT — no yield (BTC)",         m: false },
    "GCRED-I":      { y: 10.5, t: "Distribution Rate",    n: "GCRED — ~SOFR+5.5% floating",   m: false },
    "KYG4737U1085": { y: 9.1,  t: "Distribution Rate",    n: "HLEND — estimated",             m: true  },
    "LU2827810776": { y: null, t: "N/A — illiquid PE",    n: "Carlyle — return via cap gain", m: false },
    "LU2847068389": { y: 4.0,  t: "Distribution Yield",   n: "HLGPI — Hamilton Lane Global Private Infra", m: false },
    "LU2659193242": { y: null, t: "N/A — illiquid PE",    n: "NB PE — return via cap gain",   m: false },
    "XS2658535526": { y: 9.4,  t: "Distribution Rate",    n: "Barings BPCC — email datum",    m: true  },
    "LU2966298809":     { y: null, t: "N/A — illiquid PE",    n: "Flex-Lex — secondaries",        m: false },
    "IE00B87KCF77": { y: 4.38, t: "Current Yield",        n: "PIMCO website 31-Mar",          m: false },
    "IE00BDT57R20": { y: 4.05, t: "Current Yield",        n: "PIMCO website 31-Mar",          m: false },
    "IE000OE87WX6": { y: 6.20, t: "Current Yield",        n: "Man GLG factsheet (verify)",    m: false },
    "IE00089T5MA6": { y: null, t: "Yield TBD",             n: "Man EM Corp Credit Alt IV — pendiente factsheet", m: false },
    "XS2324777171": { y: 8.00, t: "Current Yield",        n: "Tenac/Nico Dujovne (verify)",   m: true  },
    "IE00B29K0P99": { y: 6.21, t: "Current Yield",        n: "PIMCO website 31-Mar",          m: false },
    "LU2049315265": { y: 7.80, t: "Current Yield",        n: "Schroder factsheet (verify)",   m: false },
    "CASH-USD":     { y: 4.3,  t: "Money Market",         n: "Fed Funds estimate",            m: false }
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

    // Quarterly — interval funds / BDCs con redemption windows (penalty si te salís fuera)
    "KYG4737U1085": { profile: "quarterly", ticker: "HLEND", redemption: "Quarterly windows + 5% gate", lock_type: "Quarterly windows" },
    "XS2658535526": { profile: "quarterly", ticker: "BPCC",  redemption: "Quarterly windows + 5% gate", lock_type: "Quarterly windows" },
    "GCRED-I":      { profile: "quarterly", ticker: "GCRED", redemption: "Quarterly windows", lock_type: "Quarterly windows" },

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
// CURRENCY DISPLAY CONFIG
// ============================================================
const CUR_COLORS = {
    USD:"#2a7a4a", EUR:"#1a4a9a", GBP:"#6a2a8a",
    BRL:"#9a5a1a", ARS:"#9a2a1a", MXN:"#1a6a6a",
    JPY:"#8a1a1a", IDR:"#4a6a1a", INR:"#7a4a1a",
    ZAR:"#1a7a5a", CLP:"#5a1a7a", COP:"#7a5a0a",
    AUD:"#3a6a9a", CAD:"#9a6a3a", PEN:"#3a5a2a",
    GOLD:"#D4AF37", BTC:"#f7931a", OTHER:"#666"
};

// ============================================================
// COUNTRY / GEOGRAPHY EXPOSURE (underlying)
// Estimated from factsheets. Keys = country code.
// ============================================================
const COUNTRY_EXPOSURE = {
    "IE00B5BMR087": [{c:"US",p:100}],
    "IE00B6YCBF59": [{c:"US",p:55},{c:"DE",p:8},{c:"UK",p:7},{c:"TW",p:6},{c:"CH",p:5},{c:"NL",p:4},{c:"FR",p:3},{c:"JP",p:4},{c:"OTHER",p:8}],
    "US4642873909": [{c:"BR",p:56},{c:"MX",p:22},{c:"CL",p:8},{c:"CO",p:4},{c:"PE",p:4},{c:"AR",p:4},{c:"OTHER",p:2}],
    "US37950E2596": [{c:"AR",p:100}],
    "DE000A0Q4R85": [{c:"BR",p:100}],
    "IE00BF4KN675": [{c:"US",p:45},{c:"UK",p:15},{c:"ES",p:8},{c:"AU",p:7},{c:"CA",p:6},{c:"IT",p:5},{c:"FR",p:4},{c:"OTHER",p:10}],
    "LU1985812756": [{c:"US",p:40},{c:"UK",p:12},{c:"FR",p:10},{c:"DE",p:9},{c:"JP",p:7},{c:"CH",p:6},{c:"NL",p:5},{c:"OTHER",p:11}],
    "IE00BFMHRK20": [{c:"US",p:58},{c:"DE",p:8},{c:"TW",p:6},{c:"UK",p:5},{c:"JP",p:5},{c:"KR",p:4},{c:"FR",p:4},{c:"OTHER",p:10}],
    "LU2940405447": [{c:"US",p:55},{c:"UK",p:16},{c:"JP",p:8},{c:"DE",p:5},{c:"FR",p:3},{c:"CA",p:3},{c:"OTHER",p:10}],
    "US78463V1070": [{c:"GLOBAL",p:100}],
    "US46438F1012": [{c:"GLOBAL",p:100}],
    "GCRED-I":      [{c:"US",p:100}],
    "KYG4737U1085": [{c:"US",p:90},{c:"UK",p:7},{c:"OTHER",p:3}],
    "LU2827810776": [{c:"US",p:55},{c:"UK",p:15},{c:"FR",p:10},{c:"DE",p:8},{c:"OTHER",p:12}],
    "LU2847068389": [{c:"US",p:55},{c:"UK",p:12},{c:"DE",p:8},{c:"FR",p:7},{c:"AU",p:5},{c:"OTHER",p:13}],
    "LU2659193242": [{c:"US",p:50},{c:"UK",p:18},{c:"FR",p:10},{c:"DE",p:8},{c:"OTHER",p:14}],
    "XS2658535526": [{c:"US",p:90},{c:"UK",p:5},{c:"OTHER",p:5}],
    "LU2966298809":     [{c:"US",p:60},{c:"UK",p:15},{c:"FR",p:10},{c:"DE",p:8},{c:"OTHER",p:7}],
    "IE00B87KCF77": [{c:"US",p:60},{c:"DE",p:6},{c:"UK",p:5},{c:"FR",p:4},{c:"JP",p:4},{c:"OTHER",p:21}],
    "IE00BDT57R20": [{c:"US",p:85},{c:"UK",p:4},{c:"OTHER",p:11}],
    "IE000OE87WX6": [{c:"US",p:55},{c:"UK",p:10},{c:"DE",p:8},{c:"FR",p:6},{c:"OTHER",p:21}],
    "IE00089T5MA6": [{c:"EM",p:100}],
    "XS2324777171": [{c:"US",p:40},{c:"UK",p:15},{c:"LatAm",p:15},{c:"EU",p:20},{c:"OTHER",p:10}],
    "IE00B29K0P99": [{c:"BR",p:16},{c:"MX",p:14},{c:"ID",p:9},{c:"IN",p:9},{c:"ZA",p:8},{c:"CL",p:7},{c:"PL",p:6},{c:"OTHER",p:31}],
    "LU2049315265": [{c:"US",p:80},{c:"JP",p:5},{c:"EU",p:10},{c:"OTHER",p:5}],
    "CASH-USD":     [{c:"US",p:100}]
};

// ============================================================
// SECTOR EXPOSURE — REMOVIDO el 2026-05-15
//
// Era data muerta: nunca se consumio en dashboard.js, era incompleto
// (solo 6 de 9 equity funds). Si en el futuro se necesita sector
// breakdown del equity sleeve, ya lo tenemos en data/equity_breakdown_latest.json
// (que SI alimenta el tab Equity Race con datos de FT.com primary).
// ============================================================
// const SECTOR_EXPOSURE = {} — removido (ver historia git pre-2026-05-15)
