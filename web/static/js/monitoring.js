/**
 * Monitoring / Intelligence — Market Radar dashboard.
 * Shows monitors, change feed, and aggregate stats for a project.
 *
 * Entry point: initMonitoring() — called when the Intelligence tab is shown.
 *
 * API prefix: /api/monitoring/...
 */

// ── State ────────────────────────────────────────────────────────
let _monitoringStats = null;
let _monitoringFeed = [];
let _monitoringMonitors = [];
let _monitoringFeedOffset = 0;
let _monitoringFeedLimit = 50;
let _monitoringFeedFilters = {};   // {change_type, severity, is_read}
let _monitoringFeedHasMore = false;
let _monitoringCheckingAll = false;
let _monitoringEntities = null;    // cached entity list for forms

// ── Initialisation ───────────────────────────────────────────────

/**
 * Main entry point. Loads stats, feed, and monitors in parallel,
 * then renders the full dashboard.
 */
async function initMonitoring() {
    if (!currentProjectId) return;

    const container = document.getElementById('monitoringDashboard');
    if (!container) return;

    // Show skeleton while loading
    _renderMonitoringSkeleton(container);

    // Reset pagination state
    _monitoringFeedOffset = 0;
    _monitoringFeedHasMore = false;

    await Promise.all([
        _loadMonitoringStats(),
        _loadChangeFeed(),
        _loadMonitors(),
    ]);
}

// ── Desktop Badge Bridge ─────────────────────────────────────────

/**
 * Push monitoring alert count and recent changes to the desktop menu bar
 * status item (if running inside pywebview desktop app).
 */
function _updateDesktopBadge() {
    if (!window.pywebview?.api?.update_monitoring_badge) return;
    try {
        const alertCount = (_monitoringStats && _monitoringStats.unread_changes) || 0;
        const recentChanges = (_monitoringFeed || []).slice(0, 5).map(item => ({
            entity: item.entity_name || '',
            summary: item.title || item.summary || '',
        }));
        window.pywebview.api.update_monitoring_badge(
            alertCount,
            JSON.stringify(recentChanges)
        );
    } catch (e) {
        // Silent fallback — desktop API may not be available
    }
}

// ── Stats ────────────────────────────────────────────────────────

async function _loadMonitoringStats() {
    if (!currentProjectId) return;
    try {
        const resp = await safeFetch(`/api/monitoring/stats?project_id=${currentProjectId}`);
        if (!resp.ok) return;
        _monitoringStats = await resp.json();
        _renderMonitoringStats();
        _updateDesktopBadge();
    } catch (e) {
        console.warn('Failed to load monitoring stats:', e);
    }
}

function _renderMonitoringStats() {
    const el = document.getElementById('monitoringStatsBar');
    if (!el || !_monitoringStats) return;

    const s = _monitoringStats;
    const totalMonitors = s.total_monitors || 0;
    const totalChanges = s.total_changes || 0;
    const unreadChanges = s.unread_changes || 0;
    const activeMonitors = s.active_monitors || 0;
    const lastCheckTime = s.last_check_time ? _relativeTime(s.last_check_time) : 'never';

    el.innerHTML = `
        <div class="mon-stat">
            <span class="mon-stat-value">${totalMonitors}</span>
            <span class="mon-stat-label">Monitors</span>
        </div>
        <div class="mon-stat">
            <span class="mon-stat-value">${totalChanges}</span>
            <span class="mon-stat-label">Changes</span>
        </div>
        <div class="mon-stat ${unreadChanges > 0 ? 'mon-stat-highlight' : ''}">
            <span class="mon-stat-value">${unreadChanges}</span>
            <span class="mon-stat-label">Unread</span>
        </div>
        <div class="mon-stat">
            <span class="mon-stat-value">${activeMonitors}</span>
            <span class="mon-stat-label">Active</span>
        </div>
        <div class="mon-stat">
            <span class="mon-stat-value mon-stat-value-sm">${lastCheckTime}</span>
            <span class="mon-stat-label">Last Check</span>
        </div>
    `;
}

// ── Change Feed ──────────────────────────────────────────────────

async function _loadChangeFeed(append) {
    if (!currentProjectId) return;

    if (!append) {
        _monitoringFeedOffset = 0;
    }

    let url = `/api/monitoring/feed?project_id=${currentProjectId}&limit=${_monitoringFeedLimit}&offset=${_monitoringFeedOffset}`;

    if (_monitoringFeedFilters.change_type) {
        url += `&change_type=${encodeURIComponent(_monitoringFeedFilters.change_type)}`;
    }
    if (_monitoringFeedFilters.severity) {
        url += `&severity=${encodeURIComponent(_monitoringFeedFilters.severity)}`;
    }
    if (_monitoringFeedFilters.is_read !== undefined && _monitoringFeedFilters.is_read !== null) {
        url += `&is_read=${_monitoringFeedFilters.is_read}`;
    }

    try {
        const resp = await safeFetch(url);
        if (!resp.ok) return;
        const data = await resp.json();
        const items = data.items || data.feed || data || [];

        if (append) {
            _monitoringFeed = _monitoringFeed.concat(items);
        } else {
            _monitoringFeed = items;
        }

        _monitoringFeedHasMore = items.length >= _monitoringFeedLimit;
        _renderChangeFeed();
        _updateDesktopBadge();
    } catch (e) {
        console.warn('Failed to load change feed:', e);
    }
}

function _renderChangeFeed() {
    const container = document.getElementById('monitoringFeed');
    const emptyEl = document.getElementById('monitoringFeedEmpty');
    if (!container) return;

    // Render filter bar
    _renderFeedFilterBar();

    if (!_monitoringFeed || _monitoringFeed.length === 0) {
        container.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    container.innerHTML = _monitoringFeed.map((item, idx) => {
        const isUnread = !item.is_read;
        const severity = (item.severity || 'info').toLowerCase();
        const changeType = item.change_type || 'unknown';
        const entityName = item.entity_name || '';
        const title = item.title || item.summary || '';
        const detail = item.detail || item.description || '';
        const sourceType = item.source_type || changeType;
        const timeAgo = item.detected_at ? _relativeTime(item.detected_at) : '';
        const isDismissed = item.is_dismissed;

        if (isDismissed) return '';

        return `
            <div class="feed-item ${isUnread ? 'feed-item--unread' : ''}"
                 data-feed-id="${item.id}" style="--i:${idx}"
                 onclick="_onFeedItemClick(${item.id})">
                <div class="feed-item__left">
                    ${_severityBadge(severity)}
                    <div class="feed-item__content">
                        <div class="feed-item__title-row">
                            ${entityName ? `<span class="feed-item__entity">${esc(entityName)}</span>` : ''}
                            <span class="feed-item__title">${esc(title)}</span>
                        </div>
                        <div class="feed-item__meta">
                            <span class="feed-item__time">${esc(timeAgo)}</span>
                            <span class="feed-item__sep">&middot;</span>
                            <span class="feed-item__source">${esc(_formatSourceType(sourceType))}</span>
                            ${detail ? `<span class="feed-item__sep">&middot;</span><span class="feed-item__detail">${esc(_truncateDetail(detail, 60))}</span>` : ''}
                        </div>
                    </div>
                </div>
                <div class="feed-item__actions">
                    ${isUnread ? `<button class="mon-btn mon-btn-sm" onclick="event.stopPropagation(); _markFeedRead(${item.id})" title="Mark as read">Read</button>` : ''}
                    <button class="mon-btn mon-btn-sm mon-btn-ghost" onclick="event.stopPropagation(); _dismissFeedItem(${item.id})" title="Dismiss">Dismiss</button>
                </div>
            </div>
        `;
    }).join('');

    // Load more button
    if (_monitoringFeedHasMore) {
        container.insertAdjacentHTML('beforeend', `
            <div class="feed-load-more">
                <button class="mon-btn" onclick="_loadMoreFeed()">Load more</button>
            </div>
        `);
    }
}

function _renderFeedFilterBar() {
    const el = document.getElementById('monitoringFeedFilters');
    if (!el) return;

    const typeOptions = [
        { value: '', label: 'All types' },
        { value: 'content_change', label: 'Content change' },
        { value: 'new_page', label: 'New page' },
        { value: 'pricing_change', label: 'Pricing change' },
        { value: 'app_update', label: 'App update' },
        { value: 'screenshot_change', label: 'Screenshot' },
        { value: 'new_post', label: 'New post' },
        { value: 'news_mention', label: 'HN mention' },
        { value: 'news_article', label: 'News article' },
        { value: 'traffic_change', label: 'Traffic change' },
        { value: 'patent_filed', label: 'Patent filed' },
    ];

    const severityOptions = [
        { value: '', label: 'All severity' },
        { value: 'critical', label: 'Critical' },
        { value: 'major', label: 'Major' },
        { value: 'minor', label: 'Minor' },
        { value: 'info', label: 'Info' },
    ];

    const currentType = _monitoringFeedFilters.change_type || '';
    const currentSeverity = _monitoringFeedFilters.severity || '';

    el.innerHTML = `
        <div class="feed-filter-group">
            <button class="mon-btn mon-btn-sm" onclick="_markAllFeedRead()">Mark All Read</button>
        </div>
        <div class="feed-filter-group">
            <select class="mon-filter-select" onchange="_setFeedFilter('change_type', this.value)" aria-label="Filter by type">
                ${typeOptions.map(o => `<option value="${o.value}" ${o.value === currentType ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
            <select class="mon-filter-select" onchange="_setFeedFilter('severity', this.value)" aria-label="Filter by severity">
                ${severityOptions.map(o => `<option value="${o.value}" ${o.value === currentSeverity ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
        </div>
    `;
}

function _setFeedFilter(key, value) {
    if (value) {
        _monitoringFeedFilters[key] = value;
    } else {
        delete _monitoringFeedFilters[key];
    }
    _monitoringFeedOffset = 0;
    _loadChangeFeed();
}

function _loadMoreFeed() {
    _monitoringFeedOffset += _monitoringFeedLimit;
    _loadChangeFeed(true);
}

function _onFeedItemClick(feedId) {
    const item = _monitoringFeed.find(i => i.id === feedId);
    if (!item) return;

    // Mark as read on click
    if (!item.is_read) {
        _markFeedRead(feedId);
    }

    // If item has a diff URL or entity, could navigate there
    // For now, just mark as read
}

// ── Feed Actions ─────────────────────────────────────────────────

async function _markFeedRead(feedId) {
    try {
        const resp = await safeFetch(`/api/monitoring/feed/${feedId}/read`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) return;

        // Update local state
        const item = _monitoringFeed.find(i => i.id === feedId);
        if (item) item.is_read = true;

        // Update DOM without full re-render
        const row = document.querySelector(`[data-feed-id="${feedId}"]`);
        if (row) {
            row.classList.remove('feed-item--unread');
            const readBtn = row.querySelector('.mon-btn:not(.mon-btn-ghost)');
            if (readBtn && readBtn.textContent.trim() === 'Read') readBtn.remove();
        }

        // Update stats
        if (_monitoringStats && _monitoringStats.unread_changes > 0) {
            _monitoringStats.unread_changes--;
            _renderMonitoringStats();
        }
    } catch (e) {
        console.warn('Failed to mark feed read:', e);
    }
}

async function _dismissFeedItem(feedId) {
    try {
        const resp = await safeFetch(`/api/monitoring/feed/${feedId}/dismiss`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) return;

        // Remove from local state
        _monitoringFeed = _monitoringFeed.filter(i => i.id !== feedId);

        // Animate removal
        const row = document.querySelector(`[data-feed-id="${feedId}"]`);
        if (row) {
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            setTimeout(() => {
                row.remove();
                if (_monitoringFeed.length === 0) {
                    _renderChangeFeed();
                }
            }, 200);
        }

        _loadMonitoringStats();
    } catch (e) {
        console.warn('Failed to dismiss feed item:', e);
    }
}

async function _markAllFeedRead() {
    if (!currentProjectId) return;
    try {
        const resp = await safeFetch(`/api/monitoring/feed/mark-all-read?project_id=${currentProjectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) return;

        // Update all local items
        _monitoringFeed.forEach(item => { item.is_read = true; });
        _renderChangeFeed();

        if (_monitoringStats) {
            _monitoringStats.unread_changes = 0;
            _renderMonitoringStats();
        }

        showToast('All items marked as read');
    } catch (e) {
        console.warn('Failed to mark all read:', e);
    }
}

// ── Monitors ─────────────────────────────────────────────────────

async function _loadMonitors() {
    if (!currentProjectId) return;
    try {
        const resp = await safeFetch(`/api/monitoring/monitors?project_id=${currentProjectId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        _monitoringMonitors = data.monitors || data || [];
        _renderMonitors();
    } catch (e) {
        console.warn('Failed to load monitors:', e);
    }
}

function _renderMonitors() {
    const container = document.getElementById('monitoringMonitorList');
    const emptyEl = document.getElementById('monitoringMonitorsEmpty');
    if (!container) return;

    if (!_monitoringMonitors || _monitoringMonitors.length === 0) {
        container.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    container.innerHTML = `
        <div class="monitor-table">
            <div class="monitor-table-header">
                <span class="monitor-col monitor-col-entity">Entity</span>
                <span class="monitor-col monitor-col-type">Type</span>
                <span class="monitor-col monitor-col-url">URL</span>
                <span class="monitor-col monitor-col-interval">Interval</span>
                <span class="monitor-col monitor-col-status">Status</span>
                <span class="monitor-col monitor-col-actions">Actions</span>
            </div>
            ${_monitoringMonitors.map(m => _renderMonitorRow(m)).join('')}
        </div>
    `;
}

function _renderMonitorRow(monitor) {
    const entityName = monitor.entity_name || 'Unknown';
    const monType = monitor.monitor_type || 'website';
    const url = monitor.target_url || '';
    const isActive = monitor.is_active !== false;
    const lastCheck = monitor.last_checked_at;
    const lastStatus = monitor.last_status || '';
    const interval = monitor.check_interval_hours || 24;
    const hasError = lastStatus === 'error' || lastStatus === 'failed';
    const neverChecked = !lastCheck;

    let statusHtml;
    if (hasError) {
        statusHtml = `<span class="monitor-status monitor-status-error">
            <span class="status-dot error"></span> Error
        </span>`;
    } else if (neverChecked) {
        statusHtml = `<span class="monitor-status monitor-status-never">
            <span class="status-dot inactive"></span> Never
        </span>`;
    } else {
        statusHtml = `<span class="monitor-status monitor-status-ok">
            <span class="status-dot active"></span> ${_relativeTime(lastCheck)}
        </span>`;
    }

    const queryTypes = ['hackernews', 'news_search', 'patent'];
    const isQueryType = queryTypes.includes(monType);
    const displayUrl = isQueryType ? _truncateDetail(url, 40) : _truncateMonitorUrl(url);

    return `
        <div class="monitor-row ${!isActive ? 'monitor-row--inactive' : ''}" data-monitor-id="${monitor.id}">
            <span class="monitor-col monitor-col-entity">${esc(entityName)}</span>
            <span class="monitor-col monitor-col-type">
                ${_monitorTypeIcon(monType)}
                <span class="monitor-type-label">${esc(_formatMonitorType(monType))}</span>
            </span>
            <span class="monitor-col monitor-col-url" title="${escAttr(url)}">${isQueryType ? '<span class="monitor-query-prefix">Q:</span> ' : ''}${esc(displayUrl)}</span>
            <span class="monitor-col monitor-col-interval">
                <span class="monitor-interval">${interval}h</span>
            </span>
            <span class="monitor-col monitor-col-status">${statusHtml}</span>
            <span class="monitor-col monitor-col-actions">
                <button class="mon-btn mon-btn-sm" onclick="_checkMonitor(${monitor.id})" title="Check now">Check</button>
                <button class="mon-btn mon-btn-sm mon-btn-ghost" onclick="_toggleMonitorActive(${monitor.id}, ${!isActive})" title="${isActive ? 'Pause' : 'Resume'}">
                    ${isActive ? 'Pause' : 'Resume'}
                </button>
                <button class="mon-btn mon-btn-sm mon-btn-danger" onclick="_deleteMonitor(${monitor.id})" title="Delete monitor">Delete</button>
            </span>
        </div>
    `;
}

// ── Monitor Actions ──────────────────────────────────────────────

async function _createMonitor() {
    if (!currentProjectId) return;

    // Ensure entity list is cached
    if (!_monitoringEntities) {
        _monitoringEntities = await _getMonitoringEntities();
    }

    if (!_monitoringEntities.length) {
        showToast('No entities in project. Create an entity first.');
        return;
    }

    const entityOptions = _monitoringEntities.map(e => ({
        value: String(e.id),
        label: e.name,
    }));

    // Step 1: select entity
    window.showSelectDialog('Select Entity', entityOptions, (entityId) => {
        if (!entityId) return;

        // Step 2: select monitor type
        const typeOptions = [
            { value: 'website', label: 'Website' },
            { value: 'app_store', label: 'App Store' },
            { value: 'play_store', label: 'Play Store' },
            { value: 'rss', label: 'RSS Feed' },
            { value: 'social', label: 'Social Media' },
            { value: 'hackernews', label: 'Hacker News' },
            { value: 'news_search', label: 'News Search' },
            { value: 'traffic', label: 'Traffic Monitor' },
            { value: 'patent', label: 'Patent Watch' },
        ];

        window.showSelectDialog('Monitor Type', typeOptions, (monitorType) => {
            if (!monitorType) return;

            // Types that take a search query instead of a URL
            const queryTypes = ['hackernews', 'news_search', 'patent'];
            const isQueryType = queryTypes.includes(monitorType);
            const promptLabel = isQueryType ? 'Search query' : 'Target URL';
            const promptPlaceholder = isQueryType ? 'Entity or topic name' : 'https://example.com';

            // Step 3: enter URL or search query
            window.showPromptDialog(promptLabel, promptPlaceholder, (targetUrl) => {
                if (!targetUrl) return;

                _submitCreateMonitor(parseInt(entityId), monitorType, targetUrl);
            }, 'Create');
        }, 'Next');
    }, 'Next');
}

async function _submitCreateMonitor(entityId, monitorType, targetUrl) {
    try {
        const resp = await safeFetch('/api/monitoring/monitors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: currentProjectId,
                entity_id: entityId,
                monitor_type: monitorType,
                target_url: targetUrl,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to create monitor');
            return;
        }

        showToast('Monitor created');
        _monitoringEntities = null; // invalidate cache
        await Promise.all([_loadMonitors(), _loadMonitoringStats()]);
    } catch (e) {
        console.error('Failed to create monitor:', e);
        showToast('Failed to create monitor');
    }
}

async function _autoSetupMonitors() {
    if (!currentProjectId) return;

    const confirmed = await window.showNativeConfirm({
        title: 'Auto-Setup Monitors',
        message: 'This will scan all entities with URLs and create monitors automatically. Existing monitors will not be duplicated.',
        confirmText: 'Auto-Setup',
        type: 'warning',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/monitoring/auto-setup?project_id=${currentProjectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Auto-setup failed');
            return;
        }

        const data = await resp.json();
        const created = data.created || 0;
        const skipped = data.skipped || 0;
        showToast(`Created ${created} monitors (${skipped} skipped)`);
        await Promise.all([_loadMonitors(), _loadMonitoringStats()]);
    } catch (e) {
        console.error('Auto-setup failed:', e);
        showToast('Auto-setup failed');
    }
}

async function _checkAllMonitors() {
    if (!currentProjectId || _monitoringCheckingAll) return;
    _monitoringCheckingAll = true;

    // Update button state
    const btn = document.getElementById('monitoringCheckAllBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Checking...';
    }

    try {
        const resp = await safeFetch(`/api/monitoring/check-all?project_id=${currentProjectId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Check all failed');
            return;
        }

        const data = await resp.json();
        const checked = data.checked || 0;
        const changes = data.changes_detected || 0;
        showToast(`Checked ${checked} monitors, ${changes} changes detected`);

        await Promise.all([
            _loadMonitoringStats(),
            _loadChangeFeed(),
            _loadMonitors(),
        ]);
    } catch (e) {
        console.error('Check all failed:', e);
        showToast('Check all failed');
    } finally {
        _monitoringCheckingAll = false;
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Check All';
        }
    }
}

async function _checkMonitor(monitorId) {
    const row = document.querySelector(`[data-monitor-id="${monitorId}"]`);
    const checkBtn = row ? row.querySelector('.mon-btn:first-child') : null;
    if (checkBtn) {
        checkBtn.disabled = true;
        checkBtn.textContent = '...';
    }

    try {
        const resp = await safeFetch(`/api/monitoring/monitors/${monitorId}/check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Check failed');
            return;
        }

        const data = await resp.json();
        if (data.change_detected) {
            showToast('Change detected');
        } else {
            showToast('No changes detected');
        }

        await Promise.all([
            _loadMonitoringStats(),
            _loadChangeFeed(),
            _loadMonitors(),
        ]);
    } catch (e) {
        console.error('Monitor check failed:', e);
        showToast('Check failed');
    } finally {
        if (checkBtn) {
            checkBtn.disabled = false;
            checkBtn.textContent = 'Check';
        }
    }
}

async function _toggleMonitorActive(monitorId, activate) {
    try {
        const resp = await safeFetch(`/api/monitoring/monitors/${monitorId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: activate }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Update failed');
            return;
        }

        showToast(activate ? 'Monitor resumed' : 'Monitor paused');
        await Promise.all([_loadMonitors(), _loadMonitoringStats()]);
    } catch (e) {
        console.error('Toggle monitor failed:', e);
        showToast('Update failed');
    }
}

async function _deleteMonitor(monitorId) {
    const confirmed = await window.showNativeConfirm({
        title: 'Delete Monitor',
        message: 'This will permanently remove this monitor and stop tracking changes.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/monitoring/monitors/${monitorId}`, {
            method: 'DELETE',
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Delete failed');
            return;
        }

        // Animate removal
        const row = document.querySelector(`[data-monitor-id="${monitorId}"]`);
        if (row) {
            row.style.opacity = '0';
            row.style.transform = 'translateX(20px)';
            setTimeout(() => {
                _monitoringMonitors = _monitoringMonitors.filter(m => m.id !== monitorId);
                _renderMonitors();
                _loadMonitoringStats();
            }, 200);
        } else {
            await Promise.all([_loadMonitors(), _loadMonitoringStats()]);
        }

        showToast('Monitor deleted');
    } catch (e) {
        console.error('Delete monitor failed:', e);
        showToast('Delete failed');
    }
}

// ── Helpers ──────────────────────────────────────────────────────

/**
 * Format an ISO date string as a human-readable relative time.
 * Returns "just now", "2 minutes ago", "3 hours ago", "5 days ago", etc.
 */
function _relativeTime(isoString) {
    if (!isoString) return '';
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diffMs = now - date;
        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffHr = Math.floor(diffMin / 60);
        const diffDay = Math.floor(diffHr / 24);
        const diffWeek = Math.floor(diffDay / 7);

        if (diffSec < 60) return 'just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHr < 24) return `${diffHr}h ago`;
        if (diffDay < 7) return `${diffDay}d ago`;
        if (diffWeek < 5) return `${diffWeek}w ago`;

        return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
        return '';
    }
}

/**
 * Returns HTML for a severity indicator badge.
 */
function _severityBadge(severity) {
    const level = (severity || 'info').toLowerCase();
    const labels = {
        critical: 'CRIT',
        major: 'MAJOR',
        minor: 'MINOR',
        info: 'INFO',
    };
    const label = labels[level] || level.toUpperCase();
    return `<span class="feed-severity feed-severity--${level}" title="${label}">${label}</span>`;
}

/**
 * Returns a text icon for a monitor type.
 */
function _monitorTypeIcon(type) {
    const icons = {
        website: '<span class="monitor-type-icon" title="Website">WEB</span>',
        app_store: '<span class="monitor-type-icon" title="App Store">iOS</span>',
        play_store: '<span class="monitor-type-icon" title="Play Store">AND</span>',
        rss: '<span class="monitor-type-icon" title="RSS Feed">RSS</span>',
        social: '<span class="monitor-type-icon" title="Social Media">SOC</span>',
        hackernews: '<span class="monitor-type-icon" title="Hacker News">HN</span>',
        news_search: '<span class="monitor-type-icon" title="News Search">NEWS</span>',
        traffic: '<span class="monitor-type-icon" title="Traffic Monitor">TRF</span>',
        patent: '<span class="monitor-type-icon" title="Patent Watch">PAT</span>',
    };
    return icons[type] || `<span class="monitor-type-icon">${esc((type || '').substring(0, 3).toUpperCase())}</span>`;
}

function _formatMonitorType(type) {
    const labels = {
        website: 'Website',
        app_store: 'App Store',
        play_store: 'Play Store',
        rss: 'RSS',
        social: 'Social',
        hackernews: 'Hacker News',
        news_search: 'News Search',
        traffic: 'Traffic',
        patent: 'Patents',
    };
    return labels[type] || type || '';
}

function _formatSourceType(type) {
    const labels = {
        content_change: 'Content',
        new_page: 'New Page',
        pricing_change: 'Pricing',
        app_update: 'App Update',
        screenshot_change: 'Screenshot',
        new_post: 'New Post',
        website: 'Website',
        app_store: 'App Store',
        play_store: 'Play Store',
        rss: 'RSS',
        social: 'Social',
        hackernews: 'Hacker News',
        news_search: 'News Search',
        traffic: 'Traffic',
        patent: 'Patents',
        news_mention: 'HN Mention',
        news_article: 'News Article',
        traffic_change: 'Traffic Change',
        patent_filed: 'Patent Filed',
    };
    return labels[type] || type || '';
}

function _truncateMonitorUrl(url) {
    if (!url) return '';
    if (url.length <= 40) return url;
    try {
        const u = new URL(url);
        const path = u.pathname.length > 20 ? u.pathname.substring(0, 20) + '...' : u.pathname;
        return u.hostname + path;
    } catch {
        return url.substring(0, 37) + '...';
    }
}

function _truncateDetail(text, maxLen) {
    if (!text) return '';
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen - 3) + '...';
}

async function _getMonitoringEntities() {
    if (!currentProjectId) return [];
    try {
        const resp = await safeFetch(`/api/entities?project_id=${currentProjectId}&limit=200`);
        if (!resp.ok) return [];
        const data = await resp.json();
        return data.entities || data || [];
    } catch {
        return [];
    }
}

// ── Skeleton Loading ─────────────────────────────────────────────

function _renderMonitoringSkeleton(container) {
    // Ensure the sub-containers exist so loading looks smooth
    const statsEl = document.getElementById('monitoringStatsBar');
    if (statsEl) {
        statsEl.innerHTML = `
            <div class="mon-stat"><span class="skeleton skeleton-text short" style="height:28px;width:40px;"></span><span class="skeleton skeleton-text short" style="height:12px;width:60px;"></span></div>
            <div class="mon-stat"><span class="skeleton skeleton-text short" style="height:28px;width:40px;"></span><span class="skeleton skeleton-text short" style="height:12px;width:60px;"></span></div>
            <div class="mon-stat"><span class="skeleton skeleton-text short" style="height:28px;width:40px;"></span><span class="skeleton skeleton-text short" style="height:12px;width:60px;"></span></div>
            <div class="mon-stat"><span class="skeleton skeleton-text short" style="height:28px;width:40px;"></span><span class="skeleton skeleton-text short" style="height:12px;width:60px;"></span></div>
        `;
    }

    const feedEl = document.getElementById('monitoringFeed');
    if (feedEl) {
        feedEl.innerHTML = Array.from({ length: 5 }, () => `
            <div class="skeleton-row">
                <div class="skeleton skeleton-avatar"></div>
                <div class="skeleton-content">
                    <div class="skeleton skeleton-text medium"></div>
                    <div class="skeleton skeleton-text short"></div>
                </div>
            </div>
        `).join('');
    }

    const monitorEl = document.getElementById('monitoringMonitorList');
    if (monitorEl) {
        monitorEl.innerHTML = Array.from({ length: 3 }, () => `
            <div class="skeleton-row">
                <div class="skeleton-content">
                    <div class="skeleton skeleton-text long"></div>
                </div>
            </div>
        `).join('');
    }
}

// ── Expose on window ─────────────────────────────────────────────

window.initMonitoring = initMonitoring;
window._loadChangeFeed = _loadChangeFeed;
window._loadMonitors = _loadMonitors;
window._createMonitor = _createMonitor;
window._autoSetupMonitors = _autoSetupMonitors;
window._checkAllMonitors = _checkAllMonitors;
window._checkMonitor = _checkMonitor;
window._markFeedRead = _markFeedRead;
window._dismissFeedItem = _dismissFeedItem;
window._markAllFeedRead = _markAllFeedRead;
window._deleteMonitor = _deleteMonitor;
window._toggleMonitorActive = _toggleMonitorActive;
window._setFeedFilter = _setFeedFilter;
window._loadMoreFeed = _loadMoreFeed;
window._onFeedItemClick = _onFeedItemClick;
