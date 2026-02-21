/**
 * Analysis Lenses — analysis views that activate based on available data.
 * Phase 3 of the Research Workbench.
 *
 * Provides multiple analytical perspectives on entity data:
 * - Competitive: Feature matrix, gap analysis, positioning map
 * - Design: Evidence gallery, screenshot journey map
 * - Temporal: Snapshot timeline, side-by-side comparison
 * - Product: Pricing landscape, plan comparison grid
 */

// ── Lenses State ────────────────────────────────────────────

let _lensesData = [];              // Available lenses from API
let _activeLens = null;            // Currently loaded lens id
let _lensEntityFilter = null;      // Selected entity_id for entity-scoped lenses
let _lensSubView = null;           // Active sub-view within a lens
let _lensExpandedImage = null;     // Currently expanded gallery image

// ── Init ─────────────────────────────────────────────────────

/**
 * Initialize the Analysis tab — called when the Analysis tab is shown.
 */
async function initLenses() {
    if (!currentProjectId) return;
    await _loadAvailableLenses();
}

// ── Available Lenses ─────────────────────────────────────────

async function _loadAvailableLenses() {
    try {
        const resp = await fetch(`/api/lenses/available?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            _renderLensError('Failed to load analysis lenses.');
            return;
        }
        _lensesData = await resp.json();
        _renderLensSelector(_lensesData);
    } catch (e) {
        console.warn('Failed to load lenses:', e);
        _renderLensError('Unable to reach lenses endpoint.');
    }
}

// ── Lens Selector ─────────────────────────────────────────────

/**
 * Render the horizontal lens selector bar.
 * Available lenses are clickable; unavailable show a hint and are greyed out.
 */
function _renderLensSelector(lenses) {
    const bar = document.getElementById('lensSelector');
    const content = document.getElementById('lensContent');
    if (!bar) return;

    if (!lenses || lenses.length === 0) {
        bar.innerHTML = '';
        if (content) content.innerHTML = _lensEmptyState(
            'No Lenses Available',
            'Add entities with attributes to unlock analysis lenses.'
        );
        return;
    }

    bar.innerHTML = lenses.map(lens => {
        const available = lens.available !== false;
        const count = lens.entity_count != null ? lens.entity_count : 0;
        const hint = lens.hint || 'Requires more data';

        return `
            <div class="lens-card ${available ? 'lens-card-available' : 'lens-card-unavailable'} ${_activeLens === lens.id ? 'lens-card-active' : ''}"
                 ${available ? `data-action="select-lens" data-value="${esc(lens.id)}"` : ''}
                 title="${available ? esc(lens.name) : esc(hint)}">
                <div class="lens-card-name">${esc(lens.name)}</div>
                <div class="lens-card-count">
                    ${available
                        ? `<span class="lens-card-count-value">${count}</span> ${count === 1 ? 'entity' : 'entities'}`
                        : `<span class="lens-card-hint">${esc(hint)}</span>`
                    }
                </div>
            </div>
        `;
    }).join('');

    // If a lens was already active, re-render its content after selector refresh
    if (_activeLens) {
        const active = lenses.find(l => l.id === _activeLens);
        if (!active || active.available === false) {
            _activeLens = null;
            if (content) content.innerHTML = '';
        }
    }
}

function _selectLens(lensId) {
    _activeLens = lensId;
    _lensSubView = null;
    _lensEntityFilter = null;

    // Re-render selector to update active state
    _renderLensSelector(_lensesData);

    switch (lensId) {
        case 'competitive': _loadCompetitiveLens(); break;
        case 'design':      _loadDesignLens();      break;
        case 'temporal':    _loadTemporalLens();     break;
        case 'product':     _loadProductLens();      break;
        case 'signals':     _loadSignalsLens();      break;
        default:
            _renderLensError(`Unknown lens: ${lensId}`);
    }
}

// ── Competitive Lens ─────────────────────────────────────────

/**
 * Load the Competitive lens — three sub-views: Feature Matrix, Gap Analysis,
 * Positioning Map.
 */
async function _loadCompetitiveLens() {
    const content = document.getElementById('lensContent');
    if (!content) return;

    content.innerHTML = `
        <div class="lens-subview-bar" id="competitiveSubBar">
            <button class="lens-subview-btn lens-subview-btn-active"
                    data-action="switch-competitive-view" data-value="matrix">Feature Matrix</button>
            <button class="lens-subview-btn"
                    data-action="switch-competitive-view" data-value="gap">Gap Analysis</button>
            <button class="lens-subview-btn"
                    data-action="switch-competitive-view" data-value="positioning">Positioning</button>
            <button class="lens-subview-btn"
                    data-action="switch-competitive-view" data-value="market_map">Market Map</button>
        </div>
        <div id="competitiveSubContent" class="lens-sub-content">
            <div class="lens-loading">Loading feature matrix&hellip;</div>
        </div>
    `;

    _lensSubView = 'matrix';
    await _loadFeatureMatrixData();
}

function _switchCompetitiveSubView(view) {
    _lensSubView = view;

    // Update button states
    const bar = document.getElementById('competitiveSubBar');
    if (bar) {
        bar.querySelectorAll('.lens-subview-btn').forEach(btn => {
            btn.classList.remove('lens-subview-btn-active');
        });
        const idx = { matrix: 0, gap: 1, positioning: 2, market_map: 3 }[view];
        const btns = bar.querySelectorAll('.lens-subview-btn');
        if (btns[idx]) btns[idx].classList.add('lens-subview-btn-active');
    }

    switch (view) {
        case 'matrix':      _loadFeatureMatrixData();   break;
        case 'gap':         _loadGapAnalysisData();     break;
        case 'positioning': _loadPositioningData();     break;
        case 'market_map':  _loadMarketMapData();       break;
    }
}

async function _loadFeatureMatrixData() {
    const sub = document.getElementById('competitiveSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading feature matrix&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/competitive/matrix?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Data', 'No feature matrix data available.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderFeatureMatrix(data);
    } catch (e) {
        console.warn('Feature matrix load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load feature matrix.');
    }
}

async function _loadGapAnalysisData() {
    const sub = document.getElementById('competitiveSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading gap analysis&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/competitive/gaps?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Data', 'No gap analysis data available.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderGapAnalysis(data);
    } catch (e) {
        console.warn('Gap analysis load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load gap analysis.');
    }
}

async function _loadPositioningData() {
    const sub = document.getElementById('competitiveSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading positioning map&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/competitive/positioning?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Data', 'No positioning data available.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderPositioningMap(data);
    } catch (e) {
        console.warn('Positioning load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load positioning map.');
    }
}

/**
 * Render the feature matrix table.
 * Rows = features/attributes, Columns = entities.
 * Boolean values show a checkmark; missing values are highlighted as gaps.
 */
function _renderFeatureMatrix(data) {
    // data = { entities: [{id, name}], features: [{slug, label, values: {entity_id: value}}] }
    const entities = data.entities || [];
    const features = data.features || [];

    if (!entities.length || !features.length) {
        return _lensEmptyState('No Matrix Data', 'Entities need attributes to build a feature matrix.');
    }

    const headerCells = entities.map(e =>
        `<th class="matrix-col-header" title="${escAttr(e.name)}">${esc(_truncateLabel(e.name, 16))}</th>`
    ).join('');

    const rows = features.map((feat, rowIdx) => {
        const cells = entities.map(e => {
            const val = feat.values ? feat.values[e.id] : undefined;
            const isGap = val === undefined || val === null || val === '';
            const display = _matrixCellDisplay(val);
            return `<td class="matrix-cell ${isGap ? 'matrix-cell-gap' : 'matrix-cell-filled'}" title="${escAttr(isGap ? 'No data' : String(val))}">${display}</td>`;
        }).join('');

        return `
            <tr class="${rowIdx % 2 === 0 ? 'matrix-row-even' : 'matrix-row-odd'}">
                <th class="matrix-row-header" title="${escAttr(feat.label || feat.slug)}">${esc(feat.label || feat.slug)}</th>
                ${cells}
            </tr>
        `;
    }).join('');

    const gapCount = features.reduce((total, feat) => {
        return total + entities.filter(e => {
            const val = feat.values ? feat.values[e.id] : undefined;
            return val === undefined || val === null || val === '';
        }).length;
    }, 0);
    const totalCells = features.length * entities.length;
    const coveragePct = totalCells > 0 ? Math.round(((totalCells - gapCount) / totalCells) * 100) : 0;

    const toggleHtml = _renderEnrichedToggle(false);

    return `
        ${toggleHtml}
        <div class="matrix-meta">
            <span class="matrix-meta-stat">${entities.length} entities</span>
            <span class="matrix-meta-sep">/</span>
            <span class="matrix-meta-stat">${features.length} features</span>
            <span class="matrix-meta-sep">/</span>
            <span class="matrix-meta-stat matrix-coverage">${coveragePct}% coverage</span>
        </div>
        <div class="matrix-scroll-wrap">
            <table class="matrix-table">
                <thead>
                    <tr>
                        <th class="matrix-origin-cell"></th>
                        ${headerCells}
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>
        <div class="matrix-legend">
            <span class="matrix-legend-item matrix-legend-filled">Filled</span>
            <span class="matrix-legend-item matrix-legend-gap">Gap</span>
        </div>
    `;
}

function _matrixCellDisplay(val) {
    if (val === undefined || val === null || val === '') return '<span class="matrix-gap-marker">—</span>';
    if (val === true || val === 'true' || val === 1 || val === '1') return '<span class="matrix-check">&#10003;</span>';
    if (val === false || val === 'false' || val === 0 || val === '0') return '<span class="matrix-cross">&#215;</span>';
    const str = String(val);
    return `<span class="matrix-value">${esc(_truncateLabel(str, 12))}</span>`;
}

/**
 * Render the gap analysis list.
 * Features sorted by coverage ascending (lowest coverage first).
 * Horizontal bars show fill percentage; red for low, green for high.
 */
function _renderGapAnalysis(data) {
    // data = { features: [{slug, label, coverage_pct, filled, total}] }
    const features = (data.features || []).slice().sort((a, b) => a.coverage_pct - b.coverage_pct);

    if (!features.length) {
        return _lensEmptyState('No Gap Data', 'No attribute data to analyse for gaps.');
    }

    const rows = features.map(feat => {
        const pct = Math.round(feat.coverage_pct || 0);
        let barClass = 'gap-bar-low';
        if (pct >= 70) barClass = 'gap-bar-high';
        else if (pct >= 40) barClass = 'gap-bar-medium';

        return `
            <div class="gap-row">
                <div class="gap-label" title="${escAttr(feat.label || feat.slug)}">${esc(feat.label || feat.slug)}</div>
                <div class="gap-bar-wrap">
                    <div class="gap-bar ${barClass}" style="width: ${pct}%"></div>
                </div>
                <div class="gap-pct">${pct}%</div>
                <div class="gap-counts">${feat.filled || 0} / ${feat.total || 0}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="gap-header-row">
            <span class="gap-header-label">Feature</span>
            <span class="gap-header-bar">Coverage</span>
            <span class="gap-header-pct">%</span>
            <span class="gap-header-counts">Filled / Total</span>
        </div>
        <div class="gap-list">
            ${rows}
        </div>
        <div class="gap-legend">
            <span class="gap-legend-item gap-bar-low">Low (&lt;40%)</span>
            <span class="gap-legend-item gap-bar-medium">Medium (40–69%)</span>
            <span class="gap-legend-item gap-bar-high">High (&ge;70%)</span>
        </div>
    `;
}

/**
 * Render a simple 2D positioning grid.
 * Each entity is placed at an x/y coordinate with a dot and label.
 * Axes are labelled from the data.
 */
function _renderPositioningMap(data) {
    // data = { x_axis: {label, attr_slug}, y_axis: {label, attr_slug}, entities: [{id, name, x, y}] }
    const entities = data.entities || [];
    const xLabel = (data.x_axis || {}).label || 'X Axis';
    const yLabel = (data.y_axis || {}).label || 'Y Axis';

    if (!entities.length) {
        return _lensEmptyState('No Positioning Data', 'Entities need numeric attributes on two dimensions to plot.');
    }

    // Normalise coordinates to 0–100 range
    const xs = entities.map(e => e.x || 0);
    const ys = entities.map(e => e.y || 0);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;

    const dots = entities.map(e => {
        const px = ((e.x - minX) / rangeX) * 90 + 5;  // 5–95% margin
        const py = 95 - ((e.y - minY) / rangeY) * 90;  // invert Y (top=high)
        return `
            <div class="pos-dot-wrap" style="left: ${px.toFixed(1)}%; top: ${py.toFixed(1)}%" title="${escAttr(e.name)}">
                <div class="pos-dot"></div>
                <span class="pos-dot-label">${esc(_truncateLabel(e.name, 14))}</span>
            </div>
        `;
    }).join('');

    return `
        <div class="pos-wrap">
            <div class="pos-y-label">${esc(yLabel)}</div>
            <div class="pos-grid-wrap">
                <div class="pos-grid">
                    ${dots}
                    <div class="pos-grid-lines">
                        <div class="pos-grid-h"></div>
                        <div class="pos-grid-v"></div>
                    </div>
                </div>
                <div class="pos-x-label">${esc(xLabel)}</div>
            </div>
        </div>
        <div class="pos-entity-count">${entities.length} entities plotted</div>
    `;
}

// ── Competitive Lens: Market Map ─────────────────────────────

async function _loadMarketMapData() {
    const sub = document.getElementById('competitiveSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading market map&hellip;</div>';

    try {
        const resp = await fetch(
            `/api/lenses/competitive/market-map?project_id=${currentProjectId}`,
            { headers: { 'X-CSRFToken': CSRF_TOKEN } }
        );
        if (!resp.ok) {
            sub.innerHTML = _lensEmptyState('No Data', 'Market map unavailable. Enrich entities with financial data first.');
            return;
        }
        const data = await resp.json();
        sub.innerHTML = _renderMarketMap(data);
    } catch (e) {
        console.warn('Market map load failed:', e);
        sub.innerHTML = _lensEmptyState('Market Map Unavailable', 'Enrich entities with financial data first.');
    }
}

function _renderMarketMap(data) {
    const entities = data.entities || [];
    const xLabel = data.x_label || 'X Axis';
    const yLabel = data.y_label || 'Y Axis';
    const sizeLabel = data.size_label || 'Size';

    if (!entities.length) {
        return _lensEmptyState('No Financial Data', 'Enrich entities with financial data to generate a market map.');
    }

    const width = 600;
    const height = 400;
    const padding = 50;

    // Extract raw values
    const xVals = entities.map(e => e.x_value || 0);
    const yVals = entities.map(e => e.y_value || 0);
    const sizeVals = entities.map(e => e.size_value || 1);

    // Compute ranges
    const minX = Math.min(...xVals), maxX = Math.max(...xVals);
    const minY = Math.min(...yVals), maxY = Math.max(...yVals);
    const minS = Math.min(...sizeVals), maxS = Math.max(...sizeVals);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;
    const rangeS = maxS - minS || 1;

    // Map entities to SVG circles
    const circles = entities.map(e => {
        const cx = padding + ((e.x_value || 0) - minX) / rangeX * (width - padding * 2);
        const cy = padding + (1 - ((e.y_value || 0) - minY) / rangeY) * (height - padding * 2);
        const r = 8 + ((e.size_value || 0) - minS) / rangeS * 24;
        const name = _truncateLabel(e.name || '', 14);

        return `
            <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${r.toFixed(1)}"
                    class="market-map-dot" />
            <text x="${cx.toFixed(1)}" y="${(cy + r + 14).toFixed(1)}"
                  class="market-map-label" text-anchor="middle">${esc(name)}</text>
        `;
    }).join('');

    // Axis lines
    const axisLines = `
        <line x1="${padding}" y1="${height - padding}" x2="${width - padding}" y2="${height - padding}" class="market-map-axis" />
        <line x1="${padding}" y1="${padding}" x2="${padding}" y2="${height - padding}" class="market-map-axis" />
    `;

    // Axis labels
    const axisLabels = `
        <text x="${width / 2}" y="${height - 8}" class="market-map-axis-label" text-anchor="middle">${esc(xLabel)}</text>
        <text x="14" y="${height / 2}" class="market-map-axis-label" text-anchor="middle" transform="rotate(-90, 14, ${height / 2})">${esc(yLabel)}</text>
    `;

    const svg = `
        <svg width="${width}" height="${height}" class="market-map-svg" viewBox="0 0 ${width} ${height}">
            ${axisLines}
            ${axisLabels}
            ${circles}
        </svg>
    `;

    return `
        <div class="market-map-meta">
            <span class="matrix-meta-stat">${entities.length} entities</span>
            <span class="matrix-meta-sep">/</span>
            <span class="matrix-meta-stat">Size: ${esc(sizeLabel)}</span>
        </div>
        <div class="market-map-container">${svg}</div>
    `;
}

// ── Competitive Lens: Enriched Matrix ────────────────────────

let _enrichedMatrixEnabled = false;

async function _loadEnrichedMatrixData() {
    const sub = document.getElementById('competitiveSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading enriched matrix&hellip;</div>';

    try {
        const resp = await fetch(
            `/api/lenses/competitive/enriched-matrix?project_id=${currentProjectId}`,
            { headers: { 'X-CSRFToken': CSRF_TOKEN } }
        );
        if (!resp.ok) {
            sub.innerHTML = _lensEmptyState('No Enriched Data', 'No financial data available for enriched matrix.');
            return;
        }
        const data = await resp.json();
        sub.innerHTML = _renderEnrichedMatrix(data);
    } catch (e) {
        console.warn('Enriched matrix load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load enriched matrix.');
    }
}

function _renderEnrichedMatrix(data) {
    const entities = data.entities || [];
    const features = data.features || [];
    const financialColumns = data.financial_columns || [];

    if (!entities.length || (!features.length && !financialColumns.length)) {
        return _lensEmptyState('No Enriched Data', 'Entities need attributes and financial data for an enriched matrix.');
    }

    // Entity header cells
    const headerCells = entities.map(e =>
        `<th class="matrix-col-header" title="${escAttr(e.name)}">${esc(_truncateLabel(e.name, 16))}</th>`
    ).join('');

    // Feature rows (same as standard matrix)
    const featureRows = features.map((feat, rowIdx) => {
        const cells = entities.map(e => {
            const val = feat.values ? feat.values[e.id] : undefined;
            const isGap = val === undefined || val === null || val === '';
            const display = _matrixCellDisplay(val);
            return `<td class="matrix-cell ${isGap ? 'matrix-cell-gap' : 'matrix-cell-filled'}" title="${escAttr(isGap ? 'No data' : String(val))}">${display}</td>`;
        }).join('');

        return `
            <tr class="${rowIdx % 2 === 0 ? 'matrix-row-even' : 'matrix-row-odd'}">
                <th class="matrix-row-header" title="${escAttr(feat.label || feat.slug)}">${esc(feat.label || feat.slug)}</th>
                ${cells}
            </tr>
        `;
    }).join('');

    // Financial rows (visually distinct)
    const financialRows = financialColumns.map((col, rowIdx) => {
        const cells = entities.map(e => {
            const financials = e.financials || {};
            const val = financials[col.key];
            const isGap = val === undefined || val === null || val === '';
            const display = isGap ? '<span class="matrix-gap-marker">\u2014</span>' : `<span class="matrix-value">${esc(_truncateLabel(String(val), 12))}</span>`;
            return `<td class="matrix-cell matrix-cell-financial ${isGap ? 'matrix-cell-gap' : 'matrix-cell-filled'}" title="${escAttr(isGap ? 'No data' : String(val))}">${display}</td>`;
        }).join('');

        return `
            <tr class="matrix-row-financial ${rowIdx % 2 === 0 ? 'matrix-row-even' : 'matrix-row-odd'}">
                <th class="matrix-row-header matrix-row-header-financial" title="${escAttr(col.label)}">${esc(col.label)}</th>
                ${cells}
            </tr>
        `;
    }).join('');

    // Separator row between features and financials
    const separatorRow = financialColumns.length && features.length
        ? `<tr class="matrix-separator-row"><td colspan="${entities.length + 1}" class="matrix-separator-cell"><span class="matrix-separator-label">Financial Data</span></td></tr>`
        : '';

    const toggleHtml = _renderEnrichedToggle(true);

    return `
        ${toggleHtml}
        <div class="matrix-meta">
            <span class="matrix-meta-stat">${entities.length} entities</span>
            <span class="matrix-meta-sep">/</span>
            <span class="matrix-meta-stat">${features.length} features</span>
            <span class="matrix-meta-sep">/</span>
            <span class="matrix-meta-stat">${financialColumns.length} financial fields</span>
        </div>
        <div class="matrix-scroll-wrap">
            <table class="matrix-table">
                <thead>
                    <tr>
                        <th class="matrix-origin-cell"></th>
                        ${headerCells}
                    </tr>
                </thead>
                <tbody>
                    ${featureRows}
                    ${separatorRow}
                    ${financialRows}
                </tbody>
            </table>
        </div>
        <div class="matrix-legend">
            <span class="matrix-legend-item matrix-legend-filled">Filled</span>
            <span class="matrix-legend-item matrix-legend-gap">Gap</span>
            <span class="matrix-legend-item matrix-legend-financial">Financial</span>
        </div>
    `;
}

function _renderEnrichedToggle(active) {
    return `
        <div class="matrix-enriched-toggle">
            <label class="matrix-toggle-label">
                <input type="checkbox" ${active ? 'checked' : ''}
                       data-on-change="toggle-enriched-matrix" />
                <span>Show financial data</span>
            </label>
        </div>
    `;
}

function _toggleEnrichedMatrix(enabled) {
    _enrichedMatrixEnabled = enabled;
    if (enabled) {
        _loadEnrichedMatrixData();
    } else {
        _loadFeatureMatrixData();
    }
}

// ── Design Lens ──────────────────────────────────────────────

/**
 * Load the Design lens — entity selector + screenshot gallery grouped by
 * evidence type, with optional journey map view if screenshots are classified.
 */
async function _loadDesignLens() {
    const content = document.getElementById('lensContent');
    if (!content) return;

    content.innerHTML = `
        <div class="lens-entity-selector-row">
            <label class="lens-entity-label">Entity</label>
            <select class="lens-entity-select" id="designEntitySelect" data-on-change="design-entity-change">
                <option value="">All entities</option>
            </select>
        </div>
        <div class="lens-subview-bar" id="designSubBar">
            <button class="lens-subview-btn lens-subview-btn-active"
                    data-action="switch-design-view" data-value="gallery">Gallery</button>
            <button class="lens-subview-btn"
                    data-action="switch-design-view" data-value="journey">Journey Map</button>
            <button class="lens-subview-btn"
                    data-action="switch-design-view" data-value="patterns">Pattern Library</button>
            <button class="lens-subview-btn"
                    data-action="switch-design-view" data-value="scoring">UX Scoring</button>
        </div>
        <div id="designSubContent" class="lens-sub-content">
            <div class="lens-loading">Loading evidence&hellip;</div>
        </div>
    `;

    _lensSubView = 'gallery';
    await _populateDesignEntitySelector();
    await _loadDesignGalleryData();
}

async function _populateDesignEntitySelector() {
    try {
        const resp = await fetch(`/api/entities?project_id=${currentProjectId}&limit=200`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const entities = Array.isArray(data) ? data : (data.entities || data.items || []);

        const sel = document.getElementById('designEntitySelect');
        if (!sel) return;
        entities.forEach(e => {
            const opt = document.createElement('option');
            opt.value = e.id;
            opt.textContent = e.name || e.company_name || `Entity ${e.id}`;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.warn('Could not load entity list:', e);
    }
}

function _onDesignEntityChange() {
    const sel = document.getElementById('designEntitySelect');
    _lensEntityFilter = sel ? (sel.value || null) : null;
    switch (_lensSubView) {
        case 'journey':  _loadDesignJourneyData();  break;
        case 'patterns': _loadDesignPatternsData(); break;
        case 'scoring':  _loadDesignScoringData();  break;
        default:         _loadDesignGalleryData();  break;
    }
}

function _switchDesignSubView(view) {
    _lensSubView = view;
    const bar = document.getElementById('designSubBar');
    if (bar) {
        const viewMap = { gallery: 0, journey: 1, patterns: 2, scoring: 3 };
        bar.querySelectorAll('.lens-subview-btn').forEach((btn, i) => {
            btn.classList.toggle('lens-subview-btn-active', i === viewMap[view]);
        });
    }
    switch (view) {
        case 'gallery':  _loadDesignGalleryData();  break;
        case 'journey':  _loadDesignJourneyData();  break;
        case 'patterns': _loadDesignPatternsData(); break;
        case 'scoring':  _loadDesignScoringData();  break;
    }
}

async function _loadDesignGalleryData() {
    const sub = document.getElementById('designSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading evidence gallery&hellip;</div>';

    let url = `/api/lenses/design/gallery?project_id=${currentProjectId}`;
    if (_lensEntityFilter) url += `&entity_id=${_lensEntityFilter}`;

    try {
        const resp = await fetch(url, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Evidence', 'No screenshots or documents captured yet.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderEvidenceGallery(data);
    } catch (e) {
        console.warn('Gallery load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load evidence gallery.');
    }
}

async function _loadDesignJourneyData() {
    const sub = document.getElementById('designSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading journey map&hellip;</div>';

    let url = `/api/lenses/design/journey?project_id=${currentProjectId}`;
    if (_lensEntityFilter) url += `&entity_id=${_lensEntityFilter}`;

    try {
        const resp = await fetch(url, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Journey Data', 'No classified screenshots available.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderJourneyMap(data);
    } catch (e) {
        console.warn('Journey load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load journey map.');
    }
}

/**
 * Render a grid of screenshot thumbnails grouped by evidence type.
 * Clicking a thumbnail expands it; metadata shown on hover.
 */
function _renderEvidenceGallery(data) {
    // data = { groups: [{type, label, items: [{id, filename, url, entity_name, captured_at, metadata}]}] }
    const groups = data.groups || [];

    if (!groups.length || groups.every(g => !g.items || !g.items.length)) {
        return _lensEmptyState('No Evidence', 'No screenshots or documents captured yet.');
    }

    const totalItems = groups.reduce((s, g) => s + (g.items || []).length, 0);

    const groupHtml = groups
        .filter(g => g.items && g.items.length)
        .map(group => {
            const items = group.items.map(item => {
                const src = item.serve_url || item.url || '';
                const isImg = /\.(png|jpe?g|gif|webp|avif)$/i.test(item.filename || src);
                const capturedAt = item.captured_at ? new Date(item.captured_at).toLocaleDateString() : '';

                return `
                    <div class="gallery-thumb" data-action="expand-gallery-item" data-src="${escAttr(src)}" data-entity="${escAttr(item.entity_name || '')}" data-filename="${escAttr(item.filename || '')}"
                         title="${escAttr(item.filename || '')} — ${escAttr(item.entity_name || '')}">
                        ${isImg
                            ? `<img class="gallery-thumb-img" src="${escAttr(src)}" alt="${escAttr(item.filename || '')}" loading="lazy">`
                            : `<div class="gallery-thumb-doc"><span class="gallery-doc-ext">${esc(_fileExt(item.filename || src))}</span></div>`
                        }
                        <div class="gallery-thumb-overlay">
                            <div class="gallery-thumb-name">${esc(_truncateLabel(item.entity_name || item.filename || '', 20))}</div>
                            ${capturedAt ? `<div class="gallery-thumb-date">${esc(capturedAt)}</div>` : ''}
                        </div>
                    </div>
                `;
            }).join('');

            return `
                <div class="gallery-group">
                    <div class="gallery-group-header">
                        <span class="gallery-group-label">${esc(group.label || group.type)}</span>
                        <span class="gallery-group-count">${group.items.length}</span>
                    </div>
                    <div class="gallery-grid">
                        ${items}
                    </div>
                </div>
            `;
        }).join('');

    return `
        <div class="gallery-meta">${totalItems} items</div>
        ${groupHtml}
        <div id="galleryLightbox" class="gallery-lightbox hidden" data-action="close-lightbox">
            <div class="gallery-lightbox-inner" data-action="lightbox-inner-stop">
                <button class="gallery-lightbox-close" data-action="close-lightbox">&times;</button>
                <img id="galleryLightboxImg" class="gallery-lightbox-img" src="" alt="">
                <div id="galleryLightboxCaption" class="gallery-lightbox-caption"></div>
            </div>
        </div>
    `;
}

function _renderJourneyMap(data) {
    // data = { sequences: [{stage, label, items: [{entity_name, filename, serve_url, ui_pattern}]}] }
    const sequences = data.sequences || [];

    if (!sequences.length) {
        return _lensEmptyState('No Journey Stages', 'Screenshots need to be classified to build a journey map.');
    }

    const stages = sequences.map(stage => {
        const thumbs = (stage.items || []).map(item => `
            <div class="journey-thumb" title="${escAttr(item.entity_name || '')} — ${escAttr(item.ui_pattern || '')}">
                <img class="journey-thumb-img" src="${escAttr(item.serve_url || '')}" alt="${escAttr(item.filename || '')}" loading="lazy">
                <div class="journey-thumb-meta">
                    <div class="journey-thumb-entity">${esc(_truncateLabel(item.entity_name || '', 14))}</div>
                    ${item.ui_pattern ? `<div class="journey-thumb-pattern">${esc(item.ui_pattern)}</div>` : ''}
                </div>
            </div>
        `).join('');

        return `
            <div class="journey-stage">
                <div class="journey-stage-label">${esc(stage.label || stage.stage)}</div>
                <div class="journey-stage-thumbs">
                    ${thumbs || '<span class="journey-no-thumbs">No screenshots</span>'}
                </div>
            </div>
        `;
    }).join('');

    return `
        <div class="journey-map">
            ${stages}
        </div>
    `;
}

function _expandGalleryItem(src, entityName, filename) {
    _lensExpandedImage = src;
    const lb = document.getElementById('galleryLightbox');
    const img = document.getElementById('galleryLightboxImg');
    const cap = document.getElementById('galleryLightboxCaption');
    if (!lb || !img) return;
    img.src = src;
    img.alt = filename;
    if (cap) cap.textContent = [entityName, filename].filter(Boolean).join(' — ');
    lb.classList.remove('hidden');
}

function _closeLightbox() {
    _lensExpandedImage = null;
    const lb = document.getElementById('galleryLightbox');
    if (lb) lb.classList.add('hidden');
}

// ── Design Lens: Pattern Library ──────────────────────────────

let _patternCategoryFilter = null;  // Current category filter for pattern library

async function _loadDesignPatternsData() {
    const sub = document.getElementById('designSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading pattern library&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/design/patterns?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Patterns', 'No design patterns found in evidence or attributes.'); return; }
        const data = await resp.json();
        _patternCategoryFilter = null;
        sub.innerHTML = _renderPatternLibrary(data);
    } catch (e) {
        console.warn('Pattern library load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load pattern library.');
    }
}

function _renderPatternLibrary(data) {
    const patterns = data.patterns || [];
    const categories = data.categories || [];

    if (!patterns.length) {
        return _lensEmptyState('No Patterns Found',
            'Capture screenshots and run extractions to discover design patterns.');
    }

    const filterPills = categories.map(cat =>
        `<button class="pattern-filter-pill ${_patternCategoryFilter === cat ? 'pattern-filter-pill-active' : ''}"
                data-action="filter-pattern-category" data-value="${escAttr(cat)}">${esc(cat.replace('_', ' '))}</button>`
    ).join('');

    const allActive = !_patternCategoryFilter ? 'pattern-filter-pill-active' : '';

    const filtered = _patternCategoryFilter
        ? patterns.filter(p => p.category === _patternCategoryFilter)
        : patterns;

    const cards = filtered.map(p => {
        const entityList = (p.entities || []).map(e =>
            `<span class="pattern-entity-tag">${esc(_truncateLabel(e, 16))}</span>`
        ).join('');

        const evidenceLinks = (p.evidence_ids || []).slice(0, 5).map(id =>
            `<span class="pattern-evidence-link" title="Evidence #${id}">#${id}</span>`
        ).join(' ');

        return `
            <div class="pattern-card">
                <div class="pattern-card-header">
                    <span class="pattern-card-name">${esc(p.name)}</span>
                    <span class="pattern-card-count">${p.occurrences || 0}</span>
                </div>
                <div class="pattern-card-category">${esc((p.category || '').replace('_', ' '))}</div>
                ${p.description ? `<div class="pattern-card-desc">${esc(_truncateLabel(p.description, 80))}</div>` : ''}
                ${entityList ? `<div class="pattern-card-entities">${entityList}</div>` : ''}
                ${evidenceLinks ? `<div class="pattern-card-evidence">${evidenceLinks}</div>` : ''}
            </div>
        `;
    }).join('');

    return `
        <div class="pattern-meta">
            <span class="pattern-meta-stat">${data.total_patterns || 0} patterns</span>
            <span class="matrix-meta-sep">/</span>
            <span class="pattern-meta-stat">${data.total_evidence || 0} evidence items</span>
        </div>
        <div class="pattern-filter-bar">
            <button class="pattern-filter-pill ${allActive}" data-action="filter-pattern-category" data-value="">All</button>
            ${filterPills}
        </div>
        <div class="pattern-grid">
            ${cards}
        </div>
    `;
}

function _filterPatternCategory(category) {
    _patternCategoryFilter = category;
    // Re-fetch and re-render (data is cached via browser)
    _loadDesignPatternsData();
}

// ── Design Lens: UX Scoring ──────────────────────────────────

async function _loadDesignScoringData() {
    const sub = document.getElementById('designSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Computing UX scores&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/design/scoring?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Scoring Data', 'Capture evidence to enable UX scoring.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderUXScoring(data);
    } catch (e) {
        console.warn('UX scoring load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not compute UX scores.');
    }
}

function _renderUXScoring(data) {
    const entities = data.entities || [];

    if (!entities.length) {
        return _lensEmptyState('No Entities with Evidence',
            'Capture screenshots and evidence for entities to compute UX scores.');
    }

    const avgScore = data.average_score || 0;
    const avgPct = Math.round(avgScore * 100);

    const rows = entities.map(e => {
        const overallPct = Math.round((e.overall_score || 0) * 100);
        const journeyPct = Math.round((e.journey_coverage || 0) * 100);
        const evidencePct = Math.round((e.evidence_depth || 0) * 100);
        const patternPct = Math.round((e.pattern_diversity || 0) * 100);
        const attrPct = Math.round((e.attribute_completeness || 0) * 100);

        let scoreClass = 'ux-score-weak';
        if (e.overall_score > 0.7) scoreClass = 'ux-score-strong';
        else if (e.overall_score >= 0.4) scoreClass = 'ux-score-moderate';

        const stageTags = (e.journey_stages_covered || []).map(s =>
            `<span class="ux-stage-tag">${esc(s)}</span>`
        ).join('');

        const patternTags = (e.patterns_found || []).map(p =>
            `<span class="ux-pattern-tag">${esc(p)}</span>`
        ).join('');

        return `
            <div class="ux-entity-row">
                <div class="ux-entity-header">
                    <span class="ux-entity-name" title="${escAttr(e.entity_name)}">${esc(_truncateLabel(e.entity_name, 24))}</span>
                    <span class="ux-overall-pct ${scoreClass}">${overallPct}%</span>
                </div>
                <div class="ux-score-bar-wrap">
                    <div class="ux-score-bar ${scoreClass}" style="width: ${overallPct}%"></div>
                </div>
                <div class="ux-sub-scores">
                    <div class="ux-sub-score">
                        <span class="ux-sub-label">Journey</span>
                        <div class="ux-sub-bar-wrap">
                            <div class="ux-sub-bar" style="width: ${journeyPct}%"></div>
                        </div>
                        <span class="ux-sub-pct">${journeyPct}%</span>
                    </div>
                    <div class="ux-sub-score">
                        <span class="ux-sub-label">Evidence</span>
                        <div class="ux-sub-bar-wrap">
                            <div class="ux-sub-bar" style="width: ${evidencePct}%"></div>
                        </div>
                        <span class="ux-sub-pct">${evidencePct}%</span>
                    </div>
                    <div class="ux-sub-score">
                        <span class="ux-sub-label">Patterns</span>
                        <div class="ux-sub-bar-wrap">
                            <div class="ux-sub-bar" style="width: ${patternPct}%"></div>
                        </div>
                        <span class="ux-sub-pct">${patternPct}%</span>
                    </div>
                    <div class="ux-sub-score">
                        <span class="ux-sub-label">Attributes</span>
                        <div class="ux-sub-bar-wrap">
                            <div class="ux-sub-bar" style="width: ${attrPct}%"></div>
                        </div>
                        <span class="ux-sub-pct">${attrPct}%</span>
                    </div>
                </div>
                <div class="ux-entity-details">
                    <span class="ux-detail-stat">${e.total_evidence || 0} evidence</span>
                    ${stageTags ? `<div class="ux-stage-tags">${stageTags}</div>` : ''}
                    ${patternTags ? `<div class="ux-pattern-tags">${patternTags}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');

    return `
        <div class="ux-scoring-meta">
            <span class="ux-meta-stat">${entities.length} entities scored</span>
            <span class="matrix-meta-sep">/</span>
            <span class="ux-meta-stat">Average: <strong>${avgPct}%</strong></span>
        </div>
        <div class="ux-scoring-legend">
            <span class="ux-legend-item ux-score-strong">Strong (&gt;70%)</span>
            <span class="ux-legend-item ux-score-moderate">Moderate (40&ndash;70%)</span>
            <span class="ux-legend-item ux-score-weak">Weak (&lt;40%)</span>
        </div>
        <div class="ux-scoring-list">
            ${rows}
        </div>
    `;
}

// ── Temporal Lens ────────────────────────────────────────────

/**
 * Load the Temporal lens — entity selector + snapshot timeline with
 * a side-by-side comparison picker.
 */
async function _loadTemporalLens() {
    const content = document.getElementById('lensContent');
    if (!content) return;

    content.innerHTML = `
        <div class="lens-entity-selector-row">
            <label class="lens-entity-label">Entity</label>
            <select class="lens-entity-select" id="temporalEntitySelect" data-on-change="temporal-entity-change">
                <option value="">Select an entity&hellip;</option>
            </select>
        </div>
        <div class="lens-subview-bar" id="temporalSubBar">
            <button class="lens-subview-btn lens-subview-btn-active"
                    data-action="switch-temporal-view" data-value="timeline">Timeline</button>
            <button class="lens-subview-btn"
                    data-action="switch-temporal-view" data-value="compare">Compare</button>
        </div>
        <div id="temporalSubContent" class="lens-sub-content">
            <div class="lens-empty-state">
                <div class="lens-empty-title">Select an entity</div>
                <div class="lens-empty-desc">Choose an entity above to view its snapshot history.</div>
            </div>
        </div>
    `;

    _lensSubView = 'timeline';
    await _populateTemporalEntitySelector();
}

async function _populateTemporalEntitySelector() {
    try {
        const resp = await fetch(`/api/entities?project_id=${currentProjectId}&limit=200`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const entities = Array.isArray(data) ? data : (data.entities || data.items || []);

        const sel = document.getElementById('temporalEntitySelect');
        if (!sel) return;
        entities.forEach(e => {
            const opt = document.createElement('option');
            opt.value = e.id;
            opt.textContent = e.name || e.company_name || `Entity ${e.id}`;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.warn('Could not load entity list for temporal lens:', e);
    }
}

function _onTemporalEntityChange() {
    const sel = document.getElementById('temporalEntitySelect');
    _lensEntityFilter = sel ? (sel.value || null) : null;
    if (!_lensEntityFilter) return;
    if (_lensSubView === 'compare') {
        _loadTemporalCompareData();
    } else {
        _loadTemporalTimelineData();
    }
}

function _switchTemporalSubView(view) {
    _lensSubView = view;
    const bar = document.getElementById('temporalSubBar');
    if (bar) {
        bar.querySelectorAll('.lens-subview-btn').forEach((btn, i) => {
            btn.classList.toggle('lens-subview-btn-active', (view === 'timeline' && i === 0) || (view === 'compare' && i === 1));
        });
    }
    if (!_lensEntityFilter) return;
    if (view === 'compare') _loadTemporalCompareData();
    else _loadTemporalTimelineData();
}

async function _loadTemporalTimelineData() {
    const sub = document.getElementById('temporalSubContent');
    if (!sub || !_lensEntityFilter) return;
    sub.innerHTML = '<div class="lens-loading">Loading timeline&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/temporal/timeline?project_id=${currentProjectId}&entity_id=${_lensEntityFilter}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Snapshots', 'No snapshot history for this entity.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderTimeline(data);
    } catch (e) {
        console.warn('Timeline load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load timeline.');
    }
}

async function _loadTemporalCompareData() {
    const sub = document.getElementById('temporalSubContent');
    if (!sub || !_lensEntityFilter) return;
    sub.innerHTML = '<div class="lens-loading">Loading snapshots for comparison&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/temporal/snapshots?project_id=${currentProjectId}&entity_id=${_lensEntityFilter}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Snapshots', 'No snapshot history available.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderComparisonPicker(data);
    } catch (e) {
        console.warn('Comparison load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load snapshots.');
    }
}

function _renderTimeline(data) {
    // data = { entity_name, snapshots: [{id, captured_at, attributes: {slug: value}}] }
    const snapshots = (data.snapshots || []).slice().sort((a, b) =>
        new Date(b.captured_at) - new Date(a.captured_at)
    );

    if (!snapshots.length) {
        return _lensEmptyState('No History', 'No attribute snapshots recorded for this entity.');
    }

    const cards = snapshots.map(snap => {
        const date = snap.captured_at ? new Date(snap.captured_at).toLocaleString() : 'Unknown date';
        const attrs = snap.attributes || {};
        const attrHtml = Object.entries(attrs).map(([slug, val]) =>
            `<div class="timeline-attr-row">
                <span class="timeline-attr-slug">${esc(slug)}</span>
                <span class="timeline-attr-val">${esc(String(val ?? ''))}</span>
            </div>`
        ).join('') || '<div class="timeline-attr-empty">No attributes captured</div>';

        return `
            <div class="timeline-card">
                <div class="timeline-dot"></div>
                <div class="timeline-card-inner">
                    <div class="timeline-card-date">${esc(date)}</div>
                    <div class="timeline-attrs">
                        ${attrHtml}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    return `
        <div class="timeline-entity-name">${esc(data.entity_name || '')}</div>
        <div class="timeline-wrap">
            ${cards}
        </div>
    `;
}

function _renderComparisonPicker(data) {
    // data = { entity_name, snapshots: [{id, captured_at, label}] }
    const snapshots = data.snapshots || [];

    if (snapshots.length < 2) {
        return _lensEmptyState('Not Enough Snapshots', 'At least two snapshots are needed for comparison.');
    }

    const options = snapshots.map(s =>
        `<option value="${esc(s.id)}">${esc(s.captured_at ? new Date(s.captured_at).toLocaleString() : `Snapshot ${s.id}`)}</option>`
    ).join('');

    return `
        <div class="compare-picker">
            <div class="compare-picker-row">
                <div class="compare-picker-col">
                    <label class="compare-picker-label">Before</label>
                    <select class="compare-picker-select" id="compareSnapshotA">
                        ${options}
                    </select>
                </div>
                <div class="compare-picker-vs">vs</div>
                <div class="compare-picker-col">
                    <label class="compare-picker-label">After</label>
                    <select class="compare-picker-select" id="compareSnapshotB">
                        ${options}
                    </select>
                </div>
            </div>
            <button class="btn btn-sm" data-action="run-comparison">Compare</button>
        </div>
        <div id="compareResult" class="compare-result"></div>
    `;
}

async function _runComparison() {
    const selA = document.getElementById('compareSnapshotA');
    const selB = document.getElementById('compareSnapshotB');
    const result = document.getElementById('compareResult');
    if (!selA || !selB || !result) return;

    const idA = selA.value;
    const idB = selB.value;
    if (!idA || !idB || idA === idB) {
        result.innerHTML = '<div class="compare-warn">Select two different snapshots.</div>';
        return;
    }

    result.innerHTML = '<div class="lens-loading">Comparing&hellip;</div>';

    try {
        const resp = await fetch(
            `/api/lenses/temporal/compare?project_id=${currentProjectId}&snapshot_a=${idA}&snapshot_b=${idB}`,
            { headers: { 'X-CSRFToken': CSRF_TOKEN } }
        );
        if (!resp.ok) { result.innerHTML = _lensEmptyState('Compare Failed', 'Could not compare snapshots.'); return; }
        const data = await resp.json();
        result.innerHTML = _renderComparisonView(data);
    } catch (e) {
        console.warn('Comparison failed:', e);
        result.innerHTML = _lensEmptyState('Compare Failed', 'An error occurred during comparison.');
    }
}

function _renderComparisonView(data) {
    // data = { label_a, label_b, diffs: [{slug, value_a, value_b, changed}] }
    const diffs = data.diffs || [];

    if (!diffs.length) {
        return '<div class="compare-no-diff">No attributes to compare.</div>';
    }

    const rows = diffs.map(diff => {
        const changedClass = diff.changed ? 'compare-row-changed' : '';
        return `
            <div class="compare-row ${changedClass}">
                <div class="compare-row-slug">${esc(diff.slug)}</div>
                <div class="compare-row-a">${esc(String(diff.value_a ?? '—'))}</div>
                <div class="compare-row-b">${esc(String(diff.value_b ?? '—'))}</div>
                ${diff.changed ? '<div class="compare-row-changed-marker">Changed</div>' : '<div></div>'}
            </div>
        `;
    }).join('');

    return `
        <div class="compare-view">
            <div class="compare-view-header">
                <div class="compare-view-attr-head">Attribute</div>
                <div class="compare-view-col-head">${esc(data.label_a || 'Before')}</div>
                <div class="compare-view-col-head">${esc(data.label_b || 'After')}</div>
                <div class="compare-view-diff-head">Diff</div>
            </div>
            ${rows}
        </div>
    `;
}

// ── Product Lens ─────────────────────────────────────────────

/**
 * Load the Product lens — pricing landscape table + plan comparison grid.
 */
async function _loadProductLens() {
    const content = document.getElementById('lensContent');
    if (!content) return;

    content.innerHTML = `
        <div class="lens-subview-bar" id="productSubBar">
            <button class="lens-subview-btn lens-subview-btn-active"
                    data-action="switch-product-view" data-value="pricing">Pricing Landscape</button>
            <button class="lens-subview-btn"
                    data-action="switch-product-view" data-value="plans">Plan Comparison</button>
        </div>
        <div id="productSubContent" class="lens-sub-content">
            <div class="lens-loading">Loading pricing data&hellip;</div>
        </div>
    `;

    _lensSubView = 'pricing';
    await _loadPricingLandscapeData();
}

function _switchProductSubView(view) {
    _lensSubView = view;
    const bar = document.getElementById('productSubBar');
    if (bar) {
        bar.querySelectorAll('.lens-subview-btn').forEach((btn, i) => {
            btn.classList.toggle('lens-subview-btn-active', (view === 'pricing' && i === 0) || (view === 'plans' && i === 1));
        });
    }
    if (view === 'plans') _loadPlanComparisonData();
    else _loadPricingLandscapeData();
}

async function _loadPricingLandscapeData() {
    const sub = document.getElementById('productSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading pricing landscape&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/product/pricing?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Pricing Data', 'No pricing attributes found for entities.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderPricingLandscape(data);
    } catch (e) {
        console.warn('Pricing load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load pricing data.');
    }
}

async function _loadPlanComparisonData() {
    const sub = document.getElementById('productSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading plan comparison&hellip;</div>';

    try {
        const resp = await fetch(`/api/lenses/product/plans?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Plan Data', 'No plan or tier data found for entities.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderPlanComparison(data);
    } catch (e) {
        console.warn('Plan comparison load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load plan comparison.');
    }
}

function _renderPricingLandscape(data) {
    // data = { entities: [{id, name, pricing_model, price_min, price_max, currency, free_tier}] }
    const entities = (data.entities || []).slice().sort((a, b) => (a.price_min || 0) - (b.price_min || 0));

    if (!entities.length) {
        return _lensEmptyState('No Pricing Data', 'No pricing attributes found for entities.');
    }

    const rows = entities.map((e, i) => {
        const curr = e.currency || '$';
        const priceStr = e.price_min != null
            ? (e.price_max != null && e.price_max !== e.price_min
                ? `${curr}${e.price_min} – ${curr}${e.price_max}`
                : `${curr}${e.price_min}`)
            : '—';

        return `
            <tr class="${i % 2 === 0 ? 'pricing-row-even' : 'pricing-row-odd'}">
                <td class="pricing-cell pricing-entity">${esc(e.name)}</td>
                <td class="pricing-cell pricing-model">${esc(e.pricing_model || '—')}</td>
                <td class="pricing-cell pricing-price">${esc(priceStr)}</td>
                <td class="pricing-cell pricing-free">
                    ${e.free_tier ? '<span class="pricing-badge-free">Free tier</span>' : ''}
                </td>
            </tr>
        `;
    }).join('');

    return `
        <div class="pricing-scroll-wrap">
            <table class="pricing-table">
                <thead>
                    <tr>
                        <th class="pricing-head">Entity</th>
                        <th class="pricing-head">Model</th>
                        <th class="pricing-head">Price</th>
                        <th class="pricing-head">Free Tier</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>
        <div class="pricing-meta">${entities.length} entities</div>
    `;
}

function _renderPlanComparison(data) {
    // data = { features: [{label}], plans: [{entity_name, plan_name, values: [value_per_feature]}] }
    const features = data.features || [];
    const plans = data.plans || [];

    if (!plans.length || !features.length) {
        return _lensEmptyState('No Plan Data', 'No plan or tier attributes found for entities.');
    }

    const headerCells = plans.map(p =>
        `<th class="plans-col-head" title="${escAttr(p.entity_name)}">${esc(_truncateLabel(p.plan_name || p.entity_name, 14))}</th>`
    ).join('');

    const rows = features.map((feat, rowIdx) => {
        const cells = plans.map(p => {
            const val = p.values ? p.values[rowIdx] : undefined;
            const display = _matrixCellDisplay(val);
            return `<td class="plans-cell">${display}</td>`;
        }).join('');
        return `
            <tr class="${rowIdx % 2 === 0 ? 'plans-row-even' : 'plans-row-odd'}">
                <th class="plans-row-head">${esc(feat.label)}</th>
                ${cells}
            </tr>
        `;
    }).join('');

    return `
        <div class="plans-scroll-wrap">
            <table class="plans-table">
                <thead>
                    <tr>
                        <th class="plans-origin-cell"></th>
                        ${headerCells}
                    </tr>
                </thead>
                <tbody>
                    ${rows}
                </tbody>
            </table>
        </div>
        <div class="plans-meta">${plans.length} plans across ${features.length} features</div>
    `;
}

// ── Signals Lens ──────────────────────────────────────────────

/**
 * Load the Signals lens — four sub-views: Timeline, Activity, Trends, Heatmap.
 */
async function _loadSignalsLens() {
    const content = document.getElementById('lensContent');
    if (!content) return;

    content.innerHTML = `
        <div class="lens-subview-bar" id="signalsSubBar">
            <button class="lens-subview-btn lens-subview-btn-active"
                    data-action="switch-signals-view" data-value="timeline">Timeline</button>
            <button class="lens-subview-btn"
                    data-action="switch-signals-view" data-value="activity">Activity</button>
            <button class="lens-subview-btn"
                    data-action="switch-signals-view" data-value="trends">Trends</button>
            <button class="lens-subview-btn"
                    data-action="switch-signals-view" data-value="heatmap">Heatmap</button>
            <button class="lens-subview-btn"
                    data-action="switch-signals-view" data-value="summary">Summary</button>
        </div>
        <div id="signalsSubContent" class="lens-sub-content">
            <div class="lens-loading">Loading timeline&hellip;</div>
        </div>
    `;

    _lensSubView = 'timeline';
    await _loadSignalsTimelineData();
}

function _switchSignalsSubView(view) {
    _lensSubView = view;
    const bar = document.getElementById('signalsSubBar');
    if (bar) {
        const viewMap = { timeline: 0, activity: 1, trends: 2, heatmap: 3, summary: 4 };
        bar.querySelectorAll('.lens-subview-btn').forEach((btn, i) => {
            btn.classList.toggle('lens-subview-btn-active', i === viewMap[view]);
        });
    }
    switch (view) {
        case 'timeline': _loadSignalsTimelineData(); break;
        case 'activity': _loadSignalsActivityData(); break;
        case 'trends':   _loadSignalsTrendsData();   break;
        case 'heatmap':  _loadSignalsHeatmapData();  break;
        case 'summary':  _loadSignalsSummaryData();  break;
    }
}

async function _loadSignalsTimelineData() {
    const sub = document.getElementById('signalsSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading timeline&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/lenses/signals/timeline?project_id=${currentProjectId}&limit=100`);
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Timeline Data', 'No events recorded yet.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderSignalsTimeline(data);
    } catch (e) {
        console.warn('Signals timeline load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load timeline.');
    }
}

function _renderSignalsTimeline(data) {
    const events = data.events || [];
    if (!events.length) {
        return _lensEmptyState('No Events', 'No signals events recorded for this project.');
    }

    const typeIcons = {
        change_detected: '\u0394',   // delta
        attribute_updated: '\u270E', // pencil
        evidence_captured: '\u2609', // sun/dot
    };

    const severityClass = {
        critical: 'sig-sev-critical',
        high: 'sig-sev-high',
        medium: 'sig-sev-medium',
        low: 'sig-sev-low',
        info: 'sig-sev-info',
    };

    const rows = events.map(ev => {
        const icon = typeIcons[ev.type] || '\u2022';
        const sevCls = severityClass[ev.severity] || 'sig-sev-info';
        const ts = ev.timestamp ? ev.timestamp.substring(0, 16).replace('T', ' ') : '';

        return `
            <div class="sig-timeline-row">
                <div class="sig-timeline-icon ${sevCls}" title="${esc(ev.severity || 'info')}">${icon}</div>
                <div class="sig-timeline-body">
                    <div class="sig-timeline-header">
                        <span class="sig-timeline-entity">${esc(ev.entity_name || '')}</span>
                        <span class="sig-timeline-ts">${esc(ts)}</span>
                    </div>
                    <div class="sig-timeline-title">${esc(ev.title || '')}</div>
                    <div class="sig-timeline-desc">${esc(ev.description || '')}</div>
                </div>
            </div>
        `;
    }).join('');

    return `
        <div class="sig-timeline-meta">${data.total || events.length} events total</div>
        <div class="sig-timeline-list">${rows}</div>
    `;
}

async function _loadSignalsActivityData() {
    const sub = document.getElementById('signalsSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading activity summary&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/lenses/signals/activity?project_id=${currentProjectId}`);
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Activity Data', 'No entity activity recorded.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderSignalsActivity(data);
    } catch (e) {
        console.warn('Signals activity load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load activity data.');
    }
}

function _renderSignalsActivity(data) {
    const entities = data.entities || [];
    if (!entities.length) {
        return _lensEmptyState('No Activity', 'No entities found in this project.');
    }

    // Sort by total activity descending
    const sorted = entities.slice().sort((a, b) => {
        const totalA = (a.change_count || 0) + (a.evidence_count || 0) + (a.attribute_updates || 0);
        const totalB = (b.change_count || 0) + (b.evidence_count || 0) + (b.attribute_updates || 0);
        return totalB - totalA;
    });

    const maxTotal = Math.max(...sorted.map(e =>
        (e.change_count || 0) + (e.evidence_count || 0) + (e.attribute_updates || 0)
    ), 1);

    const rows = sorted.map(e => {
        const total = (e.change_count || 0) + (e.evidence_count || 0) + (e.attribute_updates || 0);
        const pct = Math.round((total / maxTotal) * 100);
        const lastChange = e.last_change ? e.last_change.substring(0, 10) : '—';

        return `
            <div class="sig-activity-row">
                <div class="sig-activity-name" title="${escAttr(e.entity_name)}">${esc(_truncateLabel(e.entity_name, 24))}</div>
                <div class="sig-activity-bar-wrap">
                    <div class="sig-activity-bar" style="width: ${pct}%">
                        <span class="sig-activity-changes" style="width: ${total ? Math.round(((e.change_count || 0) / total) * 100) : 0}%"></span>
                        <span class="sig-activity-evidence" style="width: ${total ? Math.round(((e.evidence_count || 0) / total) * 100) : 0}%"></span>
                        <span class="sig-activity-attrs" style="width: ${total ? Math.round(((e.attribute_updates || 0) / total) * 100) : 0}%"></span>
                    </div>
                </div>
                <div class="sig-activity-stats">
                    <span title="Changes">${e.change_count || 0}</span> /
                    <span title="Evidence">${e.evidence_count || 0}</span> /
                    <span title="Attributes">${e.attribute_updates || 0}</span>
                </div>
                <div class="sig-activity-last">${esc(lastChange)}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="sig-activity-header">
            <span class="sig-activity-h-name">Entity</span>
            <span class="sig-activity-h-bar">Activity</span>
            <span class="sig-activity-h-stats">Ch / Ev / At</span>
            <span class="sig-activity-h-last">Last Change</span>
        </div>
        <div class="sig-activity-legend">
            <span class="sig-legend-item sig-legend-changes">Changes</span>
            <span class="sig-legend-item sig-legend-evidence">Evidence</span>
            <span class="sig-legend-item sig-legend-attrs">Attributes</span>
        </div>
        <div class="sig-activity-list">${rows}</div>
    `;
}

async function _loadSignalsTrendsData() {
    const sub = document.getElementById('signalsSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading trends&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/lenses/signals/trends?project_id=${currentProjectId}`);
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Trend Data', 'No temporal data available.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderSignalsTrends(data);
    } catch (e) {
        console.warn('Signals trends load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load trends.');
    }
}

function _renderSignalsTrends(data) {
    const periods = data.periods || [];
    if (!periods.length) {
        return _lensEmptyState('No Trends', 'No weekly activity data available.');
    }

    const maxTotal = Math.max(...periods.map(p => p.total || 0), 1);

    const bars = periods.map(p => {
        const pct = Math.round(((p.total || 0) / maxTotal) * 100);
        const label = p.period_start ? p.period_start.substring(5) : '';

        return `
            <div class="sig-trends-col">
                <div class="sig-trends-bar-area">
                    <div class="sig-trends-bar" style="height: ${pct}%" title="${p.total} events">
                        <span class="sig-trends-seg sig-trends-seg-change" style="height: ${p.total ? Math.round(((p.change_count || 0) / p.total) * 100) : 0}%"></span>
                        <span class="sig-trends-seg sig-trends-seg-attr" style="height: ${p.total ? Math.round(((p.attribute_count || 0) / p.total) * 100) : 0}%"></span>
                        <span class="sig-trends-seg sig-trends-seg-ev" style="height: ${p.total ? Math.round(((p.evidence_count || 0) / p.total) * 100) : 0}%"></span>
                    </div>
                </div>
                <div class="sig-trends-label">${esc(label)}</div>
                <div class="sig-trends-count">${p.total || 0}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="sig-trends-chart">
            <div class="sig-trends-cols">${bars}</div>
        </div>
        <div class="sig-trends-legend">
            <span class="sig-legend-item sig-legend-changes">Changes</span>
            <span class="sig-legend-item sig-legend-evidence">Evidence</span>
            <span class="sig-legend-item sig-legend-attrs">Attributes</span>
        </div>
        <div class="sig-trends-meta">${periods.length} weeks</div>
    `;
}

async function _loadSignalsHeatmapData() {
    const sub = document.getElementById('signalsSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading heatmap&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/lenses/signals/heatmap?project_id=${currentProjectId}`);
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Heatmap Data', 'No data for heatmap.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderSignalsHeatmap(data);
    } catch (e) {
        console.warn('Signals heatmap load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load heatmap.');
    }
}

function _renderSignalsHeatmap(data) {
    const entities = data.entities || [];
    const eventTypes = data.event_types || [];
    const matrix = data.matrix || [];

    if (!entities.length || !eventTypes.length) {
        return _lensEmptyState('No Heatmap Data', 'No entity event data to display.');
    }

    const typeLabels = {
        change_detected: 'Changes',
        attribute_updated: 'Attributes',
        evidence_captured: 'Evidence',
    };

    // Find max value for color intensity
    const allVals = matrix.flat();
    const maxVal = Math.max(...allVals, 1);

    const headerCells = eventTypes.map(t =>
        `<th class="sig-hm-col-header">${esc(typeLabels[t] || t)}</th>`
    ).join('');

    const rows = entities.map((name, rowIdx) => {
        const cells = eventTypes.map((_, colIdx) => {
            const val = matrix[rowIdx] ? (matrix[rowIdx][colIdx] || 0) : 0;
            const intensity = Math.round((val / maxVal) * 100);
            return `<td class="sig-hm-cell" style="--hm-intensity: ${intensity}%" title="${val}">${val || ''}</td>`;
        }).join('');

        return `
            <tr>
                <th class="sig-hm-row-header" title="${escAttr(name)}">${esc(_truncateLabel(name, 20))}</th>
                ${cells}
            </tr>
        `;
    }).join('');

    return `
        <div class="sig-hm-scroll-wrap">
            <table class="sig-hm-table">
                <thead>
                    <tr>
                        <th class="sig-hm-origin"></th>
                        ${headerCells}
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
        <div class="sig-hm-legend">
            <span class="sig-hm-legend-low">Low</span>
            <span class="sig-hm-legend-gradient"></span>
            <span class="sig-hm-legend-high">High</span>
        </div>
        <div class="sig-hm-meta">${entities.length} entities &times; ${eventTypes.length} event types</div>
    `;
}

async function _loadSignalsSummaryData() {
    const sub = document.getElementById('signalsSubContent');
    if (!sub) return;
    sub.innerHTML = '<div class="lens-loading">Loading market summary&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/lenses/signals/summary?project_id=${currentProjectId}&days=30`);
        if (!resp.ok) { sub.innerHTML = _lensEmptyState('No Summary Data', 'No market activity in the last 30 days.'); return; }
        const data = await resp.json();
        sub.innerHTML = _renderSignalsSummary(data);
    } catch (e) {
        console.warn('Signals summary load failed:', e);
        sub.innerHTML = _lensEmptyState('Load Failed', 'Could not load market summary.');
    }
}

function _renderSignalsSummary(data) {
    if (!data.total_events) {
        return _lensEmptyState('No Market Activity', 'No events recorded in the last ' + data.period_days + ' days.');
    }

    const sb = data.source_breakdown || {};
    const sv = data.severity_breakdown || {};

    // Stats bar
    const statsHtml = `
        <div class="sig-summary-stats">
            <div class="sig-summary-stat">
                <span class="sig-summary-stat-value">${data.total_events}</span>
                <span class="sig-summary-stat-label">Total Events</span>
            </div>
            <div class="sig-summary-stat">
                <span class="sig-summary-stat-value">${data.entity_count || 0}</span>
                <span class="sig-summary-stat-label">Entities</span>
            </div>
            <div class="sig-summary-stat">
                <span class="sig-summary-stat-value">${sb.change_detected || 0}</span>
                <span class="sig-summary-stat-label">Changes</span>
            </div>
            <div class="sig-summary-stat">
                <span class="sig-summary-stat-value">${sb.attribute_updated || 0}</span>
                <span class="sig-summary-stat-label">Attributes</span>
            </div>
            <div class="sig-summary-stat">
                <span class="sig-summary-stat-value">${sb.evidence_captured || 0}</span>
                <span class="sig-summary-stat-label">Evidence</span>
            </div>
        </div>
    `;

    // Most active entities
    const activeEntities = (data.most_active_entities || []).map(e => `
        <div class="sig-summary-active-row">
            <span class="sig-summary-active-name">${esc(e.entity_name)}</span>
            <span class="sig-summary-active-count">${e.event_count}</span>
        </div>
    `).join('') || '<div class="sig-summary-none">No active entities</div>';

    // Top changed fields
    const changedFields = (data.top_changed_fields || []).map(f => `
        <div class="sig-summary-field-row">
            <span class="sig-summary-field-name">${esc(f.field_name)}</span>
            <span class="sig-summary-field-count">${f.change_count} changes across ${f.entities_affected} entities</span>
        </div>
    `).join('') || '<div class="sig-summary-none">No field changes detected</div>';

    // Recent highlights
    const highlights = (data.recent_highlights || []).map(h => `
        <div class="sig-summary-highlight">
            <span class="sig-summary-hl-entity">${esc(h.entity_name)}</span>
            <span class="sig-summary-hl-field">${esc(h.field_name || '')}</span>
            <span class="sig-summary-hl-change">${esc((h.old_value || '').substring(0, 20))} &rarr; ${esc((h.new_value || '').substring(0, 20))}</span>
            <span class="sig-summary-hl-ts">${h.timestamp ? h.timestamp.substring(0, 10) : ''}</span>
        </div>
    `).join('') || '<div class="sig-summary-none">No recent highlights</div>';

    // Severity breakdown
    const sevHtml = Object.entries(sv)
        .filter(([_, v]) => v > 0)
        .map(([k, v]) => `<span class="sig-summary-sev sig-sev-${k}">${k}: ${v}</span>`)
        .join(' ') || '<span class="sig-summary-none">No severity data</span>';

    return `
        <div class="sig-summary-period">Last ${data.period_days} days</div>
        ${statsHtml}
        <div class="sig-summary-sections">
            <div class="sig-summary-section">
                <h3>Most Active Entities</h3>
                ${activeEntities}
            </div>
            <div class="sig-summary-section">
                <h3>Top Changed Fields</h3>
                ${changedFields}
            </div>
            <div class="sig-summary-section">
                <h3>Severity</h3>
                <div class="sig-summary-sev-bar">${sevHtml}</div>
            </div>
            <div class="sig-summary-section">
                <h3>Recent Highlights</h3>
                ${highlights}
            </div>
        </div>
    `;
}

// ── Utilities ─────────────────────────────────────────────────

function _lensEmptyState(title, desc) {
    return `
        <div class="lens-empty-state">
            <div class="lens-empty-title">${esc(title)}</div>
            <div class="lens-empty-desc">${esc(desc)}</div>
        </div>
    `;
}

function _renderLensError(msg) {
    const content = document.getElementById('lensContent');
    if (content) content.innerHTML = _lensEmptyState('Error', msg);
    const bar = document.getElementById('lensSelector');
    if (bar) bar.innerHTML = '';
}

function _truncateLabel(str, maxLen) {
    if (!str) return '';
    return str.length <= maxLen ? str : str.substring(0, maxLen - 1) + '\u2026';
}

function _fileExt(filename) {
    const m = filename.match(/\.([a-zA-Z0-9]+)$/);
    return m ? m[1].toUpperCase() : 'FILE';
}

// ── Action Delegation ─────────────────────────────────────────

registerActions({
    'select-lens':              (el) => _selectLens(el.dataset.value),
    'switch-competitive-view':  (el) => _switchCompetitiveSubView(el.dataset.value),
    'switch-design-view':       (el) => _switchDesignSubView(el.dataset.value),
    'switch-temporal-view':     (el) => _switchTemporalSubView(el.dataset.value),
    'switch-product-view':      (el) => _switchProductSubView(el.dataset.value),
    'switch-signals-view':      (el) => _switchSignalsSubView(el.dataset.value),
    'design-entity-change':     ()   => _onDesignEntityChange(),
    'temporal-entity-change':   ()   => _onTemporalEntityChange(),
    'expand-gallery-item':      (el) => _expandGalleryItem(el.dataset.src, el.dataset.entity, el.dataset.filename),
    'close-lightbox':           ()   => _closeLightbox(),
    'lightbox-inner-stop':      (el, e) => e.stopPropagation(),
    'run-comparison':           ()   => _runComparison(),
    'filter-pattern-category':  (el) => _filterPatternCategory(el.dataset.value || null),
    'toggle-enriched-matrix':   (el) => _toggleEnrichedMatrix(el.checked),
});

// ── Expose on window (for external callers) ──────────────────

window.initLenses = initLenses;
