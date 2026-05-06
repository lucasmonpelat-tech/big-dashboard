/* ============================================================
   BIG Factsheet — Data loader + chart renderer
   Auto-pulls JSON data and renders Plotly charts
   ============================================================ */

const NAVY = '#1F3864';
const SAND = '#A78768';     // brownish/tan for benchmark
const GOLD = '#C9A87E';
const NEGATIVE = '#A8554F';

// ============================================================
// MANUAL DATA — fill from Maximus / Lynk
// (will be replaced as Lucas provides values)
// ============================================================
const APRIL_2026 = {
    // Returns table (page 1) — Maximus Apr 2026
    big: {
        '1m': 2.2,      // April real (Lucas confirmed)
        '3m': -0.98,
        '6m': 0.82,
        'ytd': 1.0,     // computed from Q1 + April +2.21
        '1y': 7.75,
        '3y': 10.91,
        '5y': 6.53,
        'inicio': 8.7,  // mantener marzo (sin cambio)
    },
    bench: {
        '1m': 5.48,
        '3m': 3.71,
        '6m': 5.75,
        'ytd': 4.62,
        '1y': 18.76,
        '3y': 13.70,
        '5y': 6.99,
        'inicio': 8.2,  // mantener marzo (sin cambio)
    },
    // Monthly returns table — historical modeled + real Lynk
    monthly: {
        2022: { values: [-1.8, -0.3, 1.4, -3.6, -0.9, -5.7, 3.8, -2.5, -4.4, 2.4, 2.4, -0.9], total: -10.1 },
        2023: { values: [4.0, -1.8, 2.6, 0.8, -1.1, 3.1, 1.3, -0.5, -1.9, 0.0, 3.8, 2.9], total: 13.6 },
        2024: { values: [1.1, 2.2, 2.2, -2.5, 2.5, 0.5, 2.6, 2.1, 1.2, -0.7, 3.4, -2.0], total: 12.5 },
        2025: { values: [2.4, 1.2, 0.1, 0.9, 1.6, 1.9, 0.5, 1.8, 1.6, 0.4, 0.3, 0.1], total: 13.4 },
        2026: { values: [1.6, 0.6, -3.3, 2.2, null, null, null, null, null, null, null, null], total: 1.0 },
    },
    // Benchmark comparativo bars (BIG vs ACWI 60/40) — Maximus Apr 2026
    bmk_bars: {
        labels: ['Ret. 3 años', 'Ret. 5 años', 'Vol. 3 años', 'Vol. 5 años', 'Máximo Drawdown 3 años', 'Máximo Drawdown 5 años'],
        big:    [10.91, 6.53, 5.65, 7.11, -3.32, -13.48],
        bench:  [13.70, 6.99, 8.57, 9.68, -9.94, -21.11],
    },
    sharpe_bars: {
        labels: ['Sharpe 3 años', 'Sharpe 5 años'],
        big:    [1.18, 0.42],
        bench:  [1.11, 0.35],
    },
    // Sleeve weights for donut (page 1) — Maximus-style bucketing
    // RV / RF (incl Cash) / Alts (incl Derivados)
    sleeve_weights: {
        renta_variable: 29,
        renta_fija: 40,
        alternativos: 31,
    },
};

// ============================================================
// LOAD DATA FROM JSON
// ============================================================
async function loadData() {
    const noCache = '?_=' + Date.now();
    const positions = await fetch('../data/positions_latest.json' + noCache).then(r => r.json());
    const lynkSeries = await fetch('../data/lynk_nav_series.json' + noCache).then(r => r.json());
    const lynkData = await fetch('../data/lynk_data.json' + noCache).then(r => r.json());
    return { positions, lynkSeries, lynkData };
}

// ============================================================
// DONUT — Sleeve weights
// ============================================================
function renderDonutSleeves(positions) {
    // Use manual Maximus-style bucketing for factsheet (RV / RF+Cash / Alts+Deriv)
    const w = APRIL_2026.sleeve_weights;
    const rv = w.renta_variable;
    const rf = w.renta_fija;
    const alts = w.alternativos;

    const trace = {
        type: 'pie',
        hole: 0.55,
        labels: ['Alternativos', 'Renta Variable', 'Renta Fija'],
        values: [alts, rv, rf],
        marker: {
            colors: ['#1F3864', '#7B8C9E', '#34495E'],
            line: { color: '#FFFFFF', width: 2 },
        },
        text: [
            `${alts.toFixed(0)}%<br>Alternativos`,
            `${rv.toFixed(0)}%<br>Renta<br>Variable`,
            `${rf.toFixed(0)}%<br>Renta Fija`,
        ],
        textposition: 'outside',
        textinfo: 'text',
        textfont: { size: 11, color: '#1E2A3A', family: 'Segoe UI' },
        hoverinfo: 'label+percent',
        sort: false,
        rotation: 90,
    };
    const layout = {
        margin: { t: 25, r: 25, b: 25, l: 25 },
        showlegend: false,
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
    };
    Plotly.newPlot('donut-sleeves', [trace], layout, { displayModeBar: false, responsive: true });
}

// ============================================================
// LINE CHART — Cumulative growth (BIG sleeve vs ACWI 60/40)
// ============================================================
function renderGrowthChart(lynkSeries) {
    // Real data: from Lynk inception (2025-06-30)
    const series = lynkSeries.series;
    const dates = series.map(p => p.date);
    const big = series.map(p => p.value);

    const trace_big = {
        x: dates, y: big,
        name: 'Balanced Income & Growth',
        type: 'scatter', mode: 'lines+markers',
        line: { color: NAVY, width: 2 },
        marker: { size: 3, color: NAVY },
    };

    // Placeholder benchmark line (TODO: real ACWI 60/40 data)
    // Will be replaced when Lucas provides Maximus modeled benchmark
    const layout = {
        margin: { t: 30, r: 16, b: 35, l: 40 },
        legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.1, font: { size: 9 } },
        font: { family: 'Segoe UI', size: 9, color: '#2E3D52' },
        xaxis: { showgrid: false, tickfont: { size: 9 }, type: 'date' },
        yaxis: { showgrid: true, gridcolor: '#ECEFF1', tickfont: { size: 9 } },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
    };
    Plotly.newPlot('growth-chart', [trace_big], layout, { displayModeBar: false, responsive: true });
}

// ============================================================
// RETURNS TABLE
// ============================================================
function renderReturnsTable() {
    const fmt = v => v == null ? '—' : v.toFixed(1);
    const periods = ['1m', '3m', '6m', 'ytd', '1y', '3y', '5y', 'inicio'];
    const big = APRIL_2026.big;
    const bench = APRIL_2026.bench;
    const tbody = document.getElementById('returns-tbody');
    tbody.innerHTML = `
        <tr class="row-big">
            <td class="left">Balanced Income and Growth (BIG)</td>
            ${periods.map(p => `<td>${fmt(big[p])}</td>`).join('')}
        </tr>
        <tr class="row-bmk">
            <td class="left">ACWI 60%/40% AGG</td>
            ${periods.map(p => `<td>${fmt(bench[p])}</td>`).join('')}
        </tr>
    `;
}

// ============================================================
// MONTHLY RETURNS TABLE
// ============================================================
function renderMonthlyTable() {
    const tbody = document.getElementById('monthly-tbody');
    const rows = [];
    Object.keys(APRIL_2026.monthly).sort().forEach(year => {
        const data = APRIL_2026.monthly[year];
        const cells = data.values.map(v =>
            v == null
                ? '<td class="empty">&nbsp;</td>'
                : `<td>${v >= 0 ? '+' : ''}${v.toFixed(1)}</td>`
        ).join('');
        const totalCell = data.total == null
            ? '<td class="empty">—</td>'
            : `<td class="year-total">${data.total >= 0 ? '+' : ''}${data.total.toFixed(1)}</td>`;
        rows.push(`<tr><td class="left year-cell">${year}</td>${cells}${totalCell}</tr>`);
    });
    tbody.innerHTML = rows.join('');
}

// ============================================================
// BENCHMARK COMPARATIVO BARS
// ============================================================
function renderBmkBars() {
    const cfg = APRIL_2026.bmk_bars;
    const has_data = cfg.big.some(v => v != null);
    if (!has_data) {
        document.getElementById('bmk-bars').innerHTML = '<div style="text-align:center;padding:80px;color:#888;font-size:11px;">[Pending Maximus data: 3y/5y returns, vol, MaxDD]</div>';
    } else {
        const traces = [
            { type: 'bar', name: 'BIG', x: cfg.labels, y: cfg.big, marker: { color: NAVY }, text: cfg.big.map(v => v == null ? '' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'), textposition: 'outside', textfont: { size: 9 } },
            { type: 'bar', name: 'ACWI 60%/40% AGG', x: cfg.labels, y: cfg.bench, marker: { color: SAND }, text: cfg.bench.map(v => v == null ? '' : (v >= 0 ? '+' : '') + v.toFixed(1) + '%'), textposition: 'outside', textfont: { size: 9 } },
        ];
        const layout = {
            barmode: 'group',
            margin: { t: 10, r: 10, b: 60, l: 35 },
            font: { family: 'Segoe UI', size: 9, color: '#2E3D52' },
            xaxis: { tickangle: -25, tickfont: { size: 8 } },
            yaxis: { showgrid: true, gridcolor: '#ECEFF1', ticksuffix: '%' },
            legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: -0.45, font: { size: 9 } },
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
        };
        Plotly.newPlot('bmk-bars', traces, layout, { displayModeBar: false, responsive: true });
    }
}

function renderSharpeBars() {
    const cfg = APRIL_2026.sharpe_bars;
    const has_data = cfg.big.some(v => v != null);
    if (!has_data) {
        document.getElementById('sharpe-bars').innerHTML = '<div style="text-align:center;padding:80px;color:#888;font-size:11px;">[Pending Maximus data: Sharpe 3y/5y]</div>';
    } else {
        const traces = [
            { type: 'bar', name: 'BIG', x: cfg.labels, y: cfg.big, marker: { color: NAVY }, text: cfg.big.map(v => v == null ? '' : v.toFixed(2)), textposition: 'outside', textfont: { size: 10 } },
            { type: 'bar', name: 'ACWI 60%/40% AGG', x: cfg.labels, y: cfg.bench, marker: { color: SAND }, text: cfg.bench.map(v => v == null ? '' : v.toFixed(2)), textposition: 'outside', textfont: { size: 10 } },
        ];
        const layout = {
            barmode: 'group',
            margin: { t: 10, r: 10, b: 60, l: 35 },
            font: { family: 'Segoe UI', size: 9, color: '#2E3D52' },
            yaxis: { showgrid: true, gridcolor: '#ECEFF1' },
            legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: -0.25, font: { size: 9 } },
            paper_bgcolor: 'rgba(0,0,0,0)',
            plot_bgcolor: 'rgba(0,0,0,0)',
        };
        Plotly.newPlot('sharpe-bars', traces, layout, { displayModeBar: false, responsive: true });
    }
}

// ============================================================
// MAIN INIT
// ============================================================
async function init() {
    try {
        const { positions, lynkSeries, lynkData } = await loadData();
        renderDonutSleeves(positions);
        renderGrowthChart(lynkSeries);
        renderReturnsTable();
        renderMonthlyTable();
        renderBmkBars();
        renderSharpeBars();
        console.log('[Factsheet] Rendered. Lynk NAV:', lynkData.nav, '| AUM:', lynkData.aum);
    } catch (e) {
        console.error('Factsheet render error:', e);
    }
}

document.addEventListener('DOMContentLoaded', init);
