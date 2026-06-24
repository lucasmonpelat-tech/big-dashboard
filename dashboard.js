/* ==========================================================================
   BIG FUND DASHBOARD — Pampa Capital
   Main render & logic
   ========================================================================== */

// ==============================================================
// CSV URL (pegar cuando el Sheet esté publicado como CSV)
// ==============================================================
const CSV_URL = ""; // TODO: Replace with published Google Sheet CSV URL

// ==============================================================
// HELPERS
// ==============================================================
function formatUSD(v, dec = 0) {
    if (v === null || v === undefined) return "—";
    return "$" + v.toLocaleString('en-US', { maximumFractionDigits: dec, minimumFractionDigits: dec });
}
function formatPct(v, dec = 2) {
    if (v === null || v === undefined) return "—";
    return v.toFixed(dec) + "%";
}
function formatNum(v, dec = 2) {
    if (v === null || v === undefined) return "—";
    return v.toFixed(dec);
}
function colorFor(val) { return val >= 0 ? "#81C784" : "#EF5350"; }

// Wrap a long string into multiple lines at word boundaries.
// Shows the FULL name — no truncation, adds extra lines if needed.
function wrapName(name, maxCharsPerLine = 24) {
    if (!name) return '';
    if (name.length <= maxCharsPerLine) return name;
    const words = name.split(' ');
    const lines = [];
    let current = '';
    for (const w of words) {
        if (!current) {
            current = w;
        } else if ((current + ' ' + w).length > maxCharsPerLine) {
            lines.push(current);
            current = w;
        } else {
            current = current + ' ' + w;
        }
    }
    if (current) lines.push(current);
    return lines.join('<br>');
}

// ==============================================================
// FRESHNESS — banner de "qué tan fresca está la data" por tab
// ==============================================================
function daysSince(isoDate) {
    if (!isoDate) return null;
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return null;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
}

// Para market data: devuelve el ultimo close US esperado (skip weekends).
// Si hoy es weekend o lunes pre-cron, el ultimo close esperado es viernes.
function lastExpectedClose() {
    const today = new Date();
    const wd = today.getDay(); // 0=dom, 1=lun, ..., 6=sab
    const offsetDays = (wd === 0) ? 2          // domingo -> viernes (2 dias atras)
                     : (wd === 6) ? 1          // sabado -> viernes
                     : (wd === 1) ? 3          // lunes pre-cron -> viernes
                     : 1;                       // martes-viernes -> dia anterior
    const lastClose = new Date(today);
    lastClose.setDate(today.getDate() - offsetDays);
    lastClose.setHours(0, 0, 0, 0);
    return lastClose;
}

// Semáforo: verde si dentro del SLA, naranja si lo excede hasta 1.5x, rojo si más.
function freshnessLevel(daysAgo, expectedDays) {
    if (daysAgo == null) return { icon: '⚪', color: '#90A4AE' };
    if (daysAgo <= Math.max(expectedDays, 1)) return { icon: '🟢', color: '#81C784' };
    if (daysAgo <= expectedDays * 1.5) return { icon: '🟠', color: '#FFA726' };
    return { icon: '🔴', color: '#EF5350' };
}

// ==============================================================
// LYNK NAV DATE — fecha real del NAV oficial de Lynk (T-1 tipico)
// ==============================================================
// La FUENTE DE VERDAD de "a que fecha corresponde el numero YTD/perf de BIG".
// Se setea en init() leyendo el ultimo punto de lynk_nav_series.json (fecha
// real del NAV). Si falla, cae a LYNK_DATA.refreshedAt (cuando corrio el cron).
// Mata la confusion de Lucas: cualquier numero derivado de Lynk lleva "al <fecha>".
let LYNK_NAV_DATE = null;        // ISO "YYYY-MM-DD" — fecha real del ultimo NAV Lynk
let LYNK_NAV_DATE_SOURCE = null; // 'series' | 'refreshedAt' — de donde salio

// "2026-05-26" -> "26-May" (es-AR, sin year para ahorrar espacio en KPI).
function fmtNavDateShort(isoDate) {
    if (!isoDate) return null;
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return null;
    // Forzar UTC para que "2026-05-26" no se corra al 25 por timezone.
    const dd = String(d.getUTCDate()).padStart(2, '0');
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${dd}-${months[d.getUTCMonth()]}`;
}

// HTML del label "al <fecha>" para pegar al lado de un numero derivado de Lynk.
function lynkAsOfLabel() {
    const s = fmtNavDateShort(LYNK_NAV_DATE);
    return s ? `al ${s}` : '';
}

// Para fuentes market data: si data >= lastExpectedClose -> verde (no penalizar weekend)
function marketFreshnessLevel(isoDate) {
    if (!isoDate) return { icon: '⚪', color: '#90A4AE' };
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return { icon: '⚪', color: '#90A4AE' };
    const lastClose = lastExpectedClose();
    if (d >= lastClose) return { icon: '🟢', color: '#81C784' };
    const days = Math.floor((lastClose - d) / 86400000);
    if (days <= 2) return { icon: '🟠', color: '#FFA726' };
    return { icon: '🔴', color: '#EF5350' };
}

/**
 * UNIFIED MULTI-PERIOD RETURNS — fecha-based, NO asume 1 punto = 1 mes.
 *
 * Calcula retornos 1M/3M/6M/YTD/SI/ANN para un sleeve + benchmark alineados
 * por fecha. Es la fuente UNICA de verdad para todas las tablas Multi-Period
 * (Performance, Equity Race, FI Race, Alts Race). Previene el bug clasico de
 * "YTD agarra un anchor random" que paso el 18-may con ACWI 5.75% vs 9.09%.
 *
 * @param {Array<{date,index}>} sleeveSeries
 * @param {Array<{date,index}>} benchSeries
 * @param {Object} options
 *   - toleranceDays: ventana para buscar punto cercano al anchor target (default 7)
 *   - periods: subset de ['1M','3M','6M','YTD','SI','ANN'] (default todos)
 *   - benchKey: nombre del campo benchmark en el output (default 'bench')
 * @returns {Object} ej. { '1M': {sleeve, bench, alpha}, ... }
 *   alpha = sleeve - bench (en puntos porcentuales)
 */
function computeMultiPeriodReturns(sleeveSeries, benchSeries, options = {}) {
    // toleranceDays default 31: funciona para series monthly (Equity/FI Sleeve TWR)
    // y daily (Lynk NAV). Para periodos cortos (1M/3M) en series monthly el algoritmo
    // agarra el month-end mas cercano al target, no genera "ruido" porque siempre
    // elige el minimo de |fecha - target|.
    const tolerance = (options.toleranceDays || 31) * 86400000;
    const periods = options.periods || ['1M', '3M', '6M', 'YTD', 'SI', 'ANN'];
    const benchKey = options.benchKey || 'bench';
    const result = {};
    if (!sleeveSeries || !sleeveSeries.length || !benchSeries || !benchSeries.length) {
        for (const p of periods) result[p] = { sleeve: null, [benchKey]: null, alpha: null };
        return result;
    }
    const sortedS = [...sleeveSeries].sort((a, b) => a.date.localeCompare(b.date));
    const sortedB = [...benchSeries].sort((a, b) => a.date.localeCompare(b.date));
    const lastS = sortedS[sortedS.length - 1];
    const lastB = sortedB[sortedB.length - 1];
    const lastDate = new Date(lastS.date);
    const round2 = (x) => Math.round(x * 100) / 100;
    function findClosest(series, targetISO) {
        const target = new Date(targetISO).getTime();
        let best = null, bestDiff = Infinity;
        for (const p of series) {
            const diff = Math.abs(new Date(p.date).getTime() - target);
            if (diff < bestDiff && diff <= tolerance) {
                bestDiff = diff;
                best = p;
            }
        }
        return best;
    }
    function emptyRow() { return { sleeve: null, [benchKey]: null, alpha: null }; }
    for (const label of periods) {
        let row = emptyRow();
        if (label === 'SI') {
            const sleeveR = (lastS.index / sortedS[0].index - 1) * 100;
            const benchR = (lastB.index / sortedB[0].index - 1) * 100;
            row = { sleeve: round2(sleeveR), [benchKey]: round2(benchR), alpha: round2(sleeveR - benchR) };
        } else if (label === 'ANN') {
            const days = (lastDate - new Date(sortedS[0].date)) / 86400000;
            const years = days / 365.25;
            if (years > 0) {
                const sleeveAnn = (Math.pow(lastS.index / sortedS[0].index, 1 / years) - 1) * 100;
                const benchAnn  = (Math.pow(lastB.index / sortedB[0].index, 1 / years) - 1) * 100;
                row = { sleeve: round2(sleeveAnn), [benchKey]: round2(benchAnn), alpha: round2(sleeveAnn - benchAnn) };
            }
        } else {
            // 1M / 3M / 6M / YTD: por fecha objetivo
            let targetISO = null;
            if (label === 'YTD') {
                targetISO = `${lastDate.getFullYear() - 1}-12-31`;
            } else {
                const monthsBack = { '1M': 1, '3M': 3, '6M': 6 }[label];
                const d = new Date(lastDate);
                d.setMonth(d.getMonth() - monthsBack);
                targetISO = d.toISOString().slice(0, 10);
            }
            const sStart = findClosest(sortedS, targetISO);
            const bStart = findClosest(sortedB, targetISO);
            if (sStart && bStart) {
                const sleeveR = (lastS.index / sStart.index - 1) * 100;
                const benchR = (lastB.index / bStart.index - 1) * 100;
                row = { sleeve: round2(sleeveR), [benchKey]: round2(benchR), alpha: round2(sleeveR - benchR) };
            }
        }
        result[label] = row;
    }
    return result;
}

// Un badge: "🟢 NAV Lynk hoy". label=nombre visible, isoDate=fecha interna, expectedDays=SLA.
// options.deprecated=true → badge rojo con "DEPRECATED"
// options.market=true → usa marketFreshnessLevel (skip weekends)
function freshBadge(label, isoDate, expectedDays, options = {}) {
    if (options.deprecated) {
        const dateStr = isoDate ? new Date(isoDate).toISOString().slice(0, 10) : '—';
        return `<span class="fresh-badge" title="${label} — fuente DEPRECATED (${dateStr}). Rebuild pendiente desde primary.">`
             + `🔴 <strong>${label}</strong> <span style="color:#EF5350">DEPRECATED</span></span>`;
    }
    const dateStr = isoDate ? new Date(isoDate).toISOString().slice(0, 10) : '—';
    let lvl, ageStr, titleSuffix;
    if (options.market) {
        // Market data: si data >= last close esperado -> al cierre
        lvl = marketFreshnessLevel(isoDate);
        if (lvl.icon === '🟢') {
            ageStr = 'al cierre';
            titleSuffix = ` (market data, ultimo close esperado: ${lastExpectedClose().toISOString().slice(0,10)})`;
        } else {
            const lastClose = lastExpectedClose();
            const dt = isoDate ? new Date(isoDate) : null;
            const behind = dt ? Math.floor((lastClose - dt) / 86400000) : null;
            ageStr = behind != null ? `${behind}d behind` : 'sin fecha';
            titleSuffix = ` (market data, deberia estar al cierre ${lastExpectedClose().toISOString().slice(0,10)})`;
        }
    } else {
        // Calendar-day SLA
        const days = daysSince(isoDate);
        lvl = freshnessLevel(days, expectedDays);
        ageStr = days == null ? 'sin fecha' : (days <= 0 ? 'hoy' : days + 'd');
        titleSuffix = ` (SLA ${expectedDays}d)`;
    }
    return `<span class="fresh-badge" title="${label} — actualizado ${dateStr}${titleSuffix}">`
         + `${lvl.icon} <strong>${label}</strong> `
         + `<span style="color:${lvl.color}">${ageStr}</span></span>`;
}

// Devuelve la fecha mas vieja (min) de un dict { isin: {date|asOf: "..."} }
function oldestDate(dict, field) {
    if (!dict) return null;
    let oldest = null;
    for (const k of Object.keys(dict)) {
        const v = dict[k];
        if (!v || typeof v !== 'object') continue;
        const dStr = v[field];
        if (!dStr) continue;
        const d = new Date(dStr);
        if (isNaN(d.getTime())) continue;
        if (!oldest || d < oldest) oldest = d;
    }
    return oldest ? oldest.toISOString().slice(0, 10) : null;
}

function renderFreshness(containerId, badges) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = badges.filter(Boolean).join('<span class="fresh-sep">·</span>');
}

// ==============================================================
// BANNER DE ALERTA: data Lynk vieja (cron roto / corrio tarde)
// ==============================================================
// Si lynk_data.json.refreshedAt tiene > 26h Y hoy es dia habil (lun-vie),
// mostramos un banner amarillo arriba del Overview. Asi si el cron se rompe
// 1+ dia, Lucas se entera al toque en vez de mirar un numero viejo creyendo
// que es fresco. 26h = tolera que el cron corra una vez por dia con holgura.
// Nota: NO penalizamos fin de semana (sab/dom) porque el cierre Lynk es T-1 y
// el cron no corre; ahi un refreshedAt del viernes es esperable.
const LYNK_STALE_THRESHOLD_HOURS = 26;

function renderLynkStaleBanner() {
    const el = document.getElementById('lynk-stale-banner');
    if (!el) return;
    el.innerHTML = '';

    const iso = (window.LYNK_DATA && window.LYNK_DATA.refreshedAt) || null;
    if (!iso) {
        el.innerHTML = `⚠️ <strong>NAV Lynk sin fecha de refresh</strong> — `
            + `no se encontro <code>refreshedAt</code> en lynk_data.json. Verificar el cron de refresh.`;
        return;
    }
    const refreshed = new Date(iso);
    if (isNaN(refreshed.getTime())) return;

    const ageHours = (Date.now() - refreshed.getTime()) / 3600000;
    const todayWd = new Date().getDay(); // 0=dom, 6=sab
    const isWeekend = (todayWd === 0 || todayWd === 6);

    // Solo alertamos en dia habil y si supera el umbral.
    if (ageHours > LYNK_STALE_THRESHOLD_HOURS && !isWeekend) {
        const ageDays = Math.floor(ageHours / 24);
        const ageTxt = ageDays >= 1
            ? `hace ${ageDays} día${ageDays === 1 ? '' : 's'}`
            : `hace ${Math.floor(ageHours)} horas`;
        const dateTxt = iso.substring(0, 16).replace('T', ' ');
        el.innerHTML = `⚠️ <strong>Lynk NAV no actualizado ${ageTxt}</strong> `
            + `(último refresh: ${dateTxt}) — el número YTD/performance de BIG puede estar viejo. `
            + `Verificar el cron <code>lynk-daily-refresh</code>.`;
    }
}

// Llena los 8 banners de frescura. Se llama al final del init.
async function renderAllFreshness() {
    const noCache = '?_=' + Date.now();
    async function fileDate(path, field) {
        try {
            const r = await fetch(path + noCache);
            if (!r.ok) return null;
            const d = await r.json();
            return d[field] || null;
        } catch (e) { return null; }
    }

    // FI metrics ahora viven en data/funds/<TICKER>.json (single source).
    // Calculo el asOf mas viejo entre los 6 FI funds.
    const FI_TICKERS = ['PIMCO-LD', 'PIMCO-INC', 'PIMCO-EM', 'MANIG', 'SGCB', 'TGF'];

    const [navSeries, eqRace, eqContrib, eqSleeveReal, eqBreakdown, acwiOverlap, fiRace, fiSleeveReal, fiBreakdown, altsRace, bmk6040Date, ...fiFundDates] = await Promise.all([
        fileDate('data/lynk_nav_series.json', 'refreshedAt'),
        fileDate('data/equity_race.json', 'refreshedAt'),
        fileDate('data/equity_contributions_real.json', 'refreshedAt'),
        fileDate('data/equity_sleeve_real.json', 'refreshedAt'),
        fileDate('data/equity_breakdown_latest.json', 'asOf'),
        fileDate('data/acwi_overlap.json', 'refreshedAt'),
        fileDate('data/fi_race.json', 'refreshedAt'),
        fileDate('data/fi_sleeve_real.json', 'refreshedAt'),
        fileDate('data/fi_breakdown_latest.json', 'asOf'),
        fileDate('data/alts_race.json', 'refreshedAt'),
        fileDate('data/bmk_6040.json', 'refreshedAt'),
        ...FI_TICKERS.map(t => fileDate(`data/funds/${t}.json`, 'as_of_factsheet')),
    ]);

    // FI Metrics: el asOf mas viejo entre los 6 FI funds
    const validFiDates = fiFundDates.filter(Boolean);
    const fiMetricsOldest = validFiDates.length
        ? validFiDates.reduce((min, d) => d < min ? d : min, validFiDates[0])
        : null;

    const lynkDate = (window.LYNK_DATA && window.LYNK_DATA.refreshedAt) || null;
    const posDate  = typeof POSITIONS_AS_OF !== 'undefined' ? POSITIONS_AS_OF : null;
    const metaDate = typeof METADATA_LAST_REVIEW !== 'undefined' ? METADATA_LAST_REVIEW : null;
    // Manual NAVs (UCITS) — la mas vieja en el dict MANUAL_NAV (de live_prices.js)
    const manualNavOldest = (typeof MANUAL_NAV !== 'undefined') ? oldestDate(MANUAL_NAV, 'date') : null;

    renderFreshness('fresh-overview', [
        freshBadge('NAV Lynk', lynkDate, 1, { market: true }),
        freshBadge('Posiciones Pershing', posDate, 7),
        freshBadge('NAVs manuales UCITS', manualNavOldest, 14),
    ]);
    renderFreshness('fresh-currency', [
        freshBadge('Posiciones Pershing', posDate, 7),
        freshBadge('Currency exposure (factsheets)', metaDate, 90),
    ]);
    renderFreshness('fresh-geography', [
        freshBadge('Posiciones Pershing', posDate, 7),
        freshBadge('Country exposure (factsheets)', metaDate, 90),
    ]);
    renderFreshness('fresh-yield', [
        freshBadge('Posiciones Pershing', posDate, 7),
        freshBadge('Current yield (factsheets)', metaDate, 90),
    ]);
    renderFreshness('fresh-performance', [
        freshBadge('Serie NAV Lynk', navSeries, 1, { market: true }),
        freshBadge('Benchmark 60/40 (ACWI+AGG)', bmk6040Date, 1, { market: true }),
    ]);
    renderFreshness('fresh-equity-race', [
        freshBadge('Equity Race (Yahoo+baha)', eqRace, 31),
        freshBadge('Contribuciones REAL (Pershing trans)', eqContrib, 31),
        freshBadge('Sleeve REAL TWR', eqSleeveReal, 31),
        freshBadge('Equity Breakdown (style/sector/regional)', eqBreakdown, 31),
        freshBadge('ACWI Top 10 Overlap', acwiOverlap, 31),
    ]);
    renderFreshness('fresh-fi-race', [
        freshBadge('FI Race (baha+Yahoo)', fiRace, 31),
        freshBadge('FI Sleeve REAL TWR (Pershing trans)', fiSleeveReal, 31),
        freshBadge('FI Metrics (YTW/Dur/Maturity)', fiMetricsOldest, 90),
        freshBadge('FI Breakdown', fiBreakdown, 31, { deprecated: true }),
    ]);
    renderFreshness('fresh-alts-race', [
        freshBadge('Alts Race (proxies)', altsRace, 31),
    ]);
}

function computeSleeveTotals(positions) {
    const totals = { Equity: 0, Alternatives: 0, "Fixed Income": 0, Cash: 0 };
    positions.forEach(p => { if (totals[p.sleeve] !== undefined) totals[p.sleeve] += p.value; });
    const total = Object.values(totals).reduce((a, b) => a + b, 0);
    return { totals, total };
}

// ==============================================================
// TAB SWITCHING
// ==============================================================
function initTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-section').forEach(s => s.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + tab).classList.add('active');
            // Trigger resize for plotly charts when tab becomes visible
            setTimeout(() => window.dispatchEvent(new Event('resize')), 10);
        });
    });
}

// ==============================================================
// OVERVIEW TAB — KPIs + Allocation + NAV chart
// ==============================================================
function renderOverview() {
    const L = LYNK_DATA;
    document.getElementById('kpi-nav').textContent = L.nav.toFixed(3);
    document.getElementById('kpi-nav-change').textContent = (L.change24h >= 0 ? '+' : '') + L.change24h.toFixed(2) + '% (24h)';
    document.getElementById('kpi-aum').textContent = '$' + (L.aum / 1e6).toFixed(2) + 'M';
    document.getElementById('kpi-ytd').textContent = (L.returnYTD >= 0 ? '+' : '') + L.returnYTD.toFixed(2) + '%';
    // "al <fecha>" — fecha real del NAV Lynk (T-1 tipico). Si Lucas ve "+1.37% al 26-May"
    // entiende que es el cierre de ayer, NO un error vs lo que ve hoy en el portal Lynk.
    const ytdAsOfEl = document.getElementById('kpi-ytd-asof');
    if (ytdAsOfEl) ytdAsOfEl.textContent = lynkAsOfLabel();
    document.getElementById('kpi-si').textContent = (L.returnSI >= 0 ? '+' : '') + L.returnSI.toFixed(2) + '%';
    document.getElementById('kpi-si-sub').textContent = 'Ann: +' + L.returnAnnualized.toFixed(2) + '%';
    document.getElementById('kpi-vol').textContent = L.volatility.toFixed(2) + '%';
    document.getElementById('kpi-vol-sub').textContent = 'Sharpe: ' + L.sharpe.toFixed(2);

    const incept = new Date(L.inception);
    const today = new Date(L.lastUpdate);
    const days = Math.floor((today - incept) / (1000 * 60 * 60 * 24));
    document.getElementById('kpi-days').textContent = days;
    document.getElementById('kpi-days-sub').textContent = 'Launch: ' + incept.toLocaleDateString('en-GB');

    renderAllocBars();
    renderAllocChart();
    renderNavChart('nav-chart');
    // renderSIPerformance() removido el 2026-05-15 — redundante con el tab Performance
}

// renderSIPerformance() removido el 2026-05-15 — la tabla del Overview era
// redundante con el tab Performance + usaba fuente 60/40 distinta (bmk_6040.json)
// generando inconsistencias. Toda la performance ahora vive en el tab Performance,
// que tambien usa bmk_6040.json (single source de 60/40).

function renderAllocBars() {
    const { totals, total } = computeSleeveTotals(BIG_POSITIONS);
    const targets = { Equity: 30, Alternatives: 30, "Fixed Income": 40, Cash: 0 };
    const colors = { Equity: "#64B5F6", Alternatives: "#FFA726", "Fixed Income": "#81C784", Cash: "#CE93D8" };
    const sleeveOrder = ["Equity", "Alternatives", "Fixed Income", "Cash"];
    const container = document.getElementById('alloc-bars');
    container.innerHTML = '';
    sleeveOrder.forEach(sleeve => {
        const pct = total > 0 ? (totals[sleeve] / total * 100) : 0;
        const target = targets[sleeve];
        const drift = pct - target;
        const driftSign = drift >= 0 ? '+' : '';
        const driftColor = Math.abs(drift) < 2 ? '#81C784' : Math.abs(drift) < 5 ? '#FFA726' : '#EF5350';

        const wrap = document.createElement('div');
        wrap.innerHTML = `
            <div class="alloc-row">
                <div style="flex:1;">
                    <div class="alloc-name" style="color:${colors[sleeve]};">${sleeve}</div>
                    <div class="alloc-bar"><div class="alloc-bar-fill" style="width:${Math.min(pct, 100)}%; background:${colors[sleeve]};"></div></div>
                </div>
                <div class="alloc-pct">${pct.toFixed(2)}%</div>
            </div>
            <div style="font-size:10px; color:#6B88A8; margin: -4px 0 4px 0;">
                Target: ${target}% · Drift: <span style="color:${driftColor};">${driftSign}${drift.toFixed(2)}pp</span>
            </div>
        `;
        container.appendChild(wrap);
    });
}

function renderAllocChart() {
    const { totals, total } = computeSleeveTotals(BIG_POSITIONS);
    const data = [{
        type: 'pie',
        labels: Object.keys(totals),
        values: Object.values(totals),
        hole: 0.55,
        textposition: 'outside',
        textinfo: 'label+percent',
        marker: {
            colors: ['#64B5F6', '#FFA726', '#81C784', '#CE93D8'],
            line: { color: '#0D1B2A', width: 2 }
        },
        hovertemplate: '<b>%{label}</b><br>$%{value:,.0f}<br>%{percent}<extra></extra>'
    }];
    const layout = {
        paper_bgcolor: '#1A2A3D',
        plot_bgcolor: '#1A2A3D',
        font: { color: '#E0E8F0', family: 'Segoe UI, Arial, sans-serif', size: 12 },
        margin: { t: 20, r: 20, b: 20, l: 20 },
        showlegend: false,
        annotations: [{
            text: `<b>AUM</b><br>$${(total / 1e6).toFixed(2)}M`,
            showarrow: false,
            font: { color: '#D4AF37', size: 16 }
        }]
    };
    Plotly.newPlot('alloc-chart', data, layout, { displayModeBar: false, responsive: true });
}

// NAV history — synthetic path (will be replaced when real series available)
const NAV_HISTORY = generateSyntheticNAV();

function generateSyntheticNAV() {
    const start = new Date(2025, 5, 27);
    const end = new Date(2026, 3, 19);
    const endNAV = LYNK_DATA.nav;
    const x = [], y = [];
    let cum = 100;
    const ann = LYNK_DATA.returnAnnualized / 100;
    const dailyReturn = Math.pow(1 + ann, 1 / 252) - 1;
    const dailyVol = LYNK_DATA.volatility / 100 / Math.sqrt(252);
    let rng = 42;
    function rand() { rng = (rng * 9301 + 49297) % 233280; return rng / 233280; }
    const totalDays = Math.floor((end - start) / (1000 * 60 * 60 * 24));
    for (let i = 0; i <= totalDays; i++) {
        const d = new Date(start.getTime() + i * 24 * 60 * 60 * 1000);
        if (d.getDay() === 0 || d.getDay() === 6) continue;
        const remaining = (end - d) / (1000 * 60 * 60 * 24);
        const targetReturn = remaining > 0 ? Math.log(endNAV / cum) / Math.max(remaining / 252, 0.01) / 252 : 0;
        const shock = (rand() - 0.5) * 2 * dailyVol;
        cum = cum * (1 + targetReturn * 0.5 + dailyReturn * 0.5 + shock);
        x.push(d.toISOString().slice(0, 10));
        y.push(Number(cum.toFixed(4)));
    }
    x.push("2026-04-19"); y.push(endNAV);
    return { x, y };
}

function generate6040(navHistory) {
    const start = new Date(navHistory.x[0]);
    return {
        x: navHistory.x,
        y: navHistory.x.map(d => {
            const days = (new Date(d) - start) / (1000 * 60 * 60 * 24);
            return 100 * Math.pow(1.055, days / 365.25);
        })
    };
}

async function renderNavChart(targetId) {
    // Try real Lynk series first; fall back to synthetic
    let big;
    try {
        const r = await fetch('data/lynk_nav_series.json');
        if (r.ok) {
            const d = await r.json();
            big = {
                x: d.series.map(p => p.date),
                y: d.series.map(p => p.value),
            };
            console.log(`Loaded ${big.x.length} real Lynk NAV points (${big.x[0]} → ${big.x[big.x.length-1]})`);
        }
    } catch(e) { /* fallback */ }
    if (!big) big = NAV_HISTORY;

    // Try real 60/40 from Yahoo calculation
    let bmk;
    try {
        const r = await fetch('data/bmk_6040.json');
        if (r.ok) {
            const d = await r.json();
            bmk = {
                x: d.series.map(p => p.date),
                y: d.series.map(p => p.value),
            };
        }
    } catch(e) { /* fallback below */ }
    if (!bmk) bmk = generate6040(big);

    const traces = [
        {
            x: big.x, y: big.y, name: 'BIG Fund (Lynk NAV)',
            type: 'scatter', mode: 'lines',
            line: { color: '#D4AF37', width: 2.8 },
            hovertemplate: '%{x}<br>BIG: <b>%{y:.3f}</b><extra></extra>'
        },
        {
            x: bmk.x, y: bmk.y, name: '60/40 Benchmark (ACWI/AGG, Yahoo)',
            type: 'scatter', mode: 'lines',
            line: { color: '#90CAF9', width: 2, dash: 'dot' },
            hovertemplate: '%{x}<br>60/40: <b>%{y:.3f}</b><extra></extra>'
        }
    ];
    const layout = {
        paper_bgcolor: '#1A2A3D',
        plot_bgcolor: '#12243A',
        font: { color: '#90CAF9', family: 'Segoe UI, Arial, sans-serif', size: 11 },
        margin: { t: 30, r: 24, b: 48, l: 60 },
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 12, color: '#ECEFF1' } },
        xaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, type: 'date' },
        yaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, title: { text: 'Base 100', font: { size: 11 } } },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#1F3864', bordercolor: '#2E74B5', font: { color: '#FFFFFF', size: 11 } }
    };
    Plotly.newPlot(targetId, traces, layout, { responsive: true, displayModeBar: true, displaylogo: false });
}

// ==============================================================
// POSITIONS TAB
// ==============================================================
async function getTminus1Navs() {
    // Build a map ticker -> {nav, date, source} from the same T-1 sources
    // used by the Race tabs (so NAV/Price column es consistente).
    const map = {};
    // 1) UCITS baha daily NAV (highest priority for UCITS)
    try {
        const r = await fetch('data/ucits_daily_nav.json?_=' + Date.now());
        if (r.ok) {
            const d = await r.json();
            const navs = d.navs || {};
            for (const rec of Object.values(navs)) {
                const tk = rec.ticker;
                const nav = rec.nav;
                const date = rec.date || (d.refreshedAt || '').slice(0,10);
                if (tk && typeof nav === 'number' && isFinite(nav) && nav > 0) {
                    map[tk] = { nav, date, source: 'baha T-1' };
                }
            }
        }
    } catch(e) { console.warn('ucits_daily_nav not loaded', e); }
    // 2) Last point of equity_sleeve_real / fi_sleeve_real (per-holding prices)
    for (const f of ['equity_sleeve_real.json', 'fi_sleeve_real.json']) {
        try {
            const r = await fetch('data/' + f + '?_=' + Date.now());
            if (!r.ok) continue;
            const d = await r.json();
            const series = d.sleeve_series_equity || d.sleeve_series_fi || d.sleeve_series || [];
            if (!series.length) continue;
            const last = series[series.length - 1];
            const date = last.date;
            for (const h of (last.holdings || [])) {
                const tk = h.ticker;
                const price = h.price;
                if (tk && typeof price === 'number' && isFinite(price) && price > 0 && !map[tk]) {
                    map[tk] = { nav: price, date, source: 'sleeve T-1' };
                }
            }
        } catch(e) { console.warn(f + ' not loaded', e); }
    }
    return map;
}

async function renderPositions(livePrices) {
    const tbody = document.getElementById('positions-body');
    tbody.innerHTML = '';
    const sleeveOrder = ["Equity", "Alternatives", "Fixed Income", "Cash"];
    const sleeveClass = { Equity: "equity", Alternatives: "alts", "Fixed Income": "fi", Cash: "cash" };
    const { totals, total } = computeSleeveTotals(BIG_POSITIONS);

    const T1 = await getTminus1Navs();

    sleeveOrder.forEach(sleeve => {
        const items = BIG_POSITIONS.filter(p => p.sleeve === sleeve);
        if (!items.length) return;
        const hdr = document.createElement('tr');
        hdr.className = 'sleeve-header';
        hdr.innerHTML = `
            <td class="left" colspan="3">${sleeve}</td>
            <td>${formatUSD(totals[sleeve])}</td>
            <td>${(totals[sleeve] / total * 100).toFixed(2)}%</td>
            <td></td><td></td><td></td><td></td>
        `;
        tbody.appendChild(hdr);
        items.forEach(p => {
            // Try T-1 source first (consistent con Race tabs), then live, then manual
            let nav;
            if (T1[p.ticker]) {
                nav = { nav: T1[p.ticker].nav, date: T1[p.ticker].date, source: T1[p.ticker].source, isT1: true, isLive: false };
            } else {
                nav = getNAV(p, livePrices);
            }
            let navTag;
            if (p.status === 'IN_TRANSIT') {
                navTag = '<span class="tag" style="background:#FFA726;color:#0D1B2A;">IN TRANSIT</span>';
            } else if (nav.isT1) {
                navTag = '<span class="tag tag-live">T-1</span>';
            } else if (nav.isLive) {
                navTag = '<span class="tag tag-live">LIVE</span>';
            } else if (nav.nav) {
                navTag = '<span class="tag tag-manual">MANUAL</span>';
            } else {
                navTag = '<span class="tag tag-na">N/A</span>';
            }
            const statusBadge = p.status === 'IN_TRANSIT' ? ' <span style="font-size:9px; color:#FFA726;">🕐 NAV pending</span>' : '';
            const tr = document.createElement('tr');
            tr.className = `sleeve-${sleeveClass[sleeve]}`;
            tr.innerHTML = `
                <td class="left"><strong>${p.name}</strong>${statusBadge}<span class="note">${p.isin}</span></td>
                <td class="left"><span style="font-family:'Courier New',monospace; color:#90CAF9;">${p.ticker}</span></td>
                <td class="left"><span class="sleeve-badge ${sleeveClass[sleeve]}">${sleeve}</span></td>
                <td>${formatUSD(p.value)}</td>
                <td>${formatPct(p.pct)}</td>
                <td>${nav.nav ? nav.nav.toFixed(2) : '—'} ${navTag}</td>
                <td style="font-size:10px; color:#90CAF9;">${nav.date || '—'}</td>
                <td>${formatPct(p.terInst)}</td>
                <td style="font-size:10px; color:#90CAF9;">${nav.source}</td>
            `;
            tbody.appendChild(tr);
        });
    });
    const totalRow = document.createElement('tr');
    totalRow.className = 'total-row';
    totalRow.innerHTML = `
        <td class="left" colspan="3">TOTAL</td>
        <td>${formatUSD(total)}</td>
        <td>100.00%</td>
        <td></td><td></td><td></td><td></td>
    `;
    tbody.appendChild(totalRow);

    // Factsheet links list
    const linksDiv = document.getElementById('factsheet-links');
    linksDiv.innerHTML = BIG_POSITIONS.map(p => {
        const link = FACTSHEET_LINKS[p.isin];
        if (!link || link.startsWith("Email") || link.startsWith("Tenac")) {
            return `<div style="margin: 3px 0;">• <strong style="color:#E0E8F0;">${p.name}</strong> → <span style="color:#FFA726;">${link || 'N/A'}</span></div>`;
        }
        return `<div style="margin: 3px 0;">• <strong style="color:#E0E8F0;">${p.name}</strong> → <a href="${link}" target="_blank" style="color:#64B5F6;">${link}</a></div>`;
    }).join('');
}

// ==============================================================
// CURRENCY TAB
// ==============================================================
function renderCurrency() {
    // Aggregate portfolio currency exposure
    const totals = {};
    BIG_POSITIONS.forEach(p => {
        const cd = CURRENCY_EXPOSURE[p.isin];
        if (!cd) return;
        cd.exposures.forEach(e => {
            if (!totals[e.c]) totals[e.c] = 0;
            totals[e.c] += (p.pct * e.p) / 100;
        });
    });
    const tsum = Object.values(totals).reduce((a, b) => a + b, 0);
    const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);

    // Bar rows
    const bars = document.getElementById('currency-bars');
    bars.innerHTML = sorted.map(([c, v]) => `
        <div class="bar-row">
            <div class="bar-label" style="color:${CUR_COLORS[c] || '#888'};">${c}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${((v / tsum) * 100).toFixed(1)}%; background:${CUR_COLORS[c] || '#888'};"></div></div>
            <div class="bar-value">${((v / tsum) * 100).toFixed(1)}%</div>
        </div>
    `).join('');

    // Table by instrument
    const tbody = document.getElementById('currency-tbody');
    const sleeveClass = { Equity: "equity", Alternatives: "alts", "Fixed Income": "fi", Cash: "cash" };
    let html = '';
    let lastSleeve = '';
    BIG_POSITIONS.forEach(p => {
        if (p.sleeve !== lastSleeve) {
            lastSleeve = p.sleeve;
            html += `<tr class="sleeve-header"><td class="left" colspan="4">${p.sleeve}</td></tr>`;
        }
        const cd = CURRENCY_EXPOSURE[p.isin];
        if (!cd) return;
        const pills = cd.exposures.map(e => `<span class="currency-pill" style="background:${CUR_COLORS[e.c] || '#666'}; color:#fff;">${e.c} ${e.p}%</span>`).join(' ');
        html += `
            <tr class="sleeve-${sleeveClass[p.sleeve]}">
                <td class="left"><strong>${p.name}</strong><span class="note">${p.isin}</span></td>
                <td>${formatPct(p.pct)}</td>
                <td class="left">${pills}</td>
                <td class="left" style="font-size:10px; color:#90CAF9;">${cd.src}</td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

// ==============================================================
// COUNTRY / GEOGRAPHY TAB
// ==============================================================
const COUNTRY_COLORS = {
    US: "#1F3864", BR: "#9a5a1a", MX: "#2E7D32", AR: "#90CAF9", UK: "#8A1A1A",
    DE: "#F57F17", FR: "#5E35B1", CH: "#E53935", JP: "#C62828", CN: "#B71C1C",
    IN: "#FF6F00", CL: "#7E57C2", CO: "#388E3C", PE: "#33691E", ES: "#D84315",
    NL: "#FFB300", IT: "#43A047", CA: "#00838F", AU: "#4527A0", TW: "#1565C0",
    KR: "#6A1B9A", ID: "#2E7D32", ZA: "#BF360C", PL: "#455A64",
    GLOBAL: "#D4AF37", EU: "#283593", LatAm: "#00695C", OTHER: "#616161"
};

function renderCountry() {
    const totals = {};
    BIG_POSITIONS.forEach(p => {
        const ce = COUNTRY_EXPOSURE[p.isin];
        if (!ce) return;
        ce.forEach(e => {
            if (!totals[e.c]) totals[e.c] = 0;
            totals[e.c] += (p.pct * e.p) / 100;
        });
    });
    const tsum = Object.values(totals).reduce((a, b) => a + b, 0);
    const sorted = Object.entries(totals).sort((a, b) => b[1] - a[1]);

    const bars = document.getElementById('country-bars');
    bars.innerHTML = sorted.slice(0, 15).map(([c, v]) => `
        <div class="bar-row">
            <div class="bar-label" style="color:${COUNTRY_COLORS[c] || '#888'};">${c}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${((v / tsum) * 100).toFixed(1)}%; background:${COUNTRY_COLORS[c] || '#888'};"></div></div>
            <div class="bar-value">${((v / tsum) * 100).toFixed(1)}%</div>
        </div>
    `).join('');

    const tbody = document.getElementById('country-tbody');
    const sleeveClass = { Equity: "equity", Alternatives: "alts", "Fixed Income": "fi", Cash: "cash" };
    let html = '';
    let lastSleeve = '';
    BIG_POSITIONS.forEach(p => {
        if (p.sleeve !== lastSleeve) {
            lastSleeve = p.sleeve;
            html += `<tr class="sleeve-header"><td class="left" colspan="3">${p.sleeve}</td></tr>`;
        }
        const ce = COUNTRY_EXPOSURE[p.isin];
        if (!ce) return;
        const pills = ce.map(e => `<span class="currency-pill" style="background:${COUNTRY_COLORS[e.c] || '#666'}; color:#fff;">${e.c} ${e.p}%</span>`).join(' ');
        html += `
            <tr class="sleeve-${sleeveClass[p.sleeve]}">
                <td class="left"><strong>${p.name}</strong><span class="note">${p.isin}</span></td>
                <td>${formatPct(p.pct)}</td>
                <td class="left">${pills}</td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

// ==============================================================
// YIELD TAB
// ==============================================================
function renderYield() {
    // Weighted portfolio yield
    let weightedYield = 0;
    let pctWithYield = 0;
    let manualCount = 0;
    let noYieldCount = 0;
    BIG_POSITIONS.forEach(p => {
        const yd = CURRENT_YIELD[p.isin];
        if (!yd) return;
        if (yd.y && yd.y > 0) {
            weightedYield += (p.pct * yd.y) / 100;
            pctWithYield += p.pct;
        } else if (yd.y === null || yd.y === 0) {
            noYieldCount++;
        }
        if (yd.m) manualCount++;
    });

    const bmkYield = 0.60 * 2.0 + 0.40 * 4.5; // 60% ACWI div + 40% AGG
    const yieldAlpha = weightedYield - bmkYield;

    document.getElementById('yield-summary-grid').innerHTML = `
        <div class="summary-item" style="border-left-color:#81C784;">
            <div class="s-lbl">Portfolio Weighted Yield</div>
            <div class="yield-total">${weightedYield.toFixed(2)}%</div>
            <div class="s-sub">weighted by portfolio pct</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">% Portfolio Generating Income</div>
            <div class="s-val" style="color:#64B5F6;">${pctWithYield.toFixed(1)}%</div>
            <div class="s-sub">assets with yield > 0</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">Manual Confirmation Needed</div>
            <div class="s-val" style="color:#FFA726;">${manualCount}</div>
            <div class="s-sub">HLEND · TGF · BPCC</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">No Yield Assets</div>
            <div class="s-val" style="color:#90CAF9;">${noYieldCount}</div>
            <div class="s-sub">GLD · IBIT · PE · Equities no div</div>
        </div>
    `;

    document.getElementById('yield-bmk-grid').innerHTML = `
        <div class="summary-item" style="border-left-color:#90CAF9;">
            <div class="s-lbl">Benchmark Yield (60/40)</div>
            <div class="yield-total" style="color:#90CAF9;">${bmkYield.toFixed(2)}%</div>
            <div class="s-sub">60% ACWI (2.0%) + 40% AGG (4.5%)</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">MSCI ACWI Div Yield</div>
            <div class="s-val">2.00%</div>
            <div class="s-sub">60% of benchmark</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">Bloomberg AGG Yield</div>
            <div class="s-val">4.50%</div>
            <div class="s-sub">40% of benchmark</div>
        </div>
        <div class="summary-item" style="border-left-color:${yieldAlpha >= 0 ? '#81C784' : '#EF5350'};">
            <div class="s-lbl">Yield Alpha (BIG − BMK)</div>
            <div class="s-val" style="color:${yieldAlpha >= 0 ? '#81C784' : '#EF5350'};">${yieldAlpha >= 0 ? '+' : ''}${yieldAlpha.toFixed(2)}%</div>
            <div class="s-sub">excess income vs benchmark</div>
        </div>
    `;

    // Detail table
    const tbody = document.getElementById('yield-tbody');
    const sleeveClass = { Equity: "equity", Alternatives: "alts", "Fixed Income": "fi", Cash: "cash" };
    let html = '';
    let lastSleeve = '';
    BIG_POSITIONS.forEach(p => {
        if (p.sleeve !== lastSleeve) {
            lastSleeve = p.sleeve;
            html += `<tr class="sleeve-header"><td class="left" colspan="7">${p.sleeve}</td></tr>`;
        }
        const yd = CURRENT_YIELD[p.isin];
        if (!yd) return;
        const y = yd.y;
        const yDisplay = y === null ? '<span style="color:#6B88A8; font-style:italic;">N/A</span>' :
                         y === 0 ? '<span style="color:#6B88A8;">0.00%</span>' :
                                   `<strong style="color:#81C784;">${y.toFixed(2)}%</strong>`;
        const tag = yd.m ? '<span class="tag tag-manual">MANUAL</span>' :
                   y === null ? '<span class="tag tag-na">N/A</span>' :
                                '<span class="tag tag-auto">AUTO</span>';
        const contrib = y && y > 0 ? ((p.pct * y) / 100).toFixed(3) + '%' : '—';
        html += `
            <tr class="sleeve-${sleeveClass[p.sleeve]}">
                <td class="left"><strong>${p.name}</strong><span class="note">${p.isin}</span></td>
                <td>${formatPct(p.pct)}</td>
                <td class="left"><span class="sleeve-badge ${sleeveClass[p.sleeve]}">${p.sleeve}</span></td>
                <td>${yDisplay}</td>
                <td class="left"><span style="font-size:11px;">${yd.t}</span>${tag}</td>
                <td>${contrib}</td>
                <td class="left" style="font-size:10px; color:#90CAF9;">${yd.n}</td>
            </tr>
        `;
    });
    tbody.innerHTML = html;
}

// ==============================================================
// PERFORMANCE TAB
// ==============================================================
async function renderPerformance() {
    const b = PORT_PERF_DETAIL.big;   // Para risk metrics (vol/sharpe/dd/capture) — Maximus
    const k = PORT_PERF_DETAIL.bmk;
    const fmt = v => v == null ? '<span style="color:#6B88A8;">—</span>'
        : (v >= 0 ? `<span style="color:#81C784;">+${v.toFixed(2)}%</span>`
                   : `<span style="color:#EF5350;">${v.toFixed(2)}%</span>`);

    // ===== Computar multi-period returns desde fuentes auto-refresh =====
    // BIG: lynk_nav_series.json (cron diario)
    // 60/40: bmk_6040.json (SINGLE SOURCE — el mismo que usa el NAV chart del Overview)
    let bigSeries = null, bmk6040Data = null;
    try {
        const [r1, r2] = await Promise.all([
            fetch('data/lynk_nav_series.json?_=' + Date.now()),
            fetch('data/bmk_6040.json?_=' + Date.now()),
        ]);
        if (r1.ok) bigSeries = (await r1.json()).series;  // [{date, value}, ...]
        if (r2.ok) bmk6040Data = await r2.json();  // tiene periods.returns + series
    } catch (e) { console.warn('Performance: error fetching data', e); }

    function findClosestBig(targetISO) {
        // Devuelve el NAV mas cercano (mismo dia o el siguiente trading day)
        if (!bigSeries) return null;
        for (const p of bigSeries) {
            if (p.date >= targetISO) return p.value;
        }
        return null;
    }

    function bigReturnFrom(startISO) {
        if (!bigSeries || !bigSeries.length) return null;
        const startNav = findClosestBig(startISO);
        const endNav = bigSeries[bigSeries.length - 1].value;
        if (!startNav || !endNav) return null;
        return (endNav / startNav - 1) * 100;
    }

    function isoNDaysAgo(days) {
        const d = bigSeries && bigSeries.length ? new Date(bigSeries[bigSeries.length - 1].date) : new Date();
        d.setDate(d.getDate() - days);
        return d.toISOString().slice(0, 10);
    }

    // Fechas para cada periodo
    const latestDate = bigSeries && bigSeries.length ? bigSeries[bigSeries.length - 1].date : new Date().toISOString().slice(0,10);
    const latestYear = parseInt(latestDate.slice(0, 4));
    const ytdStart = `${latestYear - 1}-12-31`;
    const ytdMonth = `${latestYear - 1}-12`;

    const periods = [
        { label: '1M',  startDate: isoNDaysAgo(30),  startMonth: null },  // monthly bmk: use 1M back
        { label: '3M',  startDate: isoNDaysAgo(90),  startMonth: null },
        { label: '6M',  startDate: isoNDaysAgo(180), startMonth: null },
        { label: 'YTD', startDate: ytdStart, startMonth: ytdMonth },
    ];

    // BIG returns — POLITICA: el performance del FONDO BIG TOTAL sale de LYNK
    // (estructurador oficial de la nota), NO se recalcula. Lynk publica
    // YTD / SI / Annualized oficiales en lynk_data.json -> usamos esos directo
    // para que el dashboard matchee EXACTO la app de Lynk.
    // 1M / 3M / 6M: Lynk no los publica, los derivamos de la serie del NAV
    // oficial de Lynk (lynk_nav_series.json) — mismo NAV, solo otro periodo.
    const bigReturns = {};
    periods.forEach(p => {
        if (p.label === 'YTD') return;  // YTD viene de Lynk (abajo)
        bigReturns[p.label] = bigReturnFrom(p.startDate);
    });
    // YTD / SI / Annualized: numeros OFICIALES de Lynk (no recalculados)
    const L = (typeof LYNK_DATA !== 'undefined') ? LYNK_DATA : {};
    bigReturns.YTD = (L.returnYTD != null) ? L.returnYTD : bigReturnFrom(ytdStart);
    bigReturns.SI  = (L.returnSI != null) ? L.returnSI : null;
    bigReturns.ANN = (L.returnAnnualized != null) ? L.returnAnnualized : null;

    // 60/40 returns — todos pre-calculados en bmk_6040.json (single source de 60/40)
    const bmkReturns = {};
    if (bmk6040Data && bmk6040Data.periods && bmk6040Data.periods.returns) {
        const r = bmk6040Data.periods.returns;
        bmkReturns['1M']  = r['1M'];
        bmkReturns['3M']  = r['3M'];
        bmkReturns['6M']  = r['6M'];
        bmkReturns.YTD    = r['YTD'];
        bmkReturns.SI     = r['SI'];
        bmkReturns.ANN    = r['Annualized'];
    }

    // Alpha
    const alpha = (label) => {
        const a = bigReturns[label], c = bmkReturns[label];
        return (a != null && c != null) ? a - c : null;
    };

    // "al <fecha>" para la fila BIG Fund (numeros derivados de Lynk T-1).
    // Prioriza el global LYNK_NAV_DATE (seteado en init desde la serie); si por
    // alguna razon no esta, cae al ultimo punto de bigSeries fetcheado aca mismo.
    const perfNavISO = LYNK_NAV_DATE
        || (bigSeries && bigSeries.length ? bigSeries[bigSeries.length - 1].date : null);
    const perfAsOf = fmtNavDateShort(perfNavISO);
    const perfAsOfHtml = perfAsOf
        ? ` <span class="asof-label">(al ${perfAsOf})</span>` : '';

    document.getElementById('perf-returns-body').innerHTML = `
        <tr class="row-big">
            <td class="left"><strong>BIG Fund</strong>${perfAsOfHtml}</td>
            <td>${fmt(bigReturns.YTD)}</td>
            <td>${fmt(bigReturns['1M'])}</td>
            <td>${fmt(bigReturns['3M'])}</td>
            <td>${fmt(bigReturns['6M'])}</td>
            <td>${fmt(bigReturns.SI)}</td>
            <td>${fmt(bigReturns.ANN)}</td>
        </tr>
        <tr class="row-bmk">
            <td class="left">Benchmark 60/40 (ACWI/AGG)</td>
            <td>${fmt(bmkReturns.YTD)}</td>
            <td>${fmt(bmkReturns['1M'])}</td>
            <td>${fmt(bmkReturns['3M'])}</td>
            <td>${fmt(bmkReturns['6M'])}</td>
            <td>${fmt(bmkReturns.SI)}</td>
            <td>${fmt(bmkReturns.ANN)}</td>
        </tr>
        <tr class="row-alpha">
            <td class="left"><strong>Alpha</strong></td>
            <td>${fmt(alpha('YTD'))}</td>
            <td>${fmt(alpha('1M'))}</td>
            <td>${fmt(alpha('3M'))}</td>
            <td>${fmt(alpha('6M'))}</td>
            <td>${fmt(alpha('SI'))}</td>
            <td>${fmt(alpha('ANN'))}</td>
        </tr>
    `;

    // ===== Alpha Attribution YTD por Asset Class =====
    // Carga attribution_ytd.json y desglosa el alpha total por sleeve.
    try {
        const ra = await fetch('data/attribution_ytd.json?_=' + Date.now());
        if (ra.ok) {
            const attr = await ra.json();
            const aa = attr && attr.alpha_attribution;
            const bodyEl = document.getElementById('perf-alpha-attribution-body');
            if (aa && aa.components && bodyEl) {
                const fmtPP = (v) => {
                    if (v === null || v === undefined) return '<span style="color:#6B88A8;">n/a</span>';
                    const sign = v >= 0 ? '+' : '';
                    const color = v >= 0 ? '#81C784' : '#EF5350';
                    return `<strong style="color:${color};">${sign}${v.toFixed(2)}pp</strong>`;
                };
                let rows = aa.components.map(c => `
                    <tr>
                        <td class="left"><strong>${c.name}</strong></td>
                        <td>${c.big_contrib_pp !== null && c.big_contrib_pp !== undefined ? fmtPP(c.big_contrib_pp) : '<span style="color:#6B88A8;">—</span>'}</td>
                        <td>${c.bench_contrib_pp !== null && c.bench_contrib_pp !== undefined ? fmtPP(c.bench_contrib_pp) : '<span style="color:#6B88A8;">—</span>'}</td>
                        <td>${fmtPP(c.alpha_pp)}</td>
                        <td class="left" style="font-size:11px;color:#90CAF9;">${c.comment || ''}</td>
                    </tr>
                `).join('');
                // Total row
                rows += `
                    <tr style="border-top:2px solid #2E74B5;background:rgba(46,116,181,0.1);">
                        <td class="left"><strong>TOTAL Alpha YTD</strong></td>
                        <td style="font-size:11px;color:#90CAF9;">BIG ${aa.big_ytd !== null ? aa.big_ytd.toFixed(2) + '%' : 'n/a'}</td>
                        <td style="font-size:11px;color:#90CAF9;">Bench ${aa.bench_ytd_aor_etf !== null ? aa.bench_ytd_aor_etf.toFixed(2) + '%' : 'n/a'}</td>
                        <td>${fmtPP(aa.alpha_ytd_total_pp)}</td>
                        <td class="left" style="font-size:11px;color:#90CAF9;font-style:italic;">Sum de alpha por sleeve + fee + residual = alpha total</td>
                    </tr>
                `;
                bodyEl.innerHTML = rows;
            }
        }
    } catch (e) {
        console.warn('Alpha attribution: error fetching', e);
    }

    // Disclaimer: Risk & Capture Metrics vienen del backtest Maximus.
    // Bumpear MAXIMUS_AS_OF en funds_metadata.js al rehacer el factsheet mensual.
    const maximusDate = typeof MAXIMUS_AS_OF !== 'undefined' ? MAXIMUS_AS_OF : null;
    const disclaimerEl = document.getElementById('perf-risk-disclaimer');
    if (disclaimerEl && maximusDate) {
        const badge = freshBadge('Maximus backtest', maximusDate, 90);
        disclaimerEl.innerHTML =
            `Fuente: <strong>Maximus backtest</strong> (track record 5Y del strategy replicado). ` +
            `Se actualiza al rehacer el factsheet mensual. ` + badge;
    }

    document.getElementById('perf-risk-grid').innerHTML = `
        <div class="summary-item">
            <div class="s-lbl">Volatility 3Y</div>
            <div class="s-val">${b.vol3}%</div>
            <div class="s-sub">vs ${k.vol3}% bmk</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">Volatility 5Y</div>
            <div class="s-val">${b.vol5}%</div>
            <div class="s-sub">vs ${k.vol5}% bmk</div>
        </div>
        <div class="summary-item" style="border-left-color:#81C784;">
            <div class="s-lbl">Sharpe 3Y</div>
            <div class="s-val" style="color:#81C784;">${b.sharpe3}</div>
            <div class="s-sub">vs ${k.sharpe3} bmk</div>
        </div>
        <div class="summary-item" style="border-left-color:#81C784;">
            <div class="s-lbl">Sharpe 5Y</div>
            <div class="s-val" style="color:#81C784;">${b.sharpe5}</div>
            <div class="s-sub">vs ${k.sharpe5} bmk</div>
        </div>
        <div class="summary-item" style="border-left-color:#EF5350;">
            <div class="s-lbl">Max Drawdown 3Y</div>
            <div class="s-val" style="color:#EF5350;">${b.maxdd3}%</div>
            <div class="s-sub">vs ${k.maxdd3}% bmk</div>
        </div>
        <div class="summary-item" style="border-left-color:#EF5350;">
            <div class="s-lbl">Max Drawdown 5Y</div>
            <div class="s-val" style="color:#EF5350;">${b.maxdd5}%</div>
            <div class="s-sub">vs ${k.maxdd5}% bmk</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">Up Capture 3Y</div>
            <div class="s-val">${b.upCap3}%</div>
            <div class="s-sub">capture of market upside</div>
        </div>
        <div class="summary-item" style="border-left-color:#81C784;">
            <div class="s-lbl">Down Capture 3Y</div>
            <div class="s-val" style="color:#81C784;">${b.downCap3}%</div>
            <div class="s-sub">lower = better downside protection</div>
        </div>
    `;

    renderNavChart('nav-chart-perf');
}

// ==============================================================
// MONTHLY BREAKDOWN — Equity Sleeve mes a mes con notas explicativas
// ==============================================================
// Notas mensuales — Lucas las edita aca cuando quiere. Key = "YYYY-MM" del fin
// de mes (mismo formato que twr_series). Generadas inicialmente por agent
// research el 2026-05-19. Bumpear cuando haya nuevo mes cerrado.
// Notas FI mensuales 2026 — generadas por agent research el 2026-05-20.
// Lucas las edita aca cuando quiere. Bumpear con cada mes que cierre.
const FI_MONTHLY_NOTES = {
    "2026-01": "AGG flat: 10Y anclo en 4.15%, IG spreads en minimos de 30 anos (71bp). BIG FI +0.43% — corta duracion limito upside.",
    "2026-02": "10Y bajo a 4.08% pre-shock Iran fin de mes. PIMCO-INC y carry IG impulsaron BIG FI +0.91%, batiendo AGG holgado.",
    "2026-03": "Shock petrolero (Brent +55%) y CPI +0.9% m/m dispararon yields. BIG FI -2.06% pero corta duracion PIMCO-LD amortiguo vs AGG.",
    "2026-04": "AGG +0.26%, EM +0.41%, IG +0.38%. PIMCO-EM (USD debil) y entrada de SGCB cat bonds llevaron BIG FI a +1.62%, alpha fuerte.",
    "2026-05": "Selloff global: 10Y a 4.7%, CPI max 3 anos, oil shock Hormuz. BIG FI -0.38% — short duration y MANIG IG hedged contuvieron perdida.",
};

const EQUITY_MONTHLY_NOTES = {
    "2025-08": "Rotacion value/small-cap post-Jackson Hole. BRK.B + MFSCV value tilt + NBGMT le ganaron al S&P large-cap.",
    "2025-09": "Rally AI/Mag7 (S&P +8.1% Q3). BRK.B arrastro post-retiro Buffett y la sub-pond en hyperscalers costo caro.",
    "2025-10": "Peor mes. Tensiones US-China, ACWI capturo resiliencia internacional (+30% YTD), BIG no.",
    "2025-11": "Alpha por entrada de Virtus US Small Cap justo cuando Russell 2000 desperto. Rotacion value capturada.",
    "2025-12": "Santa rally en AI hyperscalers (Nvidia +37% YTD). Sub-pond Mag7 vs CSPX/ACWI costo el cierre de ano.",
    "2026-01": "Drag por entrada tardia a LatAm (4BRZ+ARGT 5.5%) y peso US large-cap; rotacion a value/EM ya en marcha sin BIG capturarla.",
    "2026-02": "Alpha leve: LatAm rally historico (Arg +27%, ILF flows record) capturado parcial via 4BRZ/ARGT/ILF/LGLI; value tilt ayudo.",
    "2026-03": "Alpha defensivo en selloff -6%: value tilt (NBGMT+MFSCV 33%) y BRK.B residual cushionearon vs equal-weight.",
    "2026-04": "Drag fuerte: rally tech/AI +9% lider por semis; BIG sin BRK.B (Q1 sale), pesado en value/LatAm sin growth puro.",
    "2026-05": "Rally global equities: NASDAQ +8.4%, S&P +5.3% por earnings beat (83% S&P 500). BIG +5.3% capturo via CSPX (34% sleeve) y NBGMT tech-tilt; alpha leve +0.72pp.",
};

function renderEquityMonthlyBreakdown(twrSeries, acwiSeries) {
    const tbody = document.getElementById('er-monthly-body');
    if (!tbody || !twrSeries || twrSeries.length < 2) return;

    // Alinear ACWI por fecha (mismo approach que computeMultiPeriodReturns)
    const acwiByDate = Object.fromEntries(acwiSeries.map(p => [p.date, p.index]));

    // Calcular return mensual: (index[i] / index[i-1] - 1) * 100
    // El twr_series ya tiene el campo `twr` (mensual ajustado por flujos) pero
    // recalculamos para consistencia y para el ACWI (que no tiene `twr`).
    const rows = [];
    // Agrupar por YYYY-MM y tomar el ULTIMO punto disponible de cada mes.
    // (Con series interpoladas diarias, varios dias matchearian -28/-29/-30/-31
    //  causando filas duplicadas. Este approach toma 1 punto por mes garantizado.)
    const lastOfMonth = new Map();
    for (const p of twrSeries) {
        if (!p.date.startsWith('2026-')) continue;
        const ym = p.date.slice(0, 7);
        const existing = lastOfMonth.get(ym);
        if (!existing || p.date > existing.date) {
            lastOfMonth.set(ym, p);
        }
    }

    // Indexar twrSeries por fecha para encontrar el punto del mes anterior
    const byDate = Object.fromEntries(twrSeries.map(p => [p.date, p]));
    const sortedMonths = Array.from(lastOfMonth.keys()).sort();

    for (const ym of sortedMonths) {
        const curr = lastOfMonth.get(ym);
        // Buscar el ultimo punto del mes anterior (puede no ser exactamente fin de mes)
        const [year, month] = ym.split('-').map(Number);
        const prevYear = month === 1 ? year - 1 : year;
        const prevMonth = month === 1 ? 12 : month - 1;
        const prevYM = `${prevYear}-${String(prevMonth).padStart(2, '0')}`;
        // Tomar el ultimo punto del mes anterior
        const prevCandidates = twrSeries.filter(p => p.date.startsWith(prevYM));
        if (prevCandidates.length === 0) continue;
        const prev = prevCandidates[prevCandidates.length - 1];

        const bigRet = (curr.index / prev.index - 1) * 100;
        const acwiCurr = acwiByDate[curr.date];
        const acwiPrev = acwiByDate[prev.date];
        if (acwiCurr == null || acwiPrev == null) continue;
        const acwiRet = (acwiCurr / acwiPrev - 1) * 100;
        const alpha = bigRet - acwiRet;

        const note = EQUITY_MONTHLY_NOTES[ym] || '<span style="color:#6B88A8;font-style:italic;">— sin nota —</span>';
        rows.push({ date: curr.date, ym, bigRet, acwiRet, alpha, note });
    }

    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#6B88A8;">No hay meses fin-de-mes en la serie.</td></tr>';
        return;
    }

    // Helpers de formato
    const monthLabel = (dateStr) => {
        const d = new Date(dateStr);
        const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        return `${months[d.getMonth()]}-${d.getFullYear()}`;
    };
    const fmtPct = (v) => {
        const sign = v >= 0 ? '+' : '';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<span style="color:${color};font-weight:600;">${sign}${v.toFixed(2)}%</span>`;
    };
    const fmtAlpha = (v) => {
        const sign = v >= 0 ? '+' : '';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<strong style="color:${color};">${sign}${v.toFixed(2)}pp</strong>`;
    };

    tbody.innerHTML = rows.map(r => `
        <tr>
            <td class="left"><strong>${monthLabel(r.date)}</strong></td>
            <td>${fmtPct(r.bigRet)}</td>
            <td>${fmtPct(r.acwiRet)}</td>
            <td>${fmtAlpha(r.alpha)}</td>
            <td class="left" style="font-size:12px;color:#E8F4FF;line-height:1.5;">${r.note}</td>
        </tr>
    `).join('');
}

// ==============================================================
// FI Monthly Breakdown — mes a mes 2026 (BIG FI TWR vs AGG)
// ==============================================================
function renderFIMonthlyBreakdown(twrSeries, aggSeries) {
    const tbody = document.getElementById('fr-monthly-body');
    if (!tbody || !twrSeries || twrSeries.length < 2) return;

    const aggByDate = Object.fromEntries(aggSeries.map(p => [p.date, p.index]));
    const rows = [];

    // Agrupar por YYYY-MM y tomar el ULTIMO punto disponible de cada mes (1 fila por mes).
    const lastOfMonth = new Map();
    for (const p of twrSeries) {
        if (!p.date.startsWith('2026-')) continue;
        const ym = p.date.slice(0, 7);
        const existing = lastOfMonth.get(ym);
        if (!existing || p.date > existing.date) {
            lastOfMonth.set(ym, p);
        }
    }

    const sortedMonths = Array.from(lastOfMonth.keys()).sort();
    for (const ym of sortedMonths) {
        const curr = lastOfMonth.get(ym);
        // Buscar el ultimo punto del mes anterior
        const [year, month] = ym.split('-').map(Number);
        const prevYear = month === 1 ? year - 1 : year;
        const prevMonth = month === 1 ? 12 : month - 1;
        const prevYM = `${prevYear}-${String(prevMonth).padStart(2, '0')}`;
        const prevCandidates = twrSeries.filter(p => p.date.startsWith(prevYM));
        if (prevCandidates.length === 0) continue;
        const prev = prevCandidates[prevCandidates.length - 1];

        const bigRet = (curr.index / prev.index - 1) * 100;
        const aggCurr = aggByDate[curr.date];
        const aggPrev = aggByDate[prev.date];
        if (aggCurr == null || aggPrev == null) continue;
        const aggRet = (aggCurr / aggPrev - 1) * 100;
        const alpha = bigRet - aggRet;
        let note = FI_MONTHLY_NOTES[ym] || '<span style="color:#6B88A8;font-style:italic;">— sin nota —</span>';

        // Marcar si es punto intra-mes (parcial)
        const isMonthEnd = curr.date.endsWith('-31') || curr.date.endsWith('-30')
            || curr.date.endsWith('-29') || curr.date.endsWith('-28');
        if (!isMonthEnd) {
            note = `<span style="color:#FFA726;">[parcial al ${curr.date.slice(8)}]</span> ${note}`;
        }
        rows.push({ date: curr.date, ym, bigRet, aggRet, alpha, note, isMonthEnd });
    }
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#6B88A8;">Sin meses 2026 en la serie.</td></tr>';
        return;
    }
    const monthLabel = (dateStr) => {
        const d = new Date(dateStr);
        const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        return `${months[d.getMonth()]}-${d.getFullYear()}`;
    };
    const fmtPct = (v) => {
        const sign = v >= 0 ? '+' : '';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<span style="color:${color};font-weight:600;">${sign}${v.toFixed(2)}%</span>`;
    };
    const fmtAlpha = (v) => {
        const sign = v >= 0 ? '+' : '';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<strong style="color:${color};">${sign}${v.toFixed(2)}pp</strong>`;
    };
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td class="left"><strong>${monthLabel(r.date)}${r.isMonthEnd ? '' : ' ⏳'}</strong></td>
            <td>${fmtPct(r.bigRet)}</td>
            <td>${fmtPct(r.aggRet)}</td>
            <td>${fmtAlpha(r.alpha)}</td>
            <td class="left" style="font-size:12px;color:#E8F4FF;line-height:1.5;">${r.note}</td>
        </tr>
    `).join('');
}

// ==============================================================
// NORMALIZED PERFORMANCE — estilo Koyfin (sleeve vs indices, base 100)
// Indices on/off por defecto. SP500 + ACWI visibles, resto ocultos.
// ==============================================================
const NORM_DEFAULT_ON = { 'SP500': true, 'ACWI': true, 'NASDAQ100': false };

async function renderNormalizedPerformance(twrSeries) {
    const chartEl = document.getElementById('er-norm-chart');
    const togglesEl = document.getElementById('er-norm-toggles');
    if (!chartEl) return;

    let bench;
    try {
        const r = await fetch('data/equity_bench_indices.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        bench = await r.json();
    } catch (e) {
        chartEl.innerHTML = '<div style="padding:40px;text-align:center;color:#FFA726;">' +
            'Datos de índices no disponibles. Corré: <code>python scripts/bench_indices_refresher.py</code></div>';
        return;
    }

    // Sleeve trace (siempre visible, dorado). Solo lineas (sin markers) para
    // un look mas limpio tipo TradingView con series diarias densas.
    const sleeveTrace = {
        x: twrSeries.map(p => p.date),
        y: twrSeries.map(p => p.index),
        name: 'BIG Equity Sleeve',
        type: 'scatter', mode: 'lines',
        line: { color: '#D4AF37', width: 3, shape: 'spline', smoothing: 0.3 },
        hovertemplate: '%{x|%d %b %Y}<br><b>BIG Equity</b>: %{y:.2f}<extra></extra>',
    };

    // Un trace por indice; visibilidad inicial segun NORM_DEFAULT_ON
    const idxKeys = Object.keys(bench.indices || {});
    const benchTraces = idxKeys.map(k => {
        const idx = bench.indices[k];
        const on = NORM_DEFAULT_ON[k] !== false;
        return {
            x: idx.series.map(p => p.date),
            y: idx.series.map(p => p.index),
            name: idx.name,
            type: 'scatter', mode: 'lines',
            line: { color: idx.color || '#90A4AE', width: 1.5, shape: 'spline', smoothing: 0.3 },
            visible: on ? true : 'legendonly',
            hovertemplate: '%{x|%d %b %Y}<br><b>' + idx.name + '</b>: %{y:.2f}<extra></extra>',
        };
    });

    const traces = [sleeveTrace, ...benchTraces];
    const layout = {
        paper_bgcolor: '#1A2A3D', plot_bgcolor: '#12243A',
        font: { color: '#90CAF9', family: 'Segoe UI, Arial', size: 11 },
        margin: { t: 30, r: 24, b: 48, l: 60 },
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 12, color: '#ECEFF1' } },
        xaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, type: 'date' },
        yaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, title: { text: 'Base 100 (Inception 31-Jul-2025)', font: { size: 11 } } },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#1F3864', bordercolor: '#2E74B5', font: { color: '#FFF' } },
    };
    Plotly.newPlot('er-norm-chart', traces, layout, { responsive: true, displaylogo: false });

    // Chips de selección — toggle de visibilidad por índice (trace index = k+1)
    if (togglesEl) {
        const ytd = (series) => {
            const a = series.find(p => p.date === '2025-12-31');
            const last = series[series.length - 1];
            return (a && last) ? ((last.index / a.index - 1) * 100) : null;
        };
        togglesEl.innerHTML = idxKeys.map((k, i) => {
            const idx = bench.indices[k];
            const on = NORM_DEFAULT_ON[k] !== false;
            const y = ytd(idx.series);
            const ytdStr = y == null ? '' : ` ${y >= 0 ? '+' : ''}${y.toFixed(1)}%`;
            return `<button class="norm-chip" data-trace="${i + 1}" data-on="${on}" style="` +
                `border:1.5px solid ${idx.color};border-radius:16px;padding:4px 12px;cursor:pointer;` +
                `font-size:12px;font-weight:600;font-family:'Segoe UI';transition:all .15s;` +
                `background:${on ? idx.color : 'transparent'};color:${on ? '#0D1B2A' : idx.color};">` +
                `${idx.name}<span style="font-weight:400;opacity:.85;">${ytdStr}</span></button>`;
        }).join('');

        togglesEl.querySelectorAll('.norm-chip').forEach(btn => {
            btn.onclick = () => {
                const traceIdx = parseInt(btn.getAttribute('data-trace'), 10);
                const isOn = btn.getAttribute('data-on') === 'true';
                const newOn = !isOn;
                Plotly.restyle('er-norm-chart', { visible: newOn ? true : 'legendonly' }, [traceIdx]);
                btn.setAttribute('data-on', String(newOn));
                const color = btn.style.borderColor;
                btn.style.background = newOn ? color : 'transparent';
                btn.style.color = newOn ? '#0D1B2A' : color;
            };
        });
    }
}

// ==============================================================
// EQUITY RACE TAB — Uses REAL TWR data from Pershing transaction history
// ==============================================================
async function renderEquityRace() {
    let realData;
    let data;
    const noCache = '?_=' + Date.now();  // prevent stale JSON

    // ============================================================
    // EQUITY PIE CHART — composición % de cada fondo en el sleeve
    // ============================================================
    try {
        const posResp = await fetch('data/positions_latest.json' + noCache);
        const posData = await posResp.json();
        const equityHoldings = posData.positions.filter(p => p.sleeve === 'Equity');
        const eqTotal = equityHoldings.reduce((a, h) => a + h.value, 0);

        // Compute % of equity sleeve
        const pieData = equityHoldings.map(h => ({
            ticker: h.ticker,
            name: h.name,
            value_usd: h.value,
            pct_sleeve: h.value / eqTotal * 100,
            pct_fund: h.pct,
        })).sort((a, b) => b.pct_sleeve - a.pct_sleeve);

        // Color palette: Navy + Gold + complementary
        const colors = [
            '#1F3864', '#D4AF37', '#5B9BD5', '#A78768', '#7B8C9E',
            '#2E74B5', '#E5BF47', '#90A4AE', '#C9A87E'
        ];

        const trace = {
            type: 'pie',
            hole: 0.4,
            labels: pieData.map(h => h.ticker),
            values: pieData.map(h => h.pct_sleeve),
            customdata: pieData.map(h => [h.name, h.value_usd / 1000, h.pct_fund, h.ticker]),
            hovertemplate:
                '<b>%{customdata[0]}</b> (%{customdata[3]})<br>' +
                'En sleeve Equity: %{value:.2f}%<br>' +
                'En fondo BIG: %{customdata[2]:.2f}%<br>' +
                'MV: $%{customdata[1]:,.0f}K<extra></extra>',
            marker: {
                colors: colors.slice(0, pieData.length),
                line: { color: '#0D1B2A', width: 2 },
            },
            textposition: 'outside',
            textinfo: 'label+percent',
            texttemplate: '<b>%{label}</b><br>%{percent:.1%}',
            textfont: { size: 11, color: '#E0E8F0', family: 'Segoe UI' },
            outsidetextfont: { size: 11, color: '#E0E8F0' },
            automargin: true,
            pull: pieData.map((_, i) => i === 0 ? 0.04 : 0),  // emphasize largest
            sort: false,
            rotation: 90,
            // Leader lines (flechitas) automaticas para slices chicas
            insidetextorientation: 'horizontal',
        };

        const layout = {
            height: 540,
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { family: 'Segoe UI', color: '#E0E8F0' },
            margin: { t: 60, b: 60, l: 170, r: 170 },
            showlegend: false,
            annotations: [{
                text: `<b>Equity</b><br><span style="font-size:13px">$${(eqTotal/1e6).toFixed(2)}M</span><br><span style="font-size:10px;color:#90CAF9">100%</span>`,
                x: 0.5, y: 0.5,
                font: { size: 16, color: '#D4AF37' },
                showarrow: false,
            }],
        };
        Plotly.newPlot('er-pie-equity', [trace], layout, { responsive: true, displaylogo: false });
    } catch (e) {
        console.warn('Failed to render equity pie chart', e);
        document.getElementById('er-pie-equity').innerHTML =
            '<div style="padding:40px;text-align:center;color:#FFA726;">No se pudo cargar positions_latest.json</div>';
    }

    try {
        const r = await fetch('data/equity_race.json' + noCache);
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('equity_race.json not available', e);
        const fallbackEl = document.getElementById('er-norm-chart') || document.getElementById('er-pie-equity');
        if (fallbackEl) fallbackEl.innerHTML =
            '<div style="padding:40px;text-align:center;color:#EF5350;">Data not available. Run: <code>python scripts/equity_race.py</code></div>';
        return;
    }
    // Try to load real TWR series
    try {
        const r2 = await fetch('data/equity_sleeve_real.json' + noCache);
        if (r2.ok) realData = await r2.json();
    } catch(e) { /* fallback to backtest */ }
    // Try to load real holding contributions
    let realContribs = null;
    try {
        const r3 = await fetch('data/equity_contributions_real.json' + noCache);
        if (r3.ok) realContribs = await r3.json();
    } catch(e) { /* table simply won't render */ }

    const stats = data.stats || {};
    const returns = stats.returns || {};
    const ann = stats.annualized || {};
    const holdings = data.holdings || [];

    // KPIs — use REAL TWR if available, else backtest
    const siRet = returns.SI || {};
    let sleeve_si = siRet.sleeve;
    let acwi_si = siRet.acwi;
    let alpha_si = siRet.alpha;
    let dataSource = "Backtest (current weights)";
    let realTwr = null;
    let realAcwi = null;
    if (realData && realData.twr_series && realData.twr_series.length > 0
        && realData.acwi_index_series && realData.acwi_index_series.length > 0) {
        const lastTwr = realData.twr_series[realData.twr_series.length - 1];
        const lastAcwi = realData.acwi_index_series[realData.acwi_index_series.length - 1];
        realTwr = lastTwr.index - 100;
        realAcwi = lastAcwi.index - 100;
        sleeve_si = realTwr;
        acwi_si = realAcwi;
        alpha_si = realTwr - realAcwi;
        dataSource = "Real TWR (Pershing transaction history)";
    }
    const totalEquity = holdings.reduce((a, h) => a + h.value_usd, 0);

    const fmtSigned = (v, unit='%') => {
        if (v == null) return '—';
        return (v >= 0 ? '+' : '') + v.toFixed(2) + unit;
    };

    document.getElementById('er-sleeve-si').textContent = fmtSigned(sleeve_si);
    document.getElementById('er-acwi-si').textContent = fmtSigned(acwi_si);
    const alphaEl = document.getElementById('er-alpha-si');
    alphaEl.textContent = fmtSigned(alpha_si, 'pp');
    alphaEl.style.color = alpha_si >= 0 ? '#81C784' : '#EF5350';
    const statusEl = document.getElementById('er-alpha-status');
    if (alpha_si >= 0) {
        statusEl.innerHTML = '<span style="color:#81C784;font-weight:700;">🏆 GANANDO</span>';
    } else {
        statusEl.innerHTML = '<span style="color:#EF5350;font-weight:700;">🔴 PERDIENDO</span>';
    }
    document.getElementById('er-alpha-ann').textContent = fmtSigned(ann.alpha, 'pp');
    document.getElementById('er-alpha-ann').style.color = (ann.alpha || 0) >= 0 ? '#81C784' : '#EF5350';
    document.getElementById('er-aum').textContent = '$' + (totalEquity / 1e6).toFixed(2) + 'M';

    // Returns table
    const fmtRet = v => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${color};">${sign}${v.toFixed(2)}%</span>`;
    };
    const fmtAlpha = v => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<strong style="color:${color};">${sign}${v.toFixed(2)}pp</strong>`;
    };
    // Compute real multi-period returns from TWR series usando la funcion unificada
    // computeMultiPeriodReturns (fecha-based, YTD anchor = ${y-1}-12-31, tolerance 7d).
    // Reemplaza la implementacion vieja que usaba indices (rompia con puntos intra-mes
    // y el YTD agarraba un anchor random, generando el bug ACWI 5.75% vs 9.09%).
    let realPeriods = null;
    if (realData && realData.twr_series && realData.acwi_index_series && realData.acwi_index_series.length > 0) {
        realPeriods = computeMultiPeriodReturns(
            realData.twr_series,
            realData.acwi_index_series,
            { benchKey: 'acwi', toleranceDays: 31 }  // serie monthly
        );
    }

    // Render Monthly Breakdown table (mes a mes con notas)
    if (realData && realData.twr_series && realData.acwi_index_series) {
        renderEquityMonthlyBreakdown(realData.twr_series, realData.acwi_index_series);
    }

    const R = realPeriods || {
        '1M': returns['1M'], '3M': returns['3M'], '6M': returns['6M'],
        'YTD': returns.YTD, 'SI': returns.SI, 'ANN': ann
    };

    document.getElementById('er-returns-body').innerHTML = `
        <tr class="row-big">
            <td class="left"><strong>BIG Equity Sleeve ${realPeriods ? '(TWR real)' : '(backtest)'}</strong></td>
            <td>${fmtRet(R['1M']?.sleeve)}</td>
            <td>${fmtRet(R['3M']?.sleeve)}</td>
            <td>${fmtRet(R['6M']?.sleeve)}</td>
            <td>${fmtRet(R.YTD?.sleeve)}</td>
            <td>${fmtRet(R.SI?.sleeve)}</td>
            <td>${fmtRet(R.ANN?.sleeve)}</td>
        </tr>
        <tr class="row-bmk">
            <td class="left">MSCI ACWI</td>
            <td>${fmtRet(R['1M']?.acwi)}</td>
            <td>${fmtRet(R['3M']?.acwi)}</td>
            <td>${fmtRet(R['6M']?.acwi)}</td>
            <td>${fmtRet(R.YTD?.acwi)}</td>
            <td>${fmtRet(R.SI?.acwi)}</td>
            <td>${fmtRet(R.ANN?.acwi)}</td>
        </tr>
        <tr class="row-alpha">
            <td class="left"><strong>Alpha</strong></td>
            <td>${fmtAlpha(R['1M']?.alpha)}</td>
            <td>${fmtAlpha(R['3M']?.alpha)}</td>
            <td>${fmtAlpha(R['6M']?.alpha)}</td>
            <td>${fmtAlpha(R.YTD?.alpha)}</td>
            <td>${fmtAlpha(R.SI?.alpha)}</td>
            <td>${fmtAlpha(R.ANN?.alpha)}</td>
        </tr>
    `;

    // Race Chart "er-chart" eliminado 2026-05-26 — el Normalized Performance abajo
    // cubre la misma comparación BIG vs ACWI y agrega S&P 500, Nasdaq, MSCI World.

    // Normalized Performance chart (estilo Koyfin) — sleeve vs indices seleccionables
    if (realData && realData.twr_series) {
        renderNormalizedPerformance(realData.twr_series);
    }

    // (Backtest holdings table removed — using REAL TWR table only)
    const sorted = [...holdings].sort((a, b) => (b.contribution_pct || -999) - (a.contribution_pct || -999));
    const acwi_ref = siRet.acwi || 0;

    // ============================================================
    // CARRERA POR HOLDING (cost basis methodology) — desde 2026-06-17
    // Usa renderHoldingsRace() al final del archivo. La lógica vieja
    // (price race con equity_contributions_real.json) fue removida porque
    // la tabla pasó a 10 columnas y los datos viejos no encajaban.
    // ============================================================
    if (typeof renderHoldingsRace === 'function') {
        renderHoldingsRace('equity', 'er-real-body', 'er-real-source');
    }

    // (Trade Ideas section removed el 2026-05-15 — Lucas quiere ordenar la
    // info primero antes de tener recomendaciones automaticas.)

    // ============================================================
    // ACWI TOP 10 LOOKTHROUGH OVERLAP
    // ============================================================
    try {
        const ovResp = await fetch('data/acwi_overlap.json?_=' + Date.now());
        if (ovResp.ok) {
            const ovData = await ovResp.json();
            const summary = ovData.summary;
            const summaryCard = (label, val, color, sub = '') => `
                <div style="flex:1; background:#12243A; padding:14px; border-radius:6px; border-left:3px solid ${color};">
                    <div style="font-size:11px; color:#90CAF9; margin-bottom:4px;">${label}</div>
                    <div style="font-size:22px; font-weight:700; color:${color};">${val}</div>
                    ${sub ? `<div style="font-size:10px; color:#90CAF9; margin-top:4px;">${sub}</div>` : ''}
                </div>
            `;
            document.getElementById('er-overlap-summary').innerHTML =
                summaryCard('🌐 ACWI Top 10 weight', summary.total_acwi_top10.toFixed(1) + '%', '#64B5F6', '% del ACWI (100% equity)') +
                summaryCard('🎯 BIG Equity lookthrough', summary.total_big_top10_exposure.toFixed(1) + '%', '#D4AF37', '% del Equity Sleeve (100%, apples-to-apples)') +
                summaryCard('⚠️ Diff (BIG − ACWI)', (summary.diff_pp >= 0 ? '+' : '') + summary.diff_pp.toFixed(1) + 'pp', summary.diff_pp >= 0 ? '#81C784' : '#EF5350',
                    summary.diff_pp < 0 ? 'BIG UNDERWEIGHT en megacaps — explica parte del alpha vs ACWI' : 'BIG OVERWEIGHT');

            const ovRows = ovData.overlap.map((h, idx) => {
                const diffColor = h.diff_pp >= 0 ? '#81C784' : '#EF5350';
                const diffSign = h.diff_pp >= 0 ? '+' : '';
                return `
                    <tr>
                        <td>${idx + 1}</td>
                        <td class="left"><strong>${h.ticker}</strong></td>
                        <td class="left" style="font-size:11px;">${h.name}</td>
                        <td class="left" style="font-size:10px;color:#90CAF9;">${h.sector}</td>
                        <td><strong style="color:#64B5F6;">${h.weight_acwi.toFixed(2)}%</strong></td>
                        <td><strong style="color:#D4AF37;">${h.weight_big.toFixed(2)}%</strong></td>
                        <td><strong style="color:${diffColor};">${diffSign}${h.diff_pp.toFixed(2)}pp</strong></td>
                    </tr>
                `;
            }).join('');
            const totalRow = `<tr style="border-top:2px solid #1F3864;background:#12243A;">
                <td colspan="4" class="left"><strong>TOTAL TOP 10</strong></td>
                <td><strong style="color:#64B5F6;">${summary.total_acwi_top10.toFixed(2)}%</strong></td>
                <td><strong style="color:#D4AF37;">${summary.total_big_top10_exposure.toFixed(2)}%</strong></td>
                <td><strong style="color:${summary.diff_pp >= 0 ? '#81C784' : '#EF5350'};">${summary.diff_pp >= 0 ? '+' : ''}${summary.diff_pp.toFixed(2)}pp</strong></td>
            </tr>`;
            document.getElementById('er-overlap-body').innerHTML = ovRows + totalRow;
        }
    } catch(e) {
        console.warn('acwi_overlap.json not available', e);
        document.getElementById('er-overlap-body').innerHTML =
            '<tr><td colspan="7" style="padding:20px;text-align:center;color:#FFA726;">Run: <code>python scripts/acwi_overlap.py</code></td></tr>';
    }

    // ============================================================
    // TOP 10 PER FUND — lookthrough card grid
    // ============================================================
    try {
        const ftResp = await fetch('data/fund_holdings_top10.json?_=' + Date.now());
        if (ftResp.ok) {
            const ft = await ftResp.json();
            const FUND_ORDER = ['CSPX', 'NBGMT', 'MFSCV', 'THOR', 'JHGSC', 'LGLI', 'ARGT', 'ILF', '4BRZ'];
            const fmtName = (k) => k.replace(/_/g, ' ');
            const cards = FUND_ORDER.map(tk => {
                const f = ft[tk]; if (!f) return '';
                const asOf = f._as_of || '?';
                const factsheet = f._factsheet_top10 || {};
                const topHoldings = f.top_holdings || {};
                let holdings = Object.entries(factsheet).filter(([k,v]) => !k.startsWith('_') && typeof v === 'number');
                if (!holdings.length) {
                    holdings = Object.entries(topHoldings).filter(([k,v]) => typeof v === 'number');
                }
                holdings.sort((a,b) => b[1] - a[1]);
                const total = holdings.reduce((s,[,v]) => s+v, 0);
                const rows = holdings.slice(0,10).map(([name,w],i) => `
                    <tr>
                        <td style="padding:4px 6px; color:#90CAF9; font-size:11px;">${i+1}</td>
                        <td style="padding:4px 6px; font-size:12px;">${fmtName(name)}</td>
                        <td style="padding:4px 6px; text-align:right; font-weight:600; color:#D4AF37;">${w.toFixed(2)}%</td>
                    </tr>
                `).join('');
                const note = factsheet._note || '';
                return `
                    <div style="background:#12243A; border-radius:8px; padding:14px; border-left:3px solid #D4AF37;">
                        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:8px;">
                            <div>
                                <div style="font-size:14px; font-weight:700; color:#D4AF37;">${tk}</div>
                                <div style="font-size:11px; color:#90CAF9;">${f.name || ''}</div>
                            </div>
                            <div style="font-size:10px; color:#90CAF9; text-align:right;">as of ${asOf}</div>
                        </div>
                        <table style="width:100%; border-collapse:collapse;">
                            <tbody>${rows}</tbody>
                            <tr style="border-top:1px solid #1F3864;">
                                <td colspan="2" style="padding:6px 6px 0; font-size:11px; color:#90CAF9;"><strong>Top 10 total</strong></td>
                                <td style="padding:6px 6px 0; text-align:right; font-weight:700; color:#D4AF37;">${total.toFixed(1)}%</td>
                            </tr>
                        </table>
                        ${note ? `<div style="margin-top:8px; padding-top:8px; border-top:1px solid #1F3864; font-size:10px; color:#FFA726; line-height:1.4;">${note}</div>` : ''}
                    </div>
                `;
            }).join('');
            document.getElementById('er-fund-top10').innerHTML = cards;
        }
    } catch(e) {
        console.warn('fund_holdings_top10.json not available', e);
    }

    // ============================================================
    // TOP 10 CONSOLIDADO BIG Equity sleeve
    // ============================================================
    try {
        const cResp = await fetch('data/equity_top10_consolidated.json?_=' + Date.now());
        if (cResp.ok) {
            const cData = await cResp.json();
            const rows = cData.consolidated_top10.map((h, i) => {
                const funds = (h.funds || []).map(f =>
                    `<span style="color:#90CAF9;">${f.fund}</span> <span style="color:#D4AF37;">${f.weight_in_fund.toFixed(1)}%</span>`
                ).join('  ·  ');
                const bigBar = Math.min(h.weight_in_sleeve_pct / 3.0, 1.0) * 100;
                return `
                    <tr>
                        <td style="padding:6px 8px; color:#90CAF9; font-size:12px;">${h.rank}</td>
                        <td style="padding:6px 8px; font-weight:600;">${h.name}</td>
                        <td style="padding:6px 8px; font-size:11px; color:#90CAF9;">${funds}</td>
                        <td style="padding:6px 8px; text-align:right; font-weight:700; color:#D4AF37;">${h.weight_in_sleeve_pct.toFixed(2)}%</td>
                        <td style="padding:6px 8px;">
                            <div style="background:#0C1B2E; height:14px; border-radius:3px; position:relative; min-width:140px;">
                                <div style="background:linear-gradient(90deg,#D4AF37 0%,#E5BF47 100%); height:100%; width:${bigBar}%; border-radius:3px;"></div>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
            const total = cData.consolidated_top10.reduce((s, h) => s + h.weight_in_sleeve_pct, 0);
            document.getElementById('er-consolidated-body').innerHTML = `
                <table class="data-table" style="margin-top:8px;">
                    <thead>
                        <tr>
                            <th class="left">#</th>
                            <th class="left">Holding</th>
                            <th class="left">Vía (fondo · peso fondo)</th>
                            <th>% del Equity Sleeve</th>
                            <th class="left">Bar</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                    <tr style="border-top:2px solid #1F3864;background:#12243A;">
                        <td colspan="3" style="padding:8px;"><strong>TOTAL TOP 15 (% del Equity sleeve)</strong></td>
                        <td style="padding:8px;text-align:right;"><strong style="color:#D4AF37;">${total.toFixed(2)}%</strong></td>
                        <td></td>
                    </tr>
                </table>
                <div style="margin-top:8px; font-size:11px; color:#90CAF9;">
                    Refreshed ${cData.refreshedAt} · Método: ${cData.method}
                </div>
            `;
        }
    } catch(e) {
        console.warn('equity_top10_consolidated.json not available', e);
    }

    // (Specific trade recommendations removed el 2026-05-15 — info primero,
    // recomendaciones automaticas despues cuando este todo bien ordenado.)
}

// ==============================================================
// NORMALIZED PERFORMANCE FI — estilo Koyfin (sleeve vs indices FI, base 100)
// Indices on/off por defecto. AGG + LQD visibles, HYG + EMB ocultos.
// ==============================================================
const FI_NORM_DEFAULT_ON = { 'AGG': true, 'LQD': true, 'HYG': false, 'EMB': false };

async function renderFINormalizedPerformance(twrSeries) {
    const chartEl = document.getElementById('fi-norm-chart');
    const togglesEl = document.getElementById('fi-norm-toggles');
    if (!chartEl) return;

    let bench;
    try {
        const r = await fetch('data/fi_bench_indices.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        bench = await r.json();
    } catch (e) {
        chartEl.innerHTML = '<div style="padding:40px;text-align:center;color:#FFA726;">' +
            'Datos de índices FI no disponibles. Corré: <code>python scripts/fi_bench_indices_refresher.py</code></div>';
        return;
    }

    // Sleeve trace (siempre visible, dorado). Solo lineas (sin markers) para
    // un look mas limpio tipo TradingView con series diarias densas.
    const sleeveTrace = {
        x: twrSeries.map(p => p.date),
        y: twrSeries.map(p => p.index),
        name: 'BIG FI Sleeve',
        type: 'scatter', mode: 'lines',
        line: { color: '#D4AF37', width: 3, shape: 'spline', smoothing: 0.3 },
        hovertemplate: '%{x|%d %b %Y}<br><b>BIG FI</b>: %{y:.2f}<extra></extra>',
    };

    // Un trace por indice; visibilidad inicial segun FI_NORM_DEFAULT_ON
    const idxKeys = Object.keys(bench.indices || {});
    const benchTraces = idxKeys.map(k => {
        const idx = bench.indices[k];
        const on = FI_NORM_DEFAULT_ON[k] !== false;
        return {
            x: idx.series.map(p => p.date),
            y: idx.series.map(p => p.index),
            name: idx.name,
            type: 'scatter', mode: 'lines',
            line: { color: idx.color || '#90A4AE', width: 1.5, shape: 'spline', smoothing: 0.3 },
            visible: on ? true : 'legendonly',
            hovertemplate: '%{x|%d %b %Y}<br><b>' + idx.name + '</b>: %{y:.2f}<extra></extra>',
        };
    });

    const traces = [sleeveTrace, ...benchTraces];
    const layout = {
        paper_bgcolor: '#1A2A3D', plot_bgcolor: '#12243A',
        font: { color: '#90CAF9', family: 'Segoe UI, Arial', size: 11 },
        margin: { t: 30, r: 24, b: 48, l: 60 },
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 12, color: '#ECEFF1' } },
        xaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, type: 'date' },
        yaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, title: { text: 'Base 100 (Inception 31-Jul-2025)', font: { size: 11 } } },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#1F3864', bordercolor: '#2E74B5', font: { color: '#FFF' } },
    };
    Plotly.newPlot('fi-norm-chart', traces, layout, { responsive: true, displaylogo: false });

    // Chips de selección — toggle de visibilidad por índice (trace index = k+1)
    if (togglesEl) {
        const ytd = (series) => {
            const a = series.find(p => p.date === '2025-12-31');
            const last = series[series.length - 1];
            return (a && last) ? ((last.index / a.index - 1) * 100) : null;
        };
        togglesEl.innerHTML = idxKeys.map((k, i) => {
            const idx = bench.indices[k];
            const on = FI_NORM_DEFAULT_ON[k] !== false;
            const y = ytd(idx.series);
            const ytdStr = y == null ? '' : ` ${y >= 0 ? '+' : ''}${y.toFixed(1)}%`;
            return `<button class="norm-chip" data-trace="${i + 1}" data-on="${on}" style="` +
                `border:1.5px solid ${idx.color};border-radius:16px;padding:4px 12px;cursor:pointer;` +
                `font-size:12px;font-weight:600;font-family:'Segoe UI';transition:all .15s;` +
                `background:${on ? idx.color : 'transparent'};color:${on ? '#0D1B2A' : idx.color};">` +
                `${idx.name}<span style="font-weight:400;opacity:.85;">${ytdStr}</span></button>`;
        }).join('');

        togglesEl.querySelectorAll('.norm-chip').forEach(btn => {
            btn.onclick = () => {
                const traceIdx = parseInt(btn.getAttribute('data-trace'), 10);
                const isOn = btn.getAttribute('data-on') === 'true';
                const newOn = !isOn;
                Plotly.restyle('fi-norm-chart', { visible: newOn ? true : 'legendonly' }, [traceIdx]);
                btn.setAttribute('data-on', String(newOn));
                const color = btn.style.borderColor;
                btn.style.background = newOn ? color : 'transparent';
                btn.style.color = newOn ? '#0D1B2A' : color;
            };
        });
    }
}

// ==============================================================
// FI RACE TAB
// ==============================================================
async function renderFIRace() {
    const noCache = '?_=' + Date.now();

    // Load REAL TWR (from Pershing transactions) — flow-adjusted, no backtest
    let fiReal = null;
    try {
        const rr = await fetch('data/fi_sleeve_real.json' + noCache);
        if (rr.ok) fiReal = await rr.json();
    } catch (e) { /* sigue sin REAL si no esta */ }

    // ============================================================
    // FI PIE CHART — composición % de cada fondo en el sleeve
    // ============================================================
    try {
        const posResp = await fetch('data/positions_latest.json' + noCache);
        const posData = await posResp.json();
        const fiHoldings = posData.positions.filter(p => p.sleeve === 'Fixed Income');
        const fiTotal = fiHoldings.reduce((a, h) => a + h.value, 0);

        const pieData = fiHoldings.map(h => ({
            ticker: h.ticker,
            name: h.name,
            value_usd: h.value,
            pct_sleeve: h.value / fiTotal * 100,
            pct_fund: h.pct,
        })).sort((a, b) => b.pct_sleeve - a.pct_sleeve);

        // FI palette: greens + complementary (sleeve color = green)
        const colors = [
            '#2E7D32', '#81C784', '#1F3864', '#D4AF37', '#5B9BD5',
            '#A5D6A7', '#388E3C', '#90A4AE'
        ];

        const trace = {
            type: 'pie',
            hole: 0.4,
            labels: pieData.map(h => h.ticker),
            values: pieData.map(h => h.pct_sleeve),
            customdata: pieData.map(h => [h.name, h.value_usd / 1000, h.pct_fund, h.ticker]),
            hovertemplate:
                '<b>%{customdata[0]}</b> (%{customdata[3]})<br>' +
                'En sleeve FI: %{value:.2f}%<br>' +
                'En fondo BIG: %{customdata[2]:.2f}%<br>' +
                'MV: $%{customdata[1]:,.0f}K<extra></extra>',
            marker: {
                colors: colors.slice(0, pieData.length),
                line: { color: '#0D1B2A', width: 2 },
            },
            textposition: 'outside',
            textinfo: 'label+percent',
            texttemplate: '<b>%{label}</b><br>%{percent:.1%}',
            textfont: { size: 11, color: '#E0E8F0', family: 'Segoe UI' },
            outsidetextfont: { size: 11, color: '#E0E8F0' },
            automargin: true,
            pull: pieData.map((_, i) => i === 0 ? 0.04 : 0),
            sort: false,
            rotation: 90,
        };

        const layout = {
            height: 540,
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { family: 'Segoe UI', color: '#E0E8F0' },
            margin: { t: 60, b: 60, l: 170, r: 170 },
            showlegend: false,
            annotations: [{
                text: `<b>Fixed Income</b><br><span style="font-size:13px">$${(fiTotal/1e6).toFixed(2)}M</span><br><span style="font-size:10px;color:#A5D6A7">100%</span>`,
                x: 0.5, y: 0.5,
                font: { size: 14, color: '#D4AF37' },
                showarrow: false,
            }],
        };
        Plotly.newPlot('fr-pie-fi', [trace], layout, { responsive: true, displaylogo: false });
    } catch (e) {
        console.warn('Failed to render FI pie chart', e);
        const el = document.getElementById('fr-pie-fi');
        if (el) el.innerHTML = '<div style="padding:40px;text-align:center;color:#FFA726;">No se pudo cargar positions_latest.json</div>';
    }

    let data;
    try {
        const r = await fetch('data/fi_race.json' + noCache);
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('fi_race.json not available', e);
        const fallbackEl = document.getElementById('fi-norm-chart') || document.getElementById('fr-pie-fi');
        if (fallbackEl) fallbackEl.innerHTML =
            '<div style="padding:40px;text-align:center;color:#EF5350;">FI data not available. Run: <code>python scripts/fi_race.py</code></div>';
        return;
    }

    const stats = data.stats || {};
    let returns = stats.returns || {};
    let ann = stats.annualized || {};
    const holdings = data.holdings || [];
    const pm = data.portfolio_metrics || {};

    // Multi-Period FRESCO (T-1): si fiReal (fi_sleeve_real.json, refrescado diario por
    // el cron) tiene twr_series, recomputamos los returns con computeMultiPeriodReturns
    // — mismo approach que Equity Race. Cae al fi_race.json (stats, mensual) solo si falta.
    if (fiReal && fiReal.twr_series && fiReal.agg_index_series && fiReal.agg_index_series.length) {
        // benchKey:'agg' -> cada row sale {sleeve, agg, alpha}, exactamente lo que lee
        // fr-returns-body. ANN sale como result.ANN con la misma forma.
        const fresh = computeMultiPeriodReturns(
            fiReal.twr_series, fiReal.agg_index_series,
            { benchKey: 'agg', toleranceDays: 31 }
        );
        returns = fresh;
        if (fresh.ANN) ann = fresh.ANN;
    }

    const fmtSigned = (v, unit='%') => {
        if (v == null) return '—';
        return (v >= 0 ? '+' : '') + v.toFixed(2) + unit;
    };

    // KPIs
    const siRet = returns.SI || {};
    document.getElementById('fr-sleeve-si').textContent = fmtSigned(siRet.sleeve);
    document.getElementById('fr-agg-si').textContent = fmtSigned(siRet.agg);
    const alphaEl = document.getElementById('fr-alpha-si');
    alphaEl.textContent = fmtSigned(siRet.alpha, 'pp');
    alphaEl.style.color = (siRet.alpha || 0) >= 0 ? '#81C784' : '#EF5350';
    document.getElementById('fr-alpha-status').innerHTML = (siRet.alpha || 0) >= 0
        ? '<span style="color:#81C784;font-weight:700;">🏆 GANANDO</span>'
        : '<span style="color:#EF5350;font-weight:700;">🔴 PERDIENDO</span>';
    document.getElementById('fr-ytw').textContent = pm.weighted_ytw ? pm.weighted_ytw.toFixed(2) + '%' : '—';
    document.getElementById('fr-spread-ust').textContent = pm.spread_vs_ust_10y != null
        ? `Spread UST 10Y: ${pm.spread_vs_ust_10y >= 0 ? '+' : ''}${pm.spread_vs_ust_10y.toFixed(2)}pp (UST ${pm.ust_10y_yield}%)`
        : '—';
    document.getElementById('fr-dur').textContent = pm.weighted_duration ? pm.weighted_duration.toFixed(2) + 'y' : '—';
    document.getElementById('fr-mat').textContent = pm.weighted_maturity ? `Maturity: ${pm.weighted_maturity.toFixed(2)}y` : '—';
    document.getElementById('fr-aum').textContent = pm.total_fi_usd ? '$' + (pm.total_fi_usd / 1e6).toFixed(2) + 'M' : '—';

    // Returns table
    const fmtRet = v => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${color};">${sign}${v.toFixed(2)}%</span>`;
    };
    const fmtAlpha = v => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<strong style="color:${color};">${sign}${v.toFixed(2)}pp</strong>`;
    };
    document.getElementById('fr-returns-body').innerHTML = `
        <tr class="row-big">
            <td class="left"><strong>BIG FI Sleeve</strong></td>
            <td>${fmtRet(returns['1M']?.sleeve)}</td>
            <td>${fmtRet(returns['3M']?.sleeve)}</td>
            <td>${fmtRet(returns['6M']?.sleeve)}</td>
            <td>${fmtRet(returns.YTD?.sleeve)}</td>
            <td>${fmtRet(returns.SI?.sleeve)}</td>
            <td>${fmtRet(ann.sleeve)}</td>
        </tr>
        <tr class="row-bmk">
            <td class="left">AGG (Bloomberg US Aggregate)</td>
            <td>${fmtRet(returns['1M']?.agg)}</td>
            <td>${fmtRet(returns['3M']?.agg)}</td>
            <td>${fmtRet(returns['6M']?.agg)}</td>
            <td>${fmtRet(returns.YTD?.agg)}</td>
            <td>${fmtRet(returns.SI?.agg)}</td>
            <td>${fmtRet(ann.agg)}</td>
        </tr>
        <tr class="row-alpha">
            <td class="left"><strong>Alpha</strong></td>
            <td>${fmtAlpha(returns['1M']?.alpha)}</td>
            <td>${fmtAlpha(returns['3M']?.alpha)}</td>
            <td>${fmtAlpha(returns['6M']?.alpha)}</td>
            <td>${fmtAlpha(returns.YTD?.alpha)}</td>
            <td>${fmtAlpha(returns.SI?.alpha)}</td>
            <td>${fmtAlpha(ann.alpha)}</td>
        </tr>
    `;

    // Render Monthly Breakdown FI (mes a mes 2026 con notas)
    if (fiReal && fiReal.twr_series && fiReal.agg_index_series) {
        renderFIMonthlyBreakdown(fiReal.twr_series, fiReal.agg_index_series);
    }

    // Race Chart "fr-chart" eliminado 2026-05-26 — el Normalized Performance abajo
    // cubre la misma comparación BIG FI vs AGG (mismo patron que Equity Race chart removal).

    // Normalized Performance FI chart (estilo Koyfin) — sleeve vs indices FI seleccionables
    if (fiReal && fiReal.twr_series) {
        renderFINormalizedPerformance(fiReal.twr_series);
    }

    // Holdings table
    const sorted = [...holdings].sort((a, b) => (b.contribution_pct || -999) - (a.contribution_pct || -999));
    const fmtPct = v => {
        if (v == null) return '—';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${color};font-weight:700;">${sign}${v.toFixed(2)}%</span>`;
    };
    const fmtContrib = v => {
        if (v == null) return '—';
        const color = v >= 0 ? '#D4AF37' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${color};font-weight:700;">${sign}${v.toFixed(2)}pp</span>`;
    };
    const fmtSpread = v => {
        if (v == null) return '—';
        const color = v >= 2 ? '#81C784' : v >= 0 ? '#D4AF37' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${color};font-weight:700;">${sign}${v.toFixed(2)}pp</span>`;
    };
    // NAV del cierre anterior (T-1) por fondo, de baha (refresh_fi_race_daily.py).
    // Muestra el valor + moneda; la fecha del NAV va en el tooltip. "—" si aun no
    // hay NAV vivo (TGF carry, MANEM, o el cron todavia no corrio).
    const fmtNav = h => {
        if (h.nav_t1 == null) return '<span style="color:#6B88A8;">—</span>';
        const ccy = h.nav_currency ? ' <span style="font-size:9px;opacity:0.7;">' + h.nav_currency + '</span>' : '';
        const d = h.nav_date ? new Date(h.nav_date).toISOString().slice(0, 10) : 's/f';
        return `<span title="NAV al ${d} (baha, cierre anterior)">${h.nav_t1.toFixed(2)}${ccy}</span>`;
    };
    const holdingsRows = sorted.map(h => `
        <tr>
            <td class="left"><strong>${h.name}</strong></td>
            <td class="left" style="font-size:10px;color:#90CAF9;">${h.source}</td>
            <td>$${(h.value_usd/1000).toFixed(0)}K</td>
            <td>${h.weight_pct.toFixed(1)}%</td>
            <td><strong style="color:#81C784;">${h.ytw.toFixed(2)}%</strong></td>
            <td>${h.duration.toFixed(2)}y</td>
            <td>${h.maturity.toFixed(2)}y</td>
            <td><span class="sleeve-badge fi">${h.rating}</span></td>
            <td>${fmtSpread(h.spread_vs_ust)}</td>
            <td>${fmtNav(h)}</td>
            <td>${fmtPct(h.ytd_return_pct)}</td>
            <td>${fmtPct(h.si_return_pct)}</td>
            <td>${fmtContrib(h.ytd_contribution_pct)}</td>
            <td>${fmtContrib(h.contribution_pct)}</td>
        </tr>
    `).join('');
    // AGG reference row
    const aggYtd = returns.YTD?.agg;
    const aggSi = returns.SI?.agg;
    const aggRow = `<tr style="background:#12243A;border-top:2px solid #64B5F6;">
        <td class="left"><strong style="color:#64B5F6;">AGG <span style="font-size:10px;opacity:0.8;">(Benchmark)</span></strong></td>
        <td class="left" style="font-size:10px;color:#90CAF9;">Yahoo:AGG</td>
        <td style="color:#6B88A8;">—</td>
        <td style="color:#6B88A8;">—</td>
        <td><span style="color:#64B5F6;">~${pm.ust_10y_yield ? pm.ust_10y_yield.toFixed(2) : '—'}%</span></td>
        <td>~6.5y</td>
        <td>~8.5y</td>
        <td><span class="sleeve-badge fi">AA</span></td>
        <td style="color:#6B88A8;">0.00pp</td>
        <td style="color:#6B88A8;">—</td>
        <td>${fmtPct(aggYtd)}</td>
        <td>${fmtPct(aggSi)}</td>
        <td style="color:#6B88A8;">—</td>
        <td style="color:#6B88A8;">—</td>
    </tr>`;
    document.getElementById('fr-holdings-body').innerHTML = holdingsRows + aggRow;

    // (FI Trade Ideas section removed el 2026-05-15 — info primero, ideas despues.)
}

// ==============================================================
// EQUITY BREAKDOWN — Style + Sectorial + Regional (Apr-2026 cierre, Maximus)
// ==============================================================
async function renderEquityBreakdown() {
    let data;
    try {
        const r = await fetch('data/equity_breakdown_latest.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('equity_breakdown_latest.json not available', e);
        return;
    }

    // Reusable bar renderer (BIG gold + BMK blue)
    const renderBar = (label, bigVal, bmkVal, bigLabel = 'BIG', bmkLabel = 'BMK') => {
        const max = Math.max(bigVal, bmkVal, 1);
        const bigW = (bigVal / max) * 100;
        const bmkW = (bmkVal / max) * 100;
        const bigDisplay = Number.isInteger(bigVal) ? bigVal : bigVal.toFixed(1);
        const bmkDisplay = Number.isInteger(bmkVal) ? bmkVal : bmkVal.toFixed(1);
        return `
            <div style="margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-size: 11px; font-weight: 700; color: #E0E8F0;">${label}</span>
                    <span style="font-size: 10px; color: #90CAF9;">
                        <span style="color:#D4AF37;font-weight:700;">${bigLabel} ${bigDisplay}%</span>
                        &nbsp;·&nbsp;
                        <span style="color:#64B5F6;">${bmkLabel} ${bmkDisplay}%</span>
                    </span>
                </div>
                <div style="position: relative; height: 18px; background: #12243A; border-radius: 3px; overflow: hidden; margin-bottom: 3px;">
                    <div style="position: absolute; height: 50%; top: 0; left: 0; width: ${bigW}%; background: linear-gradient(90deg, #D4AF37 0%, #E5BF47 100%); border-radius: 3px 0 0 0;"></div>
                    <div style="position: absolute; height: 50%; bottom: 0; left: 0; width: ${bmkW}%; background: linear-gradient(90deg, #64B5F6 0%, #74C5FF 100%); border-radius: 0 0 0 3px;"></div>
                </div>
            </div>
        `;
    };

    // Style bars
    const st = data.style;
    const styleHTML = st.rows.map(r => renderBar(r.category, r.big, r.bmk, 'BIG', 'BMK')).join('');
    document.getElementById('er-style-bars').innerHTML = styleHTML +
        `<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #2E74B5; font-size: 11px; color: #90CAF9;">
            <strong style="color:#D4AF37;">Total BIG: ${st.totals.big}%</strong> ·
            <strong style="color:#64B5F6;">Total BMK: ${st.totals.bmk}%</strong>
        </div>`;

    // Sectorial bars
    const sec = data.sectorial;
    const sectorHTML = sec.rows.map(r => renderBar(r.category, r.big, r.acwi, 'BIG', 'ACWI')).join('');
    let sectorFooter = `<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #2E74B5; font-size: 11px; color: #90CAF9;">
        <strong style="color:#D4AF37;">Total BIG: ${sec.totals.big}%</strong> ·
        <strong style="color:#64B5F6;">Total ACWI: ${sec.totals.acwi}%</strong>`;
    if (sec.footnote) {
        sectorFooter += `<div style="font-size: 10px; color: #6B88A8; margin-top: 4px; font-style: italic;">${sec.footnote}</div>`;
    }
    sectorFooter += `</div>`;
    document.getElementById('er-sectorial-bars').innerHTML = sectorHTML + sectorFooter;

    // Regional bars
    const reg = data.regional;
    const regionalHTML = reg.rows.map(r => renderBar(r.category, r.big, r.acwi, 'BIG', 'ACWI')).join('');
    document.getElementById('er-regional-bars').innerHTML = regionalHTML +
        `<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #2E74B5; font-size: 11px; color: #90CAF9;">
            <strong style="color:#D4AF37;">Total BIG: ${reg.totals.big}%</strong> ·
            <strong style="color:#64B5F6;">Total ACWI: ${reg.totals.acwi}%</strong>
        </div>`;

    // KPI summary
    const valueRow = st.rows.find(r => r.category === 'Value');
    const latamRow = reg.rows.find(r => r.category === 'Latin Am.');
    const finRow = sec.rows.find(r => r.category === 'Financial');
    if (valueRow) document.getElementById('er-kpi-value').textContent = valueRow.big + '%';
    if (latamRow) document.getElementById('er-kpi-latam').textContent = latamRow.big + '%';
    if (finRow) document.getElementById('er-kpi-fin').textContent = finRow.big + '%';
}

// ==============================================================
// FI BREAKDOWN — Sub-asset class & Credit Quality (Apr-2026 cierre, Maximus)
// ==============================================================
async function renderFIBreakdown() {
    let data;
    try {
        const r = await fetch('data/fi_breakdown_latest.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('fi_breakdown_latest.json not available', e);
        return;
    }

    // Helper: render side-by-side bar (BIG vs BMK)
    const renderBar = (label, bigVal, bmkVal, bigLabel = 'BIG', bmkLabel = 'BMK') => {
        const max = Math.max(bigVal, bmkVal, 1);
        const bigW = (bigVal / max) * 100;
        const bmkW = (bmkVal / max) * 100;
        return `
            <div style="margin-bottom: 14px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-size: 11px; font-weight: 700; color: #E0E8F0;">${label}</span>
                    <span style="font-size: 10px; color: #90CAF9;">
                        <span style="color:#D4AF37;font-weight:700;">${bigLabel} ${bigVal}%</span>
                        &nbsp;·&nbsp;
                        <span style="color:#64B5F6;">${bmkLabel} ${bmkVal}%</span>
                    </span>
                </div>
                <div style="position: relative; height: 18px; background: #12243A; border-radius: 3px; overflow: hidden; margin-bottom: 3px;">
                    <div style="position: absolute; height: 50%; top: 0; left: 0; width: ${bigW}%; background: linear-gradient(90deg, #D4AF37 0%, #E5BF47 100%); border-radius: 3px 0 0 0;"></div>
                    <div style="position: absolute; height: 50%; bottom: 0; left: 0; width: ${bmkW}%; background: linear-gradient(90deg, #64B5F6 0%, #74C5FF 100%); border-radius: 0 0 0 3px;"></div>
                </div>
            </div>
        `;
    };

    // Sub-asset class bars
    const sa = data.sub_asset_class;
    const subassetHTML = sa.rows.map(r => renderBar(r.category, r.big, r.agg, 'BIG', 'AGG')).join('');
    document.getElementById('fr-subasset-bars').innerHTML = subassetHTML +
        `<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #2E74B5; font-size: 11px; color: #90CAF9;">
            <strong style="color:#D4AF37;">Total BIG: ${sa.totals.big}%</strong> ·
            <strong style="color:#64B5F6;">Total AGG: ${sa.totals.agg}%</strong>
        </div>`;

    // Credit quality bars
    const cq = data.credit_quality;
    const creditHTML = cq.rows.map(r => renderBar(r.rating, r.big, r.bmk, 'BIG', 'BMK')).join('');
    document.getElementById('fr-credit-bars').innerHTML = creditHTML +
        `<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #2E74B5; font-size: 11px; color: #90CAF9;">
            <strong style="color:#D4AF37;">Total BIG: ${cq.totals.big}%</strong> ·
            <strong style="color:#64B5F6;">Total BMK: ${cq.totals.bmk}%</strong>
        </div>`;

    // Summary KPIs
    const s = cq.summary;
    document.getElementById('fr-big-ig').textContent = s.big_ig + '%';
    document.getElementById('fr-big-hy').textContent = s.big_hy + '%';
    // AGG = 100% IG por definicion del index. La data Maximus deprecated metia
    // 14.3% como "NR" pero para AGG, NR son Treasuries + Agency MBS (= AAA implicito).
    // Hardcodeamos a 100 hasta rebuildear fi_breakdown desde primary.
    document.getElementById('fr-bmk-ig').textContent = '100%';
}

// ==============================================================
// UPDATE TIMESTAMPS
// ==============================================================
function updateTime() {
    const now = new Date();
    const s = now.toLocaleString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    const upd = document.getElementById('update-time');
    if (upd) upd.textContent = s;
    const ft = document.getElementById('footer-time');
    if (ft) ft.textContent = s;
}

// ==============================================================
// INIT
// ==============================================================
(async function init() {
    updateTime();
    initTabs();

    // Try fetching live prices
    // Priority 1: local static JSON (from scripts/price_refresher.py)
    // Priority 2: direct Stooq fetch (may fail due to CORS in browsers)
    let livePrices = {};
    try {
        const resp = await fetch('data/live_prices.json');
        if (resp.ok) {
            const json = await resp.json();
            livePrices = json.prices || {};
            console.log("Live prices loaded from static JSON:", json.refreshedAt);
        } else {
            throw new Error('No static JSON, trying direct fetch');
        }
    } catch(e) {
        try {
            livePrices = await fetchAllLivePrices();
            console.log("Live prices fetched directly:", livePrices);
        } catch(e2) {
            console.warn("Live prices unavailable; using manual NAV fallback", e2);
        }
    }

    // Try loading Lynk data JSON (from scripts/lynk_refresher.py)
    try {
        const respL = await fetch('data/lynk_data.json?_=' + Date.now());
        if (respL.ok) {
            const L = await respL.json();
            if (L.nav) window.LYNK_DATA.nav = L.nav;
            if (L.aum) window.LYNK_DATA.aum = L.aum;
            if (L.change24h !== null) window.LYNK_DATA.change24h = L.change24h;
            if (L.returnYTD !== null) window.LYNK_DATA.returnYTD = L.returnYTD;
            if (L.returnSI !== null) window.LYNK_DATA.returnSI = L.returnSI;
            if (L.returnAnnualized !== null) window.LYNK_DATA.returnAnnualized = L.returnAnnualized;
            if (L.volatility !== null) window.LYNK_DATA.volatility = L.volatility;
            if (L.sharpe !== null) window.LYNK_DATA.sharpe = L.sharpe;
            if (L.refreshedAt) window.LYNK_DATA.refreshedAt = L.refreshedAt;
            console.log("Lynk data loaded:", L.refreshedAt);
        }
    } catch(e) {
        console.log("Lynk static JSON not found; using hardcoded");
    }

    // Fecha REAL del ultimo NAV Lynk (para los labels "al <fecha>"). Fuente de
    // verdad = ultimo punto de lynk_nav_series.json. Fallback = refreshedAt de
    // lynk_data.json (cuando corrio el scraper). El series date es el NAV real;
    // refreshedAt es solo "cuando lo bajamos".
    try {
        const respS = await fetch('data/lynk_nav_series.json?_=' + Date.now());
        if (respS.ok) {
            const sj = await respS.json();
            const series = sj && sj.series;
            if (series && series.length && series[series.length - 1].date) {
                LYNK_NAV_DATE = series[series.length - 1].date;
                LYNK_NAV_DATE_SOURCE = 'series';
            }
        }
    } catch(e) { /* fallback abajo */ }
    if (!LYNK_NAV_DATE && window.LYNK_DATA && window.LYNK_DATA.refreshedAt) {
        LYNK_NAV_DATE = window.LYNK_DATA.refreshedAt.slice(0, 10);
        LYNK_NAV_DATE_SOURCE = 'refreshedAt';
    }
    console.log("Lynk NAV date (as-of):", LYNK_NAV_DATE, "(via " + LYNK_NAV_DATE_SOURCE + ")");

    renderLynkStaleBanner();

    renderOverview();
    renderPositions(livePrices);  // async — fire and forget, no bloquea otros renders
    renderCurrency();
    renderCountry();
    renderYield();
    renderPerformance();
    renderEquityRace();
    renderEquityBreakdown();
    renderFIRace();
    renderFIBreakdown();
    renderAltsRace();
    renderDataHealth();
    renderAllFreshness();
})();

// ==============================================================
// ALTS RACE — BIG Alts Sleeve vs 60/40 and HFRX
// ==============================================================
async function renderAltsRace() {
    const noCache = '?_=' + Date.now();
    let data;
    try {
        const r = await fetch('data/alts_race.json' + noCache);
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('alts_race.json not available', e);
        const el = document.getElementById('ar-chart');
        if (el) el.innerHTML = '<div style="padding:40px;text-align:center;color:#EF5350;">Alts data not available. Run: <code>python scripts/alts_race.py</code></div>';
        return;
    }

    // Lucas pidio quitar benchmarks del tab Alts Race (privates iliquidos no son
    // comparables con indices liquidos). Solo extraemos r6040 para obtener los
    // returns del sleeve mismo (SI / YTD / multi-period), ignoramos bmk6040/hfrx.
    const stats6040 = data.stats_vs_6040 || {};
    const r6040 = stats6040.returns || {};
    const ann6040 = stats6040.annualized || {};
    const holdings = data.holdings || [];
    const pm = data.portfolio_metrics || {};

    const fmtSigned = (v, unit='%') => v == null ? '—' : (v >= 0 ? '+' : '') + v.toFixed(2) + unit;

    // KPIs (solo Alts Sleeve SI + AUM — sin benchmarks)
    const si6040 = r6040.SI || {};
    document.getElementById('ar-sleeve-si').textContent = fmtSigned(si6040.sleeve);
    document.getElementById('ar-aum').textContent = pm.total_alts_usd ? '$' + (pm.total_alts_usd / 1e6).toFixed(2) + 'M' : '—';

    // Returns table
    const fmtRet = v => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<span style="color:${color};">${v >= 0 ? '+' : ''}${v.toFixed(2)}%</span>`;
    };
    const fmtAlpha = v => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<strong style="color:${color};">${v >= 0 ? '+' : ''}${v.toFixed(2)}pp</strong>`;
    };

    // Tabla solo con BIG Alts Sleeve — sin filas BMK/Alpha (Lucas quito benchmarks)
    document.getElementById('ar-returns-body').innerHTML = `
        <tr class="row-big">
            <td class="left"><strong>BIG Alts Sleeve</strong></td>
            <td>${fmtRet(r6040['1M']?.sleeve)}</td>
            <td>${fmtRet(r6040['3M']?.sleeve)}</td>
            <td>${fmtRet(r6040['6M']?.sleeve)}</td>
            <td>${fmtRet(r6040.YTD?.sleeve)}</td>
            <td>${fmtRet(r6040.SI?.sleeve)}</td>
            <td>${fmtRet(ann6040.sleeve)}</td>
        </tr>
    `;

    // Pie chart (Alts sleeve composition)
    try {
        const total = holdings.reduce((a, h) => a + h.value_usd, 0);
        const pieData = [...holdings].sort((a, b) => b.value_usd - a.value_usd);
        const colors = ['#E65100', '#FFA726', '#D4AF37', '#FB8C00', '#A78768', '#1F3864', '#5B9BD5', '#FFB74D'];
        const subClassEmoji = {
            'private_equity': '🏛️',
            'private_credit': '💵',
            'crypto': '₿',
            'commodity': '🥇',
        };
        const trace = {
            type: 'pie',
            hole: 0.4,
            labels: pieData.map(h => h.ticker),
            values: pieData.map(h => h.weight_pct),
            customdata: pieData.map(h => [h.name, h.value_usd/1000, h.ticker, h.sub_class, subClassEmoji[h.sub_class] || '']),
            hovertemplate:
                '<b>%{customdata[0]}</b> (%{customdata[2]})<br>' +
                '%{customdata[4]} %{customdata[3]}<br>' +
                'En sleeve Alts: %{value:.2f}%<br>' +
                'MV: $%{customdata[1]:,.0f}K<extra></extra>',
            marker: { colors: colors.slice(0, pieData.length), line: { color: '#0D1B2A', width: 2 } },
            textposition: 'outside',
            textinfo: 'label+percent',
            texttemplate: '<b>%{label}</b><br>%{percent:.1%}',
            textfont: { size: 11, color: '#E0E8F0' },
            outsidetextfont: { size: 11, color: '#E0E8F0' },
            automargin: true,
            pull: pieData.map((_, i) => i === 0 ? 0.04 : 0),
            sort: false,
            rotation: 90,
        };
        const layout = {
            height: 540,
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
            font: { family: 'Segoe UI', color: '#E0E8F0' },
            margin: { t: 60, b: 60, l: 170, r: 170 },
            showlegend: false,
            annotations: [{
                text: `<b>Alternatives</b><br><span style="font-size:13px">$${(total/1e6).toFixed(2)}M</span><br><span style="font-size:10px;color:#FFB74D">100%</span>`,
                x: 0.5, y: 0.5,
                font: { size: 14, color: '#D4AF37' },
                showarrow: false,
            }],
        };
        Plotly.newPlot('ar-pie-alts', [trace], layout, { responsive: true, displaylogo: false });
    } catch (e) {
        console.warn('Failed to render Alts race pie', e);
    }

    // Race chart — solo Alts Sleeve (sin benchmarks por pedido de Lucas)
    const sleeveKeys = Object.keys(data.sleeve_index).sort();
    const traces = [
        {
            x: sleeveKeys.map(k => k + '-15'),
            y: sleeveKeys.map(k => data.sleeve_index[k]),
            name: 'BIG Alts Sleeve',
            type: 'scatter', mode: 'lines+markers',
            line: { color: '#FFA726', width: 3 },
            marker: { size: 6, color: '#FFA726' },
            hovertemplate: '%{x|%b %Y}<br>Alts: <b>%{y:.2f}</b><extra></extra>'
        }
    ];
    const layout = {
        paper_bgcolor: '#1A2A3D',
        plot_bgcolor: '#12243A',
        font: { color: '#FFB74D', family: 'Segoe UI, Arial', size: 11 },
        margin: { t: 30, r: 24, b: 48, l: 60 },
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 13, color: '#ECEFF1' } },
        xaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, type: 'date' },
        yaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, title: { text: 'Base 100', font: { size: 11 } } },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#1F3864', bordercolor: '#2E74B5', font: { color: '#FFF' } }
    };
    Plotly.newPlot('ar-chart', traces, layout, { responsive: true, displaylogo: false });

    // Holdings table
    const subClassLabel = {
        'private_equity': '🏛️ Private Equity',
        'private_credit': '💵 Private Credit',
        'private_infra':  '🏗️ Private Infra',
        'crypto': '₿ Crypto',
        'commodity': '🥇 Commodity',
    };
    // Source + fecha de valuacion (transparencia del lag de privates)
    const srcDate = (h) => {
        const vd = h.valuation_date || '';
        let label, color;
        if (vd === 'live') { label = 'live (al 18-may)'; color = '#81C784'; }
        else if (vd) { label = `val ${vd}`; color = (vd >= '2026-04') ? '#81C784' : '#FFA726'; }
        else { label = ''; color = '#90CAF9'; }
        return `<span style="color:${color};font-weight:600;">${label}</span>`
             + `<br><span style="font-size:9px;color:#6B88A8;">${h.source || ''}</span>`;
    };
    const sorted = [...holdings].sort((a, b) => (b.ytd_contribution_pct || -999) - (a.ytd_contribution_pct || -999));
    document.getElementById('ar-holdings-body').innerHTML = sorted.map(h => `
        <tr>
            <td class="left"><strong>${h.name}</strong> <span style="font-size:10px;color:#90CAF9;">(${h.ticker})</span></td>
            <td class="left">${subClassLabel[h.sub_class] || h.sub_class}</td>
            <td class="left" style="font-size:10px;">${srcDate(h)}</td>
            <td>$${(h.value_usd / 1000).toFixed(0)}K</td>
            <td>${h.weight_pct.toFixed(1)}%</td>
            <td>${fmtRet(h.ytd_return_pct)}</td>
            <td>${fmtRet(h.si_return_pct)}</td>
            <td>${fmtAlpha(h.ytd_contribution_pct)}</td>
            <td>${fmtAlpha(h.contribution_pct)}</td>
        </tr>
    `).join('');

    // Sub-class bars
    const subBreak = pm.sub_class_breakdown_pct || {};
    const subOrder = ['private_equity', 'private_credit', 'private_infra', 'crypto', 'commodity'];
    const subColors = { 'private_equity': '#1F3864', 'private_credit': '#5B9BD5', 'private_infra': '#66BB6A', 'crypto': '#FFB74D', 'commodity': '#D4AF37' };
    const subTraces = [{
        type: 'bar',
        orientation: 'h',
        x: subOrder.map(s => subBreak[s] || 0),
        y: subOrder.map(s => subClassLabel[s] || s),
        marker: { color: subOrder.map(s => subColors[s]) },
        text: subOrder.map(s => `${(subBreak[s] || 0).toFixed(1)}%`),
        textposition: 'auto',
        hovertemplate: '%{y}<br>%{x:.2f}% del sleeve<extra></extra>',
    }];
    const subLayout = {
        height: 240,
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#E0E8F0' },
        margin: { t: 20, b: 30, l: 160, r: 30 },
        xaxis: { ticksuffix: '%', gridcolor: '#1F3864' },
        yaxis: { automargin: true },
        showlegend: false,
    };
    Plotly.newPlot('ar-subclass-bars', subTraces, subLayout, { responsive: true, displaylogo: false });

    // ============================================================
    // CONCENTRATION RANKING + LIQUIDITY BUCKETS
    // ============================================================
    try {
        // Holdings vienen de fi/alts data + positions_latest. Uso BIG_POSITIONS
        // para tener pesos al dia y matchear ISINs con ALTS_LIQUIDITY.
        const altsPos = (typeof BIG_POSITIONS !== 'undefined' ? BIG_POSITIONS : [])
            .filter(p => p.sleeve === 'Alternatives');
        const altsTotal = altsPos.reduce((a, p) => a + p.value, 0);

        // ----- Concentration ranking -----
        const sortedByMV = [...altsPos].sort((a, b) => b.value - a.value);
        const concEl = document.getElementById('ar-concentration');
        if (concEl) {
            const top1 = sortedByMV[0];
            const top1PctSleeve = top1 ? (top1.value / altsTotal * 100) : 0;
            const top3PctSleeve = sortedByMV.slice(0, 3).reduce((a, p) => a + p.value, 0) / altsTotal * 100;
            const headerAlert = top1PctSleeve >= 30
                ? `<div style="font-size:11px;color:#EF5350;margin-bottom:10px;">🔴 Alta concentración: <strong>${top1.ticker}</strong> es ${top1PctSleeve.toFixed(1)}% del sleeve</div>`
                : top1PctSleeve >= 20
                    ? `<div style="font-size:11px;color:#FFA726;margin-bottom:10px;">🟠 Concentración moderada: top-1 = ${top1PctSleeve.toFixed(1)}%</div>`
                    : `<div style="font-size:11px;color:#81C784;margin-bottom:10px;">🟢 Concentración baja: top-1 = ${top1PctSleeve.toFixed(1)}%</div>`;
            const top3Note = `<div style="font-size:11px;color:#90CAF9;margin-bottom:12px;">Top 3 = ${top3PctSleeve.toFixed(1)}% del sleeve</div>`;
            const rows = sortedByMV.map((p, i) => {
                const pctSleeve = p.value / altsTotal * 100;
                const barW = (pctSleeve / top1PctSleeve * 100).toFixed(1);
                const color = pctSleeve >= 30 ? '#EF5350' : pctSleeve >= 20 ? '#FFA726' : '#81C784';
                return `
                    <div style="margin-bottom: 8px;">
                        <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px;">
                            <span style="color:#E0E8F0;"><strong>${i+1}.</strong> ${p.ticker}</span>
                            <span style="color:${color};font-weight:700;">${pctSleeve.toFixed(1)}%</span>
                        </div>
                        <div style="height:6px;background:#0D1B2A;border-radius:3px;overflow:hidden;">
                            <div style="height:100%;width:${barW}%;background:${color};"></div>
                        </div>
                    </div>`;
            }).join('');
            concEl.innerHTML = headerAlert + top3Note + rows;
        }

        // ----- Liquidity buckets: Daily + Lock-up -----
        const liqEl = document.getElementById('ar-liquidity');
        if (liqEl) {
            const dailyItems = [];
            const lockedItems = [];
            for (const p of altsPos) {
                const liq = (typeof ALTS_LIQUIDITY !== 'undefined' && ALTS_LIQUIDITY[p.isin]) || null;
                if (liq && liq.profile === 'daily') {
                    dailyItems.push({ ...p, ...liq });
                } else {
                    lockedItems.push({ ...p, ...liq, lock_type: liq?.lock_type || 'Sin clasificar' });
                }
            }
            const dailyMV = dailyItems.reduce((a, p) => a + p.value, 0);
            const lockedMV = lockedItems.reduce((a, p) => a + p.value, 0);
            const today = new Date();

            // Daily bucket (verde)
            const dailyHTML = `
                <div style="margin-bottom: 14px; padding: 10px; background:#0D1B2A; border-left: 3px solid #81C784; border-radius: 4px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                        <span style="font-size:12px;font-weight:700;color:#81C784;">🟢 Daily (líquido)</span>
                        <span style="font-size:13px;color:#E0E8F0;font-weight:700;">${(dailyMV/altsTotal*100).toFixed(1)}% · $${(dailyMV/1e6).toFixed(2)}M</span>
                    </div>
                    <div style="font-size:11px;color:#90CAF9;">${dailyItems.map(p => p.ticker).join(', ')}</div>
                </div>`;

            // Lock-up table (rows ordenadas por unlock date asc — los que se desbloquean antes arriba)
            const fmtDate = (d) => d ? new Date(d).toLocaleDateString('es-AR', {day:'2-digit', month:'short', year:'2-digit'}) : '—';
            const sortedLocked = lockedItems.slice().sort((a, b) => {
                if (!a.unlock_date && !b.unlock_date) return 0;
                if (!a.unlock_date) return 1;
                if (!b.unlock_date) return -1;
                return new Date(a.unlock_date) - new Date(b.unlock_date);
            });
            const lockRows = sortedLocked.map(p => {
                let daysLeft = null;
                let daysLabel = '—';
                let daysColor = '#90CAF9';
                if (p.unlock_date) {
                    daysLeft = Math.ceil((new Date(p.unlock_date) - today) / 86400000);
                    if (daysLeft <= 0) { daysLabel = '<strong style="color:#81C784;">DESBLOQUEADO</strong>'; }
                    else if (daysLeft <= 90) { daysLabel = `<strong style="color:#FFA726;">${daysLeft}d ⚠</strong>`; }
                    else { daysLabel = `${daysLeft}d`; }
                }
                return `
                    <tr>
                        <td style="padding:6px 8px;"><strong>${p.ticker}</strong></td>
                        <td style="padding:6px 8px; font-size:11px; color:#90CAF9;">${p.lock_type}</td>
                        <td style="padding:6px 8px; font-size:11px;">${fmtDate(p.purchase_date)}</td>
                        <td style="padding:6px 8px; font-size:11px; font-weight:600;">${fmtDate(p.unlock_date)}</td>
                        <td style="padding:6px 8px; text-align:center; font-size:12px;">${daysLabel}</td>
                        <td style="padding:6px 8px; text-align:right; font-weight:700; color:#D4AF37;">$${(p.value/1000).toFixed(0)}K</td>
                    </tr>`;
            }).join('');
            const hardLocked = sortedLocked.filter(p => p.unlock_date && (new Date(p.unlock_date) - today) > 0)
                .reduce((a, p) => a + p.value, 0);
            const lockHTML = `
                <div style="margin-bottom: 8px; padding: 10px; background:#0D1B2A; border-left: 3px solid #B0A0FF; border-radius: 4px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                        <span style="font-size:12px;font-weight:700;color:#B0A0FF;">🔒 Lock-up</span>
                        <span style="font-size:13px;color:#E0E8F0;font-weight:700;">${(lockedMV/altsTotal*100).toFixed(1)}% · $${(lockedMV/1e6).toFixed(2)}M</span>
                    </div>
                    <table style="width:100%; border-collapse:collapse; font-size:11px;">
                        <thead>
                            <tr style="border-bottom:1px solid #1F3864; color:#90CAF9;">
                                <th style="padding:6px 8px; text-align:left;">Ticker</th>
                                <th style="padding:6px 8px; text-align:left;">Tipo</th>
                                <th style="padding:6px 8px; text-align:left;">Compra</th>
                                <th style="padding:6px 8px; text-align:left;">Desbloqueo</th>
                                <th style="padding:6px 8px; text-align:center;">Faltan</th>
                                <th style="padding:6px 8px; text-align:right;">Monto</th>
                            </tr>
                        </thead>
                        <tbody>${lockRows}</tbody>
                    </table>
                    <div style="margin-top:8px; padding-top:8px; border-top:1px solid #1F3864; font-size:11px; color:#90CAF9;">
                        Bloqueado hasta unlock: <strong style="color:#FFA726;">$${(hardLocked/1e6).toFixed(2)}M</strong>
                        (no rescatable sin penalty hasta su fecha)
                    </div>
                </div>`;

            liqEl.innerHTML = dailyHTML + lockHTML;
        }
    } catch (e) {
        console.warn('Failed to render concentration/liquidity panel', e);
    }
}

// ==============================================================
// DATA HEALTH — Lineage + status of every data source
// ==============================================================
// ==============================================================
// SLEEVE TWR AUDIT — verifica que TWR reportado coincida con la formula
// (MV_end - flow) / MV_start - 1 mes a mes. Util para validar visualmente
// que el YTD desglosado tenga sentido.
// ==============================================================
async function renderSleeveTwrAudit() {
    // Renderiza tablas audit: Equity, FI (con TWR + flow), Alts (solo return + index).
    await renderSleeveTwrAuditOne({
        jsonPath: 'data/equity_sleeve_real.json',
        tbodyId: 'dh-sleeve-audit-equity',
        tfootId: 'dh-sleeve-audit-equity-foot',
        sleeveLabel: 'Equity',
    });
    await renderSleeveTwrAuditOne({
        jsonPath: 'data/fi_sleeve_real.json',
        tbodyId: 'dh-sleeve-audit-fi',
        tfootId: 'dh-sleeve-audit-fi-foot',
        sleeveLabel: 'Fixed Income',
    });
    await renderAltsAudit();
}

// Audit Alts — estructura distinta: no hay MV+flow auditable, solo returns
// mensuales reportados por managers (privates corren por NAVs trimestrales).
async function renderAltsAudit() {
    const tbody = document.getElementById('dh-sleeve-audit-alts');
    const tfoot = document.getElementById('dh-sleeve-audit-alts-foot');
    if (!tbody) return;

    let data;
    try {
        const r = await fetch('data/alts_race.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch (e) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#6B88A8;">No se pudo cargar alts_race.json</td></tr>';
        return;
    }

    const smr = data.sleeve_monthly_returns || {};
    const si = data.sleeve_index || {};
    const monthsAll = Object.keys(smr).sort();
    const months2026 = monthsAll.filter(m => m.startsWith('2026-'));

    if (months2026.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#6B88A8;">Sin datos 2026 en alts_race</td></tr>';
        return;
    }

    const fmtPct = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
    const monthLabel = (m) => {
        const [y, mm] = m.split('-');
        const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        return `${months[parseInt(mm) - 1]}-${y.slice(2)}`;
    };

    let compoundYtd = 1;
    const rows = months2026.map(m => {
        const ret = smr[m];
        const idx = si[m];
        compoundYtd *= (1 + ret);
        return { month: m, ret, idx };
    });
    compoundYtd -= 1;

    tbody.innerHTML = rows.map(r => {
        const color = r.ret >= 0 ? '#81C784' : '#EF5350';
        // Notas placeholder — Lucas las edita despues si quiere
        const isCurrent = r.month === months2026[months2026.length - 1];
        const note = isCurrent
            ? '<span style="color:#FFA726;">Mes corriente (parcial)</span>'
            : '<span style="color:#6B88A8;font-style:italic;">— sin nota —</span>';
        return `
            <tr>
                <td class="left"><strong>${monthLabel(r.month)}</strong></td>
                <td style="color:${color};font-weight:600;">${fmtPct(r.ret)}</td>
                <td>${r.idx != null ? r.idx.toFixed(4) : '—'}</td>
                <td class="left" style="font-size:12px;color:#E8F4FF;">${note}</td>
            </tr>
        `;
    }).join('');

    const compoundColor = compoundYtd >= 0 ? '#81C784' : '#EF5350';
    if (tfoot) {
        tfoot.innerHTML = `
            <tr style="border-top:2px solid #D4AF37;">
                <td class="left"><strong>YTD 2026 (compound)</strong></td>
                <td style="color:${compoundColor};font-weight:700;font-size:14px;">${fmtPct(compoundYtd)}</td>
                <td colspan="2" style="font-size:11px;color:#6B88A8;">Producto de (1+return) de cada mes 2026</td>
            </tr>
        `;
    }

    // renderAltsHoldingsBreakdown eliminado 2026-05-26 — duplicaba ar-holdings-body
    // del tab Alts Race. Si necesitás detalle holding-level del YTD Alts, mirá ese tab.
}

async function renderSleeveTwrAuditOne(cfg) {
    const tbody = document.getElementById(cfg.tbodyId);
    const tfoot = document.getElementById(cfg.tfootId);
    if (!tbody) return;

    let data;
    try {
        const r = await fetch(cfg.jsonPath + '?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#6B88A8;">No se pudo cargar ${cfg.jsonPath}</td></tr>`;
        return;
    }

    const twr = data.twr_series || [];
    if (twr.length < 2) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#6B88A8;">Serie TWR vacia</td></tr>';
        return;
    }

    const fmtMoney = (v) => '$' + (v >= 0 ? '' : '−') + Math.abs(v / 1e6).toFixed(2) + 'M';
    const fmtFlow  = (v) => (v >= 0 ? '+' : '−') + '$' + Math.abs(v / 1e3).toFixed(0) + 'K';
    const fmtPct   = (v) => (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
    const monthLabel = (d) => {
        const dt = new Date(d);
        const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        return `${months[dt.getMonth()]}-${String(dt.getFullYear()).slice(2)}`;
    };

    // Verificacion: la formula recalculada deberia coincidir con el TWR del JSON
    // dentro de ~10 bps (tolerancia para rounding de Modified Dietz simplificado).
    // FILTRO: solo mostrar meses 2026 (Lucas no quiere ver historia 2025 aca).
    const YTD_YEAR_FILTER = '2026-';
    const TOL = 0.001;  // 10 bps
    const rows = [];
    let allMatch = true;
    for (let i = 1; i < twr.length; i++) {
        const prev = twr[i - 1];
        const curr = twr[i];
        // Filtrar solo meses 2026
        if (!curr.date.startsWith(YTD_YEAR_FILTER)) continue;
        const mvStart = prev.mv_usd;
        const flow = curr.flow_in || 0;
        const mvEnd = curr.mv_usd;
        const twrReported = curr.twr;
        const twrCalc = (mvEnd - flow) / mvStart - 1;
        const diff = Math.abs(twrCalc - twrReported);
        const match = diff < TOL;
        if (!match) allMatch = false;
        rows.push({
            date: curr.date,
            mvStart, flow, mvEnd,
            twrReported, twrCalc, match, diff,
        });
    }

    // Compound YTD (todos los rows ya son del 2026)
    let compoundYtd = 1;
    rows.forEach(r => { compoundYtd *= (1 + r.twrReported); });
    compoundYtd -= 1;

    tbody.innerHTML = rows.map(r => {
        const formulaStr = `(${fmtMoney(r.mvEnd)} − ${fmtFlow(r.flow)}) / ${fmtMoney(r.mvStart)} − 1 = ${fmtPct(r.twrCalc)}`;
        const matchIcon = r.match
            ? '<span style="color:#81C784;font-weight:700;font-size:16px;">✓</span>'
            : `<span style="color:#EF5350;font-weight:700;font-size:16px;">✗ (${(r.diff*10000).toFixed(0)}bps)</span>`;
        const flowColor = r.flow >= 0 ? '#81C784' : '#EF5350';
        const twrColor = r.twrReported >= 0 ? '#81C784' : '#EF5350';
        return `
            <tr>
                <td class="left"><strong>${monthLabel(r.date)}</strong></td>
                <td>${fmtMoney(r.mvStart)}</td>
                <td style="color:${flowColor};">${fmtFlow(r.flow)}</td>
                <td style="color:${twrColor};font-weight:600;">${fmtPct(r.twrReported)}</td>
                <td>${fmtMoney(r.mvEnd)}</td>
                <td style="font-size:11px;color:#90CAF9;font-family:monospace;">${formulaStr}</td>
                <td style="text-align:center;">${matchIcon}</td>
            </tr>
        `;
    }).join('');

    // Footer: compound YTD + status global
    const compoundColor = compoundYtd >= 0 ? '#81C784' : '#EF5350';
    const statusBadge = allMatch
        ? '<span style="color:#81C784;font-weight:700;">✓ Todos los meses validados</span>'
        : '<span style="color:#EF5350;font-weight:700;">✗ Hay meses con bug — revisar</span>';
    if (tfoot) {
        tfoot.innerHTML = `
            <tr style="border-top:2px solid #D4AF37;">
                <td class="left" colspan="3"><strong>YTD 2026 (compound de meses 2026)</strong></td>
                <td style="color:${compoundColor};font-weight:700;font-size:14px;">${fmtPct(compoundYtd)}</td>
                <td colspan="2" style="font-size:11px;color:#6B88A8;">Producto de (1+TWR) de cada mes 2026</td>
                <td style="text-align:center;">${statusBadge}</td>
            </tr>
        `;
    }
}

async function renderDataHealth() {
    // Atribucion YTD (peso x retorno por sleeve) — arriba del tab
    renderAttributionYTD();
    // Render audit de cadena TWR mes a mes (al final del tab)
    renderSleeveTwrAudit();

    let catalog;
    try {
        const r = await fetch('data/data_health_catalog.json?_=' + Date.now());
        if (!r.ok) throw new Error('no catalog');
        catalog = await r.json();
    } catch (e) {
        console.warn('data_health_catalog.json not available', e);
        return;
    }

    // ============================================================
    // Resolver fecha de freshness segun el "freshness_source" del catalogo
    // ============================================================
    async function getSourceDate(src) {
        const fs = src.freshness_source;
        const field = src.freshness_field;

        // 1) JSON file — leer la fecha del primer file que matchee
        if (fs === 'json_file') {
            for (const path of (src.files || [])) {
                try {
                    const r = await fetch(path + '?_=' + Date.now());
                    if (!r.ok) continue;
                    const d = await r.json();
                    if (field && d[field]) return new Date(d[field]);
                    for (const f of ['asOf', 'refreshedAt', 'refreshed_at', 'as_of', 'lastUpdate']) {
                        if (d[f]) return new Date(d[f]);
                    }
                } catch (e) {}
            }
            return null;
        }

        // 2) Metadata constant — POSITIONS_AS_OF o METADATA_LAST_REVIEW en JS
        if (fs === 'metadata_constant') {
            if (field === 'METADATA_LAST_REVIEW' && typeof METADATA_LAST_REVIEW !== 'undefined') {
                return new Date(METADATA_LAST_REVIEW);
            }
            if (field === 'POSITIONS_AS_OF' && typeof POSITIONS_AS_OF !== 'undefined') {
                return new Date(POSITIONS_AS_OF);
            }
            return null;
        }

        // 3) funds_dir_oldest — el min as_of_factsheet en data/funds/*.json
        if (fs === 'funds_dir_oldest') {
            let oldest = null;
            for (const path of (src.files || [])) {
                try {
                    const r = await fetch(path + '?_=' + Date.now());
                    if (!r.ok) continue;
                    const d = await r.json();
                    const dateStr = d[field || 'as_of_factsheet'];
                    if (!dateStr) continue;
                    const dt = new Date(dateStr);
                    if (!oldest || dt < oldest) oldest = dt;
                } catch (e) {}
            }
            return oldest;
        }

        // 4) live_prices oldest — el min date en MANUAL_NAV dict (live_prices.js)
        if (fs === 'live_prices_oldest') {
            if (typeof MANUAL_NAV === 'undefined') return null;
            let oldest = null;
            for (const isin of Object.keys(MANUAL_NAV)) {
                const dStr = MANUAL_NAV[isin] && MANUAL_NAV[isin].date;
                if (!dStr) continue;
                const dt = new Date(dStr);
                if (!oldest || dt < oldest) oldest = dt;
            }
            return oldest;
        }

        // 5) Sin date tracking — manual o live
        return null;
    }

    // ============================================================
    // Status calculation con soporte market-aware
    // ============================================================
    function statusOf(src, sourceDate) {
        if (src.deprecated) {
            return { code: 'deprecated', label: '🪦 DEPRECATED', color: '#90A4AE' };
        }
        if (src.freshness_source === 'live_always_ok') {
            return { code: 'live', label: '🟢 LIVE', color: '#81C784' };
        }
        if (src.freshness_source === 'manual_no_tracking') {
            return { code: 'unknown', label: '⚪ Sin tracking', color: '#90A4AE' };
        }
        if (sourceDate == null) {
            return { code: 'unknown', label: '⚪ Unknown', color: '#90A4AE' };
        }

        // Market-aware: compara contra ultimo close US esperado (skip weekends)
        if (src.treat_as_market_data) {
            const lastClose = lastExpectedClose();  // reusamos la funcion del banner
            if (sourceDate >= lastClose) {
                return { code: 'ok', label: '🟢 Al cierre', color: '#81C784' };
            }
            const behindDays = Math.floor((lastClose - sourceDate) / 86400000);
            if (behindDays <= 2) return { code: 'needs_refresh', label: `🟠 ${behindDays}d behind`, color: '#FFA726' };
            return { code: 'stale', label: `🔴 ${behindDays}d STALE`, color: '#EF5350' };
        }

        // Calendar-day SLA
        const now = new Date();
        // Math.max para evitar -1d por timezone
        const daysAgo = Math.max(0, Math.floor((now - sourceDate) / 86400000));
        const sla = src.expected_frequency_days || 31;
        if (daysAgo <= sla) return { code: 'ok', label: '🟢 OK', color: '#81C784' };
        if (daysAgo <= sla * 1.5) return { code: 'needs_refresh', label: '🟠 NEEDS REFRESH', color: '#FFA726' };
        return { code: 'stale', label: '🔴 STALE', color: '#EF5350' };
    }

    const now = new Date();
    const rows = [];
    const todos = [];
    let counts = { live: 0, ok: 0, needs_refresh: 0, stale: 0, unknown: 0, deprecated: 0 };

    // Agrupar fuentes por automation -> frequency_group
    // Orden: auto/daily, auto/monthly, manual/weekly, manual/monthly, manual/quarterly, manual/on_demand
    const FREQ_ORDER = ['daily', 'weekly', 'monthly', 'quarterly', 'on_demand'];
    const FREQ_LABELS = {
        daily:     { label: 'DIARIAS',      color: '#81C784', emoji: '🟢' },
        weekly:    { label: 'SEMANALES',    color: '#FFE082', emoji: '🟡' },
        monthly:   { label: 'MENSUALES',    color: '#FFA726', emoji: '🟠' },
        quarterly: { label: 'TRIMESTRALES', color: '#CE93D8', emoji: '🟣' },
        on_demand: { label: 'ON-DEMAND',    color: '#90A4AE', emoji: '⚫' },
    };

    function sortKey(s) {
        const automationOrder = s.automation === 'auto' ? 0 : 1;
        const freqOrder = FREQ_ORDER.indexOf(s.frequency_group || 'on_demand');
        return [automationOrder, freqOrder === -1 ? 99 : freqOrder];
    }
    const orderedSources = [...catalog.sources].sort((a, b) => {
        const [a1, a2] = sortKey(a);
        const [b1, b2] = sortKey(b);
        return a1 - b1 || a2 - b2;
    });

    // Helpers para insertar dividers
    function bigDivider(emoji, text, color) {
        return `
            <tr style="background:transparent;"><td colspan="8" style="padding:0;border:none;height:18px;"></td></tr>
            <tr class="divider-row" style="background:#0D1B2A;border-top:2px solid #1F3864;border-bottom:2px solid #1F3864;">
                <td colspan="8" style="text-align:center;padding:10px;font-size:11px;font-weight:700;letter-spacing:2px;color:${color};">
                    ${emoji} ${text}
                </td>
            </tr>
            <tr style="background:transparent;"><td colspan="8" style="padding:0;border:none;height:6px;"></td></tr>
        `;
    }

    function subDivider(freq) {
        const m = FREQ_LABELS[freq] || { label: freq.toUpperCase(), color: '#6B88A8', emoji: '·' };
        return `
            <tr style="background:#12243A;">
                <td colspan="8" style="text-align:center;padding:8px 14px;font-size:11px;font-weight:700;letter-spacing:2px;color:${m.color};border-top:1px solid ${m.color}33;border-bottom:1px solid ${m.color}33;">
                    ${m.emoji} ${m.label} ${m.emoji}
                </td>
            </tr>
        `;
    }

    let prevAutomation = null;
    let prevFrequency = null;

    for (const src of orderedSources) {
        // Inserta big divider cuando cambia automation
        if (src.automation !== prevAutomation) {
            if (src.automation === 'auto') {
                rows.push(bigDivider('🤖', 'FUENTES AUTOMÁTICAS (cron, sin intervención)', '#81C784'));
            } else {
                rows.push(bigDivider('🔧', 'FUENTES MANUALES (Lucas refresh)', '#FFA726'));
            }
            prevAutomation = src.automation;
            prevFrequency = null;  // reset para que dispare el sub-divider tambien
        }

        // Inserta sub-divider cuando cambia frequency dentro del mismo automation
        if (src.frequency_group !== prevFrequency) {
            rows.push(subDivider(src.frequency_group || 'on_demand'));
            prevFrequency = src.frequency_group;
        }

        const sourceDate = await getSourceDate(src);
        const status = statusOf(src, sourceDate);
        counts[status.code] = (counts[status.code] || 0) + 1;

        // Calcular days display (market vs calendar)
        let daysDisplay = '—';
        let dateDisplay = sourceDate ? sourceDate.toISOString().slice(0, 10) : '—';
        if (sourceDate) {
            if (src.treat_as_market_data) {
                const lastClose = lastExpectedClose();
                if (sourceDate >= lastClose) {
                    daysDisplay = 'al cierre';
                } else {
                    const behind = Math.floor((lastClose - sourceDate) / 86400000);
                    daysDisplay = `${behind}d behind`;
                }
            } else {
                const days = Math.max(0, Math.floor((now - sourceDate) / 86400000));
                daysDisplay = days === 0 ? 'hoy' : `${days}d`;
            }
        }

        const freqDisplay = src.treat_as_market_data
            ? 'market'
            : (src.expected_frequency_days ? `${src.expected_frequency_days}d` : '—');

        const feedsTabs = (src.feeds_tabs && src.feeds_tabs.length) ? src.feeds_tabs.join(', ') : '—';

        rows.push(`
            <tr>
                <td class="left"><strong>${src.name}</strong><br><span style="font-size:10px;color:#90CAF9;">${src.source_type}</span></td>
                <td class="left">${src.category}</td>
                <td class="left" style="font-size:10px;color:#E0E8F0;">${feedsTabs}</td>
                <td>${dateDisplay}</td>
                <td><strong style="color:${status.color};">${daysDisplay}</strong></td>
                <td>${freqDisplay}</td>
                <td class="left"><span style="color:${status.color};font-weight:700;">${status.label}</span></td>
                <td class="left" style="font-size:10px;color:#90CAF9;">${src.refresh_method}</td>
            </tr>
        `);

        if (status.code === 'deprecated' || status.code === 'stale' || status.code === 'needs_refresh') {
            const reason = src.deprecated
                ? `→ ${src.deprecated_reason || 'deprecated'}`
                : `→ ${daysDisplay} (esperado ${freqDisplay})`;
            todos.push(`<li><strong>${src.name}</strong> ${reason}</li>`);
        }
    }

    // Summary cards
    const summaryCard = (label, count, color) => `
        <div style="flex:1; background:#12243A; padding:12px; border-radius:6px; border-left:3px solid ${color};">
            <div style="font-size:11px; color:#90CAF9; margin-bottom:4px;">${label}</div>
            <div style="font-size:24px; font-weight:700; color:${color};">${count}</div>
        </div>
    `;
    document.getElementById('dh-summary').innerHTML =
        summaryCard('🟢 LIVE/OK', (counts.live || 0) + (counts.ok || 0), '#81C784') +
        summaryCard('🟠 NEEDS REFRESH', counts.needs_refresh || 0, '#FFA726') +
        summaryCard('🔴 STALE', counts.stale || 0, '#EF5350');

    document.getElementById('dh-tbody').innerHTML = rows.join('');
    document.getElementById('dh-todos').innerHTML = todos.length
        ? `<ul style="color:#FFA726;">${todos.join('')}</ul>`
        : '<p style="color:#81C784;">✅ Todas las fuentes al día</p>';
}

// ==============================================================
// ATRIBUCION YTD — cuadro "peso x retorno por sleeve" en Data Health
// Lee data/attribution_ytd.json (generado diario por scripts/compute_attribution.py)
// ==============================================================
async function renderAttributionYTD() {
    const container = document.getElementById('dh-attribution-container');
    if (!container) return;

    let d;
    try {
        const r = await fetch('data/attribution_ytd.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        d = await r.json();
    } catch (e) {
        container.innerHTML = '<div style="padding:20px;color:#FFA726;">Atribución YTD no disponible. Corré: <code>python scripts/compute_attribution.py</code></div>';
        return;
    }

    // Helpers de formato
    const fmtPct = (v, dec = 2) => {
        if (v == null) return '—';
        const sign = v >= 0 ? '+' : '';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<span style="color:${color};font-weight:600;">${sign}${v.toFixed(dec)}%</span>`;
    };
    const fmtPp = (v, dec = 3) => {
        if (v == null) return '—';
        const sign = v >= 0 ? '+' : '';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        return `<strong style="color:${color};">${sign}${v.toFixed(dec)}pp</strong>`;
    };
    const fmtMoney = (v) => '$' + (v / 1e6).toFixed(2) + 'M';

    // Semáforo del residuo
    const absRes = Math.abs(d.residual_pp || 0);
    let resBadge, resColor;
    if (absRes <= 0.20) { resBadge = '🟢 OK'; resColor = '#81C784'; }
    else if (absRes <= 0.50) { resBadge = '🟡 ACEPTABLE'; resColor = '#FFA726'; }
    else { resBadge = '🔴 INVESTIGAR'; resColor = '#EF5350'; }

    // Tabla principal — sleeves
    const sleeveRows = d.sleeves.map(s => `
        <tr>
            <td class="left"><strong>${s.name}</strong></td>
            <td>${fmtMoney(s.value_usd)}</td>
            <td>${s.weight_pct.toFixed(2)}%</td>
            <td>${fmtPct(s.ytd_pct)}</td>
            <td>${fmtPp(s.contribution_pp)}</td>
        </tr>
    `).join('');

    // Footer — reconciliacion
    const summary = `
        <tr style="border-top:2px solid #D4AF37;">
            <td class="left" colspan="4"><strong>GROSS reconstruido</strong> (suma contribuciones)</td>
            <td>${fmtPp(d.gross_reconstructed_pct, 3)}</td>
        </tr>
        <tr>
            <td class="left" colspan="4" style="color:#90CAF9;">− Mgmt fee Lynk ${d.mgmt_fee_rate_annual_pct}% × ${d.days_ytd}/365</td>
            <td>${fmtPp(d.mgmt_fee_pp, 3)}</td>
        </tr>
        <tr style="background:rgba(212,175,55,0.08);">
            <td class="left" colspan="4"><strong>NET reconstruido</strong> (= gross − fee)</td>
            <td>${fmtPp(d.net_reconstructed_pct, 3)}</td>
        </tr>
        <tr style="background:rgba(100,181,246,0.08);">
            <td class="left" colspan="4"><strong>LYNK YTD oficial</strong> (estructurador)</td>
            <td>${fmtPp(d.lynk_ytd_pct, 3)}</td>
        </tr>
        <tr style="border-top:1px solid ${resColor};">
            <td class="left" colspan="4"><strong>RESIDUO</strong> (= NET − Lynk) <span style="color:${resColor};font-weight:700;">${resBadge}</span></td>
            <td><strong style="color:${resColor};font-size:14px;">${(d.residual_pp >= 0 ? '+' : '') + d.residual_pp.toFixed(3)}pp</strong></td>
        </tr>
    `;

    // Alts detail (collapsible)
    const altsRows = (d.alts_detail || []).map(h => `
        <tr>
            <td class="left">${h.ticker}</td>
            <td>${fmtMoney(h.value_usd)}</td>
            <td>${h.weight_pct.toFixed(2)}%</td>
            <td>${fmtPct(h.ytd_pct)}</td>
            <td>${fmtPp(h.contribution_pp, 3)}</td>
            <td class="left" style="font-size:11px;color:#90CAF9;">${h.valuation_date || ''} · ${(h.source || '').substring(0,40)}</td>
        </tr>
    `).join('');

    container.innerHTML = `
        <table class="data-table perf-table" style="margin-top:8px;">
            <thead>
                <tr>
                    <th class="left">Sleeve</th>
                    <th>MV</th>
                    <th>Weight</th>
                    <th>YTD return</th>
                    <th>Contribución</th>
                </tr>
            </thead>
            <tbody>${sleeveRows}${summary}</tbody>
        </table>
        <details style="margin-top:14px;">
            <summary style="color:#D4AF37;cursor:pointer;font-weight:600;">📊 Detalle Alts holding-level (qué tiró el Alts YTD)</summary>
            <table class="data-table" style="margin-top:8px;">
                <thead>
                    <tr>
                        <th class="left">Ticker</th>
                        <th>MV</th>
                        <th>Weight (Alts)</th>
                        <th>YTD return</th>
                        <th>Contrib (a sleeve)</th>
                        <th class="left">Fuente / Val date</th>
                    </tr>
                </thead>
                <tbody>${altsRows}</tbody>
            </table>
        </details>
        <div style="margin-top:10px;font-size:11px;color:#6B88A8;">
            Computado: ${d.refreshedAt.substring(0,16).replace('T',' ')} · YTD anchor ${d.ytd_anchor} (${d.days_ytd} días) · AUM ${fmtMoney(d.total_aum)}
            <br>Lynk last refresh: ${(d.lynk_refreshed_at || '').substring(0,16).replace('T',' ')}
        </div>
    `;
}


// ============================================================================
// renderHoldingsRace — funcion unificada para Equity/FI/Alts "Carrera por Holding"
// ============================================================================
// Usa la nueva metodologia cost basis ponderado (matchea Pershing).
// Lee de holdings_returns_{sleeve}.json (generado por compute_holdings_returns.py).
// Renderea: OPEN holdings (Return + Bench DW + Alpha REAL) + CLOSED (Realized G/L).
//
// Decided 2026-06-17 con Lucas: migrar de price race (first_buy) a cost basis
// porque con DCA cada 1-3 meses el first_buy pierde relevancia rapido.
// ============================================================================
async function renderHoldingsRace(sleeveKey, tbodyId, sourceElId) {
    const noCache = '?_=' + Date.now();
    const sleeveFiles = {
        'equity': 'data/holdings_returns_equity.json',
        'fi':     'data/holdings_returns_fixed_income.json',
        'alts':   'data/holdings_returns_alternatives.json',
    };
    const benchLabel = sleeveKey === 'fi' ? 'AGG DW' : 'ACWI DW';
    const tbody = document.getElementById(tbodyId);
    const sourceEl = sourceElId ? document.getElementById(sourceElId) : null;
    if (!tbody) return;

    let data;
    try {
        const r = await fetch(sleeveFiles[sleeveKey] + noCache);
        if (!r.ok) throw new Error('not available');
        data = await r.json();
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" style="padding:20px;text-align:center;color:#FFA726;">
            Cost basis returns no disponibles. Run: <code>python scripts/compute_holdings_returns.py</code></td></tr>`;
        return;
    }

    const fmtPct = (v, decimals=2) => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const c = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${c};">${sign}${v.toFixed(decimals)}%</span>`;
    };
    const fmtPp = (v, decimals=2) => {
        if (v == null) return '<span style="color:#6B88A8;">—</span>';
        const c = v >= 0 ? '#81C784' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<strong style="color:${c};">${sign}${v.toFixed(decimals)}pp</strong>`;
    };
    const fmtMv = (v) => v == null ? '—' : '$' + Math.round(v).toLocaleString('en-US');
    const fmtPeriod = (start, end) => {
        if (!start) return '—';
        const fmt = d => d ? d.slice(0, 7) : '';
        return `${fmt(start)} → ${fmt(end)}`;
    };

    const open = (data.holdings || []).filter(h => h.status === 'OPEN');
    const closed = (data.holdings || []).filter(h => h.status === 'CLOSED');

    let rows = '';

    // OPEN rows
    open.forEach(h => {
        const isLoser = h.alpha_real_pp != null && h.alpha_real_pp < 0;
        const statusBadge = isLoser
            ? '<span style="color:#EF5350;font-weight:700;">🔴 UNDERPERFORM</span>'
            : '<span style="color:#81C784;font-weight:700;">🏆 OUTPERFORM</span>';
        rows += `
            <tr>
                <td class="left"><strong>${h.ticker}</strong><br><span style="font-size:10px;color:#6B88A8;">${h.name || ''}</span></td>
                <td class="left" style="font-size:11px;color:#90CAF9;">${fmtPeriod(h.first_buy_date, h.period_end)}</td>
                <td>${fmtMv(h.mv_usd)}</td>
                <td>${fmtPct(h.ytd_pct)}</td>
                <td>${fmtPct(h.bench_ytd_pct)}</td>
                <td>${fmtPp(h.alpha_ytd_pp)}</td>
                <td>${fmtPct(h.return_pct)}</td>
                <td>${fmtPct(h.bench_dw_pct)}</td>
                <td>${fmtPp(h.alpha_real_pp)}</td>
                <td class="left">${statusBadge}</td>
            </tr>
        `;
    });

    // Separator + CLOSED rows
    if (closed.length) {
        rows += `
            <tr style="background:#1F3864;">
                <td colspan="10" class="left" style="padding:10px;font-weight:700;color:#FFA726;font-size:12px;">
                    🔒 HOLDINGS CERRADOS (Realized G/L de Pershing RGL)
                </td>
            </tr>
        `;
        closed.forEach(h => {
            const isWinner = h.realized_gl_pct != null && h.realized_gl_pct >= 0;
            const statusBadge = isWinner
                ? '<span style="color:#A5D6A7;font-weight:700;">✅ CLOSED (+)</span>'
                : '<span style="color:#FFAB91;font-weight:700;">⛔ CLOSED (-)</span>';
            rows += `
                <tr style="opacity:0.85;">
                    <td class="left"><strong>${h.ticker}</strong><br><span style="font-size:10px;color:#6B88A8;">${h.name || ''}</span></td>
                    <td class="left" style="font-size:11px;color:#90CAF9;">${fmtPeriod(h.first_buy_date, h.last_sell_date)}</td>
                    <td colspan="4" class="left" style="font-size:11px;color:#6B88A8;">Realized G/L:</td>
                    <td>${fmtPct(h.realized_gl_pct)}</td>
                    <td>—</td>
                    <td>—</td>
                    <td class="left">${statusBadge}</td>
                </tr>
            `;
        });
    }

    tbody.innerHTML = rows || '<tr><td colspan="10" style="padding:20px;text-align:center;color:#6B88A8;">Sin holdings.</td></tr>';

    if (sourceEl) {
        const ts = (data.refreshedAt || '').slice(0, 16).replace('T', ' ');
        sourceEl.innerHTML = `Source: <strong>Cost basis Pershing UGL + Bench Dollar-Weighted</strong> · Refreshed: ${ts} · OPEN: ${data.n_open} · CLOSED: ${data.n_closed}`;
    }
}

// Wire renderers — se llaman cuando se entra al tab respectivo
async function renderEquityRaceHoldingsCB() {
    await renderHoldingsRace('equity', 'er-real-body', 'er-real-source');
}
async function renderFIRaceHoldingsCB() {
    await renderHoldingsRace('fi', 'fr-real-body', 'fr-real-source');
}
async function renderAltsRaceHoldingsCB() {
    await renderHoldingsRace('alts', 'ar-real-body', 'ar-real-source');
}

// Auto-trigger en load
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => {
        renderEquityRaceHoldingsCB();
        renderFIRaceHoldingsCB();
        renderAltsRaceHoldingsCB();
    }, 500);
});
