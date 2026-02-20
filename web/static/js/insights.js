/**
 * Insights & Hypotheses -- Intelligence tab sub-view.
 *
 * Sub-views: insights (pattern detection) and hypotheses (claim tracking).
 * Lives inside #tab-intelligence alongside the Monitoring dashboard.
 * Users toggle between "Monitoring", "Insights", and "Hypotheses" via sub-nav.
 *
 * API prefix: /api/insights/...
 */

// ── State ──────────────────────────────────────────────────────
let _insightsLoaded = false;
let _currentInsightView = 'insights'; // 'insights' | 'hypotheses'
let _insightsList = [];
let _insightsSummary = null;
let _insightsFilters = {};             // {type, severity, category, source, is_dismissed}
let _hypothesesList = [];
let _hypothesesFilters = {};           // {status, category}
let _insightsGenerating = false;
let _viewingHypothesisId = null;       // Currently expanded hypothesis detail

// ── Public API ─────────────────────────────────────────────────

window.initInsights = initInsights;
window._switchIntelligenceView = _switchIntelligenceView;

/**
 * Entry point -- called when Intelligence tab is shown.
 * Sets up the sub-navigation if not already present, then loads
 * whichever sub-view is currently selected.
 */
function initInsights() {
    if (!currentProjectId) return;

    _ensureIntelligenceSubNav();

    // Load the currently selected sub-view
    if (_currentInsightView === 'insights') {
        _loadInsightsDashboard();
    } else if (_currentInsightView === 'hypotheses') {
        _loadHypothesesDashboard();
    }
    // 'monitoring' is handled by initMonitoring() directly
}

// ── Sub-Navigation ─────────────────────────────────────────────

/**
 * Build the sub-nav bar inside the intelligence tab if it does not
 * already exist. Three views: Monitoring, Insights, Hypotheses.
 */
function _ensureIntelligenceSubNav() {
    const tab = document.getElementById('tab-intelligence');
    if (!tab) return;

    // Already injected?
    if (document.getElementById('intelligenceSubNav')) return;

    // Create sub-nav
    const nav = document.createElement('div');
    nav.id = 'intelligenceSubNav';
    nav.className = 'intel-sub-nav';
    nav.innerHTML = `
        <button class="intel-sub-btn intel-sub-btn--active" data-view="monitoring"
                onclick="_switchIntelligenceView('monitoring')">Monitoring</button>
        <button class="intel-sub-btn" data-view="insights"
                onclick="_switchIntelligenceView('insights')">Insights</button>
        <button class="intel-sub-btn" data-view="hypotheses"
                onclick="_switchIntelligenceView('hypotheses')">Hypotheses</button>
    `;
    tab.insertBefore(nav, tab.firstChild);

    // Create insights container (hidden by default)
    const insightsContainer = document.createElement('div');
    insightsContainer.id = 'insightsDashboard';
    insightsContainer.className = 'insights-dashboard hidden';
    insightsContainer.innerHTML = `
        <div class="insights-header">
            <h2>Insights</h2>
            <div class="insights-header-actions">
                <button class="ins-btn" onclick="_generateInsights()" id="insightsGenerateBtn">Detect Patterns</button>
                <button class="ins-btn ins-btn-ghost" onclick="_generateAiInsights()" id="insightsAiBtn">AI Enhance</button>
            </div>
        </div>
        <div class="insights-stats" id="insightsStatsBar"></div>
        <div class="insights-filters" id="insightsFilters"></div>
        <div class="insights-list" id="insightsList"></div>
        <div class="insights-empty hidden" id="insightsEmpty">
            <div class="insights-empty-title">No insights yet</div>
            <div class="insights-empty-desc">Run pattern detection to discover insights from your research data.</div>
            <button class="ins-btn" onclick="_generateInsights()">Detect Patterns</button>
        </div>
    `;
    tab.appendChild(insightsContainer);

    // Create hypotheses container (hidden by default)
    const hypothesesContainer = document.createElement('div');
    hypothesesContainer.id = 'hypothesesDashboard';
    hypothesesContainer.className = 'hypotheses-dashboard hidden';
    hypothesesContainer.innerHTML = `
        <div class="hypotheses-header">
            <h2>Hypotheses</h2>
            <div class="hypotheses-header-actions">
                <button class="ins-btn" onclick="_createHypothesis()">+ New Hypothesis</button>
            </div>
        </div>
        <div class="hypotheses-filters" id="hypothesesFilters"></div>
        <div class="hypotheses-list" id="hypothesesList"></div>
        <div class="hypotheses-empty hidden" id="hypothesesEmpty">
            <div class="hypotheses-empty-title">No hypotheses yet</div>
            <div class="hypotheses-empty-desc">Create a hypothesis to track and test claims about your market.</div>
            <button class="ins-btn" onclick="_createHypothesis()">+ New Hypothesis</button>
        </div>
        <div class="hypothesis-detail hidden" id="hypothesisDetail"></div>
    `;
    tab.appendChild(hypothesesContainer);
}

/**
 * Switch between monitoring, insights, and hypotheses sub-views.
 */
function _switchIntelligenceView(view) {
    _currentInsightView = view;

    // Update sub-nav active state
    document.querySelectorAll('.intel-sub-btn').forEach(btn => {
        btn.classList.toggle('intel-sub-btn--active', btn.dataset.view === view);
    });

    // Toggle containers
    const monitoringEl = document.getElementById('monitoringDashboard');
    const insightsEl = document.getElementById('insightsDashboard');
    const hypothesesEl = document.getElementById('hypothesesDashboard');

    if (monitoringEl) monitoringEl.classList.toggle('hidden', view !== 'monitoring');
    if (insightsEl) insightsEl.classList.toggle('hidden', view !== 'insights');
    if (hypothesesEl) hypothesesEl.classList.toggle('hidden', view !== 'hypotheses');

    // Load data for the selected view
    if (view === 'monitoring') {
        if (typeof initMonitoring === 'function') initMonitoring();
    } else if (view === 'insights') {
        _loadInsightsDashboard();
    } else if (view === 'hypotheses') {
        _loadHypothesesDashboard();
    }
}

// ── Insights Dashboard ─────────────────────────────────────────

async function _loadInsightsDashboard() {
    if (!currentProjectId) return;
    await Promise.all([
        _loadInsightsSummary(),
        _loadInsights(),
    ]);
}

// ── Insights Summary ───────────────────────────────────────────

async function _loadInsightsSummary() {
    if (!currentProjectId) return;
    try {
        const resp = await safeFetch(`/api/insights/summary?project_id=${currentProjectId}`);
        if (!resp.ok) return;
        _insightsSummary = await resp.json();
        _renderInsightStats(_insightsSummary);
    } catch (e) {
        console.warn('Failed to load insights summary:', e);
    }
}

function _renderInsightStats(summary) {
    const el = document.getElementById('insightsStatsBar');
    if (!el || !summary) return;

    const total = summary.total || 0;
    const bySeverity = summary.by_severity || {};
    const bySource = summary.by_source || {};
    const pinned = summary.pinned || 0;

    el.innerHTML = `
        <div class="ins-stat">
            <span class="ins-stat-value">${total}</span>
            <span class="ins-stat-label">Total</span>
        </div>
        <div class="ins-stat ${(bySeverity.critical || 0) > 0 ? 'ins-stat-critical' : ''}">
            <span class="ins-stat-value">${bySeverity.critical || 0}</span>
            <span class="ins-stat-label">Critical</span>
        </div>
        <div class="ins-stat ${(bySeverity.important || 0) > 0 ? 'ins-stat-important' : ''}">
            <span class="ins-stat-value">${bySeverity.important || 0}</span>
            <span class="ins-stat-label">Important</span>
        </div>
        <div class="ins-stat">
            <span class="ins-stat-value">${bySeverity.notable || 0}</span>
            <span class="ins-stat-label">Notable</span>
        </div>
        <div class="ins-stat">
            <span class="ins-stat-value">${bySeverity.info || 0}</span>
            <span class="ins-stat-label">Info</span>
        </div>
        <div class="ins-stat">
            <span class="ins-stat-value">${pinned}</span>
            <span class="ins-stat-label">Pinned</span>
        </div>
    `;
}

// ── Insights List ──────────────────────────────────────────────

async function _loadInsights(filters) {
    if (!currentProjectId) return;

    if (filters) _insightsFilters = filters;

    let url = `/api/insights?project_id=${currentProjectId}`;
    if (_insightsFilters.type) url += `&type=${encodeURIComponent(_insightsFilters.type)}`;
    if (_insightsFilters.severity) url += `&severity=${encodeURIComponent(_insightsFilters.severity)}`;
    if (_insightsFilters.category) url += `&category=${encodeURIComponent(_insightsFilters.category)}`;
    if (_insightsFilters.source) url += `&source=${encodeURIComponent(_insightsFilters.source)}`;
    if (_insightsFilters.is_dismissed !== undefined && _insightsFilters.is_dismissed !== null) {
        url += `&is_dismissed=${_insightsFilters.is_dismissed}`;
    }

    try {
        const resp = await safeFetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        _insightsList = data.insights || data || [];
        _renderInsights();
    } catch (e) {
        console.warn('Failed to load insights:', e);
    }
}

function _renderInsights() {
    const container = document.getElementById('insightsList');
    const emptyEl = document.getElementById('insightsEmpty');
    if (!container) return;

    _renderInsightFilters();

    if (!_insightsList || _insightsList.length === 0) {
        container.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    // Sort: pinned first, then by severity weight, then by created_at desc
    const severityOrder = { critical: 0, important: 1, notable: 2, info: 3 };
    const sorted = [..._insightsList].sort((a, b) => {
        if (a.is_pinned && !b.is_pinned) return -1;
        if (!a.is_pinned && b.is_pinned) return 1;
        const sa = severityOrder[a.severity] ?? 4;
        const sb = severityOrder[b.severity] ?? 4;
        if (sa !== sb) return sa - sb;
        return (b.created_at || '').localeCompare(a.created_at || '');
    });

    container.innerHTML = sorted.map((insight, idx) => _renderInsightCard(insight, idx)).join('');
}

function _renderInsightCard(insight, idx) {
    const severity = (insight.severity || 'info').toLowerCase();
    const type = insight.type || 'pattern';
    const isPinned = insight.is_pinned;
    const isDismissed = insight.is_dismissed;
    const evidenceCount = insight.evidence_count || insight.supporting_data?.length || 0;
    const timeAgo = insight.created_at ? _insRelativeTime(insight.created_at) : '';
    const source = insight.source || 'rule';
    const category = insight.category || '';

    const classes = [
        'insight-card',
        isPinned ? 'insight-card--pinned' : '',
        isDismissed ? 'insight-card--dismissed' : '',
    ].filter(Boolean).join(' ');

    return `
        <div class="${classes}" data-insight-id="${insight.id}" style="--i:${idx}">
            <div class="insight-card__left">
                ${_insightSeverityBadge(severity)}
                <div class="insight-card__content">
                    <div class="insight-card__title-row">
                        <span class="insight-card__type-badge">${esc(_formatInsightType(type))}</span>
                        ${isPinned ? '<span class="insight-card__pin-indicator" title="Pinned">PIN</span>' : ''}
                        <span class="insight-card__title">${esc(insight.title || '')}</span>
                    </div>
                    <div class="insight-card__description">${esc(insight.description || '')}</div>
                    <div class="insight-card__meta">
                        <span class="insight-card__time">${esc(timeAgo)}</span>
                        <span class="insight-card__sep">&middot;</span>
                        <span class="insight-card__source">${esc(source)}</span>
                        ${category ? `<span class="insight-card__sep">&middot;</span><span class="insight-card__category">${esc(category)}</span>` : ''}
                        ${evidenceCount > 0 ? `<span class="insight-card__sep">&middot;</span><span class="insight-card__evidence">${evidenceCount} evidence</span>` : ''}
                    </div>
                </div>
            </div>
            <div class="insight-card__actions">
                <button class="ins-btn ins-btn-sm ${isPinned ? 'ins-btn-active' : 'ins-btn-ghost'}"
                        onclick="event.stopPropagation(); _pinInsight(${insight.id})"
                        title="${isPinned ? 'Unpin' : 'Pin'}">
                    ${isPinned ? 'Unpin' : 'Pin'}
                </button>
                ${!isDismissed ? `
                    <button class="ins-btn ins-btn-sm ins-btn-ghost"
                            onclick="event.stopPropagation(); _dismissInsight(${insight.id})"
                            title="Dismiss">Dismiss</button>
                ` : ''}
                <button class="ins-btn ins-btn-sm ins-btn-danger"
                        onclick="event.stopPropagation(); _deleteInsight(${insight.id})"
                        title="Delete">Delete</button>
            </div>
        </div>
    `;
}

function _renderInsightFilters() {
    const el = document.getElementById('insightsFilters');
    if (!el) return;

    const typeOptions = [
        { value: '', label: 'All types' },
        { value: 'coverage_gap', label: 'Coverage Gap' },
        { value: 'data_quality', label: 'Data Quality' },
        { value: 'cluster', label: 'Cluster' },
        { value: 'outlier', label: 'Outlier' },
        { value: 'trend', label: 'Trend' },
        { value: 'correlation', label: 'Correlation' },
        { value: 'contradiction', label: 'Contradiction' },
    ];

    const severityOptions = [
        { value: '', label: 'All severity' },
        { value: 'critical', label: 'Critical' },
        { value: 'important', label: 'Important' },
        { value: 'notable', label: 'Notable' },
        { value: 'info', label: 'Info' },
    ];

    const sourceOptions = [
        { value: '', label: 'All sources' },
        { value: 'rule', label: 'Rule-based' },
        { value: 'ai', label: 'AI-generated' },
    ];

    const currentType = _insightsFilters.type || '';
    const currentSeverity = _insightsFilters.severity || '';
    const currentSource = _insightsFilters.source || '';

    el.innerHTML = `
        <div class="ins-filter-group">
            <select class="ins-filter-select" onchange="_setInsightFilter('type', this.value)" aria-label="Filter by type">
                ${typeOptions.map(o => `<option value="${o.value}" ${o.value === currentType ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
            <select class="ins-filter-select" onchange="_setInsightFilter('severity', this.value)" aria-label="Filter by severity">
                ${severityOptions.map(o => `<option value="${o.value}" ${o.value === currentSeverity ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
            <select class="ins-filter-select" onchange="_setInsightFilter('source', this.value)" aria-label="Filter by source">
                ${sourceOptions.map(o => `<option value="${o.value}" ${o.value === currentSource ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
        </div>
        <div class="ins-filter-group">
            <label class="ins-filter-checkbox">
                <input type="checkbox" ${_insightsFilters.is_dismissed ? 'checked' : ''}
                       onchange="_setInsightFilter('is_dismissed', this.checked ? '1' : null)">
                <span>Show dismissed</span>
            </label>
        </div>
    `;
}

function _setInsightFilter(key, value) {
    if (value) {
        _insightsFilters[key] = value;
    } else {
        delete _insightsFilters[key];
    }
    _loadInsights();
}

// ── Insight Actions ────────────────────────────────────────────

async function _generateInsights() {
    if (!currentProjectId || _insightsGenerating) return;
    _insightsGenerating = true;

    const btn = document.getElementById('insightsGenerateBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Detecting...';
    }

    try {
        const resp = await safeFetch(`/api/insights/generate?project_id=${currentProjectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to generate insights');
            return;
        }

        const data = await resp.json();
        const count = data.generated || data.count || 0;
        showToast(`Detected ${count} insight${count !== 1 ? 's' : ''}`);
        await _loadInsightsDashboard();
    } catch (e) {
        console.error('Insight generation failed:', e);
        showToast('Insight generation failed');
    } finally {
        _insightsGenerating = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Detect Patterns';
        }
    }
}

async function _generateAiInsights() {
    if (!currentProjectId || _insightsGenerating) return;

    const confirmed = await window.showNativeConfirm({
        title: 'AI-Enhanced Insights',
        message: 'This will use an LLM to analyse your data and generate deeper insights. This may take a moment and will consume API credits.',
        confirmText: 'Generate',
        type: 'warning',
    });
    if (!confirmed) return;

    _insightsGenerating = true;
    const btn = document.getElementById('insightsAiBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Generating...';
    }

    try {
        const resp = await safeFetch(`/api/insights/generate-ai?project_id=${currentProjectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'AI insight generation failed');
            return;
        }

        const data = await resp.json();
        const count = data.generated || data.count || 0;
        showToast(`AI generated ${count} insight${count !== 1 ? 's' : ''}`);
        await _loadInsightsDashboard();
    } catch (e) {
        console.error('AI insight generation failed:', e);
        showToast('AI insight generation failed');
    } finally {
        _insightsGenerating = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'AI Enhance';
        }
    }
}

async function _dismissInsight(id) {
    try {
        const resp = await safeFetch(`/api/insights/${id}/dismiss`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) return;

        // Update local state
        const insight = _insightsList.find(i => i.id === id);
        if (insight) insight.is_dismissed = true;

        // Animate card out
        const card = document.querySelector(`[data-insight-id="${id}"]`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateX(20px)';
            setTimeout(() => {
                if (!_insightsFilters.is_dismissed) {
                    _insightsList = _insightsList.filter(i => i.id !== id);
                }
                _renderInsights();
            }, 200);
        }

        _loadInsightsSummary();
        showToast('Insight dismissed');
    } catch (e) {
        console.warn('Failed to dismiss insight:', e);
    }
}

async function _pinInsight(id) {
    try {
        const resp = await safeFetch(`/api/insights/${id}/pin`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) return;

        // Toggle local state
        const insight = _insightsList.find(i => i.id === id);
        if (insight) insight.is_pinned = !insight.is_pinned;

        _renderInsights();
        _loadInsightsSummary();
    } catch (e) {
        console.warn('Failed to toggle pin:', e);
    }
}

async function _deleteInsight(id) {
    const confirmed = await window.showNativeConfirm({
        title: 'Delete Insight',
        message: 'This will permanently remove this insight.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/insights/${id}`, {
            method: 'DELETE',
        });
        if (!resp.ok) return;

        // Animate removal
        const card = document.querySelector(`[data-insight-id="${id}"]`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateX(20px)';
            setTimeout(() => {
                _insightsList = _insightsList.filter(i => i.id !== id);
                _renderInsights();
                _loadInsightsSummary();
            }, 200);
        }

        showToast('Insight deleted');
    } catch (e) {
        console.warn('Failed to delete insight:', e);
    }
}

// ── Hypotheses Dashboard ───────────────────────────────────────

async function _loadHypothesesDashboard() {
    if (!currentProjectId) return;
    _viewingHypothesisId = null;
    const detailEl = document.getElementById('hypothesisDetail');
    if (detailEl) detailEl.classList.add('hidden');
    await _loadHypotheses();
}

async function _loadHypotheses(filters) {
    if (!currentProjectId) return;

    if (filters) _hypothesesFilters = filters;

    let url = `/api/insights/hypotheses?project_id=${currentProjectId}`;
    if (_hypothesesFilters.status) url += `&status=${encodeURIComponent(_hypothesesFilters.status)}`;
    if (_hypothesesFilters.category) url += `&category=${encodeURIComponent(_hypothesesFilters.category)}`;

    try {
        const resp = await safeFetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        _hypothesesList = data.hypotheses || data || [];
        _renderHypotheses();
    } catch (e) {
        console.warn('Failed to load hypotheses:', e);
    }
}

function _renderHypotheses() {
    const container = document.getElementById('hypothesesList');
    const emptyEl = document.getElementById('hypothesesEmpty');
    if (!container) return;

    _renderHypothesesFilters();

    if (!_hypothesesList || _hypothesesList.length === 0) {
        container.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    container.innerHTML = _hypothesesList.map((hyp, idx) => _renderHypothesisCard(hyp, idx)).join('');
}

function _renderHypothesisCard(hyp, idx) {
    const status = (hyp.status || 'open').toLowerCase();
    const confidence = hyp.confidence ?? hyp.computed_confidence ?? null;
    const evidenceCount = hyp.evidence_count || 0;
    const supCount = hyp.supporting_count || 0;
    const conCount = hyp.contradicting_count || 0;
    const category = hyp.category || '';
    const timeAgo = hyp.created_at ? _insRelativeTime(hyp.created_at) : '';

    return `
        <div class="hypothesis-card" data-hypothesis-id="${hyp.id}" style="--i:${idx}"
             onclick="_viewHypothesis(${hyp.id})">
            <div class="hypothesis-card__top">
                <div class="hypothesis-card__header">
                    <span class="hypothesis-status-badge hypothesis-status--${esc(status)}">${esc(_formatHypothesisStatus(status))}</span>
                    ${category ? `<span class="hypothesis-card__category">${esc(category)}</span>` : ''}
                </div>
                <div class="hypothesis-card__statement">${esc(hyp.statement || '')}</div>
            </div>
            <div class="hypothesis-card__bottom">
                <div class="hypothesis-card__confidence-row">
                    ${confidence !== null ? _renderConfidenceBar(confidence) : '<span class="hypothesis-card__no-evidence">No evidence yet</span>'}
                </div>
                <div class="hypothesis-card__meta">
                    <span class="hypothesis-card__evidence-summary">
                        <span class="hyp-ev-sup" title="Supporting">${supCount} sup</span>
                        <span class="hypothesis-card__sep">/</span>
                        <span class="hyp-ev-con" title="Contradicting">${conCount} con</span>
                        <span class="hypothesis-card__sep">&middot;</span>
                        <span>${evidenceCount} total</span>
                    </span>
                    <span class="hypothesis-card__time">${esc(timeAgo)}</span>
                </div>
            </div>
            <div class="hypothesis-card__actions">
                <button class="ins-btn ins-btn-sm ins-btn-ghost"
                        onclick="event.stopPropagation(); _updateHypothesis(${hyp.id})"
                        title="Edit">Edit</button>
                <button class="ins-btn ins-btn-sm ins-btn-danger"
                        onclick="event.stopPropagation(); _deleteHypothesis(${hyp.id})"
                        title="Delete">Delete</button>
            </div>
        </div>
    `;
}

function _renderConfidenceBar(confidence) {
    const pct = Math.round((confidence || 0) * 100);
    let level = 'low';
    if (confidence >= 0.7) level = 'high';
    else if (confidence >= 0.4) level = 'medium';

    return `
        <div class="confidence-bar" title="Confidence: ${pct}%">
            <div class="confidence-bar__track">
                <div class="confidence-bar__fill confidence-bar--${level}" style="width: ${pct}%"></div>
            </div>
            <span class="confidence-bar__label">${pct}%</span>
        </div>
    `;
}

function _renderHypothesesFilters() {
    const el = document.getElementById('hypothesesFilters');
    if (!el) return;

    const statusOptions = [
        { value: '', label: 'All statuses' },
        { value: 'open', label: 'Open' },
        { value: 'supported', label: 'Supported' },
        { value: 'refuted', label: 'Refuted' },
        { value: 'inconclusive', label: 'Inconclusive' },
    ];

    const currentStatus = _hypothesesFilters.status || '';

    el.innerHTML = `
        <div class="ins-filter-group">
            <select class="ins-filter-select" onchange="_setHypothesisFilter('status', this.value)" aria-label="Filter by status">
                ${statusOptions.map(o => `<option value="${o.value}" ${o.value === currentStatus ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
        </div>
    `;
}

function _setHypothesisFilter(key, value) {
    if (value) {
        _hypothesesFilters[key] = value;
    } else {
        delete _hypothesesFilters[key];
    }
    _loadHypotheses();
}

// ── Hypothesis CRUD ────────────────────────────────────────────

function _createHypothesis() {
    if (!currentProjectId) return;

    _ensureHypothesisFormModal();
    const overlay = document.getElementById('hypothesisFormModal');
    const titleEl = document.getElementById('hypFormTitle');
    const stmtInput = document.getElementById('hypFormStatement');
    const catInput = document.getElementById('hypFormCategory');
    const submitBtn = document.getElementById('hypFormSubmit');

    titleEl.textContent = 'New Hypothesis';
    stmtInput.value = '';
    catInput.value = '';
    submitBtn.textContent = 'Create';
    submitBtn.dataset.mode = 'create';
    submitBtn.dataset.hypId = '';

    overlay.style.display = 'flex';
    requestAnimationFrame(() => {
        overlay.classList.add('visible');
        stmtInput.focus();
    });
}

function _updateHypothesis(id) {
    const hyp = _hypothesesList.find(h => h.id === id);
    if (!hyp) return;

    _ensureHypothesisFormModal();
    const overlay = document.getElementById('hypothesisFormModal');
    const titleEl = document.getElementById('hypFormTitle');
    const stmtInput = document.getElementById('hypFormStatement');
    const catInput = document.getElementById('hypFormCategory');
    const statusSelect = document.getElementById('hypFormStatus');
    const submitBtn = document.getElementById('hypFormSubmit');

    titleEl.textContent = 'Edit Hypothesis';
    stmtInput.value = hyp.statement || '';
    catInput.value = hyp.category || '';
    if (statusSelect) statusSelect.value = hyp.status || 'open';
    submitBtn.textContent = 'Save';
    submitBtn.dataset.mode = 'edit';
    submitBtn.dataset.hypId = String(id);

    overlay.style.display = 'flex';
    requestAnimationFrame(() => {
        overlay.classList.add('visible');
        stmtInput.focus();
    });
}

async function _submitHypothesisForm() {
    const submitBtn = document.getElementById('hypFormSubmit');
    const stmtInput = document.getElementById('hypFormStatement');
    const catInput = document.getElementById('hypFormCategory');
    const statusSelect = document.getElementById('hypFormStatus');

    const statement = (stmtInput?.value || '').trim();
    if (!statement) {
        showToast('Statement is required');
        return;
    }

    const mode = submitBtn.dataset.mode;
    const hypId = submitBtn.dataset.hypId;

    submitBtn.disabled = true;

    try {
        if (mode === 'create') {
            const body = {
                project_id: currentProjectId,
                statement: statement,
            };
            if (catInput?.value.trim()) body.category = catInput.value.trim();

            const resp = await safeFetch('/api/insights/hypotheses', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showToast(err.error || 'Failed to create hypothesis');
                return;
            }
            showToast('Hypothesis created');
        } else {
            const body = { statement: statement };
            if (catInput?.value.trim()) body.category = catInput.value.trim();
            if (statusSelect?.value) body.status = statusSelect.value;

            const resp = await safeFetch(`/api/insights/hypotheses/${hypId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showToast(err.error || 'Failed to update hypothesis');
                return;
            }
            showToast('Hypothesis updated');
        }

        _closeHypothesisForm();
        await _loadHypotheses();
    } catch (e) {
        console.error('Hypothesis form submit failed:', e);
        showToast('Operation failed');
    } finally {
        submitBtn.disabled = false;
    }
}

function _closeHypothesisForm() {
    const overlay = document.getElementById('hypothesisFormModal');
    if (!overlay) return;
    overlay.classList.remove('visible');
    setTimeout(() => { overlay.style.display = 'none'; }, 200);
}

async function _deleteHypothesis(id) {
    const confirmed = await window.showNativeConfirm({
        title: 'Delete Hypothesis',
        message: 'This will permanently remove this hypothesis and all its evidence.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/insights/hypotheses/${id}`, {
            method: 'DELETE',
        });
        if (!resp.ok) return;

        const card = document.querySelector(`[data-hypothesis-id="${id}"]`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateX(20px)';
            setTimeout(() => {
                _hypothesesList = _hypothesesList.filter(h => h.id !== id);
                _renderHypotheses();
            }, 200);
        }

        // Close detail if we were viewing this one
        if (_viewingHypothesisId === id) {
            _viewingHypothesisId = null;
            const detailEl = document.getElementById('hypothesisDetail');
            if (detailEl) detailEl.classList.add('hidden');
        }

        showToast('Hypothesis deleted');
    } catch (e) {
        console.warn('Failed to delete hypothesis:', e);
    }
}

// ── Hypothesis Detail View ─────────────────────────────────────

async function _viewHypothesis(id) {
    _viewingHypothesisId = id;

    const listEl = document.getElementById('hypothesesList');
    const detailEl = document.getElementById('hypothesisDetail');
    const filtersEl = document.getElementById('hypothesesFilters');
    const emptyEl = document.getElementById('hypothesesEmpty');
    if (!detailEl) return;

    // Hide list, show detail
    if (listEl) listEl.classList.add('hidden');
    if (filtersEl) filtersEl.classList.add('hidden');
    if (emptyEl) emptyEl.classList.add('hidden');
    detailEl.classList.remove('hidden');
    detailEl.innerHTML = '<div class="hypothesis-detail-loading">Loading...</div>';

    try {
        const resp = await safeFetch(`/api/insights/hypotheses/${id}`);
        if (!resp.ok) {
            detailEl.innerHTML = '<div class="hypothesis-detail-error">Failed to load hypothesis</div>';
            return;
        }

        const hyp = await resp.json();
        _renderHypothesisDetail(hyp);
    } catch (e) {
        console.warn('Failed to load hypothesis detail:', e);
        detailEl.innerHTML = '<div class="hypothesis-detail-error">Failed to load hypothesis</div>';
    }
}

function _renderHypothesisDetail(hyp) {
    const detailEl = document.getElementById('hypothesisDetail');
    if (!detailEl) return;

    const status = (hyp.status || 'open').toLowerCase();
    const confidence = hyp.confidence ?? hyp.computed_confidence ?? null;
    const evidenceList = hyp.evidence || [];
    const category = hyp.category || '';
    const timeAgo = hyp.created_at ? _insRelativeTime(hyp.created_at) : '';

    detailEl.innerHTML = `
        <div class="hypothesis-detail__header">
            <button class="ins-btn ins-btn-ghost" onclick="_backToHypothesesList()">Back</button>
            <div class="hypothesis-detail__actions">
                <button class="ins-btn ins-btn-sm" onclick="_updateHypothesis(${hyp.id})">Edit</button>
                <button class="ins-btn ins-btn-sm ins-btn-danger" onclick="_deleteHypothesis(${hyp.id})">Delete</button>
            </div>
        </div>

        <div class="hypothesis-detail__body">
            <div class="hypothesis-detail__status-row">
                <span class="hypothesis-status-badge hypothesis-status--${esc(status)}">${esc(_formatHypothesisStatus(status))}</span>
                ${category ? `<span class="hypothesis-detail__category">${esc(category)}</span>` : ''}
                <span class="hypothesis-detail__time">${esc(timeAgo)}</span>
            </div>

            <div class="hypothesis-detail__statement">${esc(hyp.statement || '')}</div>

            ${confidence !== null ? `
                <div class="hypothesis-detail__confidence">
                    <span class="hypothesis-detail__conf-label">Confidence</span>
                    ${_renderConfidenceBar(confidence)}
                </div>
            ` : ''}
        </div>

        <div class="hypothesis-detail__evidence-section">
            <div class="hypothesis-detail__evidence-header">
                <span class="hypothesis-detail__evidence-title">Evidence (${evidenceList.length})</span>
                <button class="ins-btn ins-btn-sm" onclick="_addHypothesisEvidence(${hyp.id})">+ Add Evidence</button>
            </div>

            <div class="hypothesis-detail__evidence-list" id="hypothesisEvidenceList">
                ${evidenceList.length === 0
                    ? '<div class="hypothesis-detail__no-evidence">No evidence recorded. Add supporting or contradicting evidence to build confidence.</div>'
                    : evidenceList.map(ev => _renderEvidenceRow(hyp.id, ev)).join('')
                }
            </div>
        </div>
    `;
}

function _renderEvidenceRow(hypothesisId, ev) {
    const direction = (ev.direction || 'neutral').toLowerCase();
    const weight = ev.weight || 1;
    const description = ev.description || '';
    const entityName = ev.entity_name || '';
    const source = ev.source || '';
    const timeAgo = ev.created_at ? _insRelativeTime(ev.created_at) : '';

    const weightDots = Array.from({ length: 5 }, (_, i) =>
        `<span class="weight-dot ${i < weight ? 'weight-dot--active' : ''}"></span>`
    ).join('');

    return `
        <div class="evidence-row evidence-row--${esc(direction)}" data-evidence-id="${ev.id}">
            <div class="evidence-row__left">
                <span class="evidence-direction evidence-direction--${esc(direction)}">${esc(_formatDirection(direction))}</span>
                <div class="evidence-row__content">
                    <div class="evidence-row__description">${esc(description)}</div>
                    <div class="evidence-row__meta">
                        ${entityName ? `<span class="evidence-row__entity">${esc(entityName)}</span><span class="evidence-row__sep">&middot;</span>` : ''}
                        ${source ? `<span class="evidence-row__source">${esc(source)}</span><span class="evidence-row__sep">&middot;</span>` : ''}
                        <span class="evidence-row__weight">${weightDots}</span>
                        <span class="evidence-row__sep">&middot;</span>
                        <span class="evidence-row__time">${esc(timeAgo)}</span>
                    </div>
                </div>
            </div>
            <div class="evidence-row__actions">
                <button class="ins-btn ins-btn-sm ins-btn-danger"
                        onclick="event.stopPropagation(); _removeHypothesisEvidence(${hypothesisId}, ${ev.id})"
                        title="Remove">Remove</button>
            </div>
        </div>
    `;
}

function _backToHypothesesList() {
    _viewingHypothesisId = null;

    const listEl = document.getElementById('hypothesesList');
    const detailEl = document.getElementById('hypothesisDetail');
    const filtersEl = document.getElementById('hypothesesFilters');

    if (detailEl) detailEl.classList.add('hidden');
    if (listEl) listEl.classList.remove('hidden');
    if (filtersEl) filtersEl.classList.remove('hidden');

    // Refresh list
    _loadHypotheses();
}

// ── Hypothesis Evidence CRUD ───────────────────────────────────

function _addHypothesisEvidence(hypothesisId) {
    _ensureEvidenceFormModal();
    const overlay = document.getElementById('evidenceFormModal');
    const dirSelect = document.getElementById('evFormDirection');
    const weightInput = document.getElementById('evFormWeight');
    const descInput = document.getElementById('evFormDescription');
    const entityInput = document.getElementById('evFormEntity');
    const sourceInput = document.getElementById('evFormSource');
    const submitBtn = document.getElementById('evFormSubmit');

    // Reset form
    if (dirSelect) dirSelect.value = 'supports';
    if (weightInput) weightInput.value = '3';
    if (descInput) descInput.value = '';
    if (entityInput) entityInput.value = '';
    if (sourceInput) sourceInput.value = '';
    submitBtn.dataset.hypothesisId = String(hypothesisId);

    overlay.style.display = 'flex';
    requestAnimationFrame(() => {
        overlay.classList.add('visible');
        if (descInput) descInput.focus();
    });
}

async function _submitEvidenceForm() {
    const submitBtn = document.getElementById('evFormSubmit');
    const dirSelect = document.getElementById('evFormDirection');
    const weightInput = document.getElementById('evFormWeight');
    const descInput = document.getElementById('evFormDescription');
    const entityInput = document.getElementById('evFormEntity');
    const sourceInput = document.getElementById('evFormSource');

    const hypothesisId = submitBtn.dataset.hypothesisId;
    const description = (descInput?.value || '').trim();

    if (!description) {
        showToast('Description is required');
        return;
    }

    const body = {
        direction: dirSelect?.value || 'neutral',
        weight: parseInt(weightInput?.value || '3', 10),
        description: description,
    };
    if (entityInput?.value.trim()) body.entity_id = parseInt(entityInput.value.trim(), 10);
    if (sourceInput?.value.trim()) body.source = sourceInput.value.trim();

    submitBtn.disabled = true;

    try {
        const resp = await safeFetch(`/api/insights/hypotheses/${hypothesisId}/evidence`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to add evidence');
            return;
        }

        showToast('Evidence added');
        _closeEvidenceForm();

        // Refresh the detail view
        if (_viewingHypothesisId) {
            await _viewHypothesis(_viewingHypothesisId);
        }
    } catch (e) {
        console.error('Add evidence failed:', e);
        showToast('Failed to add evidence');
    } finally {
        submitBtn.disabled = false;
    }
}

function _closeEvidenceForm() {
    const overlay = document.getElementById('evidenceFormModal');
    if (!overlay) return;
    overlay.classList.remove('visible');
    setTimeout(() => { overlay.style.display = 'none'; }, 200);
}

async function _removeHypothesisEvidence(hypothesisId, evidenceId) {
    const confirmed = await window.showNativeConfirm({
        title: 'Remove Evidence',
        message: 'Remove this piece of evidence from the hypothesis?',
        confirmText: 'Remove',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/insights/hypotheses/${hypothesisId}/evidence/${evidenceId}`, {
            method: 'DELETE',
        });
        if (!resp.ok) return;

        // Animate removal
        const row = document.querySelector(`[data-evidence-id="${evidenceId}"]`);
        if (row) {
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            setTimeout(() => {
                // Refresh detail
                if (_viewingHypothesisId) _viewHypothesis(_viewingHypothesisId);
            }, 200);
        }

        showToast('Evidence removed');
    } catch (e) {
        console.warn('Failed to remove evidence:', e);
    }
}

// ── Modal Builders ─────────────────────────────────────────────

function _ensureHypothesisFormModal() {
    if (document.getElementById('hypothesisFormModal')) return;
    const html = `
        <div id="hypothesisFormModal" class="confirm-sheet-overlay" style="display:none;">
            <div class="confirm-sheet ins-modal">
                <div id="hypFormTitle" class="confirm-sheet-title ins-modal-title">New Hypothesis</div>
                <div class="ins-modal-form">
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="hypFormStatement">Statement</label>
                        <textarea id="hypFormStatement" class="ins-form-textarea"
                                  placeholder="e.g. Companies with mobile apps have higher retention rates"
                                  rows="3"></textarea>
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="hypFormCategory">Category (optional)</label>
                        <input id="hypFormCategory" type="text" class="ins-form-input"
                               placeholder="e.g. pricing, features, market">
                    </div>
                    <div class="ins-form-field" id="hypFormStatusGroup">
                        <label class="ins-form-label" for="hypFormStatus">Status</label>
                        <select id="hypFormStatus" class="ins-form-select">
                            <option value="open">Open</option>
                            <option value="supported">Supported</option>
                            <option value="refuted">Refuted</option>
                            <option value="inconclusive">Inconclusive</option>
                        </select>
                    </div>
                </div>
                <div class="confirm-sheet-actions" style="margin-top:16px;">
                    <button id="hypFormSubmit" class="confirm-btn-primary" style="border-radius:0;"
                            onclick="_submitHypothesisForm()">Create</button>
                    <button class="confirm-btn-cancel" style="border-radius:0;"
                            onclick="_closeHypothesisForm()">Cancel</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
}

function _ensureEvidenceFormModal() {
    if (document.getElementById('evidenceFormModal')) return;
    const html = `
        <div id="evidenceFormModal" class="confirm-sheet-overlay" style="display:none;">
            <div class="confirm-sheet ins-modal">
                <div class="confirm-sheet-title ins-modal-title">Add Evidence</div>
                <div class="ins-modal-form">
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="evFormDirection">Direction</label>
                        <select id="evFormDirection" class="ins-form-select">
                            <option value="supports">Supports</option>
                            <option value="contradicts">Contradicts</option>
                            <option value="neutral">Neutral</option>
                        </select>
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="evFormWeight">Weight (1-5)</label>
                        <input id="evFormWeight" type="number" class="ins-form-input"
                               min="1" max="5" value="3">
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="evFormDescription">Description</label>
                        <textarea id="evFormDescription" class="ins-form-textarea"
                                  placeholder="Describe the evidence..." rows="3"></textarea>
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="evFormEntity">Entity ID (optional)</label>
                        <input id="evFormEntity" type="text" class="ins-form-input"
                               placeholder="Entity ID linked to this evidence">
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="evFormSource">Source (optional)</label>
                        <input id="evFormSource" type="text" class="ins-form-input"
                               placeholder="e.g. website, interview, analysis">
                    </div>
                </div>
                <div class="confirm-sheet-actions" style="margin-top:16px;">
                    <button id="evFormSubmit" class="confirm-btn-primary" style="border-radius:0;"
                            onclick="_submitEvidenceForm()">Add Evidence</button>
                    <button class="confirm-btn-cancel" style="border-radius:0;"
                            onclick="_closeEvidenceForm()">Cancel</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
}

// ── Helpers ────────────────────────────────────────────────────

/**
 * Format an ISO date string as a human-readable relative time.
 */
function _insRelativeTime(isoString) {
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

function _insightSeverityBadge(severity) {
    const level = (severity || 'info').toLowerCase();
    const labels = {
        critical: 'CRIT',
        important: 'IMP',
        notable: 'NOTE',
        info: 'INFO',
    };
    const label = labels[level] || level.toUpperCase();
    return `<span class="insight-severity insight-severity--${level}" title="${esc(severity)}">${label}</span>`;
}

function _formatInsightType(type) {
    const labels = {
        coverage_gap: 'Coverage Gap',
        data_quality: 'Data Quality',
        cluster: 'Cluster',
        outlier: 'Outlier',
        trend: 'Trend',
        correlation: 'Correlation',
        contradiction: 'Contradiction',
        pattern: 'Pattern',
    };
    return labels[type] || (type || '').replace(/_/g, ' ');
}

function _formatHypothesisStatus(status) {
    const labels = {
        open: 'Open',
        supported: 'Supported',
        refuted: 'Refuted',
        inconclusive: 'Inconclusive',
    };
    return labels[status] || status || '';
}

function _formatDirection(direction) {
    const labels = {
        supports: 'Supports',
        contradicts: 'Contradicts',
        neutral: 'Neutral',
    };
    return labels[direction] || direction || '';
}

// ── Expose on window ──────────────────────────────────────────

window._loadInsights = _loadInsights;
window._generateInsights = _generateInsights;
window._generateAiInsights = _generateAiInsights;
window._dismissInsight = _dismissInsight;
window._pinInsight = _pinInsight;
window._deleteInsight = _deleteInsight;
window._setInsightFilter = _setInsightFilter;
window._loadHypotheses = _loadHypotheses;
window._createHypothesis = _createHypothesis;
window._viewHypothesis = _viewHypothesis;
window._updateHypothesis = _updateHypothesis;
window._deleteHypothesis = _deleteHypothesis;
window._addHypothesisEvidence = _addHypothesisEvidence;
window._removeHypothesisEvidence = _removeHypothesisEvidence;
window._submitHypothesisForm = _submitHypothesisForm;
window._closeHypothesisForm = _closeHypothesisForm;
window._submitEvidenceForm = _submitEvidenceForm;
window._closeEvidenceForm = _closeEvidenceForm;
window._backToHypothesesList = _backToHypothesesList;
window._setHypothesisFilter = _setHypothesisFilter;
