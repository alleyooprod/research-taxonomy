/**
 * Market map (drag-drop tiles), compare companies, geographic map (Leaflet).
 */

let compareSelection = new Set();
let leafletMap = null;
let markerClusterGroup = null;
let _heatLayer = null;
let _geoHeatmapOn = false;

async function loadMarketMap() {
    const [compRes, taxRes] = await Promise.all([
        fetch(`/api/companies?project_id=${currentProjectId}`),
        fetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();

    const topLevel = categories.filter(c => !c.parent_id).sort((a, b) => a.name.localeCompare(b.name));

    const byCategory = {};
    companies.forEach(c => {
        const catId = c.category_id || 0;
        byCategory[catId] = byCategory[catId] || [];
        byCategory[catId].push(c);
    });

    const mapDiv = document.getElementById('marketMap');
    mapDiv.innerHTML = topLevel.map(cat => {
        const catColor = getCategoryColor(cat.id);
        return `
        <div class="map-column"
             ondragover="event.preventDefault();this.classList.add('drag-over')"
             ondragleave="this.classList.remove('drag-over')"
             ondrop="handleMapDrop(event, ${cat.id})"
             data-category-id="${cat.id}"
             style="${catColor ? `border-top: 3px solid ${catColor}` : ''}">
            <div class="map-column-header"><span class="cat-color-dot" style="background:${catColor || 'transparent'}"></span> ${esc(cat.name)} <span class="count">(${(byCategory[cat.id] || []).length})</span></div>
            <div class="map-tiles">
                ${(byCategory[cat.id] || []).sort((a,b) => a.name.localeCompare(b.name)).map(c => `
                    <div class="map-tile ${compareSelection.has(c.id) ? 'tile-selected' : ''}"
                         draggable="true"
                         ondragstart="event.dataTransfer.setData('text/plain', '${c.id}')"
                         onclick="toggleCompareSelect(${c.id}, this)"
                         title="${esc(c.what || '')}">
                        <img class="map-tile-logo" src="${c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`}" alt="" onerror="this.style.display='none'">
                        <span class="map-tile-name">${esc(c.name)}</span>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }).join('');

    updateCompareBar();
    setTimeout(initMapPanzoom, 100);
}

async function handleMapDrop(event, targetCategoryId) {
    event.preventDefault();
    event.currentTarget.classList.remove('drag-over');
    const companyId = event.dataTransfer.getData('text/plain');
    if (!companyId) return;

    await safeFetch(`/api/companies/${companyId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: targetCategoryId, project_id: currentProjectId }),
    });

    loadMarketMap();
    loadTaxonomy();
}

function toggleCompareSelect(id, el) {
    if (compareSelection.has(id)) {
        compareSelection.delete(id);
        el.classList.remove('tile-selected');
    } else if (compareSelection.size < 4) {
        compareSelection.add(id);
        el.classList.add('tile-selected');
    } else {
        showToast('Maximum 4 companies for comparison. Deselect one first.');
    }
    updateCompareBar();
}

function updateCompareBar() {
    const bar = document.getElementById('compareBar');
    if (compareSelection.size > 0) {
        bar.classList.remove('hidden');
        document.getElementById('compareCount').textContent = `${compareSelection.size} selected`;
    } else {
        bar.classList.add('hidden');
    }
}

function clearCompareSelection() {
    compareSelection.clear();
    document.querySelectorAll('.map-tile.tile-selected').forEach(el => el.classList.remove('tile-selected'));
    updateCompareBar();
}

async function runComparison() {
    if (compareSelection.size < 2) { showToast('Select at least 2 companies'); return; }
    const ids = Array.from(compareSelection).join(',');
    const res = await safeFetch(`/api/companies/compare?ids=${ids}`);
    const companies = await res.json();

    const fields = ['what', 'target', 'products', 'funding', 'geography',
        'employee_range', 'founded_year', 'funding_stage', 'total_funding_usd',
        'hq_city', 'hq_country', 'tam'];

    let html = '<table class="compare-table"><thead><tr><th>Field</th>';
    companies.forEach(c => { html += `<th>${esc(c.name)}</th>`; });
    html += '</tr></thead><tbody>';

    const labels = {
        what: 'What', target: 'Target', products: 'Products', funding: 'Funding',
        geography: 'Geography', employee_range: 'Employees', founded_year: 'Founded',
        funding_stage: 'Stage', total_funding_usd: 'Total Raised',
        hq_city: 'HQ City', hq_country: 'HQ Country', tam: 'TAM',
    };

    fields.forEach(f => {
        html += `<tr><td><strong>${labels[f] || f}</strong></td>`;
        companies.forEach(c => {
            let val = c[f];
            if (f === 'total_funding_usd' && val) val = typeof formatCurrency === 'function' ? formatCurrency(val) : '$' + Number(val).toLocaleString();
            html += `<td>${esc(String(val || 'N/A'))}</td>`;
        });
        html += '</tr>';
    });

    html += '<tr><td><strong>Tags</strong></td>';
    companies.forEach(c => { html += `<td>${(c.tags || []).join(', ') || 'None'}</td>`; });
    html += '</tr>';

    html += '</tbody></table>';

    document.getElementById('compareContent').innerHTML = html;
    document.getElementById('compareSection').classList.remove('hidden');
    document.getElementById('compareSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function clearComparison() {
    document.getElementById('compareSection').classList.add('hidden');
    clearCompareSelection();
}

async function exportMapPng() {
    if (typeof html2canvas === 'undefined') {
        showToast('html2canvas is still loading. Please try again in a moment.');
        return;
    }
    const mapEl = document.getElementById('marketMap');
    const canvas = await html2canvas(mapEl, { backgroundColor: getComputedStyle(document.documentElement).getPropertyValue('--bg-container').trim() });
    const link = document.createElement('a');
    link.download = 'market-map.png';
    link.href = canvas.toDataURL();
    link.click();
}

// --- Geographic Map (Leaflet) ---
const GEO_COORDS = {
    'US': [39.8, -98.5], 'USA': [39.8, -98.5], 'United States': [39.8, -98.5],
    'UK': [54.0, -2.0], 'United Kingdom': [54.0, -2.0], 'GB': [54.0, -2.0],
    'Canada': [56.1, -106.3], 'Germany': [51.2, 10.5], 'France': [46.6, 2.2],
    'Israel': [31.0, 34.8], 'India': [20.6, 78.9], 'Australia': [-25.3, 133.8],
    'Singapore': [1.35, 103.8], 'Japan': [36.2, 138.3], 'China': [35.9, 104.2],
    'Brazil': [-14.2, -51.9], 'South Korea': [35.9, 127.8], 'Netherlands': [52.1, 5.3],
    'Sweden': [60.1, 18.6], 'Switzerland': [46.8, 8.2], 'Spain': [40.5, -3.7],
    'Italy': [41.9, 12.6], 'Ireland': [53.4, -8.2], 'Mexico': [23.6, -102.5],
    'New York': [40.7, -74.0], 'San Francisco': [37.8, -122.4], 'London': [51.5, -0.1],
    'Boston': [42.4, -71.1], 'Los Angeles': [34.1, -118.2], 'Chicago': [41.9, -87.6],
    'Austin': [30.3, -97.7], 'Seattle': [47.6, -122.3], 'Denver': [39.7, -105.0],
    'Toronto': [43.7, -79.4], 'Berlin': [52.5, 13.4], 'Paris': [48.9, 2.3],
    'Tel Aviv': [32.1, 34.8], 'Mumbai': [19.1, 72.9], 'Bangalore': [12.97, 77.6],
    'Sydney': [-33.9, 151.2], 'Tokyo': [35.7, 139.7], 'Shanghai': [31.2, 121.5],
};

function getCoords(company) {
    const city = company.hq_city || '';
    const country = company.hq_country || company.geography || '';
    if (city && GEO_COORDS[city]) return GEO_COORDS[city];
    if (country && GEO_COORDS[country]) return GEO_COORDS[country];
    const firstWord = (country || '').split(',')[0].trim();
    if (GEO_COORDS[firstWord]) return GEO_COORDS[firstWord];
    return null;
}

async function renderGeoMap() {
    const container = document.getElementById('geoMap');
    if (!container) return;
    if (!window.L) {
        _waitForLib('map library', () => window.L, () => renderGeoMap(), container);
        return;
    }

    if (!leafletMap) {
        leafletMap = L.map('geoMap').setView([30, 0], 2);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 18,
        }).addTo(leafletMap);
    }

    if (markerClusterGroup) leafletMap.removeLayer(markerClusterGroup);
    markerClusterGroup = L.markerClusterGroup ? L.markerClusterGroup() : L.layerGroup();

    const res = await safeFetch(`/api/companies?project_id=${currentProjectId}`);
    const companies = await res.json();

    const fallbackPalette = ['#bc6c5a','#5a7c5a','#6b8fa3','#d4a853','#8b6f8b','#5a8c8c','#a67c52','#7c8c5a','#c4786e','#4a6a4a'];
    let colorIdx = 0;
    const catColorsFallback = {};

    companies.forEach(c => {
        const coords = getCoords(c);
        if (!coords) return;
        const cat = c.category_name || 'Unknown';
        // Prefer saved category color, fall back to palette
        let color = getCategoryColor(c.category_id);
        if (!color) {
            if (!catColorsFallback[cat]) catColorsFallback[cat] = fallbackPalette[colorIdx++ % fallbackPalette.length];
            color = catColorsFallback[cat];
        }

        const icon = L.divIcon({
            html: `<div style="background:${color};width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.3)"></div>`,
            className: 'geo-marker-icon',
            iconSize: [16, 16],
        });
        const marker = L.marker([coords[0] + (Math.random()-0.5)*0.5, coords[1] + (Math.random()-0.5)*0.5], { icon });
        marker.bindPopup(`<strong>${esc(c.name)}</strong><br>${esc(cat)}<br>${esc(c.geography || '')}`);
        markerClusterGroup.addLayer(marker);
    });

    leafletMap.addLayer(markerClusterGroup);

    // Build heatmap layer from company coordinates
    if (window.L && L.heatLayer) {
        if (_heatLayer) leafletMap.removeLayer(_heatLayer);
        const heatPoints = [];
        companies.forEach(c => {
            const coords = getCoords(c);
            if (coords) heatPoints.push([coords[0], coords[1], 0.6]);
        });
        _heatLayer = L.heatLayer(heatPoints, {
            radius: 30, blur: 20, maxZoom: 10,
            gradient: { 0.2: '#2b83ba', 0.4: '#abdda4', 0.6: '#ffffbf', 0.8: '#fdae61', 1.0: '#d7191c' },
        });
        if (_geoHeatmapOn) _heatLayer.addTo(leafletMap);
    }

    setTimeout(() => leafletMap.invalidateSize(), 100);
}

function toggleGeoHeatmap() {
    if (!_heatLayer || !leafletMap) return;
    _geoHeatmapOn = !_geoHeatmapOn;
    if (_geoHeatmapOn) {
        _heatLayer.addTo(leafletMap);
    } else {
        leafletMap.removeLayer(_heatLayer);
    }
    const btn = document.getElementById('heatmapToggleBtn');
    if (btn) btn.classList.toggle('active', _geoHeatmapOn);
}

function switchMapView(view) {
    document.getElementById('marketMap').classList.add('hidden');
    document.getElementById('autoLayoutMap').classList.add('hidden');
    document.getElementById('geoMap').classList.add('hidden');
    document.getElementById('marketMapBtn').classList.remove('active');
    document.getElementById('autoMapBtn').classList.remove('active');
    document.getElementById('geoMapBtn').classList.remove('active');

    if (view === 'market') {
        document.getElementById('marketMap').classList.remove('hidden');
        document.getElementById('marketMapBtn').classList.add('active');
    } else if (view === 'auto') {
        document.getElementById('autoLayoutMap').classList.remove('hidden');
        document.getElementById('autoMapBtn').classList.add('active');
        renderAutoLayoutMap();
    } else {
        document.getElementById('geoMap').classList.remove('hidden');
        document.getElementById('geoMapBtn').classList.add('active');
        renderGeoMap();
    }
}

// --- Auto-Layout Market Map (structured grid) ---
let _autoLayoutCy = null;

async function renderAutoLayoutMap() {
    const container = document.getElementById('autoLayoutMap');
    if (!container) return;
    if (!window.cytoscape) {
        _waitForLib('graph library', () => window.cytoscape, () => renderAutoLayoutMap(), container);
        return;
    }

    const [compRes, taxRes] = await Promise.all([
        safeFetch(`/api/companies?project_id=${currentProjectId}`),
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();
    const topLevel = categories.filter(c => !c.parent_id)
        .sort((a, b) => (b.company_count || 0) - (a.company_count || 0));
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    if (!topLevel.length) {
        container.innerHTML = '<div class="graph-loading"><p>No categories to display. Add categories first.</p></div>';
        return;
    }

    // Group companies by category
    const byCategory = {};
    companies.forEach(c => {
        if (!c.category_id) return;
        if (!byCategory[c.category_id]) byCategory[c.category_id] = [];
        byCategory[c.category_id].push(c);
    });

    // Grid layout: structured placement of categories and companies
    const COLS = Math.min(4, topLevel.length);
    const NODE_SIZE = 32;
    const NODE_GAP = 10;
    const CAT_PADDING_X = 30;
    const CAT_PADDING_TOP = 40;
    const CAT_PADDING_BOTTOM = 20;
    const GRID_GAP = 50;

    const elements = [];
    let maxRowHeight = [];  // track height per row for vertical positioning

    // First pass: calculate cell dimensions
    const cellDims = topLevel.map(cat => {
        const catCompanies = byCategory[cat.id] || [];
        const innerCols = Math.max(2, Math.min(6, Math.ceil(Math.sqrt(catCompanies.length))));
        const innerRows = Math.ceil(catCompanies.length / innerCols);
        const cellW = Math.max(180, innerCols * (NODE_SIZE + NODE_GAP) + CAT_PADDING_X * 2);
        const cellH = Math.max(100, innerRows * (NODE_SIZE + NODE_GAP) + CAT_PADDING_TOP + CAT_PADDING_BOTTOM);
        return { cat, companies: catCompanies, innerCols, cellW, cellH };
    });

    // Calculate column widths and row heights
    const colWidths = [];
    const rowHeights = [];
    for (let i = 0; i < cellDims.length; i++) {
        const col = i % COLS;
        const row = Math.floor(i / COLS);
        colWidths[col] = Math.max(colWidths[col] || 0, cellDims[i].cellW);
        rowHeights[row] = Math.max(rowHeights[row] || 0, cellDims[i].cellH);
    }

    // Second pass: place elements with calculated positions
    cellDims.forEach((cell, idx) => {
        const col = idx % COLS;
        const row = Math.floor(idx / COLS);

        // Calculate absolute X/Y for this cell's center
        let cx = 0;
        for (let c = 0; c < col; c++) cx += colWidths[c] + GRID_GAP;
        cx += colWidths[col] / 2;

        let cy = 0;
        for (let r = 0; r < row; r++) cy += rowHeights[r] + GRID_GAP;
        cy += rowHeights[row] / 2;

        const color = getCategoryColor(cell.cat.id) || '#999';
        const companyCount = cell.companies.length;

        // Category parent node
        elements.push({
            group: 'nodes',
            data: {
                id: 'cat-' + cell.cat.id,
                label: cell.cat.name + (companyCount ? ` (${companyCount})` : ''),
                type: 'category',
                color: color,
            },
            position: { x: cx, y: cy },
        });

        // Company child nodes arranged in mini-grid inside category
        const sorted = cell.companies.sort((a, b) => a.name.localeCompare(b.name));
        const startX = cx - (cell.innerCols * (NODE_SIZE + NODE_GAP) - NODE_GAP) / 2 + NODE_SIZE / 2;
        const startY = cy - (rowHeights[row] - CAT_PADDING_TOP - CAT_PADDING_BOTTOM) / 2 + NODE_SIZE / 2;

        sorted.forEach((c, i) => {
            const ic = i % cell.innerCols;
            const ir = Math.floor(i / cell.innerCols);
            elements.push({
                group: 'nodes',
                data: {
                    id: 'co-' + c.id,
                    label: c.name,
                    parent: 'cat-' + cell.cat.id,
                    type: 'company',
                    color: color,
                    companyId: c.id,
                },
                position: {
                    x: startX + ic * (NODE_SIZE + NODE_GAP),
                    y: startY + ir * (NODE_SIZE + NODE_GAP),
                },
            });
        });
    });

    if (_autoLayoutCy) _autoLayoutCy.destroy();

    _autoLayoutCy = cytoscape({
        container: container,
        elements: elements,
        style: [
            {
                selector: 'node[type="category"]',
                style: {
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'center',
                    'font-size': '13px',
                    'font-weight': '600',
                    'color': isDark ? '#e0ddd5' : '#3D4035',
                    'background-color': 'data(color)',
                    'background-opacity': 0.06,
                    'border-width': 2,
                    'border-color': 'data(color)',
                    'border-opacity': 0.35,
                    'padding': '25px',
                    'shape': 'round-rectangle',
                    'text-margin-y': -10,
                },
            },
            {
                selector: 'node[type="company"]',
                style: {
                    'label': 'data(label)',
                    'background-color': 'data(color)',
                    'background-opacity': 0.18,
                    'color': isDark ? '#bbb' : '#555',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'font-size': '9px',
                    'width': NODE_SIZE,
                    'height': NODE_SIZE,
                    'border-width': 1.5,
                    'border-color': 'data(color)',
                    'text-wrap': 'ellipsis',
                    'text-max-width': '55px',
                },
            },
            {
                selector: 'node[type="company"]:active',
                style: {
                    'overlay-color': '#bc6c5a',
                    'overlay-opacity': 0.15,
                },
            },
        ],
        layout: { name: 'preset' },
        wheelSensitivity: 0.3,
    });

    // Fit to view with some padding
    _autoLayoutCy.fit(undefined, 40);

    // Click company node to open detail
    _autoLayoutCy.on('tap', 'node[type="company"]', (e) => {
        const companyId = e.target.data('companyId');
        if (companyId) navigateTo('company', companyId, e.target.data('label'));
    });
}
