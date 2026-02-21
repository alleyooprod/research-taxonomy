/**
 * Capture UI — evidence management and capture controls.
 * Phase 2.7 of the Research Workbench.
 *
 * Sub-section within the Process tab. Shows evidence stats,
 * entity evidence list, capture triggers, upload, and job progress.
 */

// Capture state
let _captureStats = null;
let _captureJobs = [];
let _bulkCaptureJobId = null;
let _bulkCapturePolling = false;

/**
 * Initialize capture section — called when Process tab shown.
 */
async function initCaptureUI() {
    if (!currentProjectId) return;
    await Promise.all([
        _loadCaptureStats(),
        _loadCaptureJobs(),
    ]);
    // Resume polling if a bulk job is in progress
    if (_bulkCaptureJobId) {
        _pollBulkCapture();
    }
}

// ── Evidence Stats ───────────────────────────────────────────

async function _loadCaptureStats() {
    if (!currentProjectId) return;
    try {
        const resp = await fetch(`/api/evidence/stats?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        _captureStats = await resp.json();
        _renderCaptureStats();
    } catch (e) {
        console.warn('Failed to load capture stats:', e);
    }
}

function _renderCaptureStats() {
    const el = document.getElementById('captureStats');
    if (!el || !_captureStats) return;

    const total = _captureStats.total_count || 0;
    const sizeMb = _captureStats.total_size_mb || 0;
    const byType = _captureStats.by_type || {};

    el.innerHTML = `
        <div class="cap-stat-row">
            <div class="cap-stat">
                <span class="cap-stat-value">${total}</span>
                <span class="cap-stat-label">Evidence Files</span>
            </div>
            <div class="cap-stat">
                <span class="cap-stat-value">${sizeMb}</span>
                <span class="cap-stat-label">MB Stored</span>
            </div>
            ${Object.entries(byType).map(([type, data]) => `
                <div class="cap-stat">
                    <span class="cap-stat-value">${data.count}</span>
                    <span class="cap-stat-label">${type}</span>
                </div>
            `).join('')}
        </div>
    `;
}

// ── Capture Jobs ─────────────────────────────────────────────

async function _loadCaptureJobs() {
    try {
        const resp = await fetch('/api/capture/jobs', {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        _captureJobs = await resp.json();
        _renderCaptureJobs();
    } catch (e) {
        console.warn('Failed to load capture jobs:', e);
    }
}

function _renderCaptureJobs() {
    const el = document.getElementById('captureJobsList');
    if (!el) return;

    if (!_captureJobs.length) {
        el.innerHTML = '<div class="cap-no-jobs">No recent capture jobs</div>';
        return;
    }

    // Show most recent 20 jobs
    const recent = _captureJobs.slice(0, 20);
    el.innerHTML = recent.map(j => `
        <div class="cap-job-row cap-job-${j.status}">
            <span class="cap-job-type">${esc(j.type || 'capture')}</span>
            <span class="cap-job-url" title="${escAttr(j.url || '')}">${esc(_truncateCaptureUrl(j.url || ''))}</span>
            <span class="cap-job-status">${j.status}</span>
        </div>
    `).join('');
}

function _truncateCaptureUrl(url) {
    if (!url || url.length <= 50) return url;
    try {
        const u = new URL(url);
        return u.hostname + u.pathname.substring(0, 30) + '...';
    } catch {
        return url.substring(0, 47) + '...';
    }
}

// ── Single Capture ───────────────────────────────────────────

async function captureEntityUrl() {
    if (!currentProjectId) return;

    const url = await showPromptDialog(
        'Capture URL',
        'Enter URL to capture (screenshot + HTML):',
        '',
    );
    if (!url || !url.trim()) return;

    // Get entity to link to
    const entities = await _getProjectEntities();
    if (!entities.length) {
        if (window.notyf) window.notyf.error('No entities in project — create one first');
        return;
    }

    const options = entities.map(e => ({
        value: String(e.id),
        label: e.name,
    }));

    const entityId = await showSelectDialog(
        'Link to Entity',
        'Which entity should this evidence be linked to?',
        options,
    );
    if (!entityId) return;

    try {
        const resp = await fetch('/api/capture/website', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                url: url.trim(),
                entity_id: parseInt(entityId),
                project_id: currentProjectId,
                async: true,
            }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Capture failed');
            return;
        }
        const data = await resp.json();
        if (window.notyf) window.notyf.success('Capture started');
        // Reload jobs
        setTimeout(() => _loadCaptureJobs(), 1000);
        setTimeout(() => { _loadCaptureJobs(); _loadCaptureStats(); }, 5000);
    } catch (e) {
        console.error('Capture failed:', e);
        if (window.notyf) window.notyf.error('Capture failed');
    }
}

// ── Bulk Capture ─────────────────────────────────────────────

async function bulkCaptureStart() {
    if (!currentProjectId) return;

    const urlsInput = await showPromptDialog(
        'Bulk Capture',
        'Enter URLs to capture (one per line).\nEach URL will be captured as screenshot + HTML.',
        '',
    );
    if (!urlsInput || !urlsInput.trim()) return;

    const urls = urlsInput.split('\n')
        .map(u => u.trim())
        .filter(u => u && (u.startsWith('http://') || u.startsWith('https://')));

    if (!urls.length) {
        if (window.notyf) window.notyf.error('No valid URLs found');
        return;
    }

    // Get entity to link to (all URLs go to the same entity for bulk)
    const entities = await _getProjectEntities();
    if (!entities.length) {
        if (window.notyf) window.notyf.error('No entities in project — create one first');
        return;
    }

    const options = entities.map(e => ({
        value: String(e.id),
        label: e.name,
    }));

    const entityId = await showSelectDialog(
        'Link Evidence to Entity',
        `Capture ${urls.length} URLs. Link evidence to which entity?`,
        options,
    );
    if (!entityId) return;

    const items = urls.map(url => ({
        url,
        entity_id: parseInt(entityId),
        capture_type: 'website',
    }));

    try {
        const resp = await fetch('/api/capture/bulk', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({
                project_id: currentProjectId,
                items,
            }),
        });
        if (!resp.ok) {
            const err = await resp.json();
            if (window.notyf) window.notyf.error(err.error || 'Bulk capture failed');
            return;
        }
        const data = await resp.json();
        _bulkCaptureJobId = data.job_id;
        if (window.notyf) window.notyf.success(`Bulk capture started: ${urls.length} URLs`);
        _renderBulkProgress({ status: 'running', total: urls.length, completed: 0, succeeded: 0, failed: 0 });
        _pollBulkCapture();
    } catch (e) {
        console.error('Bulk capture failed:', e);
        if (window.notyf) window.notyf.error('Bulk capture failed');
    }
}

function _pollBulkCapture() {
    if (!_bulkCaptureJobId || _bulkCapturePolling) return;
    _bulkCapturePolling = true;

    const interval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/capture/bulk/${_bulkCaptureJobId}`, {
                headers: { 'X-CSRFToken': CSRF_TOKEN },
            });
            if (!resp.ok) {
                clearInterval(interval);
                _bulkCapturePolling = false;
                return;
            }
            const data = await resp.json();
            _renderBulkProgress(data);

            if (data.status === 'complete' || data.status === 'error') {
                clearInterval(interval);
                _bulkCapturePolling = false;
                _bulkCaptureJobId = null;
                _loadCaptureStats();
                _loadCaptureJobs();
                if (data.status === 'complete') {
                    if (window.notyf) window.notyf.success(`Bulk capture done: ${data.succeeded}/${data.total} succeeded`);
                }
            }
        } catch (e) {
            console.warn('Bulk poll failed:', e);
        }
    }, 3000);
}

function _renderBulkProgress(data) {
    const el = document.getElementById('captureBulkProgress');
    if (!el) return;

    if (!data || data.status === 'pending') {
        el.innerHTML = '';
        return;
    }

    const total = data.total || 0;
    const completed = data.completed || 0;
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    const isDone = data.status === 'complete';

    el.innerHTML = `
        <div class="cap-bulk-progress">
            <div class="cap-bulk-bar">
                <div class="cap-bulk-fill" style="width: ${pct}%"></div>
            </div>
            <div class="cap-bulk-info">
                <span>${completed}/${total} captured</span>
                <span>${data.succeeded || 0} succeeded, ${data.failed || 0} failed</span>
                ${isDone ? '<span class="cap-bulk-done">Complete</span>' : '<span class="cap-bulk-running">Running...</span>'}
            </div>
        </div>
    `;
}

// ── Upload ───────────────────────────────────────────────────

async function uploadEvidence() {
    if (!currentProjectId) return;

    // Get entity
    const entities = await _getProjectEntities();
    if (!entities.length) {
        if (window.notyf) window.notyf.error('No entities in project — create one first');
        return;
    }

    const options = entities.map(e => ({
        value: String(e.id),
        label: e.name,
    }));

    const entityId = await showSelectDialog(
        'Upload Evidence',
        'Which entity should this file be linked to?',
        options,
    );
    if (!entityId) return;

    // Native file dialog (macOS desktop) or HTML fallback
    if (window.pywebview?.api?.open_file_dialog) {
        const fileTypes = ['Evidence files (*.png *.jpg *.jpeg *.gif *.webp *.svg *.pdf *.doc *.docx *.xls *.xlsx *.html *.htm *.mp4 *.mov *.webm *.json *.csv *.txt *.md)'];
        const paths = await window.pywebview.api.open_file_dialog(fileTypes, true);
        if (!paths || !paths.length) return;

        for (const filePath of paths) {
            const fileInfo = await window.pywebview.api.read_local_file(filePath);
            if (!fileInfo) continue;

            // Build FormData with file content
            const blob = fileInfo.encoding === 'base64'
                ? new Blob([Uint8Array.from(atob(fileInfo.content), c => c.charCodeAt(0))])
                : new Blob([fileInfo.content], { type: 'text/plain' });
            const formData = new FormData();
            formData.append('file', blob, fileInfo.name);
            formData.append('entity_id', entityId);
            formData.append('project_id', String(currentProjectId));

            try {
                const resp = await fetch('/api/evidence/upload', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': CSRF_TOKEN },
                    body: formData,
                });
                if (resp.ok) {
                    if (window.notyf) window.notyf.success(`Uploaded "${fileInfo.name}"`);
                } else {
                    const err = await resp.json();
                    if (window.notyf) window.notyf.error(err.error || `Upload failed: ${fileInfo.name}`);
                }
            } catch (e) {
                console.error('Upload failed:', e);
                if (window.notyf) window.notyf.error(`Upload failed: ${fileInfo.name}`);
            }
        }
        _loadCaptureStats();
    } else {
        // HTML file input fallback (browser mode)
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.png,.jpg,.jpeg,.gif,.webp,.svg,.pdf,.doc,.docx,.xls,.xlsx,.html,.htm,.mp4,.mov,.webm,.json,.csv,.txt,.md';
        input.multiple = true;

        input.onchange = async () => {
            if (!input.files.length) return;

            for (const file of input.files) {
                const formData = new FormData();
                formData.append('file', file);
                formData.append('entity_id', entityId);
                formData.append('project_id', String(currentProjectId));

                try {
                    const resp = await fetch('/api/evidence/upload', {
                        method: 'POST',
                        headers: { 'X-CSRFToken': CSRF_TOKEN },
                        body: formData,
                    });
                    if (resp.ok) {
                        if (window.notyf) window.notyf.success(`Uploaded "${file.name}"`);
                    } else {
                        const err = await resp.json();
                        if (window.notyf) window.notyf.error(err.error || `Upload failed: ${file.name}`);
                    }
                } catch (e) {
                    console.error('Upload failed:', e);
                    if (window.notyf) window.notyf.error(`Upload failed: ${file.name}`);
                }
            }
            _loadCaptureStats();
        };

        input.click();
    }
}

// ── Helpers ──────────────────────────────────────────────────

async function _getProjectEntities() {
    if (!currentProjectId) return [];
    try {
        const resp = await fetch(`/api/entities?project_id=${currentProjectId}&limit=200`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return [];
        const data = await resp.json();
        return data.entities || data || [];
    } catch {
        return [];
    }
}

// ── Drag & Drop ──────────────────────────────────────────────

let _captureDragCounter = 0;

/**
 * Initialize drag-and-drop on the capture section.
 * Called once at page load.
 */
function initCaptureDragDrop() {
    const target = document.getElementById('captureDropTarget');
    if (!target) return;

    target.addEventListener('dragenter', _onCaptureDragEnter);
    target.addEventListener('dragover', _onCaptureDragOver);
    target.addEventListener('dragleave', _onCaptureDragLeave);
    target.addEventListener('drop', _onCaptureDrop);
}

function _onCaptureDragEnter(e) {
    e.preventDefault();
    e.stopPropagation();
    _captureDragCounter++;
    if (_captureDragCounter === 1) {
        _showCaptureDropZone(true);
    }
}

function _onCaptureDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
}

function _onCaptureDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    _captureDragCounter--;
    if (_captureDragCounter <= 0) {
        _captureDragCounter = 0;
        _showCaptureDropZone(false);
    }
}

function _onCaptureDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    _captureDragCounter = 0;
    _showCaptureDropZone(false);

    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;

    _uploadFilesWithEntitySelect(Array.from(files));
}

function _showCaptureDropZone(show) {
    const zone = document.getElementById('captureDropZone');
    const target = document.getElementById('captureDropTarget');
    if (!zone) return;
    if (show) {
        zone.classList.remove('hidden');
        // Force reflow then activate for transition
        zone.offsetHeight; // eslint-disable-line no-unused-expressions
        zone.classList.add('active');
        if (target) target.classList.add('cap-drag-over');
    } else {
        zone.classList.remove('active');
        if (target) target.classList.remove('cap-drag-over');
        // Hide after transition
        setTimeout(() => {
            if (!zone.classList.contains('active')) {
                zone.classList.add('hidden');
            }
        }, 200);
    }
}

/**
 * Upload files, asking the user which entity to link to.
 * @param {File[]} files - Array of File objects to upload
 * @param {number|null} entityId - If provided, skip entity selection
 */
async function _uploadFilesWithEntitySelect(files, entityId) {
    if (!currentProjectId) {
        if (window.notyf) window.notyf.error('No project selected');
        return;
    }

    if (!files || files.length === 0) return;

    // If entity ID is already known, upload directly
    if (entityId) {
        await _uploadFilesToEntity(files, entityId);
        return;
    }

    // Otherwise, ask which entity to link to
    const entities = await _getProjectEntities();
    if (!entities.length) {
        if (window.notyf) window.notyf.error('No entities in project — create one first');
        return;
    }

    const options = entities.map(e => ({
        value: String(e.id),
        label: e.name,
    }));

    window.showSelectDialog(
        'Link dropped files to entity',
        options,
        async function(selectedId) {
            if (!selectedId) return;
            await _uploadFilesToEntity(files, selectedId);
        },
    );
}

/**
 * Upload an array of files to a specific entity.
 */
async function _uploadFilesToEntity(files, entityId) {
    let successCount = 0;
    let failCount = 0;

    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('entity_id', String(entityId));
        formData.append('project_id', String(currentProjectId));

        try {
            const resp = await fetch('/api/evidence/upload', {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN },
                body: formData,
            });
            if (resp.ok) {
                successCount++;
            } else {
                failCount++;
                const err = await resp.json();
                if (window.notyf) window.notyf.error(err.error || `Upload failed: ${file.name}`);
            }
        } catch (e) {
            failCount++;
            console.error('Upload failed:', e);
            if (window.notyf) window.notyf.error(`Upload failed: ${file.name}`);
        }
    }

    if (successCount > 0) {
        const msg = successCount === 1
            ? `Uploaded "${files[0].name}"`
            : `Uploaded ${successCount} file(s)`;
        if (window.notyf) window.notyf.success(msg);
        _loadCaptureStats();
    }
}

// ── Clipboard Paste ──────────────────────────────────────────

/**
 * Initialize clipboard paste listener for screenshots.
 * Called once at page load. Active when Process or Companies tab is visible.
 */
function initClipboardPaste() {
    document.addEventListener('paste', _onClipboardPaste);
}

function _onClipboardPaste(e) {
    // Only active on Process or Companies tabs
    const processTab = document.getElementById('tab-process');
    const companiesTab = document.getElementById('tab-companies');
    const processActive = processTab && processTab.classList.contains('active');
    const companiesActive = companiesTab && companiesTab.classList.contains('active');

    if (!processActive && !companiesActive) return;
    if (!currentProjectId) return;

    // Check if paste target is an input/textarea (don't intercept normal typing)
    const target = e.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
    }

    // Look for image data in clipboard
    const items = e.clipboardData?.items;
    if (!items) return;

    const imageFiles = [];
    for (const item of items) {
        if (item.type.startsWith('image/')) {
            const file = item.getAsFile();
            if (file) {
                // Generate a descriptive filename with timestamp
                const now = new Date();
                const ts = now.getFullYear()
                    + '-' + String(now.getMonth() + 1).padStart(2, '0')
                    + '-' + String(now.getDate()).padStart(2, '0')
                    + '_' + String(now.getHours()).padStart(2, '0')
                    + String(now.getMinutes()).padStart(2, '0')
                    + String(now.getSeconds()).padStart(2, '0');
                const ext = item.type.split('/')[1] || 'png';
                const namedFile = new File([file], `screenshot_${ts}.${ext}`, { type: item.type });
                imageFiles.push(namedFile);
            }
        }
    }

    if (imageFiles.length === 0) return;

    // Prevent default paste behaviour since we're handling the image
    e.preventDefault();

    // Check if entity detail panel is open and visible — auto-link to that entity
    const detailPanel = document.getElementById('entityDetailPanel');
    if (companiesActive && detailPanel && !detailPanel.classList.contains('hidden')) {
        const entityId = _getDetailPanelEntityId();
        if (entityId) {
            _uploadFilesWithEntitySelect(imageFiles, entityId);
            return;
        }
    }

    // Otherwise ask which entity to link to
    _uploadFilesWithEntitySelect(imageFiles);
}

/**
 * Extract the entity ID from the currently open entity detail panel.
 * Looks for data attribute or parses from the edit button onclick.
 */
function _getDetailPanelEntityId() {
    const panel = document.getElementById('entityDetailPanel');
    if (!panel || panel.classList.contains('hidden')) return null;

    // Try data attribute first (set by entity detail rendering)
    if (panel.dataset.entityId) return panel.dataset.entityId;

    // Fallback: parse from the edit button onclick
    const editBtn = panel.querySelector('button[onclick*="openEntityEditModal"]');
    if (editBtn) {
        const match = editBtn.getAttribute('onclick').match(/openEntityEditModal\((\d+)\)/);
        if (match) return match[1];
    }
    return null;
}

// ── Init on Load ─────────────────────────────────────────────

// Set up drag-drop and paste when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        initCaptureDragDrop();
        initClipboardPaste();
    });
} else {
    // DOM already loaded (script loaded with defer or at end of body)
    initCaptureDragDrop();
    initClipboardPaste();
}

// Make functions globally accessible
window.initCaptureUI = initCaptureUI;
window.captureEntityUrl = captureEntityUrl;
window.bulkCaptureStart = bulkCaptureStart;
window.uploadEvidence = uploadEvidence;
window._uploadFilesWithEntitySelect = _uploadFilesWithEntitySelect;
window._uploadFilesToEntity = _uploadFilesToEntity;
