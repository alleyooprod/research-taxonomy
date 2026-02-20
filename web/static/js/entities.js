/**
 * Entity Browser — schema-aware drill-down entity list.
 * Works alongside companies.js; activated when project has multi-type schema.
 */

// Entity browser state
let _entityBrowserActive = false;
let _entityTypeFilter = null;     // Current type slug being viewed
let _entityParentStack = [];      // Breadcrumb: [{id, name, type_slug}]
let _entitySchema = null;         // Current project's parsed schema
let _entityTypeDefs = [];         // Type definitions from API
let _entityBulkSelection = new Set();
let _entityList = [];             // Last loaded entities

/**
 * Initialize entity browser for the current project.
 * Called from selectProject() after schema loads.
 */
function initEntityBrowser() {
    const schema = window._currentProjectSchema;
    if (!schema || !schema.entity_types || schema.entity_types.length <= 1) {
        _entityBrowserActive = false;
        _showCompanyView();
        return;
    }

    _entityBrowserActive = true;
    _entitySchema = schema;
    _entityTypeFilter = null;
    _entityParentStack = [];
    _entityBulkSelection = new Set();

    _showEntityBrowser();
    _renderEntityTypeBar();
    _renderEntityBreadcrumbs();

    // Default to first root type
    const rootTypes = schema.entity_types.filter(t => !t.parent_type);
    if (rootTypes.length > 0) {
        _setEntityTypeFilter(rootTypes[0].slug);
    }
}

function _showEntityBrowser() {
    const eb = document.getElementById('entityBrowser');
    const cv = document.getElementById('companyViewWrapper');
    if (eb) eb.classList.remove('hidden');
    if (cv) cv.classList.add('hidden');
}

function _showCompanyView() {
    const eb = document.getElementById('entityBrowser');
    const cv = document.getElementById('companyViewWrapper');
    if (eb) eb.classList.add('hidden');
    if (cv) cv.classList.remove('hidden');
}

/**
 * Render the entity type selector bar.
 */
function _renderEntityTypeBar() {
    const bar = document.getElementById('entityTypeBar');
    if (!bar || !_entitySchema) return;

    const rootTypes = _entitySchema.entity_types.filter(t => !t.parent_type);

    bar.innerHTML = rootTypes.map(t => {
        const active = t.slug === _entityTypeFilter ? 'entity-type-btn-active' : '';
        const count = ''; // Will be updated by stats
        return `<button class="entity-type-btn ${active}" data-type="${escAttr(t.slug)}"
                    onclick="_setEntityTypeFilter('${escAttr(t.slug)}')">${esc(t.name)}${count}</button>`;
    }).join('');

    // Load stats to show counts on type buttons
    _loadEntityTypeCounts();
}

async function _loadEntityTypeCounts() {
    if (!currentProjectId) return;
    try {
        const res = await safeFetch(`/api/entity-stats?project_id=${currentProjectId}`);
        const stats = await res.json();
        document.querySelectorAll('.entity-type-btn').forEach(btn => {
            const slug = btn.dataset.type;
            const count = stats[slug] || 0;
            const existing = btn.textContent.replace(/\s*\(\d+\)$/, '');
            btn.textContent = `${existing} (${count})`;
        });
    } catch (e) { /* stats are cosmetic */ }
}

function _setEntityTypeFilter(typeSlug) {
    _entityTypeFilter = typeSlug;
    _entityParentStack = [];
    _entityBulkSelection = new Set();

    // Update active state in type bar
    document.querySelectorAll('.entity-type-btn').forEach(btn => {
        btn.classList.toggle('entity-type-btn-active', btn.dataset.type === typeSlug);
    });

    _renderEntityBreadcrumbs();
    loadEntities();
}

/**
 * Drill down into a parent entity — show its children.
 */
function entityDrillDown(entityId, entityName, typeSlug) {
    _entityParentStack.push({ id: entityId, name: entityName, type_slug: typeSlug });

    // Find child type
    const childTypes = _entitySchema.entity_types.filter(t => t.parent_type === typeSlug);
    if (childTypes.length > 0) {
        _entityTypeFilter = childTypes[0].slug;
    }

    _entityBulkSelection = new Set();
    _renderEntityBreadcrumbs();
    loadEntities();
}

/**
 * Navigate to a specific breadcrumb level.
 */
function entityBreadcrumbNav(index) {
    if (index < 0) {
        // Back to root
        _entityParentStack = [];
        const rootTypes = _entitySchema.entity_types.filter(t => !t.parent_type);
        if (rootTypes.length > 0) _entityTypeFilter = rootTypes[0].slug;
    } else {
        const entry = _entityParentStack[index];
        _entityParentStack = _entityParentStack.slice(0, index + 1);
        // Child type of this level
        const childTypes = _entitySchema.entity_types.filter(t => t.parent_type === entry.type_slug);
        if (childTypes.length > 0) _entityTypeFilter = childTypes[0].slug;
    }

    _entityBulkSelection = new Set();
    _renderEntityBreadcrumbs();
    loadEntities();
}

function _renderEntityBreadcrumbs() {
    const bar = document.getElementById('entityBreadcrumbs');
    if (!bar) return;

    if (_entityParentStack.length === 0) {
        bar.classList.add('hidden');
        return;
    }

    let html = `<span class="entity-bc-item entity-bc-link" onclick="entityBreadcrumbNav(-1)">Root</span>`;
    _entityParentStack.forEach((entry, i) => {
        const isLast = i === _entityParentStack.length - 1;
        html += `<span class="entity-bc-sep">/</span>`;
        if (isLast) {
            html += `<span class="entity-bc-item entity-bc-current">${esc(entry.name)}</span>`;
        } else {
            html += `<span class="entity-bc-item entity-bc-link" onclick="entityBreadcrumbNav(${i})">${esc(entry.name)}</span>`;
        }
    });

    bar.innerHTML = html;
    bar.classList.remove('hidden');
}

/**
 * Load entities for the current type/parent context.
 */
async function loadEntities() {
    if (!currentProjectId || !_entityTypeFilter) return;

    const searchVal = document.getElementById('entitySearchInput')?.value?.trim() || '';

    let url = `/api/entities?project_id=${currentProjectId}&type=${_entityTypeFilter}`;

    // If drilled down, filter by parent
    if (_entityParentStack.length > 0) {
        const parentId = _entityParentStack[_entityParentStack.length - 1].id;
        url += `&parent_id=${parentId}`;
    } else {
        url += '&parent_id=root';
    }

    if (searchVal) url += `&search=${encodeURIComponent(searchVal)}`;

    try {
        const res = await safeFetch(url);
        _entityList = await res.json();
        _renderEntityList(_entityList);
    } catch (e) {
        _renderEntityList([]);
    }
}

/**
 * Get the type definition for the current entity type.
 */
function _getCurrentTypeDef() {
    if (!_entitySchema || !_entityTypeFilter) return null;
    return _entitySchema.entity_types.find(t => t.slug === _entityTypeFilter) || null;
}

/**
 * Render entity list as a table with schema-driven columns.
 */
function _renderEntityList(entities) {
    const tbody = document.getElementById('entityTableBody');
    const emptyState = document.getElementById('entityEmptyState');
    const table = document.getElementById('entityTable');
    if (!tbody || !table) return;

    const typeDef = _getCurrentTypeDef();
    const childTypes = _entitySchema ? _entitySchema.entity_types.filter(t => t.parent_type === _entityTypeFilter) : [];
    const hasChildren = childTypes.length > 0;

    // Build column headers
    const attrs = (typeDef?.attributes || []).slice(0, 5); // Show first 5 attributes
    const thead = document.getElementById('entityTableHead');
    if (thead) {
        let headerHtml = `<tr>
            <th class="col-bulk"><input type="checkbox" onchange="_toggleEntitySelectAll(this)" aria-label="Select all"></th>
            <th class="col-starred"></th>
            <th>Name</th>`;
        attrs.forEach(a => {
            headerHtml += `<th>${esc(a.name)}</th>`;
        });
        if (hasChildren) headerHtml += `<th>${esc(childTypes[0].name)}s</th>`;
        headerHtml += `<th>Evidence</th></tr>`;
        thead.innerHTML = headerHtml;
    }

    if (entities.length === 0) {
        tbody.innerHTML = '';
        if (emptyState) {
            emptyState.classList.remove('hidden');
            const typeName = typeDef?.name || 'entity';
            emptyState.querySelector('.empty-state-title').textContent = `No ${typeName}s yet`;
            emptyState.querySelector('.empty-state-desc').textContent =
                _entityParentStack.length > 0
                    ? `Add ${typeName.toLowerCase()}s to ${_entityParentStack[_entityParentStack.length - 1].name}`
                    : `Create your first ${typeName.toLowerCase()} to get started`;
        }
        table.classList.add('hidden');
        return;
    }

    if (emptyState) emptyState.classList.add('hidden');
    table.classList.remove('hidden');

    tbody.innerHTML = entities.map(e => {
        const isSelected = _entityBulkSelection.has(e.id);
        const starred = e.is_starred ? 'starred' : '';
        const drillable = hasChildren && e.child_count > 0;

        let row = `<tr class="${isSelected ? 'selected-row' : ''}" data-entity-id="${e.id}">
            <td class="col-bulk"><input type="checkbox" ${isSelected ? 'checked' : ''} onchange="_toggleEntitySelect(${e.id}, this)"></td>
            <td class="col-starred"><span class="star ${starred}" onclick="toggleEntityStar(${e.id})">&#9733;</span></td>
            <td class="entity-name-cell">
                <span class="entity-name" onclick="showEntityDetail(${e.id})">${esc(e.name)}</span>`;

        if (drillable) {
            row += ` <button class="entity-drill-btn" onclick="entityDrillDown(${e.id}, '${escAttr(e.name)}', '${escAttr(e.type_slug)}')"
                        title="View ${childTypes[0].name}s">${e.child_count} &rarr;</button>`;
        }

        row += `</td>`;

        // Attribute columns
        const eAttrs = e.attributes || {};
        attrs.forEach(a => {
            const val = eAttrs[a.slug];
            const displayVal = val ? (typeof val === 'object' ? val.value || '' : val) : '';
            row += `<td class="entity-attr-cell">${esc(String(displayVal).substring(0, 80))}</td>`;
        });

        if (hasChildren) {
            row += `<td class="entity-child-count">${e.child_count || 0}</td>`;
        }

        row += `<td class="entity-evidence-count">${e.evidence_count || 0}</td>`;
        row += `</tr>`;
        return row;
    }).join('');

    _updateEntityBulkBar();
}

/**
 * Show entity detail panel.
 */
async function showEntityDetail(entityId) {
    try {
        const res = await safeFetch(`/api/entities/${entityId}`);
        const entity = await res.json();
        _renderEntityDetail(entity);
    } catch (e) {
        showToast('Failed to load entity');
    }
}

function _renderEntityDetail(entity) {
    const panel = document.getElementById('entityDetailPanel');
    if (!panel) return;

    // Store entity ID for drag-drop and clipboard paste
    panel.dataset.entityId = String(entity.id);

    const typeDef = _entitySchema?.entity_types?.find(t => t.slug === entity.type_slug);
    const attrs = typeDef?.attributes || [];
    const eAttrs = entity.attributes || {};

    let html = `
        <div class="entity-drop-zone" id="entityDetailDropZone">
            <div class="cap-drop-zone-inner">
                <div class="cap-drop-zone-icon">&#8681;</div>
                <div class="cap-drop-zone-text">Drop to add evidence for ${esc(entity.name)}</div>
            </div>
        </div>
        <div class="detail-header">
            <div>
                <span class="entity-type-badge">${esc(typeDef?.name || entity.type_slug)}</span>
                <h2>${esc(entity.name)}</h2>
            </div>
            <button class="close-btn" onclick="closeEntityDetail()">&times;</button>
        </div>
        <div class="entity-detail-body">`;

    // Attributes section
    html += `<div class="entity-detail-section">
        <h3 class="section-label">ATTRIBUTES</h3>`;
    attrs.forEach(a => {
        const val = eAttrs[a.slug];
        const displayVal = val ? (typeof val === 'object' ? val.value || '' : val) : '';
        const source = val && typeof val === 'object' ? val.source : '';
        const confidence = val && typeof val === 'object' ? val.confidence : null;
        html += `<div class="entity-attr-row">
            <span class="entity-attr-label">${esc(a.name)}</span>
            <span class="entity-attr-value">${esc(String(displayVal))}</span>
            ${source ? `<span class="entity-attr-source">${esc(source)}</span>` : ''}
        </div>`;
    });
    html += `</div>`;

    // Children section
    const childTypes = _entitySchema?.entity_types?.filter(t => t.parent_type === entity.type_slug) || [];
    if (childTypes.length > 0 && entity.child_count > 0) {
        html += `<div class="entity-detail-section">
            <h3 class="section-label">CHILDREN</h3>
            <p>${entity.child_count} ${childTypes[0].name}(s)
            <button class="btn btn-sm" onclick="entityDrillDown(${entity.id}, '${escAttr(entity.name)}', '${escAttr(entity.type_slug)}'); closeEntityDetail()">
                View &rarr;
            </button></p>
        </div>`;
    }

    // Evidence section
    html += `<div class="entity-detail-section">
        <h3 class="section-label">EVIDENCE</h3>
        <p>${entity.evidence_count || 0} item(s)</p>
        <p class="hint-text" style="margin-top:4px;">Drop files here or paste screenshots to add evidence</p>
    </div>`;

    // Actions
    html += `<div class="entity-detail-actions">
        <button class="btn" onclick="openEntityEditModal(${entity.id})">Edit</button>
        <button class="danger-btn" onclick="deleteEntity(${entity.id})">Delete</button>
    </div>`;

    html += `</div>`;

    panel.innerHTML = html;
    panel.classList.remove('hidden');

    // Set up drag-and-drop on this panel
    _initEntityDetailDragDrop(panel);
}

function closeEntityDetail() {
    const panel = document.getElementById('entityDetailPanel');
    if (panel) panel.classList.add('hidden');
}

/**
 * Entity CRUD operations.
 */
async function openEntityCreateModal() {
    const typeDef = _getCurrentTypeDef();
    if (!typeDef) return;

    const attrs = typeDef.attributes || [];

    const modal = document.getElementById('entityModal');
    const title = document.getElementById('entityModalTitle');
    const body = document.getElementById('entityModalBody');
    if (!modal || !body) return;

    title.textContent = `New ${typeDef.name}`;

    let html = `<div class="entity-form">
        <div class="form-group">
            <label>Name *</label>
            <input type="text" id="entityFormName" required placeholder="Enter name">
        </div>`;

    attrs.forEach(a => {
        html += _renderAttributeFormField(a);
    });

    html += `<div class="form-actions">
        <button class="primary-btn" onclick="_saveNewEntity()">Create</button>
        <button class="btn" onclick="closeEntityModal()">Cancel</button>
    </div></div>`;

    body.innerHTML = html;
    modal.classList.remove('hidden');
    document.getElementById('entityFormName')?.focus();
}

function _renderAttributeFormField(attr) {
    const id = `entityAttr_${attr.slug}`;
    let input = '';

    switch (attr.data_type) {
        case 'boolean':
            input = `<label class="filter-checkbox"><input type="checkbox" id="${id}"> ${esc(attr.name)}</label>`;
            return `<div class="form-group">${input}</div>`;
        case 'enum':
            const options = (attr.enum_values || []).map(v =>
                `<option value="${escAttr(v)}">${esc(v)}</option>`
            ).join('');
            input = `<select id="${id}"><option value="">Select...</option>${options}</select>`;
            break;
        case 'number':
        case 'currency':
            input = `<input type="number" id="${id}" step="any" placeholder="${esc(attr.name)}">`;
            break;
        case 'url':
            input = `<input type="url" id="${id}" placeholder="https://...">`;
            break;
        case 'date':
            input = `<input type="date" id="${id}">`;
            break;
        case 'tags':
            input = `<input type="text" id="${id}" placeholder="Comma-separated tags">`;
            break;
        default: // text, json
            input = `<textarea id="${id}" rows="2" placeholder="${esc(attr.name)}"></textarea>`;
    }

    return `<div class="form-group">
        <label for="${id}">${esc(attr.name)}${attr.required ? ' *' : ''}</label>
        ${input}
    </div>`;
}

function _getAttributeFormValues() {
    const typeDef = _getCurrentTypeDef();
    if (!typeDef) return {};

    const values = {};
    (typeDef.attributes || []).forEach(a => {
        const el = document.getElementById(`entityAttr_${a.slug}`);
        if (!el) return;

        let val;
        if (a.data_type === 'boolean') {
            val = el.checked;
        } else if (a.data_type === 'tags') {
            val = el.value.split(',').map(t => t.trim()).filter(Boolean);
        } else {
            val = el.value.trim();
        }

        if (val !== '' && val !== false && !(Array.isArray(val) && val.length === 0)) {
            values[a.slug] = val;
        }
    });
    return values;
}

async function _saveNewEntity() {
    const name = document.getElementById('entityFormName')?.value?.trim();
    if (!name) {
        showToast('Name is required');
        return;
    }

    const attributes = _getAttributeFormValues();
    const parentId = _entityParentStack.length > 0
        ? _entityParentStack[_entityParentStack.length - 1].id
        : null;

    try {
        const res = await safeFetch('/api/entities', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: currentProjectId,
                type: _entityTypeFilter,
                name,
                parent_id: parentId,
                attributes,
            }),
        });
        const result = await res.json();
        if (result.error) {
            showToast(result.error);
            return;
        }

        closeEntityModal();
        loadEntities();
        _loadEntityTypeCounts();
        showToast(`${name} created`);
    } catch (e) {
        showToast('Failed to create entity');
    }
}

async function openEntityEditModal(entityId) {
    try {
        const res = await safeFetch(`/api/entities/${entityId}`);
        const entity = await res.json();

        const typeDef = _entitySchema?.entity_types?.find(t => t.slug === entity.type_slug);
        if (!typeDef) return;

        const modal = document.getElementById('entityModal');
        const title = document.getElementById('entityModalTitle');
        const body = document.getElementById('entityModalBody');
        if (!modal || !body) return;

        title.textContent = `Edit ${typeDef.name}`;

        const attrs = typeDef.attributes || [];
        const eAttrs = entity.attributes || {};

        let html = `<div class="entity-form">
            <input type="hidden" id="entityFormId" value="${entity.id}">
            <div class="form-group">
                <label>Name *</label>
                <input type="text" id="entityFormName" required value="${escAttr(entity.name)}">
            </div>`;

        attrs.forEach(a => {
            html += _renderAttributeFormField(a);
        });

        html += `<div class="form-actions">
            <button class="primary-btn" onclick="_saveEditEntity()">Save</button>
            <button class="btn" onclick="closeEntityModal()">Cancel</button>
        </div></div>`;

        body.innerHTML = html;

        // Populate attribute values
        attrs.forEach(a => {
            const el = document.getElementById(`entityAttr_${a.slug}`);
            if (!el) return;
            const val = eAttrs[a.slug];
            const displayVal = val ? (typeof val === 'object' ? val.value || '' : val) : '';

            if (a.data_type === 'boolean') {
                el.checked = displayVal === true || displayVal === '1' || displayVal === 'true';
            } else {
                el.value = displayVal;
            }
        });

        modal.classList.remove('hidden');
    } catch (e) {
        showToast('Failed to load entity');
    }
}

async function _saveEditEntity() {
    const entityId = document.getElementById('entityFormId')?.value;
    const name = document.getElementById('entityFormName')?.value?.trim();
    if (!entityId || !name) {
        showToast('Name is required');
        return;
    }

    const attributes = _getAttributeFormValues();

    try {
        const res = await safeFetch(`/api/entities/${entityId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, attributes }),
        });
        const result = await res.json();
        if (result.error) {
            showToast(result.error);
            return;
        }

        closeEntityModal();
        closeEntityDetail();
        loadEntities();
        showToast(`${name} updated`);
    } catch (e) {
        showToast('Failed to save entity');
    }
}

function closeEntityModal() {
    const modal = document.getElementById('entityModal');
    if (modal) modal.classList.add('hidden');
}

async function deleteEntity(entityId) {
    const entity = _entityList.find(e => e.id === entityId);
    const name = entity?.name || 'this entity';

    showNativeConfirm(`Delete ${name}?`, 'This will also delete all child entities.', 'Delete', 'danger', async () => {
        try {
            await safeFetch(`/api/entities/${entityId}`, { method: 'DELETE' });
            closeEntityDetail();
            loadEntities();
            _loadEntityTypeCounts();
            showToast(`${name} deleted`);
        } catch (e) {
            showToast('Failed to delete');
        }
    });
}

async function toggleEntityStar(entityId) {
    try {
        await safeFetch(`/api/entities/${entityId}/star`, { method: 'POST' });
        loadEntities();
    } catch (e) { /* silent */ }
}

// Bulk selection
function _toggleEntitySelect(entityId, checkbox) {
    if (checkbox.checked) {
        _entityBulkSelection.add(entityId);
    } else {
        _entityBulkSelection.delete(entityId);
    }
    _updateEntityBulkBar();
}

function _toggleEntitySelectAll(checkbox) {
    _entityList.forEach(e => {
        if (checkbox.checked) {
            _entityBulkSelection.add(e.id);
        } else {
            _entityBulkSelection.delete(e.id);
        }
    });
    // Update row checkboxes
    document.querySelectorAll('#entityTableBody input[type=checkbox]').forEach(cb => {
        cb.checked = checkbox.checked;
    });
    _updateEntityBulkBar();
}

function _updateEntityBulkBar() {
    const bar = document.getElementById('entityBulkBar');
    const count = document.getElementById('entityBulkCount');
    if (!bar) return;

    if (_entityBulkSelection.size > 0) {
        bar.classList.remove('hidden');
        if (count) count.textContent = `${_entityBulkSelection.size} selected`;
    } else {
        bar.classList.add('hidden');
    }
}

function clearEntityBulkSelection() {
    _entityBulkSelection = new Set();
    document.querySelectorAll('#entityTableBody input[type=checkbox], #entityTable thead input[type=checkbox]').forEach(cb => {
        cb.checked = false;
    });
    _updateEntityBulkBar();
}

async function entityBulkAction(action) {
    if (_entityBulkSelection.size === 0) return;
    const ids = [..._entityBulkSelection];

    if (action === 'delete') {
        showNativeConfirm(`Delete ${ids.length} entities?`, 'This will also delete all child entities.', 'Delete', 'danger', async () => {
            await safeFetch('/api/entities/bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ids, action: 'delete' }),
            });
            clearEntityBulkSelection();
            loadEntities();
            _loadEntityTypeCounts();
            showToast(`${ids.length} entities deleted`);
        });
    } else if (action === 'star') {
        await safeFetch('/api/entities/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids, action: 'star' }),
        });
        clearEntityBulkSelection();
        loadEntities();
    } else if (action === 'unstar') {
        await safeFetch('/api/entities/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids, action: 'unstar' }),
        });
        clearEntityBulkSelection();
        loadEntities();
    }
}

/**
 * Debounced entity search.
 */
let _entitySearchTimer = null;
function debounceEntitySearch() {
    clearTimeout(_entitySearchTimer);
    _entitySearchTimer = setTimeout(loadEntities, 300);
}

// ── Entity Detail Panel Drag & Drop ─────────────────────────

let _entityDetailDragCounter = 0;

/**
 * Set up drag-and-drop handlers on the entity detail panel.
 * Called each time _renderEntityDetail renders new content.
 */
function _initEntityDetailDragDrop(panel) {
    if (!panel) return;
    _entityDetailDragCounter = 0;

    // Remove old listeners (in case of re-render)
    panel.removeEventListener('dragenter', _onEntityDetailDragEnter);
    panel.removeEventListener('dragover', _onEntityDetailDragOver);
    panel.removeEventListener('dragleave', _onEntityDetailDragLeave);
    panel.removeEventListener('drop', _onEntityDetailDrop);

    panel.addEventListener('dragenter', _onEntityDetailDragEnter);
    panel.addEventListener('dragover', _onEntityDetailDragOver);
    panel.addEventListener('dragleave', _onEntityDetailDragLeave);
    panel.addEventListener('drop', _onEntityDetailDrop);
}

function _onEntityDetailDragEnter(e) {
    e.preventDefault();
    e.stopPropagation();
    _entityDetailDragCounter++;
    if (_entityDetailDragCounter === 1) {
        _showEntityDetailDropZone(true);
    }
}

function _onEntityDetailDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
}

function _onEntityDetailDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    _entityDetailDragCounter--;
    if (_entityDetailDragCounter <= 0) {
        _entityDetailDragCounter = 0;
        _showEntityDetailDropZone(false);
    }
}

function _onEntityDetailDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    _entityDetailDragCounter = 0;
    _showEntityDetailDropZone(false);

    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;

    const panel = document.getElementById('entityDetailPanel');
    const entityId = panel?.dataset?.entityId;
    if (!entityId) return;

    // Upload directly to this entity (no need to ask)
    if (typeof window._uploadFilesToEntity === 'function') {
        window._uploadFilesToEntity(Array.from(files), entityId);
    }
}

function _showEntityDetailDropZone(show) {
    const zone = document.getElementById('entityDetailDropZone');
    const panel = document.getElementById('entityDetailPanel');
    if (!zone) return;
    if (show) {
        zone.style.display = 'flex';
        zone.offsetHeight; // eslint-disable-line no-unused-expressions
        zone.classList.add('active');
        if (panel) panel.classList.add('cap-drag-over');
    } else {
        zone.classList.remove('active');
        if (panel) panel.classList.remove('cap-drag-over');
        setTimeout(() => {
            if (!zone.classList.contains('active')) {
                zone.style.display = 'none';
            }
        }, 200);
    }
}
