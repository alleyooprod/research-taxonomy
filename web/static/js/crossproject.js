/**
 * Cross-Project Intelligence — entity linking, attribute diffing, cross-project insights.
 *
 * Sub-view inside #tab-intelligence, toggled via the sub-nav in insights.js.
 * Dashboard container is created dynamically by _ensureCrossProjectDashboard().
 *
 * API prefix: /api/cross-project/...
 */

// ── State ──────────────────────────────────────────────────────
let _xpLoaded = false;
let _xpLinks = [];
let _xpInsights = [];
let _xpStats = null;
let _xpCurrentView = 'overview';  // 'overview' | 'links' | 'insights'
let _xpLinkFilters = {};          // {link_type, source}
let _xpScanning = false;
let _xpAnalysing = false;
let _xpDiffPanelVisible = false;
let _xpManualLinkFormVisible = false;

// ── Public API ─────────────────────────────────────────────────
window.initCrossProject = initCrossProject;
window._ensureCrossProjectDashboard = _ensureCrossProjectDashboard;

// ── Entry Point ────────────────────────────────────────────────

/**
 * Initialise cross-project intelligence view.
 * Called when the cross-project sub-nav button is clicked.
 */
async function initCrossProject() {
    if (!currentProjectId) return;

    _ensureCrossProjectDashboard();

    await Promise.all([
        _loadXpStats(),
        _loadXpLinks(),
        _loadXpInsights(),
    ]);

    _xpLoaded = true;
}

// ── Dashboard Construction ─────────────────────────────────────

/**
 * Create the cross-project dashboard container inside #tab-intelligence
 * if it does not already exist.
 */
function _ensureCrossProjectDashboard() {
    const tab = document.getElementById('tab-intelligence');
    if (!tab) return;

    // Already created?
    if (document.getElementById('crossProjectDashboard')) return;

    const container = document.createElement('div');
    container.id = 'crossProjectDashboard';
    container.className = 'xp-dashboard hidden';
    container.innerHTML = `
        <div class="xp-header">
            <h2>Cross-Project Intelligence</h2>
            <div class="xp-header-actions">
                <button class="xp-btn xp-scan-btn" id="xpScanBtn"
                        onclick="_xpScanForOverlaps()">Scan for Overlaps</button>
                <button class="xp-btn xp-btn-ghost" id="xpAnalyseBtn"
                        onclick="_xpRunAnalysis()">Run Analysis</button>
            </div>
        </div>

        <div class="xp-stats-bar" id="xpStatsBar">
            <div class="xp-loading">Loading stats...</div>
        </div>

        <div class="xp-inner-nav" id="xpInnerNav">
            <button class="xp-inner-nav-btn xp-inner-nav-btn--active" data-xp-view="overview"
                    onclick="_xpSwitchView('overview')">Overview</button>
            <button class="xp-inner-nav-btn" data-xp-view="links"
                    onclick="_xpSwitchView('links')">Entity Links</button>
            <button class="xp-inner-nav-btn" data-xp-view="insights"
                    onclick="_xpSwitchView('insights')">Insights</button>
        </div>

        <div id="xpOverviewSection" class="xp-overview"></div>
        <div id="xpLinksSection" class="xp-links-section hidden"></div>
        <div id="xpInsightsSection" class="xp-insights-section hidden"></div>
        <div id="xpDiffPanel" class="xp-diff-panel hidden"></div>
    `;
    tab.appendChild(container);
}

// ── Inner Navigation ───────────────────────────────────────────

/**
 * Switch between overview, links, and insights sub-views.
 */
function _xpSwitchView(view) {
    _xpCurrentView = view;

    // Update nav buttons
    document.querySelectorAll('.xp-inner-nav-btn').forEach(btn => {
        btn.classList.toggle('xp-inner-nav-btn--active', btn.dataset.xpView === view);
    });

    // Toggle sections
    const overviewEl = document.getElementById('xpOverviewSection');
    const linksEl = document.getElementById('xpLinksSection');
    const insightsEl = document.getElementById('xpInsightsSection');

    if (overviewEl) overviewEl.classList.toggle('hidden', view !== 'overview');
    if (linksEl) linksEl.classList.toggle('hidden', view !== 'links');
    if (insightsEl) insightsEl.classList.toggle('hidden', view !== 'insights');

    // Hide diff panel when switching views
    _xpCloseDiffPanel();

    // Render content for the view
    if (view === 'overview') {
        _renderXpOverview();
    } else if (view === 'links') {
        _renderXpLinksView();
    } else if (view === 'insights') {
        _renderXpInsightCards(_xpInsights);
    }
}

// ── Stats ──────────────────────────────────────────────────────

async function _loadXpStats() {
    try {
        const resp = await safeFetch('/api/cross-project/stats');
        if (!resp.ok) return;
        _xpStats = await resp.json();
        _renderXpStats(_xpStats);
    } catch (e) {
        console.warn('Failed to load cross-project stats:', e);
    }
}

function _renderXpStats(stats) {
    const el = document.getElementById('xpStatsBar');
    if (!el || !stats) return;

    const totalLinks = stats.total_links || 0;
    const overlapping = stats.overlapping_entities || 0;
    const projects = stats.projects_with_overlaps || 0;
    const insights = stats.undismissed_insights || stats.total_insights || 0;

    el.innerHTML = `
        <div class="xp-stat-card">
            <span class="xp-stat-value">${totalLinks}</span>
            <span class="xp-stat-label">Links</span>
        </div>
        <div class="xp-stat-card">
            <span class="xp-stat-value">${overlapping}</span>
            <span class="xp-stat-label">Overlapping</span>
        </div>
        <div class="xp-stat-card">
            <span class="xp-stat-value">${projects}</span>
            <span class="xp-stat-label">Projects</span>
        </div>
        <div class="xp-stat-card">
            <span class="xp-stat-value">${insights}</span>
            <span class="xp-stat-label">Insights</span>
        </div>
    `;
}

// ── Scan for Overlaps ──────────────────────────────────────────

async function _xpScanForOverlaps() {
    if (_xpScanning) return;
    _xpScanning = true;

    const btn = document.getElementById('xpScanBtn');
    if (btn) {
        btn.disabled = true;
        btn.classList.add('xp-scan-btn--scanning');
        btn.textContent = 'Scanning...';
    }

    try {
        const resp = await safeFetch('/api/cross-project/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Scan failed');
            return;
        }

        const data = await resp.json();
        const count = data.links_found || data.count || 0;
        showToast(`Found ${count} overlap${count !== 1 ? 's' : ''}`);

        // Reload data
        await Promise.all([
            _loadXpStats(),
            _loadXpLinks(),
        ]);

        // Re-render current view
        _xpSwitchView(_xpCurrentView);
    } catch (e) {
        console.error('Overlap scan failed:', e);
        showToast('Overlap scan failed');
    } finally {
        _xpScanning = false;
        if (btn) {
            btn.disabled = false;
            btn.classList.remove('xp-scan-btn--scanning');
            btn.textContent = 'Scan for Overlaps';
        }
    }
}

// ── Load Links ─────────────────────────────────────────────────

async function _loadXpLinks() {
    let url = '/api/cross-project/overlaps?limit=100';
    if (_xpLinkFilters.link_type) url += `&link_type=${encodeURIComponent(_xpLinkFilters.link_type)}`;
    if (_xpLinkFilters.source) url += `&source=${encodeURIComponent(_xpLinkFilters.source)}`;

    try {
        const resp = await safeFetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        _xpLinks = data.links || data.overlaps || data || [];
        if (Array.isArray(_xpLinks)) {
            // Already good
        } else {
            _xpLinks = [];
        }
    } catch (e) {
        console.warn('Failed to load cross-project links:', e);
        _xpLinks = [];
    }
}

// ── Load Insights ──────────────────────────────────────────────

async function _loadXpInsights() {
    try {
        const resp = await safeFetch('/api/cross-project/insights');
        if (!resp.ok) return;
        const data = await resp.json();
        _xpInsights = data.insights || data || [];
        if (!Array.isArray(_xpInsights)) _xpInsights = [];
    } catch (e) {
        console.warn('Failed to load cross-project insights:', e);
        _xpInsights = [];
    }
}

// ── Overview Rendering ─────────────────────────────────────────

function _renderXpOverview() {
    const el = document.getElementById('xpOverviewSection');
    if (!el) return;

    const recentLinks = _xpLinks.slice(0, 5);
    const recentInsights = _xpInsights.filter(i => !i.is_dismissed).slice(0, 5);

    el.innerHTML = `
        <div class="xp-overview-section">
            <div class="xp-overview-section-title">Recent Entity Links</div>
            ${recentLinks.length > 0
                ? _renderXpLinksTableHtml(recentLinks)
                : '<div class="xp-empty"><div class="xp-empty-title">No entity links yet</div><div class="xp-empty-desc">Scan for overlaps to discover entities that appear across multiple projects.</div></div>'
            }
            ${recentLinks.length > 0 && _xpLinks.length > 5
                ? `<button class="xp-btn xp-btn-ghost xp-btn-sm" onclick="_xpSwitchView('links')" style="margin-top:var(--space-2);">View all ${_xpLinks.length} links</button>`
                : ''
            }
        </div>

        <div class="xp-overview-section">
            <div class="xp-overview-section-title">Recent Insights</div>
            ${recentInsights.length > 0
                ? '<div id="xpOverviewInsights">' + recentInsights.map((ins, i) => _renderXpInsightCardHtml(ins, i)).join('') + '</div>'
                : '<div class="xp-empty"><div class="xp-empty-title">No insights yet</div><div class="xp-empty-desc">Run analysis to discover patterns across your projects.</div></div>'
            }
            ${recentInsights.length > 0 && _xpInsights.filter(i => !i.is_dismissed).length > 5
                ? `<button class="xp-btn xp-btn-ghost xp-btn-sm" onclick="_xpSwitchView('insights')" style="margin-top:var(--space-2);">View all insights</button>`
                : ''
            }
        </div>
    `;
}

// ── Links View Rendering ───────────────────────────────────────

function _renderXpLinksView() {
    const el = document.getElementById('xpLinksSection');
    if (!el) return;

    el.innerHTML = `
        <div class="xp-links-filters" id="xpLinksFilters">
            ${_renderXpLinkFiltersHtml()}
        </div>
        <div id="xpManualLinkArea"></div>
        <div id="xpLinksTableContainer">
            ${_xpLinks.length > 0
                ? _renderXpLinksTableHtml(_xpLinks)
                : '<div class="xp-empty"><div class="xp-empty-title">No entity links</div><div class="xp-empty-desc">Scan for overlaps or create a manual link to connect entities across projects.</div><button class="xp-btn" onclick="_xpScanForOverlaps()">Scan for Overlaps</button></div>'
            }
        </div>
    `;
}

function _renderXpLinkFiltersHtml() {
    const linkTypeOptions = [
        { value: '', label: 'All types' },
        { value: 'same_entity', label: 'Same Entity' },
        { value: 'related', label: 'Related' },
        { value: 'parent_child', label: 'Parent/Child' },
    ];
    const sourceOptions = [
        { value: '', label: 'All sources' },
        { value: 'auto', label: 'Auto' },
        { value: 'manual', label: 'Manual' },
        { value: 'ai', label: 'AI' },
    ];

    const currentType = _xpLinkFilters.link_type || '';
    const currentSource = _xpLinkFilters.source || '';

    return `
        <select class="xp-filter-select" onchange="_xpSetLinkFilter('link_type', this.value)" aria-label="Filter by link type">
            ${linkTypeOptions.map(o => `<option value="${o.value}" ${o.value === currentType ? 'selected' : ''}>${o.label}</option>`).join('')}
        </select>
        <select class="xp-filter-select" onchange="_xpSetLinkFilter('source', this.value)" aria-label="Filter by source">
            ${sourceOptions.map(o => `<option value="${o.value}" ${o.value === currentSource ? 'selected' : ''}>${o.label}</option>`).join('')}
        </select>
        <button class="xp-btn xp-btn-sm xp-btn-ghost" onclick="_xpToggleManualLinkForm()">+ Manual Link</button>
    `;
}

function _xpSetLinkFilter(key, value) {
    if (value) {
        _xpLinkFilters[key] = value;
    } else {
        delete _xpLinkFilters[key];
    }
    _loadXpLinks().then(() => _renderXpLinksView());
}

// ── Links Table HTML ───────────────────────────────────────────

function _renderXpLinksTableHtml(links) {
    if (!links || links.length === 0) return '';

    const rows = links.map(link => {
        const srcName = link.source_entity_name || link.source_name || 'Unknown';
        const srcProject = link.source_project_name || link.source_project || '';
        const tgtName = link.target_entity_name || link.target_name || 'Unknown';
        const tgtProject = link.target_project_name || link.target_project || '';
        const linkType = link.link_type || 'related';
        const confidence = link.confidence != null ? link.confidence : 1.0;
        const confPct = Math.round(confidence * 100);
        const source = link.source || 'auto';
        const linkId = link.id;
        const srcId = link.source_entity_id;
        const tgtId = link.target_entity_id;

        return `
            <tr data-link-id="${linkId}">
                <td>
                    <div class="xp-entity-cell">
                        <span class="xp-entity-name">${esc(srcName)}</span>
                        <span class="xp-entity-project">${esc(srcProject)}</span>
                    </div>
                </td>
                <td>
                    <div class="xp-entity-cell">
                        <span class="xp-entity-name">${esc(tgtName)}</span>
                        <span class="xp-entity-project">${esc(tgtProject)}</span>
                    </div>
                </td>
                <td>
                    <span class="xp-link-type-badge xp-link-type-badge--${esc(linkType)}">${esc(_xpFormatLinkType(linkType))}</span>
                </td>
                <td>
                    <div class="xp-confidence">
                        <div class="xp-confidence-bar">
                            <div class="xp-confidence-fill" style="width: ${confPct}%"></div>
                        </div>
                        <span class="xp-confidence-label">${confPct}%</span>
                    </div>
                </td>
                <td>
                    <span class="xp-source-badge xp-source-badge--${esc(source)}">${esc(source)}</span>
                </td>
                <td>
                    <div class="xp-link-actions">
                        <button class="xp-btn xp-btn-sm xp-btn-ghost"
                                onclick="event.stopPropagation(); _xpViewEntityDiff(${srcId}, ${tgtId})"
                                title="View Diff">Diff</button>
                        <button class="xp-btn xp-btn-sm xp-btn-ghost"
                                onclick="event.stopPropagation(); _xpShowSyncPanel(${srcId}, ${tgtId})"
                                title="Sync Attributes">Sync</button>
                        <button class="xp-btn xp-btn-sm xp-btn-danger"
                                onclick="event.stopPropagation(); _xpDeleteLink(${linkId})"
                                title="Delete Link">Delete</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    return `
        <table class="xp-links-table">
            <thead>
                <tr>
                    <th>Source Entity</th>
                    <th>Target Entity</th>
                    <th>Type</th>
                    <th>Confidence</th>
                    <th>Source</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;
}

function _renderXpLinksTable(links) {
    const container = document.getElementById('xpLinksTableContainer');
    if (!container) return;

    if (!links || links.length === 0) {
        container.innerHTML = '<div class="xp-empty"><div class="xp-empty-title">No entity links</div><div class="xp-empty-desc">Scan for overlaps or create a manual link.</div></div>';
        return;
    }

    container.innerHTML = _renderXpLinksTableHtml(links);
}

// ── Entity Diff ────────────────────────────────────────────────

async function _xpViewEntityDiff(entityId, compareToId) {
    const panel = document.getElementById('xpDiffPanel');
    if (!panel) return;

    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="xp-loading">Loading comparison...</div>';
    _xpDiffPanelVisible = true;

    try {
        const resp = await safeFetch(`/api/cross-project/entity/${entityId}/diff?compare_to=${compareToId}`);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            panel.innerHTML = `<div class="xp-loading">${esc(err.error || 'Failed to load diff')}</div>`;
            return;
        }

        const data = await resp.json();
        _renderDiffPanel(data, entityId, compareToId);
    } catch (e) {
        console.warn('Failed to load entity diff:', e);
        panel.innerHTML = '<div class="xp-loading">Failed to load comparison</div>';
    }
}

function _renderDiffPanel(data, entityId, compareToId) {
    const panel = document.getElementById('xpDiffPanel');
    if (!panel) return;

    const entityAName = data.entity_a_name || data.source_name || `Entity ${entityId}`;
    const entityBName = data.entity_b_name || data.target_name || `Entity ${compareToId}`;
    const attributes = data.attributes || data.diff || [];

    // Categorise attributes
    let sameCount = 0;
    let diffCount = 0;
    let onlyACount = 0;
    let onlyBCount = 0;

    const rows = attributes.map(attr => {
        const slug = attr.slug || attr.attribute || attr.name || '';
        const valA = attr.value_a != null ? String(attr.value_a) : '';
        const valB = attr.value_b != null ? String(attr.value_b) : '';
        const hasA = attr.value_a != null && attr.value_a !== '';
        const hasB = attr.value_b != null && attr.value_b !== '';

        let rowClass = '';
        if (hasA && hasB && valA === valB) {
            rowClass = 'xp-diff-row--same';
            sameCount++;
        } else if (hasA && hasB) {
            rowClass = 'xp-diff-row--different';
            diffCount++;
        } else if (hasA && !hasB) {
            rowClass = 'xp-diff-row--only-a';
            onlyACount++;
        } else if (!hasA && hasB) {
            rowClass = 'xp-diff-row--only-b';
            onlyBCount++;
        } else {
            sameCount++;
        }

        return `
            <div class="xp-diff-row ${rowClass}">
                <span class="xp-diff-row-attr">${esc(slug)}</span>
                <span class="xp-diff-row-val">${hasA ? esc(valA) : '<em style="color:var(--text-muted)">--</em>'}</span>
                <span class="xp-diff-row-val">${hasB ? esc(valB) : '<em style="color:var(--text-muted)">--</em>'}</span>
            </div>
        `;
    }).join('');

    panel.innerHTML = `
        <div class="xp-diff-panel-header">
            <span class="xp-diff-panel-title">Attribute Comparison</span>
            <button class="xp-btn xp-btn-sm xp-btn-ghost" onclick="_xpCloseDiffPanel()">Close</button>
        </div>

        <div class="xp-diff-entities">
            <span class="xp-diff-entity-label">${esc(entityAName)}</span>
            <span class="xp-diff-vs">vs</span>
            <span class="xp-diff-entity-label">${esc(entityBName)}</span>
        </div>

        <div class="xp-diff-grid-header">
            <span>Attribute</span>
            <span>${esc(entityAName)}</span>
            <span>${esc(entityBName)}</span>
        </div>

        <div class="xp-diff-rows">
            ${rows || '<div class="xp-loading">No attributes to compare</div>'}
        </div>

        <div class="xp-diff-summary">
            <div class="xp-diff-summary-item">
                <span class="xp-diff-summary-count">${sameCount}</span>
                <span>same</span>
            </div>
            <div class="xp-diff-summary-item">
                <span class="xp-diff-summary-count">${diffCount}</span>
                <span>different</span>
            </div>
            <div class="xp-diff-summary-item">
                <span class="xp-diff-summary-count">${onlyACount}</span>
                <span>only in A</span>
            </div>
            <div class="xp-diff-summary-item">
                <span class="xp-diff-summary-count">${onlyBCount}</span>
                <span>only in B</span>
            </div>
        </div>
    `;
}

function _xpCloseDiffPanel() {
    const panel = document.getElementById('xpDiffPanel');
    if (panel) panel.classList.add('hidden');
    _xpDiffPanelVisible = false;
}

// ── Sync Attributes ────────────────────────────────────────────

async function _xpShowSyncPanel(sourceId, targetId) {
    // First load the diff to know which attributes differ
    const panel = document.getElementById('xpDiffPanel');
    if (!panel) return;

    panel.classList.remove('hidden');
    panel.innerHTML = '<div class="xp-loading">Loading attributes...</div>';
    _xpDiffPanelVisible = true;

    try {
        const resp = await safeFetch(`/api/cross-project/entity/${sourceId}/diff?compare_to=${targetId}`);
        if (!resp.ok) {
            panel.innerHTML = '<div class="xp-loading">Failed to load attributes</div>';
            return;
        }

        const data = await resp.json();
        _renderSyncPanel(data, sourceId, targetId);
    } catch (e) {
        console.warn('Failed to load sync data:', e);
        panel.innerHTML = '<div class="xp-loading">Failed to load attributes</div>';
    }
}

function _renderSyncPanel(data, sourceId, targetId) {
    const panel = document.getElementById('xpDiffPanel');
    if (!panel) return;

    const entityAName = data.entity_a_name || data.source_name || `Entity ${sourceId}`;
    const entityBName = data.entity_b_name || data.target_name || `Entity ${targetId}`;
    const attributes = data.attributes || data.diff || [];

    // Only show attributes that differ or exist only in source
    const syncable = attributes.filter(attr => {
        const valA = attr.value_a != null ? String(attr.value_a) : '';
        const valB = attr.value_b != null ? String(attr.value_b) : '';
        return valA !== valB && valA !== '';
    });

    if (syncable.length === 0) {
        panel.innerHTML = `
            <div class="xp-diff-panel-header">
                <span class="xp-diff-panel-title">Sync Attributes</span>
                <button class="xp-btn xp-btn-sm xp-btn-ghost" onclick="_xpCloseDiffPanel()">Close</button>
            </div>
            <div class="xp-loading">No differing attributes to sync from ${esc(entityAName)} to ${esc(entityBName)}</div>
        `;
        return;
    }

    const checkboxes = syncable.map(attr => {
        const slug = attr.slug || attr.attribute || attr.name || '';
        return `
            <div class="xp-sync-row">
                <input type="checkbox" id="xpSync_${esc(slug)}" value="${esc(slug)}" checked>
                <label for="xpSync_${esc(slug)}">${esc(slug)}</label>
                <span style="font-size:var(--font-size-xs);color:var(--text-muted);font-family:var(--font-mono);margin-left:auto;">${esc(String(attr.value_a || ''))}</span>
            </div>
        `;
    }).join('');

    panel.innerHTML = `
        <div class="xp-diff-panel-header">
            <span class="xp-diff-panel-title">Sync Attributes</span>
            <button class="xp-btn xp-btn-sm xp-btn-ghost" onclick="_xpCloseDiffPanel()">Close</button>
        </div>

        <div class="xp-diff-entities">
            <span class="xp-diff-entity-label">${esc(entityAName)}</span>
            <span class="xp-diff-vs">-&gt;</span>
            <span class="xp-diff-entity-label">${esc(entityBName)}</span>
        </div>

        <div id="xpSyncCheckboxes">
            ${checkboxes}
        </div>

        <div class="xp-sync-actions">
            <button class="xp-btn xp-btn-sm" id="xpSyncSubmitBtn"
                    onclick="_xpDoSync(${sourceId}, ${targetId})">Sync Selected</button>
            <button class="xp-btn xp-btn-sm xp-btn-ghost" onclick="_xpCloseDiffPanel()">Cancel</button>
        </div>
    `;
}

async function _xpDoSync(sourceId, targetId) {
    const checkboxes = document.querySelectorAll('#xpSyncCheckboxes input[type="checkbox"]:checked');
    const attrSlugs = Array.from(checkboxes).map(cb => cb.value);

    if (attrSlugs.length === 0) {
        showToast('Select at least one attribute to sync');
        return;
    }

    const btn = document.getElementById('xpSyncSubmitBtn');
    if (btn) btn.disabled = true;

    try {
        const resp = await safeFetch('/api/cross-project/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_entity_id: sourceId,
                target_entity_id: targetId,
                attr_slugs: attrSlugs,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Sync failed');
            return;
        }

        const data = await resp.json();
        const synced = data.synced || attrSlugs.length;
        showToast(`Synced ${synced} attribute${synced !== 1 ? 's' : ''}`);
        _xpCloseDiffPanel();
    } catch (e) {
        console.error('Attribute sync failed:', e);
        showToast('Sync failed');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function _xpSyncAttributes(sourceId, targetId, attrSlugs) {
    return _xpDoSync(sourceId, targetId);
}

// ── Run Analysis ───────────────────────────────────────────────

async function _xpRunAnalysis() {
    if (_xpAnalysing) return;
    _xpAnalysing = true;

    const btn = document.getElementById('xpAnalyseBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Analysing...';
    }

    try {
        const resp = await safeFetch('/api/cross-project/analyse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Analysis failed');
            return;
        }

        const data = await resp.json();
        const count = data.insights_generated || data.count || 0;
        showToast(`Generated ${count} insight${count !== 1 ? 's' : ''}`);

        // Reload
        await Promise.all([
            _loadXpStats(),
            _loadXpInsights(),
        ]);
        _xpSwitchView(_xpCurrentView);
    } catch (e) {
        console.error('Cross-project analysis failed:', e);
        showToast('Analysis failed');
    } finally {
        _xpAnalysing = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Run Analysis';
        }
    }
}

// ── Insight Cards ──────────────────────────────────────────────

function _renderXpInsightCards(insights) {
    const el = document.getElementById('xpInsightsSection');
    if (!el) return;

    const active = (insights || []).filter(i => !i.is_dismissed);

    if (active.length === 0) {
        el.innerHTML = `
            <div class="xp-empty">
                <div class="xp-empty-title">No cross-project insights</div>
                <div class="xp-empty-desc">Run analysis to discover patterns, divergences, and coverage gaps across projects.</div>
                <button class="xp-btn" onclick="_xpRunAnalysis()">Run Analysis</button>
            </div>
        `;
        return;
    }

    el.innerHTML = active.map((ins, i) => _renderXpInsightCardHtml(ins, i)).join('');
}

function _renderXpInsightCardHtml(insight, idx) {
    const severity = (insight.severity || 'info').toLowerCase();
    const type = insight.type || 'pattern';
    const isDismissed = insight.is_dismissed;
    const timeAgo = insight.created_at ? _xpRelativeTime(insight.created_at) : '';
    const entityRef = insight.entity_name || '';
    const projectRef = insight.project_name || '';

    const severityLabels = { critical: 'CRIT', important: 'IMP', notable: 'NOTE', info: 'INFO' };
    const severityLabel = severityLabels[severity] || severity.toUpperCase();

    const cardClasses = [
        'xp-insight-card',
        `xp-insight-card--${severity}`,
        isDismissed ? 'xp-insight-card--dismissed' : '',
    ].filter(Boolean).join(' ');

    return `
        <div class="${cardClasses}" data-xp-insight-id="${insight.id}" style="--i:${idx}">
            <div class="xp-insight-card__left">
                <span class="xp-insight-card__severity xp-insight-card__severity--${esc(severity)}" title="${esc(severity)}">${severityLabel}</span>
                <div class="xp-insight-card__content">
                    <div class="xp-insight-card__title-row">
                        <span class="xp-insight-card__type">${esc(_xpFormatInsightType(type))}</span>
                        <span class="xp-insight-card__title">${esc(insight.title || '')}</span>
                    </div>
                    <div class="xp-insight-card__description">${esc(insight.description || '')}</div>
                    <div class="xp-insight-card__meta">
                        ${entityRef ? `<span class="xp-insight-card__entity-ref">${esc(entityRef)}</span><span class="xp-insight-card__meta-sep">&middot;</span>` : ''}
                        ${projectRef ? `<span class="xp-insight-card__project-ref">${esc(projectRef)}</span><span class="xp-insight-card__meta-sep">&middot;</span>` : ''}
                        <span class="xp-insight-card__time">${esc(timeAgo)}</span>
                    </div>
                </div>
            </div>
            <div class="xp-insight-card__actions">
                <button class="xp-btn xp-btn-sm xp-btn-ghost"
                        onclick="event.stopPropagation(); _xpDismissInsight(${insight.id})"
                        title="Dismiss">Dismiss</button>
                <button class="xp-btn xp-btn-sm xp-btn-danger"
                        onclick="event.stopPropagation(); _xpDeleteInsight(${insight.id})"
                        title="Delete">Delete</button>
            </div>
        </div>
    `;
}

// ── Insight Actions ────────────────────────────────────────────

async function _xpDismissInsight(id) {
    try {
        const resp = await safeFetch(`/api/cross-project/insights/${id}/dismiss`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) return;

        // Animate out
        const card = document.querySelector(`[data-xp-insight-id="${id}"]`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateX(20px)';
            setTimeout(() => {
                const insight = _xpInsights.find(i => i.id === id);
                if (insight) insight.is_dismissed = true;
                _renderXpInsightCards(_xpInsights);
                _loadXpStats();
            }, 200);
        }

        showToast('Insight dismissed');
    } catch (e) {
        console.warn('Failed to dismiss cross-project insight:', e);
    }
}

async function _xpDeleteInsight(id) {
    const confirmed = await window.showNativeConfirm({
        title: 'Delete Insight',
        message: 'This will permanently remove this cross-project insight.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/cross-project/insights/${id}`, {
            method: 'DELETE',
        });
        if (!resp.ok) return;

        const card = document.querySelector(`[data-xp-insight-id="${id}"]`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateX(20px)';
            setTimeout(() => {
                _xpInsights = _xpInsights.filter(i => i.id !== id);
                _renderXpInsightCards(_xpInsights);
                _loadXpStats();
            }, 200);
        }

        showToast('Insight deleted');
    } catch (e) {
        console.warn('Failed to delete cross-project insight:', e);
    }
}

// ── Delete Link ────────────────────────────────────────────────

async function _xpDeleteLink(linkId) {
    const confirmed = await window.showNativeConfirm({
        title: 'Delete Link',
        message: 'Remove this entity link? This does not affect the entities themselves.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/cross-project/link/${linkId}`, {
            method: 'DELETE',
        });
        if (!resp.ok) return;

        // Animate row removal
        const row = document.querySelector(`[data-link-id="${linkId}"]`);
        if (row) {
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            row.style.transition = 'opacity 200ms, transform 200ms';
            setTimeout(() => {
                _xpLinks = _xpLinks.filter(l => l.id !== linkId);
                _xpSwitchView(_xpCurrentView);
                _loadXpStats();
            }, 200);
        }

        showToast('Link removed');
    } catch (e) {
        console.warn('Failed to delete link:', e);
    }
}

// ── Manual Link Form ───────────────────────────────────────────

function _xpToggleManualLinkForm() {
    _xpManualLinkFormVisible = !_xpManualLinkFormVisible;
    const area = document.getElementById('xpManualLinkArea');
    if (!area) return;

    if (!_xpManualLinkFormVisible) {
        area.innerHTML = '';
        return;
    }

    area.innerHTML = `
        <div class="xp-link-form">
            <div class="xp-link-form-title">Create Manual Link</div>
            <div class="xp-form-row">
                <div class="xp-form-field">
                    <label class="xp-form-label" for="xpLinkSourceId">Source Entity ID</label>
                    <input id="xpLinkSourceId" type="number" class="xp-form-input" placeholder="Entity ID">
                </div>
                <div class="xp-form-field">
                    <label class="xp-form-label" for="xpLinkTargetId">Target Entity ID</label>
                    <input id="xpLinkTargetId" type="number" class="xp-form-input" placeholder="Entity ID">
                </div>
            </div>
            <div class="xp-form-row">
                <div class="xp-form-field">
                    <label class="xp-form-label" for="xpLinkType">Link Type</label>
                    <select id="xpLinkType" class="xp-form-select">
                        <option value="same_entity">Same Entity</option>
                        <option value="related">Related</option>
                        <option value="parent_child">Parent / Child</option>
                    </select>
                </div>
                <div class="xp-form-field">
                    <label class="xp-form-label" for="xpLinkConfidence">Confidence (0-1)</label>
                    <input id="xpLinkConfidence" type="number" class="xp-form-input"
                           min="0" max="1" step="0.1" value="1.0" placeholder="0.0 - 1.0">
                </div>
            </div>
            <div class="xp-form-actions">
                <button class="xp-btn xp-btn-sm" id="xpManualLinkSubmit"
                        onclick="_xpSubmitManualLink()">Create Link</button>
                <button class="xp-btn xp-btn-sm xp-btn-ghost"
                        onclick="_xpToggleManualLinkForm()">Cancel</button>
            </div>
        </div>
    `;

    // Focus the first input
    const firstInput = document.getElementById('xpLinkSourceId');
    if (firstInput) firstInput.focus();
}

function _xpCreateManualLink() {
    _xpManualLinkFormVisible = false;
    _xpToggleManualLinkForm();
}

async function _xpSubmitManualLink() {
    const sourceId = parseInt(document.getElementById('xpLinkSourceId')?.value, 10);
    const targetId = parseInt(document.getElementById('xpLinkTargetId')?.value, 10);
    const linkType = document.getElementById('xpLinkType')?.value || 'related';
    const confidence = parseFloat(document.getElementById('xpLinkConfidence')?.value) || 1.0;

    if (!sourceId || !targetId) {
        showToast('Both source and target entity IDs are required');
        return;
    }
    if (sourceId === targetId) {
        showToast('Source and target must be different entities');
        return;
    }

    const btn = document.getElementById('xpManualLinkSubmit');
    if (btn) btn.disabled = true;

    try {
        const resp = await safeFetch('/api/cross-project/link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_entity_id: sourceId,
                target_entity_id: targetId,
                link_type: linkType,
                confidence: confidence,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to create link');
            return;
        }

        showToast('Link created');
        _xpManualLinkFormVisible = false;

        await Promise.all([
            _loadXpStats(),
            _loadXpLinks(),
        ]);
        _renderXpLinksView();
    } catch (e) {
        console.error('Manual link creation failed:', e);
        showToast('Failed to create link');
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Helpers ────────────────────────────────────────────────────

/**
 * Format link type for display.
 */
function _xpFormatLinkType(type) {
    const labels = {
        same_entity: 'Same Entity',
        related: 'Related',
        parent_child: 'Parent/Child',
    };
    return labels[type] || (type || '').replace(/_/g, ' ');
}

/**
 * Format insight type for display.
 */
function _xpFormatInsightType(type) {
    const labels = {
        overlap: 'Overlap',
        divergence: 'Divergence',
        coverage_gap: 'Coverage Gap',
        trend: 'Trend',
        pattern: 'Pattern',
        contradiction: 'Contradiction',
    };
    return labels[type] || (type || '').replace(/_/g, ' ');
}

/**
 * Format an ISO date string as a human-readable relative time.
 */
function _xpRelativeTime(isoString) {
    if (!isoString) return '';
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHr = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHr / 24);
        const diffWeek = Math.floor(diffDay / 7);

        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHr < 24) return `${diffHr}h ago`;
        if (diffDay < 7) return `${diffDay}d ago`;
        if (diffWeek < 5) return `${diffWeek}w ago`;

        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
        return '';
    }
}

// ── Expose on window ──────────────────────────────────────────

window._xpScanForOverlaps = _xpScanForOverlaps;
window._xpRunAnalysis = _xpRunAnalysis;
window._xpSwitchView = _xpSwitchView;
window._xpViewEntityDiff = _xpViewEntityDiff;
window._xpShowSyncPanel = _xpShowSyncPanel;
window._xpDoSync = _xpDoSync;
window._xpSyncAttributes = _xpSyncAttributes;
window._xpDismissInsight = _xpDismissInsight;
window._xpDeleteInsight = _xpDeleteInsight;
window._xpDeleteLink = _xpDeleteLink;
window._xpToggleManualLinkForm = _xpToggleManualLinkForm;
window._xpCreateManualLink = _xpCreateManualLink;
window._xpSubmitManualLink = _xpSubmitManualLink;
window._xpSetLinkFilter = _xpSetLinkFilter;
window._xpCloseDiffPanel = _xpCloseDiffPanel;
