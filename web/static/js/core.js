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
    return str.replace(/\\/g, '\\\\')
              .replace(/'/g, "\\'")
              .replace(/"/g, '\\"')
              .replace(/`/g, '\\`')
              .replace(/\$/g, '\\$')
              .replace(/</g, '\\x3c')
              .replace(/>/g, '\\x3e')
              .replace(/\n/g, '\\n')
              .replace(/\r/g, '\\r')
              .replace(/\u2028/g, '\\u2028')
              .replace(/\u2029/g, '\\u2029');
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
const LEGACY_TABS = ['companies', 'taxonomy', 'map', 'canvas'];
const ALL_TAB_NAMES = ['companies', 'taxonomy', 'map', 'reports', 'canvas', 'discovery', 'process', 'review', 'analysis', 'intelligence', 'export', 'settings'];

function showTab(name) {
    // Support numeric index for backward compat
    if (typeof name === 'number') {
        name = ALL_TAB_NAMES[name] || 'reports';
    }

    // Validate tab name
    if (!ALL_TAB_NAMES.includes(name)) return;

    // Ensure driver.js tour isn't blocking pointer events
    if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();

    // Deactivate all tab content panels
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));

    // Deactivate all tab buttons (primary bar + dropdown items)
    document.querySelectorAll('.tab[data-tab]').forEach(el => {
        el.classList.remove('active');
        el.setAttribute('aria-selected', 'false');
    });
    document.querySelectorAll('.tools-menu-item').forEach(el => el.classList.remove('active'));

    // Activate the target content panel
    const panel = document.getElementById('tab-' + name);
    if (panel) panel.classList.add('active');

    // Activate the correct button
    const isLegacy = LEGACY_TABS.includes(name);
    const trigger = document.getElementById('toolsTrigger');

    if (isLegacy) {
        // Highlight the dropdown menu item
        const menuItem = document.querySelector('.tools-menu-item[data-tab="' + name + '"]');
        if (menuItem) menuItem.classList.add('active');
        // Highlight the Tools trigger button
        if (trigger) {
            trigger.classList.add('active');
            trigger.setAttribute('aria-selected', 'true');
        }
    } else {
        // Standard primary tab
        const tabBtn = document.querySelector('.tab[data-tab="' + name + '"]');
        if (tabBtn) {
            tabBtn.classList.add('active');
            tabBtn.setAttribute('aria-selected', 'true');
        }
        // Clear Tools trigger active state
        if (trigger) {
            trigger.classList.remove('active');
            trigger.setAttribute('aria-selected', 'false');
        }
    }

    // Slide the tab indicator to the newly active tab
    updateTabIndicator();

    // Update URL state without page reload
    const url = new URL(window.location);
    url.searchParams.set('tab', name);
    if (currentProjectId) url.searchParams.set('project', currentProjectId);
    window.history.replaceState({}, '', url);

    if (name === 'companies') loadCompanies();
    if (name === 'taxonomy') loadTaxonomy();
    if (name === 'map') loadMarketMap();
    if (name === 'reports') { if (typeof loadSavedResearch === 'function') loadSavedResearch(); }
    if (name === 'canvas') { if (typeof loadCanvasList === 'function') loadCanvasList(); }
    if (name === 'discovery') { if (typeof loadDiscoveryTab === 'function') loadDiscoveryTab(); }
    if (name === 'process') { loadBatches(); if (typeof initCaptureUI === 'function') initCaptureUI(); }
    if (name === 'review') { if (typeof initReviewQueue === 'function') initReviewQueue(); if (typeof initFeatures === 'function') initFeatures(); }
    if (name === 'analysis') { if (typeof initLenses === 'function') initLenses(); }
    if (name === 'intelligence') { if (typeof initInsights === 'function') initInsights(); if (typeof initMonitoring === 'function') initMonitoring(); }
    if (name === 'export') { loadShareTokens(); loadNotifPrefs(); if (typeof initReports === 'function') initReports(); }
    if (name === 'settings') { if (typeof loadAiSetupStatus === 'function') loadAiSetupStatus(); if (typeof loadDefaultModel === 'function') loadDefaultModel(); }

    // Save app state on tab change
    if (typeof saveAppState === 'function') saveAppState();
}

// --- Tools Dropdown ---
function toggleToolsDropdown(e) {
    if (e) e.stopPropagation();
    const container = document.querySelector('.tools-dropdown');
    const menu = document.getElementById('toolsMenu');
    const triggerBtn = document.getElementById('toolsTrigger');
    if (!container || !menu) return;

    const isOpen = !menu.classList.contains('hidden');
    if (isOpen) {
        closeToolsDropdown();
    } else {
        menu.classList.remove('hidden');
        container.classList.add('open');
        if (triggerBtn) triggerBtn.setAttribute('aria-expanded', 'true');
        menu.querySelector('.tools-menu-item')?.focus();
        // Close on outside click (deferred so current click doesn't trigger it)
        setTimeout(() => document.addEventListener('click', _closeToolsOnOutsideClick), 0);
    }
}

function closeToolsDropdown() {
    const container = document.querySelector('.tools-dropdown');
    const menu = document.getElementById('toolsMenu');
    const triggerBtn = document.getElementById('toolsTrigger');
    if (menu) menu.classList.add('hidden');
    if (container) container.classList.remove('open');
    if (triggerBtn) triggerBtn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', _closeToolsOnOutsideClick);
}

function _closeToolsOnOutsideClick(e) {
    const dropdown = document.querySelector('.tools-dropdown');
    if (!dropdown || !dropdown.contains(e.target)) {
        closeToolsDropdown();
    }
}

// Keyboard nav within the tools dropdown
document.addEventListener('keydown', (e) => {
    const menu = document.getElementById('toolsMenu');
    if (!menu || menu.classList.contains('hidden')) return;

    if (e.key === 'Escape') {
        e.preventDefault();
        closeToolsDropdown();
        document.getElementById('toolsTrigger')?.focus();
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const items = [...menu.querySelectorAll('.tools-menu-item')];
        const current = items.indexOf(document.activeElement);
        const next = e.key === 'ArrowDown'
            ? (current + 1) % items.length
            : (current - 1 + items.length) % items.length;
        items[next]?.focus();
    } else if (e.key === 'Enter' && document.activeElement?.classList.contains('tools-menu-item')) {
        document.activeElement.click();
    }
});

// Restore tab from URL on load
function restoreTabFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    if (tab) showTab(tab);
}

// --- Sliding Tab Indicator ---
function updateTabIndicator() {
    // Find active tab in the main bar or the Tools trigger when a legacy tab is active
    const activeTab = document.querySelector('nav.tabs > .tab.active, nav.tabs > .tools-dropdown .tools-trigger.active');
    const tabsContainer = document.querySelector('.tabs');
    if (!activeTab || !tabsContainer) return;

    let indicator = tabsContainer.querySelector('.tab-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.className = 'tab-indicator';
        tabsContainer.appendChild(indicator);
    }

    indicator.style.left = activeTab.offsetLeft + 'px';
    indicator.style.width = activeTab.offsetWidth + 'px';
}
window.updateTabIndicator = updateTabIndicator;

// Debounced resize handler for tab indicator
let _resizeIndicatorTimer = null;
window.addEventListener('resize', () => {
    clearTimeout(_resizeIndicatorTimer);
    _resizeIndicatorTimer = setTimeout(updateTabIndicator, 100);
});

// Initialise indicator once DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Small delay so layout is fully settled (fonts loaded, flexbox computed)
    requestAnimationFrame(updateTabIndicator);
});

// --- Collapsible Sections ---
function toggleSection(sectionId) {
    const body = document.getElementById(sectionId);
    const arrow = document.getElementById(sectionId + '-toggle');
    if (!body) return;
    body.classList.toggle('collapsed');
    if (arrow) arrow.classList.toggle('collapsed');

    // Toggle aria-expanded on the header element that triggered the toggle
    const isCollapsed = body.classList.contains('collapsed');
    const header = document.querySelector(`[aria-controls="${sectionId}"]`);
    if (header) {
        header.setAttribute('aria-expanded', String(!isCollapsed));
    }
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

    // Also load entity stats if project has rich schema
    _loadEntityStatsForHeader();
}

async function _loadEntityStatsForHeader() {
    if (!currentProjectId) return;
    try {
        const res = await safeFetch(`/api/entity-stats?project_id=${currentProjectId}`);
        const entityStats = await res.json();
        const total = Object.values(entityStats).reduce((s, n) => s + n, 0);
        if (total > 0) {
            const parts = Object.entries(entityStats).map(([type, count]) => `${count} ${type}`);
            document.getElementById('statCompanies').textContent = parts.join(', ');
        }
    } catch (e) { /* entity stats are supplementary */ }
}

// --- Dark Mode ---
function toggleTheme() {
    const html = document.documentElement;
    const current = html.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    localStorage.setItem('lastThemeToggle', Date.now().toString());
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

// --- Native macOS-style Confirmation Dialog ---
/**
 * Native macOS-style confirmation dialog (replaces browser confirm())
 * @param {Object} options
 * @param {string} options.title - Dialog title
 * @param {string} options.message - Dialog message
 * @param {string} options.confirmText - Confirm button text (default: "Delete")
 * @param {string} options.cancelText - Cancel button text (default: "Cancel")
 * @param {string} options.type - "danger" or "warning" (default: "danger")
 * @returns {Promise<boolean>} - true if confirmed, false if cancelled
 */
window.showNativeConfirm = function({ title, message, confirmText = 'Delete', cancelText = 'Cancel', type = 'danger' } = {}) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('confirmSheet');
    if (!overlay) { resolve(confirm(message || title)); return; }

    const iconEl = document.getElementById('confirmSheetIcon');
    const titleEl = document.getElementById('confirmSheetTitle');
    const msgEl = document.getElementById('confirmSheetMessage');
    const confirmBtn = document.getElementById('confirmSheetConfirm');
    const cancelBtn = document.getElementById('confirmSheetCancel');

    titleEl.textContent = title || 'Are you sure?';
    msgEl.textContent = message || 'This action cannot be undone.';
    confirmBtn.textContent = confirmText;
    cancelBtn.textContent = cancelText;

    // Set icon and button style based on type
    iconEl.className = 'confirm-sheet-icon ' + type;
    iconEl.textContent = type === 'danger' ? '\u26a0\ufe0f' : '\u26a1';
    confirmBtn.className = type === 'danger' ? 'confirm-btn-danger' : 'confirm-btn-primary';

    overlay.style.display = 'flex';
    // Trigger animation
    requestAnimationFrame(() => { overlay.classList.add('visible'); });

    function cleanup() {
      overlay.classList.remove('visible');
      setTimeout(() => { overlay.style.display = 'none'; }, 200);
      confirmBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onKey);
    }

    function onConfirm() { cleanup(); resolve(true); }
    function onCancel() { cleanup(); resolve(false); }
    function onKey(e) {
      if (e.key === 'Escape') { onCancel(); }
      else if (e.key === 'Enter') { onConfirm(); }
    }

    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
    document.addEventListener('keydown', onKey);

    // Focus the cancel button (safer default like macOS)
    cancelBtn.focus();
  });
};

/**
 * Show a prompt dialog (replaces native prompt() which is blocked by pywebview).
 * Creates its DOM on first use, reuses thereafter.
 *
 * Supports two calling patterns:
 *   Callback:  showPromptDialog(title, placeholder, callback, confirmText)
 *   Promise:   const val = await showPromptDialog(title, placeholder, defaultValue, confirmText)
 *
 * The 3rd argument is inspected: if it is a function the callback pattern is used,
 * otherwise it is treated as a default value and the function returns a Promise.
 * If the 3rd arg is a non-function default value and the 4th arg IS a function,
 * the 4th arg is used as a callback (for mixed patterns).
 *
 * @param {string} title - Dialog title
 * @param {string} placeholder - Input placeholder text
 * @param {function|string} callbackOrDefault - Callback function OR default input value
 * @param {string|function} confirmTextOrCallback - Confirm button label OR callback (when 3rd arg is default value)
 * @returns {Promise<string|null>|undefined} Promise when used without callback
 */
window.showPromptDialog = function(title, placeholder, callbackOrDefault, confirmTextOrCallback) {
  // Determine calling pattern
  const arg3IsFunction = typeof callbackOrDefault === 'function';
  const arg4IsFunction = typeof confirmTextOrCallback === 'function';

  let defaultValue, callback, confirmText;

  if (arg3IsFunction) {
    // Classic callback pattern: showPromptDialog(title, placeholder, callback, confirmText)
    defaultValue = '';
    callback = callbackOrDefault;
    confirmText = confirmTextOrCallback || 'OK';
  } else if (arg4IsFunction) {
    // Mixed pattern: showPromptDialog(title, placeholder, defaultValue, callback)
    defaultValue = callbackOrDefault || '';
    callback = confirmTextOrCallback;
    confirmText = 'OK';
  } else {
    // Promise pattern: showPromptDialog(title, placeholder, defaultValue, confirmText)
    defaultValue = callbackOrDefault || '';
    callback = null;
    confirmText = confirmTextOrCallback || 'OK';
  }

  function _showDialog(resolve) {
    _ensurePromptDialogSheet();
    const overlay = document.getElementById('promptDialogSheet');
    const titleEl = document.getElementById('promptDialogTitle');
    const input = document.getElementById('promptDialogInput');
    const confirmBtn = document.getElementById('promptDialogConfirm');
    const cancelBtn = document.getElementById('promptDialogCancel');

    titleEl.textContent = title || 'Enter a value';
    input.value = defaultValue;
    input.placeholder = placeholder || '';
    confirmBtn.textContent = confirmText;

    overlay.style.display = 'flex';
    requestAnimationFrame(() => { overlay.classList.add('visible'); input.focus(); });

    function cleanup() {
      overlay.classList.remove('visible');
      setTimeout(() => { overlay.style.display = 'none'; }, 200);
      confirmBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click', onCancel);
      input.removeEventListener('keydown', onKey);
    }
    function onConfirm() {
      const v = input.value.trim();
      cleanup();
      if (callback) callback(v || null);
      resolve(v || null);
    }
    function onCancel() {
      cleanup();
      if (callback) callback(null);
      resolve(null);
    }
    function onKey(e) {
      if (e.key === 'Enter') { onConfirm(); }
      else if (e.key === 'Escape') { onCancel(); }
    }
    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
    input.addEventListener('keydown', onKey);
  }

  return new Promise(_showDialog);
};

/**
 * Show a select dialog with a dropdown of options (replaces native prompt() for constrained choices).
 * Creates its DOM on first use, reuses thereafter.
 * @param {string} title - Dialog title
 * @param {Array<{value:string, label:string}|string>} options - Options for the select
 * @param {function} callback - Called with selected value string on submit, null on cancel
 * @param {string} confirmText - Submit button label (default: "OK")
 */
window.showSelectDialog = function(title, options, callback, confirmText) {
  _ensureSelectDialogSheet();
  const overlay = document.getElementById('selectDialogSheet');
  const titleEl = document.getElementById('selectDialogTitle');
  const select = document.getElementById('selectDialogSelect');
  const confirmBtn = document.getElementById('selectDialogConfirm');
  const cancelBtn = document.getElementById('selectDialogCancel');

  titleEl.textContent = title || 'Select an option';
  confirmBtn.textContent = confirmText || 'OK';

  // Build options
  select.innerHTML = '<option value="" disabled selected>Choose...</option>';
  (options || []).forEach(opt => {
    const o = document.createElement('option');
    if (typeof opt === 'string') { o.value = opt; o.textContent = opt.replace(/_/g, ' '); }
    else { o.value = opt.value; o.textContent = opt.label; }
    select.appendChild(o);
  });

  overlay.style.display = 'flex';
  requestAnimationFrame(() => { overlay.classList.add('visible'); select.focus(); });

  function cleanup() {
    overlay.classList.remove('visible');
    setTimeout(() => { overlay.style.display = 'none'; }, 200);
    confirmBtn.removeEventListener('click', onConfirm);
    cancelBtn.removeEventListener('click', onCancel);
    document.removeEventListener('keydown', onKey);
  }
  function onConfirm() { const v = select.value; cleanup(); callback(v || null); }
  function onCancel() { cleanup(); callback(null); }
  function onKey(e) {
    if (e.key === 'Escape') { onCancel(); }
    else if (e.key === 'Enter') { onConfirm(); }
  }
  confirmBtn.addEventListener('click', onConfirm);
  cancelBtn.addEventListener('click', onCancel);
  document.addEventListener('keydown', onKey);
};

/** Lazily create prompt dialog DOM */
function _ensurePromptDialogSheet() {
  if (document.getElementById('promptDialogSheet')) return;
  const html = `<div id="promptDialogSheet" class="confirm-sheet-overlay" style="display:none;">
    <div class="confirm-sheet" style="border-radius:0;">
      <div id="promptDialogTitle" class="confirm-sheet-title"
           style="font-family:'Plus Jakarta Sans',sans-serif;font-weight:600;">Enter a value</div>
      <input id="promptDialogInput" type="text" autocomplete="off"
             class="prompt-dialog-input" />
      <div class="confirm-sheet-actions" style="margin-top:16px;">
        <button id="promptDialogConfirm" class="confirm-btn-primary" style="border-radius:0;">OK</button>
        <button id="promptDialogCancel" class="confirm-btn-cancel" style="border-radius:0;">Cancel</button>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
}

/** Lazily create select dialog DOM */
function _ensureSelectDialogSheet() {
  if (document.getElementById('selectDialogSheet')) return;
  const html = `<div id="selectDialogSheet" class="confirm-sheet-overlay" style="display:none;">
    <div class="confirm-sheet" style="border-radius:0;">
      <div id="selectDialogTitle" class="confirm-sheet-title"
           style="font-family:'Plus Jakarta Sans',sans-serif;font-weight:600;">Select an option</div>
      <select id="selectDialogSelect" class="select-dialog-select">
        <option value="" disabled selected>Choose...</option>
      </select>
      <div class="confirm-sheet-actions" style="margin-top:16px;">
        <button id="selectDialogConfirm" class="confirm-btn-primary" style="border-radius:0;">OK</button>
        <button id="selectDialogCancel" class="confirm-btn-cancel" style="border-radius:0;">Cancel</button>
      </div>
    </div>
  </div>`;
  document.body.insertAdjacentHTML('beforeend', html);
}

// --- App-wide Undo/Redo System ---
window._undoStack = [];
window._redoStack = [];
const MAX_UNDO = 30;

/**
 * Push an undoable action onto the stack
 * @param {string} description - Human-readable description
 * @param {Function} undoFn - Function to call on undo
 * @param {Function} redoFn - Function to call on redo
 */
window.pushUndoAction = function(description, undoFn, redoFn) {
  window._undoStack.push({ description, undoFn, redoFn, timestamp: Date.now() });
  if (window._undoStack.length > MAX_UNDO) window._undoStack.shift();
  window._redoStack = []; // Clear redo on new action
};

window.performUndo = function() {
  const action = window._undoStack.pop();
  if (!action) { showToast('Nothing to undo', 'info'); return; }
  try {
    action.undoFn();
    window._redoStack.push(action);
    showToast(`Undid: ${action.description}`, 'info');
  } catch (e) {
    console.error('Undo failed:', e);
    showToast('Undo failed', 'error');
  }
};

window.performRedo = function() {
  const action = window._redoStack.pop();
  if (!action) { showToast('Nothing to redo', 'info'); return; }
  try {
    action.redoFn();
    window._undoStack.push(action);
    showToast(`Redid: ${action.description}`, 'info');
  } catch (e) {
    console.error('Redo failed:', e);
    showToast('Redo failed', 'error');
  }
};

// --- State Restoration ---
window.saveAppState = function() {
  // Determine active tab name from data-tab attribute or tools menu
  const activeTabName = document.querySelector('.tab.active[data-tab]')?.dataset?.tab
      || document.querySelector('.tools-menu-item.active')?.dataset?.tab
      || 'reports';
  const state = {
    activeTabName: activeTabName,
    scrollPositions: {},
    currentView: window.currentCompanyView || 'table',
    sortField: window.currentSort?.field,
    sortDir: window.currentSort?.direction,
    detailOpen: !!document.querySelector('.detail-panel.active, .detail-panel.open, .detail-panel:not([style*="display: none"])'),
    timestamp: Date.now()
  };

  // Save scroll positions for scrollable containers
  document.querySelectorAll('.company-list, .category-list, .detail-panel').forEach(el => {
    if (el.id) state.scrollPositions[el.id] = el.scrollTop;
  });

  try { localStorage.setItem('appState', JSON.stringify(state)); } catch(e) {}
};

window.restoreAppState = function() {
  try {
    const state = JSON.parse(localStorage.getItem('appState'));
    if (!state || Date.now() - state.timestamp > 86400000) return; // Expire after 24h

    // Restore tab (name-based, with backward compat for old tabIndex format)
    const restoreTab = state.activeTabName || (typeof state.tabIndex === 'number' ? ALL_TAB_NAMES[state.tabIndex] : null);
    if (restoreTab) {
      setTimeout(() => {
        if (typeof showTab === 'function') showTab(restoreTab);
      }, 100);
    }

    // Restore view mode
    if (state.currentView && window.currentCompanyView !== undefined) {
      window.currentCompanyView = state.currentView;
    }

    // Restore scroll positions after render
    setTimeout(() => {
      if (state.scrollPositions) {
        Object.entries(state.scrollPositions).forEach(([id, pos]) => {
          const el = document.getElementById(id);
          if (el) el.scrollTop = pos;
        });
      }
    }, 300);
  } catch(e) {}
};

// --- About Dialog ---
window.showAboutDialog = function() {
  const versionEl = document.getElementById('aboutVersion');
  const pythonEl = document.getElementById('aboutPython');
  if (versionEl) {
    const version = window.APP_VERSION || document.querySelector('[data-app-version]')?.dataset?.appVersion || '1.1.0';
    versionEl.textContent = 'Version ' + version;
  }
  if (pythonEl) {
    pythonEl.textContent = '3.14';
  }
  document.getElementById('aboutModal')?.classList.remove('hidden');
};

// --- Dark Mode System Sync ---
if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    const systemWantsDark = e.matches;
    // Only auto-switch if user hasn't explicitly set a preference recently
    const lastManualToggle = parseInt(localStorage.getItem('lastThemeToggle') || '0');
    if (Date.now() - lastManualToggle > 3600000) { // 1 hour since manual toggle
      document.documentElement.setAttribute('data-theme', systemWantsDark ? 'dark' : 'light');
      localStorage.setItem('theme', systemWantsDark ? 'dark' : 'light');
      document.querySelectorAll('.theme-toggle').forEach(btn => {
        btn.innerHTML = `<span class="material-symbols-outlined">${systemWantsDark ? 'light_mode' : 'dark_mode'}</span>`;
      });
    }
  });
}

// ========== Native File Dialogs (desktop mode) ==========

/**
 * Open a native macOS file picker when in desktop mode, falling back to HTML input.
 * @param {string[]} fileTypes - Filter descriptions, e.g. ["CSV files (*.csv)"]
 * @param {boolean} multiple - Allow multiple file selection
 * @returns {Promise<FileList|string[]|null>} File objects (web) or file paths (native)
 */
async function nativeFileDialog(fileTypes, multiple = false) {
    if (window.pywebview?.api?.open_file_dialog) {
        try {
            const paths = await window.pywebview.api.open_file_dialog(fileTypes || null, multiple);
            return paths;  // Returns array of file paths
        } catch (e) {
            console.debug('Native file dialog failed, falling back to HTML:', e);
        }
    }
    // Fallback: HTML file input
    return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        if (multiple) input.multiple = true;
        input.onchange = () => resolve(input.files?.length ? input.files : null);
        input.click();
    });
}

/**
 * Open a native macOS save dialog when in desktop mode.
 * @param {string} filename - Default filename
 * @param {string[]} fileTypes - Filter descriptions
 * @returns {Promise<string|null>} File path or null
 */
async function nativeSaveDialog(filename, fileTypes) {
    if (window.pywebview?.api?.save_file_dialog) {
        try {
            return await window.pywebview.api.save_file_dialog(filename, fileTypes || null);
        } catch (e) {
            console.debug('Native save dialog failed:', e);
        }
    }
    return null;
}

// ========== Drag-Drop File Import ==========
(function setupDragDrop() {
  let dragCounter = 0;
  const dropOverlay = document.createElement('div');
  dropOverlay.id = 'dropOverlay';
  dropOverlay.innerHTML = '<div class="drop-overlay-content"><div class="drop-icon">📥</div><div class="drop-text">Drop file to import</div><div class="drop-hint">Supports CSV and JSON files</div></div>';
  dropOverlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.3);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px);z-index:9999;display:none;align-items:center;justify-content:center;';
  dropOverlay.querySelector('.drop-overlay-content').style.cssText = 'background:var(--bg-primary,#fff);border-radius:16px;padding:40px 60px;text-align:center;box-shadow:0 20px 60px rgba(0,0,0,0.3);border:2px dashed var(--accent-primary,#bc6c5a);';
  dropOverlay.querySelector('.drop-icon').style.cssText = 'font-size:48px;margin-bottom:12px;';
  dropOverlay.querySelector('.drop-text').style.cssText = 'font-size:18px;font-weight:600;color:var(--text-primary,#333);';
  dropOverlay.querySelector('.drop-hint').style.cssText = 'font-size:13px;color:var(--text-secondary,#666);margin-top:4px;';
  document.body.appendChild(dropOverlay);

  document.addEventListener('dragenter', (e) => {
    e.preventDefault();
    dragCounter++;
    if (e.dataTransfer && e.dataTransfer.types.includes('Files')) {
      dropOverlay.style.display = 'flex';
    }
  });

  document.addEventListener('dragleave', (e) => {
    e.preventDefault();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      dropOverlay.style.display = 'none';
    }
  });

  document.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
  });

  document.addEventListener('drop', async (e) => {
    e.preventDefault();
    dragCounter = 0;
    dropOverlay.style.display = 'none';

    const files = e.dataTransfer?.files;
    if (!files || files.length === 0) return;

    const file = files[0];
    const ext = file.name.split('.').pop().toLowerCase();

    if (ext === 'csv' || ext === 'json') {
      try {
        const text = await file.text();
        // Send to server for processing
        const resp = await safeFetch('/api/import/file', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: file.name, content: text, type: ext })
        });
        if (resp.ok) {
          const result = await resp.json();
          showToast(`Imported ${result.count || 0} companies from ${file.name}`, 'success');
          if (typeof loadCompanies === 'function') loadCompanies();
        } else {
          const err = await resp.json().catch(() => ({}));
          showToast(err.error || `Failed to import ${file.name}`, 'error');
        }
      } catch (err) {
        showToast(`Error reading file: ${err.message}`, 'error');
      }
    } else {
      showToast('Unsupported file type. Please drop a CSV or JSON file.', 'warning');
    }
  });
})();

// ========== Window Focus/Blur Handling ==========
window._appFocused = true;

document.addEventListener('visibilitychange', () => {
  window._appFocused = !document.hidden;

  if (typeof onWindowFocusChange === 'function') {
    onWindowFocusChange(!document.hidden);
  }

  // Notify pywebview desktop API if available
  if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.on_focus_change === 'function') {
    window.pywebview.api.on_focus_change(!document.hidden);
  }

  if (!document.hidden) {
    // Window regained focus — refresh data if stale
    if (typeof loadCompanies === 'function' && window._lastFocusLoss) {
      const elapsed = Date.now() - window._lastFocusLoss;
      if (elapsed > 60000) { // More than 1 minute away
        loadCompanies();
      }
    }
  } else {
    window._lastFocusLoss = Date.now();
  }
});

// ========== Native Context Menus (desktop mode) ==========

document.addEventListener('contextmenu', function(e) {
    if (!window.pywebview?.api?.show_context_menu) return;
    // Don't intercept on editable elements
    if (e.target.matches('input, textarea, [contenteditable="true"]')) return;

    const items = _buildContextMenuItems(e.target);
    if (!items || items.length === 0) return;

    e.preventDefault();
    window.pywebview.api.show_context_menu(
        JSON.stringify(items),
        e.clientX,
        e.clientY
    );
});

function _buildContextMenuItems(target) {
    // Entity table row
    const entityRow = target.closest('tr[data-entity-id], tr[data-id]');
    if (entityRow) {
        const id = entityRow.dataset.entityId || entityRow.dataset.id;
        return [
            { label: 'Open', action: 'entity_open', id: id },
            { label: 'Capture Evidence', action: 'entity_capture', id: id },
            { separator: true },
            { label: 'Copy Name', action: 'entity_copy_name', id: id },
            { separator: true },
            { label: 'Delete', action: 'entity_delete', id: id },
        ];
    }
    // Evidence card
    const evidenceCard = target.closest('[data-evidence-id]');
    if (evidenceCard) {
        const id = evidenceCard.dataset.evidenceId;
        return [
            { label: 'View', action: 'evidence_view', id: id },
            { label: 'Download', action: 'evidence_download', id: id },
            { separator: true },
            { label: 'Delete', action: 'evidence_delete', id: id },
        ];
    }
    // Tab right-click
    const tab = target.closest('.tab[data-tab]');
    if (tab) {
        const tabName = tab.dataset.tab;
        return [
            { label: 'Reload Tab', action: 'tab_reload', id: tabName },
        ];
    }
    // Project card
    const projectCard = target.closest('[data-project-id]');
    if (projectCard) {
        const id = projectCard.dataset.projectId;
        return [
            { label: 'Open Project', action: 'project_open', id: id },
            { separator: true },
            { label: 'Delete Project', action: 'project_delete', id: id },
        ];
    }
    return null;
}

window._handleContextMenuAction = function(action, id) {
    switch (action) {
        case 'entity_open':
            if (typeof showEntityDetail === 'function') showEntityDetail(parseInt(id));
            break;
        case 'entity_capture':
            showTab('process');
            break;
        case 'entity_copy_name': {
            const row = document.querySelector(`tr[data-entity-id="${id}"], tr[data-id="${id}"]`);
            if (row) {
                const name = row.querySelector('td:first-child')?.textContent?.trim();
                if (name) navigator.clipboard.writeText(name);
            }
            break;
        }
        case 'entity_delete':
            if (typeof deleteEntity === 'function') deleteEntity(parseInt(id));
            break;
        case 'evidence_view':
            // Open evidence viewer if available
            break;
        case 'evidence_download':
            window.open(`/api/evidence/${id}/download`, '_blank');
            break;
        case 'evidence_delete':
            if (typeof deleteEvidence === 'function') deleteEvidence(parseInt(id));
            break;
        case 'tab_reload':
            showTab(id);
            break;
        case 'project_open':
            if (typeof selectProject === 'function') selectProject(parseInt(id));
            break;
        case 'project_delete':
            if (typeof deleteProject === 'function') deleteProject(parseInt(id));
            break;
    }
};

// ========== Share Functionality ==========
window.shareData = async function(data) {
  // data: { title, text, url }
  if (navigator.share) {
    try {
      await navigator.share(data);
      return;
    } catch (e) {
      if (e.name === 'AbortError') return; // User cancelled
    }
  }

  // Fallback: copy to clipboard
  const shareText = [data.title, data.text, data.url].filter(Boolean).join('\n');
  try {
    await navigator.clipboard.writeText(shareText);
    showToast('Copied to clipboard for sharing', 'success');
  } catch (e) {
    showToast('Failed to share', 'error');
  }
};

// Share current company
window.shareCompany = async function(companyId) {
  try {
    const resp = await safeFetch(`/api/companies/${companyId}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const company = data.company || data;

    await shareData({
      title: company.name,
      text: company.description || `${company.name} — ${company.category_name || 'Uncategorized'}`,
      url: company.url || ''
    });
  } catch (e) {
    showToast('Failed to share company', 'error');
  }
};

// Share current project summary
window.shareProject = async function() {
  if (!window.currentProjectId) return;
  try {
    const resp = await safeFetch(`/api/projects/${window.currentProjectId}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const project = data.project || data;

    await shareData({
      title: project.name,
      text: `${project.name} — ${project.description || 'Market research project'}\n${project.company_count || 0} companies, ${project.category_count || 0} categories`
    });
  } catch (e) {
    showToast('Failed to share project', 'error');
  }
};

// ========== Lucide Icons ==========
function initLucideIcons() {
    if (window.lucide) {
        lucide.createIcons();
    }
}
// Call after DOMContentLoaded and after any dynamic HTML insertion

function getIcon(name, size = 16) {
    if (!window.lucide) return '';
    return `<i data-lucide="${name}" style="width:${size}px;height:${size}px;display:inline-block;vertical-align:middle;"></i>`;
}
window.getIcon = getIcon;

// ========== ninja-keys Command Palette ==========
function initCommandPalette() {
    const ninja = document.querySelector('ninja-keys');
    if (!ninja) return;

    const actions = [
        // Navigation (primary workbench tabs)
        { id: 'tab-research', title: 'Go to Research', section: 'Navigation', handler: () => showTab('reports') },
        { id: 'tab-process', title: 'Go to Process', section: 'Navigation', handler: () => showTab('process') },
        { id: 'tab-review', title: 'Go to Review', section: 'Navigation', handler: () => showTab('review') },
        { id: 'tab-analysis', title: 'Go to Analysis', section: 'Navigation', handler: () => showTab('analysis') },
        { id: 'tab-intelligence', title: 'Go to Intelligence', section: 'Navigation', handler: () => showTab('intelligence') },
        { id: 'tab-export', title: 'Go to Export', section: 'Navigation', handler: () => showTab('export') },
        // Tools (legacy tabs)
        { id: 'tab-companies', title: 'Go to Companies', section: 'Tools', handler: () => showTab('companies') },
        { id: 'tab-taxonomy', title: 'Go to Taxonomy', section: 'Tools', handler: () => showTab('taxonomy') },
        { id: 'tab-map', title: 'Go to Map', section: 'Tools', handler: () => showTab('map') },
        { id: 'tab-canvas', title: 'Go to Canvas', section: 'Tools', handler: () => showTab('canvas') },
        // Actions
        { id: 'new-project', title: 'New Project', section: 'Actions', handler: () => document.querySelector('[onclick*="newProject"]')?.click() },
        { id: 'search', title: 'Search Entities', section: 'Actions', handler: () => { showTab('companies'); document.getElementById('searchInput')?.focus(); } },
        { id: 'export-pdf', title: 'Export as PDF', section: 'Export', handler: () => { showTab('export'); } },
        { id: 'export-excel', title: 'Export as Excel', section: 'Export', handler: () => { showTab('export'); } },
        { id: 'toggle-theme', title: 'Toggle Dark Mode', section: 'Preferences', handler: () => toggleTheme() },
        { id: 'tab-settings', title: 'Settings', section: 'Preferences', handler: () => showTab('settings') },
        { id: 'shortcuts', title: 'Show Keyboard Shortcuts', section: 'Help', handler: () => document.getElementById('shortcutsOverlay')?.style.display === 'flex' ? null : document.getElementById('shortcutsOverlay').style.display = 'flex' },
    ];

    ninja.data = actions;

    // Style the command palette to match The Instrument
    ninja.classList.add('instrument-palette');
}

// ========== SortableJS Drag-to-Reorder ==========
function initSortable() {
    if (!window.Sortable) return;

    // Make category lists sortable
    document.querySelectorAll('.sortable-list').forEach(el => {
        Sortable.create(el, {
            animation: 100,
            ghostClass: 'sortable-ghost',
            handle: '.drag-handle',
            onEnd: function(evt) {
                // Persist new order via API
                const items = [...el.children].map((child, i) => ({
                    id: child.dataset.id,
                    sort_order: i,
                }));
                safeFetch('/api/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ items }),
                });
            },
        });
    });
}

// ========== Driver.js Onboarding Tour ==========
function _cleanupDriverJs() {
    // Ensure driver.js classes are removed from body (they set pointer-events: none on everything)
    document.body.classList.remove('driver-active', 'driver-simple', 'driver-fade');
    document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
}

function startOnboardingTour() {
    if (!window.driver) return;
    // Store on window so it can be destroyed externally
    window.driverObj = window.driver.js.driver({
        showProgress: true,
        animate: false, // The Instrument: no animation
        overlayColor: 'rgba(0,0,0,0.5)',
        popoverClass: 'instrument-popover',
        onDestroyed: _cleanupDriverJs,
        onDestroyStarted: _cleanupDriverJs,
        steps: [
            { element: '.tabs', popover: { title: 'Workflow', description: 'Follow the guided research flow: Research, Process, Review, Analysis, Intelligence, Export.' } },
            { element: '.tools-dropdown', popover: { title: 'Tools', description: 'Legacy views (Companies, Taxonomy, Map, Canvas) are available here.' } },
            { element: '#searchInput', popover: { title: 'Search', description: 'Find entities by name, category, or description. Supports fuzzy matching.' } },
            { popover: { title: 'Keyboard Shortcuts', description: 'Press Cmd+K for the command palette. Press ? for all shortcuts.' } },
        ],
    });
    window.driverObj.drive();
}
// Tour is manual-only: triggered via command palette ("Start Product Tour") or ? button.
// Auto-start removed — pywebview uses a dynamic port each launch so localStorage
// is never persisted, causing the tour to show on every single launch.

// ========== Choices.js Enhanced Dropdowns ==========
function initChoicesDropdowns() {
    if (!window.Choices) return;
    document.querySelectorAll('select.enhanced-select').forEach(el => {
        new Choices(el, {
            searchEnabled: true,
            itemSelectText: '',
            classNames: { containerOuter: 'choices instrument-choices' },
            shouldSort: false,
        });
    });
}

// ========== Tippy.js Tooltips ==========
function initTooltips() {
    if (typeof tippy === 'undefined') return;
    // Generic data-tippy-content elements (from integrations)
    tippy('[data-tippy-content]', { theme: 'light-border', placement: 'top', animation: 'fade', delay: [300, 0] });
    // Find all buttons with aria-label that contain only an icon (no visible text)
    document.querySelectorAll('button[aria-label]').forEach(btn => {
        // Skip if already has a tippy instance
        if (btn._tippy) return;
        // Check if button has no visible text (only icon children)
        const textContent = Array.from(btn.childNodes)
            .filter(n => n.nodeType === Node.TEXT_NODE)
            .map(n => n.textContent.trim())
            .join('');
        const hasVisibleText = textContent.length > 0 && textContent !== '\u00d7'; // exclude &times; symbol
        // Also check for text outside of material-symbols-outlined spans
        const iconSpans = btn.querySelectorAll('.material-symbols-outlined');
        const allSpans = btn.querySelectorAll('span');
        const isIconOnly = (iconSpans.length > 0 && iconSpans.length === allSpans.length && !hasVisibleText) ||
                           (!hasVisibleText && btn.classList.contains('icon-btn')) ||
                           (!hasVisibleText && btn.classList.contains('theme-toggle')) ||
                           (!hasVisibleText && btn.classList.contains('chat-fab')) ||
                           (!hasVisibleText && btn.classList.contains('close-btn')) ||
                           (!hasVisibleText && btn.classList.contains('back-btn'));
        if (!isIconOnly) return;
        tippy(btn, {
            content: btn.getAttribute('aria-label'),
            placement: 'bottom',
            theme: 'instrument',
        });
    });
}

// --- State Save Hooks ---
window.addEventListener('beforeunload', saveAppState);
setInterval(saveAppState, 5000);
