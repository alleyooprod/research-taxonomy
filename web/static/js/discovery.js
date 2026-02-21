/**
 * Discovery tab: context files, feature landscape, gap analysis.
 */

let _discoveryLoaded = false;

async function loadDiscoveryTab() {
    if (!currentProjectId) return;
    // Check if discovery is enabled for this project
    updateDiscoveryTabVisibility();
    loadContexts();
    loadDimensions();
    loadAnalysisHistory();
    populateCategoryDropdowns();
    _discoveryLoaded = true;
}

async function updateDiscoveryTabVisibility() {
    const btn = document.getElementById('discoveryTabBtn');
    if (!btn) return;
    // Always show the Discovery tab — the toggle controls full features
    btn.classList.remove('hidden');
    btn.style.display = '';
}

// --- Context Files ---

async function loadContexts() {
    if (!currentProjectId) return;
    const res = await safeFetch(`/api/discovery/contexts?project_id=${currentProjectId}`);
    if (!res.ok) return;
    const contexts = await res.json();
    renderContextsList(contexts);
    updateContextDropdowns(contexts);
}

function renderContextsList(contexts) {
    const el = document.getElementById('contextsList');
    if (!el) return;
    if (!contexts.length) {
        el.innerHTML = '<p class="empty-state">No context files uploaded. Upload a product roadmap or feature list to enable comparison-based gap analysis.</p>';
        return;
    }
    el.innerHTML = contexts.map(c => `
        <div class="context-card">
            <div class="context-info">
                <strong>${esc(c.name)}</strong>
                <span class="context-type">${esc(c.context_type)}</span>
                <span class="context-size">${Math.round(c.content_length / 1024)}KB</span>
                <span class="context-date">${new Date(c.created_at).toLocaleDateString()}</span>
            </div>
            <div class="context-actions">
                <button class="btn btn-sm" data-action="preview-context" data-id="${c.id}">Preview</button>
                <button class="btn btn-sm btn-danger" data-action="delete-context" data-id="${c.id}">Delete</button>
            </div>
        </div>
    `).join('');
}

function updateContextDropdowns(contexts) {
    const sel = document.getElementById('gapContextSelect');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">No context (best-in-class only)</option>' +
        contexts.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
    if (current) sel.value = current;
}

// File upload
function initContextUpload() {
    const dropZone = document.getElementById('contextDropZone');
    const fileInput = document.getElementById('contextFileInput');
    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) uploadContextFile(e.dataTransfer.files[0]);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) uploadContextFile(fileInput.files[0]);
        fileInput.value = '';
    });
}

async function uploadContextFile(file) {
    if (!currentProjectId) return;
    const form = new FormData();
    form.append('file', file);
    form.append('project_id', currentProjectId);
    form.append('name', file.name);

    const ext = file.name.split('.').pop().toLowerCase();
    const type = ext === 'md' || ext === 'markdown' ? 'roadmap' : 'feature_list';
    form.append('context_type', type);

    const res = await safeFetch('/api/discovery/upload-context', {
        method: 'POST',
        body: form,
    });
    if (res.ok) {
        showToast(`Uploaded ${file.name}`);
        loadContexts();
    }
}

async function previewContext(ctxId) {
    const res = await safeFetch(`/api/discovery/contexts/${ctxId}`);
    if (!res.ok) return;
    const ctx = await res.json();

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `<div class="context-preview-modal">
        <h3>${esc(ctx.name)}</h3>
        <div class="context-preview-content">${typeof marked !== 'undefined' ? sanitize(marked.parse(ctx.content)) : '<pre>' + esc(ctx.content) + '</pre>'}</div>
        <button class="btn" data-action="close-modal-overlay">Close</button>
    </div>`;
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);
}

async function deleteContext(ctxId) {
    const confirmed = await showNativeConfirm({
        title: 'Delete Context',
        message: 'This will permanently remove this context file.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;
    const res = await safeFetch(`/api/discovery/contexts/${ctxId}`, { method: 'DELETE' });
    if (res.ok) { showToast('Context deleted'); loadContexts(); }
}

// --- Category Dropdowns ---

async function populateCategoryDropdowns() {
    if (!currentProjectId) return;
    const res = await safeFetch(`/api/taxonomy/stats?project_id=${currentProjectId}`);
    if (!res.ok) return;
    const cats = await res.json();
    const topLevel = cats.filter(c => !c.parent_id);

    const sel = document.getElementById('landscapeCategoryFilter');
    if (sel) {
        sel.innerHTML = '<option value="">All Categories</option>' +
            topLevel.map(c => `<option value="${esc(c.name)}">${esc(c.name)} (${c.company_count})</option>`).join('');
    }
}

// --- Feature Landscape ---

async function generateFeatureLandscape() {
    if (!currentProjectId) return;
    const model = document.getElementById('landscapeModel')?.value || 'claude-sonnet-4-5-20250929';
    const category = document.getElementById('landscapeCategoryFilter')?.value || null;

    const resultsEl = document.getElementById('landscapeResults');
    if (resultsEl) resultsEl.innerHTML = '<p class="loading-pulse">Generating feature landscape... This may take a few minutes.</p>';

    const res = await safeFetch('/api/discovery/feature-landscape', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, model, category }),
    });
    if (!res.ok) return;
    const { landscape_id, analysis_id } = await res.json();

    let retries = 0;
    const poll = setInterval(async () => {
        if (++retries > 120) { clearInterval(poll); if (resultsEl) resultsEl.innerHTML = '<p>Timed out. Check Analysis History.</p>'; return; }
        const pr = await safeFetch(`/api/discovery/feature-landscape/${landscape_id}`);
        const data = await pr.json();
        if (data.status === 'complete') {
            clearInterval(poll);
            loadAnalysis(analysis_id, 'landscapeResults');
            loadAnalysisHistory();
        } else if (data.status === 'error') {
            clearInterval(poll);
            if (resultsEl) resultsEl.innerHTML = `<p class="error">${esc(data.error)}</p>`;
        }
    }, 5000);
}

// --- Gap Analysis ---

async function generateGapAnalysis() {
    if (!currentProjectId) return;
    const model = document.getElementById('gapModel')?.value || 'claude-sonnet-4-5-20250929';
    const contextId = document.getElementById('gapContextSelect')?.value || null;

    const resultsEl = document.getElementById('gapResults');
    if (resultsEl) resultsEl.innerHTML = '<p class="loading-pulse">Running gap analysis... This may take a few minutes.</p>';

    const res = await safeFetch('/api/discovery/gap-analysis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId, model,
            context_id: contextId ? parseInt(contextId) : null,
        }),
    });
    if (!res.ok) return;
    const { gap_id, analysis_id } = await res.json();

    let retries = 0;
    const poll = setInterval(async () => {
        if (++retries > 120) { clearInterval(poll); if (resultsEl) resultsEl.innerHTML = '<p>Timed out. Check Analysis History.</p>'; return; }
        const pr = await safeFetch(`/api/discovery/gap-analysis/${gap_id}`);
        const data = await pr.json();
        if (data.status === 'complete') {
            clearInterval(poll);
            loadAnalysis(analysis_id, 'gapResults');
            loadAnalysisHistory();
        } else if (data.status === 'error') {
            clearInterval(poll);
            if (resultsEl) resultsEl.innerHTML = `<p class="error">${esc(data.error)}</p>`;
        }
    }, 5000);
}

// --- Analysis Display ---

async function loadAnalysis(analysisId, targetElementId) {
    const res = await safeFetch(`/api/discovery/analyses/${analysisId}`);
    if (!res.ok) return;
    const analysis = await res.json();
    const el = document.getElementById(targetElementId);
    if (!el) return;

    const result = analysis.result;
    if (!result) {
        el.innerHTML = `<p>Analysis ${analysis.status}${analysis.error_message ? ': ' + esc(analysis.error_message) : ''}</p>`;
        return;
    }

    // Render markdown if available
    if (result.markdown) {
        const rendered = typeof marked !== 'undefined' ? sanitize(marked.parse(result.markdown)) : '<pre>' + esc(result.markdown) + '</pre>';
        el.innerHTML = `<div class="analysis-result">
            <div class="analysis-markdown">${rendered}</div>
            ${renderStructuredResult(result, analysis.analysis_type)}
        </div>`;
        return;
    }

    // Structured result rendering
    el.innerHTML = `<div class="analysis-result">${renderStructuredResult(result, analysis.analysis_type)}</div>`;
}

function renderStructuredResult(result, type) {
    let html = '';

    if (type === 'feature_landscape' && result.feature_areas) {
        html += '<div class="feature-areas">';
        for (const area of result.feature_areas) {
            html += `<div class="feature-area">
                <h4>${esc(area.name)}</h4>
                <p class="area-desc">${esc(area.description || '')}</p>
                <div class="feature-grid">
                    ${(area.features || []).map(f => `
                        <div class="feature-item ${f.best_in_class ? 'best-in-class' : ''}">
                            <strong>${esc(f.name)}</strong>
                            <div class="feature-companies">${(f.companies || []).map(c => `<span class="company-chip">${esc(c)}</span>`).join('')}</div>
                            ${f.best_in_class ? `<div class="bic-badge">Best: ${esc(f.best_in_class)}</div>` : ''}
                        </div>
                    `).join('')}
                </div>
            </div>`;
        }
        html += '</div>';
        if (result.insights) {
            html += '<div class="analysis-insights"><h4>Key Insights</h4><ul>' +
                result.insights.map(i => `<li>${esc(i)}</li>`).join('') + '</ul></div>';
        }
    }

    if (type === 'gap_analysis') {
        if (result.gaps?.length) {
            html += '<div class="gap-list"><h4>Gaps</h4>';
            for (const g of result.gaps) {
                const prClass = g.priority === 'high' ? 'priority-high' : g.priority === 'medium' ? 'priority-med' : 'priority-low';
                html += `<div class="gap-item ${prClass}">
                    <div class="gap-header"><strong>${esc(g.feature)}</strong><span class="gap-priority">${esc(g.priority)}</span></div>
                    <p>${esc(g.description || '')}</p>
                    <p class="gap-leaders">Market leaders: ${(g.market_leaders || []).join(', ')}</p>
                    <p class="gap-opportunity">${esc(g.opportunity || '')}</p>
                </div>`;
            }
            html += '</div>';
        }

        if (result.best_in_class?.length) {
            html += '<div class="bic-list"><h4>Best in Class</h4><table><tr><th>Area</th><th>Company</th><th>Reason</th></tr>' +
                result.best_in_class.map(b => `<tr><td>${esc(b.area)}</td><td><strong>${esc(b.company)}</strong></td><td>${esc(b.reason)}</td></tr>`).join('') +
                '</table></div>';
        }

        if (result.summary) {
            html += `<div class="analysis-summary"><p>${esc(result.summary.overall_assessment || '')}</p></div>`;
        }
    }

    return html;
}

// --- Analysis History ---

async function loadAnalysisHistory() {
    if (!currentProjectId) return;
    const res = await safeFetch(`/api/discovery/analyses?project_id=${currentProjectId}`);
    if (!res.ok) return;
    const analyses = await res.json();
    const el = document.getElementById('analysisHistoryList');
    if (!el) return;
    if (!analyses.length) {
        el.innerHTML = '<p class="empty-state">No analyses yet. Generate a Feature Landscape or Gap Analysis above.</p>';
        return;
    }
    el.innerHTML = analyses.map(a => `
        <div class="analysis-history-card" data-action="show-analysis-detail" data-id="${a.id}">
            <div class="analysis-history-info">
                <strong>${esc(a.title || a.analysis_type)}</strong>
                <span class="analysis-type-badge">${esc(a.analysis_type.replace('_', ' '))}</span>
                <span class="analysis-status analysis-status-${a.status}">${a.status}</span>
                ${a.context_name ? `<span class="analysis-context">vs ${esc(a.context_name)}</span>` : ''}
            </div>
            <div class="analysis-history-meta">
                <span>${new Date(a.created_at).toLocaleDateString()}</span>
                <button class="btn btn-sm btn-danger" data-action="delete-analysis" data-id="${a.id}">Delete</button>
            </div>
        </div>
    `).join('');
}

async function showAnalysisDetail(analysisId) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = '<div class="analysis-detail-modal"><p>Loading...</p></div>';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);

    const res = await safeFetch(`/api/discovery/analyses/${analysisId}`);
    if (!res.ok) { overlay.remove(); return; }
    const analysis = await res.json();
    const result = analysis.result;

    let content = '';
    if (result?.markdown) {
        content = typeof marked !== 'undefined' ? sanitize(marked.parse(result.markdown)) : '<pre>' + esc(result.markdown) + '</pre>';
    } else if (result) {
        content = renderStructuredResult(result, analysis.analysis_type);
    } else {
        content = `<p>Status: ${analysis.status}${analysis.error_message ? ' — ' + esc(analysis.error_message) : ''}</p>`;
    }

    overlay.querySelector('.analysis-detail-modal').innerHTML = `
        <h3>${esc(analysis.title || analysis.analysis_type)}</h3>
        <div class="analysis-detail-content">${content}</div>
        <button class="btn" data-action="close-modal-overlay">Close</button>
    `;
}

async function deleteAnalysis(analysisId) {
    const confirmed = await showNativeConfirm({
        title: 'Delete Analysis',
        message: 'This will permanently remove this analysis.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;
    const res = await safeFetch(`/api/discovery/analyses/${analysisId}`, { method: 'DELETE' });
    if (res.ok) { showToast('Analysis deleted'); loadAnalysisHistory(); }
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    initContextUpload();
});

// ── Action Delegation ─────────────────────────────────────────

registerActions({
    'preview-context': (el) => previewContext(Number(el.dataset.id)),
    'delete-context': (el) => deleteContext(Number(el.dataset.id)),
    'show-analysis-detail': (el) => showAnalysisDetail(Number(el.dataset.id)),
    'delete-analysis': (el, e) => { e.stopPropagation(); deleteAnalysis(Number(el.dataset.id)); },
    'generate-feature-landscape': () => generateFeatureLandscape(),
    'generate-gap-analysis': () => generateGapAnalysis(),
    'close-modal-overlay': (el) => el.closest('.modal-overlay').remove(),
    'choose-context-file': () => document.getElementById('contextFileInput')?.click(),
});

// ── Expose on window (for external callers) ──────────────────

window.loadDiscoveryTab = loadDiscoveryTab;
