/**
 * Analytics dashboards: Category matrix, ECharts pie, Chart.js doughnut/bar.
 * Color scheme: monochromatic terracotta gradient + sage green accent.
 */

let echartInstances = {};

// Monochromatic palette: terracotta shades (light → dark) + sage accent
const MONO_PALETTE = [
    '#f2ddd7', '#e8c4ba', '#daa898', '#cc8c76',
    '#bc6c5a', '#a05a4b', '#7d463a', '#5a3329',
];
const ACCENT_SAGE = '#5a7c5a';

// Cache for matrix re-rendering on dimension change
let _matrixCompanies = [];
let _matrixCategories = [];

// --- Category Matrix (replaces treemap) ---

function renderCategoryMatrix(companies, categories) {
    // Allow re-render from dimension dropdown (no args = use cache)
    if (companies) _matrixCompanies = companies;
    else companies = _matrixCompanies;
    if (categories) _matrixCategories = categories;
    else categories = _matrixCategories;

    const container = document.getElementById('matrixContainer');
    if (!container || !companies.length || !categories.length) {
        if (container) container.innerHTML = '<p class="hint-text" style="padding:20px;text-align:center">No data available</p>';
        return;
    }

    const dim = (document.getElementById('matrixDimension') || {}).value || 'funding_stage';
    const topCats = categories.filter(c => !c.parent_id);

    // Build parent lookup for subcategory companies
    const parentLookup = {};
    categories.forEach(c => { if (c.parent_id) parentLookup[c.id] = c.parent_id; });

    // Get unique column values, sorted by frequency (top 10)
    const colCount = {};
    companies.forEach(c => {
        const val = c[dim] || 'Unknown';
        colCount[val] = (colCount[val] || 0) + 1;
    });
    const colValues = Object.entries(colCount)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([name]) => name);

    // Build matrix: map each company to its top-level category
    const matrix = {};
    topCats.forEach(cat => {
        matrix[cat.id] = {};
        colValues.forEach(v => { matrix[cat.id][v] = 0; });
    });
    companies.forEach(c => {
        const topCatId = parentLookup[c.category_id] || c.category_id;
        if (!matrix[topCatId]) return;
        const val = c[dim] || 'Unknown';
        if (matrix[topCatId][val] !== undefined) matrix[topCatId][val]++;
    });

    // Find max for heat intensity
    let maxVal = 1;
    Object.values(matrix).forEach(row => {
        Object.values(row).forEach(v => { if (v > maxVal) maxVal = v; });
    });

    // Render HTML table
    let html = '<table class="matrix-table"><thead><tr><th class="matrix-corner"></th>';
    colValues.forEach(v => {
        const label = v.length > 24 ? v.substring(0, 23) + '\u2026' : v;
        html += `<th title="${esc(v)}">${esc(label)}</th>`;
    });
    html += '</tr></thead><tbody>';

    topCats.forEach(cat => {
        const catName = cat.name.length > 36 ? cat.name.substring(0, 35) + '\u2026' : cat.name;
        html += `<tr><td class="matrix-row-label" title="${esc(cat.name)}">${esc(catName)}</td>`;
        colValues.forEach(v => {
            const count = matrix[cat.id]?.[v] || 0;
            const intensity = count ? Math.min(0.12 + (count / maxVal) * 0.45, 0.6) : 0;
            const bg = count ? `rgba(188, 108, 90, ${intensity.toFixed(2)})` : 'transparent';
            const textColor = intensity > 0.35 ? '#fff' : 'var(--text-primary)';
            html += `<td class="matrix-cell" style="background:${bg};color:${textColor}">${count || ''}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

// --- ECharts: Geographic Distribution (Pie) ---

function renderAnalyticsDashboard(companies, categories) {
    if (!window.echarts) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const theme = isDark ? 'dark' : null;

    // Geographic Distribution (Pie — monochromatic terracotta)
    const geoDiv = document.getElementById('chartGeoDist');
    if (geoDiv) {
        if (echartInstances.geoDist) echartInstances.geoDist.dispose();
        echartInstances.geoDist = echarts.init(geoDiv, theme);
        const geoMap = {};
        companies.forEach(c => {
            const geo = c.hq_country || c.geography || 'Unknown';
            geoMap[geo] = (geoMap[geo] || 0) + 1;
        });
        const geoData = Object.entries(geoMap)
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value)
            .slice(0, 12);

        // Monochromatic terracotta gradient for pie slices
        const pieColors = geoData.map((_, i) => {
            const t = geoData.length > 1 ? i / (geoData.length - 1) : 0;
            return _lerpColor('#e8c4ba', '#7d463a', t);
        });
        // Accent the top slice with sage green
        if (pieColors.length > 0) pieColors[0] = ACCENT_SAGE;

        echartInstances.geoDist.setOption({
            tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
            series: [{
                type: 'pie',
                radius: ['35%', '70%'],
                data: geoData,
                color: pieColors,
                label: { formatter: '{b}: {c}', fontSize: 11 },
                emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.15)' } },
            }],
        });
    }

    // Render matrix
    renderCategoryMatrix(companies, categories);
}

function _chartTextColor() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? '#ccc5b9' : '#3D4035';
}

function _chartGridColor() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
}

// --- Chart.js Dashboards (Doughnut + Bar — monochromatic) ---

function renderChartJsDashboard(companies) {
    if (!window.Chart) return;
    const textColor = _chartTextColor();
    const gridColor = _chartGridColor();

    // Funding Stage (Doughnut — monochromatic terracotta)
    const fundingCanvas = document.getElementById('chartFundingStage');
    if (fundingCanvas) {
        const ctx = fundingCanvas.getContext('2d');
        const stageMap = {};
        companies.forEach(c => {
            const stage = c.funding_stage || 'Unknown';
            stageMap[stage] = (stageMap[stage] || 0) + 1;
        });
        const labels = Object.keys(stageMap);
        const data = Object.values(stageMap);
        // Monochromatic terracotta gradient for slices
        const colors = labels.map((_, i) => {
            const t = labels.length > 1 ? i / (labels.length - 1) : 0;
            return _lerpColor('#e8c4ba', '#7d463a', t);
        });
        if (colors.length > 0) colors[0] = ACCENT_SAGE;

        if (window._chartFunding) window._chartFunding.destroy();
        window._chartFunding = new Chart(ctx, {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors }] },
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom', labels: { font: { size: 11 }, color: textColor } } },
            },
        });
    }

    // Confidence Histogram (Bar — terracotta gradient, sage for high)
    const confCanvas = document.getElementById('chartConfidence');
    if (confCanvas) {
        const ctx = confCanvas.getContext('2d');
        const buckets = { '0-20%': 0, '20-40%': 0, '40-60%': 0, '60-80%': 0, '80-100%': 0 };
        companies.forEach(c => {
            const pct = (c.confidence_score || 0) * 100;
            if (pct < 20) buckets['0-20%']++;
            else if (pct < 40) buckets['20-40%']++;
            else if (pct < 60) buckets['40-60%']++;
            else if (pct < 80) buckets['60-80%']++;
            else buckets['80-100%']++;
        });
        // Terracotta light → dark for low→mid, sage green for high
        const barColors = ['#e8c4ba', '#daa898', '#cc8c76', '#a05a4b', ACCENT_SAGE];

        if (window._chartConf) window._chartConf.destroy();
        window._chartConf = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: Object.keys(buckets),
                datasets: [{
                    label: 'Companies',
                    data: Object.values(buckets),
                    backgroundColor: barColors,
                }],
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1, color: textColor }, grid: { color: gridColor } },
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                },
            },
        });
    }
}

// Color interpolation helper (hex → hex, linear)
function _lerpColor(a, b, t) {
    const ah = parseInt(a.slice(1), 16), bh = parseInt(b.slice(1), 16);
    const ar = (ah >> 16) & 0xff, ag = (ah >> 8) & 0xff, ab = ah & 0xff;
    const br = (bh >> 16) & 0xff, bg = (bh >> 8) & 0xff, bb = bh & 0xff;
    const r = Math.round(ar + (br - ar) * t);
    const g = Math.round(ag + (bg - ag) * t);
    const b2 = Math.round(ab + (bb - ab) * t);
    return '#' + ((1 << 24) + (r << 16) + (g << 8) + b2).toString(16).slice(1);
}

async function refreshDashboardCharts() {
    if (!currentProjectId) return;
    const [compRes, taxRes] = await Promise.all([
        safeFetch(`/api/companies?project_id=${currentProjectId}`),
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();
    renderAnalyticsDashboard(companies, categories);
    renderChartJsDashboard(companies);
}

// Resize handler for ECharts
window.addEventListener('resize', () => {
    Object.values(echartInstances).forEach(chart => {
        if (chart && chart.resize) chart.resize();
    });
});
