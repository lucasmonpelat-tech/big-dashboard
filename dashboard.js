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
    document.getElementById('kpi-ytd-sub').textContent = 'see perf table below';
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
    renderSIPerformance();
}

// ==============================================================
// SINCE-INCEPTION PERFORMANCE TABLE (Overview tab)
// ==============================================================
async function renderSIPerformance() {
    const L = window.LYNK_DATA;
    let bmk = null;
    try {
        const r = await fetch('data/bmk_6040.json');
        if (r.ok) bmk = await r.json();
    } catch(e) { console.warn("bmk_6040.json not found", e); }

    const tbody = document.getElementById('si-perf-body');
    if (!tbody) return;

    const fmt = v => {
        if (v === null || v === undefined) return '<span style="color:#6B88A8;">—</span>';
        if (v >= 0) return `<span style="color:#81C784;">+${v.toFixed(2)}%</span>`;
        return `<span style="color:#EF5350;">${v.toFixed(2)}%</span>`;
    };

    // BIG values (Lynk — limited periods)
    const bigYTD = L.returnYTD;
    const bigSI = L.returnSI;
    const bigAnn = L.returnAnnualized;
    const bigVol = L.volatility;
    const bigSharpe = L.sharpe;

    // Benchmark values (from bmk_6040.json, calculated)
    const bmk_1w   = bmk ? bmk.periods.returns["1W"]   : null;
    const bmk_1m   = bmk ? bmk.periods.returns["1M"]   : null;
    const bmk_3m   = bmk ? bmk.periods.returns["3M"]   : null;
    const bmk_6m   = bmk ? bmk.periods.returns["6M"]   : null;
    const bmk_ytd  = bmk ? bmk.periods.returns["YTD"]  : null;
    const bmk_si   = bmk ? bmk.periods.returns["SI"]   : null;
    const bmk_ann  = bmk ? bmk.periods.returns["Annualized"] : null;
    const bmk_vol  = bmk ? bmk.periods.volatility      : null;
    const bmk_shrp = bmk ? bmk.periods.sharpe_approx   : null;

    const alpha = (a, b) => (a != null && b != null) ? a - b : null;

    tbody.innerHTML = `
        <tr class="row-big">
            <td class="left"><strong>BIG Fund (Lynk)</strong></td>
            <td>${fmt(null)}</td>
            <td>${fmt(null)}</td>
            <td>${fmt(null)}</td>
            <td>${fmt(null)}</td>
            <td>${fmt(bigYTD)}</td>
            <td>${fmt(bigSI)}</td>
            <td>${fmt(bigAnn)}</td>
            <td>${bigVol.toFixed(2)}%</td>
            <td>${bigSharpe.toFixed(2)}</td>
        </tr>
        <tr class="row-bmk">
            <td class="left">60/40 (ACWI/AGG Yahoo)</td>
            <td>${fmt(bmk_1w)}</td>
            <td>${fmt(bmk_1m)}</td>
            <td>${fmt(bmk_3m)}</td>
            <td>${fmt(bmk_6m)}</td>
            <td>${fmt(bmk_ytd)}</td>
            <td>${fmt(bmk_si)}</td>
            <td>${fmt(bmk_ann)}</td>
            <td>${bmk_vol ? bmk_vol.toFixed(2) + '%' : '—'}</td>
            <td>${bmk_shrp != null ? bmk_shrp.toFixed(2) : '—'}</td>
        </tr>
        <tr class="row-alpha">
            <td class="left"><strong>Alpha (BIG − BMK)</strong></td>
            <td>${fmt(null)}</td>
            <td>${fmt(null)}</td>
            <td>${fmt(null)}</td>
            <td>${fmt(null)}</td>
            <td>${fmt(alpha(bigYTD, bmk_ytd))}</td>
            <td>${fmt(alpha(bigSI, bmk_si))}</td>
            <td>${fmt(alpha(bigAnn, bmk_ann))}</td>
            <td>${bmk_vol ? (bigVol - bmk_vol).toFixed(2) + 'pp' : '—'}</td>
            <td>${bmk_shrp != null ? (bigSharpe - bmk_shrp).toFixed(2) : '—'}</td>
        </tr>
    `;
}

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
function renderPositions(livePrices) {
    const tbody = document.getElementById('positions-body');
    tbody.innerHTML = '';
    const sleeveOrder = ["Equity", "Alternatives", "Fixed Income", "Cash"];
    const sleeveClass = { Equity: "equity", Alternatives: "alts", "Fixed Income": "fi", Cash: "cash" };
    const { totals, total } = computeSleeveTotals(BIG_POSITIONS);

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
            const nav = getNAV(p, livePrices);
            let navTag;
            if (p.status === 'IN_TRANSIT') {
                navTag = '<span class="tag" style="background:#FFA726;color:#0D1B2A;">IN TRANSIT</span>';
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

    // Plotly donut chart
    const data = [{
        type: 'pie',
        labels: sorted.map(([c]) => c),
        values: sorted.map(([_, v]) => v),
        hole: 0.5,
        textposition: 'outside',
        textinfo: 'label+percent',
        marker: {
            colors: sorted.map(([c]) => CUR_COLORS[c] || '#666'),
            line: { color: '#0D1B2A', width: 1.5 }
        },
        hovertemplate: '<b>%{label}</b><br>%{value:.2f}%<extra></extra>'
    }];
    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#E0E8F0', family: 'Segoe UI, Arial, sans-serif', size: 12 },
        margin: { t: 20, r: 20, b: 20, l: 20 },
        showlegend: false
    };
    Plotly.newPlot('currency-chart', data, layout, { displayModeBar: false, responsive: true });

    // Bar rows
    const bars = document.getElementById('currency-bars');
    bars.innerHTML = sorted.map(([c, v]) => `
        <div class="bar-row">
            <div class="bar-label" style="color:${CUR_COLORS[c] || '#888'};">${c}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${((v / tsum) * 100).toFixed(1)}%; background:${CUR_COLORS[c] || '#888'};"></div></div>
            <div class="bar-value">${((v / tsum) * 100).toFixed(2)}%</div>
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
    const top10 = sorted.slice(0, 10);
    const rest = sorted.slice(10);
    const restTotal = rest.reduce((a, [_, v]) => a + v, 0);
    const chartLabels = top10.map(([c]) => c).concat(restTotal > 0 ? ['OTHER'] : []);
    const chartValues = top10.map(([_, v]) => v).concat(restTotal > 0 ? [restTotal] : []);

    const data = [{
        type: 'pie',
        labels: chartLabels,
        values: chartValues,
        hole: 0.5,
        textposition: 'outside',
        textinfo: 'label+percent',
        marker: {
            colors: chartLabels.map(c => COUNTRY_COLORS[c] || '#666'),
            line: { color: '#0D1B2A', width: 1.5 }
        },
        hovertemplate: '<b>%{label}</b><br>%{value:.2f}%<extra></extra>'
    }];
    const layout = {
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: { color: '#E0E8F0', family: 'Segoe UI, Arial, sans-serif', size: 12 },
        margin: { t: 20, r: 20, b: 20, l: 20 },
        showlegend: false
    };
    Plotly.newPlot('country-chart', data, layout, { displayModeBar: false, responsive: true });

    const bars = document.getElementById('country-bars');
    bars.innerHTML = sorted.slice(0, 15).map(([c, v]) => `
        <div class="bar-row">
            <div class="bar-label" style="color:${COUNTRY_COLORS[c] || '#888'};">${c}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${((v / tsum) * 100).toFixed(1)}%; background:${COUNTRY_COLORS[c] || '#888'};"></div></div>
            <div class="bar-value">${((v / tsum) * 100).toFixed(2)}%</div>
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
// YTM / FIXED INCOME TAB
// ==============================================================
function renderYTM() {
    const fiPositions = BIG_POSITIONS.filter(p => p.sleeve === "Fixed Income");
    const totalRFpct = fiPositions.reduce((a, p) => a + p.pct, 0);
    let wtdYTM = 0, wtdDur = 0, wtdVenc = 0;
    fiPositions.forEach(p => {
        const m = FI_METRICS[p.isin];
        if (!m) return;
        const wt = p.pct / totalRFpct;
        wtdYTM += wt * m.ytw;
        wtdDur += wt * m.dur;
        wtdVenc += wt * m.venc;
    });

    document.getElementById('ytm-summary-grid').innerHTML = `
        <div class="summary-item" style="border-left-color:#81C784;">
            <div class="s-lbl">Weighted YTM</div>
            <div class="yield-total">${wtdYTM.toFixed(2)}%</div>
            <div class="s-sub">weighted avg across FI funds</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">Weighted Duration</div>
            <div class="s-val" style="color:#64B5F6;">${wtdDur.toFixed(2)} yrs</div>
            <div class="s-sub">interest rate sensitivity</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">Weighted Maturity</div>
            <div class="s-val" style="color:#64B5F6;">${wtdVenc.toFixed(2)} yrs</div>
            <div class="s-sub">average time to maturity</div>
        </div>
        <div class="summary-item">
            <div class="s-lbl">FI Sleeve Weight</div>
            <div class="s-val" style="color:#D4AF37;">${totalRFpct.toFixed(2)}%</div>
            <div class="s-sub">of total BIG</div>
        </div>
    `;

    let html = '';
    fiPositions.forEach(p => {
        const m = FI_METRICS[p.isin];
        if (!m) return;
        const wt = p.pct / totalRFpct;
        const contrib = (wt * m.ytw).toFixed(3);
        html += `
            <tr class="sleeve-fi">
                <td class="left"><strong>${p.name}</strong><span class="note">${p.isin}</span></td>
                <td>${formatPct(p.pct)}</td>
                <td>${formatPct(wt * 100)}</td>
                <td><strong style="color:#81C784;">${m.ytw.toFixed(2)}%</strong></td>
                <td>${m.dur.toFixed(2)}</td>
                <td>${m.venc.toFixed(2)}</td>
                <td><span class="sleeve-badge fi">${m.rating}</span></td>
                <td>${contrib}%</td>
            </tr>
        `;
    });
    html += `
        <tr class="total-row">
            <td class="left"><strong>TOTAL FI PONDERADO</strong></td>
            <td>${totalRFpct.toFixed(2)}%</td>
            <td>100.00%</td>
            <td><strong>${wtdYTM.toFixed(2)}%</strong></td>
            <td>${wtdDur.toFixed(2)}</td>
            <td>${wtdVenc.toFixed(2)}</td>
            <td>—</td>
            <td>${wtdYTM.toFixed(3)}%</td>
        </tr>
    `;
    document.getElementById('ytm-tbody').innerHTML = html;
}

// ==============================================================
// PERFORMANCE TAB
// ==============================================================
function renderPerformance() {
    const b = PORT_PERF_DETAIL.big;
    const k = PORT_PERF_DETAIL.bmk;
    const fmt = v => v >= 0 ? `<span style="color:#81C784;">+${v.toFixed(2)}%</span>` : `<span style="color:#EF5350;">${v.toFixed(2)}%</span>`;

    document.getElementById('perf-returns-body').innerHTML = `
        <tr class="row-big">
            <td class="left"><strong>BIG Fund</strong></td>
            <td>${fmt(b.m1)}</td>
            <td>${fmt(b.m3)}</td>
            <td>${fmt(b.m6)}</td>
            <td>${fmt(b.ytd)}</td>
            <td>${fmt(b.y1)}</td>
            <td>${fmt(b.y3)}</td>
            <td>${fmt(b.y5)}</td>
        </tr>
        <tr class="row-bmk">
            <td class="left">Benchmark 60/40 (ACWI/AGG)</td>
            <td>${fmt(k.m1)}</td>
            <td>${fmt(k.m3)}</td>
            <td>${fmt(k.m6)}</td>
            <td>${fmt(k.ytd)}</td>
            <td>${fmt(k.y1)}</td>
            <td>${fmt(k.y3)}</td>
            <td>${fmt(k.y5)}</td>
        </tr>
        <tr class="row-alpha">
            <td class="left"><strong>Alpha</strong></td>
            <td>${fmt(b.m1 - k.m1)}</td>
            <td>${fmt(b.m3 - k.m3)}</td>
            <td>${fmt(b.m6 - k.m6)}</td>
            <td>${fmt(b.ytd - k.ytd)}</td>
            <td>${fmt(b.y1 - k.y1)}</td>
            <td>${fmt(b.y3 - k.y3)}</td>
            <td>${fmt(b.y5 - k.y5)}</td>
        </tr>
    `;

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
// EQUITY RACE TAB — Uses REAL TWR data from Pershing transaction history
// ==============================================================
async function renderEquityRace() {
    let realData;
    let data;
    const noCache = '?_=' + Date.now();  // prevent stale JSON
    try {
        const r = await fetch('data/equity_race.json' + noCache);
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('equity_race.json not available', e);
        document.getElementById('er-chart').innerHTML =
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
    if (realData && realData.twr_series && realData.twr_series.length > 0) {
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
    // Compute real multi-period returns from TWR series
    let realPeriods = null;
    if (realData && realData.twr_series && realData.acwi_index_series) {
        const s = realData.twr_series;
        const a = realData.acwi_index_series;
        const n = s.length;
        const getIdx = offset => n - 1 - offset >= 0 ? n - 1 - offset : null;
        const latest_s = s[n-1].index;
        const latest_a = a[n-1].index;
        const period = (back) => {
            const i = getIdx(back);
            if (i === null) return {sleeve: null, acwi: null, alpha: null};
            const ss = (latest_s / s[i].index - 1) * 100;
            const aa = (latest_a / a[i].index - 1) * 100;
            return {sleeve: Math.round(ss*100)/100, acwi: Math.round(aa*100)/100, alpha: Math.round((ss-aa)*100)/100};
        };
        // Find YTD (first month of current year)
        const latestDate = new Date(s[n-1].date);
        const ytdIdx = s.findIndex(p => new Date(p.date).getFullYear() === latestDate.getFullYear()) - 1;
        const ytd = ytdIdx >= 0 ? {
            sleeve: Math.round((latest_s / s[ytdIdx].index - 1) * 10000) / 100,
            acwi: Math.round((latest_a / a[ytdIdx].index - 1) * 10000) / 100,
        } : {sleeve: null, acwi: null};
        ytd.alpha = (ytd.sleeve !== null && ytd.acwi !== null) ? Math.round((ytd.sleeve - ytd.acwi)*100)/100 : null;
        // Since inception
        const si = {sleeve: Math.round((latest_s - 100)*100)/100, acwi: Math.round((latest_a - 100)*100)/100};
        si.alpha = Math.round((si.sleeve - si.acwi)*100)/100;
        // Annualized
        const months = n - 1;
        const ann_s = months > 0 ? Math.round(((Math.pow(latest_s/100, 12/months) - 1) * 10000))/100 : null;
        const ann_a = months > 0 ? Math.round(((Math.pow(latest_a/100, 12/months) - 1) * 10000))/100 : null;
        const ann_alpha = (ann_s !== null && ann_a !== null) ? Math.round((ann_s - ann_a)*100)/100 : null;

        realPeriods = {
            '1M': period(1), '3M': period(3), '6M': period(6),
            'YTD': ytd, 'SI': si,
            'ANN': {sleeve: ann_s, acwi: ann_a, alpha: ann_alpha}
        };
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

    // Race chart — use REAL TWR series if available
    let traces;
    if (realData && realData.twr_series) {
        const r_s = realData.twr_series;
        const r_a = realData.acwi_index_series;
        traces = [
            {
                x: r_s.map(p => p.date),
                y: r_s.map(p => p.index),
                name: 'BIG Equity Sleeve (TWR real)',
                type: 'scatter', mode: 'lines+markers',
                line: { color: '#D4AF37', width: 3 },
                marker: { size: 7, color: '#D4AF37' },
                hovertemplate: '%{x|%b %Y}<br>Sleeve: <b>%{y:.2f}</b><extra></extra>'
            },
            {
                x: r_a.map(p => p.date),
                y: r_a.map(p => p.index),
                name: 'MSCI ACWI',
                type: 'scatter', mode: 'lines+markers',
                line: { color: '#64B5F6', width: 2.5, dash: 'dot' },
                marker: { size: 6, color: '#64B5F6' },
                hovertemplate: '%{x|%b %Y}<br>ACWI: <b>%{y:.2f}</b><extra></extra>'
            }
        ];
    } else {
        const sleeveKeys = Object.keys(data.sleeve_index).sort();
        const acwiKeys = Object.keys(data.acwi_index).sort();
        traces = [
            {
                x: sleeveKeys.map(k => k + '-15'),
                y: sleeveKeys.map(k => data.sleeve_index[k]),
                name: 'BIG Equity Sleeve (backtest)',
                type: 'scatter', mode: 'lines+markers',
                line: { color: '#D4AF37', width: 3 },
                marker: { size: 6, color: '#D4AF37' },
            },
            {
                x: acwiKeys.map(k => k + '-15'),
                y: acwiKeys.map(k => data.acwi_index[k]),
                name: 'MSCI ACWI',
                type: 'scatter', mode: 'lines+markers',
                line: { color: '#64B5F6', width: 2.5, dash: 'dot' },
                marker: { size: 5, color: '#64B5F6' },
            }
        ];
    }
    const layout = {
        paper_bgcolor: '#1A2A3D',
        plot_bgcolor: '#12243A',
        font: { color: '#90CAF9', family: 'Segoe UI, Arial', size: 11 },
        margin: { t: 30, r: 24, b: 48, l: 60 },
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 13, color: '#ECEFF1' } },
        xaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, type: 'date' },
        yaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, title: { text: 'Base 100 (Inception 31-Jul-2025)', font: { size: 11 } } },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#1F3864', bordercolor: '#2E74B5', font: { color: '#FFF' } }
    };
    Plotly.newPlot('er-chart', traces, layout, { responsive: true, displaylogo: false });

    // Holdings table sorted by SI contribution
    const sorted = [...holdings].sort((a, b) => (b.contribution_pct || -999) - (a.contribution_pct || -999));
    const acwi_ref = siRet.acwi || 0;
    const fmtPct = (v, withSign = true) => {
        if (v == null) return '—';
        const color = v >= 0 ? '#81C784' : '#EF5350';
        const sign = withSign && v >= 0 ? '+' : '';
        return `<span style="color:${color};font-weight:700;">${sign}${v.toFixed(2)}%</span>`;
    };
    const fmtContrib = v => {
        if (v == null) return '—';
        const color = v >= 0 ? '#D4AF37' : '#EF5350';
        const sign = v >= 0 ? '+' : '';
        return `<span style="color:${color};font-weight:700;">${sign}${v.toFixed(2)}pp</span>`;
    };
    const holdingsRows = sorted.map(h => {
        const rel = h.si_return_pct != null ? h.si_return_pct - acwi_ref : null;
        const winStatus = rel == null ? '—' : rel >= 3 ? '<span style="color:#81C784;font-weight:700;">🏆 Winner</span>' : rel >= 0 ? '<span style="color:#81C784;">✅ OK</span>' : rel >= -5 ? '<span style="color:#FFA726;">⚠️ Lagging</span>' : '<span style="color:#EF5350;font-weight:700;">🔴 Loser</span>';
        const relColor = rel == null ? '#6B88A8' : rel >= 0 ? '#81C784' : '#EF5350';
        const relTxt = rel == null ? '—' : (rel >= 0 ? '+' : '') + rel.toFixed(2) + 'pp';
        return `<tr>
            <td class="left"><strong>${h.name}</strong></td>
            <td class="left" style="font-size:10px;color:#90CAF9;">${h.source}</td>
            <td>$${(h.value_usd/1000).toFixed(0)}K</td>
            <td>${h.weight_pct.toFixed(1)}%</td>
            <td>${fmtPct(h.ytd_return_pct)}</td>
            <td>${fmtPct(h.si_return_pct)}</td>
            <td style="color:${relColor};font-weight:700;">${relTxt}</td>
            <td>${fmtContrib(h.ytd_contribution_pct)}</td>
            <td>${fmtContrib(h.contribution_pct)}</td>
            <td class="left">${winStatus}</td>
        </tr>`;
    }).join('');

    // Benchmark reference row (ACWI) — appended at bottom
    const acwiYtd = returns.YTD?.acwi;
    const acwiSi = returns.SI?.acwi;
    const acwiRow = `<tr style="background:#12243A;border-top:2px solid #64B5F6;">
        <td class="left"><strong style="color:#64B5F6;">MSCI ACWI <span style="font-size:10px;opacity:0.8;">(Benchmark)</span></strong></td>
        <td class="left" style="font-size:10px;color:#90CAF9;">Yahoo:ACWI</td>
        <td style="color:#6B88A8;">—</td>
        <td style="color:#6B88A8;">—</td>
        <td>${fmtPct(acwiYtd)}</td>
        <td>${fmtPct(acwiSi)}</td>
        <td style="color:#6B88A8;">0.00pp</td>
        <td style="color:#6B88A8;">—</td>
        <td style="color:#6B88A8;">—</td>
        <td class="left"><span style="color:#64B5F6;font-weight:700;">🎯 Benchmark</span></td>
    </tr>`;

    document.getElementById('er-holdings-body').innerHTML = holdingsRows + acwiRow;

    // ============================================================
    // REAL TWR HOLDING CONTRIBUTIONS (from Pershing transactions)
    // ============================================================
    if (realContribs && realContribs.holdings && realContribs.holdings.length) {
        const statusColor = {
            winner:  '#81C784',
            lagging: '#FFA726',
            loser:   '#EF5350',
            closed:  '#90A4AE',
        };
        const statusBadge = {
            winner:  '🏆 Winner',
            lagging: '⚠️ Lagging',
            loser:   '🔴 Loser',
            closed:  '⚰️ Closed',
        };
        const fmtSigned = (v, suffix='%') => {
            if (v == null) return '—';
            const c = v >= 0 ? '#81C784' : '#EF5350';
            const sign = v >= 0 ? '+' : '';
            return `<span style="color:${c};">${sign}${v.toFixed(2)}${suffix}</span>`;
        };
        const fmtContrib = v => {
            if (v == null) return '—';
            const c = v >= 0 ? '#81C784' : '#EF5350';
            const sign = v >= 0 ? '+' : '';
            return `<strong style="color:${c};">${sign}${v.toFixed(2)}pp</strong>`;
        };
        document.getElementById('er-real-source').innerHTML =
            `Source: <strong>${realContribs.source}</strong> · Period: ${realContribs.period_start} → ${realContribs.period_end} · ` +
            `Total contribution: <strong>${(realContribs.total_contribution_pp >= 0 ? '+' : '')}${realContribs.total_contribution_pp.toFixed(2)}pp</strong>`;
        const realRows = realContribs.holdings.map(h => `
            <tr>
                <td class="left"><strong>${h.name}</strong><br><span style="font-size:10px;color:#6B88A8;">${h.ticker}</span></td>
                <td class="left" style="font-size:11px;color:#90CAF9;">${h.period_start.slice(0,7)} → ${h.period_end.slice(0,7)}</td>
                <td>${h.months_held}</td>
                <td>${h.avg_weight_pct.toFixed(2)}%</td>
                <td>${fmtSigned(h.twr_pct)}</td>
                <td>${fmtContrib(h.contribution_pp)}</td>
                <td class="left"><span style="color:${statusColor[h.status]};font-weight:700;">${statusBadge[h.status]}</span></td>
            </tr>
        `).join('');
        const totalRow = `<tr style="border-top:2px solid #1F3864;">
            <td class="left" colspan="5"><strong>TOTAL Sleeve TWR</strong></td>
            <td>${fmtContrib(realContribs.total_contribution_pp)}</td>
            <td></td>
        </tr>`;
        document.getElementById('er-real-body').innerHTML = realRows + totalRow;
    } else {
        document.getElementById('er-real-body').innerHTML =
            '<tr><td colspan="7" style="padding:20px;text-align:center;color:#FFA726;">Real TWR contributions not available. Run: <code>python scripts/holding_contributions_real.py --sleeve equity</code></td></tr>';
    }

    // Trade Ideas generation
    const winners = sorted.filter(h => (h.si_return_pct || 0) - acwi_ref >= 3);
    const losers = sorted.filter(h => (h.si_return_pct || 0) - acwi_ref <= -5);
    const neutral = sorted.filter(h => {
        const diff = (h.si_return_pct || 0) - acwi_ref;
        return diff > -5 && diff < 3;
    });

    const ideasHTML = `
        <div class="summary-box" style="border-left: 4px solid #EF5350;">
            <h3>🔴 LAGGARDS — candidatos a rotar</h3>
            ${losers.length === 0 ? '<p style="color:#81C784;">No hay laggards significativos hoy. Equity sleeve bien balanceado.</p>' : losers.map(h => `
                <div class="alloc-row" style="padding: 10px 0;">
                    <div style="flex:1;">
                        <strong>${h.name}</strong>
                        <span style="font-size: 11px; color: #EF5350;"> · ${((h.si_return_pct || 0) - acwi_ref).toFixed(2)}pp vs ACWI</span>
                        <br><span style="font-size: 11px; color: #90CAF9;">Peso: ${h.weight_pct.toFixed(1)}% · Valor: $${(h.value_usd/1000).toFixed(0)}K · Return SI: ${(h.si_return_pct >= 0 ? '+' : '') + h.si_return_pct.toFixed(2)}%</span>
                    </div>
                </div>
            `).join('')}
        </div>

        <div class="summary-box" style="border-left: 4px solid #81C784;">
            <h3>🏆 WINNERS — mantener o aumentar</h3>
            ${winners.length === 0 ? '<p style="color:#90CAF9;">Ningún holding superó ACWI por más de +3pp.</p>' : winners.map(h => `
                <div class="alloc-row" style="padding: 10px 0;">
                    <div style="flex:1;">
                        <strong>${h.name}</strong>
                        <span style="font-size: 11px; color: #81C784;"> · +${((h.si_return_pct || 0) - acwi_ref).toFixed(2)}pp vs ACWI</span>
                        <br><span style="font-size: 11px; color: #90CAF9;">Peso: ${h.weight_pct.toFixed(1)}% · Valor: $${(h.value_usd/1000).toFixed(0)}K · Return SI: ${(h.si_return_pct >= 0 ? '+' : '') + h.si_return_pct.toFixed(2)}%</span>
                    </div>
                </div>
            `).join('')}
        </div>

        <div class="summary-box" style="border-left: 4px solid #D4AF37;">
            <h3>💡 Mis recomendaciones de trade (pensadas)</h3>
            <div id="er-trade-recommendations"></div>
        </div>
    `;
    document.getElementById('er-trade-ideas').innerHTML = ideasHTML;

    // Generate specific trade recommendations based on REAL data
    const tradeRecs = [];
    const realGap = realPeriods ? realPeriods.SI.alpha : alpha_si;

    // Primera idea CRITICA: la realidad del gap
    if (realGap !== null && realGap < -3) {
        tradeRecs.push({
            action: '🚨 CONTEXTO',
            target: `Gap real vs ACWI: ${realGap.toFixed(2)}pp desde inception`,
            size: `Perdemos ${Math.abs(realGap).toFixed(2)}pp reales — NO es el backtest optimista`,
            rationale: `La historia real del sleeve tuvo arrastre de BRK (~$2.2M), Virtus US Small Cap y NB Real Estate (vendidos Feb), más una rotación tardía a LatAm (ILF/4BRZ entraron Feb, ~2 meses de contribución).`,
            impact: 'Para recuperar el gap necesitamos +5.72pp incremental sobre ACWI en los próximos meses. Trades abajo.',
            color: '#EF5350'
        });
    }

    if (losers.length > 0) {
        const worst = losers[losers.length - 1];
        tradeRecs.push({
            action: 'CERRAR / REDUCIR',
            target: worst.name,
            size: `$${(worst.value_usd/1000).toFixed(0)}K (${worst.weight_pct.toFixed(1)}% del sleeve)`,
            rationale: `Peor laggard: ${((worst.si_return_pct || 0) - acwi_ref).toFixed(2)}pp vs ACWI desde inception. No está agregando alpha.`,
            impact: `Alpha esperado si se reemplaza por ACWI directo: aprox +${(((acwi_ref - worst.si_return_pct) * worst.weight_pct)/100).toFixed(2)}pp al sleeve total`,
            color: '#EF5350'
        });
    }
    // Look for NB Megatrends specifically
    const nbgmt = holdings.find(h => h.ticker === 'NBGMT');
    if (nbgmt && (nbgmt.si_return_pct || 0) - acwi_ref < -3) {
        tradeRecs.push({
            action: 'RECORTAR',
            target: `${nbgmt.name}`,
            size: `de ${nbgmt.weight_pct.toFixed(1)}% → ~8% (liberar ~$${((nbgmt.weight_pct - 8) * 7890).toFixed(0)}K aprox)`,
            rationale: `Duplica exposure tech/growth con CSPX. Underperform vs ACWI ${((nbgmt.si_return_pct || 0) - acwi_ref).toFixed(2)}pp. TER 0.75% no justificado cuando CSPX va 0.07%.`,
            impact: 'Rotar a CSPX o Nomura Japan recovery-play.',
            color: '#FFA726'
        });
    }
    tradeRecs.push({
        action: 'AGREGAR',
        target: 'Nomura Japan Strategic Value',
        size: '$500K (1.9% BIG / 6.3% equity sleeve)',
        rationale: 'BIG tiene 0% Japan directo. ACWI tiene ~6% Japan. Gap estructural. Nomura flagship con Alpha 2.99 a 3Y, Beta 0.93.',
        impact: 'Cubre un underweight geográfico + trade asimétrico (BOJ normalización + TSE Reform). Funding: Janus cierre.',
        color: '#64B5F6'
    });

    // Winner that could justify top-up
    if (winners.length > 0) {
        const bestWinner = winners[0];
        if (bestWinner.weight_pct < 10) {
            tradeRecs.push({
                action: 'EVALUAR TOP-UP',
                target: bestWinner.name,
                size: `actual ${bestWinner.weight_pct.toFixed(1)}% del sleeve · considerar +2-3pp si tesis sigue`,
                rationale: `Winner claro: +${((bestWinner.si_return_pct || 0) - acwi_ref).toFixed(2)}pp vs ACWI SI. Tesis vigente (LatAm / EM / value).`,
                impact: `Con peso 8-10%, contribución podría escalar a +3-4pp del sleeve.`,
                color: '#81C784'
            });
        }
    }

    document.getElementById('er-trade-recommendations').innerHTML = tradeRecs.map((t, i) => `
        <div style="background: #12243A; border-left: 3px solid ${t.color}; padding: 12px 16px; margin-bottom: 12px; border-radius: 4px;">
            <div style="font-size: 11px; font-weight: 700; color: ${t.color}; letter-spacing: 1px;">IDEA ${i+1} — ${t.action}</div>
            <div style="font-size: 15px; font-weight: 700; color: #FFFFFF; margin: 4px 0;">${t.target}</div>
            <div style="font-size: 11px; color: #90CAF9;">${t.size}</div>
            <div style="font-size: 12px; color: #E0E8F0; margin-top: 6px; line-height: 1.5;"><strong>Razón:</strong> ${t.rationale}</div>
            <div style="font-size: 12px; color: #D4AF37; margin-top: 4px; line-height: 1.5;"><strong>Impacto esperado:</strong> ${t.impact}</div>
        </div>
    `).join('');
}

// ==============================================================
// FI RACE TAB
// ==============================================================
async function renderFIRace() {
    let data;
    try {
        const r = await fetch('data/fi_race.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('fi_race.json not available', e);
        document.getElementById('fr-chart').innerHTML =
            '<div style="padding:40px;text-align:center;color:#EF5350;">FI data not available. Run: <code>python scripts/fi_race.py</code></div>';
        return;
    }

    const stats = data.stats || {};
    const returns = stats.returns || {};
    const ann = stats.annualized || {};
    const holdings = data.holdings || [];
    const pm = data.portfolio_metrics || {};

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

    // Chart
    const sleeveKeys = Object.keys(data.sleeve_index).sort();
    const aggKeys = Object.keys(data.agg_index).sort();
    const traces = [
        {
            x: sleeveKeys.map(k => k + '-15'),
            y: sleeveKeys.map(k => data.sleeve_index[k]),
            name: 'BIG FI Sleeve',
            type: 'scatter', mode: 'lines+markers',
            line: { color: '#81C784', width: 3 },
            marker: { size: 6, color: '#81C784' },
            hovertemplate: '%{x|%b %Y}<br>Sleeve: <b>%{y:.2f}</b><extra></extra>'
        },
        {
            x: aggKeys.map(k => k + '-15'),
            y: aggKeys.map(k => data.agg_index[k]),
            name: 'AGG Benchmark',
            type: 'scatter', mode: 'lines+markers',
            line: { color: '#64B5F6', width: 2.5, dash: 'dot' },
            marker: { size: 5, color: '#64B5F6' },
            hovertemplate: '%{x|%b %Y}<br>AGG: <b>%{y:.2f}</b><extra></extra>'
        }
    ];
    const layout = {
        paper_bgcolor: '#1A2A3D',
        plot_bgcolor: '#12243A',
        font: { color: '#90CAF9', family: 'Segoe UI, Arial', size: 11 },
        margin: { t: 30, r: 24, b: 48, l: 60 },
        legend: { orientation: 'h', x: 0, y: 1.08, bgcolor: 'rgba(0,0,0,0)', font: { size: 13, color: '#ECEFF1' } },
        xaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, type: 'date' },
        yaxis: { gridcolor: '#1F3864', linecolor: '#2E74B5', tickfont: { size: 10 }, title: { text: 'Base 100', font: { size: 11 } } },
        hovermode: 'x unified',
        hoverlabel: { bgcolor: '#1F3864', bordercolor: '#2E74B5', font: { color: '#FFF' } }
    };
    Plotly.newPlot('fr-chart', traces, layout, { responsive: true, displaylogo: false });

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
        <td>${fmtPct(aggYtd)}</td>
        <td>${fmtPct(aggSi)}</td>
        <td style="color:#6B88A8;">—</td>
        <td style="color:#6B88A8;">—</td>
    </tr>`;
    document.getElementById('fr-holdings-body').innerHTML = holdingsRows + aggRow;

    // Trade Ideas
    const topSpread = sorted.filter(h => h.spread_vs_ust >= 5);
    const lowSpread = sorted.filter(h => h.spread_vs_ust < 3);
    const tradeRecs = [];

    // Context card
    tradeRecs.push({
        action: '✅ CONTEXTO',
        target: `FI Sleeve GANANDO +${siRet.alpha ? siRet.alpha.toFixed(2) : '—'}pp vs AGG SI`,
        size: `YTW ponderado ${pm.weighted_ytw}% vs UST 10Y ${pm.ust_10y_yield}% = spread +${pm.spread_vs_ust_10y}pp`,
        rationale: 'FI sleeve performando arriba del benchmark. Diseño de 38.6% Low Duration (defensivo) + 10.9% EM Local (high carry) + 5% Cat Bond (uncorrelated) funciona.',
        impact: 'La estrategia FI está generando alpha. Mantener composición o ajustar en los márgenes.',
        color: '#81C784'
    });

    if (topSpread.length > 0) {
        const best = topSpread[0];
        tradeRecs.push({
            action: '🏆 MANTENER/AUMENTAR',
            target: best.name,
            size: `Peso ${best.weight_pct.toFixed(1)}% · YTW ${best.ytw.toFixed(2)}% · Spread UST +${best.spread_vs_ust}pp`,
            rationale: `Mayor spread del sleeve (${best.spread_vs_ust}pp sobre UST 10Y). Aporta carry alto. SI return: ${best.si_return_pct >= 0 ? '+' : ''}${best.si_return_pct}%.`,
            impact: 'Si aumentamos peso de este holding: más carry, pero también más riesgo crediticio. Evaluar.',
            color: '#81C784'
        });
    }

    // Duration consideration
    if (pm.weighted_duration < 4) {
        tradeRecs.push({
            action: '⚖️ EVALUAR',
            target: 'Aumentar Duration (actualmente ' + pm.weighted_duration.toFixed(2) + 'y)',
            size: 'Duration corta expone menos a tasas bajando. Si Fed corta, vamos a capturar menos upside.',
            rationale: 'PIMCO LD (dur 2.54) es 38.6% del sleeve. Si expectativa es Fed cutting cycle, vale considerar rotar parte a PIMCO Income (dur 5.15) o Man GLG (dur 4.89).',
            impact: 'Duration 4.5-5y capturaría mejor un rally de bonos si hay recortes de tasas.',
            color: '#FFA726'
        });
    }

    // EM allocation
    const em = sorted.find(h => h.ticker === 'PIMCO-EM');
    if (em && em.si_return_pct > 8) {
        tradeRecs.push({
            action: '🔍 MONITOREAR',
            target: em.name,
            size: `Peso actual ${em.weight_pct.toFixed(1)}%, SI return +${em.si_return_pct}%, YTW ${em.ytw}%`,
            rationale: 'EM Local Bond fue el winner absoluto con +10.51% SI. El carry de 8.22% es el más alto. Riesgo: USD fortalecimiento o EM sell-off.',
            impact: 'Mantener peso actual. Si USD se debilita o Fed dovish, considerar top-up.',
            color: '#64B5F6'
        });
    }

    document.getElementById('fr-trade-ideas').innerHTML = tradeRecs.map((t, i) => `
        <div style="background: #12243A; border-left: 3px solid ${t.color}; padding: 12px 16px; margin-bottom: 12px; border-radius: 4px;">
            <div style="font-size: 11px; font-weight: 700; color: ${t.color}; letter-spacing: 1px;">IDEA ${i+1} — ${t.action}</div>
            <div style="font-size: 15px; font-weight: 700; color: #FFFFFF; margin: 4px 0;">${t.target}</div>
            <div style="font-size: 11px; color: #90CAF9;">${t.size}</div>
            <div style="font-size: 12px; color: #E0E8F0; margin-top: 6px; line-height: 1.5;"><strong>Razón:</strong> ${t.rationale}</div>
            <div style="font-size: 12px; color: #D4AF37; margin-top: 4px; line-height: 1.5;"><strong>Impacto esperado:</strong> ${t.impact}</div>
        </div>
    `).join('');
}

// ==============================================================
// EQUITY BREAKDOWN — Style + Sectorial + Regional (Apr-2026 cierre, Maximus)
// ==============================================================
async function renderEquityBreakdown() {
    let data;
    try {
        const r = await fetch('data/equity_breakdown_apr26.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('equity_breakdown_apr26.json not available', e);
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
        const r = await fetch('data/fi_breakdown_apr26.json?_=' + Date.now());
        if (!r.ok) throw new Error('no data');
        data = await r.json();
    } catch(e) {
        console.warn('fi_breakdown_apr26.json not available', e);
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
    document.getElementById('fr-bmk-ig').textContent = s.bmk_ig + '%';
}

// ==============================================================
// UPDATE TIMESTAMPS
// ==============================================================
function updateTime() {
    const now = new Date();
    const s = now.toLocaleString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    document.getElementById('update-time').textContent = s;
    document.getElementById('footer-time').textContent = s;
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
            console.log("Lynk data loaded:", L.refreshedAt);
        }
    } catch(e) {
        console.log("Lynk static JSON not found; using hardcoded");
    }

    renderOverview();
    renderPositions(livePrices);
    renderCurrency();
    renderCountry();
    renderYield();
    renderYTM();
    renderPerformance();
    renderEquityRace();
    renderEquityBreakdown();
    renderFIRace();
    renderFIBreakdown();
    renderDataHealth();
})();

// ==============================================================
// DATA HEALTH — Lineage + status of every data source
// ==============================================================
async function renderDataHealth() {
    let catalog;
    try {
        const r = await fetch('data/data_health_catalog.json?_=' + Date.now());
        if (!r.ok) throw new Error('no catalog');
        catalog = await r.json();
    } catch (e) {
        console.warn('data_health_catalog.json not available', e);
        return;
    }

    // Helper: get last-modified date from a JSON file (via its content asOf/refreshedAt fields)
    async function probeFileDate(path) {
        if (!path || path.startsWith('(') || path.includes('funds_metadata.js') || path.includes('live_prices.js')) {
            // Static JS modules — use their git mtime via fetch HEAD or just assume recent
            try {
                const r = await fetch(path + '?_=' + Date.now(), { method: 'HEAD' });
                const lm = r.headers.get('last-modified');
                if (lm) return new Date(lm);
            } catch (e) {}
            return null;
        }
        try {
            const r = await fetch(path + '?_=' + Date.now());
            if (!r.ok) return null;
            const d = await r.json();
            // Try multiple fields
            const fields = ['asOf', 'refreshedAt', 'refreshed_at', 'as_of', 'lastUpdate', 'extractedAt'];
            for (const f of fields) {
                if (d[f]) return new Date(d[f]);
            }
            // Try Last-Modified header
            const lm = r.headers.get('last-modified');
            if (lm) return new Date(lm);
        } catch (e) {}
        return null;
    }

    // Status calculation
    function statusOf(daysAgo, expectedDays) {
        if (daysAgo == null) return { code: 'unknown', label: '⚪ Unknown', color: '#90A4AE' };
        if (daysAgo <= 1) return { code: 'live', label: '🟢 LIVE', color: '#81C784' };
        if (daysAgo <= expectedDays) return { code: 'ok', label: '🟢 OK', color: '#81C784' };
        if (daysAgo <= expectedDays * 1.5) return { code: 'needs_refresh', label: '🟠 NEEDS REFRESH', color: '#FFA726' };
        return { code: 'stale', label: '🔴 STALE', color: '#EF5350' };
    }

    const now = new Date();
    const rows = [];
    const todos = [];
    let counts = { live: 0, ok: 0, needs_refresh: 0, stale: 0, unknown: 0, deprecated: 0 };

    for (const src of catalog.sources) {
        // Get most recent date from any of the source's files
        let mostRecent = null;
        for (const f of src.files) {
            const d = await probeFileDate(f);
            if (d && (!mostRecent || d > mostRecent)) mostRecent = d;
        }
        const daysAgo = mostRecent ? Math.floor((now - mostRecent) / (1000 * 60 * 60 * 24)) : null;
        const status = src.deprecated
            ? { code: 'deprecated', label: '⚰️ DEPRECATED', color: '#90A4AE' }
            : statusOf(daysAgo, src.expected_frequency_days);
        counts[status.code] = (counts[status.code] || 0) + 1;

        rows.push(`
            <tr>
                <td class="left"><strong>${src.name}</strong><br><span style="font-size:10px;color:#90CAF9;">${src.source_type}</span></td>
                <td class="left">${src.category}</td>
                <td class="left" style="font-size:10px;color:#E0E8F0;">${src.feeds_tabs.join(', ')}</td>
                <td>${mostRecent ? mostRecent.toISOString().slice(0, 10) : '—'}</td>
                <td><strong style="color:${daysAgo > src.expected_frequency_days ? '#EF5350' : '#81C784'};">${daysAgo != null ? daysAgo + 'd' : '—'}</strong></td>
                <td>${src.expected_frequency_days}d</td>
                <td class="left"><span style="color:${status.color};font-weight:700;">${status.label}</span></td>
                <td class="left" style="font-size:10px;color:#90CAF9;">${src.refresh_method}</td>
            </tr>
        `);

        if (src.deprecated || status.code === 'stale' || status.code === 'needs_refresh') {
            todos.push(`<li><strong>${src.name}</strong> ${src.deprecated ? `→ ${src.deprecated_reason || 'deprecated'}` : `→ ${daysAgo}d sin refresh (expected ${src.expected_frequency_days}d)`}</li>`);
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
        summaryCard('🔴 STALE', counts.stale || 0, '#EF5350') +
        summaryCard('⚰️ DEPRECATED', counts.deprecated || 0, '#90A4AE') +
        summaryCard('⚪ UNKNOWN', counts.unknown || 0, '#607D8B');

    document.getElementById('dh-tbody').innerHTML = rows.join('');
    document.getElementById('dh-todos').innerHTML = todos.length
        ? `<ul style="color:#FFA726;">${todos.join('')}</ul>`
        : '<p style="color:#81C784;">✅ Todas las fuentes al día</p>';
}
