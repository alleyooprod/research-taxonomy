/**
 * Taxonomy tree, review, quality dashboard, and Cytoscape graph.
 * Graph style: "The Instrument" — monochromatic black/white/gray, rectangular nodes.
 */

// Register optional Cytoscape layout plugins.
// NOTE: CDN scripts use `defer` and execute AFTER local scripts,
// so we register plugins lazily inside render functions instead.

let reviewChanges = [];
let cyInstance = null;

// Default palette for auto-assigning category colors
const CATEGORY_PALETTE = [
    '#bc6c5a', '#5a7c5a', '#6b8fa3', '#d4a853', '#8b6f8b',
    '#5a8c8c', '#a67c52', '#7c8c5a', '#c4786e', '#4a6a4a',
    '#7a6b8a', '#8c7a5a',
];

// Cache category data with colors for cross-module use
let categoryColorMap = {};

function getCategoryColor(categoryId) {
    return categoryColorMap[categoryId] || null;
}

async function updateCategoryColor(categoryId, color) {
    await safeFetch(`/api/categories/${categoryId}/color`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ color }),
    });
    categoryColorMap[categoryId] = color;
    // Refresh market map and companies if visible
    if (document.getElementById('tab-map')?.classList.contains('active')) loadMarketMap();
}

async function loadTaxonomy() {
    const res = await safeFetch(`/api/taxonomy?project_id=${currentProjectId}`);
    const categories = await res.json();

    // Build color map — use saved color or auto-assign from palette
    categoryColorMap = {};
    let paletteIdx = 0;
    categories.filter(c => !c.parent_id).forEach(cat => {
        categoryColorMap[cat.id] = cat.color || CATEGORY_PALETTE[paletteIdx++ % CATEGORY_PALETTE.length];
    });
    categories.filter(c => c.parent_id).forEach(sub => {
        categoryColorMap[sub.id] = sub.color || categoryColorMap[sub.parent_id] || CATEGORY_PALETTE[paletteIdx++ % CATEGORY_PALETTE.length];
    });

    const topLevel = categories.filter(c => !c.parent_id);
    const subs = categories.filter(c => c.parent_id);

    document.getElementById('taxonomyTree').innerHTML = topLevel.map(cat => {
        const color = categoryColorMap[cat.id];
        const children = subs.filter(s => s.parent_id === cat.id);
        const childHtml = children.length
            ? `<div class="sub-categories">${children.map(s => {
                const subColor = categoryColorMap[s.id];
                return `<div class="sub-cat" onclick="toggleCategoryCompanies(${s.id}, this); event.stopPropagation();">
                    <span class="cat-color-dot" style="background:${subColor}"></span>
                    <span class="sub-cat-name">${esc(s.name)}</span> <span class="count">(${s.company_count})</span>
                    <span class="material-symbols-outlined sub-cat-arrow" style="font-size:16px;margin-left:auto;color:var(--text-muted)">chevron_right</span>
                </div>`;
            }).join('')}</div>`
            : '';
        const hasMetadata = cat.scope_note || cat.inclusion_criteria || cat.exclusion_criteria;
        const metaHtml = `<div class="cat-metadata" id="catMeta-${cat.id}" onclick="event.stopPropagation()">
            <button class="cat-metadata-toggle" onclick="toggleCatMetadata(${cat.id})">
                ${hasMetadata ? 'Scope Notes' : 'Add Scope Notes'}
                <span class="collapse-arrow"><span class="material-symbols-outlined">${hasMetadata ? 'expand_more' : 'add'}</span></span>
            </button>
            <div class="cat-metadata-body hidden" id="catMetaBody-${cat.id}">
                <label>Scope Note</label>
                <textarea id="catScope-${cat.id}" rows="2" placeholder="What this category covers...">${esc(cat.scope_note || '')}</textarea>
                <label>Inclusion Criteria</label>
                <textarea id="catInclude-${cat.id}" rows="2" placeholder="Companies that belong here if...">${esc(cat.inclusion_criteria || '')}</textarea>
                <label>Exclusion Criteria</label>
                <textarea id="catExclude-${cat.id}" rows="2" placeholder="Companies that do NOT belong here if...">${esc(cat.exclusion_criteria || '')}</textarea>
                <button class="btn btn-sm" onclick="saveCategoryMetadata(${cat.id})">Save</button>
            </div>
        </div>`;
        return `<div class="category-card" style="border-left: 4px solid ${color}">
            <div class="cat-header" onclick="toggleCategoryCompanies(${cat.id}, this)" style="cursor:pointer">
                <input type="color" class="cat-color-picker" value="${color}" title="Category color"
                    onchange="updateCategoryColor(${cat.id}, this.value)" onclick="event.stopPropagation()">
                <span class="cat-name-link">${esc(cat.name)} <span class="count">(${cat.company_count})</span></span>
                <span class="material-symbols-outlined cat-expand-arrow" style="font-size:16px;margin-left:auto;color:var(--text-muted);transition:transform 0.2s">chevron_right</span>
            </div>
            ${childHtml}
            ${metaHtml}
        </div>`;
    }).join('');

    // Populate category filter dropdown
    const filter = document.getElementById('categoryFilter');
    filter.innerHTML = '<option value="">+ Category</option>' +
        topLevel.map(c => `<option value="${c.id}">${esc(c.name)} (${c.company_count})</option>`).join('');

    // Populate report category dropdown
    const reportSel = document.getElementById('reportCategorySelect');
    if (reportSel) {
        reportSel.innerHTML = '<option value="">Select a category...</option>' +
            topLevel.map(c => `<option value="${esc(c.name)}">${esc(c.name)} (${c.company_count})</option>`).join('');
    }

    // Load history
    const histRes = await safeFetch(`/api/taxonomy/history?project_id=${currentProjectId}`);
    const history = await histRes.json();
    document.getElementById('taxonomyHistory').innerHTML = history.length
        ? history.map(h => `<div class="history-entry">
            <span class="change-type">${esc(h.change_type)}</span>
            ${esc(h.reason || '')}
            <span class="change-date">${new Date(h.created_at).toLocaleDateString()}</span>
          </div>`).join('')
        : '<p>No taxonomy changes yet.</p>';
}

// --- Category Scope Notes ---
function toggleCatMetadata(catId) {
    const body = document.getElementById(`catMetaBody-${catId}`);
    body.classList.toggle('hidden');
    const arrow = body.previousElementSibling.querySelector('.material-symbols-outlined');
    if (arrow) arrow.textContent = body.classList.contains('hidden') ? 'expand_more' : 'expand_less';
}

async function saveCategoryMetadata(catId) {
    const scope_note = document.getElementById(`catScope-${catId}`).value.trim();
    const inclusion_criteria = document.getElementById(`catInclude-${catId}`).value.trim();
    const exclusion_criteria = document.getElementById(`catExclude-${catId}`).value.trim();
    await safeFetch(`/api/categories/${catId}/metadata`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scope_note, inclusion_criteria, exclusion_criteria }),
    });
    showToast('Scope notes saved');
}

// --- Inline Category Company List (toggle expand/collapse) ---
async function toggleCategoryCompanies(catId, clickedEl) {
    const existing = document.getElementById(`catCompanies-${catId}`);
    if (existing) {
        existing.remove();
        // Rotate arrow back
        const arrow = clickedEl.closest('.category-card, .sub-cat')?.querySelector('.sub-cat-arrow, .cat-expand-arrow');
        if (arrow) arrow.style.transform = '';
        return;
    }

    const res = await safeFetch(`/api/categories/${catId}`);
    const cat = await res.json();
    if (cat.error) { showToast(cat.error); return; }

    const companies = cat.companies || [];
    const color = categoryColorMap[catId] || '#888';
    const html = `<div class="cat-companies-inline" id="catCompanies-${catId}">
        ${companies.length ? companies.map(c => `
            <div class="cat-company-row" onclick="event.stopPropagation(); navigateTo('company', ${c.id}, '${escAttr(c.name)}')">
                <span class="cat-color-dot" style="background:${color}"></span>
                <span class="cat-company-row-name">${esc(c.name)}</span>
                <span class="cat-company-row-desc">${esc((c.what || '').substring(0, 80))}</span>
            </div>
        `).join('') : '<p class="hint-text" style="padding:6px 0;font-size:12px">No companies in this category yet.</p>'}
    </div>`;

    // Insert company list visibly below the clicked element
    const subCatEl = clickedEl.closest('.sub-cat');
    const cardEl = clickedEl.closest('.category-card');
    if (subCatEl) {
        // Subcategory: insert AFTER the flex row as a sibling (not inside the narrow flex row)
        subCatEl.insertAdjacentHTML('afterend', html);
        const arrow = subCatEl.querySelector('.sub-cat-arrow');
        if (arrow) arrow.style.transform = 'rotate(90deg)';
    } else if (cardEl) {
        // Top-level category: insert inside the block card container
        cardEl.insertAdjacentHTML('beforeend', html);
        const arrow = cardEl.querySelector('.cat-expand-arrow');
        if (arrow) arrow.style.transform = 'rotate(90deg)';
    }
}

// --- Category Detail View ---
async function showCategoryDetail(categoryId) {
    const res = await safeFetch(`/api/categories/${categoryId}`);
    const cat = await res.json();
    if (cat.error) { showToast(cat.error); return; }

    const color = categoryColorMap[cat.id] || '#888';
    const companies = cat.companies || [];

    const panel = document.getElementById('detailPanel');
    document.getElementById('detailName').textContent = cat.name;
    document.getElementById('detailContent').innerHTML = `
        <div class="category-detail-header">
            <span class="cat-color-dot" style="background:${color};width:14px;height:14px"></span>
            <input type="color" class="cat-color-picker" value="${color}" title="Category color"
                onchange="updateCategoryColor(${cat.id}, this.value)">
            <span class="detail-cat-name">${esc(cat.name)}</span>
        </div>
        ${cat.description ? `<div class="detail-field"><label>Description</label><p>${esc(cat.description)}</p></div>` : ''}
        ${cat.scope_note ? `<div class="detail-field"><label>Scope Note</label><p>${esc(cat.scope_note)}</p></div>` : ''}
        ${cat.inclusion_criteria ? `<div class="detail-field"><label>Includes</label><p>${esc(cat.inclusion_criteria)}</p></div>` : ''}
        ${cat.exclusion_criteria ? `<div class="detail-field"><label>Excludes</label><p>${esc(cat.exclusion_criteria)}</p></div>` : ''}
        <div class="detail-field"><label>Companies (${companies.length})</label></div>
        <div class="category-company-list">
            ${companies.length ? companies.map(c => `
                <div class="cat-company-item" onclick="navigateTo('company', ${c.id}, '${escAttr(c.name)}')">
                    <img class="company-logo" src="${esc(c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`)}" alt="" onerror="this.style.display='none'">
                    <span>${esc(c.name)}</span>
                    <span class="text-muted" style="font-size:11px;margin-left:auto">${esc(c.what || '').substring(0, 60)}</span>
                </div>
            `).join('') : '<p style="font-size:12px;color:var(--text-muted)">No companies in this category yet.</p>'}
        </div>
        <div class="detail-actions" style="margin-top:16px">
            <button class="btn" onclick="activeFilters.category_id=${cat.id};activeFilters.category_name='${escAttr(cat.name)}';renderFilterChips();loadCompanies();closeDetail()">
                Filter by this category
            </button>
            <button class="btn" onclick="closeDetail()">Close</button>
        </div>
    `;
    panel.classList.remove('hidden');
}

// --- Taxonomy Review ---
async function startTaxonomyReview() {
    const btn = document.getElementById('reviewBtn');
    btn.disabled = true;
    btn.textContent = 'Reviewing...';

    document.getElementById('reviewStatus').classList.remove('hidden');
    document.getElementById('reviewStatus').innerHTML =
        '<div class="progress-bar"><div id="reviewProgress" class="progress-fill" style="width:30%;animation:pulse 2s infinite"></div></div>' +
        '<p>Claude is analyzing all categories and company placements. This may take 1-3 minutes...</p>';
    document.getElementById('reviewResults').classList.add('hidden');

    const observations = (document.getElementById('reviewObservations').value || '').trim();
    const res = await safeFetch('/api/taxonomy/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, model: document.getElementById('reviewModelSelect').value, observations }),
    });
    const data = await res.json();

    pollReview(data.review_id);
}

let _reviewPollCount = 0;
const _MAX_REVIEW_RETRIES = 120; // 6 minutes at 3s intervals

async function pollReview(reviewId) {
    const res = await safeFetch(`/api/taxonomy/review/${reviewId}`);
    const data = await res.json();

    if (data.status === 'pending') {
        if (++_reviewPollCount > _MAX_REVIEW_RETRIES) {
            data.status = 'complete';
            data.result = { error: 'Taxonomy review timed out. Please try again.' };
        } else {
            setTimeout(() => pollReview(reviewId), 3000);
            return;
        }
    }
    _reviewPollCount = 0;

    const btn = document.getElementById('reviewBtn');
    btn.disabled = false;
    btn.textContent = 'Review Taxonomy with Claude';
    document.getElementById('reviewStatus').classList.add('hidden');

    const result = data.result;
    if (result.error) {
        document.getElementById('reviewResults').classList.remove('hidden');
        document.getElementById('reviewResults').innerHTML =
            `<div class="review-error">${esc(result.error)}</div>`;
        return;
    }

    reviewChanges = result.changes || [];
    let html = `<div class="review-analysis"><strong>Analysis:</strong> ${esc(result.analysis || '')}</div>`;

    if (result.no_changes_needed || !reviewChanges.length) {
        html += `<p>No changes recommended.</p>`;
    } else {
        html += `<h3>Proposed Changes (${reviewChanges.length})</h3>`;
        html += `<p class="hint-text">Select changes to apply, then click "Apply Selected".</p>`;
        html += reviewChanges.map((c, i) => {
            let desc = '';
            if (c.type === 'move') desc = `Move "${c.category_name}" to ${c.merge_into}`;
            else if (c.type === 'merge') desc = `Merge "${c.category_name}" into "${c.merge_into}"`;
            else if (c.type === 'rename') desc = `Rename "${c.category_name}" to "${c.new_name}"`;
            else if (c.type === 'split') desc = `Split "${c.category_name}" into ${(c.split_into||[]).join(', ')}`;
            else if (c.type === 'add') desc = `Add category: "${c.category_name}"`;
            else if (c.type === 'add_subcategory') desc = `Add subcategory: "${c.category_name}" under "${c.parent_category}"`;
            else desc = `${c.type}: ${c.category_name || ''}`;

            return `<div class="review-change">
                <label>
                    <input type="checkbox" name="review_change" value="${i}" checked>
                    <span class="change-type">${esc(c.type)}</span>
                    ${esc(desc)}
                </label>
                <div class="review-change-reason">${esc(c.reason || '')}</div>
            </div>`;
        }).join('');

        html += `<div class="review-actions">
            <button class="primary-btn" onclick="applyReviewChanges()">Apply Selected</button>
            <button class="btn" onclick="dismissReview()">Dismiss</button>
        </div>`;
    }

    document.getElementById('reviewResults').classList.remove('hidden');
    document.getElementById('reviewResults').innerHTML = html;
}

async function applyReviewChanges() {
    const checkboxes = document.querySelectorAll('input[name="review_change"]:checked');
    const selected = Array.from(checkboxes).map(cb => reviewChanges[parseInt(cb.value)]);

    if (!selected.length) { showToast('No changes selected'); return; }

    const res = await safeFetch('/api/taxonomy/review/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ changes: selected, project_id: currentProjectId }),
    });
    const data = await res.json();

    document.getElementById('reviewResults').innerHTML =
        `<p>${data.applied} changes applied successfully.</p>`;
    loadTaxonomy();
    loadStats();
}

function dismissReview() {
    document.getElementById('reviewResults').classList.add('hidden');
    reviewChanges = [];
}

// --- Taxonomy Quality ---
async function loadTaxonomyQuality() {
    const container = document.getElementById('qualityContent');
    container.classList.remove('hidden');
    container.innerHTML = '<p>Loading...</p>';
    const res = await safeFetch(`/api/taxonomy/quality?project_id=${currentProjectId}`);
    const q = await res.json();

    let html = '<div class="quality-cards">';

    const confColor = q.avg_confidence >= 0.7 ? 'var(--accent-success)' : q.avg_confidence >= 0.4 ? '#e6a817' : 'var(--accent-danger, #dc3545)';
    html += `<div class="quality-card">
        <div class="quality-metric" style="color:${confColor}">${q.avg_confidence != null ? Math.round(q.avg_confidence * 100) + '%' : 'N/A'}</div>
        <div class="quality-label">Avg. Confidence</div>
        <div class="quality-hint">${q.avg_confidence != null && q.avg_confidence < 0.5 ? 'Consider re-researching low-confidence companies' : q.avg_confidence != null && q.avg_confidence < 0.7 ? 'Moderate — review flagged categories' : 'Good coverage'}</div>
    </div>`;

    html += `<div class="quality-card">
        <div class="quality-metric">${q.total_companies}</div>
        <div class="quality-label">Total Companies</div>
        <div class="quality-hint">${q.total_companies < 20 ? 'Add more companies for richer analysis' : 'Solid dataset'}</div>
    </div>`;

    html += `<div class="quality-card">
        <div class="quality-metric">${q.total_categories}</div>
        <div class="quality-label">Categories</div>
        <div class="quality-hint">${q.total_categories > 0 ? Math.round(q.total_companies / q.total_categories) + ' companies per category avg.' : 'No categories'}</div>
    </div>`;

    html += '</div>';

    if (q.empty_categories.length) {
        html += `<div class="quality-issue">
            <div class="quality-issue-header"><strong>Empty categories (${q.empty_categories.length})</strong></div>
            <p class="quality-issue-desc">These categories have no companies. Either add companies or consider removing them.</p>
            <div class="quality-issue-items">${q.empty_categories.map(c =>
                `<span class="quality-chip">${esc(c.name)}
                    <button class="quality-chip-action" onclick="prefillReviewObservation('Remove empty category: ${esc(c.name)}')" title="Suggest removal in review">review</button>
                </span>`
            ).join('')}</div>
        </div>`;
    }
    if (q.overcrowded_categories.length) {
        html += `<div class="quality-issue quality-warn">
            <div class="quality-issue-header"><strong>Overcrowded categories (>15 companies)</strong></div>
            <p class="quality-issue-desc">These categories are too broad. Consider splitting them into subcategories for clearer segmentation.</p>
            <div class="quality-issue-items">${q.overcrowded_categories.map(c =>
                `<span class="quality-chip">${esc(c.name)} <strong>(${c.count})</strong>
                    <button class="quality-chip-action" onclick="prefillReviewObservation('Split overcrowded category ${esc(c.name)} (${c.count} companies) into subcategories')" title="Suggest split in review">split</button>
                </span>`
            ).join('')}</div>
        </div>`;
    }
    if (q.low_confidence_categories.length) {
        html += `<div class="quality-issue quality-warn">
            <div class="quality-issue-header"><strong>Low confidence categories (<50%)</strong></div>
            <p class="quality-issue-desc">Companies in these categories may be misclassified. Re-research or manually review placements.</p>
            <div class="quality-issue-items">${q.low_confidence_categories.map(c =>
                `<span class="quality-chip">${esc(c.name)} <strong>(${Math.round(c.avg_confidence * 100)}%)</strong>
                    <button class="quality-chip-action" onclick="prefillReviewObservation('Review misclassified companies in ${esc(c.name)} (low confidence ${Math.round(c.avg_confidence * 100)}%)')" title="Suggest review">review</button>
                </span>`
            ).join('')}</div>
        </div>`;
    }

    if (!q.empty_categories.length && !q.overcrowded_categories.length && !q.low_confidence_categories.length) {
        html += '<p style="color:var(--accent-success);font-size:13px;margin-top:12px">No quality issues found. Taxonomy is well-structured.</p>';
    }

    container.innerHTML = html;
}

function prefillReviewObservation(text) {
    const textarea = document.getElementById('reviewObservations');
    if (textarea) {
        const current = textarea.value.trim();
        textarea.value = current ? current + '\n' + text : text;
        textarea.scrollIntoView({ behavior: 'smooth', block: 'center' });
        textarea.focus();
    }
}

// --- Library loading helper (used by taxonomy.js and maps.js) ---
function _waitForLib(libName, checkFn, callback, containerEl, maxWait = 10000) {
    if (checkFn()) { callback(); return; }
    containerEl.innerHTML = `<div class="graph-loading">
        <div class="tab-loading-spinner"></div>
        <p>Loading ${libName}...</p>
    </div>`;
    const start = Date.now();
    const poll = setInterval(() => {
        if (checkFn()) {
            clearInterval(poll);
            containerEl.innerHTML = '';
            callback();
        } else if (Date.now() - start > maxWait) {
            clearInterval(poll);
            containerEl.innerHTML = `<div class="graph-loading">
                <p style="color:var(--accent-danger)">Failed to load ${libName}. <a href="#" onclick="location.reload();return false">Reload page</a></p>
            </div>`;
        }
    }, 200);
}

// --- Cytoscape Graph ---
function _ensureCytoscapePlugins() {
    try {
        if (window.cytoscape && window.cytoscapeDagre) {
            // Only register if not already registered
            try { cytoscape.use(cytoscapeDagre); } catch (_) { /* already registered */ }
        }
        if (window.cytoscape && window.cytoscapeFcose) {
            try { cytoscape.use(cytoscapeFcose); } catch (_) { /* already registered */ }
        }
    } catch (e) {
        console.warn('Cytoscape plugin registration error:', e);
    }
}

function renderTaxonomyGraph(categories, companies) {
    const container = document.getElementById('taxonomyGraph');
    if (!container) return;
    if (!window.cytoscape) {
        _waitForLib('graph library', () => window.cytoscape, () => renderTaxonomyGraph(categories, companies), container);
        return;
    }

    // Register plugins now that cytoscape is loaded
    _ensureCytoscapePlugins();

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    // Build color map for graph nodes
    let graphColorMap = {};
    let pIdx = 0;
    categories.filter(c => !c.parent_id).forEach(cat => {
        graphColorMap[cat.id] = cat.color || CATEGORY_PALETTE[pIdx++ % CATEGORY_PALETTE.length];
    });
    categories.filter(c => c.parent_id).forEach(sub => {
        graphColorMap[sub.id] = sub.color || graphColorMap[sub.parent_id] || CATEGORY_PALETTE[pIdx++ % CATEGORY_PALETTE.length];
    });

    const elements = [];
    const topLevel = categories.filter(c => !c.parent_id);
    const subs = categories.filter(c => c.parent_id);

    elements.push({ data: { id: 'root', label: 'Taxonomy', type: 'root' } });

    topLevel.forEach(cat => {
        elements.push({
            data: {
                id: `cat-${cat.id}`,
                label: `${cat.name}\n(${cat.company_count})`,
                type: 'category',
                count: cat.company_count,
                catColor: graphColorMap[cat.id],
            },
        });
        elements.push({ data: { source: 'root', target: `cat-${cat.id}` } });
    });

    subs.forEach(sub => {
        elements.push({
            data: {
                id: `cat-${sub.id}`,
                label: `${sub.name}\n(${sub.company_count})`,
                type: 'subcategory',
                count: sub.company_count,
                catColor: graphColorMap[sub.id],
            },
        });
        elements.push({ data: { source: `cat-${sub.parent_id}`, target: `cat-${sub.id}` } });
    });

    if (cyInstance) cyInstance.destroy();

    // Double-RAF ensures the container has actual layout dimensions after unhiding
    requestAnimationFrame(() => { requestAnimationFrame(() => {
        const rect = container.getBoundingClientRect();
        // If container still has no dimensions, force explicit height
        if (rect.width < 10 || rect.height < 10) {
            container.style.width = '100%';
            container.style.height = '500px';
            container.style.minHeight = '500px';
        }

        // Determine layout: prefer dagre if registered, fallback to breadthfirst
        let layoutConfig;
        try {
            // Test if dagre layout is actually registered by checking Cytoscape's layout registry
            const hasDagre = window.cytoscapeDagre && typeof cytoscape('layout', 'dagre') !== 'undefined';
            layoutConfig = hasDagre
                ? { name: 'dagre', rankDir: 'TB', nodeSep: 60, rankSep: 80, padding: 30, animate: false }
                : { name: 'breadthfirst', directed: true, padding: 30, spacingFactor: 1.2, animate: false };
        } catch (_) {
            layoutConfig = { name: 'breadthfirst', directed: true, padding: 30, spacingFactor: 1.2, animate: false };
        }

        const cyStyle = [
                    {
                        selector: 'node[type="root"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 2,
                            'border-color': '#000000',
                            label: 'data(label)',
                            'text-valign': 'center',
                            'font-size': '14px',
                            'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#CCCCCC' : '#000000',
                            width: 60, height: 60,
                            shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node[type="category"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 1,
                            'border-color': '#000000',
                            label: 'data(label)',
                            'text-valign': 'center',
                            'text-wrap': 'wrap',
                            'text-max-width': '100px',
                            'font-size': '12px',
                            'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#CCCCCC' : '#000000',
                            width: 'mapData(count, 0, 30, 30, 70)',
                            height: 'mapData(count, 0, 30, 30, 70)',
                            shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node[type="subcategory"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 1,
                            'border-color': '#000000',
                            label: 'data(label)',
                            'text-valign': 'center',
                            'text-wrap': 'wrap',
                            'text-max-width': '80px',
                            'font-size': '12px',
                            'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#CCCCCC' : '#000000',
                            width: 25, height: 25,
                            shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node:selected',
                        style: {
                            'background-color': '#000000',
                            color: '#FFFFFF',
                            'border-color': '#000000',
                        },
                    },
                    {
                        selector: 'edge',
                        style: {
                            width: 1,
                            'line-color': isDark ? '#666666' : '#999999',
                            'target-arrow-color': isDark ? '#666666' : '#999999',
                            'target-arrow-shape': 'triangle',
                            'curve-style': 'bezier',
                        },
                    },
                ];

        // Try preferred layout first, fallback to breadthfirst if it fails at runtime
        // (dagre can fail if graphlib dependency is missing from CDN bundle)
        try {
            cyInstance = cytoscape({ container, elements, style: cyStyle, layout: layoutConfig });
        } catch (e) {
            console.warn('Primary layout failed, falling back to breadthfirst:', e.message);
            try {
                const fallbackLayout = { name: 'breadthfirst', directed: true, padding: 30, spacingFactor: 1.2, animate: false };
                cyInstance = cytoscape({ container, elements, style: cyStyle, layout: fallbackLayout });
            } catch (e2) {
                console.error('Cytoscape graph init error:', e2);
                container.innerHTML = `<div class="graph-loading"><p style="color:var(--accent-danger)">Graph rendering failed: ${e2.message}. <a href="#" onclick="location.reload();return false">Reload page</a></p></div>`;
                return;
            }
        }

        // Fit after layout completes + fallback timeout
        cyInstance.one('layoutstop', () => {
            cyInstance.resize();
            cyInstance.fit(undefined, 40);
        });
        // Fallback: resize and fit after 500ms in case layoutstop never fires
        setTimeout(() => {
            if (cyInstance) {
                cyInstance.resize();
                cyInstance.fit(undefined, 40);
            }
        }, 500);

        cyInstance.on('tap', 'node[type="category"]', (evt) => {
            const catId = evt.target.id().replace('cat-', '');
            const catName = evt.target.data('label').split('\n')[0];
            activeFilters.category_id = catId;
            activeFilters.category_name = catName;
            renderFilterChips();
            showTab('companies');
            loadCompanies();
        });
    }); });
}

let kgInstance = null;
let kgNodeTypes = { category: true, company: true, tag: true, geography: true };

function switchTaxonomyView(view) {
    document.getElementById('taxonomyTree').classList.add('hidden');
    document.getElementById('taxonomyGraph').classList.add('hidden');
    const kgContainer = document.getElementById('knowledgeGraph');
    if (kgContainer) kgContainer.classList.add('hidden');
    document.querySelectorAll('.taxonomy-view-toggle .view-toggle-btn').forEach(b => b.classList.remove('active'));

    if (view === 'tree') {
        document.getElementById('taxonomyTree').classList.remove('hidden');
        document.getElementById('treeViewBtn').classList.add('active');
    } else if (view === 'graph') {
        const graphEl = document.getElementById('taxonomyGraph');
        graphEl.classList.remove('hidden');
        // Force synchronous reflow so container has dimensions before rendering
        void graphEl.offsetHeight;
        document.getElementById('graphViewBtn').classList.add('active');
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`)
            .then(r => r.json())
            .then(cats => renderTaxonomyGraph(cats, []));
    } else if (view === 'knowledge') {
        if (kgContainer) {
            kgContainer.classList.remove('hidden');
            // Force synchronous reflow so container has dimensions before rendering
            void kgContainer.offsetHeight;
        }
        document.getElementById('kgViewBtn').classList.add('active');
        renderKnowledgeGraph();
    }
}

// --- Knowledge Graph ---
async function renderKnowledgeGraph() {
    const container = document.getElementById('kgCanvas');
    if (!container) return;
    if (!window.cytoscape) {
        _waitForLib('graph library', () => window.cytoscape, () => renderKnowledgeGraph(), container);
        return;
    }

    // Register plugins now that cytoscape is loaded
    _ensureCytoscapePlugins();

    const [catsRes, companiesRes] = await Promise.all([
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
        safeFetch(`/api/companies?project_id=${currentProjectId}&limit=200`),
    ]);
    const cats = await catsRes.json();
    const companies = await companiesRes.json();

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const elements = [];

    // Category nodes
    if (kgNodeTypes.category) {
        cats.forEach(cat => {
            elements.push({
                data: {
                    id: `cat-${cat.id}`, label: cat.name, type: 'category',
                    catColor: categoryColorMap[cat.id] || '#6b8fa3',
                },
            });
            if (cat.parent_id) {
                elements.push({ data: { source: `cat-${cat.parent_id}`, target: `cat-${cat.id}`, edgeType: 'has_subcategory' } });
            }
        });
    }

    // Company nodes + edges
    const allTags = new Set();
    const allGeos = new Set();

    if (kgNodeTypes.company) {
        companies.forEach(c => {
            elements.push({
                data: { id: `co-${c.id}`, label: c.name, type: 'company', companyId: c.id },
            });
            if (c.category_id && kgNodeTypes.category) {
                elements.push({ data: { source: `co-${c.id}`, target: `cat-${c.category_id}`, edgeType: 'belongs_to' } });
            }
            (c.tags || []).forEach(t => {
                allTags.add(t);
                if (kgNodeTypes.tag) {
                    elements.push({ data: { source: `co-${c.id}`, target: `tag-${t}`, edgeType: 'tagged_with' } });
                }
            });
            if (c.geography && kgNodeTypes.geography) {
                const geo = c.geography.split(',')[0].trim();
                allGeos.add(geo);
                elements.push({ data: { source: `co-${c.id}`, target: `geo-${geo}`, edgeType: 'located_in' } });
            }
        });
    }

    // Tag nodes
    if (kgNodeTypes.tag) {
        allTags.forEach(t => {
            elements.push({ data: { id: `tag-${t}`, label: t, type: 'tag' } });
        });
    }

    // Geography nodes
    if (kgNodeTypes.geography) {
        allGeos.forEach(g => {
            elements.push({ data: { id: `geo-${g}`, label: g, type: 'geography' } });
        });
    }

    if (kgInstance) kgInstance.destroy();

    if (!elements.length) {
        container.innerHTML = '<div class="graph-loading"><p>No data to display. Add companies and categories first.</p></div>';
        return;
    }

    // Double-RAF ensures the container has actual layout dimensions after unhiding
    requestAnimationFrame(() => { requestAnimationFrame(() => {
        const rect = container.getBoundingClientRect();
        if (rect.width < 10 || rect.height < 10) {
            container.style.width = '100%';
            container.style.height = '500px';
            container.style.minHeight = '500px';
        }

        // Determine layout: prefer fcose if registered, fallback to cose
        let kgLayoutConfig;
        try {
            const hasFcose = window.cytoscapeFcose && typeof cytoscape('layout', 'fcose') !== 'undefined';
            kgLayoutConfig = hasFcose
                ? { name: 'fcose', animate: false, nodeDimensionsIncludeLabels: true, idealEdgeLength: 100 }
                : { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 8000 };
        } catch (_) {
            kgLayoutConfig = { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 8000 };
        }

        try {
            kgInstance = cytoscape({
                container,
                elements,
                style: [
                    {
                        selector: 'node[type="category"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 1,
                            'border-color': '#000000',
                            label: 'data(label)', 'text-valign': 'bottom', 'text-margin-y': 4,
                            'font-size': '12px', 'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#CCCCCC' : '#000000',
                            width: 30, height: 30, shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node[type="company"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 1,
                            'border-color': '#333333',
                            label: 'data(label)', 'text-valign': 'bottom', 'text-margin-y': 4,
                            'font-size': '12px', 'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#CCCCCC' : '#000000',
                            width: 18, height: 18, shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node[type="tag"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 1,
                            'border-color': '#666666',
                            label: 'data(label)', 'text-valign': 'bottom', 'text-margin-y': 3,
                            'font-size': '12px', 'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#999999' : '#333333',
                            width: 12, height: 12, shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node[type="geography"]',
                        style: {
                            'background-color': '#FFFFFF',
                            'border-width': 1,
                            'border-color': '#999999',
                            label: 'data(label)', 'text-valign': 'bottom', 'text-margin-y': 3,
                            'font-size': '12px', 'font-family': 'Plus Jakarta Sans, sans-serif',
                            color: isDark ? '#999999' : '#333333',
                            width: 14, height: 14, shape: 'rectangle',
                        },
                    },
                    {
                        selector: 'node:selected',
                        style: {
                            'background-color': '#000000',
                            color: '#FFFFFF',
                            'border-color': '#000000',
                        },
                    },
                    {
                        selector: 'edge',
                        style: {
                            width: 1, 'line-color': isDark ? '#666666' : '#999999',
                            'curve-style': 'bezier', opacity: 0.6,
                        },
                    },
                    {
                        selector: '.kg-dimmed',
                        style: { opacity: 0.15 },
                    },
                    {
                        selector: '.kg-highlighted',
                        style: { opacity: 1, 'border-width': 2, 'border-color': '#000000' },
                    },
                ],
                layout: kgLayoutConfig,
                wheelSensitivity: 0.3,
            });
        } catch (e) {
            console.error('Knowledge graph init error:', e);
            container.innerHTML = `<div class="graph-loading"><p style="color:var(--accent-danger)">Knowledge graph failed: ${e.message}. <a href="#" onclick="location.reload();return false">Reload page</a></p></div>`;
            return;
        }

        // Fit after layout completes + fallback timeout
        kgInstance.one('layoutstop', () => {
            kgInstance.resize();
            kgInstance.fit(undefined, 30);
        });
        setTimeout(() => {
            if (kgInstance) {
                kgInstance.resize();
                kgInstance.fit(undefined, 30);
            }
        }, 500);

        // Click to highlight connections
        kgInstance.on('tap', 'node', (evt) => {
            const node = evt.target;
            kgInstance.elements().removeClass('kg-highlighted kg-dimmed').addClass('kg-dimmed');
            node.removeClass('kg-dimmed').addClass('kg-highlighted');
            node.connectedEdges().removeClass('kg-dimmed').addClass('kg-highlighted');
            node.neighborhood('node').removeClass('kg-dimmed').addClass('kg-highlighted');
        });

        kgInstance.on('tap', (evt) => {
            if (evt.target === kgInstance) {
                kgInstance.elements().removeClass('kg-highlighted kg-dimmed');
            }
        });

        // Double-click company to navigate
        kgInstance.on('dbltap', 'node[type="company"]', (evt) => {
            const id = evt.target.data('companyId');
            if (id) showDetail(id);
        });
    }); });
}

function toggleKgNodeType(type) {
    kgNodeTypes[type] = !kgNodeTypes[type];
    renderKnowledgeGraph();
}
