/* ==========================================================================
   LIVE PRICING MODULE
   - ETFs (listed) via Stooq public feed (no auth, CSV, delayed ~15min)
   - UCITS funds: manual NAV (from factsheets/bahia/bloomberg terminal)
   - Lynk NAV: manual refresh from lynkmarkets.com

   Stooq provides free CSV feeds for most global tickers:
   Format: https://stooq.com/q/l/?s=<ticker>&f=sd2t2ohlcv&h&e=csv
   ========================================================================== */

// ============================================================
// TICKER MAPPING for Stooq
// Stooq uses suffixes: .US, .DE (Xetra), .UK, .F (Frankfurt)
// ============================================================
const STOOQ_TICKERS = {
    // US-listed ETFs
    "ILF":  { symbol: "ilf.us",   market: "US",    currency: "USD" },
    "ARGT": { symbol: "argt.us",  market: "US",    currency: "USD" },
    "GLD":  { symbol: "gld.us",   market: "US",    currency: "USD" },
    "IBIT": { symbol: "ibit.us",  market: "US",    currency: "USD" },
    "THOR": { symbol: "tibwx.us", market: "US",    currency: "USD" },  // Thornburg share class I

    // European UCITS ETFs (Xetra)
    "CSPX": { symbol: "cspx.uk",  market: "UK",    currency: "USD" },
    "4BRZ": { symbol: "ibzl.de",  market: "DE",    currency: "EUR" },

    // BDCs (US-listed)
    "HLEND": { symbol: "hlend.us", market: "US",   currency: "USD" },
    "BPCC":  { symbol: "bpcc.us",  market: "US",   currency: "USD" },
    "GCRED": { symbol: "gcred.us", market: "US",   currency: "USD" },
};

// ============================================================
// UCITS MANUAL NAV (refresh daily/weekly from source)
// Source priority: 1) Fund website factsheet, 2) bahia.com, 3) Bloomberg
// ============================================================
const MANUAL_NAV = {
    "IE00B5BMR087": { nav: 598.55,   date: "2026-02-28", src: "BlackRock" },
    "LU1985812756": { nav: 28.42,    date: "2026-03-31", src: "MFS factsheet" },
    "IE00BFMHRK20": { nav: 18.65,    date: "2026-03-31", src: "NB factsheet" },
    "LU2940405447": { nav: 12.38,    date: "2026-03-31", src: "Janus Henderson" },
    "IE00BF4KN675": { nav: 15.22,    date: "2026-03-31", src: "Lazard" },
    "IE00B87KCF77": { nav: 20.03,    date: "2026-05-05", src: "baha" },
    "IE00BDT57R20": { nav: 13.91,    date: "2026-05-05", src: "baha" },
    "IE000OE87WX6": { nav: 123.73,   date: "2026-05-05", src: "baha" },
    "IE00B29K0P99": { nav: 17.98,    date: "2026-05-05", src: "baha" },
    "LU2049315265": { nav: 2115.78,  date: "2026-05-05", src: "baha" },
    "XS2324777171": { nav: 110.50,   date: "2026-03-28", src: "Tenac (manager)" },
    "LU2837777825": { nav: null,     date: "2026-03-31", src: "Carlyle (quarterly)" },
    "LU2659193242": { nav: null,     date: "2026-03-31", src: "NB PE (quarterly)" },
    "XS2658535526": { nav: null,     date: "2026-03-31", src: "Barings (quarterly)" },
    "GCRED-I":      { nav: null,     date: "2026-03-31", src: "GCRED (quarterly)" },
    "FLEX-LEX":     { nav: null,     date: "2026-03-31", src: "Flex-Lex (quarterly)" },
};

// ============================================================
// FETCH STOOQ PRICE (single ticker)
// Returns {symbol, date, time, price, change, volume} or null
// CORS-friendly public endpoint
// ============================================================
async function fetchStooqPrice(symbol) {
    const url = `https://stooq.com/q/l/?s=${symbol}&f=sd2t2ohlcv&h&e=csv`;
    try {
        const res = await fetch(url, { mode: 'cors' });
        if (!res.ok) return null;
        const csv = await res.text();
        const lines = csv.trim().split("\n");
        if (lines.length < 2) return null;
        const cols = lines[1].split(",");
        if (cols[1] === "N/D" || cols[6] === "N/D") return null;
        return {
            symbol: cols[0],
            date:   cols[1],
            time:   cols[2],
            open:   parseFloat(cols[3]),
            high:   parseFloat(cols[4]),
            low:    parseFloat(cols[5]),
            close:  parseFloat(cols[6]),
            volume: parseFloat(cols[7]) || 0
        };
    } catch(e) {
        console.warn("Stooq fetch failed for", symbol, e);
        return null;
    }
}

// ============================================================
// FETCH ALL LIVE PRICES (ETFs + BDCs)
// ============================================================
async function fetchAllLivePrices() {
    const result = {};
    const promises = Object.entries(STOOQ_TICKERS).map(async ([ticker, cfg]) => {
        const p = await fetchStooqPrice(cfg.symbol);
        result[ticker] = p ? { price: p.close, date: p.date, time: p.time, source: "Stooq" } : null;
    });
    await Promise.all(promises);
    return result;
}

// ============================================================
// GET NAV FOR INSTRUMENT (tries live → manual → null)
// ============================================================
function getNAV(position, livePrices) {
    // Try live prices first (ETFs and BDCs)
    if (livePrices[position.ticker] && livePrices[position.ticker].price) {
        return {
            nav: livePrices[position.ticker].price,
            date: livePrices[position.ticker].date,
            source: "live (Stooq)",
            isLive: true
        };
    }
    // Fall back to manual NAV (UCITS)
    if (MANUAL_NAV[position.isin] && MANUAL_NAV[position.isin].nav !== null) {
        return {
            nav: MANUAL_NAV[position.isin].nav,
            date: MANUAL_NAV[position.isin].date,
            source: MANUAL_NAV[position.isin].src,
            isLive: false
        };
    }
    return { nav: null, date: null, source: "—", isLive: false };
}

// Exports
window.STOOQ_TICKERS = STOOQ_TICKERS;
window.MANUAL_NAV = MANUAL_NAV;
window.fetchStooqPrice = fetchStooqPrice;
window.fetchAllLivePrices = fetchAllLivePrices;
window.getNAV = getNAV;
