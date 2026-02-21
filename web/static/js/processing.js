/**
 * URL submission, triage, batch processing, and retry logic.
 */

// Fallback if showNativeConfirm hasn't been loaded yet
const _confirmProcessing = window.showNativeConfirm || (async (opts) => confirm(opts.message || opts.title));

async function submitUrls() {
    const text = document.getElementById('urlInput').value;
    if (!text.trim()) { showToast('Paste some URLs first'); return; }

    const res = await safeFetch('/api/triage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, project_id: currentProjectId })
    });

    const data = await res.json();
    if (data.error) { showToast(data.error || 'An error occurred'); return; }

    currentTriageBatchId = data.batch_id;
    triageData = [];

    document.getElementById('triageSection').classList.remove('hidden');
    document.getElementById('triageActions').classList.add('hidden');
    document.getElementById('triageResults').innerHTML = '';
    document.getElementById('triageStatus').textContent = 'Checking...';
    document.getElementById('triageStatus').className = 'triage-status-badge checking';
    document.getElementById('triageProgressText').textContent =
        `Checking ${data.url_count} URLs for accessibility and relevance...`;
    document.getElementById('triageProgress').style.width = '0%';

    pollTriage(data.batch_id, data.url_count);
}

let _triagePollCount = 0;
const _MAX_TRIAGE_RETRIES = 150; // 5 min at 2s intervals

async function pollTriage(batchId, expectedCount) {
    _triagePollCount++;
    if (_triagePollCount > _MAX_TRIAGE_RETRIES) {
        document.getElementById('triageStatus').textContent = 'Timed Out';
        document.getElementById('triageStatus').className = 'triage-status-badge error';
        document.getElementById('triageProgressText').textContent =
            'Triage timed out. Some URLs may still be processing — try refreshing.';
        _triagePollCount = 0;
        return;
    }

    const res = await safeFetch(`/api/triage/${batchId}`);
    if (!res) { _triagePollCount = 0; return; }
    const results = await res.json();

    const done = results.length;
    const pct = expectedCount > 0 ? (done / expectedCount) * 100 : 0;
    document.getElementById('triageProgress').style.width = pct + '%';
    document.getElementById('triageProgressText').textContent =
        `Checked ${done} of ${expectedCount} URLs...`;

    if (done < expectedCount) {
        setTimeout(() => pollTriage(batchId, expectedCount), 2000);
        return;
    }

    _triagePollCount = 0;

    triageData = results;
    renderTriageResults(results);
    document.getElementById('triageStatus').textContent = 'Review';
    document.getElementById('triageStatus').className = 'triage-status-badge review';
    document.getElementById('triageActions').classList.remove('hidden');
    updateTriageSummary();
}

function renderTriageResults(results) {
    const html = results.map((r, i) => {
        let statusClass = 'triage-valid';
        let statusLabel = 'Valid';
        let actionHtml = '';

        if (r.status === 'error') {
            statusClass = 'triage-error';
            statusLabel = 'Error';
            actionHtml = `
                <div class="triage-item-actions">
                    <label><input type="radio" name="action_${r.id}" value="skip" checked data-on-change="update-triage-summary"> Skip</label>
                    <label><input type="radio" name="action_${r.id}" value="replace" data-on-change="show-replacement-input" data-id="${r.id}"> Replace URL</label>
                    <input type="text" id="replacement_${r.id}" class="replacement-input hidden" placeholder="Replacement URL...">
                </div>`;
        } else if (r.status === 'suspect') {
            statusClass = 'triage-suspect';
            statusLabel = 'Suspect';
            actionHtml = `
                <div class="triage-item-actions">
                    <label><input type="radio" name="action_${r.id}" value="include" data-on-change="update-triage-summary"> Include anyway</label>
                    <label><input type="radio" name="action_${r.id}" value="skip" checked data-on-change="update-triage-summary"> Skip</label>
                    <label><input type="radio" name="action_${r.id}" value="replace" data-on-change="show-replacement-input" data-id="${r.id}"> Replace URL</label>
                    <input type="text" id="replacement_${r.id}" class="replacement-input hidden" placeholder="Replacement URL...">
                </div>`;
        } else {
            actionHtml = `
                <div class="triage-item-actions">
                    <label><input type="radio" name="action_${r.id}" value="include" checked data-on-change="update-triage-summary"> Include</label>
                    <label><input type="radio" name="action_${r.id}" value="skip" data-on-change="update-triage-summary"> Skip</label>
                </div>`;
        }

        return `<div class="triage-item ${statusClass}">
            <div class="triage-item-header">
                <span class="triage-badge ${statusClass}">${statusLabel}</span>
                <a href="${esc(r.resolved_url || r.original_url)}" target="_blank">${esc(r.original_url)}</a>
            </div>
            ${r.title ? `<div class="triage-title">${esc(r.title)}</div>` : ''}
            <div class="triage-reason">${esc(r.reason || '')}</div>
            ${r.scraped_text_preview ? `<div class="triage-preview">${esc(r.scraped_text_preview)}</div>` : ''}
            ${actionHtml}
            <input type="text" id="comment_${r.id}" class="triage-comment-input" placeholder="Add a comment (optional)...">
        </div>`;
    }).join('');

    document.getElementById('triageResults').innerHTML = html;
}

function showReplacementInput(triageId) {
    const input = document.getElementById(`replacement_${triageId}`);
    const radio = document.querySelector(`input[name="action_${triageId}"][value="replace"]`);
    if (radio && radio.checked) {
        input.classList.remove('hidden');
    } else {
        input.classList.add('hidden');
    }
    updateTriageSummary();
}

function updateTriageSummary() {
    let includeCount = 0;
    let skipCount = 0;
    let replaceCount = 0;

    triageData.forEach(r => {
        const selected = document.querySelector(`input[name="action_${r.id}"]:checked`);
        if (!selected) return;
        if (selected.value === 'include') includeCount++;
        else if (selected.value === 'skip') skipCount++;
        else if (selected.value === 'replace') replaceCount++;
    });

    document.getElementById('triageSummaryText').textContent =
        `${includeCount} to process, ${skipCount} skipped, ${replaceCount} replaced`;
}

async function confirmAndProcess() {
    const actions = triageData.map(r => {
        const selected = document.querySelector(`input[name="action_${r.id}"]:checked`);
        if (!selected) return null;
        const action = { triage_id: r.id, action: selected.value };
        if (selected.value === 'replace') {
            const replacement = document.getElementById(`replacement_${r.id}`);
            action.replacement_url = replacement ? replacement.value : '';
        }
        const commentInput = document.getElementById(`comment_${r.id}`);
        if (commentInput && commentInput.value.trim()) {
            action.comment = commentInput.value.trim();
        }
        return action;
    }).filter(Boolean);

    await safeFetch(`/api/triage/${currentTriageBatchId}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actions })
    });

    const model = document.getElementById('modelSelect').value;
    const workers = parseInt(document.getElementById('workerCount').value);

    const res = await safeFetch(`/api/triage/${currentTriageBatchId}/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, workers, project_id: currentProjectId })
    });

    const data = await res.json();
    if (data.error) { showToast(data.error || 'An error occurred'); return; }

    document.getElementById('triageSection').classList.add('hidden');
    document.getElementById('batchId').textContent = data.batch_id;
    document.getElementById('processStatus').textContent = `Processing ${data.url_count} URLs...`;
    document.getElementById('processingStatus').classList.remove('hidden');
    document.getElementById('processProgress').style.width = '0%';

    pollBatch(data.batch_id);
}

function resetTriage() {
    document.getElementById('triageSection').classList.add('hidden');
    currentTriageBatchId = null;
    triageData = [];
}

let _batchPollCount = 0;
const _MAX_BATCH_RETRIES = 360; // 30 min at 5s intervals
let _activeBatchPollId = null;

async function pollBatch(batchId) {
    _activeBatchPollId = batchId;
    _batchPollCount++;
    if (_batchPollCount > _MAX_BATCH_RETRIES) {
        document.getElementById('processStatus').textContent =
            'Polling timed out — batch may still be running. Check back later.';
        _batchPollCount = 0;
        _activeBatchPollId = null;
        return;
    }

    const res = await safeFetch(`/api/jobs/${batchId}`);
    if (!res) { _batchPollCount = 0; _activeBatchPollId = null; return; }
    const summary = await res.json();

    const total = summary.total || 0;
    const done = summary.done || 0;
    const errors = summary.errors || 0;
    const pending = summary.pending || 0;

    if (total === 0) {
        document.getElementById('processStatus').textContent = 'Preparing batch...';
        setTimeout(() => pollBatch(batchId), 3000);
        return;
    }

    const pct = ((done + errors) / total) * 100;
    document.getElementById('processProgress').style.width = pct + '%';
    document.getElementById('processStatus').textContent =
        `${done} done, ${errors} errors, ${pending} pending of ${total}`;

    if (pending > 0) {
        setTimeout(() => pollBatch(batchId), 5000);
    } else {
        document.getElementById('processStatus').textContent += ' - Complete!';
        _batchPollCount = 0;
        _activeBatchPollId = null;
        loadStats();
        loadBatches();
    }
}

function cancelBatchPolling() {
    _batchPollCount = _MAX_BATCH_RETRIES + 1; // force stop on next tick
    _activeBatchPollId = null;
    document.getElementById('processStatus').textContent = 'Polling cancelled — batch continues on server.';
}

async function loadBatches() {
    const res = await safeFetch(`/api/jobs?project_id=${currentProjectId}`);
    const batches = await res.json();

    document.getElementById('batchList').innerHTML = batches.length
        ? batches.map(b => {
            const errorParts = [];
            const otherErrors = (b.errors || 0) - (b.timeouts || 0);
            if (b.timeouts) errorParts.push(`${b.timeouts} timeouts`);
            if (otherErrors > 0) errorParts.push(`${otherErrors} errors`);
            const errorText = errorParts.length ? errorParts.join(', ') : '0 errors';
            const pendingText = (b.pending || 0) > 0 ? `, ${b.pending} pending` : '';
            return `<div class="batch-entry" data-action="show-batch-detail" data-id="${esc(b.batch_id)}" style="cursor:pointer">
            <strong>${esc(b.batch_id)}</strong>:
            ${b.done}/${b.total} done, ${errorText}${pendingText}
            <span class="batch-date">${new Date(b.started).toLocaleDateString()}</span>
          </div>`;
        }).join('')
        : `<div class="empty-state">
            <div class="empty-state-icon">📦</div>
            <div class="empty-state-title">No batches yet</div>
            <div class="empty-state-desc">Submit URLs above to start processing companies.</div>
          </div>`;
}

async function showBatchDetail(batchId) {
    const res = await safeFetch(`/api/jobs/${batchId}/details`);
    const data = await res.json();
    const jobs = data.jobs || [];
    const triage = data.triage || [];

    let html = `<div class="batch-detail-panel">
        <div class="detail-header">
            <h2>Batch ${esc(batchId)}</h2>
            <button class="close-btn" data-action="close-batch-detail">&times;</button>
        </div>`;

    if (triage.length) {
        html += `<h3>Triage Decisions</h3><div class="batch-detail-list">`;
        triage.forEach(t => {
            const action = t.user_action || (t.status === 'valid' ? 'auto-include' : 'no action');
            const badge = t.status === 'valid' ? 'triage-valid'
                : t.status === 'suspect' ? 'triage-suspect' : 'triage-error';
            html += `<div class="batch-detail-item">
                <span class="triage-badge ${badge}">${esc(t.status)}</span>
                <a href="${esc(t.resolved_url || t.original_url)}" target="_blank">${esc(t.original_url)}</a>
                <span class="batch-detail-action">${esc(action)}</span>
                ${t.replacement_url ? `<span class="batch-detail-replaced">&rarr; ${esc(t.replacement_url)}</span>` : ''}
                ${t.title ? `<div class="batch-detail-title">${esc(t.title)}</div>` : ''}
                ${t.reason ? `<div class="batch-detail-reason">${esc(t.reason)}</div>` : ''}
                ${t.user_comment ? `<div class="batch-detail-comment"><em>${esc(t.user_comment)}</em></div>` : ''}
            </div>`;
        });
        html += `</div>`;
    }

    const allErrors = jobs.filter(j => j.status === 'error');
    const timeoutJobs = allErrors.filter(j => (j.error_message || '').startsWith('Timeout:'));
    const otherErrors = allErrors.filter(j => !(j.error_message || '').startsWith('Timeout:'));
    const doneJobs = jobs.filter(j => j.status === 'done');
    const pendingJobs = jobs.filter(j => j.status !== 'done' && j.status !== 'error');

    let summaryParts = [];
    if (doneJobs.length) summaryParts.push(`${doneJobs.length} done`);
    if (timeoutJobs.length) summaryParts.push(`${timeoutJobs.length} timeouts`);
    if (otherErrors.length) summaryParts.push(`${otherErrors.length} errors`);
    if (pendingJobs.length) summaryParts.push(`${pendingJobs.length} pending`);

    if (pendingJobs.length > 0 && retryingBatch === batchId) {
        const totalJobs = jobs.length;
        const progress = Math.round((doneJobs.length / totalJobs) * 100);
        html += `<div class="retry-progress-banner">
            <div class="retry-progress-info">
                <span class="spinner"></span>
                <span>Retrying jobs... ${doneJobs.length}/${totalJobs} complete</span>
            </div>
            <div class="progress-bar" style="margin:8px 0">
                <div class="progress-fill" style="width:${progress}%"></div>
            </div>
        </div>`;
    }

    if (retryingBatch === batchId && pendingJobs.length === 0) {
        clearInterval(retryPollInterval);
        retryPollInterval = null;
        retryingBatch = null;
        loadBatches();
    }

    html += `<div class="batch-results-header">
        <h3>Processing Results</h3>
        <span class="batch-results-summary">${summaryParts.join(' / ')}</span>
        ${timeoutJobs.length ? `<button class="btn retry-timeouts-btn" data-action="retry-timeouts" data-id="${esc(batchId)}">Retry ${timeoutJobs.length} Timeouts</button>` : ''}
        ${allErrors.length ? `<button class="btn retry-errors-btn" data-action="retry-all-errors" data-id="${esc(batchId)}">Retry All ${allErrors.length} Errors</button>` : ''}
    </div>`;
    html += `<div class="batch-detail-list">`;
    if (jobs.length) {
        jobs.forEach(j => {
            const isTimeout = j.status === 'error' && (j.error_message || '').startsWith('Timeout:');
            const statusClass = j.status === 'done' ? 'job-done'
                : isTimeout ? 'job-timeout'
                : j.status === 'error' ? 'job-error' : 'job-pending';
            const statusLabel = isTimeout ? 'timeout' : j.status;
            html += `<div class="batch-detail-item ${statusClass}">
                <span class="job-status-badge ${statusClass}">${esc(statusLabel)}</span>
                <span class="batch-detail-url">${esc(j.url)}</span>
                ${j.company_name ? `<span class="batch-detail-company">${esc(j.company_name)}</span>` : ''}
                ${j.category_name ? `<span class="tag">${esc(j.category_name)}</span>` : ''}
                ${j.error_message ? `<div class="batch-detail-error">${esc(j.error_message)}</div>` : ''}
            </div>`;
        });
    } else {
        html += `<p>No processing jobs found for this batch.</p>`;
    }
    html += `</div></div>`;

    document.getElementById('batchDetailView').innerHTML = html;
    document.getElementById('batchDetailView').classList.remove('hidden');
}

function closeBatchDetail() {
    document.getElementById('batchDetailView').classList.add('hidden');
    if (retryPollInterval) {
        clearInterval(retryPollInterval);
        retryPollInterval = null;
        retryingBatch = null;
    }
}

function startRetryPolling(batchId) {
    retryingBatch = batchId;
    if (retryPollInterval) clearInterval(retryPollInterval);
    retryPollInterval = setInterval(() => showBatchDetail(batchId), 5000);
    setTimeout(() => showBatchDetail(batchId), 1000);
}

async function retryTimeouts(batchId) {
    const confirmed = await _confirmProcessing({
        title: 'Retry Timed-Out Jobs?',
        message: `This will retry all timed-out jobs in batch ${batchId}. They will be re-processed with the current model.`,
        confirmText: 'Retry',
        type: 'warning'
    });
    if (!confirmed) return;
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Retrying...';
    try {
        const res = await safeFetch(`/api/jobs/${batchId}/retry-timeouts`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ model: document.getElementById('modelSelect').value })
        });
        const data = await res.json();
        if (data.error) {
            showToast(data.error || 'An error occurred');
            btn.disabled = false;
            btn.textContent = 'Retry Timeouts';
        } else {
            showToast(`Retrying ${data.retry_count} timed-out jobs...`);
            startRetryPolling(batchId);
        }
    } catch (e) {
        showToast('Network error: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Retry Timeouts';
    }
}

// --- Action Delegation ---
registerActions({
    'update-triage-summary': () => updateTriageSummary(),
    'show-replacement-input': (el) => showReplacementInput(Number(el.dataset.id)),
    'show-batch-detail': (el) => showBatchDetail(el.dataset.id),
    'close-batch-detail': () => closeBatchDetail(),
    'retry-timeouts': (el) => retryTimeouts(el.dataset.id),
    'retry-all-errors': (el) => retryAllErrors(el.dataset.id),
});

async function retryAllErrors(batchId) {
    const confirmed = await _confirmProcessing({
        title: 'Retry All Failed Jobs?',
        message: `This will retry ALL failed jobs in batch ${batchId}. They will be re-processed with the current model.`,
        confirmText: 'Retry All',
        type: 'warning'
    });
    if (!confirmed) return;
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Retrying...';
    try {
        const res = await safeFetch(`/api/jobs/${batchId}/retry-errors`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ model: document.getElementById('modelSelect').value })
        });
        const data = await res.json();
        if (data.error) {
            showToast(data.error || 'An error occurred');
            btn.disabled = false;
            btn.textContent = 'Retry All Errors';
        } else {
            showToast(`Retrying ${data.retry_count} failed jobs...`);
            startRetryPolling(batchId);
        }
    } catch (e) {
        showToast('Network error: ' + e.message);
        btn.disabled = false;
        btn.textContent = 'Retry All Errors';
    }
}
