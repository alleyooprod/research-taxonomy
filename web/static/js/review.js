/**
 * Review Queue — human review interface for AI-extracted data.
 * Phase 3.4 of the Research Workbench.
 *
 * Loads pending extraction results grouped by entity, supports
 * accept/reject/edit per attribute with confidence indicators.
 */

// Review state
let _reviewQueue = [];           // Grouped queue: [{entity_id, entity_name, results: [...]}]
let _reviewStats = null;         // {pending_review, confidence_distribution, ...}
let _reviewConfidenceFilter = null; // 'high' | 'medium' | 'low' | null (all)
let _reviewEntityFilter = null;  // entity_id or null
let _reviewExpanded = new Set(); // Set of entity_ids whose cards are expanded

/**
 * Initialize the review tab — called when the Review tab is shown.
 */
async function initReviewQueue() {
    if (!currentProjectId) return;
    await Promise.all([
        _loadReviewStats(),
        _loadReviewQueue(),
    ]);
}

// ── Stats ────────────────────────────────────────────────────

async function _loadReviewStats() {
    if (!currentProjectId) return;
    try {
        const resp = await fetch(`/api/extract/stats?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        _reviewStats = await resp.json();
        _renderReviewStats();
    } catch (e) {
        console.warn('Failed to load review stats:', e);
    }
}

function _renderReviewStats() {
    const el = document.getElementById('reviewStats');
    if (!el || !_reviewStats) return;

    const pending = _reviewStats.pending_review || 0;
    const accepted = (_reviewStats.results || {}).accepted || 0;
    const rejected = (_reviewStats.results || {}).rejected || 0;
    const edited = (_reviewStats.results || {}).edited || 0;
    const conf = _reviewStats.confidence_distribution || {};
    const entities = _reviewStats.entities_pending || 0;
    const needsEv = _reviewStats.needs_evidence || 0;

    el.innerHTML = `
        <div class="review-stat-row">
            <div class="review-stat">
                <span class="review-stat-value">${pending}</span>
                <span class="review-stat-label">Pending</span>
            </div>
            <div class="review-stat">
                <span class="review-stat-value">${entities}</span>
                <span class="review-stat-label">Entities</span>
            </div>
            <div class="review-stat">
                <span class="review-stat-value">${accepted}</span>
                <span class="review-stat-label">Accepted</span>
            </div>
            <div class="review-stat">
                <span class="review-stat-value">${rejected + edited}</span>
                <span class="review-stat-label">Reviewed</span>
            </div>
            ${needsEv ? `<div class="review-stat review-stat-warn">
                <span class="review-stat-value">${needsEv}</span>
                <span class="review-stat-label">Needs Evidence</span>
            </div>` : ''}
        </div>
        <div class="review-confidence-bar">
            <button class="review-conf-btn ${!_reviewConfidenceFilter ? 'review-conf-btn-active' : ''}"
                    data-action="set-review-confidence-filter" data-value="">All</button>
            <button class="review-conf-btn ${_reviewConfidenceFilter === 'high' ? 'review-conf-btn-active' : ''}"
                    data-action="set-review-confidence-filter" data-value="high">High (${conf.high || 0})</button>
            <button class="review-conf-btn ${_reviewConfidenceFilter === 'medium' ? 'review-conf-btn-active' : ''}"
                    data-action="set-review-confidence-filter" data-value="medium">Medium (${conf.medium || 0})</button>
            <button class="review-conf-btn ${_reviewConfidenceFilter === 'low' ? 'review-conf-btn-active' : ''}"
                    data-action="set-review-confidence-filter" data-value="low">Low (${conf.low || 0})</button>
        </div>
    `;
}

// ── Queue Loading ────────────────────────────────────────────

async function _loadReviewQueue() {
    if (!currentProjectId) return;

    let url = `/api/extract/queue/grouped?project_id=${currentProjectId}`;
    if (_reviewConfidenceFilter === 'high') {
        url += '&min_confidence=0.8';
    } else if (_reviewConfidenceFilter === 'medium') {
        url += '&min_confidence=0.5&max_confidence=0.799';
    } else if (_reviewConfidenceFilter === 'low') {
        url += '&max_confidence=0.499';
    }
    if (_reviewEntityFilter) {
        url += `&entity_id=${_reviewEntityFilter}`;
    }

    try {
        const resp = await fetch(url, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        _reviewQueue = await resp.json();
        _renderReviewQueue();
    } catch (e) {
        console.warn('Failed to load review queue:', e);
    }
}

function _setReviewConfidenceFilter(level) {
    _reviewConfidenceFilter = level;
    _renderReviewStats();
    _loadReviewQueue();
}

// ── Queue Rendering ──────────────────────────────────────────

function _renderReviewQueue() {
    const container = document.getElementById('reviewQueueList');
    const empty = document.getElementById('reviewEmptyState');
    if (!container) return;

    if (!_reviewQueue || _reviewQueue.length === 0) {
        container.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        return;
    }
    if (empty) empty.classList.add('hidden');

    container.innerHTML = _reviewQueue.map(group => {
        const eid = group.entity_id;
        const expanded = _reviewExpanded.has(eid);
        const resultCount = group.results.length;
        const avgConf = resultCount > 0
            ? (group.results.reduce((s, r) => s + (r.confidence || 0), 0) / resultCount)
            : 0;

        return `
            <div class="review-entity-card ${expanded ? 'review-entity-expanded' : ''}" data-entity-id="${eid}">
                <div class="review-entity-header" data-action="toggle-review-entity" data-id="${eid}">
                    <div class="review-entity-info">
                        <span class="review-entity-type">${esc(group.entity_type || '')}</span>
                        <span class="review-entity-name">${esc(group.entity_name || 'Unknown')}</span>
                        <span class="review-entity-count">${resultCount} pending</span>
                    </div>
                    <div class="review-entity-actions">
                        ${_renderConfidenceIndicator(avgConf)}
                        <button class="btn btn-sm" data-action="bulk-review-entity-accept" data-id="${eid}" title="Accept all for this entity">Accept All</button>
                        <button class="btn btn-sm" data-action="bulk-review-entity-reject" data-id="${eid}" title="Reject all for this entity">Reject All</button>
                    </div>
                </div>
                ${expanded ? _renderReviewResults(group.results) : ''}
            </div>
        `;
    }).join('');
}

function _renderConfidenceIndicator(confidence) {
    const pct = Math.round(confidence * 100);
    let level = 'low';
    if (confidence >= 0.8) level = 'high';
    else if (confidence >= 0.5) level = 'medium';

    return `<span class="review-confidence review-confidence-${level}" title="Avg confidence: ${pct}%">
        <span class="review-confidence-bar" style="width: ${pct}%"></span>
        <span class="review-confidence-text">${pct}%</span>
    </span>`;
}

function _renderReviewResults(results) {
    if (!results || results.length === 0) return '<div class="review-no-results">No pending results</div>';

    return `<div class="review-results-list">
        ${results.map(r => _renderSingleResult(r)).join('')}
    </div>`;
}

function _renderSingleResult(r) {
    const conf = r.confidence || 0;
    const pct = Math.round(conf * 100);
    let confClass = 'low';
    if (conf >= 0.8) confClass = 'high';
    else if (conf >= 0.5) confClass = 'medium';

    const needsEvFlag = r.needs_evidence ? ' review-result-flagged' : '';
    const sourceInfo = r.evidence_url || r.source_ref || '';
    const evidenceType = r.evidence_type_name || r.source_type || '';

    return `
        <div class="review-result-row${needsEvFlag}" data-result-id="${r.id}">
            <div class="review-result-attr">
                <span class="review-result-slug">${esc(r.attr_slug)}</span>
                ${evidenceType ? `<span class="review-result-source-type">${esc(evidenceType)}</span>` : ''}
            </div>
            <div class="review-result-value">
                <span class="review-result-extracted" id="reviewValue_${r.id}">${esc(String(r.extracted_value || ''))}</span>
            </div>
            <div class="review-result-meta">
                <span class="review-confidence review-confidence-${confClass}" title="Confidence: ${pct}%">
                    <span class="review-confidence-bar" style="width: ${pct}%"></span>
                    <span class="review-confidence-text">${pct}%</span>
                </span>
                ${sourceInfo ? `<span class="review-result-source" title="${escAttr(sourceInfo)}">${esc(_truncateUrl(sourceInfo))}</span>` : ''}
            </div>
            <div class="review-result-reasoning ${r.reasoning ? '' : 'hidden'}">
                <span class="review-reasoning-text">${esc(r.reasoning || '')}</span>
            </div>
            <div class="review-result-actions">
                <button class="btn btn-sm review-btn-accept" data-action="review-accept" data-id="${r.id}" title="Accept this value">Accept</button>
                <button class="btn btn-sm" data-action="review-edit" data-id="${r.id}" data-value="${escAttr(JSON.stringify(r.extracted_value || ''))}" title="Edit then accept">Edit</button>
                <button class="btn btn-sm review-btn-reject" data-action="review-reject" data-id="${r.id}" title="Reject this value">Reject</button>
                <button class="btn btn-sm review-btn-flag ${r.needs_evidence ? 'review-btn-flag-active' : ''}"
                        data-action="toggle-needs-evidence" data-id="${r.id}" data-needs="${r.needs_evidence ? 'false' : 'true'}"
                        title="${r.needs_evidence ? 'Unflag' : 'Flag as needs more evidence'}">
                    ${r.needs_evidence ? 'Unflag' : 'Flag'}
                </button>
            </div>
        </div>
    `;
}

function _truncateUrl(url) {
    if (!url) return '';
    if (url.length <= 40) return url;
    try {
        const u = new URL(url);
        return u.hostname + u.pathname.substring(0, 20) + '...';
    } catch {
        return url.substring(0, 37) + '...';
    }
}

// ── Entity Expand/Collapse ───────────────────────────────────

function _toggleReviewEntity(entityId) {
    if (_reviewExpanded.has(entityId)) {
        _reviewExpanded.delete(entityId);
    } else {
        _reviewExpanded.add(entityId);
    }
    _renderReviewQueue();
}

// ── Single Review Actions ────────────────────────────────────

async function _reviewSingle(resultId, action, editedValue) {
    try {
        const body = { action };
        if (action === 'edit' && editedValue !== undefined) {
            body.edited_value = editedValue;
        }
        const resp = await fetch(`/api/extract/results/${resultId}/review`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify(body),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Review failed');
            return;
        }
        // Remove the result row with animation
        const row = document.querySelector(`[data-result-id="${resultId}"]`);
        if (row) {
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            setTimeout(() => {
                // Reload data
                _loadReviewStats();
                _loadReviewQueue();
            }, 200);
        } else {
            _loadReviewStats();
            _loadReviewQueue();
        }
    } catch (e) {
        console.error('Review failed:', e);
        if (window.notyf) window.notyf.error('Review failed');
    }
}

// ── Edit Flow ────────────────────────────────────────────────

async function _startEditResult(resultId, currentValue) {
    const valueStr = typeof currentValue === 'string' ? currentValue : JSON.stringify(currentValue);
    const result = await showPromptDialog(
        'Edit Extracted Value',
        'Modify the value before accepting:',
        valueStr,
    );
    if (result !== null && result !== undefined) {
        await _reviewSingle(resultId, 'edit', result);
    }
}

// ── Needs Evidence Flag ──────────────────────────────────────

async function _toggleNeedsEvidence(resultId, needs) {
    try {
        const resp = await fetch(`/api/extract/results/${resultId}/flag`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({ needs_evidence: needs }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Flag failed');
            return;
        }
        _loadReviewStats();
        _loadReviewQueue();
    } catch (e) {
        console.error('Flag failed:', e);
    }
}

// ── Bulk Actions ─────────────────────────────────────────────

async function _bulkReviewEntity(entityId, action) {
    const group = _reviewQueue.find(g => g.entity_id === entityId);
    if (!group || !group.results.length) return;

    const resultIds = group.results.map(r => r.id);
    const confirmMsg = `${action === 'accept' ? 'Accept' : 'Reject'} all ${resultIds.length} results for "${group.entity_name}"?`;

    const confirmed = await window.showNativeConfirm({
        title: `${action === 'accept' ? 'Accept' : 'Reject'} All`,
        message: confirmMsg,
        confirmText: action === 'accept' ? 'Accept All' : 'Reject All',
        type: action === 'reject' ? 'danger' : 'warning',
    });
    if (!confirmed) return;

    try {
        const resp = await fetch('/api/extract/results/bulk-review', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({ result_ids: resultIds, action }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Bulk review failed');
            return;
        }
        const data = await resp.json();
        if (window.notyf) {
            window.notyf.success(`${data.updated_count} results ${action}ed`);
        }
        _reviewExpanded.delete(entityId);
        _loadReviewStats();
        _loadReviewQueue();
    } catch (e) {
        console.error('Bulk review failed:', e);
        if (window.notyf) window.notyf.error('Bulk review failed');
    }
}

async function reviewBulkAll(action) {
    if (!_reviewQueue || !_reviewQueue.length) return;

    const total = _reviewQueue.reduce((s, g) => s + g.results.length, 0);
    const confirmed = await window.showNativeConfirm({
        title: `${action === 'accept' ? 'Accept' : 'Reject'} All`,
        message: `${action === 'accept' ? 'Accept' : 'Reject'} all ${total} pending results?`,
        confirmText: `${action === 'accept' ? 'Accept' : 'Reject'} All (${total})`,
        type: action === 'reject' ? 'danger' : 'warning',
    });
    if (!confirmed) return;

    const allIds = _reviewQueue.flatMap(g => g.results.map(r => r.id));
    try {
        const resp = await fetch('/api/extract/results/bulk-review', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({ result_ids: allIds, action }),
        });
        if (resp.ok) {
            const data = await resp.json();
            if (window.notyf) window.notyf.success(`${data.updated_count} results ${action}ed`);
        }
        _reviewExpanded.clear();
        _loadReviewStats();
        _loadReviewQueue();
    } catch (e) {
        console.error('Bulk review all failed:', e);
    }
}

// ── Action Delegation ─────────────────────────────────────────

registerActions({
    'set-review-confidence-filter': (el) => _setReviewConfidenceFilter(el.dataset.value || null),
    'toggle-review-entity': (el) => _toggleReviewEntity(Number(el.dataset.id)),
    'bulk-review-entity-accept': (el, e) => { e.stopPropagation(); _bulkReviewEntity(Number(el.dataset.id), 'accept'); },
    'bulk-review-entity-reject': (el, e) => { e.stopPropagation(); _bulkReviewEntity(Number(el.dataset.id), 'reject'); },
    'review-accept': (el) => _reviewSingle(Number(el.dataset.id), 'accept'),
    'review-edit': (el) => { try { _startEditResult(Number(el.dataset.id), JSON.parse(el.dataset.value)); } catch { _startEditResult(Number(el.dataset.id), el.dataset.value); } },
    'review-reject': (el) => _reviewSingle(Number(el.dataset.id), 'reject'),
    'toggle-needs-evidence': (el) => _toggleNeedsEvidence(Number(el.dataset.id), el.dataset.needs === 'true'),
    'review-bulk-all-accept': () => reviewBulkAll('accept'),
    'review-bulk-all-reject': () => reviewBulkAll('reject'),
});

// ── Expose on window (for external callers) ──────────────────

window.initReviewQueue = initReviewQueue;
