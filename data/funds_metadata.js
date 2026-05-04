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
// POSITIONS — Pershing export Apr 21, 2026 3:23 PM EDT
// Total AUM: $26,585,704.14 (Pershing $23.36M + External Alts $3.22M)
// In-transit (cash debited, NAV pending):
//   - Flex-Lexington Partners Secondaries $500K (initial funding wired)
// Queued (cash NOT debited yet):
//   - Hamilton Lane Global Private Infra — Jun-26 cycle, dealing 01-Jul-2026
// ============================================================
const BIG_POSITIONS = [
    // ----- EQUITY -----
    { isin: "IE00B5BMR087", ticker: "CSPX",   name: "iShares Core S&P 500 UCITS",              sleeve: "Equity",       value: 2600167.68, pct: 9.78, terInst: 0.07, terA: null },
    { isin: "IE00BFMHRK20", ticker: "NBGMT",  name: "NB Global Equity Megatrends I",           sleeve: "Equity",       value: 1241408.63, pct: 4.67, terInst: 0.75, terA: 1.45 },
    { isin: "LU1985812756", ticker: "MFSCV",  name: "MFS Meridian Contrarian Value I1",        sleeve: "Equity",       value: 1179105.20, pct: 4.44, terInst: 0.85, terA: 1.94 },
    { isin: "IE00B6YCBF59", ticker: "THOR",   name: "Thornburg Equity Income Builder I",       sleeve: "Equity",       value: 610000.02,  pct: 2.29, terInst: 0.89, terA: null },
    { isin: "LU2940405447", ticker: "JHGSC",  name: "Janus Henderson Global Smaller Cos F2",   sleeve: "Equity",       value: 567057.76,  pct: 2.13, terInst: 1.00, terA: null },
    { isin: "IE00BF4KN675", ticker: "LGLI",   name: "Lazard Global Listed Infrastructure A",   sleeve: "Equity",       value: 536360.01,  pct: 2.02, terInst: 0.74, terA: null },
    { isin: "DE000A0Q4R85", ticker: "4BRZ",   name: "iShares MSCI Brazil UCITS (DE)",          sleeve: "Equity",       value: 404488.18,  pct: 1.52, terInst: 0.47, terA: null },
    { isin: "US37950E2596", ticker: "ARGT",   name: "Global X MSCI Argentina ETF",             sleeve: "Equity",       value: 378480.00,  pct: 1.42, terInst: 0.59, terA: null },
    { isin: "US4642873909", ticker: "ILF",    name: "iShares Latin America 40 ETF",            sleeve: "Equity",       value: 375600.00,  pct: 1.41, terInst: 0.59, terA: null },

    // ----- ALTERNATIVES (mix of Pershing + external) -----
    { isin: "LU2837777825", ticker: "CALP",   name: "Carlyle AlpInvest Private Markets",       sleeve: "Alternatives", value: 2722180.00, pct: 10.24, terInst: 1.00, terA: null },
    { isin: "US78463V1070", ticker: "GLD",    name: "SPDR Gold Shares",                        sleeve: "Alternatives", value: 880137.50,  pct: 3.31, terInst: 0.25, terA: null },
    { isin: "US46438F1012", ticker: "IBIT",   name: "iShares Bitcoin Trust",                   sleeve: "Alternatives", value: 868176.12,  pct: 3.27, terInst: 1.25, terA: null },
    { isin: "LU2659193242", ticker: "NBPEA",  name: "NB Global Private Equity Access Fund LI", sleeve: "Alternatives", value: 848311.32,  pct: 3.19, terInst: 0.40, terA: null },
    { isin: "KYG4737U1085", ticker: "HLEND",  name: "HPS Corporate Lending Fund",              sleeve: "Alternatives", value: 753335.66,  pct: 2.83, terInst: 0.75, terA: null },
    { isin: "XS2658535526", ticker: "BPCC",   name: "Barings Private Credit Corporation (BPCC)", sleeve: "Alternatives", value: 589266.90, pct: 2.22, terInst: 1.25, terA: null },
    { isin: "GCRED-I",      ticker: "GCRED",  name: "Golub Capital Private Credit",            sleeve: "Alternatives", value: 501482.61,  pct: 1.89, terInst: 1.25, terA: null },
    { isin: "FLEX-LEX",     ticker: "FLEX",   name: "Flex-Lexington Partners Secondaries",     sleeve: "Alternatives", value: 500000.00,  pct: 1.88, terInst: null, terA: null, status: "IN_TRANSIT" },

    // ----- FIXED INCOME -----
    { isin: "IE00BDT57R20", ticker: "PIMCO-LD", name: "PIMCO GIS Low Duration Income I",       sleeve: "Fixed Income", value: 4022492.10, pct: 15.13, terInst: 0.55, terA: 1.45 },
    { isin: "IE00B87KCF77", ticker: "PIMCO-INC",name: "PIMCO GIS Income I",                    sleeve: "Fixed Income", value: 2042878.87, pct: 7.68, terInst: 0.55, terA: 1.10 },
    { isin: "IE000OE87WX6", ticker: "MANIG",    name: "Man GLG Global IG Opportunities",       sleeve: "Fixed Income", value: 1868128.94, pct: 7.03, terInst: 0.89, terA: 1.89 },
    { isin: "IE00B29K0P99", ticker: "PIMCO-EM", name: "PIMCO GIS EM Local Bond I",             sleeve: "Fixed Income", value: 1139861.80, pct: 4.29, terInst: 0.89, terA: null },
    { isin: "XS2324777171", ticker: "TGF",      name: "Tenac Global Fund (TGF)",               sleeve: "Fixed Income", value: 839581.12,  pct: 3.16, terInst: 0.75, terA: 1.41 },
    { isin: "LU2049315265", ticker: "SGCB",     name: "Schroder GAIA Cat Bond Class C",        sleeve: "Fixed Income", value: 519831.88,  pct: 1.96, terInst: 1.37, terA: null },

    // ----- CASH -----
    { isin: "CASH-USD",     ticker: "CASH",   name: "Cash USD",                                sleeve: "Cash",         value: 597371.84,  pct: 2.25, terInst: null, terA: null }
];

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
    "LU2837777825": "https://www.carlyle.com/caps-sicav",
    "LU2659193242": "https://www.nb.com/latam/products/private-equity",
    "IE00B87KCF77": "https://www.pimco.com/sg/en/investments/gis/income-fund/inst-usd-accumulation",
    "IE00BDT57R20": "https://www.pimco.com/sg/en/investments/gis/low-duration-income-fund/inst-usd-accumulation",
    "IE000OE87WX6": "https://www.man.com/ucits/glg-global-investment-grade-opportunities",
    "IE00B29K0P99": "https://www.pimco.com/gb/en/investments/gis/emerging-local-bond-fund/inst-usd-accumulation",
    "XS2658535526": "Email from Barings (private credit)",
    "XS2324777171": "Tenac Global Fund - direct with Nico Dujovne",
    "KYG4737U1085": "https://www.hpspartners.com/lending",
    "IE00BG13YG49": "https://www.schroders.com/en-ch/ch/professional/funds/schroder-gaia-cat-bond/",
    "LU2049315265": "https://www.schroders.com/es-es/es/inversores-particulares/centro-de-fondos/?language=es&location=es&channel=inversores-particulares&clientId=schdr&clientVersion=v1&externalId=SCHDR_F0000147B0&r=%2Ffund%2FSCHDR_F0000147B0%2F&fundName=Schroder-GAIA-Cat-Bond-C-Accumulation-USD",
    "US78462F1030": "https://www.thornburg.com/funds/equity-income-builder-fund/"
};

// ============================================================
// CURRENCY EXPOSURE (underlying, not share class)
// Each fund: list of {c: currency, p: percent}, must sum to 100
// ============================================================
const CURRENCY_EXPOSURE = {
    "IE00B5BMR087": { exposures: [{c:"USD",p:100}], note: "S&P 500 — 100% USD equities", src: "BlackRock factsheet" },
    "US78462F1030": { exposures: [{c:"USD",p:58},{c:"EUR",p:18},{c:"GBP",p:9},{c:"JPY",p:6},{c:"OTHER",p:9}], note: "Thornburg EIB — global dividend equities", src: "Thornburg factsheet" },
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
    "LU2837777825": { exposures: [{c:"USD",p:65},{c:"EUR",p:25},{c:"GBP",p:10}], note: "Carlyle — global PE multi-currency", src: "Carlyle CAPS SICAV" },
    "LU2659193242": { exposures: [{c:"USD",p:60},{c:"EUR",p:30},{c:"GBP",p:10}], note: "NB PE — global multi-currency", src: "NB docs" },
    "XS2658535526": { exposures: [{c:"USD",p:100}], note: "Barings — USD corporate lending", src: "Manager email" },
    "FLEX-LEX":     { exposures: [{c:"USD",p:80},{c:"EUR",p:15},{c:"GBP",p:5}], note: "Flex-Lexington — secondaries PE global", src: "Flex-Lex docs" },
    "IE00B87KCF77": { exposures: [{c:"USD",p:75},{c:"EUR",p:12},{c:"GBP",p:7},{c:"OTHER",p:6}], note: "PIMCO Income — global FI, USD-hedged", src: "PIMCO factsheet" },
    "IE00BDT57R20": { exposures: [{c:"USD",p:95},{c:"OTHER",p:5}], note: "PIMCO Low Duration — USD-hedged", src: "PIMCO factsheet" },
    "IE000OE87WX6": { exposures: [{c:"USD",p:70},{c:"EUR",p:18},{c:"GBP",p:8},{c:"OTHER",p:4}], note: "Man IG Opp — USD-hedged class", src: "Man docs" },
    "XS2324777171": { exposures: [{c:"USD",p:100}], note: "Tenac — USD fund, ⚠ confirm with Nico", src: "⚠ Confirm with Nico" },
    "IE00B29K0P99": { exposures: [{c:"BRL",p:18},{c:"MXN",p:16},{c:"IDR",p:10},{c:"INR",p:9},{c:"ZAR",p:8},{c:"CLP",p:7},{c:"COP",p:6},{c:"USD",p:12},{c:"OTHER",p:14}], note: "PIMCO EM Local — EM local currency bonds", src: "PIMCO factsheet" },
    "IE00BG13YG49": { exposures: [{c:"USD",p:100}], note: "Schroder GAIA Cat Bond — USD insurance-linked", src: "Schroder factsheet" },
    "CASH-USD":     { exposures: [{c:"USD",p:100}], note: "Cash USD", src: "Pershing" }
};

// ============================================================
// CURRENT YIELD (dividend / distribution / current yield)
// m = manual/requires confirmation, y = null means illiquid
// ============================================================
const CURRENT_YIELD = {
    "IE00B5BMR087": { y: 1.3,  t: "Dividend Yield",       n: "S&P 500 dividend yield",        m: false },
    "US78462F1030": { y: 4.2,  t: "Distribution Yield",   n: "Thornburg EIB — dividend-focused", m: false },
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
    "LU2837777825": { y: null, t: "N/A — illiquid PE",    n: "Carlyle — return via cap gain", m: false },
    "LU2659193242": { y: null, t: "N/A — illiquid PE",    n: "NB PE — return via cap gain",   m: false },
    "XS2658535526": { y: 9.4,  t: "Distribution Rate",    n: "Barings BPCC — email datum",    m: true  },
    "FLEX-LEX":     { y: null, t: "N/A — illiquid PE",    n: "Flex-Lex — secondaries",        m: false },
    "IE00B87KCF77": { y: 6.3,  t: "Current Yield",        n: "PIMCO Income factsheet",        m: false },
    "IE00BDT57R20": { y: 5.9,  t: "Current Yield",        n: "PIMCO Low Dur factsheet",       m: false },
    "IE000OE87WX6": { y: 6.2,  t: "Current Yield",        n: "Man IG Opp — YTW",              m: false },
    "XS2324777171": { y: null, t: "Manual",               n: "⚠ Ask Nico Dujovne",            m: true  },
    "IE00B29K0P99": { y: 8.2,  t: "Current Yield",        n: "PIMCO EM Local — YTW",          m: false },
    "IE00BG13YG49": { y: 7.8,  t: "Current Yield",        n: "Schroder Cat Bond — Libor+5%",  m: false },
    "CASH-USD":     { y: 4.3,  t: "Money Market",         n: "Fed Funds estimate",            m: false }
};

// ============================================================
// FIXED INCOME YTM / DURATION / MATURITY (Maximus Mar-2026)
// ============================================================
const FI_METRICS = {
    "IE00BDT57R20": { name: "PIMCO GIS Low Duration Income I",   ytw: 5.72, dur: 2.54, venc: 3.86,  rating: "AA"   },
    "IE00B87KCF77": { name: "PIMCO GIS Income I",                ytw: 6.05, dur: 5.15, venc: 7.68,  rating: "AA-"  },
    "IE000OE87WX6": { name: "Man GLG Global IG Opps",            ytw: 6.17, dur: 4.89, venc: 5.50,  rating: "BBB"  },
    "IE00B29K0P99": { name: "PIMCO GIS EM Local Bond I",         ytw: 8.22, dur: 6.72, venc: 8.39,  rating: "BBB"  },
    "XS2324777171": { name: "Tenac Global Fund (TGF)",           ytw: 8.67, dur: 5.17, venc: 11.92, rating: "—"    },
    "IE00BG13YG49": { name: "Schroder GAIA Cat Bond",            ytw: 7.80, dur: 0.50, venc: 2.50,  rating: "BB+"  }
};

// ============================================================
// PORTFOLIO PERFORMANCE (Maximus Mar-2026)
// ============================================================
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
// LYNK LIVE DATA (manual refresh from lynkmarkets.com)
// Last refresh: 19-Apr-2026
// ============================================================
window.LYNK_DATA = {
    nav: 105.394,
    change24h: -0.14,  // from Lynk page
    aum: 26422629.18,  // from Lynk Apr 26
    returnYTD: 1.57,
    returnSI: 5.40,
    returnAnnualized: 6.64,
    volatility: 4.96,
    sharpe: 0.43,
    lastUpdate: "2026-04-26",
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
    "US78462F1030": [{c:"US",p:55},{c:"DE",p:8},{c:"UK",p:7},{c:"TW",p:6},{c:"CH",p:5},{c:"NL",p:4},{c:"FR",p:3},{c:"JP",p:4},{c:"OTHER",p:8}],
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
    "LU2837777825": [{c:"US",p:55},{c:"UK",p:15},{c:"FR",p:10},{c:"DE",p:8},{c:"OTHER",p:12}],
    "LU2659193242": [{c:"US",p:50},{c:"UK",p:18},{c:"FR",p:10},{c:"DE",p:8},{c:"OTHER",p:14}],
    "XS2658535526": [{c:"US",p:90},{c:"UK",p:5},{c:"OTHER",p:5}],
    "FLEX-LEX":     [{c:"US",p:60},{c:"UK",p:15},{c:"FR",p:10},{c:"DE",p:8},{c:"OTHER",p:7}],
    "IE00B87KCF77": [{c:"US",p:60},{c:"DE",p:6},{c:"UK",p:5},{c:"FR",p:4},{c:"JP",p:4},{c:"OTHER",p:21}],
    "IE00BDT57R20": [{c:"US",p:85},{c:"UK",p:4},{c:"OTHER",p:11}],
    "IE000OE87WX6": [{c:"US",p:55},{c:"UK",p:10},{c:"DE",p:8},{c:"FR",p:6},{c:"OTHER",p:21}],
    "XS2324777171": [{c:"US",p:40},{c:"UK",p:15},{c:"LatAm",p:15},{c:"EU",p:20},{c:"OTHER",p:10}],
    "IE00B29K0P99": [{c:"BR",p:16},{c:"MX",p:14},{c:"ID",p:9},{c:"IN",p:9},{c:"ZA",p:8},{c:"CL",p:7},{c:"PL",p:6},{c:"OTHER",p:31}],
    "IE00BG13YG49": [{c:"US",p:80},{c:"JP",p:5},{c:"EU",p:10},{c:"OTHER",p:5}],
    "CASH-USD":     [{c:"US",p:100}]
};

// ============================================================
// SECTOR EXPOSURE (underlying, equity sleeve only)
// ============================================================
const SECTOR_EXPOSURE = {
    "IE00B5BMR087": [{s:"Technology",p:32},{s:"Financials",p:14},{s:"Healthcare",p:12},{s:"Cons.Disc",p:10},{s:"Industrials",p:9},{s:"Comm.Services",p:9},{s:"Cons.Staples",p:6},{s:"Energy",p:3},{s:"Utilities",p:2},{s:"Materials",p:2},{s:"Real Estate",p:1}],
    "US78462F1030": [{s:"Financials",p:22},{s:"Healthcare",p:16},{s:"Cons.Staples",p:13},{s:"Industrials",p:11},{s:"Technology",p:10},{s:"Energy",p:9},{s:"Comm.Services",p:7},{s:"Cons.Disc",p:6},{s:"Utilities",p:3},{s:"Materials",p:3}],
    "US4642873909": [{s:"Financials",p:30},{s:"Materials",p:18},{s:"Cons.Staples",p:13},{s:"Energy",p:10},{s:"Industrials",p:8},{s:"Comm.Services",p:7},{s:"Cons.Disc",p:6},{s:"Utilities",p:5},{s:"Technology",p:3}],
    "IE00BFMHRK20": [{s:"Technology",p:35},{s:"Healthcare",p:18},{s:"Cons.Disc",p:14},{s:"Industrials",p:12},{s:"Financials",p:8},{s:"Cons.Staples",p:5},{s:"Comm.Services",p:5},{s:"Materials",p:3}],
    "LU1985812756": [{s:"Financials",p:22},{s:"Healthcare",p:17},{s:"Industrials",p:14},{s:"Cons.Staples",p:12},{s:"Technology",p:10},{s:"Energy",p:8},{s:"Cons.Disc",p:8},{s:"Utilities",p:4},{s:"Materials",p:3},{s:"Real Estate",p:2}],
    "IE00BF4KN675": [{s:"Utilities",p:40},{s:"Industrials",p:35},{s:"Real Estate",p:15},{s:"Energy",p:7},{s:"Comm.Services",p:3}]
};
