/**
 * Library integrations and monkey-patches:
 * Notyf, DOMPurify, Day.js, Fuse.js, Tippy.js, Tagify,
 * SortableJS, Motion One, pdfmake override, confetti,
 * Driver.js product tour, enhanced search.
 */

// --- Notyf (Toast Notifications) ---
let notyf = null;
function initNotyf() {
    if (window.Notyf) {
        notyf = new Notyf({
            duration: 4000,
            position: { x: 'right', y: 'bottom' },
            types: [
                { type: 'success', background: '#5a7c5a', icon: false },
                { type: 'error', background: '#bc6c5a', icon: false },
                { type: 'info', background: '#6b7280', className: 'notyf-info', icon: false },
            ],
            ripple: true,
        });
    }
}

// Override showToast to use Notyf when available
const _origShowToast = showToast;
showToast = function(message, duration) {
    if (notyf) {
        notyf.open({ type: 'info', message });
    } else {
        _origShowToast(message, duration);
    }
};

// --- DOMPurify (Sanitize HTML output) ---
function sanitize(html) {
    if (window.DOMPurify) return DOMPurify.sanitize(html);
    // Fallback: strip all HTML tags if DOMPurify CDN failed to load
    const tmp = document.createElement('div');
    tmp.textContent = html;
    return tmp.innerHTML;
}

// --- Day.js (Date Formatting) ---
function initDayjs() {
    if (window.dayjs && window.dayjs_plugin_relativeTime) {
        dayjs.extend(dayjs_plugin_relativeTime);
    }
}
function formatDate(dateStr) {
    if (!dateStr) return 'N/A';
    if (window.dayjs) return dayjs(dateStr).format('MMM D, YYYY');
    return new Date(dateStr).toLocaleDateString();
}
function formatRelative(dateStr) {
    if (!dateStr) return '';
    if (window.dayjs) return dayjs(dateStr).fromNow();
    return new Date(dateStr).toLocaleDateString();
}

// --- Fuse.js (Fuzzy Search) ---
let fuseInstance = null;
let allCompaniesCache = [];

async function buildFuseIndex() {
    if (!window.Fuse || !currentProjectId) return;
    const res = await safeFetch(`/api/companies?project_id=${currentProjectId}`);
    allCompaniesCache = await res.json();
    fuseInstance = new Fuse(allCompaniesCache, {
        keys: [
            { name: 'name', weight: 0.4 },
            { name: 'what', weight: 0.2 },
            { name: 'target', weight: 0.15 },
            { name: 'category_name', weight: 0.1 },
            { name: 'geography', weight: 0.1 },
            { name: 'tags', weight: 0.05 },
        ],
        threshold: 0.35,
        includeScore: true,
        ignoreLocation: true,
    });
}

function fuseSearch(query) {
    if (!fuseInstance || !query.trim()) return null;
    return fuseInstance.search(query).map(r => r.item);
}

// --- Tippy.js (Tooltips) ---
function initTooltips() {
    if (!window.tippy) return;
    tippy('[data-tippy-content]', {
        theme: 'light-border',
        placement: 'top',
        animation: 'fade',
        delay: [300, 0],
    });
}

// --- Tagify (Enhanced Tag Input) ---
let tagifyInstance = null;

function initTagify() {
    if (!window.Tagify) return;
    const tagInput = document.getElementById('editTags');
    if (!tagInput || tagInput._tagifyInitialized) return;

    tagifyInstance = new Tagify(tagInput, {
        delimiters: ',',
        maxTags: 20,
        dropdown: { enabled: 1, maxItems: 10, closeOnSelect: true },
        originalInputValueFormat: vals => vals.map(v => v.value).join(', '),
    });
    tagInput._tagifyInitialized = true;
}

// Re-init tagify when edit modal opens
const _origOpenEditModal = openEditModal;
openEditModal = async function(id) {
    await _origOpenEditModal(id);
    if (tagifyInstance) { tagifyInstance.destroy(); tagifyInstance = null; }
    const tagInput = document.getElementById('editTags');
    if (tagInput) tagInput._tagifyInitialized = false;
    initTagify();
};

// --- SortableJS (Enhanced Drag-Drop for Map Tiles) ---
function initSortableMapTiles() {
    if (!window.Sortable) return;
    document.querySelectorAll('.map-tiles').forEach(container => {
        Sortable.create(container, {
            group: 'market-map',
            animation: 200,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            dragClass: 'sortable-drag',
            onEnd: async (evt) => {
                // SortableJS adds smooth animations; actual data update handled by native drag-drop
            },
        });
    });
}

// --- Hotkeys.js (Enhanced Keyboard Shortcuts) ---
let _hotkeysInitialized = false;
function initHotkeys() {
    if (!window.hotkeys || _hotkeysInitialized) return;
    _hotkeysInitialized = true;

    hotkeys('ctrl+k,command+k', (e) => {
        e.preventDefault();
        document.getElementById('searchInput')?.focus();
    });
    hotkeys('ctrl+e,command+e', (e) => {
        e.preventDefault();
        exportXlsx();
    });
    hotkeys('ctrl+shift+p,command+shift+p', (e) => {
        e.preventDefault();
        exportFullPdf();
    });
    hotkeys('g', (e) => {
        if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) return;
        e.preventDefault();
        const mapTab = document.getElementById('tab-map');
        if (mapTab && mapTab.classList.contains('active')) switchMapView('geo');
    });
    hotkeys('t', (e) => {
        if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) return;
        e.preventDefault();
        const taxTab = document.getElementById('tab-taxonomy');
        if (taxTab && taxTab.classList.contains('active')) switchTaxonomyView('graph');
    });
    hotkeys('shift+/', (e) => {
        // ? key (shift+/)
        if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) return;
        e.preventDefault();
        toggleShortcutsOverlay();
    });
    hotkeys('escape', () => {
        const overlay = document.getElementById('shortcutsOverlay');
        if (overlay && !overlay.classList.contains('hidden')) {
            overlay.classList.add('hidden');
        }
    });
}

// --- Driver.js (Product Tour) ---
function startProductTour() {
    if (!window.driver) return;
    const driverObj = driver.js.driver({
        showProgress: true,
        animate: true,
        steps: [
            { element: '#tab-companies', popover: { title: 'Companies Tab', description: 'Browse, search, and manage all researched companies. Use fuzzy search to find companies by name, category, or geography.', position: 'bottom' } },
            { element: '#searchInput', popover: { title: 'Smart Search', description: 'Powered by Fuse.js — type anything and it fuzzy-matches across name, description, category, tags, and geography. Press / to focus.', position: 'bottom' } },
            { element: '#tab-taxonomy', popover: { title: 'Taxonomy Tab', description: 'View your category structure in tree or interactive graph view. Analytics dashboard shows charts for category distribution, funding, and geography.', position: 'bottom' } },
            { element: '#tab-map', popover: { title: 'Map Tab', description: 'Two views: Market Map (drag-drop between categories) and Geographic Map (Leaflet world map showing company locations).', position: 'bottom' } },
            { element: '#tab-reports', popover: { title: 'Reports Tab', description: 'Generate AI-powered market analysis reports. Export as Markdown or PDF (powered by pdfmake).', position: 'bottom' } },
            { element: '#tab-export', popover: { title: 'Export Tab', description: 'Export your data as JSON, Markdown, CSV, or formatted Excel workbooks (powered by SheetJS).', position: 'bottom' } },
            { element: '#chatToggle', popover: { title: 'AI Chat', description: 'Ask questions about your taxonomy data — powered by Claude AI.', position: 'left' } },
            { popover: { title: 'Keyboard Shortcuts', description: 'Press ? for full shortcut list. j/k navigate rows, 1-5 switch tabs, / focuses search, Ctrl+K opens search, Ctrl+E exports Excel.', position: 'center' } },
        ],
    });
    driverObj.drive();
}

// --- canvas-confetti (Batch Complete Celebration) ---
function celebrateBatchComplete() {
    if (!window.confetti) return;
    confetti({
        particleCount: 100,
        spread: 70,
        origin: { y: 0.6 },
        colors: ['#bc6c5a', '#5a7c5a', '#d4a853', '#6b8fa3'],
    });
}

// Hook confetti into SSE batch_complete
const _origConnectSSE = connectSSE;
connectSSE = function() {
    _origConnectSSE();
    if (eventSource) {
        eventSource.addEventListener('batch_complete', () => {
            celebrateBatchComplete();
            if (notyf) notyf.success('Batch processing complete!');
        });
    }
};

// --- Motion One (Animations) ---
function animateElement(el, keyframes, options) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        // Apply final state immediately for users who prefer reduced motion
        if (keyframes.opacity) el.style.opacity = Array.isArray(keyframes.opacity) ? keyframes.opacity[keyframes.opacity.length-1] : keyframes.opacity;
        if (keyframes.transform) el.style.transform = Array.isArray(keyframes.transform) ? keyframes.transform[keyframes.transform.length-1] : keyframes.transform;
        return;
    }
    if (window.Motion && window.Motion.animate) {
        return Motion.animate(el, keyframes, options);
    }
    if (keyframes.opacity) el.style.opacity = Array.isArray(keyframes.opacity) ? keyframes.opacity[keyframes.opacity.length-1] : keyframes.opacity;
}

// Animate detail panel open
const _origShowDetail = showDetail;
showDetail = async function(id) {
    await _origShowDetail(id);
    const panel = document.getElementById('detailPanel');
    if (panel && !panel.classList.contains('hidden')) {
        animateElement(panel, { opacity: [0, 1], transform: ['translateX(20px)', 'translateX(0)'] }, { duration: 0.25 });
    }
};

// Animate tab switch + refresh charts
const _origShowTab = showTab;
showTab = function(name) {
    _origShowTab(name);
    const tab = document.getElementById('tab-' + name);
    if (tab) {
        animateElement(tab, { opacity: [0, 1] }, { duration: 0.2 });
    }
    if (name === 'taxonomy') refreshDashboardCharts();
};

// --- Enhance loadCompanies with Fuse.js rebuild ---
const _origLoadCompanies = loadCompanies;
loadCompanies = async function() {
    await _origLoadCompanies();
    buildFuseIndex();
    initTooltips();
    if (document.getElementById('tab-map')?.classList.contains('active')) {
        initSortableMapTiles();
    }
};

// --- Enhanced search with Fuse.js ---
const origDebounceSearch = debounceSearch;
debounceSearch = function() {
    clearTimeout(searchTimeout);
    const query = document.getElementById('searchInput').value;
    if (fuseInstance && query.trim().length >= 2) {
        searchTimeout = setTimeout(() => {
            const results = fuseSearch(query);
            if (results) {
                renderFuseResults(results);
            } else {
                _origLoadCompanies();
            }
        }, 200);
    } else {
        searchTimeout = setTimeout(() => _origLoadCompanies(), 300);
    }
};

function renderFuseResults(companies) {
    const tbody = document.getElementById('companyBody');
    tbody.innerHTML = companies.map(c => {
        const compClass = (c.completeness || 0) >= 0.7 ? 'comp-high' : (c.completeness || 0) >= 0.4 ? 'comp-mid' : 'comp-low';
        const compPct = Math.round((c.completeness || 0) * 100);
        return `
        <tr onclick="showDetail(${c.id})" style="cursor:pointer" data-company-id="${c.id}">
            <td class="bulk-cell" onclick="event.stopPropagation()"><input type="checkbox" class="bulk-checkbox" data-company-id="${c.id}" ${bulkSelection.has(c.id) ? 'checked' : ''} onchange="toggleBulkSelect(${c.id}, this, event)"></td>
            <td><span class="star-btn ${c.is_starred ? 'starred' : ''}" onclick="event.stopPropagation();toggleStar(${c.id},this)" title="Star"><span class="material-symbols-outlined">${c.is_starred ? 'star' : 'star_outline'}</span></span></td>
            <td>
                <div class="company-name-cell">
                    <img class="company-logo" src="${c.logo_url || 'https://logo.clearbit.com/' + extractDomain(c.url)}" alt="" onerror="this.style.display='none'">
                    <strong>${esc(c.name)}</strong>
                    <span class="completeness-dot ${compClass}" title="${compPct}% complete"></span>
                    ${c.relationship_status ? '<span class="relationship-dot rel-' + c.relationship_status + '" title="' + relationshipLabel(c.relationship_status) + '"></span>' : ''}
                </div>
            </td>
            <td>${c.category_id ? `<a class="cat-link" onclick="event.stopPropagation();navigateTo('category',${c.category_id},'${escAttr(c.category_name)}')"><span class="cat-color-dot" style="background:${getCategoryColor(c.category_id) || 'transparent'}"></span> ${esc(c.category_name)}</a>` : 'N/A'}</td>
            <td><div class="cell-clamp">${esc(c.what || '')}</div></td>
            <td><div class="cell-clamp">${esc(c.target || '')}</div></td>
            <td><div class="cell-clamp">${esc(c.geography || '')}</div></td>
            <td><span class="source-count">${c.source_count || 0} links</span></td>
            <td>${(c.tags || []).map(t => '<span class="tag">' + esc(t) + '</span>').join(' ')}</td>
            <td>${c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : '-'}</td>
        </tr>`;
    }).join('');
}

// --- Override exportReportPdf to use pdfmake when available ---
const _origExportReportPdf = exportReportPdf;
exportReportPdf = function() {
    if (window.pdfMake) {
        exportReportPdfPdfmake();
    } else {
        _origExportReportPdf();
    }
};

// --- Autosize (Auto-expanding textareas) ---
function initAutosize() {
    if (!window.autosize) return;
    document.querySelectorAll('textarea').forEach(ta => {
        if (!ta._autosizeAttached) {
            autosize(ta);
            ta._autosizeAttached = true;
        }
    });
}

// Re-apply autosize whenever modals open or tabs switch
const _origShowTabAutosize = showTab;
showTab = function(name) {
    _origShowTabAutosize(name);
    setTimeout(initAutosize, 100);
};

// --- medium-zoom (Click-to-zoom on images) ---
let _mediumZoomInstance = null;
function initMediumZoom() {
    if (!window.mediumZoom) return;
    if (_mediumZoomInstance) _mediumZoomInstance.detach();
    _mediumZoomInstance = mediumZoom('.company-logo, .report-body img, #detailPanel img', {
        margin: 24,
        background: 'rgba(0,0,0,0.6)',
    });
}

// Refresh zoom targets after company list loads
const _origLoadCompaniesZoom = loadCompanies;
loadCompanies = async function() {
    await _origLoadCompaniesZoom();
    setTimeout(initMediumZoom, 200);
};

// --- Flatpickr (Founded year range filter) ---
let _foundedYearPicker = null;
function initFlatpickr() {
    if (!window.flatpickr) return;
    const input = document.getElementById('foundedYearFilter');
    if (!input || input._flatpickrInit) return;
    input._flatpickrInit = true;

    _foundedYearPicker = flatpickr(input, {
        mode: 'range',
        dateFormat: 'Y',
        minDate: '1990',
        maxDate: new Date().getFullYear().toString(),
        onChange: function(dates) {
            if (dates.length === 2) {
                activeFilters.founded_from = dates[0].getFullYear();
                activeFilters.founded_to = dates[1].getFullYear();
                renderFilterChips();
                loadCompanies();
            } else if (dates.length === 0) {
                activeFilters.founded_from = null;
                activeFilters.founded_to = null;
                renderFilterChips();
                loadCompanies();
            }
        },
    });
}

// --- currency.js (Precise currency formatting) ---
function formatCurrency(value) {
    if (value == null || value === '') return null;
    if (window.currency) return currency(value, { separator: ',', precision: 0 }).format();
    return '$' + Number(value).toLocaleString();
}

// --- mark.js (Search result highlighting) ---
function highlightSearchResults(query) {
    if (!window.Mark || !query || query.length < 2) return;
    const ctx = document.getElementById('companyBody');
    if (!ctx) return;
    const instance = new Mark(ctx);
    instance.unmark();
    instance.mark(query, {
        className: 'search-highlight',
        separateWordSearch: true,
        accuracy: 'partially',
    });
}

// Hook into search to highlight results
const _origDebounceSearchMark = debounceSearch;
debounceSearch = function() {
    _origDebounceSearchMark();
    const query = document.getElementById('searchInput').value;
    setTimeout(() => highlightSearchResults(query), 400);
};

// --- QR Code generation ---
function generateQrCode(text, size) {
    if (!window.qrcode) return null;
    size = size || 4;
    const qr = qrcode(0, 'M');
    qr.addData(text);
    qr.make();
    return qr.createImgTag(size, 0);
}

// --- Rough Notation (hand-drawn annotations) ---
function annotateElement(el, type, color) {
    if (!window.RoughNotation) return null;
    const annotation = RoughNotation.annotate(el, {
        type: type || 'underline',
        color: color || '#bc6c5a',
        animationDuration: 600,
    });
    annotation.show();
    return annotation;
}

// --- Panzoom (pan & zoom for market map) ---
let _mapPanzoom = null;
function initMapPanzoom() {
    if (!window.Panzoom) return;
    const el = document.getElementById('marketMap');
    if (!el || el._panzoomInit) return;
    el._panzoomInit = true;
    _mapPanzoom = Panzoom(el, {
        maxScale: 3,
        minScale: 0.5,
        contain: 'outside',
    });
    el.parentElement.addEventListener('wheel', (e) => {
        if (!document.getElementById('marketMap').classList.contains('hidden')) {
            _mapPanzoom.zoomWithWheel(e);
        }
    });
}

// --- NProgress configuration ---
function initNProgress() {
    if (window.NProgress) {
        NProgress.configure({ showSpinner: false, trickleSpeed: 200, minimum: 0.1 });
    }
}

// --- Command Palette (lightweight, no dependencies) ---
let _cmdPaletteEl = null;
const _cmdActions = [
    { title: 'Go to Companies', section: 'Navigation', handler: () => showTab('companies') },
    { title: 'Go to Taxonomy', section: 'Navigation', handler: () => showTab('taxonomy') },
    { title: 'Go to Map', section: 'Navigation', handler: () => showTab('map') },
    { title: 'Go to Reports', section: 'Navigation', handler: () => showTab('reports') },
    { title: 'Go to Canvas', section: 'Navigation', handler: () => showTab('canvas') },
    { title: 'Go to Export', section: 'Navigation', handler: () => showTab('export') },
    { title: 'Go to Process', section: 'Navigation', handler: () => showTab('process') },
    { title: 'Focus Search', section: 'Actions', handler: () => document.getElementById('searchInput')?.focus() },
    { title: 'Export as Excel', section: 'Export', handler: () => { if (typeof exportXlsx === 'function') exportXlsx(); } },
    { title: 'Export as CSV', section: 'Export', handler: () => { if (typeof exportCsv === 'function') exportCsv(); } },
    { title: 'Export as JSON', section: 'Export', handler: () => { if (typeof exportJson === 'function') exportJson(); } },
    { title: 'Export Full PDF', section: 'Export', handler: () => { if (typeof exportFullPdf === 'function') exportFullPdf(); } },
    { title: 'Toggle Dark/Light Mode', section: 'Settings', handler: () => toggleTheme() },
    { title: 'Refresh Data', section: 'Actions', handler: () => { loadCompanies(); loadTaxonomy(); } },
    { title: 'Show Keyboard Shortcuts', section: 'Help', handler: () => toggleShortcutsOverlay() },
    { title: 'Start Product Tour', section: 'Help', handler: () => startProductTour() },
    { title: 'Geographic Map', section: 'Map Views', handler: () => { showTab('map'); setTimeout(() => switchMapView('geo'), 100); } },
    { title: 'Auto-Layout Map', section: 'Map Views', handler: () => { showTab('map'); setTimeout(() => switchMapView('auto'), 100); } },
    { title: 'Toggle Heatmap', section: 'Map Views', handler: () => toggleGeoHeatmap() },
];

function initCommandPalette() {
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            toggleCommandPalette();
        }
    });
}

function toggleCommandPalette() {
    if (_cmdPaletteEl) { _cmdPaletteEl.remove(); _cmdPaletteEl = null; return; }
    _cmdPaletteEl = document.createElement('div');
    _cmdPaletteEl.className = 'cmd-palette-overlay';
    _cmdPaletteEl.onclick = (e) => { if (e.target === _cmdPaletteEl) { _cmdPaletteEl.remove(); _cmdPaletteEl = null; } };
    _cmdPaletteEl.innerHTML = `<div class="cmd-palette">
        <input type="text" class="cmd-palette-input" placeholder="Type a command..." autofocus>
        <div class="cmd-palette-list"></div>
    </div>`;
    document.body.appendChild(_cmdPaletteEl);
    const input = _cmdPaletteEl.querySelector('.cmd-palette-input');
    const list = _cmdPaletteEl.querySelector('.cmd-palette-list');
    let selectedIdx = 0;

    function render(query) {
        const filtered = query ? _cmdActions.filter(a => a.title.toLowerCase().includes(query.toLowerCase())) : _cmdActions;
        selectedIdx = Math.min(selectedIdx, Math.max(0, filtered.length - 1));
        list.innerHTML = filtered.map((a, i) => `<div class="cmd-palette-item ${i === selectedIdx ? 'selected' : ''}" data-idx="${i}">
            <span class="cmd-palette-section">${esc(a.section)}</span> ${esc(a.title)}
        </div>`).join('') || '<div class="cmd-palette-empty">No matching commands</div>';
        list.querySelectorAll('.cmd-palette-item').forEach(el => {
            el.onclick = () => { const idx = parseInt(el.dataset.idx); filtered[idx]?.handler(); _cmdPaletteEl.remove(); _cmdPaletteEl = null; };
        });
        return filtered;
    }
    render('');
    input.addEventListener('input', () => { selectedIdx = 0; render(input.value); });
    input.addEventListener('keydown', (e) => {
        const filtered = input.value ? _cmdActions.filter(a => a.title.toLowerCase().includes(input.value.toLowerCase())) : _cmdActions;
        if (e.key === 'ArrowDown') { e.preventDefault(); selectedIdx = Math.min(selectedIdx + 1, filtered.length - 1); render(input.value); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); selectedIdx = Math.max(selectedIdx - 1, 0); render(input.value); }
        else if (e.key === 'Enter') { e.preventDefault(); filtered[selectedIdx]?.handler(); _cmdPaletteEl.remove(); _cmdPaletteEl = null; }
        else if (e.key === 'Escape') { _cmdPaletteEl.remove(); _cmdPaletteEl = null; }
    });
}

// --- Split.js (Resizable panes) ---
function initSplitPanes() {
    if (!window.Split) return;
    const detail = document.getElementById('detailPanel');
    const compTable = document.querySelector('#tab-companies .table-wrapper');
    if (!detail || !compTable || detail._splitInit) return;
    // Only init split when detail panel is visible and in appropriate layout
    // Defer to user triggering — available as utility
}

function splitPanes(ids, options) {
    if (!window.Split) return null;
    return Split(ids, Object.assign({ gutterSize: 6, minSize: 200 }, options || {}));
}
