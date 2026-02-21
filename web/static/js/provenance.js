/**
 * Evidence Provenance — trace data points back to source evidence.
 *
 * Sub-views: Coverage (project overview), Sources (URL list), Search (attribute lookup).
 * Lives inside #tab-intelligence as a sub-view alongside Monitoring, Insights, etc.
 *
 * API prefix: /api/provenance/...
 */

// ── State ──────────────────────────────────────────────────────
let _provenanceLoaded = false;
let _provenanceView = 'coverage'; // 'coverage' | 'sources' | 'search'
let _provenanceStats = null;

// ── Public API ─────────────────────────────────────────────────

window.initProvenance = initProvenance;
window._ensureProvenanceDashboard = _ensureProvenanceDashboard;

/**
 * Entry point — called when Provenance sub-view is selected.
 */
function initProvenance() {
    if (!currentProjectId) return;
    _ensureProvenanceDashboard();
    _loadProvenanceView();
}

// ── Dashboard Setup ────────────────────────────────────────────

function _ensureProvenanceDashboard() {
    const tab = document.getElementById('tab-intelligence');
    if (!tab || document.getElementById('provenanceDashboard')) return;

    const container = document.createElement('div');
    container.id = 'provenanceDashboard';
    container.className = 'prov-dashboard hidden';
    container.innerHTML = `
        <div class="prov-header">
            <h2>Evidence Provenance</h2>
        </div>
        <div class="prov-sub-nav" id="provSubNav">
            <button class="prov-sub-btn prov-sub-btn--active" data-view="coverage"
                    data-action="switch-provenance-view">Coverage</button>
            <button class="prov-sub-btn" data-view="sources"
                    data-action="switch-provenance-view">Sources</button>
            <button class="prov-sub-btn" data-view="search"
                    data-action="switch-provenance-view">Search</button>
        </div>
        <div class="prov-stats-bar" id="provStatsBar"></div>
        <div class="prov-content" id="provContent">
            <div class="prov-loading">Loading provenance data&hellip;</div>
        </div>
    `;
    tab.appendChild(container);
}

window._switchProvenanceView = _switchProvenanceView;

function _switchProvenanceView(view) {
    _provenanceView = view;

    // Update sub-nav active state
    document.querySelectorAll('.prov-sub-btn').forEach(btn => {
        btn.classList.toggle('prov-sub-btn--active', btn.dataset.view === view);
    });

    _loadProvenanceView();
}

async function _loadProvenanceView() {
    // Always load stats first
    await _loadProvenanceStats();

    switch (_provenanceView) {
        case 'coverage': await _loadProvenanceCoverage(); break;
        case 'sources':  await _loadProvenanceSources();  break;
        case 'search':   _renderProvenanceSearch();        break;
    }
}

// ── Stats Bar ──────────────────────────────────────────────────

async function _loadProvenanceStats() {
    const bar = document.getElementById('provStatsBar');
    if (!bar) return;

    try {
        const resp = await safeFetch(`/api/provenance/stats?project_id=${currentProjectId}`);
        if (!resp.ok) { bar.innerHTML = ''; return; }
        _provenanceStats = await resp.json();
        _renderProvenanceStatsBar(_provenanceStats);
    } catch (e) {
        console.warn('Provenance stats failed:', e);
        bar.innerHTML = '';
    }
}

function _renderProvenanceStatsBar(stats) {
    const bar = document.getElementById('provStatsBar');
    if (!bar) return;

    bar.innerHTML = `
        <div class="prov-stat">
            <span class="prov-stat-value">${stats.total_attributes || 0}</span>
            <span class="prov-stat-label">Attributes</span>
        </div>
        <div class="prov-stat">
            <span class="prov-stat-value">${stats.evidence_backed || 0}</span>
            <span class="prov-stat-label">Evidence-Backed</span>
        </div>
        <div class="prov-stat">
            <span class="prov-stat-value">${stats.coverage_pct || 0}%</span>
            <span class="prov-stat-label">Coverage</span>
        </div>
        <div class="prov-stat">
            <span class="prov-stat-value">${stats.source_count || 0}</span>
            <span class="prov-stat-label">Sources</span>
        </div>
        <div class="prov-stat">
            <span class="prov-stat-value">${stats.evidence_count || 0}</span>
            <span class="prov-stat-label">Evidence Items</span>
        </div>
    `;
}

// ── Coverage View ──────────────────────────────────────────────

async function _loadProvenanceCoverage() {
    const content = document.getElementById('provContent');
    if (!content) return;
    content.innerHTML = '<div class="prov-loading">Loading coverage data&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/provenance/project/${currentProjectId}/coverage`);
        if (!resp.ok) {
            content.innerHTML = _provEmpty('No Coverage Data', 'No entities or attributes to analyse.');
            return;
        }
        const data = await resp.json();
        content.innerHTML = _renderCoverageView(data);
    } catch (e) {
        console.warn('Provenance coverage failed:', e);
        content.innerHTML = _provEmpty('Load Failed', 'Could not load coverage data.');
    }
}

function _renderCoverageView(data) {
    const entities = data.entities || [];
    if (!entities.length) {
        return _provEmpty('No Entities', 'Add entities with attributes to see provenance coverage.');
    }

    // Overall stats
    const overallPct = data.coverage_pct || 0;

    // Sort entities by coverage % ascending (worst first)
    const sorted = entities.slice().sort((a, b) => a.pct - b.pct);

    const rows = sorted.map(e => {
        const pct = Math.round(e.pct || 0);
        let barClass = 'prov-bar-low';
        if (pct >= 70) barClass = 'prov-bar-high';
        else if (pct >= 40) barClass = 'prov-bar-medium';

        return `
            <div class="prov-cov-row" data-action="show-entity-provenance" data-id="${e.id}" title="View provenance details">
                <div class="prov-cov-name">${esc(e.name)}</div>
                <div class="prov-cov-bar-wrap">
                    <div class="prov-cov-bar ${barClass}" style="width: ${pct}%"></div>
                </div>
                <div class="prov-cov-pct">${pct}%</div>
                <div class="prov-cov-counts">${e.evidence_backed || 0} / ${e.total_attrs || 0}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="prov-cov-overall">
            <div class="prov-cov-overall-pct">${Math.round(overallPct)}%</div>
            <div class="prov-cov-overall-label">Overall Evidence Coverage</div>
            <div class="prov-cov-overall-detail">
                ${data.with_evidence || 0} evidence-backed /
                ${data.with_extraction || 0} extraction /
                ${data.manual_only || 0} manual
            </div>
        </div>
        <div class="prov-cov-header">
            <span class="prov-cov-h-name">Entity</span>
            <span class="prov-cov-h-bar">Coverage</span>
            <span class="prov-cov-h-pct">%</span>
            <span class="prov-cov-h-counts">Backed / Total</span>
        </div>
        <div class="prov-cov-list">${rows}</div>
        <div class="prov-cov-legend">
            <span class="prov-legend-item prov-bar-low">Low (&lt;40%)</span>
            <span class="prov-legend-item prov-bar-medium">Medium (40-69%)</span>
            <span class="prov-legend-item prov-bar-high">High (&ge;70%)</span>
        </div>
    `;
}

// ── Entity Provenance Detail (inline expand) ──────────────────

window._showEntityProvenance = _showEntityProvenance;
window._closeEntityProvenance = _closeEntityProvenance;

async function _showEntityProvenance(entityId) {
    const content = document.getElementById('provContent');
    if (!content) return;

    // Save current view to restore later
    const previousHtml = content.innerHTML;
    content.innerHTML = '<div class="prov-loading">Loading entity provenance&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/provenance/entity/${entityId}`);
        if (!resp.ok) {
            content.innerHTML = previousHtml;
            showToast('Could not load entity provenance', 'error');
            return;
        }
        const data = await resp.json();
        content.innerHTML = _renderEntityProvenance(data, previousHtml);
    } catch (e) {
        content.innerHTML = previousHtml;
        showToast('Failed to load entity provenance', 'error');
    }
}

function _renderEntityProvenance(data, previousHtml) {
    const attrs = data.attributes || [];
    const cov = data.coverage || {};

    const rows = attrs.map(a => {
        const sourceIcon = a.has_evidence ? '\u2713' : (a.source === 'extraction' ? '\u2248' : '\u2014');
        const sourceCls = a.has_evidence ? 'prov-src-evidence' : (a.source === 'extraction' ? 'prov-src-extraction' : 'prov-src-manual');

        return `
            <div class="prov-attr-row">
                <div class="prov-attr-slug">${esc(a.attr_slug)}</div>
                <div class="prov-attr-value" title="${escAttr(a.value || '')}">${esc(_truncateProvLabel(a.value || '', 40))}</div>
                <div class="prov-attr-source ${sourceCls}">${sourceIcon} ${esc(a.source || 'manual')}</div>
                <div class="prov-attr-chain">${a.chain_length || 1} step${(a.chain_length || 1) !== 1 ? 's' : ''}</div>
                <div class="prov-attr-url">${a.source_url ? `<a href="${escAttr(a.source_url)}" target="_blank" rel="noopener" title="${escAttr(a.source_url)}">source</a>` : ''}</div>
            </div>
        `;
    }).join('');

    // Store the previous HTML in a data attribute for the back button
    window._provPreviousHtml = previousHtml;

    return `
        <div class="prov-entity-detail">
            <div class="prov-entity-header">
                <button class="prov-back-btn" data-action="close-entity-provenance">&larr; Back</button>
                <h3>${esc(data.entity_name || '')}</h3>
                <span class="prov-entity-cov">${cov.with_evidence || 0}/${cov.total || 0} evidence-backed (${cov.coverage_pct || 0}%)</span>
            </div>
            <div class="prov-attr-header">
                <span class="prov-attr-h-slug">Attribute</span>
                <span class="prov-attr-h-value">Value</span>
                <span class="prov-attr-h-source">Source</span>
                <span class="prov-attr-h-chain">Chain</span>
                <span class="prov-attr-h-url">Link</span>
            </div>
            <div class="prov-attr-list">${rows}</div>
        </div>
    `;
}

function _closeEntityProvenance() {
    const content = document.getElementById('provContent');
    if (!content) return;
    if (window._provPreviousHtml) {
        content.innerHTML = window._provPreviousHtml;
        window._provPreviousHtml = null;
    } else {
        _loadProvenanceCoverage();
    }
}

// ── Sources View ───────────────────────────────────────────────

async function _loadProvenanceSources() {
    const content = document.getElementById('provContent');
    if (!content) return;
    content.innerHTML = '<div class="prov-loading">Loading sources&hellip;</div>';

    try {
        const resp = await safeFetch(`/api/provenance/project/${currentProjectId}/sources`);
        if (!resp.ok) {
            content.innerHTML = _provEmpty('No Sources', 'No source URLs recorded for this project.');
            return;
        }
        const data = await resp.json();
        content.innerHTML = _renderSourcesView(data);
    } catch (e) {
        console.warn('Provenance sources failed:', e);
        content.innerHTML = _provEmpty('Load Failed', 'Could not load sources.');
    }
}

function _renderSourcesView(data) {
    const sources = data.sources || [];
    if (!sources.length) {
        return _provEmpty('No Sources', 'Capture evidence with source URLs to see them listed here.');
    }

    const rows = sources.map(s => {
        const domain = _extractDomain(s.url);

        return `
            <div class="prov-source-row">
                <div class="prov-source-url">
                    <a href="${escAttr(s.url)}" target="_blank" rel="noopener" title="${escAttr(s.url)}">${esc(domain)}</a>
                </div>
                <div class="prov-source-entities">${esc((s.entities || []).join(', '))}</div>
                <div class="prov-source-count">${s.entity_count || 0} entities</div>
                <div class="prov-source-attrs">${s.attribute_count || 0} attrs</div>
                <div class="prov-source-types">${(s.evidence_types || []).map(t => `<span class="prov-type-badge">${esc(t)}</span>`).join(' ')}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="prov-sources-meta">${data.total_sources || sources.length} unique source URLs</div>
        <div class="prov-source-header">
            <span class="prov-source-h-url">URL</span>
            <span class="prov-source-h-entities">Entities</span>
            <span class="prov-source-h-count">Count</span>
            <span class="prov-source-h-attrs">Attrs</span>
            <span class="prov-source-h-types">Types</span>
        </div>
        <div class="prov-source-list">${rows}</div>
    `;
}

// ── Search View ────────────────────────────────────────────────

window._runProvenanceSearch = _runProvenanceSearch;

function _renderProvenanceSearch() {
    const content = document.getElementById('provContent');
    if (!content) return;

    content.innerHTML = `
        <div class="prov-search-form">
            <input type="text" id="provSearchInput" class="prov-search-input"
                   placeholder="Search attribute values..." autocomplete="off"
                   data-on-keyenter="run-provenance-search">
            <input type="text" id="provSearchSlug" class="prov-search-slug"
                   placeholder="Attribute slug (optional)" autocomplete="off">
            <button class="prov-search-btn" data-action="run-provenance-search">Search</button>
        </div>
        <div class="prov-search-results" id="provSearchResults">
            <div class="prov-search-hint">Enter a search term to find attributes and their provenance chains.</div>
        </div>
    `;
}

async function _runProvenanceSearch() {
    const q = (document.getElementById('provSearchInput') || {}).value || '';
    const slug = (document.getElementById('provSearchSlug') || {}).value || '';
    const results = document.getElementById('provSearchResults');
    if (!results || !q.trim()) return;

    results.innerHTML = '<div class="prov-loading">Searching&hellip;</div>';

    try {
        let url = `/api/provenance/search?project_id=${currentProjectId}&q=${encodeURIComponent(q.trim())}&limit=50`;
        if (slug.trim()) url += `&attr_slug=${encodeURIComponent(slug.trim())}`;

        const resp = await safeFetch(url);
        if (!resp.ok) {
            results.innerHTML = '<div class="prov-search-hint">Search failed.</div>';
            return;
        }
        const data = await resp.json();
        results.innerHTML = _renderSearchResults(data);
    } catch (e) {
        console.warn('Provenance search failed:', e);
        results.innerHTML = '<div class="prov-search-hint">Search failed.</div>';
    }
}

function _renderSearchResults(data) {
    const items = data.results || [];
    if (!items.length) {
        return '<div class="prov-search-hint">No matching attributes found.</div>';
    }

    const rows = items.map(r => {
        const chainLabel = r.chain_length === 4 ? 'full chain' :
                          r.chain_length === 2 ? 'extraction' :
                          r.source || 'manual';

        return `
            <div class="prov-search-row">
                <div class="prov-search-entity">${esc(r.entity_name || '')}</div>
                <div class="prov-search-attr">${esc(r.attr_slug || '')}</div>
                <div class="prov-search-value" title="${escAttr(r.value || '')}">${esc(_truncateProvLabel(r.value || '', 30))}</div>
                <div class="prov-search-chain">${esc(chainLabel)}</div>
                <div class="prov-search-url">${r.evidence_url ? `<a href="${escAttr(r.evidence_url)}" target="_blank" rel="noopener">source</a>` : ''}</div>
            </div>
        `;
    }).join('');

    return `
        <div class="prov-search-count">${data.total || items.length} results</div>
        <div class="prov-search-header">
            <span>Entity</span>
            <span>Attribute</span>
            <span>Value</span>
            <span>Chain</span>
            <span>Source</span>
        </div>
        ${rows}
    `;
}

// ── Utilities ──────────────────────────────────────────────────

function _provEmpty(title, desc) {
    return `
        <div class="prov-empty">
            <div class="prov-empty-title">${esc(title)}</div>
            <div class="prov-empty-desc">${esc(desc)}</div>
        </div>
    `;
}

function _truncateProvLabel(str, maxLen) {
    if (!str) return '';
    return str.length <= maxLen ? str : str.substring(0, maxLen - 1) + '\u2026';
}

function _extractDomain(url) {
    if (!url) return '';
    try {
        const u = new URL(url);
        return u.hostname.replace(/^www\./, '');
    } catch {
        return url.substring(0, 40);
    }
}

// --- Action Delegation ---
registerActions({
    'switch-provenance-view': (el) => _switchProvenanceView(el.dataset.view),
    'show-entity-provenance': (el) => _showEntityProvenance(Number(el.dataset.id)),
    'close-entity-provenance': () => _closeEntityProvenance(),
    'run-provenance-search': () => _runProvenanceSearch(),
});

// Handle Enter key on search input via delegation
document.addEventListener('keydown', (e) => {
    const el = e.target.closest('[data-on-keyenter]');
    if (!el || e.key !== 'Enter') return;
    const action = el.dataset.onKeyenter;
    const handler = _actionHandlers[action];
    if (handler) handler(el, e);
});
