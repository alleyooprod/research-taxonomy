/**
 * Share tokens, notification preferences, and activity log.
 */

// --- Share Tokens ---
async function createShareLink() {
    const label = document.getElementById('shareLinkLabel').value.trim() || 'Shared link';
    const res = await safeFetch('/api/share-tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, label }),
    });
    const data = await res.json();
    document.getElementById('shareLinkLabel').value = '';
    showUndoToast(`Share link created: ${data.url}`, null);
    loadShareTokens();
}

async function loadShareTokens() {
    const res = await safeFetch(`/api/share-tokens?project_id=${currentProjectId}`);
    const tokens = await res.json();
    const container = document.getElementById('shareTokensList');
    if (!tokens.length) {
        container.innerHTML = '<p style="font-size:13px;color:var(--text-muted);margin-top:8px">No share links yet.</p>';
        return;
    }
    container.innerHTML = tokens.map(t => `
        <div class="share-token-item ${t.is_active ? '' : 'share-revoked'}">
            <div>
                <strong>${esc(t.label)}</strong>
                <code class="share-url">${location.origin}/shared/${esc(t.token)}</code>
                <button class="copy-btn" data-action="copy-share-url" data-url="${location.origin}/shared/${esc(t.token)}">Copy</button>
            </div>
            ${t.is_active ? `<button class="danger-btn" data-action="revoke-share-token" data-id="${t.id}" style="font-size:11px;padding:2px 8px">Revoke</button>` : '<span class="share-revoked-label">Revoked</span>'}
        </div>
    `).join('');
}

async function revokeShareToken(tokenId) {
    await safeFetch(`/api/share-tokens/${tokenId}`, { method: 'DELETE' });
    loadShareTokens();
}

// --- Notification Prefs ---
async function loadNotifPrefs() {
    const res = await safeFetch(`/api/notification-prefs?project_id=${currentProjectId}`);
    const prefs = await res.json();
    document.getElementById('slackWebhook').value = prefs.slack_webhook_url || '';
    document.getElementById('notifBatchComplete').checked = !!prefs.notify_batch_complete;
    document.getElementById('notifTaxonomyChange').checked = !!prefs.notify_taxonomy_change;
    document.getElementById('notifNewCompany').checked = !!prefs.notify_new_company;
}

async function saveNotifPrefs() {
    const res = await safeFetch('/api/notification-prefs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            slack_webhook_url: document.getElementById('slackWebhook').value.trim() || null,
            notify_batch_complete: document.getElementById('notifBatchComplete').checked ? 1 : 0,
            notify_taxonomy_change: document.getElementById('notifTaxonomyChange').checked ? 1 : 0,
            notify_new_company: document.getElementById('notifNewCompany').checked ? 1 : 0,
        }),
    });
    const resultDiv = document.getElementById('notifSaveResult');
    resultDiv.classList.remove('hidden');
    resultDiv.innerHTML = '<p class="re-research-success">Preferences saved.</p>';
    setTimeout(() => resultDiv.classList.add('hidden'), 3000);
}

async function testSlack() {
    const url = document.getElementById('slackWebhook').value.trim();
    if (!url) { showToast('Enter a Slack webhook URL first'); return; }
    const res = await safeFetch('/api/notification-prefs/test-slack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slack_webhook_url: url }),
    });
    const data = await res.json();
    if (data.ok) showToast('Test message sent!');
    else showToast('Error: ' + (data.error || 'Unknown'));
}

// --- Cost Dashboard ---
async function initCostDashboard() {
    if (!currentProjectId) return;
    try {
        const [summaryRes, dailyRes, budgetRes] = await Promise.all([
            safeFetch(`/api/costs/summary?project_id=${currentProjectId}`),
            safeFetch(`/api/costs/daily?project_id=${currentProjectId}&days=7`),
            safeFetch(`/api/costs/budget?project_id=${currentProjectId}`),
        ]);
        const summary = await summaryRes.json();
        const daily = await dailyRes.json();
        const budget = await budgetRes.json();

        // Summary cards
        const totalSpend = document.getElementById('costTotalSpend');
        const totalCalls = document.getElementById('costTotalCalls');
        const avgPerCall = document.getElementById('costAvgPerCall');
        const budgetPct = document.getElementById('costBudgetPct');

        if (totalSpend) totalSpend.textContent = '$' + summary.total_cost_usd.toFixed(4);
        if (totalCalls) totalCalls.textContent = summary.total_calls;
        if (avgPerCall) {
            const avg = summary.total_calls > 0 ? summary.total_cost_usd / summary.total_calls : 0;
            avgPerCall.textContent = '$' + avg.toFixed(4);
        }
        if (budgetPct) {
            budgetPct.textContent = budget.budget_usd > 0
                ? budget.percentage_used.toFixed(1) + '%'
                : '--';
        }

        // Budget input
        const budgetInput = document.getElementById('costBudgetInput');
        if (budgetInput && budget.budget_usd > 0) {
            budgetInput.value = budget.budget_usd;
        }

        // Cost by operation table
        const opContainer = document.getElementById('costByOperationTable');
        if (opContainer) {
            const ops = Object.entries(summary.by_operation || {});
            if (ops.length === 0) {
                opContainer.innerHTML = '<p class="hint-text">No cost data yet.</p>';
            } else {
                let html = '<table class="cost-op-table"><thead><tr><th>Operation</th><th>Calls</th><th>Cost (USD)</th></tr></thead><tbody>';
                for (const [op, data] of ops) {
                    html += `<tr><td>${esc(op)}</td><td>${data.calls}</td><td>$${data.cost_usd.toFixed(4)}</td></tr>`;
                }
                html += '</tbody></table>';
                opContainer.innerHTML = html;
            }
        }

        // Daily bar chart
        const chartContainer = document.getElementById('costDailyChart');
        if (chartContainer) {
            if (daily.length === 0) {
                chartContainer.innerHTML = '<p class="hint-text">No daily data yet.</p>';
            } else {
                const maxCost = Math.max(...daily.map(d => d.cost_usd), 0.0001);
                chartContainer.innerHTML = daily.map(d => {
                    const h = Math.max(2, Math.round((d.cost_usd / maxCost) * 60));
                    const label = d.date ? d.date.slice(5) : '';  // MM-DD
                    return `<div class="cost-bar-col">
                        <span class="cost-bar-amount">$${d.cost_usd.toFixed(3)}</span>
                        <div class="cost-bar" style="height:${h}px"></div>
                        <span class="cost-bar-label">${esc(label)}</span>
                    </div>`;
                }).join('');
            }
        }
    } catch (e) {
        // Non-fatal — cost dashboard is supplementary
        console.warn('Cost dashboard load failed:', e);
    }
}

async function saveCostBudget() {
    if (!currentProjectId) { showToast('Select a project first'); return; }
    const input = document.getElementById('costBudgetInput');
    const val = parseFloat(input?.value);
    if (isNaN(val) || val < 0) { showToast('Enter a valid budget amount'); return; }

    const res = await safeFetch(`/api/costs/budget?project_id=${currentProjectId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ budget_usd: val }),
    });
    const data = await res.json();
    const status = document.getElementById('costBudgetStatus');
    if (data.status === 'ok') {
        if (status) { status.textContent = 'Saved'; setTimeout(() => status.textContent = '', 2000); }
        initCostDashboard();
    } else {
        if (status) { status.textContent = data.error || 'Error'; }
    }
}

// --- Activity Log ---
async function loadActivity() {
    const container = document.getElementById('activityFeed');
    container.classList.remove('hidden');
    container.innerHTML = '<p>Loading...</p>';
    const res = await safeFetch(`/api/activity?project_id=${currentProjectId}&limit=50`);
    const events = await res.json();

    if (!events.length) {
        container.innerHTML = '<p style="color:var(--text-muted);font-size:13px">No activity recorded yet.</p>';
        return;
    }

    container.innerHTML = events.map(e => `
        <div class="activity-item">
            <span class="activity-action-badge">${esc(e.action)}</span>
            <span>${esc(e.description || '')}</span>
            <span class="activity-time">${new Date(e.created_at).toLocaleString()}</span>
        </div>
    `).join('');
}

// --- Action Delegation ---
registerActions({
    'copy-share-url': (el) => {
        navigator.clipboard.writeText(el.dataset.url);
        el.textContent = 'Copied!';
        setTimeout(() => el.textContent = 'Copy', 1500);
    },
    'revoke-share-token': (el) => revokeShareToken(Number(el.dataset.id)),
});
