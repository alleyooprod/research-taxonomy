/**
 * Multi-filter system and saved views.
 */

async function loadFilterOptions() {
    const res = await safeFetch(`/api/filters/options?project_id=${currentProjectId}`);
    const data = await res.json();

    const tagSel = document.getElementById('tagFilter');
    tagSel.innerHTML = '<option value="">+ Tag</option>' +
        data.tags.map(t => `<option value="${esc(t.tag)}">${esc(t.tag)} (${t.count})</option>`).join('');

    const geoSel = document.getElementById('geoFilter');
    geoSel.innerHTML = '<option value="">+ Geography</option>' +
        data.geographies.map(g => `<option value="${esc(g)}">${esc(g)}</option>`).join('');

    const stageSel = document.getElementById('stageFilter');
    stageSel.innerHTML = '<option value="">+ Stage</option>' +
        data.funding_stages.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
}

function addFilterFromSelect(type) {
    if (type === 'category') {
        const sel = document.getElementById('categoryFilter');
        const val = sel.value;
        if (!val) { activeFilters.category_id = null; activeFilters.category_name = null; }
        else {
            activeFilters.category_id = val;
            activeFilters.category_name = sel.options[sel.selectedIndex].text.replace(/\s*\(\d+\)$/, '');
        }
        sel.selectedIndex = 0;
    } else if (type === 'tag') {
        const sel = document.getElementById('tagFilter');
        const val = sel.value;
        if (val && !activeFilters.tags.includes(val)) {
            activeFilters.tags.push(val);
        }
        sel.selectedIndex = 0;
    } else if (type === 'geography') {
        const sel = document.getElementById('geoFilter');
        activeFilters.geography = sel.value || null;
        sel.selectedIndex = 0;
    } else if (type === 'funding_stage') {
        const sel = document.getElementById('stageFilter');
        activeFilters.funding_stage = sel.value || null;
        sel.selectedIndex = 0;
    }
    renderFilterChips();
    loadCompanies();
}

function removeFilter(type, value) {
    if (type === 'category') { activeFilters.category_id = null; activeFilters.category_name = null; }
    else if (type === 'tag') { activeFilters.tags = activeFilters.tags.filter(t => t !== value); }
    else if (type === 'geography') { activeFilters.geography = null; }
    else if (type === 'funding_stage') { activeFilters.funding_stage = null; }
    else if (type === 'founded_year') {
        activeFilters.founded_from = null;
        activeFilters.founded_to = null;
        if (window._foundedYearPicker) _foundedYearPicker.clear();
    }
    renderFilterChips();
    loadCompanies();
}

function clearAllFilters() {
    activeFilters = { category_id: null, category_name: null, tags: [], geography: null, funding_stage: null, founded_from: null, founded_to: null };
    if (window._foundedYearPicker) _foundedYearPicker.clear();
    document.getElementById('searchInput').value = '';
    document.getElementById('starredFilter').checked = false;
    document.getElementById('enrichmentFilter').checked = false;
    document.getElementById('relationshipFilter').value = '';
    renderFilterChips();
    loadCompanies();
}

function renderFilterChips() {
    const container = document.getElementById('activeFilters');
    const chips = [];

    if (activeFilters.category_id) {
        chips.push(`<span class="filter-chip" data-type="category">
            Category: ${esc(activeFilters.category_name)}
            <span class="chip-remove" onclick="removeFilter('category')">&times;</span>
        </span>`);
    }
    for (const tag of activeFilters.tags) {
        chips.push(`<span class="filter-chip filter-chip-tag" data-type="tag">
            Tag: ${esc(tag)}
            <span class="chip-remove" onclick="removeFilter('tag','${escAttr(tag)}')">&times;</span>
        </span>`);
    }
    if (activeFilters.geography) {
        chips.push(`<span class="filter-chip" data-type="geography">
            Geo: ${esc(activeFilters.geography)}
            <span class="chip-remove" onclick="removeFilter('geography')">&times;</span>
        </span>`);
    }
    if (activeFilters.funding_stage) {
        chips.push(`<span class="filter-chip" data-type="funding_stage">
            Stage: ${esc(activeFilters.funding_stage)}
            <span class="chip-remove" onclick="removeFilter('funding_stage')">&times;</span>
        </span>`);
    }
    if (activeFilters.founded_from && activeFilters.founded_to) {
        chips.push(`<span class="filter-chip" data-type="founded_year">
            Founded: ${activeFilters.founded_from}–${activeFilters.founded_to}
            <span class="chip-remove" onclick="removeFilter('founded_year')">&times;</span>
        </span>`);
    }

    if (chips.length) {
        chips.push(`<span class="filter-chip filter-chip-clear" onclick="clearAllFilters()">Clear all</span>`);
        container.innerHTML = chips.join('');
        container.classList.remove('hidden');
    } else {
        container.innerHTML = '';
        container.classList.add('hidden');
    }
}

// --- Saved Views ---
async function loadSavedViews() {
    const res = await safeFetch(`/api/views?project_id=${currentProjectId}`);
    savedViews = await res.json();
    const sel = document.getElementById('savedViewSelect');
    sel.innerHTML = '<option value="">Saved views...</option>' +
        savedViews.map(v => `<option value="${v.id}">${esc(v.name)}</option>`).join('');
}

function loadSavedView() {
    const sel = document.getElementById('savedViewSelect');
    const viewId = parseInt(sel.value);
    if (!viewId) return;
    const view = savedViews.find(v => v.id === viewId);
    if (!view) return;

    const f = view.filters;
    activeFilters.category_id = f.category_id || null;
    activeFilters.category_name = f.category_name || null;
    activeFilters.tags = f.tags || [];
    activeFilters.geography = f.geography || null;
    activeFilters.funding_stage = f.funding_stage || null;
    document.getElementById('starredFilter').checked = !!f.starred;
    document.getElementById('enrichmentFilter').checked = !!f.needs_enrichment;
    document.getElementById('searchInput').value = f.search || '';

    renderFilterChips();
    loadCompanies();
}

async function saveCurrentView() {
    const name = prompt('Name for this saved view:');
    if (!name || !name.trim()) return;

    const filters = {
        category_id: activeFilters.category_id,
        category_name: activeFilters.category_name,
        tags: activeFilters.tags,
        geography: activeFilters.geography,
        funding_stage: activeFilters.funding_stage,
        starred: document.getElementById('starredFilter').checked,
        needs_enrichment: document.getElementById('enrichmentFilter').checked,
        search: document.getElementById('searchInput').value,
    };

    await safeFetch('/api/views', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, name: name.trim(), filters }),
    });
    loadSavedViews();
}
