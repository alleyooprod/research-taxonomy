/**
 * Dimensions: explore, create, populate, and display research dimensions.
 */

let _dimensionsCache = [];

async function loadDimensions() {
    if (!currentProjectId) return;
    const res = await safeFetch(`/api/dimensions?project_id=${currentProjectId}`);
    if (!res.ok) return;
    _dimensionsCache = await res.json();
    renderDimensionsList();
}

function renderDimensionsList() {
    const el = document.getElementById('dimensionsList');
    if (!el) return;
    if (!_dimensionsCache.length) {
        el.innerHTML = '<p class="empty-state">No dimensions yet. Click "Explore New Dimensions" to discover interesting attributes to track.</p>';
        return;
    }
    el.innerHTML = _dimensionsCache.map(d => `
        <div class="dimension-card" data-dim-id="${d.id}">
            <div class="dimension-header">
                <strong>${esc(d.name)}</strong>
                <span class="dimension-type badge-${d.data_type}">${d.data_type}</span>
                <span class="dimension-count">${d.value_count || 0} values</span>
            </div>
            ${d.description ? `<p class="dimension-desc">${esc(d.description)}</p>` : ''}
            <div class="dimension-actions">
                <button class="btn btn-sm" data-action="populate-dimension" data-id="${d.id}">Populate All</button>
                <button class="btn btn-sm" data-action="view-dimension-values" data-id="${d.id}">View Values</button>
                <button class="btn btn-sm btn-danger" data-action="delete-dimension" data-id="${d.id}">Delete</button>
            </div>
        </div>
    `).join('');
}

async function exploreDimensions() {
    if (!currentProjectId) return;
    const model = document.getElementById('landscapeModel')?.value || 'claude-sonnet-4-5-20250929';
    const btn = event?.target;
    if (btn) { btn.disabled = true; btn.textContent = 'Exploring...'; }

    const res = await safeFetch('/api/dimensions/explore', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, model }),
    });
    if (!res.ok) { if (btn) { btn.disabled = false; btn.textContent = 'Explore New Dimensions'; } return; }
    const { explore_id } = await res.json();

    const resultsEl = document.getElementById('dimensionExploreResults');
    if (resultsEl) { resultsEl.classList.remove('hidden'); resultsEl.innerHTML = '<p>Exploring dimensions...</p>'; }

    let retries = 0;
    const poll = setInterval(async () => {
        if (++retries > 60) { clearInterval(poll); if (btn) { btn.disabled = false; btn.textContent = 'Explore New Dimensions'; } return; }
        const pr = await safeFetch(`/api/dimensions/explore/${explore_id}`);
        const data = await pr.json();
        if (data.status === 'complete') {
            clearInterval(poll);
            if (btn) { btn.disabled = false; btn.textContent = 'Explore New Dimensions'; }
            renderExploreResults(data.dimensions || []);
        } else if (data.status === 'error') {
            clearInterval(poll);
            if (btn) { btn.disabled = false; btn.textContent = 'Explore New Dimensions'; }
            if (resultsEl) resultsEl.innerHTML = `<p class="error">${esc(data.error)}</p>`;
        }
    }, 3000);
}

function renderExploreResults(dimensions) {
    const el = document.getElementById('dimensionExploreResults');
    if (!el) return;
    if (!dimensions.length) {
        el.innerHTML = '<p>No new dimensions proposed.</p>';
        return;
    }
    el.innerHTML = `<h4>Proposed Dimensions</h4>` + dimensions.map((d, i) => `
        <div class="proposed-dimension">
            <div class="proposed-dim-header">
                <strong>${esc(d.name)}</strong>
                <span class="dimension-type badge-${d.data_type || 'text'}">${d.data_type || 'text'}</span>
            </div>
            <p>${esc(d.description || '')}</p>
            ${d.rationale ? `<p class="dim-rationale"><em>${esc(d.rationale)}</em></p>` : ''}
            <button class="btn btn-sm btn-primary" data-action="accept-dimension" data-id="${i}">Accept</button>
        </div>
    `).join('');
    el._proposedDimensions = dimensions;
}

async function acceptDimension(index) {
    const el = document.getElementById('dimensionExploreResults');
    const dims = el?._proposedDimensions;
    if (!dims || !dims[index]) return;
    const d = dims[index];

    const res = await safeFetch('/api/dimensions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            name: d.name,
            description: d.description,
            data_type: d.data_type || 'text',
            source: 'ai_discovered',
            ai_prompt: d.ai_prompt,
            enum_values: d.enum_values,
        }),
    });
    if (res.ok) {
        showToast(`Dimension "${d.name}" added`);
        loadDimensions();
        // Remove from proposed list
        dims.splice(index, 1);
        renderExploreResults(dims);
    }
}

function showAddDimensionModal() {
    const name = prompt('Dimension name:');
    if (!name) return;
    const desc = prompt('Description (optional):') || '';
    const dataType = prompt('Data type (text/number/boolean/enum):') || 'text';

    safeFetch('/api/dimensions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            name, description: desc, data_type: dataType,
            source: 'user_defined',
        }),
    }).then(res => {
        if (res.ok) { showToast(`Dimension "${name}" created`); loadDimensions(); }
    });
}

async function populateDimension(dimId) {
    if (!currentProjectId) return;
    const model = 'claude-haiku-4-5-20251001';
    showToast('Starting dimension population...');

    const res = await safeFetch(`/api/dimensions/${dimId}/populate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, model }),
    });
    if (!res.ok) return;
    const { populate_id } = await res.json();

    let retries = 0;
    const poll = setInterval(async () => {
        if (++retries > 120) { clearInterval(poll); return; }
        const pr = await safeFetch(`/api/dimensions/populate/${populate_id}`);
        const data = await pr.json();
        if (data.status === 'complete') {
            clearInterval(poll);
            const results = data.results || [];
            const ok = results.filter(r => r.ok).length;
            showToast(`Populated ${ok}/${results.length} companies`);
            loadDimensions();
        } else if (data.status === 'error') {
            clearInterval(poll);
            showToast(data.error || 'Population failed');
        }
    }, 3000);
}

async function viewDimensionValues(dimId) {
    const res = await safeFetch(`/api/dimensions/${dimId}/values`);
    if (!res.ok) return;
    const values = await res.json();
    const dim = _dimensionsCache.find(d => d.id === dimId);

    const html = `<div class="dimension-values-modal">
        <h3>${esc(dim?.name || 'Values')}</h3>
        <table class="dim-values-table">
            <tr><th>Company</th><th>Value</th><th>Confidence</th></tr>
            ${values.map(v => `<tr>
                <td>${esc(v.company_name)}</td>
                <td>${esc(v.value || '—')}</td>
                <td>${v.confidence != null ? (v.confidence * 100).toFixed(0) + '%' : '—'}</td>
            </tr>`).join('')}
        </table>
        <button class="btn" data-action="close-modal-overlay">Close</button>
    </div>`;

    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = html;
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    document.body.appendChild(overlay);
}

async function deleteDimension(dimId) {
    if (!confirm('Delete this dimension and all its values?')) return;
    const res = await safeFetch(`/api/dimensions/${dimId}`, { method: 'DELETE' });
    if (res.ok) { showToast('Dimension deleted'); loadDimensions(); }
}

// Company detail integration
async function loadCompanyDimensions(companyId) {
    const res = await safeFetch(`/api/companies/${companyId}/dimensions`);
    if (!res.ok) return [];
    return await res.json();
}

function renderCompanyDimensions(dimensions) {
    if (!dimensions || !dimensions.length) return '';
    return `<div class="detail-dimensions">
        <label class="detail-section-label">Research Dimensions</label>
        <div class="dim-values-grid">
            ${dimensions.map(d => `
                <div class="dim-value-item">
                    <span class="dim-label">${esc(d.dimension_name)}</span>
                    <span class="dim-value">${esc(d.value || '—')}</span>
                    ${d.confidence != null ? `<span class="dim-confidence">${(d.confidence * 100).toFixed(0)}%</span>` : ''}
                </div>
            `).join('')}
        </div>
    </div>`;
}

// ── Action Delegation ─────────────────────────────────────────

registerActions({
    'populate-dimension': (el) => populateDimension(Number(el.dataset.id)),
    'view-dimension-values': (el) => viewDimensionValues(Number(el.dataset.id)),
    'delete-dimension': (el) => deleteDimension(Number(el.dataset.id)),
    'accept-dimension': (el) => acceptDimension(Number(el.dataset.id)),
    'explore-dimensions': () => exploreDimensions(),
    'add-dimension-manual': () => showAddDimensionModal(),
});

// ── Expose on window (for external callers) ──────────────────

window.loadDimensions = loadDimensions;
window.loadCompanyDimensions = loadCompanyDimensions;
window.renderCompanyDimensions = renderCompanyDimensions;
