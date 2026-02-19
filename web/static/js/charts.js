/**
 * Analytics dashboards: Category matrix (ECharts heatmap), ECharts pie, Chart.js doughnut/bar.
 * Color scheme: "The Instrument" — monochromatic black/white/gray.
 * Fonts: Plus Jakarta Sans (labels), JetBrains Mono (data values/numbers).
 */

let echartInstances = {};

// "The Instrument" monochromatic palette: pure black/white/gray
const MONO_PALETTE = [
    '#000000', '#333333', '#666666', '#999999', '#CCCCCC', '#E5E5E5',
];

// Font families
const FONT_LABEL = 'Plus Jakarta Sans, sans-serif';
const FONT_DATA = 'JetBrains Mono, monospace';

// Cache for matrix re-rendering on dimension change
let _matrixCompanies = [];
let _matrixCategories = [];

// ResizeObserver for ECharts auto-resize
let _echartsResizeObserver = null;

// --- ECharts Theme Registration ---

function _initEChartsTheme() {
    if (!window.echarts || echarts._instrumentThemeRegistered) return;

    echarts.registerTheme('instrument', {
        color: ['#000000', '#333333', '#666666', '#999999', '#CCCCCC'],
        backgroundColor: 'transparent',
        textStyle: {
            fontFamily: FONT_LABEL,
            color: '#333333',
        },
        title: {
            textStyle: {
                color: '#000000',
                fontWeight: 600,
                fontFamily: FONT_LABEL,
            },
            subtextStyle: {
                color: '#666666',
                fontFamily: FONT_LABEL,
            },
        },
        legend: {
            textStyle: {
                color: '#333333',
                fontFamily: FONT_LABEL,
            },
        },
        tooltip: {
            backgroundColor: '#ffffff',
            borderColor: '#E5E5E5',
            borderWidth: 1,
            textStyle: {
                color: '#000000',
                fontFamily: FONT_LABEL,
                fontSize: 12,
            },
        },
        categoryAxis: {
            axisLine: { lineStyle: { color: '#CCCCCC' } },
            axisTick: { lineStyle: { color: '#CCCCCC' } },
            axisLabel: { color: '#333333', fontFamily: FONT_LABEL },
            splitLine: { lineStyle: { color: '#E5E5E5' } },
        },
        valueAxis: {
            axisLine: { lineStyle: { color: '#CCCCCC' } },
            axisTick: { lineStyle: { color: '#CCCCCC' } },
            axisLabel: { color: '#333333', fontFamily: FONT_DATA },
            splitLine: { lineStyle: { color: '#E5E5E5' } },
        },
    });

    echarts._instrumentThemeRegistered = true;
}

// --- ECharts ResizeObserver ---

function _setupEChartsResizeObserver() {
    if (_echartsResizeObserver) return;
    if (!window.ResizeObserver) return;

    _echartsResizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
            // Find which ECharts instance lives in this container
            for (const [key, chart] of Object.entries(echartInstances)) {
                if (chart && chart.getDom && chart.getDom() === entry.target) {
                    chart.resize();
                }
            }
        }
    });
}

function _observeEChartsContainer(el) {
    if (!_echartsResizeObserver) _setupEChartsResizeObserver();
    if (_echartsResizeObserver && el) {
        _echartsResizeObserver.observe(el);
    }
}

// --- Category Matrix (ECharts heatmap with Chart.js-style HTML table fallback) ---

function renderCategoryMatrix(companies, categories) {
    // Allow re-render from dimension dropdown (no args = use cache)
    if (companies) _matrixCompanies = companies;
    else companies = _matrixCompanies;
    if (categories) _matrixCategories = categories;
    else categories = _matrixCategories;

    const container = document.getElementById('matrixContainer');
    if (!container || !companies.length) {
        if (container) container.innerHTML = '<p class="hint-text" style="padding:20px;text-align:center">No data available</p>';
        return;
    }

    const colDim = (document.getElementById('matrixDimension') || {}).value || 'funding_stage';
    const rowDim = (document.getElementById('matrixRowDimension') || {}).value || 'category';

    // Build parent lookup for category-based rows
    const parentLookup = {};
    if (categories) categories.forEach(c => { if (c.parent_id) parentLookup[c.id] = c.parent_id; });
    const topCats = categories ? categories.filter(c => !c.parent_id) : [];

    // Helper to get row key for a company
    function getRowKey(c) {
        if (rowDim === 'category') {
            const topCatId = parentLookup[c.category_id] || c.category_id;
            const cat = topCats.find(tc => tc.id === topCatId);
            return cat ? cat.name : 'Uncategorized';
        }
        if (rowDim === 'tags') {
            return (c.tags && c.tags.length) ? c.tags : ['Untagged'];
        }
        return c[rowDim] || 'Unknown';
    }

    // Get unique column values, sorted by frequency (top 12)
    const colCount = {};
    companies.forEach(c => {
        const val = c[colDim] || 'Unknown';
        colCount[val] = (colCount[val] || 0) + 1;
    });
    const colValues = Object.entries(colCount)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12)
        .map(([name]) => name);

    // Build row keys
    const rowCount = {};
    companies.forEach(c => {
        const keys = rowDim === 'tags' ? getRowKey(c) : [getRowKey(c)];
        (Array.isArray(keys) ? keys : [keys]).forEach(k => {
            rowCount[k] = (rowCount[k] || 0) + 1;
        });
    });
    const rowKeys = Object.entries(rowCount)
        .sort((a, b) => b[1] - a[1])
        .map(([name]) => name);

    // Build matrix
    const matrix = {};
    rowKeys.forEach(rk => {
        matrix[rk] = {};
        colValues.forEach(v => { matrix[rk][v] = 0; });
    });
    companies.forEach(c => {
        const rKeys = rowDim === 'tags' ? getRowKey(c) : [getRowKey(c)];
        const colVal = c[colDim] || 'Unknown';
        (Array.isArray(rKeys) ? rKeys : [rKeys]).forEach(rk => {
            if (matrix[rk] && matrix[rk][colVal] !== undefined) matrix[rk][colVal]++;
        });
    });

    // Find max for heat intensity
    let maxVal = 1;
    Object.values(matrix).forEach(row => {
        Object.values(row).forEach(v => { if (v > maxVal) maxVal = v; });
    });

    // --- ECharts heatmap (preferred) ---
    if (window.echarts) {
        _initEChartsTheme();

        // Build ECharts heatmap data: [colIndex, rowIndex, value]
        const heatmapData = [];
        rowKeys.forEach((rk, ri) => {
            colValues.forEach((cv, ci) => {
                heatmapData.push([ci, ri, matrix[rk]?.[cv] || 0]);
            });
        });

        // Prepare container for ECharts (needs fixed height)
        const minHeight = Math.max(300, rowKeys.length * 36 + 80);
        container.innerHTML = '';
        container.style.minHeight = minHeight + 'px';

        if (echartInstances.matrix) echartInstances.matrix.dispose();
        echartInstances.matrix = echarts.init(container, 'instrument');

        echartInstances.matrix.setOption({
            tooltip: {
                position: 'top',
                formatter: function (params) {
                    return `<span style="font-family:${FONT_LABEL}">${params.name}</span><br/>` +
                           `<span style="font-family:${FONT_LABEL}">${rowKeys[params.data[1]]}</span> × ` +
                           `<span style="font-family:${FONT_LABEL}">${colValues[params.data[0]]}</span><br/>` +
                           `<strong style="font-family:${FONT_DATA}">${params.data[2]}</strong> companies`;
                },
            },
            grid: {
                left: '15%',
                right: '5%',
                top: '10%',
                bottom: '15%',
            },
            xAxis: {
                type: 'category',
                data: colValues,
                axisLabel: {
                    rotate: 45,
                    fontSize: 11,
                    fontFamily: FONT_LABEL,
                    color: '#333333',
                },
                splitArea: { show: true },
            },
            yAxis: {
                type: 'category',
                data: rowKeys,
                axisLabel: {
                    fontSize: 11,
                    fontFamily: FONT_LABEL,
                    color: '#333333',
                },
                splitArea: { show: true },
            },
            visualMap: {
                min: 0,
                max: maxVal,
                calculable: true,
                orient: 'horizontal',
                left: 'center',
                bottom: '0%',
                inRange: {
                    color: ['#ffffff', '#000000'],
                },
                textStyle: {
                    fontFamily: FONT_DATA,
                    color: '#333333',
                },
            },
            series: [{
                type: 'heatmap',
                data: heatmapData,
                label: {
                    show: true,
                    fontFamily: FONT_DATA,
                    fontSize: 11,
                    formatter: function (params) {
                        return params.data[2] || '';
                    },
                },
                emphasis: {
                    itemStyle: {
                        shadowBlur: 0,
                        borderColor: '#000000',
                        borderWidth: 1,
                    },
                },
            }],
        });

        _observeEChartsContainer(container);
        return;
    }

    // --- HTML table fallback (when ECharts not loaded) ---
    let html = '<table class="matrix-table"><thead><tr><th class="matrix-corner"></th>';
    colValues.forEach(v => {
        html += `<th title="${esc(v)}">${esc(v)}</th>`;
    });
    html += '</tr></thead><tbody>';

    rowKeys.forEach(rk => {
        html += `<tr><td class="matrix-row-label" title="${esc(rk)}">${esc(rk)}</td>`;
        colValues.forEach(v => {
            const count = matrix[rk]?.[v] || 0;
            const intensity = count ? Math.min(0.12 + (count / maxVal) * 0.55, 0.7) : 0;
            const bg = count ? `rgba(0, 0, 0, ${intensity.toFixed(2)})` : 'transparent';
            const textColor = intensity > 0.35 ? '#fff' : 'var(--text-primary)';
            html += `<td class="matrix-cell" style="background:${bg};color:${textColor};font-family:${FONT_DATA}">${count || ''}</td>`;
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

// --- ECharts: Geographic Distribution (Pie) ---

function renderAnalyticsDashboard(companies, categories) {
    if (!window.echarts) return;
    _initEChartsTheme();

    // Geographic Distribution (Pie — monochromatic Instrument)
    const geoDiv = document.getElementById('chartGeoDist');
    if (geoDiv) {
        if (echartInstances.geoDist) echartInstances.geoDist.dispose();
        echartInstances.geoDist = echarts.init(geoDiv, 'instrument');
        const geoMap = {};
        companies.forEach(c => {
            const geo = c.hq_country || c.geography || 'Unknown';
            geoMap[geo] = (geoMap[geo] || 0) + 1;
        });
        const geoData = Object.entries(geoMap)
            .map(([name, value]) => ({ name, value }))
            .sort((a, b) => b.value - a.value)
            .slice(0, 12);

        // Monochromatic gradient for pie slices: black → light gray
        const pieColors = geoData.map((_, i) => {
            const t = geoData.length > 1 ? i / (geoData.length - 1) : 0;
            return _lerpColor('#000000', '#CCCCCC', t);
        });

        echartInstances.geoDist.setOption({
            tooltip: {
                trigger: 'item',
                formatter: '{b}: {c} ({d}%)',
                textStyle: { fontFamily: FONT_LABEL },
            },
            series: [{
                type: 'pie',
                radius: ['35%', '70%'],
                data: geoData,
                color: pieColors,
                label: {
                    formatter: '{b}: {c}',
                    fontSize: 11,
                    fontFamily: FONT_LABEL,
                },
                emphasis: {
                    itemStyle: {
                        shadowBlur: 10,
                        shadowColor: 'rgba(0,0,0,0.15)',
                    },
                },
            }],
        });

        _observeEChartsContainer(geoDiv);
    }

    // Render matrix
    renderCategoryMatrix(companies, categories);
}

function _chartTextColor() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? '#CCCCCC' : '#333333';
}

function _chartGridColor() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
}

// --- Chart.js Dashboards (Doughnut + Bar — Instrument monochromatic) ---

function renderChartJsDashboard(companies) {
    if (!window.Chart) return;
    const textColor = _chartTextColor();
    const gridColor = _chartGridColor();

    // Funding Stage (Doughnut — Instrument monochromatic)
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
        // Monochromatic gradient: black → light gray
        const colors = labels.map((_, i) => {
            const t = labels.length > 1 ? i / (labels.length - 1) : 0;
            return _lerpColor('#000000', '#CCCCCC', t);
        });

        if (window._chartFunding) window._chartFunding.destroy();
        window._chartFunding = new Chart(ctx, {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors }] },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            font: { size: 11, family: FONT_LABEL },
                            color: textColor,
                        },
                    },
                },
            },
        });
    }

    // Confidence Histogram (Bar — Instrument monochromatic gradient)
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
        // Instrument: light gray → black gradient for low → high
        const barColors = ['#CCCCCC', '#999999', '#666666', '#333333', '#000000'];

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
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1,
                            color: textColor,
                            font: { family: FONT_DATA },
                        },
                        grid: { color: gridColor },
                    },
                    x: {
                        ticks: {
                            color: textColor,
                            font: { family: FONT_LABEL },
                        },
                        grid: { color: gridColor },
                    },
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

// Resize handler for ECharts (window-level fallback)
window.addEventListener('resize', () => {
    Object.values(echartInstances).forEach(chart => {
        if (chart && chart.resize) chart.resize();
    });
});
