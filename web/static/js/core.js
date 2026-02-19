/**
 * Core utilities, state, and shared functions.
 * Must be loaded first — all other modules depend on this.
 */

// CSRF token for write requests (injected by server into page)
const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content || '';

// --- Global State ---
let searchTimeout = null;
let currentTriageBatchId = null;
let triageData = [];
let allCategories = [];
let currentProjectId = null;

let activeFilters = {
    category_id: null,
    category_name: null,
    tags: [],
    geography: null,
    funding_stage: null,
    founded_from: null,
    founded_to: null,
};
let savedViews = [];

// --- Linked Record Navigation ---
let navHistory = [];  // Stack of {type, id, label}

function navigateTo(type, id, label) {
    navHistory.push({ type, id, label });
    renderBreadcrumbs();

    if (type === 'company') {
        showTab('companies');
        showDetail(id);
    } else if (type === 'category') {
        showTab('companies');
        if (typeof showCategoryDetail === 'function') showCategoryDetail(id);
    }
}

function navBack() {
    if (navHistory.length <= 1) {
        navHistory = [];
        renderBreadcrumbs();
        closeDetail();
        return;
    }
    navHistory.pop(); // remove current
    const prev = navHistory[navHistory.length - 1];
    if (prev.type === 'company') showDetail(prev.id);
    else if (prev.type === 'category') {
        if (typeof showCategoryDetail === 'function') showCategoryDetail(prev.id);
    }
    renderBreadcrumbs();
}

function renderBreadcrumbs() {
    const bar = document.getElementById('breadcrumbBar');
    if (!bar) return;
    if (!navHistory.length) {
        bar.classList.add('hidden');
        return;
    }
    bar.classList.remove('hidden');
    bar.innerHTML = navHistory.map((item, i) => {
        const isLast = i === navHistory.length - 1;
        if (isLast) return `<span class="breadcrumb-current">${esc(item.label)}</span>`;
        return `<a class="breadcrumb-link" onclick="navJumpTo(${i})">${esc(item.label)}</a><span class="breadcrumb-sep">/</span>`;
    }).join('');
}

function navJumpTo(index) {
    navHistory = navHistory.slice(0, index + 1);
    const item = navHistory[navHistory.length - 1];
    if (item.type === 'company') showDetail(item.id);
    else if (item.type === 'category') {
        if (typeof showCategoryDetail === 'function') showCategoryDetail(item.id);
    }
    renderBreadcrumbs();
}

// Retry state
let retryingBatch = null;
let retryPollInterval = null;

// AI lock (prevents concurrent CLI calls)
let aiLock = null;

function acquireAiLock(label) {
    if (aiLock) return false;
    aiLock = label;
    return true;
}

function releaseAiLock() {
    aiLock = null;
}

// --- NProgress (slim top progress bar) ---
let _activeFetches = 0;
function _nprogressStart() {
    if (window.NProgress && ++_activeFetches === 1) NProgress.start();
}
function _nprogressDone() {
    if (window.NProgress && --_activeFetches <= 0) { _activeFetches = 0; NProgress.done(); }
}

// --- Safe Fetch ---
async function safeFetch(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
        options.headers = options.headers || {};
        if (typeof options.headers.set === 'function') {
            options.headers.set('X-CSRF-Token', CSRF_TOKEN);
        } else {
            options.headers['X-CSRF-Token'] = CSRF_TOKEN;
        }
    }
    _nprogressStart();
    try {
        const response = await fetch(url, options);
        _nprogressDone();
        if (!response.ok && response.status !== 304) {
            // Clone before reading body so the original response stays usable
            const errText = await response.clone().text().catch(() => response.statusText);
            console.error(`HTTP ${response.status}: ${method} ${url}`, errText);
            if (response.status === 403) {
                showToast('Session expired — please refresh the page');
            } else if (response.status >= 500) {
                showToast(`Server error (${response.status})`);
            }
        }
        return response;
    } catch (e) {
        _nprogressDone();
        console.error(`Fetch failed: ${method} ${url}`, e);
        showToast(`Network error: ${e.message}`);
        // Return a mock Response so callers can safely call .json() / .text()
        return new Response(JSON.stringify({}), { status: 0, statusText: 'Network Error' });
    }
}

// --- HTML Escaping ---
function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escAttr(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"')
              .replace(/</g, '\\x3c').replace(/>/g, '\\x3e');
}

function extractDomain(url) {
    try { return new URL(url).hostname.replace('www.', ''); } catch { return ''; }
}

// --- Reusable Model Select HTML ---
function modelSelectHtml(id, defaultModel = 'claude-haiku-4-5-20251001') {
    return `<select id="${id}" class="model-select-inline">
        <option value="claude-haiku-4-5-20251001" ${defaultModel.includes('haiku') ? 'selected' : ''}>Haiku</option>
        <option value="claude-sonnet-4-5-20250929" ${defaultModel.includes('sonnet') ? 'selected' : ''}>Sonnet</option>
        <option value="claude-opus-4-6" ${defaultModel.includes('opus') ? 'selected' : ''}>Opus</option>
        <option disabled>──────────</option>
        <option value="gemini-2.0-flash" ${defaultModel.includes('gemini-2.0') ? 'selected' : ''}>Gemini Flash</option>
        <option value="gemini-2.5-pro" ${defaultModel.includes('gemini-2.5') ? 'selected' : ''}>Gemini Pro</option>
    </select>`;
}

// --- Relationship Labels ---
const RELATIONSHIP_LABELS = {
    watching: 'Watching',
    to_reach_out: 'To Reach Out',
    in_conversation: 'In Conversation',
    met: 'Met',
    partner: 'Partner',
    not_relevant: 'Not Relevant',
};

function relationshipLabel(status) {
    return RELATIONSHIP_LABELS[status] || status || '';
}

// --- Tab Navigation with URL State ---
function showTab(name) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(el => {
        el.classList.remove('active');
        el.setAttribute('aria-selected', 'false');
    });
    document.getElementById('tab-' + name).classList.add('active');

    const tabNames = ['companies', 'taxonomy', 'map', 'reports', 'canvas', 'discovery', 'process', 'export'];
    const idx = tabNames.indexOf(name);
    if (idx >= 0) {
        const tabBtn = document.querySelectorAll('.tab')[idx];
        if (tabBtn) {
            tabBtn.classList.add('active');
            tabBtn.setAttribute('aria-selected', 'true');
        }
    }

    // Update URL state without page reload
    const url = new URL(window.location);
    url.searchParams.set('tab', name);
    if (currentProjectId) url.searchParams.set('project', currentProjectId);
    window.history.replaceState({}, '', url);

    if (name === 'companies') loadCompanies();
    if (name === 'taxonomy') loadTaxonomy();
    if (name === 'map') loadMarketMap();
    if (name === 'reports') { loadSavedReports(); resumeActiveReport(); if (typeof loadSavedResearch === 'function') loadSavedResearch(); }
    if (name === 'canvas') { if (typeof loadCanvasList === 'function') loadCanvasList(); }
    if (name === 'discovery') { if (typeof loadDiscoveryTab === 'function') loadDiscoveryTab(); }
    if (name === 'process') { loadBatches(); if (typeof loadAiSetupStatus === 'function') loadAiSetupStatus(); }
    if (name === 'export') { loadShareTokens(); loadNotifPrefs(); }
}

// Restore tab from URL on load
function restoreTabFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    if (tab) showTab(tab);
}

// --- Collapsible Sections ---
function toggleSection(sectionId) {
    const body = document.getElementById(sectionId);
    const arrow = document.getElementById(sectionId + '-toggle');
    if (!body) return;
    body.classList.toggle('collapsed');
    if (arrow) arrow.classList.toggle('collapsed');
}

// --- Stats ---
async function loadStats() {
    const res = await safeFetch(`/api/stats?project_id=${currentProjectId}`);
    const stats = await res.json();
    document.getElementById('statCompanies').textContent = `${stats.total_companies} companies`;
    document.getElementById('statCategories').textContent = `${stats.total_categories} categories`;
    document.getElementById('statUpdated').textContent = stats.last_updated
        ? `Updated ${new Date(stats.last_updated).toLocaleDateString()}`
        : 'Never updated';
}

// --- Dark Mode ---
function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.innerHTML = `<span class="material-symbols-outlined">${next === 'dark' ? 'light_mode' : 'dark_mode'}</span>`;
    });
    if (window.mermaid) {
        mermaid.initialize({ startOnLoad: false, theme: next === 'dark' ? 'dark' : 'default', securityLevel: 'strict' });
    }
    // Re-render charts with new theme colors (always, not just on active tab)
    if (typeof refreshDashboardCharts === 'function') {
        refreshDashboardCharts();
    }
}

function initTheme() {
    const saved = localStorage.getItem('theme');
    if (saved === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
        document.querySelectorAll('.theme-toggle').forEach(btn => {
            btn.innerHTML = '<span class="material-symbols-outlined">light_mode</span>';
        });
    }
}

// --- Connection Heartbeat ---
let _heartbeatFails = 0;
const _HEARTBEAT_INTERVAL = 15000;  // 15s
const _HEARTBEAT_FAIL_THRESHOLD = 2;

function startHeartbeat() {
    setInterval(async () => {
        try {
            const res = await fetch('/healthz', { signal: AbortSignal.timeout(5000) });
            if (res.ok) {
                if (_heartbeatFails >= _HEARTBEAT_FAIL_THRESHOLD) {
                    document.getElementById('connectionBanner')?.classList.add('hidden');
                    showToast('Connection restored');
                }
                _heartbeatFails = 0;
            } else {
                _heartbeatFails++;
            }
        } catch {
            _heartbeatFails++;
        }
        if (_heartbeatFails >= _HEARTBEAT_FAIL_THRESHOLD) {
            document.getElementById('connectionBanner')?.classList.remove('hidden');
        }
    }, _HEARTBEAT_INTERVAL);
}

// --- Keyboard Shortcuts Overlay ---
function toggleShortcutsOverlay() {
    const overlay = document.getElementById('shortcutsOverlay');
    if (overlay) overlay.classList.toggle('hidden');
}

// --- Toast / Undo ---
let undoTimer = null;
let undoState = null;

function showToast(message, duration = 5000) {
    dismissToast();
    const toast = document.createElement('div');
    toast.className = 'undo-toast';
    toast.id = 'undoToast';
    toast.innerHTML = `
        <span>${esc(message)}</span>
        <span class="toast-dismiss" onclick="dismissToast()">&times;</span>
    `;
    document.body.appendChild(toast);
    setTimeout(() => dismissToast(), duration);
}

function showUndoToast(message, undoFn) {
    dismissToast();
    const toast = document.createElement('div');
    toast.className = 'undo-toast';
    toast.id = 'undoToast';
    toast.innerHTML = `
        <span>${esc(message)}</span>
        <button onclick="executeUndo()">Undo</button>
        <span class="toast-dismiss" onclick="dismissToast()">&times;</span>
    `;
    document.body.appendChild(toast);
    undoState = undoFn;
    undoTimer = setTimeout(() => dismissToast(), 8000);
}

function executeUndo() {
    if (undoState) {
        undoState();
        undoState = null;
    }
    dismissToast();
}

function dismissToast() {
    clearTimeout(undoTimer);
    undoTimer = null;
    undoState = null;
    const toast = document.getElementById('undoToast');
    if (toast) {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 300);
    }
}

// --- Focus Trap (for modals) ---
function trapFocus(container) {
    const focusable = container.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable.length) return null;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    function handler(e) {
        if (e.key !== 'Tab') return;
        if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
            if (document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }
    container.addEventListener('keydown', handler);
    first.focus();
    return () => container.removeEventListener('keydown', handler);
}

// --- Tab Loading States ---
function showTabLoading(tabName) {
    const tab = document.getElementById('tab-' + tabName);
    if (!tab || tab.querySelector('.tab-loading')) return;
    const loader = document.createElement('div');
    loader.className = 'tab-loading';
    loader.innerHTML = '<div class="tab-loading-spinner"></div><p>Loading...</p>';
    tab.prepend(loader);
}

function hideTabLoading(tabName) {
    const tab = document.getElementById('tab-' + tabName);
    if (!tab) return;
    const loader = tab.querySelector('.tab-loading');
    if (loader) loader.remove();
}
