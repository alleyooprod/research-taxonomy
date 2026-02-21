/**
 * Company list, detail panel, edit modal, star, sort.
 * Integrates Tabulator (data grid) and MiniSearch (fuzzy search) when available.
 */

// Fallback if showNativeConfirm hasn't been loaded yet
const _confirm = window.showNativeConfirm || (async (opts) => confirm(opts.message || opts.title));

let currentSort = { by: 'name', dir: 'asc' };
let currentCompanyView = 'table';
let _lastCompanies = [];

function safeHref(url) {
    if (!url) return '';
    try {
        const u = new URL(url, window.location.origin);
        return ['http:', 'https:'].includes(u.protocol) ? esc(url) : '';
    } catch { return esc(url); }
}

// --- Tabulator instance ---
let _tabulatorTable = null;

// --- MiniSearch instance ---
let _searchIndex = null;

function _buildSearchIndex(companies) {
    if (!window.MiniSearch) return;
    _searchIndex = new MiniSearch({
        fields: ['name', 'what', 'target', 'geography', 'category_name'],
        storeFields: ['id', 'name'],
        searchOptions: { fuzzy: 0.2, prefix: true },
        idField: 'id',
    });
    // MiniSearch requires unique IDs; filter duplicates just in case
    const seen = new Set();
    const unique = companies.filter(c => {
        if (!c.id || seen.has(c.id)) return false;
        seen.add(c.id);
        return true;
    });
    _searchIndex.addAll(unique);
}

function _searchCompanies(query) {
    if (!_searchIndex || !query || !query.trim()) return null; // null = show all
    return new Set(_searchIndex.search(query).map(r => r.id));
}

// --- Tabulator column definitions ---
function _getTabulatorColumns() {
    return [
        {
            title: '<input type="checkbox" id="tabulatorSelectAll" title="Select all">',
            field: '_select',
            width: 40,
            hozAlign: 'center',
            headerSort: false,
            headerHozAlign: 'center',
            cssClass: 'tabulator-bulk-cell',
            formatter: function(cell) {
                const id = cell.getRow().getData().id;
                const checked = bulkSelection.has(id) ? 'checked' : '';
                return `<input type="checkbox" class="bulk-checkbox" data-company-id="${id}" ${checked}>`;
            },
            cellClick: function(e, cell) {
                e.stopPropagation();
                const cb = cell.getElement().querySelector('.bulk-checkbox');
                if (!cb) return;
                const id = cell.getRow().getData().id;
                if (cb.checked) bulkSelection.delete(id); else bulkSelection.add(id);
                cb.checked = !cb.checked;
                updateBulkBar();
            },
        },
        {
            title: '',
            field: 'is_starred',
            width: 44,
            hozAlign: 'center',
            headerSort: true,
            sorter: function(a, b) { return (a ? 1 : 0) - (b ? 1 : 0); },
            formatter: function(cell) {
                const starred = cell.getValue();
                return `<span class="star-btn ${starred ? 'starred' : ''}" title="Star"><span class="material-symbols-outlined">${starred ? 'star' : 'star_outline'}</span></span>`;
            },
            cellClick: function(e, cell) {
                e.stopPropagation();
                const id = cell.getRow().getData().id;
                const el = cell.getElement().querySelector('.star-btn');
                if (el) toggleStar(id, el);
            },
        },
        {
            title: 'Name',
            field: 'name',
            minWidth: 180,
            sorter: 'string',
            headerFilter: 'input',
            headerFilterPlaceholder: 'Filter name...',
            formatter: function(cell) {
                const c = cell.getRow().getData();
                const logoUrl = c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`;
                const compClass = c.completeness >= 0.7 ? 'comp-high' : c.completeness >= 0.4 ? 'comp-mid' : 'comp-low';
                const compPct = Math.round((c.completeness || 0) * 100);
                const relDot = c.relationship_status ? `<span class="relationship-dot rel-${c.relationship_status}" title="${relationshipLabel(c.relationship_status)}"></span>` : '';
                return `<div class="company-name-cell">
                    <img class="company-logo" src="${esc(logoUrl)}" alt="${escAttr(c.name)} logo" onerror="this.style.display='none'">
                    <strong>${esc(c.name)}</strong>
                    <span class="completeness-dot ${compClass}" title="${compPct}% complete"></span>
                    ${relDot}
                </div>`;
            },
        },
        {
            title: 'Category',
            field: 'category_name',
            minWidth: 120,
            sorter: 'string',
            headerFilter: 'input',
            headerFilterPlaceholder: 'Filter...',
            formatter: function(cell) {
                const c = cell.getRow().getData();
                if (!c.category_id) return 'N/A';
                return `<a class="cat-link" data-action="navigate-category" data-id="${c.category_id}" data-name="${escAttr(c.category_name)}">${esc(c.category_name || '')}</a>`;
            },
        },
        {
            title: 'What',
            field: 'what',
            minWidth: 200,
            sorter: 'string',
            headerFilter: 'input',
            headerFilterPlaceholder: 'Filter...',
            formatter: function(cell) {
                const val = cell.getValue() || '';
                return `<div class="cell-clamp">${esc(val)}</div>`;
            },
        },
        {
            title: 'Target',
            field: 'target',
            minWidth: 140,
            sorter: 'string',
            formatter: function(cell) {
                const val = cell.getValue() || '';
                return `<div class="cell-clamp">${esc(val)}</div>`;
            },
        },
        {
            title: 'Geo',
            field: 'geography',
            minWidth: 100,
            sorter: 'string',
            headerFilter: 'input',
            headerFilterPlaceholder: 'Filter...',
            formatter: function(cell) {
                return `<div class="cell-clamp">${esc(cell.getValue() || '')}</div>`;
            },
        },
        {
            title: 'Funding',
            field: 'funding_stage',
            minWidth: 90,
            sorter: 'string',
            headerFilter: 'list',
            headerFilterParams: { valuesLookup: true, clearable: true },
            headerFilterPlaceholder: 'All',
        },
        {
            title: 'Employees',
            field: 'employee_range',
            minWidth: 90,
            sorter: 'string',
            headerFilter: 'list',
            headerFilterParams: { valuesLookup: true, clearable: true },
            headerFilterPlaceholder: 'All',
        },
        {
            title: 'Model',
            field: 'business_model',
            minWidth: 90,
            sorter: 'string',
            headerFilter: 'list',
            headerFilterParams: { valuesLookup: true, clearable: true },
            headerFilterPlaceholder: 'All',
        },
        {
            title: 'Sources',
            field: 'source_count',
            width: 70,
            hozAlign: 'center',
            sorter: 'number',
            formatter: function(cell) {
                return `<span class="source-count">${cell.getValue() || 0}</span>`;
            },
        },
        {
            title: 'Tags',
            field: 'tags',
            minWidth: 140,
            sorter: function(a, b) {
                return (a || []).join(',').localeCompare((b || []).join(','));
            },
            formatter: function(cell) {
                const tags = cell.getValue() || [];
                return tags.map(t => `<span class="tag tabulator-tag">${esc(t)}</span>`).join(' ');
            },
        },
        {
            title: 'Conf.',
            field: 'confidence_score',
            width: 80,
            hozAlign: 'center',
            sorter: 'number',
            formatter: function(cell) {
                const val = cell.getValue();
                if (val == null) return '-';
                const pct = Math.round(val * 100);
                return `<div class="tabulator-confidence-bar"><div class="tabulator-confidence-fill" style="width:${pct}%"></div><span>${pct}%</span></div>`;
            },
        },
    ];
}

function _initTabulator(companies) {
    if (!window.Tabulator) return;

    const container = document.getElementById('companiesGridContainer');
    if (!container) return;

    // Destroy previous instance
    if (_tabulatorTable) {
        try { _tabulatorTable.destroy(); } catch(e) { /* ignore */ }
        _tabulatorTable = null;
    }

    _tabulatorTable = new Tabulator(container, {
        data: companies,
        layout: 'fitColumns',
        responsiveLayout: false,
        pagination: false,
        height: 'calc(100vh - 300px)',
        placeholder: _getEmptyStateHtml(),
        movableColumns: true,
        resizableColumns: true,
        columns: _getTabulatorColumns(),
        rowClick: function(e, row) {
            // Don't trigger on checkbox or star clicks
            const target = e.target;
            if (target.closest('.bulk-checkbox') || target.closest('.star-btn') || target.tagName === 'INPUT') return;
            showDetail(row.getData().id);
        },
        dataLoaded: function() {
            _attachTabulatorSelectAll();
        },
        renderComplete: function() {
            _attachTabulatorSelectAll();
        },
    });

    return _tabulatorTable;
}

function _attachTabulatorSelectAll() {
    const selectAllCb = document.getElementById('tabulatorSelectAll');
    if (selectAllCb && !selectAllCb._bound) {
        selectAllCb._bound = true;
        selectAllCb.addEventListener('change', function() {
            const checked = this.checked;
            if (_tabulatorTable) {
                _tabulatorTable.getRows().forEach(row => {
                    const id = row.getData().id;
                    if (checked) bulkSelection.add(id); else bulkSelection.delete(id);
                });
                _tabulatorTable.getRows().forEach(row => {
                    const cb = row.getElement().querySelector('.bulk-checkbox');
                    if (cb) cb.checked = checked;
                });
            }
            updateBulkBar();
        });
    }
}

function _getEmptyStateHtml() {
    const searchVal = document.getElementById('searchInput')?.value || '';
    const hasFilters = searchVal || activeFilters.category_id || activeFilters.tags.length
        || activeFilters.geography || activeFilters.funding_stage;
    return `<div class="empty-state">
        <div class="empty-state-content">
            <span class="empty-state-icon"><span class="material-symbols-outlined">search</span></span>
            <p class="empty-state-title">${hasFilters ? 'No companies match your filters' : 'No companies yet'}</p>
            <p class="empty-state-desc">${hasFilters
                ? 'Try adjusting your search or clearing all filters'
                : 'Go to the Process tab to add companies'}</p>
        </div>
    </div>`;
}

function _updateTabulatorData(companies) {
    if (!_tabulatorTable) return;
    _tabulatorTable.replaceData(companies);
}

function exportTabulatorCsv() {
    if (_tabulatorTable && currentCompanyView === 'grid') {
        _tabulatorTable.download('csv', 'companies.csv');
        showToast('CSV exported');
    } else if (_lastCompanies.length) {
        // Fallback: manual CSV export from _lastCompanies
        const headers = ['Name', 'Category', 'What', 'Target', 'Geography', 'Funding Stage', 'Employees', 'Business Model', 'Confidence', 'URL'];
        const rows = _lastCompanies.map(c => [
            c.name || '', c.category_name || '', (c.what || '').replace(/"/g, '""'),
            (c.target || '').replace(/"/g, '""'), c.geography || '', c.funding_stage || '',
            c.employee_range || '', c.business_model || '',
            c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : '',
            c.url || '',
        ]);
        const csv = [headers.join(','), ...rows.map(r => r.map(v => `"${v}"`).join(','))].join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'companies.csv'; a.click();
        URL.revokeObjectURL(url);
        showToast('CSV exported');
    }
}

function _renderPricingSection(c) {
    const hasPricing = c.pricing_model || c.revenue_model || c.pricing_b2c_low || c.pricing_b2b_low;
    if (!hasPricing) return '';

    const modelLabel = c.pricing_model ? c.pricing_model.replace(/_/g, ' ') : 'N/A';
    let priceRange = '';
    if (c.pricing_b2c_low != null || c.pricing_b2c_high != null) {
        const lo = c.pricing_b2c_low != null ? '$' + c.pricing_b2c_low : '';
        const hi = c.pricing_b2c_high != null ? '$' + c.pricing_b2c_high : '';
        priceRange += `B2C: ${lo}${lo && hi ? ' – ' : ''}${hi}/mo`;
    }
    if (c.pricing_b2b_low != null || c.pricing_b2b_high != null) {
        const lo = c.pricing_b2b_low != null ? '$' + c.pricing_b2b_low : '';
        const hi = c.pricing_b2b_high != null ? '$' + c.pricing_b2b_high : '';
        if (priceRange) priceRange += ' | ';
        priceRange += `B2B: ${lo}${lo && hi ? ' – ' : ''}${hi}/seat/mo`;
    }

    let tiersHtml = '';
    if (c.pricing_tiers) {
        let tiers = c.pricing_tiers;
        if (typeof tiers === 'string') { try { tiers = JSON.parse(tiers); } catch { tiers = null; } }
        if (Array.isArray(tiers) && tiers.length) {
            tiersHtml = `<div class="pricing-tiers"><table class="pricing-tiers-table">
                <tr>${tiers.map(t => `<th>${esc(t.name)}</th>`).join('')}</tr>
                <tr>${tiers.map(t => `<td class="pricing-tier-price">$${t.price || '?'}/mo</td>`).join('')}</tr>
                <tr>${tiers.map(t => `<td class="pricing-tier-features">${(t.features || []).map(f => esc(f)).join('<br>')}</td>`).join('')}</tr>
            </table></div>`;
        }
    }

    return `<div class="detail-pricing">
        <label class="detail-section-label">Pricing</label>
        <div class="detail-firmographics">
            <div class="detail-field"><label>Model</label><p><span class="pricing-badge">${esc(modelLabel)}</span>${c.has_free_tier ? ' <span class="pricing-free-badge">Free tier</span>' : ''}</p></div>
            <div class="detail-field"><label>Revenue</label><p>${esc(c.revenue_model || 'N/A')}</p></div>
            ${priceRange ? `<div class="detail-field"><label>Price Range</label><p>${priceRange}</p></div>` : ''}
        </div>
        ${tiersHtml}
        ${c.pricing_notes ? `<div class="detail-field"><label>Notes</label><p>${esc(c.pricing_notes)}</p></div>` : ''}
    </div>`;
}

// --- Bulk Selection ---
let bulkSelection = new Set();
let _lastCheckedIdx = null;

function toggleBulkSelect(companyId, checkbox, event) {
    event.stopPropagation();
    const rows = Array.from(document.querySelectorAll('#companyBody tr[data-company-id]'));
    const currentIdx = rows.findIndex(r => r.dataset.companyId == companyId);

    if (event.shiftKey && _lastCheckedIdx !== null && currentIdx !== _lastCheckedIdx) {
        const start = Math.min(_lastCheckedIdx, currentIdx);
        const end = Math.max(_lastCheckedIdx, currentIdx);
        const shouldCheck = checkbox.checked;
        for (let i = start; i <= end; i++) {
            const id = parseInt(rows[i].dataset.companyId);
            const cb = rows[i].querySelector('.bulk-checkbox');
            if (cb) cb.checked = shouldCheck;
            if (shouldCheck) bulkSelection.add(id); else bulkSelection.delete(id);
        }
    } else {
        if (checkbox.checked) bulkSelection.add(companyId); else bulkSelection.delete(companyId);
    }
    _lastCheckedIdx = currentIdx;
    updateBulkBar();
}

function toggleSelectAll(masterCheckbox) {
    const checkboxes = document.querySelectorAll('.bulk-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = masterCheckbox.checked;
        const id = parseInt(cb.dataset.companyId);
        if (masterCheckbox.checked) bulkSelection.add(id); else bulkSelection.delete(id);
    });
    updateBulkBar();
}

function clearBulkSelection() {
    bulkSelection.clear();
    _lastCheckedIdx = null;
    document.querySelectorAll('.bulk-checkbox').forEach(cb => cb.checked = false);
    const master = document.getElementById('selectAllCheckbox');
    if (master) master.checked = false;
    const tabulatorMaster = document.getElementById('tabulatorSelectAll');
    if (tabulatorMaster) tabulatorMaster.checked = false;
    updateBulkBar();
}

function updateBulkBar() {
    const bar = document.getElementById('bulkActionBar');
    if (!bar) return;
    if (bulkSelection.size > 0) {
        bar.classList.remove('hidden');
        document.getElementById('bulkCount').textContent = `${bulkSelection.size} selected`;
    } else {
        bar.classList.add('hidden');
    }
}

async function bulkAction(action) {
    if (!bulkSelection.size) return;
    const ids = Array.from(bulkSelection);
    let params = {};

    if (action === 'assign_category') {
        const catId = await new Promise(resolve => {
            window.showPromptDialog('Assign Category', 'Enter category ID...', resolve, 'Assign');
        });
        if (!catId) return;
        params.category_id = parseInt(catId);
    } else if (action === 'add_tags') {
        const tags = await new Promise(resolve => {
            window.showPromptDialog('Add Tags', 'Enter tags (comma-separated)...', resolve, 'Add');
        });
        if (!tags) return;
        params.tags = tags.split(',').map(t => t.trim()).filter(Boolean);
    } else if (action === 'set_relationship') {
        const status = await new Promise(resolve => {
            window.showSelectDialog('Set Relationship Status', [
                'watching', 'to_reach_out', 'in_conversation', 'met', 'partner', 'not_relevant'
            ], resolve, 'Set');
        });
        if (!status) return;
        params.status = status;
    } else if (action === 'delete') {
        const confirmed = await _confirm({
            title: `Delete ${ids.length} Companies?`,
            message: `This will remove ${ids.length} companies from your project. This can be undone.`,
            confirmText: `Delete ${ids.length}`,
            type: 'danger'
        });
        if (!confirmed) return;
    }

    const res = await safeFetch('/api/companies/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, company_ids: ids, params }),
    });
    const data = await res.json();

    if (action === 'delete') {
        showUndoToast(`Deleted ${data.updated} companies`, async () => {
            for (const id of ids) {
                await safeFetch(`/api/companies/${id}/restore`, { method: 'POST' });
            }
            loadCompanies();
            loadStats();
        });
    } else {
        showToast(`Updated ${data.updated} companies`);
    }

    clearBulkSelection();
    loadCompanies();
    loadStats();
}

function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(loadCompanies, 300);
}

async function loadCompanies() {
    const search = document.getElementById('searchInput').value;
    const starred = document.getElementById('starredFilter').checked;
    const needsEnrichment = document.getElementById('enrichmentFilter').checked;

    // When using MiniSearch for fuzzy search, still send the query to the backend
    // but also apply client-side fuzzy filtering
    let url = `/api/companies?project_id=${currentProjectId}&`;
    if (search && !window.MiniSearch) url += `search=${encodeURIComponent(search)}&`;
    if (activeFilters.category_id) url += `category_id=${activeFilters.category_id}&`;
    if (starred) url += `starred=1&`;
    if (needsEnrichment) url += `needs_enrichment=1&`;
    if (activeFilters.tags.length) url += `tags=${encodeURIComponent(activeFilters.tags.join(','))}&`;
    if (activeFilters.geography) url += `geography=${encodeURIComponent(activeFilters.geography)}&`;
    if (activeFilters.funding_stage) url += `funding_stage=${encodeURIComponent(activeFilters.funding_stage)}&`;
    if (activeFilters.founded_from) url += `founded_from=${activeFilters.founded_from}&`;
    if (activeFilters.founded_to) url += `founded_to=${activeFilters.founded_to}&`;
    const relFilter = document.getElementById('relationshipFilter').value;
    if (relFilter) url += `relationship_status=${encodeURIComponent(relFilter)}&`;
    url += `sort_by=${currentSort.by}&sort_dir=${currentSort.dir}&`;

    const res = await safeFetch(url);
    let companies = await res.json();
    // Client-side founded year range filter (in case backend doesn't support it)
    if (activeFilters.founded_from && activeFilters.founded_to) {
        companies = companies.filter(c => {
            if (!c.founded_year) return false;
            const y = parseInt(c.founded_year);
            return y >= activeFilters.founded_from && y <= activeFilters.founded_to;
        });
    }

    // Build MiniSearch index and apply fuzzy filtering if search term exists
    _buildSearchIndex(companies);
    if (search && window.MiniSearch) {
        const matchIds = _searchCompanies(search);
        if (matchIds) {
            companies = companies.filter(c => matchIds.has(c.id));
        }
    }

    _lastCompanies = companies;

    // If in grid view (Tabulator), update that
    if (currentCompanyView === 'grid') {
        if (_tabulatorTable) {
            _updateTabulatorData(companies);
        } else {
            _initTabulator(companies);
        }
        return;
    }

    // If not in table view, render the alternate view
    if (currentCompanyView !== 'table') {
        renderAlternateView(companies);
        return;
    }

    document.querySelectorAll('.sort-header').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === currentSort.by) {
            th.classList.add(currentSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });

    const tbody = document.getElementById('companyBody');
    if (!companies.length) {
        const search = document.getElementById('searchInput').value;
        const hasFilters = search || activeFilters.category_id || activeFilters.tags.length
            || activeFilters.geography || activeFilters.funding_stage;
        tbody.innerHTML = `<tr><td colspan="10" class="empty-state">
            <div class="empty-state-content">
                <span class="empty-state-icon"><span class="material-symbols-outlined">search</span></span>
                <p class="empty-state-title">${hasFilters ? 'No companies match your filters' : 'No companies yet'}</p>
                <p class="empty-state-desc">${hasFilters
                    ? 'Try adjusting your search or <button class="empty-state-link" data-action="clear-all-filters">clearing all filters</button>'
                    : 'Go to the <button class="empty-state-link" data-action="show-tab" data-tab="process">Process tab</button> to add companies'}</p>
            </div>
        </td></tr>`;
    } else {
        tbody.innerHTML = companies.map(c => {
            const compClass = c.completeness >= 0.7 ? 'comp-high' : c.completeness >= 0.4 ? 'comp-mid' : 'comp-low';
            const compPct = Math.round(c.completeness * 100);
            return `
            <tr data-action="show-detail" data-id="${c.id}" style="cursor:pointer" data-company-id="${c.id}">
                <td class="bulk-cell"><input type="checkbox" class="bulk-checkbox" data-company-id="${c.id}" ${bulkSelection.has(c.id) ? 'checked' : ''} data-on-change="toggle-bulk-select" data-id="${c.id}"></td>
                <td><span class="star-btn ${c.is_starred ? 'starred' : ''}" data-action="toggle-star" data-id="${c.id}" title="Star"><span class="material-symbols-outlined">${c.is_starred ? 'star' : 'star_outline'}</span></span></td>
                <td>
                    <div class="company-name-cell">
                        <img class="company-logo" src="${esc(c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`)}" alt="${escAttr(c.name)} logo" onerror="this.style.display='none'">
                        <strong>${esc(c.name)}</strong>
                        <span class="completeness-dot ${compClass}" title="${compPct}% complete"></span>
                        ${c.relationship_status ? `<span class="relationship-dot rel-${c.relationship_status}" title="${relationshipLabel(c.relationship_status)}"></span>` : ''}
                    </div>
                </td>
                <td>${c.category_id ? `<a class="cat-link" data-action="navigate-category" data-id="${c.category_id}" data-name="${escAttr(c.category_name)}"><span class="cat-color-dot" style="background:${getCategoryColor(c.category_id) || 'transparent'}"></span> ${esc(c.category_name)}</a>` : 'N/A'}</td>
                <td><div class="cell-clamp">${esc(c.what || '')}</div></td>
                <td><div class="cell-clamp">${esc(c.target || '')}</div></td>
                <td><div class="cell-clamp">${esc(c.geography || '')}</div></td>
                <td><span class="source-count">${c.source_count || 0} links</span></td>
                <td>${(c.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(' ')}</td>
                <td>${c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : '-'}</td>
            </tr>`;
        }).join('');
    }
}

async function toggleStar(id, el) {
    const res = await safeFetch(`/api/companies/${id}/star`, { method: 'POST' });
    const data = await res.json();
    el.innerHTML = `<span class="material-symbols-outlined">${data.is_starred ? 'star' : 'star_outline'}</span>`;
    el.classList.toggle('starred', !!data.is_starred);
}

async function saveRelationship(id) {
    const status = document.getElementById(`relStatus-${id}`).value;
    const note = document.getElementById(`relNote-${id}`).value;
    await safeFetch(`/api/companies/${id}/relationship`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ status: status || null, note })
    });
    loadCompanies();
}

async function showDetail(id) {
    const res = await safeFetch(`/api/companies/${id}`);
    const c = await res.json();

    let sourcesHtml = '';
    if (c.sources && c.sources.length) {
        sourcesHtml = `<div class="detail-field">
            <label>Sources (${c.sources.length})</label>
            <div class="sources-list">
                ${c.sources.map(s => `
                    <div class="source-item">
                        <span class="source-type-badge source-type-${s.source_type}">${esc(s.source_type)}</span>
                        <a href="${safeHref(s.url)}" target="_blank">${esc(s.url)}</a>
                        <span class="source-date">${new Date(s.added_at).toLocaleDateString()}</span>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }

    const logoUrl = c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`;
    const fundingAmt = c.total_funding_usd ? (typeof formatCurrency === 'function' ? formatCurrency(c.total_funding_usd) : '$' + Number(c.total_funding_usd).toLocaleString()) : null;

    document.getElementById('detailName').textContent = c.name;
    document.getElementById('detailContent').innerHTML = `
        <div class="detail-logo-row">
            <img class="detail-logo" src="${esc(logoUrl)}" alt="${escAttr(c.name)} logo" onerror="this.style.display='none'">
            <a href="${safeHref(c.url)}" target="_blank">${esc(c.url)}</a>
            ${c.linkedin_url ? `<a href="${safeHref(c.linkedin_url)}" target="_blank" class="linkedin-link" title="LinkedIn">in</a>` : ''}
            ${c.url && typeof generateQrCode === 'function' ? `<button class="btn" style="padding:2px 6px;font-size:11px" data-action="show-qr" data-url="${escAttr(c.url)}" data-name="${escAttr(c.name)}" title="Show QR code">QR</button>` : ''}
        </div>
        <div class="detail-field"><label>What</label><p>${esc(c.what || 'N/A')}</p></div>
        <div class="detail-field"><label>Target</label><p>${esc(c.target || 'N/A')}</p></div>
        <div class="detail-field"><label>Products</label><p>${esc(c.products || 'N/A')}</p></div>
        <div class="detail-firmographics">
            <div class="detail-field"><label>Funding</label><p>${esc(c.funding || 'N/A')}</p></div>
            <div class="detail-field"><label>Stage</label><p>${esc(c.funding_stage || 'N/A')}</p></div>
            <div class="detail-field"><label>Total Raised</label><p>${fundingAmt || 'N/A'}</p></div>
            <div class="detail-field"><label>Founded</label><p>${c.founded_year || 'N/A'}</p></div>
            <div class="detail-field"><label>Employees</label><p>${esc(c.employee_range || 'N/A')}</p></div>
            <div class="detail-field"><label>HQ</label><p>${esc(c.hq_city || '')}${c.hq_city && c.hq_country ? ', ' : ''}${esc(c.hq_country || 'N/A')}</p></div>
        </div>
        ${_renderPricingSection(c)}
        <div class="detail-field"><label>Geography</label><p>${esc(c.geography || 'N/A')}</p></div>
        <div class="detail-field"><label>TAM</label><p>${esc(c.tam || 'N/A')}</p></div>
        <div class="detail-field"><label>Category</label><p>${c.category_id ? `<a class="cat-link" data-action="navigate-category" data-id="${c.category_id}" data-name="${escAttr(c.category_name)}">${esc(c.category_name)}</a>` : 'N/A'} / ${esc(c.subcategory_name || 'N/A')}</p></div>
        <div class="detail-field"><label>Tags</label><p>${(c.tags || []).map(t => esc(t)).join(', ') || 'None'}</p></div>
        <div class="detail-field"><label>Confidence</label><p>${c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : 'N/A'}</p></div>
        <div class="detail-field"><label>Processed</label><p>${c.processed_at || 'N/A'}</p></div>
        ${sourcesHtml}
        ${c.status && c.status !== 'active' ? `<div class="lifecycle-badge lifecycle-${c.status}">${esc(c.status)}</div>` : ''}
        ${c.business_model || c.company_stage || c.primary_focus ? `
        <div class="detail-facets">
            ${c.business_model ? `<span class="facet-badge facet-model">${esc(c.business_model)}</span>` : ''}
            ${c.company_stage ? `<span class="facet-badge facet-stage">${esc(c.company_stage)}</span>` : ''}
            ${c.primary_focus ? `<span class="facet-badge facet-focus">${esc(c.primary_focus)}</span>` : ''}
        </div>` : ''}
        <div class="detail-actions">
            <button class="btn" data-action="open-edit-modal" data-id="${c.id}">Edit</button>
            <button class="btn" data-action="open-re-research" data-id="${c.id}">Re-research</button>
            <button class="btn" data-action="start-enrichment" data-id="${c.id}">Enrich</button>
            <button class="btn" data-action="start-company-research" data-id="${c.id}" data-name="${escAttr(c.name)}">Deep Dive</button>
            <button class="btn" data-action="find-similar" data-id="${c.id}">Find Similar</button>
            <button class="btn" data-action="show-version-history" data-id="${c.id}">History</button>
            <button class="danger-btn" data-action="delete-company" data-id="${c.id}">Delete</button>
        </div>
        <div id="similarResults-${c.id}" class="hidden similar-results"></div>

        <!-- Relationship Section -->
        <div class="relationship-section">
            <label>Relationship</label>
            <div class="relationship-controls">
                <select id="relStatus-${c.id}" class="relationship-select" data-on-change="save-relationship" data-id="${c.id}">
                    <option value="">-- None --</option>
                    <option value="watching" ${c.relationship_status === 'watching' ? 'selected' : ''}>Watching</option>
                    <option value="to_reach_out" ${c.relationship_status === 'to_reach_out' ? 'selected' : ''}>To Reach Out</option>
                    <option value="in_conversation" ${c.relationship_status === 'in_conversation' ? 'selected' : ''}>In Conversation</option>
                    <option value="met" ${c.relationship_status === 'met' ? 'selected' : ''}>Met</option>
                    <option value="partner" ${c.relationship_status === 'partner' ? 'selected' : ''}>Partner</option>
                    <option value="not_relevant" ${c.relationship_status === 'not_relevant' ? 'selected' : ''}>Not Relevant</option>
                </select>
                ${c.relationship_status ? `<span class="relationship-dot rel-${c.relationship_status}" style="width:10px;height:10px"></span>` : ''}
            </div>
            <textarea id="relNote-${c.id}" class="relationship-note" rows="2" placeholder="Notes about this relationship..."
                data-on-blur="save-relationship" data-id="${c.id}">${esc(c.relationship_note || '')}</textarea>
        </div>

        <!-- Notes Section -->
        <div class="detail-notes">
            <div class="detail-notes-header">
                <label>Notes</label>
                <button class="filter-action-btn" data-action="show-add-note" data-id="${c.id}">+ Add note</button>
            </div>
            <div id="addNoteForm-${c.id}" class="hidden" style="margin-bottom:8px">
                <textarea id="newNoteText-${c.id}" rows="2" placeholder="Add a note..."></textarea>
                <div style="display:flex;gap:6px;margin-top:4px">
                    <button class="primary-btn" data-action="add-note" data-id="${c.id}">Save</button>
                    <button class="btn" data-action="cancel-add-note" data-id="${c.id}">Cancel</button>
                </div>
            </div>
            <div id="notesList-${c.id}">
                ${(c.notes || []).map(n => `
                    <div class="note-item ${n.is_pinned ? 'note-pinned' : ''}">
                        <div class="note-content">${esc(n.content)}</div>
                        <div class="note-meta">
                            <span>${new Date(n.created_at).toLocaleDateString()}</span>
                            <span class="note-action" data-action="toggle-pin-note" data-id="${n.id}" data-company-id="${c.id}">${n.is_pinned ? 'Unpin' : 'Pin'}</span>
                            <span class="note-action note-delete" data-action="delete-note" data-id="${n.id}" data-company-id="${c.id}">Delete</span>
                        </div>
                    </div>
                `).join('') || '<p style="font-size:12px;color:var(--text-muted)">No notes yet.</p>'}
            </div>
        </div>

        <!-- Events Section -->
        <div class="detail-events">
            <div class="detail-notes-header">
                <label>Events</label>
                <button class="filter-action-btn" data-action="show-add-event" data-id="${c.id}">+ Add event</button>
            </div>
            <div id="addEventForm-${c.id}" class="hidden" style="margin-bottom:8px">
                <div style="display:flex;gap:6px;flex-wrap:wrap">
                    <select id="newEventType-${c.id}">
                        <option value="funding_round">Funding Round</option>
                        <option value="acquired">Acquired</option>
                        <option value="shut_down">Shut Down</option>
                        <option value="launched">Product Launch</option>
                        <option value="pivot">Pivot</option>
                        <option value="partnership">Partnership</option>
                    </select>
                    <input type="date" id="newEventDate-${c.id}">
                </div>
                <textarea id="newEventDesc-${c.id}" rows="1" placeholder="Description..." style="margin-top:4px"></textarea>
                <div style="display:flex;gap:6px;margin-top:4px">
                    <button class="primary-btn" data-action="add-event" data-id="${c.id}">Save</button>
                    <button class="btn" data-action="cancel-add-event" data-id="${c.id}">Cancel</button>
                </div>
            </div>
            <div id="eventsList-${c.id}">
                ${(c.events || []).map(ev => `
                    <div class="event-item">
                        <span class="event-type-badge">${esc(ev.event_type)}</span>
                        <span>${esc(ev.description || '')}</span>
                        <span class="event-date">${ev.event_date || ''}</span>
                        <span class="note-action note-delete" data-action="delete-event" data-id="${ev.id}" data-company-id="${c.id}">Delete</span>
                    </div>
                `).join('') || '<p style="font-size:12px;color:var(--text-muted)">No events yet.</p>'}
            </div>
        </div>

        <div id="reResearchForm-${c.id}" class="re-research-form hidden">
            <label>Additional source URLs (one per line):</label>
            <textarea id="reResearchUrls-${c.id}" rows="3" placeholder="https://example.com/about&#10;https://crunchbase.com/organization/..."></textarea>
            <div class="re-research-actions">
                <button class="primary-btn" data-action="start-re-research" data-id="${c.id}">Run Re-research</button>
                <button class="btn" data-action="close-re-research" data-id="${c.id}">Cancel</button>
            </div>
            <div id="reResearchStatus-${c.id}" class="hidden"></div>
        </div>
    `;
    document.getElementById('detailPanel').classList.remove('hidden');
}

function closeDetail() {
    document.getElementById('detailPanel').classList.add('hidden');
}

async function deleteCompany(id) {
    // Get company name for the confirmation dialog
    const companyName = document.getElementById('detailName')?.textContent || 'this company';
    const confirmed = await _confirm({
        title: 'Delete Company?',
        message: `This will remove "${companyName}" from your project.`,
        confirmText: 'Delete',
        type: 'danger'
    });
    if (!confirmed) return;
    await safeFetch(`/api/companies/${id}`, { method: 'DELETE' });
    closeDetail();
    loadCompanies();
    loadStats();

    // Push undo action if available
    if (typeof pushUndoAction === 'function') {
        pushUndoAction(
            `Delete ${companyName}`,
            async () => {
                // Undo: restore the company
                await safeFetch(`/api/companies/${id}/restore`, { method: 'POST' });
                loadCompanies();
                loadStats();
            },
            async () => {
                // Redo: delete again
                await safeFetch(`/api/companies/${id}`, { method: 'DELETE' });
                loadCompanies();
                loadStats();
            }
        );
    }
}

// --- Copy company data to clipboard ---
window.copyCompanyData = async function(companyId, format = 'text') {
    try {
        const resp = await safeFetch(`/api/companies/${companyId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const company = data.company || data;

        let text;
        if (format === 'json') {
            text = JSON.stringify(company, null, 2);
        } else if (format === 'url') {
            text = company.url || '';
        } else {
            // Plain text summary
            const lines = [company.name];
            if (company.url) lines.push(company.url);
            if (company.description) lines.push(company.description);
            if (company.what) lines.push(company.what);
            if (company.category_name) lines.push(`Category: ${company.category_name}`);
            if (company.funding_stage) lines.push(`Funding: ${company.funding_stage}`);
            if (company.geography) lines.push(`Geography: ${company.geography}`);
            text = lines.join('\n');
        }

        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard', 'success');
    } catch (e) {
        console.error('Copy failed:', e);
        showToast('Failed to copy', 'error');
    }
};

// --- Re-Research ---
function openReResearch(id) {
    document.getElementById(`reResearchForm-${id}`).classList.remove('hidden');
}

function closeReResearch(id) {
    document.getElementById(`reResearchForm-${id}`).classList.add('hidden');
}

async function startReResearch(companyId) {
    const urlsText = document.getElementById(`reResearchUrls-${companyId}`).value;
    const urls = urlsText.split('\n').map(u => u.trim()).filter(Boolean);
    if (!urls.length) { showToast('Enter at least one URL'); return; }

    const statusDiv = document.getElementById(`reResearchStatus-${companyId}`);
    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = '<div class="progress-bar"><div class="progress-fill" style="width:30%;animation:pulse 2s infinite"></div></div><p>Re-researching with additional sources...</p>';

    const res = await safeFetch(`/api/companies/${companyId}/re-research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls, model: document.getElementById('modelSelect').value }),
    });
    const data = await res.json();
    pollReResearch(companyId, data.research_id);
}

let _reResearchPollCount = 0;
const _MAX_RERESEARCH_RETRIES = 60;

async function pollReResearch(companyId, researchId) {
    const res = await safeFetch(`/api/re-research/${researchId}`);
    const data = await res.json();

    if (data.status === 'pending') {
        if (++_reResearchPollCount > _MAX_RERESEARCH_RETRIES) {
            data.status = 'error';
            data.error = 'Re-research timed out. Please try again.';
        } else {
            setTimeout(() => pollReResearch(companyId, researchId), 3000);
            return;
        }
    }
    _reResearchPollCount = 0;

    const statusDiv = document.getElementById(`reResearchStatus-${companyId}`);
    if (data.status === 'error') {
        statusDiv.innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
    } else {
        statusDiv.innerHTML = '<p class="re-research-success">Research updated successfully!</p>';
        setTimeout(() => {
            showDetail(companyId);
            loadCompanies();
            loadStats();
        }, 1000);
    }
}

// --- Edit Modal ---
async function openEditModal(id) {
    const res = await safeFetch(`/api/companies/${id}`);
    const c = await res.json();

    const taxRes = await safeFetch(`/api/taxonomy?project_id=${currentProjectId}`);
    allCategories = await taxRes.json();

    const topLevel = allCategories.filter(c => !c.parent_id);
    const catSelect = document.getElementById('editCategory');
    catSelect.innerHTML = '<option value="">-- Select --</option>' +
        topLevel.map(cat => `<option value="${cat.id}">${esc(cat.name)}</option>`).join('');

    document.getElementById('editId').value = c.id;
    document.getElementById('editName').value = c.name || '';
    document.getElementById('editUrl').value = c.url || '';
    document.getElementById('editWhat').value = c.what || '';
    document.getElementById('editTarget').value = c.target || '';
    document.getElementById('editProducts').value = c.products || '';
    document.getElementById('editFunding').value = c.funding || '';
    document.getElementById('editGeography').value = c.geography || '';
    document.getElementById('editTam').value = c.tam || '';
    document.getElementById('editTags').value = (c.tags || []).join(', ');
    document.getElementById('editEmployeeRange').value = c.employee_range || '';
    document.getElementById('editFoundedYear').value = c.founded_year || '';
    document.getElementById('editFundingStage').value = c.funding_stage || '';
    document.getElementById('editTotalFunding').value = c.total_funding_usd || '';
    document.getElementById('editHqCity').value = c.hq_city || '';
    document.getElementById('editHqCountry').value = c.hq_country || '';
    document.getElementById('editLinkedin').value = c.linkedin_url || '';
    document.getElementById('editBusinessModel').value = c.business_model || '';
    document.getElementById('editCompanyStage').value = c.company_stage || '';
    document.getElementById('editPrimaryFocus').value = c.primary_focus || '';

    catSelect.value = c.category_id || '';
    loadSubcategories();
    document.getElementById('editSubcategory').value = c.subcategory_id || '';

    document.getElementById('editModal').classList.remove('hidden');
    window._editModalFocusTrap = trapFocus(document.getElementById('editModal'));
}

function loadSubcategories() {
    const parentId = parseInt(document.getElementById('editCategory').value);
    const subSelect = document.getElementById('editSubcategory');
    const subs = allCategories.filter(c => c.parent_id === parentId);
    subSelect.innerHTML = '<option value="">-- Select --</option>' +
        subs.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
}

function closeEditModal() {
    if (window._editModalFocusTrap) { window._editModalFocusTrap(); window._editModalFocusTrap = null; }
    document.getElementById('editModal').classList.add('hidden');
}

async function saveEdit(event) {
    event.preventDefault();
    const id = document.getElementById('editId').value;
    const tagsStr = document.getElementById('editTags').value;
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

    const prevRes = await safeFetch(`/api/companies/${id}`);
    const prevData = await prevRes.json();

    const fields = {
        name: document.getElementById('editName').value,
        url: document.getElementById('editUrl').value,
        what: document.getElementById('editWhat').value,
        target: document.getElementById('editTarget').value,
        products: document.getElementById('editProducts').value,
        funding: document.getElementById('editFunding').value,
        geography: document.getElementById('editGeography').value,
        tam: document.getElementById('editTam').value,
        category_id: document.getElementById('editCategory').value || null,
        subcategory_id: document.getElementById('editSubcategory').value || null,
        tags: tags,
        project_id: currentProjectId,
        employee_range: document.getElementById('editEmployeeRange').value || null,
        founded_year: document.getElementById('editFoundedYear').value ? parseInt(document.getElementById('editFoundedYear').value) : null,
        funding_stage: document.getElementById('editFundingStage').value || null,
        total_funding_usd: document.getElementById('editTotalFunding').value ? parseFloat(document.getElementById('editTotalFunding').value) : null,
        hq_city: document.getElementById('editHqCity').value || null,
        hq_country: document.getElementById('editHqCountry').value || null,
        linkedin_url: document.getElementById('editLinkedin').value || null,
        business_model: document.getElementById('editBusinessModel').value || null,
        company_stage: document.getElementById('editCompanyStage').value || null,
        primary_focus: document.getElementById('editPrimaryFocus').value || null,
    };

    await safeFetch(`/api/companies/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
    });

    closeEditModal();
    closeDetail();
    loadCompanies();
    loadStats();

    showUndoToast(`Updated ${fields.name}`, async () => {
        const undoFields = {
            name: prevData.name, url: prevData.url, what: prevData.what,
            target: prevData.target, products: prevData.products, funding: prevData.funding,
            geography: prevData.geography, tam: prevData.tam,
            category_id: prevData.category_id, subcategory_id: prevData.subcategory_id,
            tags: prevData.tags || [], project_id: currentProjectId,
            employee_range: prevData.employee_range, founded_year: prevData.founded_year,
            funding_stage: prevData.funding_stage, total_funding_usd: prevData.total_funding_usd,
            hq_city: prevData.hq_city, hq_country: prevData.hq_country,
            linkedin_url: prevData.linkedin_url,
            business_model: prevData.business_model, company_stage: prevData.company_stage,
            primary_focus: prevData.primary_focus,
        };
        await safeFetch(`/api/companies/${id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(undoFields),
        });
        loadCompanies();
        loadStats();
    });
}

// --- Notes ---
function showAddNote(companyId) {
    document.getElementById(`addNoteForm-${companyId}`).classList.remove('hidden');
}

async function addNote(companyId) {
    const content = document.getElementById(`newNoteText-${companyId}`).value.trim();
    if (!content) return;
    await safeFetch(`/api/companies/${companyId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
    });
    showDetail(companyId);
}

async function deleteNote(noteId, companyId) {
    await safeFetch(`/api/notes/${noteId}`, { method: 'DELETE' });
    showDetail(companyId);
}

async function togglePinNote(noteId, companyId) {
    await safeFetch(`/api/notes/${noteId}/pin`, { method: 'POST' });
    showDetail(companyId);
}

// --- Events ---
function showAddEvent(companyId) {
    document.getElementById(`addEventForm-${companyId}`).classList.remove('hidden');
}

async function addEvent(companyId) {
    const event_type = document.getElementById(`newEventType-${companyId}`).value;
    const description = document.getElementById(`newEventDesc-${companyId}`).value.trim();
    const event_date = document.getElementById(`newEventDate-${companyId}`).value || null;
    await safeFetch(`/api/companies/${companyId}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type, description, event_date }),
    });
    showDetail(companyId);
}

async function deleteEvent(eventId, companyId) {
    await safeFetch(`/api/events/${eventId}`, { method: 'DELETE' });
    showDetail(companyId);
}

// --- Version History ---
async function showVersionHistory(companyId) {
    const res = await safeFetch(`/api/companies/${companyId}/versions`);
    const versions = await res.json();

    let html = '<div class="version-history"><h3>Version History</h3>';
    if (!versions.length) {
        html += '<p style="font-size:13px;color:var(--text-muted)">No version history yet. Versions are created automatically when you edit a company.</p>';
    } else {
        html += versions.map((v, i) => `
            <div class="version-item">
                <div class="version-meta">
                    <span class="version-desc">${esc(v.change_description || 'Edit')}</span>
                    <span class="version-date">${new Date(v.created_at).toLocaleString()}</span>
                </div>
                <div style="display:flex;gap:4px">
                    ${i < versions.length - 1 ? `<button class="filter-action-btn" data-action="show-version-diff" data-company-id="${companyId}" data-new-version="${v.id}" data-old-version="${versions[i+1].id}">Diff</button>` : ''}
                    <button class="filter-action-btn" data-action="restore-version" data-id="${v.id}" data-company-id="${companyId}">Restore</button>
                </div>
            </div>
        `).join('');
    }
    html += `<button class="btn" data-action="show-detail" data-id="${companyId}" style="margin-top:10px">Back</button></div>`;
    document.getElementById('detailContent').innerHTML = html;
}

async function showVersionDiff(companyId, newVersionId, oldVersionId) {
    const [newRes, oldRes] = await Promise.all([
        safeFetch(`/api/versions/${newVersionId}`),
        safeFetch(`/api/versions/${oldVersionId}`),
    ]);
    const newV = await newRes.json();
    const oldV = await oldRes.json();
    const fields = ['name','what','target','products','geography','funding','funding_stage','total_funding_usd','employee_range','founded_year','hq_city','hq_country','tam','business_model'];

    if (window.Diff2Html) {
        // Build unified diff string
        let diffStr = '';
        fields.forEach(f => {
            const oldVal = String((oldV.data && oldV.data[f]) || '');
            const newVal = String((newV.data && newV.data[f]) || '');
            if (oldVal !== newVal) {
                diffStr += `--- a/${f}\n+++ b/${f}\n@@ -1 +1 @@\n-${oldVal}\n+${newVal}\n`;
            }
        });
        if (!diffStr) diffStr = '--- a/no-changes\n+++ b/no-changes\n@@ -0,0 +0,0 @@\n No differences found\n';
        const diffHtml = Diff2Html.html(diffStr, { drawFileList: false, outputFormat: 'side-by-side', matching: 'lines' });
        document.getElementById('detailContent').innerHTML = `
            <div class="version-history"><h3>Version Diff</h3>
            ${diffHtml}
            <button class="btn" data-action="show-version-history" data-id="${companyId}" style="margin-top:10px">Back to History</button></div>`;
    } else {
        // Fallback: simple text diff
        let html = '<div class="version-history"><h3>Version Diff</h3><table class="compare-table"><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>';
        fields.forEach(f => {
            const oldVal = (oldV.data && oldV.data[f]) || '';
            const newVal = (newV.data && newV.data[f]) || '';
            if (oldVal !== newVal) {
                html += `<tr><td><strong>${esc(f)}</strong></td><td style="color:var(--accent-danger)">${esc(String(oldVal))}</td><td style="color:var(--accent-green)">${esc(String(newVal))}</td></tr>`;
            }
        });
        html += `</tbody></table><button class="btn" data-action="show-version-history" data-id="${companyId}" style="margin-top:10px">Back to History</button></div>`;
        document.getElementById('detailContent').innerHTML = html;
    }
}

async function restoreVersion(versionId, companyId) {
    const confirmed = await _confirm({
        title: 'Restore Version?',
        message: 'Current state will be saved as a version first, then this version will be restored.',
        confirmText: 'Restore',
        cancelText: 'Cancel',
        type: 'warning'
    });
    if (!confirmed) return;
    await safeFetch(`/api/versions/${versionId}/restore`, { method: 'POST' });
    showDetail(companyId);
    loadCompanies();
}

function showCompanyQr(url, name) {
    const qrHtml = typeof generateQrCode === 'function' ? generateQrCode(url, 6) : null;
    if (!qrHtml) { showToast('QR code library not loaded'); return; }
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `<div class="modal" style="max-width:320px;text-align:center;padding:24px">
        <h3 style="margin:0 0 12px">${esc(name)}</h3>
        <div style="display:inline-block;padding:12px;background:#fff;border-radius:8px">${qrHtml}</div>
        <p style="margin:8px 0 0;font-size:12px;color:var(--text-muted)">${esc(url)}</p>
        <button class="btn" data-action="close-qr-modal" style="margin-top:12px">Close</button>
    </div>`;
    document.body.appendChild(modal);
}

// --- Escape to clear bulk selection ---
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && bulkSelection.size > 0) {
        clearBulkSelection();
    }
});

// --- Enrichment ---
async function startEnrichment(companyId) {
    showToast('Starting enrichment...');
    const res = await safeFetch(`/api/companies/${companyId}/enrich`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: document.getElementById('modelSelect')?.value || 'sonnet' }),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error); return; }
    pollEnrichment(data.job_id, companyId);
}

let _enrichPollCount = 0;
const _MAX_ENRICH_RETRIES = 120;

async function pollEnrichment(jobId, companyId) {
    const res = await safeFetch(`/api/enrich/${jobId}`);
    const data = await res.json();
    if (data.status === 'pending') {
        if (++_enrichPollCount > _MAX_ENRICH_RETRIES) {
            showToast('Enrichment timed out');
            return;
        }
        setTimeout(() => pollEnrichment(jobId, companyId), 3000);
        return;
    }
    _enrichPollCount = 0;
    if (data.status === 'error') {
        showToast('Enrichment failed: ' + (data.error || ''));
    } else {
        const fields = data.enriched_fields || [];
        showToast(`Enriched ${fields.length} fields (${data.steps_run} steps)`);
        if (companyId) showDetail(companyId);
        loadCompanies();
    }
}

async function startBatchEnrichment() {
    const ids = bulkSelection.size > 0 ? Array.from(bulkSelection) : null;
    showToast('Starting batch enrichment...');
    const res = await safeFetch('/api/companies/enrich-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            company_ids: ids,
            model: document.getElementById('modelSelect')?.value || 'sonnet',
        }),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error); return; }
    showToast(`Enriching ${data.count} companies...`);
    _enrichPollCount = 0;
    pollEnrichment(data.job_id, null);
}

// --- Company View Switching ---
function switchCompanyView(view) {
    currentCompanyView = view;
    const table = document.getElementById('companyTable');
    const container = document.getElementById('companyViewContainer');
    const gridContainer = document.getElementById('companiesGridContainer');
    document.querySelectorAll('.company-view-toggle .view-toggle-btn').forEach(b => b.classList.remove('active'));

    if (view === 'table') {
        table.classList.remove('hidden');
        container.classList.add('hidden');
        if (gridContainer) gridContainer.classList.add('hidden');
        document.getElementById('viewTableBtn').classList.add('active');
        loadCompanies();
    } else if (view === 'grid') {
        // Tabulator grid view
        table.classList.add('hidden');
        container.classList.add('hidden');
        if (gridContainer) {
            gridContainer.classList.remove('hidden');
            document.getElementById('viewGridBtn').classList.add('active');
            if (window.Tabulator) {
                if (!_tabulatorTable) {
                    _initTabulator(_lastCompanies);
                } else {
                    _updateTabulatorData(_lastCompanies);
                }
            } else {
                gridContainer.innerHTML = '<p class="hint-text" style="padding:20px">Tabulator library not loaded. Using table view instead.</p>';
            }
        }
    } else {
        table.classList.add('hidden');
        container.classList.remove('hidden');
        if (gridContainer) gridContainer.classList.add('hidden');
        const btnId = `view${view.charAt(0).toUpperCase() + view.slice(1)}Btn`;
        const btn = document.getElementById(btnId);
        if (btn) btn.classList.add('active');
        renderAlternateView(_lastCompanies);
    }
}

function renderAlternateView(companies) {
    const container = document.getElementById('companyViewContainer');
    if (currentCompanyView === 'gallery') renderGalleryView(companies, container);
    else if (currentCompanyView === 'timeline') renderTimelineView(companies, container);
    else if (currentCompanyView === 'matrix') renderMatrixView(companies, container);
}

function renderGalleryView(companies, container) {
    if (!companies.length) {
        container.innerHTML = '<p class="hint-text" style="padding:20px">No companies to display.</p>';
        return;
    }
    container.innerHTML = `<div class="gallery-grid">${companies.map(c => {
        const logoUrl = c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`;
        return `<div class="gallery-card" data-action="show-detail" data-id="${c.id}">
            <div class="gallery-card-header">
                <img class="gallery-logo" src="${esc(logoUrl)}" alt="${escAttr(c.name)} logo" onerror="this.style.display='none'">
                <div>
                    <strong>${esc(c.name)}</strong>
                    ${c.category_name ? `<div class="gallery-cat">${esc(c.category_name)}</div>` : ''}
                </div>
                ${c.is_starred ? '<span class="material-symbols-outlined" style="color:var(--text-primary);font-size:16px;margin-left:auto">star</span>' : ''}
            </div>
            <p class="gallery-desc">${esc((c.what || '').substring(0, 120))}</p>
            <div class="gallery-meta">
                ${c.geography ? `<span>${esc(c.geography)}</span>` : ''}
                ${c.funding_stage ? `<span>${esc(c.funding_stage)}</span>` : ''}
                ${c.founded_year ? `<span>${c.founded_year}</span>` : ''}
            </div>
            <div class="gallery-tags">${(c.tags || []).slice(0, 3).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
        </div>`;
    }).join('')}</div>`;
}

function renderTimelineView(companies, container) {
    const withYear = companies.filter(c => c.founded_year);
    if (!withYear.length) {
        container.innerHTML = '<p class="hint-text" style="padding:20px">No companies with founding year data for timeline view.</p>';
        return;
    }
    const byYear = {};
    withYear.forEach(c => {
        const y = c.founded_year;
        if (!byYear[y]) byYear[y] = [];
        byYear[y].push(c);
    });
    const years = Object.keys(byYear).sort((a, b) => a - b);

    container.innerHTML = `<div class="timeline-container">
        <div class="timeline-track">
            ${years.map(y => `<div class="timeline-year">
                <div class="timeline-year-label">${y}</div>
                <div class="timeline-year-dots">
                    ${byYear[y].map(c => {
                        return `<div class="timeline-dot" style="background:var(--text-primary)" data-action="show-detail" data-id="${c.id}" title="${esc(c.name)} — ${esc(c.category_name || '')}"></div>`;
                    }).join('')}
                </div>
            </div>`).join('')}
        </div>
    </div>`;
}

function renderMatrixView(companies, container) {
    if (!companies.length) {
        container.innerHTML = '<p class="hint-text" style="padding:20px">No companies for matrix view.</p>';
        return;
    }
    // Rows: categories, Columns: geographies
    const cats = {};
    const geos = new Set();
    companies.forEach(c => {
        const catName = c.category_name || 'Uncategorized';
        const geo = c.geography || 'Unknown';
        if (!cats[catName]) cats[catName] = {};
        const geoKey = geo.split(',')[0].trim(); // use first geo segment
        geos.add(geoKey);
        if (!cats[catName][geoKey]) cats[catName][geoKey] = [];
        cats[catName][geoKey].push(c);
    });
    const geoList = Array.from(geos).sort();
    const catNames = Object.keys(cats).sort();

    container.innerHTML = `<div class="matrix-wrapper"><table class="matrix-table">
        <thead><tr><th>Category</th>${geoList.map(g => `<th title="${esc(g)}">${esc(g.length > 16 ? g.substring(0, 15) + '\u2026' : g)}</th>`).join('')}<th>Total</th></tr></thead>
        <tbody>${catNames.map(cat => {
            const total = geoList.reduce((s, g) => s + (cats[cat][g] ? cats[cat][g].length : 0), 0);
            return `<tr><td><strong>${esc(cat)}</strong></td>
                ${geoList.map(g => {
                    const count = cats[cat][g] ? cats[cat][g].length : 0;
                    return `<td class="matrix-cell ${count ? 'matrix-filled' : ''}" ${count ? `data-action="show-matrix-detail" data-cat="${escAttr(cat)}" data-geo="${escAttr(g)}" style="cursor:pointer"` : ''}>${count || ''}</td>`;
                }).join('')}
                <td><strong>${total}</strong></td>
            </tr>`;
        }).join('')}</tbody>
        <tfoot><tr><td><strong>Total</strong></td>${geoList.map(g => {
            const total = catNames.reduce((s, cat) => s + (cats[cat][g] ? cats[cat][g].length : 0), 0);
            return `<td><strong>${total}</strong></td>`;
        }).join('')}<td><strong>${companies.length}</strong></td></tr></tfoot>
    </table></div>`;
}

function showMatrixDetail(catName, geoKey) {
    const matches = _lastCompanies.filter(c =>
        (c.category_name || 'Uncategorized') === catName &&
        (c.geography || 'Unknown').split(',')[0].trim() === geoKey
    );
    const panel = document.getElementById('detailPanel');
    document.getElementById('detailName').textContent = `${catName} × ${geoKey}`;
    document.getElementById('detailContent').innerHTML = `
        <p>${matches.length} companies</p>
        <div class="category-company-list">
            ${matches.map(c => `
                <div class="cat-company-item" data-action="show-detail" data-id="${c.id}">
                    <strong>${esc(c.name)}</strong>
                    <span class="text-muted" style="font-size:11px;margin-left:auto">${esc(c.what || '').substring(0, 60)}</span>
                </div>
            `).join('')}
        </div>
        <button class="btn" data-action="close-detail" style="margin-top:12px">Close</button>
    `;
    panel.classList.remove('hidden');
}

// --- Sort Headers ---
document.addEventListener('click', (e) => {
    const th = e.target.closest('.sort-header');
    if (!th) return;
    const sortKey = th.dataset.sort;
    if (currentSort.by === sortKey) {
        currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.by = sortKey;
        currentSort.dir = 'asc';
    }
    loadCompanies();
});

// --- Edit Form submit listener (replaces onsubmit="saveEdit(event)") ---
document.addEventListener('submit', (e) => {
    if (e.target.id === 'editForm') {
        saveEdit(e);
    }
});

// --- Search input listener (replaces oninput="debounceSearch()") ---
const _searchInput = document.getElementById('searchInput');
if (_searchInput && !_searchInput._boundInput) {
    _searchInput._boundInput = true;
    _searchInput.addEventListener('input', debounceSearch);
}

// ── Action Delegation ─────────────────────────────────────────
registerActions({
    // --- Table row / detail navigation ---
    'show-detail': (el, e) => {
        // Don't trigger on checkbox, star, or link clicks
        if (e.target.closest('.bulk-cell') || e.target.closest('.star-btn') ||
            e.target.closest('[data-action="toggle-star"]') ||
            e.target.tagName === 'INPUT' || e.target.tagName === 'A') return;
        showDetail(Number(el.dataset.id));
    },
    'close-detail': () => closeDetail(),
    'navigate-category': (el, e) => {
        e.stopPropagation();
        navigateTo('category', Number(el.dataset.id), el.dataset.name);
    },
    'show-tab': (el) => showTab(el.dataset.tab),

    // --- Starring ---
    'toggle-star': (el, e) => {
        e.stopPropagation();
        toggleStar(Number(el.dataset.id), el);
    },

    // --- Bulk selection ---
    'toggle-select-all': (el) => toggleSelectAll(el),
    'clear-bulk-selection': () => clearBulkSelection(),
    'bulk-action': (el) => bulkAction(el.dataset.bulkType),
    'start-batch-enrichment': () => startBatchEnrichment(),

    // --- View switching ---
    'switch-company-view': (el) => switchCompanyView(el.dataset.view),
    'export-tabulator-csv': () => exportTabulatorCsv(),

    // --- Filters ---
    'load-companies': () => loadCompanies(),
    'clear-all-filters': () => clearAllFilters(),
    'debounce-search': () => debounceSearch(),

    // --- Detail panel actions ---
    'open-edit-modal': (el) => openEditModal(Number(el.dataset.id)),
    'close-edit-modal': () => closeEditModal(),
    'load-subcategories': () => loadSubcategories(),
    'delete-company': (el) => deleteCompany(Number(el.dataset.id)),
    'open-re-research': (el) => openReResearch(Number(el.dataset.id)),
    'start-re-research': (el) => startReResearch(Number(el.dataset.id)),
    'close-re-research': (el) => closeReResearch(Number(el.dataset.id)),
    'start-enrichment': (el) => startEnrichment(Number(el.dataset.id)),
    'start-company-research': (el) => startCompanyResearch(Number(el.dataset.id), el.dataset.name),
    'find-similar': (el) => findSimilar(Number(el.dataset.id)),
    'show-version-history': (el) => showVersionHistory(Number(el.dataset.id)),
    'show-version-diff': (el) => showVersionDiff(
        Number(el.dataset.companyId),
        Number(el.dataset.newVersion),
        Number(el.dataset.oldVersion)
    ),
    'restore-version': (el) => restoreVersion(Number(el.dataset.id), Number(el.dataset.companyId)),
    'show-qr': (el, e) => {
        e.stopPropagation();
        showCompanyQr(el.dataset.url, el.dataset.name);
    },
    'close-qr-modal': (el) => el.closest('.modal-overlay').remove(),

    // --- Relationship ---
    'save-relationship': (el) => saveRelationship(Number(el.dataset.id)),

    // --- Notes ---
    'show-add-note': (el) => showAddNote(Number(el.dataset.id)),
    'add-note': (el) => addNote(Number(el.dataset.id)),
    'cancel-add-note': (el) => {
        document.getElementById(`addNoteForm-${el.dataset.id}`).classList.add('hidden');
    },
    'toggle-pin-note': (el) => togglePinNote(Number(el.dataset.id), Number(el.dataset.companyId)),
    'delete-note': (el) => deleteNote(Number(el.dataset.id), Number(el.dataset.companyId)),

    // --- Events ---
    'show-add-event': (el) => showAddEvent(Number(el.dataset.id)),
    'add-event': (el) => addEvent(Number(el.dataset.id)),
    'cancel-add-event': (el) => {
        document.getElementById(`addEventForm-${el.dataset.id}`).classList.add('hidden');
    },
    'delete-event': (el) => deleteEvent(Number(el.dataset.id), Number(el.dataset.companyId)),

    // --- Matrix view ---
    'show-matrix-detail': (el) => showMatrixDetail(el.dataset.cat, el.dataset.geo),
});

// --- Bulk select via change delegation ---
registerActions({
    'toggle-bulk-select': (el, e) => {
        e.stopPropagation();
        toggleBulkSelect(Number(el.dataset.id), el, e);
    },
});

// ── Window exports (called from other modules) ───────────────
window.loadCompanies = loadCompanies;
window.showDetail = showDetail;
window.closeDetail = closeDetail;
window.switchCompanyView = switchCompanyView;
window.toggleStar = toggleStar;
window.openEditModal = openEditModal;
window.closeEditModal = closeEditModal;
window.debounceSearch = debounceSearch;
window.loadSubcategories = loadSubcategories;
window.toggleBulkSelect = toggleBulkSelect;
window.toggleSelectAll = toggleSelectAll;
window.bulkAction = bulkAction;
window.clearBulkSelection = clearBulkSelection;
window.updateBulkBar = updateBulkBar;
window.saveRelationship = saveRelationship;
window.startBatchEnrichment = startBatchEnrichment;
window.exportTabulatorCsv = exportTabulatorCsv;
window.showMatrixDetail = showMatrixDetail;
window.saveEdit = saveEdit;
