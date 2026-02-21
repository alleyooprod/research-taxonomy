/**
 * Feature Standardisation — canonical vocabulary management UI.
 * Phase 3.5 of the Research Workbench.
 *
 * Manages canonical features (standard names) and their mappings from
 * raw extracted values. Lives within the Review tab as a sub-section.
 */

// Feature state
let _features = [];              // [{id, canonical_name, category, mapping_count, ...}]
let _featureCategories = [];     // Distinct category strings
let _featureStats = [];          // [{attr_slug, feature_count, mapping_count}]
let _featureCategoryFilter = null; // Current category filter
let _featureSearch = '';         // Current search text
let _featureAttrSlug = null;     // Current attr_slug filter (auto-detected)
let _featureExpanded = new Set();// Feature IDs whose mapping lists are expanded
let _unmappedValues = [];        // Raw values without a canonical mapping

/**
 * Initialize features section — called alongside review queue init.
 */
async function initFeatures() {
    if (!currentProjectId) return;

    // Detect tags-type attributes from schema
    _detectTagsAttributes();

    await Promise.all([
        _loadFeatureStats(),
        _loadFeatures(),
        _loadFeatureCategories(),
    ]);
}

/**
 * Detect which attributes in current schema are tags type (feature-like).
 */
function _detectTagsAttributes() {
    const schema = window._currentProjectSchema;
    if (!schema || !schema.entity_types) return;

    const tagAttrs = [];
    for (const et of schema.entity_types) {
        if (!et.attributes) continue;
        for (const attr of et.attributes) {
            if (attr.data_type === 'tags') {
                tagAttrs.push(attr.slug);
            }
        }
    }

    // Default to first tags attribute if none selected
    if (!_featureAttrSlug && tagAttrs.length > 0) {
        _featureAttrSlug = tagAttrs[0];
    }

    // Render attr selector if multiple
    const selectorEl = document.getElementById('featureAttrSelector');
    if (selectorEl && tagAttrs.length > 1) {
        selectorEl.innerHTML = tagAttrs.map(slug =>
            `<button class="feat-attr-btn ${slug === _featureAttrSlug ? 'feat-attr-btn-active' : ''}"
                     data-action="set-feature-attr-slug" data-value="${slug}">${slug}</button>`
        ).join('');
        selectorEl.classList.remove('hidden');
    } else if (selectorEl) {
        selectorEl.classList.add('hidden');
    }
}

function setFeatureAttrSlug(slug) {
    _featureAttrSlug = slug;
    _featureCategoryFilter = null;
    _featureExpanded.clear();
    initFeatures();
}

// ── Stats ────────────────────────────────────────────────────

async function _loadFeatureStats() {
    if (!currentProjectId) return;
    try {
        const resp = await fetch(`/api/features/stats?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        _featureStats = await resp.json();
        _renderFeatureStats();
    } catch (e) {
        console.warn('Failed to load feature stats:', e);
    }
}

function _renderFeatureStats() {
    const el = document.getElementById('featureStats');
    if (!el) return;

    const current = _featureStats.find(s => s.attr_slug === _featureAttrSlug);
    const featureCount = current ? current.feature_count : 0;
    const mappingCount = current ? current.mapping_count : 0;
    const unmappedCount = _unmappedValues.length;

    el.innerHTML = `
        <div class="feat-stat-row">
            <div class="feat-stat">
                <span class="feat-stat-value">${featureCount}</span>
                <span class="feat-stat-label">Canonical</span>
            </div>
            <div class="feat-stat">
                <span class="feat-stat-value">${mappingCount}</span>
                <span class="feat-stat-label">Mappings</span>
            </div>
            ${unmappedCount ? `<div class="feat-stat feat-stat-warn">
                <span class="feat-stat-value">${unmappedCount}</span>
                <span class="feat-stat-label">Unmapped</span>
            </div>` : ''}
        </div>
    `;
}

// ── Feature List ─────────────────────────────────────────────

async function _loadFeatures() {
    if (!currentProjectId) return;

    let url = `/api/features?project_id=${currentProjectId}`;
    if (_featureAttrSlug) url += `&attr_slug=${encodeURIComponent(_featureAttrSlug)}`;
    if (_featureCategoryFilter) url += `&category=${encodeURIComponent(_featureCategoryFilter)}`;
    if (_featureSearch) url += `&search=${encodeURIComponent(_featureSearch)}`;

    try {
        const resp = await fetch(url, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (!resp.ok) return;
        _features = await resp.json();
        _renderFeatureList();
    } catch (e) {
        console.warn('Failed to load features:', e);
    }

    // Also load unmapped values
    if (_featureAttrSlug) {
        _loadUnmapped();
    }
}

async function _loadUnmapped() {
    try {
        const resp = await fetch(
            `/api/features/unmapped?project_id=${currentProjectId}&attr_slug=${encodeURIComponent(_featureAttrSlug)}`,
            { headers: { 'X-CSRFToken': CSRF_TOKEN } },
        );
        if (!resp.ok) return;
        const data = await resp.json();
        _unmappedValues = data.unmapped || [];
        _renderFeatureStats();
        _renderUnmapped();
    } catch (e) {
        console.warn('Failed to load unmapped values:', e);
    }
}

async function _loadFeatureCategories() {
    if (!currentProjectId) return;
    try {
        let url = `/api/features/categories?project_id=${currentProjectId}`;
        if (_featureAttrSlug) url += `&attr_slug=${encodeURIComponent(_featureAttrSlug)}`;
        const resp = await fetch(url, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (!resp.ok) return;
        _featureCategories = await resp.json();
        _renderCategoryFilter();
    } catch (e) {
        console.warn('Failed to load categories:', e);
    }
}

// ── Category Filter ──────────────────────────────────────────

function _renderCategoryFilter() {
    const el = document.getElementById('featureCategoryFilter');
    if (!el) return;

    el.innerHTML = `
        <button class="feat-cat-btn ${!_featureCategoryFilter ? 'feat-cat-btn-active' : ''}"
                data-action="set-feature-category-filter" data-value="">All</button>
        ${_featureCategories.map(c => `
            <button class="feat-cat-btn ${_featureCategoryFilter === c ? 'feat-cat-btn-active' : ''}"
                    data-action="set-feature-category-filter" data-value="${escAttr(c)}">${esc(c)}</button>
        `).join('')}
    `;
}

function setFeatureCategoryFilter(cat) {
    _featureCategoryFilter = cat;
    _renderCategoryFilter();
    _loadFeatures();
}

function featureSearchInput(value) {
    _featureSearch = value.trim();
    clearTimeout(window._featureSearchTimeout);
    window._featureSearchTimeout = setTimeout(() => _loadFeatures(), 300);
}

// ── Feature List Rendering ───────────────────────────────────

function _renderFeatureList() {
    const container = document.getElementById('featureList');
    const empty = document.getElementById('featureEmptyState');
    if (!container) return;

    if (!_features || _features.length === 0) {
        container.innerHTML = '';
        if (empty) empty.classList.remove('hidden');
        return;
    }
    if (empty) empty.classList.add('hidden');

    container.innerHTML = _features.map(f => {
        const expanded = _featureExpanded.has(f.id);
        return `
            <div class="feat-card ${expanded ? 'feat-card-expanded' : ''}" data-feature-id="${f.id}">
                <div class="feat-card-header" data-action="toggle-feature-expand" data-id="${f.id}">
                    <div class="feat-card-info">
                        <span class="feat-card-name">${esc(f.canonical_name)}</span>
                        ${f.category ? `<span class="feat-card-category">${esc(f.category)}</span>` : ''}
                        <span class="feat-card-count">${f.mapping_count || 0} mapping${(f.mapping_count || 0) !== 1 ? 's' : ''}</span>
                    </div>
                    <div class="feat-card-actions">
                        <button class="btn btn-sm" data-action="edit-feature" data-id="${f.id}" title="Edit">Edit</button>
                        <button class="btn btn-sm" data-action="delete-feature" data-id="${f.id}" title="Delete">Delete</button>
                    </div>
                </div>
                ${expanded ? `<div class="feat-card-body" id="featBody_${f.id}">Loading...</div>` : ''}
            </div>
        `;
    }).join('');

    // Load expanded feature details
    for (const fid of _featureExpanded) {
        _loadFeatureDetail(fid);
    }
}

// ── Feature Detail (Expanded Card) ───────────────────────────

async function _loadFeatureDetail(featureId) {
    const body = document.getElementById(`featBody_${featureId}`);
    if (!body) return;

    try {
        const resp = await fetch(`/api/features/${featureId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) { body.innerHTML = 'Failed to load'; return; }
        const feature = await resp.json();
        _renderFeatureDetail(body, feature);
    } catch (e) {
        body.innerHTML = 'Failed to load';
    }
}

function _renderFeatureDetail(container, feature) {
    const mappings = feature.mappings || [];
    container.innerHTML = `
        ${feature.description ? `<div class="feat-description">${esc(feature.description)}</div>` : ''}
        <div class="feat-mappings-header">
            <span class="feat-mappings-title">Mappings (${mappings.length})</span>
            <button class="btn btn-sm" data-action="add-mapping" data-id="${feature.id}" title="Add mapping">+ Add</button>
        </div>
        <div class="feat-mappings-list">
            ${mappings.map(m => `
                <div class="feat-mapping-row">
                    <span class="feat-mapping-value">${esc(m.raw_value)}</span>
                    <button class="btn btn-sm feat-mapping-remove" data-action="remove-mapping" data-id="${m.id}" data-feature-id="${feature.id}"
                            title="Remove mapping">&times;</button>
                </div>
            `).join('')}
            ${mappings.length === 0 ? '<div class="feat-mapping-empty">No mappings yet</div>' : ''}
        </div>
    `;
}

function toggleFeatureExpand(featureId) {
    if (_featureExpanded.has(featureId)) {
        _featureExpanded.delete(featureId);
    } else {
        _featureExpanded.add(featureId);
    }
    _renderFeatureList();
}

// ── Create Feature ───────────────────────────────────────────

async function createFeature() {
    if (!currentProjectId || !_featureAttrSlug) return;

    const name = await showPromptDialog(
        'New Canonical Feature',
        'Enter a standardised feature name:',
        '',
    );
    if (!name || !name.trim()) return;

    const category = await showPromptDialog(
        'Category (optional)',
        'Enter a category for this feature (or leave blank):',
        '',
    );

    try {
        const resp = await fetch('/api/features', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                project_id: currentProjectId,
                attr_slug: _featureAttrSlug,
                canonical_name: name.trim(),
                category: category && category.trim() ? category.trim() : null,
            }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Create failed');
            return;
        }
        if (window.notyf) window.notyf.success(`Created "${name.trim()}"`);
        await initFeatures();
    } catch (e) {
        console.error('Create feature failed:', e);
        if (window.notyf) window.notyf.error('Create failed');
    }
}

// ── Edit Feature ─────────────────────────────────────────────

async function editFeature(featureId) {
    const feature = _features.find(f => f.id === featureId);
    if (!feature) return;

    const name = await showPromptDialog(
        'Edit Feature Name',
        'Canonical name:',
        feature.canonical_name,
    );
    if (name === null || name === undefined) return;

    const category = await showPromptDialog(
        'Edit Category',
        'Category:',
        feature.category || '',
    );
    if (category === null || category === undefined) return;

    try {
        const resp = await fetch(`/api/features/${featureId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                canonical_name: name.trim(),
                category: category.trim() || null,
            }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Update failed');
            return;
        }
        if (window.notyf) window.notyf.success('Feature updated');
        await initFeatures();
    } catch (e) {
        console.error('Edit feature failed:', e);
    }
}

// ── Delete Feature ───────────────────────────────────────────

async function deleteFeature(featureId) {
    const feature = _features.find(f => f.id === featureId);
    if (!feature) return;

    const confirmed = await window.showNativeConfirm({
        title: 'Delete Feature',
        message: `Delete "${feature.canonical_name}" and all its mappings?`,
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await fetch(`/api/features/${featureId}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (resp.ok) {
            if (window.notyf) window.notyf.success('Feature deleted');
            _featureExpanded.delete(featureId);
            await initFeatures();
        }
    } catch (e) {
        console.error('Delete feature failed:', e);
    }
}

// ── Mapping Management ───────────────────────────────────────

async function addMapping(featureId) {
    const rawValue = await showPromptDialog(
        'Add Mapping',
        'Enter a raw value that maps to this feature:',
        '',
    );
    if (!rawValue || !rawValue.trim()) return;

    try {
        const resp = await fetch(`/api/features/${featureId}/mappings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({ raw_value: rawValue.trim() }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Add failed');
            return;
        }
        if (window.notyf) window.notyf.success('Mapping added');
        _loadFeatureDetail(featureId);
        _loadFeatureStats();
        _loadUnmapped();
    } catch (e) {
        console.error('Add mapping failed:', e);
    }
}

async function removeMapping(mappingId, featureId) {
    try {
        const resp = await fetch(`/api/features/mappings/${mappingId}`, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (resp.ok) {
            _loadFeatureDetail(featureId);
            _loadFeatureStats();
            _loadUnmapped();
        }
    } catch (e) {
        console.error('Remove mapping failed:', e);
    }
}

// ── Merge Features ───────────────────────────────────────────

async function mergeFeatures() {
    if (_features.length < 2) {
        if (window.notyf) window.notyf.error('Need at least 2 features to merge');
        return;
    }

    // Let user pick the target
    const options = _features.map(f => ({
        value: String(f.id),
        label: f.canonical_name,
    }));

    const targetId = await showSelectDialog(
        'Merge Target',
        'Select the target feature (others merge into this):',
        options,
    );
    if (!targetId) return;

    // Let user pick sources
    const sourceOptions = _features
        .filter(f => String(f.id) !== targetId)
        .map(f => ({ value: String(f.id), label: f.canonical_name }));

    // For simplicity, use a prompt for source IDs
    const sourceInput = await showPromptDialog(
        'Source Features',
        `Select feature IDs to merge into "${_features.find(f => String(f.id) === targetId)?.canonical_name}".\nAvailable: ${sourceOptions.map(o => `${o.value}=${o.label}`).join(', ')}`,
        sourceOptions.map(o => o.value).join(','),
    );
    if (!sourceInput) return;

    const sourceIds = sourceInput.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n));
    if (sourceIds.length === 0) return;

    try {
        const resp = await fetch('/api/features/merge', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                target_id: parseInt(targetId),
                source_ids: sourceIds,
            }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Merge failed');
            return;
        }
        const data = await resp.json();
        if (window.notyf) window.notyf.success(`Merged ${data.mappings_moved} mappings`);
        _featureExpanded.clear();
        await initFeatures();
    } catch (e) {
        console.error('Merge failed:', e);
    }
}

// ── Unmapped Values ──────────────────────────────────────────

function _renderUnmapped() {
    const container = document.getElementById('featureUnmappedList');
    if (!container) return;

    if (!_unmappedValues || _unmappedValues.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <div class="feat-unmapped-header">
            <span class="feat-unmapped-title">Unmapped Values (${_unmappedValues.length})</span>
            <button class="btn btn-sm" data-action="suggest-canonical-names" title="AI suggest canonical names">AI Suggest</button>
        </div>
        <div class="feat-unmapped-values">
            ${_unmappedValues.map(v => `
                <div class="feat-unmapped-row">
                    <span class="feat-unmapped-value">${esc(v)}</span>
                    <button class="btn btn-sm" data-action="map-unmapped-value" data-value="${escAttr(v)}" title="Map to a feature">Map</button>
                    <button class="btn btn-sm" data-action="create-feature-from-unmapped" data-value="${escAttr(v)}" title="Create new feature">New</button>
                </div>
            `).join('')}
        </div>
    `;
}

async function mapUnmappedValue(rawValue) {
    if (_features.length === 0) {
        if (window.notyf) window.notyf.error('No features to map to — create one first');
        return;
    }

    const options = _features.map(f => ({
        value: String(f.id),
        label: f.canonical_name,
    }));

    const featureId = await showSelectDialog(
        'Map Value',
        `Map "${rawValue}" to which canonical feature?`,
        options,
    );
    if (!featureId) return;

    try {
        const resp = await fetch(`/api/features/${featureId}/mappings`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({ raw_value: rawValue }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Map failed');
            return;
        }
        if (window.notyf) window.notyf.success(`Mapped "${rawValue}"`);
        await initFeatures();
    } catch (e) {
        console.error('Map unmapped failed:', e);
    }
}

async function createFeatureFromUnmapped(rawValue) {
    const category = await showPromptDialog(
        'Category (optional)',
        `Create "${rawValue}" as a new canonical feature.\nEnter a category (or leave blank):`,
        '',
    );
    if (category === null || category === undefined) return;

    try {
        const resp = await fetch('/api/features', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                project_id: currentProjectId,
                attr_slug: _featureAttrSlug,
                canonical_name: rawValue,
                category: category.trim() || null,
                mappings: [rawValue],
            }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Create failed');
            return;
        }
        if (window.notyf) window.notyf.success(`Created "${rawValue}"`);
        await initFeatures();
    } catch (e) {
        console.error('Create from unmapped failed:', e);
    }
}

// ── AI Suggest ───────────────────────────────────────────────

async function suggestCanonicalNames() {
    if (!_unmappedValues.length) return;

    const btn = document.querySelector('[data-action="suggest-canonical-names"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Thinking...'; }

    try {
        const resp = await fetch('/api/features/suggest', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                project_id: currentProjectId,
                attr_slug: _featureAttrSlug,
                raw_values: _unmappedValues.slice(0, 50), // Cap at 50
            }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Suggest failed');
            return;
        }

        const data = await resp.json();
        _renderSuggestions(data.suggestions || []);
    } catch (e) {
        console.error('Suggest failed:', e);
        if (window.notyf) window.notyf.error('AI suggestion failed');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'AI Suggest'; }
    }
}

function _renderSuggestions(suggestions) {
    const container = document.getElementById('featureSuggestions');
    if (!container) return;

    if (!suggestions.length) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = `
        <div class="feat-suggestions-header">
            <span class="feat-suggestions-title">AI Suggestions</span>
            <button class="btn btn-sm" data-action="apply-all-suggestions" title="Apply all suggestions">Apply All</button>
        </div>
        <div class="feat-suggestions-list">
            ${suggestions.map((s, i) => `
                <div class="feat-suggestion-row" data-idx="${i}">
                    <span class="feat-suggestion-raw">${esc(s.raw_value)}</span>
                    <span class="feat-suggestion-arrow">&rarr;</span>
                    <span class="feat-suggestion-canonical">${esc(s.canonical_name)}</span>
                    ${s.category ? `<span class="feat-suggestion-cat">${esc(s.category)}</span>` : ''}
                    <span class="feat-suggestion-badge ${s.is_new ? 'feat-badge-new' : 'feat-badge-existing'}">${s.is_new ? 'new' : 'existing'}</span>
                    <button class="btn btn-sm" data-action="apply-suggestion" data-id="${i}">Apply</button>
                </div>
            `).join('')}
        </div>
    `;

    // Store suggestions for apply
    window._featureSuggestions = suggestions;
}

async function applySuggestion(idx) {
    const s = window._featureSuggestions?.[idx];
    if (!s) return;

    if (s.is_new) {
        // Create new feature + map the raw value
        try {
            const resp = await fetch('/api/features', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRF_TOKEN,
                },
                body: JSON.stringify({
                    project_id: currentProjectId,
                    attr_slug: _featureAttrSlug,
                    canonical_name: s.canonical_name,
                    category: s.category || null,
                    mappings: [s.raw_value],
                }),
            });
            if (resp.ok) {
                if (window.notyf) window.notyf.success(`Created "${s.canonical_name}"`);
            } else {
                const err = await resp.json();
                if (window.notyf) window.notyf.error(err.error || 'Apply failed');
            }
        } catch (e) {
            console.error('Apply suggestion failed:', e);
        }
    } else {
        // Resolve to find existing feature, then add mapping
        try {
            const resolveResp = await fetch('/api/features/resolve', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRF_TOKEN,
                },
                body: JSON.stringify({
                    project_id: currentProjectId,
                    attr_slug: _featureAttrSlug,
                    raw_value: s.canonical_name,
                }),
            });
            if (resolveResp.ok) {
                const resolved = await resolveResp.json();
                if (resolved.matched && resolved.canonical) {
                    await fetch(`/api/features/${resolved.canonical.id}/mappings`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': CSRF_TOKEN,
                        },
                        body: JSON.stringify({ raw_value: s.raw_value }),
                    });
                    if (window.notyf) window.notyf.success(`Mapped "${s.raw_value}"`);
                }
            }
        } catch (e) {
            console.error('Apply suggestion mapping failed:', e);
        }
    }

    // Remove from suggestions list
    const row = document.querySelector(`.feat-suggestion-row[data-idx="${idx}"]`);
    if (row) {
        row.style.opacity = '0';
        setTimeout(() => {
            row.remove();
            initFeatures();
        }, 200);
    } else {
        await initFeatures();
    }
}

async function applyAllSuggestions() {
    const suggestions = window._featureSuggestions;
    if (!suggestions || !suggestions.length) return;

    const confirmed = await window.showNativeConfirm({
        title: 'Apply All Suggestions',
        message: `Apply all ${suggestions.length} AI suggestions? New features will be created and raw values mapped.`,
        confirmText: 'Apply All',
        type: 'warning',
    });
    if (!confirmed) return;

    for (let i = 0; i < suggestions.length; i++) {
        await applySuggestion(i);
    }

    window._featureSuggestions = [];
    const container = document.getElementById('featureSuggestions');
    if (container) container.innerHTML = '';
    await initFeatures();
}

// ── Action Delegation ─────────────────────────────────────────

registerActions({
    'set-feature-attr-slug': (el) => setFeatureAttrSlug(el.dataset.value),
    'set-feature-category-filter': (el) => setFeatureCategoryFilter(el.dataset.value || null),
    'toggle-feature-expand': (el) => toggleFeatureExpand(Number(el.dataset.id)),
    'edit-feature': (el, e) => { e.stopPropagation(); editFeature(Number(el.dataset.id)); },
    'delete-feature': (el, e) => { e.stopPropagation(); deleteFeature(Number(el.dataset.id)); },
    'add-mapping': (el) => addMapping(Number(el.dataset.id)),
    'remove-mapping': (el) => removeMapping(Number(el.dataset.id), Number(el.dataset.featureId)),
    'suggest-canonical-names': () => suggestCanonicalNames(),
    'map-unmapped-value': (el) => mapUnmappedValue(el.dataset.value),
    'create-feature-from-unmapped': (el) => createFeatureFromUnmapped(el.dataset.value),
    'apply-suggestion': (el) => applySuggestion(Number(el.dataset.id)),
    'apply-all-suggestions': () => applyAllSuggestions(),
    'create-feature': () => createFeature(),
    'merge-features': () => mergeFeatures(),
    'feature-search-input': (el) => featureSearchInput(el.value),
});

// ── Expose on window (for external callers) ──────────────────

window.initFeatures = initFeatures;
