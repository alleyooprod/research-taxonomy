/**
 * ECharts treemap/pie and Chart.js doughnut/bar dashboards.
 */

let echartInstances = {};

function renderAnalyticsDashboard(companies, categories) {
    if (!window.echarts) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const theme = isDark ? 'dark' : null;

    // Category Distribution (Treemap)
    const catDiv = document.getElementById('chartCategoryDist');
    if (catDiv) {
        if (echartInstances.catDist) echartInstances.catDist.dispose();
        echartInstances.catDist = echarts.init(catDiv, theme);
        const topCats = categories.filter(c => !c.parent_id);
        const treemapData = topCats.map(cat => ({
            name: cat.name,
            value: cat.company_count || 0,
        })).filter(d => d.value > 0);
        echartInstances.catDist.setOption({
            tooltip: { trigger: 'item', formatter: '{b}: {c} companies' },
            series: [{
                type: 'treemap',
                data: treemapData,
                roam: false,
                breadcrumb: { show: false },
                label: { show: true, formatter: '{b}\n{c}', fontSize: 12 },
                itemStyle: {
                    borderColor: isDark ? '#2a2a2a' : '#fff',
                    borderWidth: 2,
                    gapWidth: 2,
                },
                levels: [{
                    colorSaturation: [0.3, 0.6],
                    itemStyle: { borderColorSaturation: 0.7 },
                }],
            }],
        });
    }

    // Geographic Distribution (Pie)
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
            .slice(0, 15);
        echartInstances.geoDist.setOption({
            tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
            series: [{
                type: 'pie',
                radius: ['35%', '70%'],
                data: geoData,
                label: { formatter: '{b}: {c}', fontSize: 11 },
                emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
            }],
        });
    }
}

function _chartTextColor() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? '#ccc5b9' : '#3D4035';
}

function _chartGridColor() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    return isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
}

function renderChartJsDashboard(companies) {
    if (!window.Chart) return;
    const textColor = _chartTextColor();
    const gridColor = _chartGridColor();

    // Funding Stage (Doughnut)
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
        const colors = ['#bc6c5a', '#5a7c5a', '#6b8fa3', '#d4a853', '#8b6f8b', '#5a8c8c', '#a67c52', '#7c8c5a'];
        if (window._chartFunding) window._chartFunding.destroy();
        window._chartFunding = new Chart(ctx, {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors.slice(0, labels.length) }] },
            options: {
                responsive: true,
                plugins: { legend: { position: 'bottom', labels: { font: { size: 11 }, color: textColor } } },
            },
        });
    }

    // Confidence Histogram (Bar)
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
        if (window._chartConf) window._chartConf.destroy();
        window._chartConf = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: Object.keys(buckets),
                datasets: [{
                    label: 'Companies',
                    data: Object.values(buckets),
                    backgroundColor: ['#dc3545', '#e6a817', '#d4a853', '#5a7c5a', '#2d5a2d'],
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

function renderWordCloud(companies) {
    if (!window.echarts) return;
    const wcDiv = document.getElementById('chartWordCloud');
    if (!wcDiv) return;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const theme = isDark ? 'dark' : null;

    // Collect tags and keywords from companies
    const wordMap = {};
    companies.forEach(c => {
        (c.tags || []).forEach(t => { wordMap[t] = (wordMap[t] || 0) + 3; });
        const cat = c.category_name;
        if (cat) wordMap[cat] = (wordMap[cat] || 0) + 1;
    });

    const wordData = Object.entries(wordMap)
        .map(([name, value]) => ({ name, value }))
        .sort((a, b) => b.value - a.value)
        .slice(0, 60);

    if (!wordData.length) {
        wcDiv.innerHTML = '<p class="hint-text" style="padding:40px;text-align:center">Add tags to companies to see the word cloud</p>';
        return;
    }

    if (echartInstances.wordCloud) echartInstances.wordCloud.dispose();
    echartInstances.wordCloud = echarts.init(wcDiv, theme);
    echartInstances.wordCloud.setOption({
        tooltip: { show: true, formatter: '{b}: {c}' },
        series: [{
            type: 'wordCloud',
            shape: 'circle',
            sizeRange: [14, 48],
            rotationRange: [-30, 30],
            gridSize: 8,
            drawOutOfBound: false,
            textStyle: {
                fontFamily: 'Noto Sans',
                color: function() {
                    const palette = ['#bc6c5a','#5a7c5a','#6b8fa3','#d4a853','#8b6f8b','#5a8c8c','#a67c52'];
                    return palette[Math.floor(Math.random() * palette.length)];
                },
            },
            data: wordData,
        }],
    });
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
    renderWordCloud(companies);
}

// Resize handler for ECharts
window.addEventListener('resize', () => {
    Object.values(echartInstances).forEach(chart => {
        if (chart && chart.resize) chart.resize();
    });
});
