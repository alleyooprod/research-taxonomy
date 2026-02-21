/**
 * Server-Sent Events, browser notifications, and notification bell.
 */

let eventSource = null;
let notifItems = [];
let _sseRetryDelay = 1000;
const _SSE_MAX_RETRY_DELAY = 30000;

function connectSSE() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    if (!currentProjectId) return;

    eventSource = new EventSource(`/api/events/stream?project_id=${currentProjectId}`);

    eventSource.addEventListener('open', () => {
        _sseRetryDelay = 1000; // reset backoff on successful connection
    });

    eventSource.addEventListener('batch_complete', (e) => {
        const data = JSON.parse(e.data);
        loadCompanies();
        loadStats();
        loadBatches();
        showBrowserNotification('Batch Complete', data.message || 'Processing finished');
        addNotifBellItem(data.message || 'Batch processing complete');
        if (retryingBatch && data.batch_id) {
            clearInterval(retryPollInterval);
            retryPollInterval = null;
            const finishedBatch = retryingBatch;
            retryingBatch = null;
            showBatchDetail(finishedBatch);
        }
    });

    eventSource.addEventListener('taxonomy_changed', (e) => {
        const data = JSON.parse(e.data);
        loadTaxonomy();
        addNotifBellItem(data.message || 'Taxonomy updated');
    });

    eventSource.addEventListener('company_added', (e) => {
        const data = JSON.parse(e.data);
        loadCompanies();
        loadStats();
        addNotifBellItem(data.message || 'New company added');
    });

    eventSource.onerror = () => {
        if (eventSource) eventSource.close();
        eventSource = null;
        setTimeout(connectSSE, _sseRetryDelay);
        _sseRetryDelay = Math.min(_sseRetryDelay * 2, _SSE_MAX_RETRY_DELAY);
    };
}

// --- Browser Notifications ---
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

function showBrowserNotification(title, body) {
    // Native macOS notification via pywebview JS API (desktop mode)
    if (window.pywebview && window.pywebview.api && window.pywebview.api.notify) {
        window.pywebview.api.notify(title, body);
        return;
    }
    // Fallback: browser Notification API
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body, icon: '/static/favicon.ico' });
    }
}

// --- Notification Bell ---
function addNotifBellItem(message) {
    notifItems.unshift({ message, time: new Date() });
    if (notifItems.length > 20) notifItems = notifItems.slice(0, 20);
    updateBellBadge();
    renderNotifPanel();
}

function updateBellBadge() {
    const badge = document.getElementById('bellBadge');
    if (notifItems.length > 0) {
        badge.textContent = notifItems.length;
        badge.classList.remove('hidden');
    } else {
        badge.classList.add('hidden');
    }
}

function toggleNotificationPanel() {
    const panel = document.getElementById('notificationPanel');
    panel.classList.toggle('hidden');
    if (!panel.classList.contains('hidden')) {
        renderNotifPanel();
        loadRecentActivity();
    }
}

function renderNotifPanel() {
    const content = document.getElementById('notifPanelContent');
    if (!notifItems.length) {
        content.innerHTML = '<p class="hint-text" style="padding:12px">No recent notifications.</p>';
        return;
    }
    content.innerHTML = notifItems.map(n => `
        <div class="notif-item">
            <span>${esc(n.message)}</span>
            <span class="notif-time">${n.time.toLocaleTimeString()}</span>
        </div>
    `).join('');
}

async function loadRecentActivity() {
    const res = await safeFetch(`/api/activity?project_id=${currentProjectId}&limit=10`);
    const events = await res.json();
    if (events.length) {
        const content = document.getElementById('notifPanelContent');
        let html = content.innerHTML;
        html += '<div style="border-top:1px solid var(--border-default);margin-top:8px;padding-top:8px"><strong style="font-size:12px;color:var(--text-muted)">Recent Activity</strong></div>';
        html += events.map(e => `
            <div class="notif-item">
                <span class="activity-action-badge">${esc(e.action)}</span>
                <span>${esc(e.description || '')}</span>
                <span class="notif-time">${new Date(e.created_at).toLocaleString()}</span>
            </div>
        `).join('');
        content.innerHTML = html;
    }
}

// --- Action Delegation ---
registerActions({
    'toggle-notification-panel': () => toggleNotificationPanel(),
});
