/**
 * App Settings, Backup/Restore, First-Run Onboarding, Auto-Update, Offline Mode, Log Viewer.
 */

// --- Offline Detection ---
let _isOffline = false;

function initOfflineDetection() {
    window.addEventListener('online', () => {
        _isOffline = false;
        document.getElementById('offlineBanner')?.classList.add('hidden');
        document.querySelectorAll('.ai-requires-online').forEach(el => {
            el.disabled = false;
            el.title = '';
        });
    });
    window.addEventListener('offline', () => {
        _isOffline = true;
        document.getElementById('offlineBanner')?.classList.remove('hidden');
        document.querySelectorAll('.ai-requires-online').forEach(el => {
            el.disabled = true;
            el.title = 'Requires internet connection';
        });
    });
    if (!navigator.onLine) {
        _isOffline = true;
        document.getElementById('offlineBanner')?.classList.remove('hidden');
    }
}

// --- App Settings Modal ---

async function openAppSettings() {
    const modal = document.getElementById('appSettingsModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    trapFocus(modal);

    // Load current settings
    const res = await safeFetch('/api/app-settings');
    const settings = await res.json();

    document.getElementById('settingLlmBackend').value = settings.llm_backend || 'cli';
    document.getElementById('settingApiKeyDisplay').textContent = settings.anthropic_api_key_masked || 'Not set';
    document.getElementById('settingDefaultModel').value = settings.default_model || '';
    document.getElementById('settingResearchModel').value = settings.research_model || '';
    document.getElementById('settingGitSync').checked = settings.git_sync_enabled !== false;
    document.getElementById('settingAutoBackup').checked = settings.auto_backup_enabled !== false;
    document.getElementById('settingUpdateCheck').checked = settings.update_check_enabled !== false;

    // Load prerequisites
    const prereqRes = await safeFetch('/api/prerequisites');
    const prereqs = await prereqRes.json();
    renderPrerequisites(prereqs);

    // Load backup list
    loadBackupList();
}

function closeAppSettings() {
    document.getElementById('appSettingsModal')?.classList.add('hidden');
}

async function saveAppSettings() {
    const data = {
        llm_backend: document.getElementById('settingLlmBackend').value,
        default_model: document.getElementById('settingDefaultModel').value,
        research_model: document.getElementById('settingResearchModel').value,
        git_sync_enabled: document.getElementById('settingGitSync').checked,
        auto_backup_enabled: document.getElementById('settingAutoBackup').checked,
        update_check_enabled: document.getElementById('settingUpdateCheck').checked,
    };
    // Include API key only if the user entered a new one
    const apiKeyInput = document.getElementById('settingApiKeyInput');
    if (apiKeyInput && apiKeyInput.value.trim()) {
        data.anthropic_api_key = apiKeyInput.value.trim();
        apiKeyInput.value = '';
    }
    await safeFetch('/api/app-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    showToast('Settings saved');
}

function renderPrerequisites(prereqs) {
    const container = document.getElementById('prereqStatus');
    if (!container) return;
    const items = [
        { label: 'Claude CLI', ok: prereqs.claude_cli?.installed, detail: prereqs.claude_cli?.path || 'Not found' },
        { label: 'Git', ok: prereqs.git?.installed, detail: prereqs.git?.remote_url || prereqs.git?.path || 'Not found' },
        { label: 'API Key', ok: prereqs.anthropic_api_key?.configured, detail: prereqs.anthropic_api_key?.configured ? 'Configured' : 'Not set' },
        { label: 'Node.js', ok: prereqs.node?.installed, detail: prereqs.node?.path || 'Not found (needed for Gemini)' },
    ];
    container.innerHTML = items.map(i => `
        <div class="prereq-item">
            <span class="prereq-status ${i.ok ? 'prereq-ok' : 'prereq-missing'}">${i.ok ? '&#10003;' : '&#10007;'}</span>
            <span class="prereq-label">${i.label}</span>
            <span class="prereq-detail">${esc(i.detail)}</span>
        </div>
    `).join('');

    // Version info
    const version = document.getElementById('settingVersion');
    if (version) version.textContent = `v${prereqs.app_version || '?'}`;

    // Data dir
    const dataDir = document.getElementById('settingDataDir');
    if (dataDir) dataDir.textContent = prereqs.data_dir?.path || '?';
}

// --- Backup & Restore ---

async function loadBackupList() {
    const res = await safeFetch('/api/backups');
    const backups = await res.json();
    const container = document.getElementById('backupList');
    if (!container) return;
    if (!backups.length) {
        container.innerHTML = '<p class="hint-text">No backups yet.</p>';
        return;
    }
    container.innerHTML = backups.map(b => `
        <div class="backup-item">
            <div class="backup-info">
                <strong>${esc(b.filename)}</strong>
                <span class="backup-meta">${b.size_mb} MB &middot; ${new Date(b.created_at).toLocaleString()}</span>
            </div>
            <div class="backup-actions">
                <button class="btn btn-sm" onclick="restoreBackup('${escAttr(b.filename)}')">Restore</button>
                <button class="btn btn-sm danger-btn" onclick="deleteBackup('${escAttr(b.filename)}')">Delete</button>
            </div>
        </div>
    `).join('');
}

async function createBackup() {
    showToast('Creating backup...');
    const res = await safeFetch('/api/backups', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        showToast(`Backup created: ${data.filename} (${data.size_mb} MB)`);
        loadBackupList();
    } else {
        showToast(data.error || 'Backup failed');
    }
}

async function restoreBackup(filename) {
    if (!confirm(`Restore from ${filename}? A safety backup of the current database will be created first.`)) return;
    const res = await safeFetch(`/api/backups/${encodeURIComponent(filename)}/restore`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
        showToast('Database restored. Reloading...');
        setTimeout(() => location.reload(), 1500);
    } else {
        showToast(data.error || 'Restore failed');
    }
}

async function deleteBackup(filename) {
    if (!confirm(`Delete backup ${filename}?`)) return;
    await safeFetch(`/api/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    loadBackupList();
}

// --- Auto-Update Check ---

async function checkForUpdates(silent) {
    try {
        const res = await safeFetch('/api/update-check');
        const data = await res.json();
        if (data.update_available) {
            const banner = document.getElementById('updateBanner');
            if (banner) {
                banner.classList.remove('hidden');
                document.getElementById('updateVersion').textContent = `v${data.latest_version}`;
                document.getElementById('updateLink').href = data.release_url || '#';
            }
            if (!silent) showToast(`Update available: v${data.latest_version}`);
        } else if (!silent) {
            showToast(`You're on the latest version (v${data.current_version})`);
        }
    } catch {
        if (!silent) showToast('Could not check for updates');
    }
}

function dismissUpdateBanner() {
    document.getElementById('updateBanner')?.classList.add('hidden');
}

// --- First-Run Onboarding ---

async function checkFirstRun() {
    try {
        const res = await safeFetch('/api/projects');
        if (!res.ok) return;
        const projects = await res.json();
        if (!Array.isArray(projects) || projects.length !== 0) return;
        // Show onboarding
        const overlay = document.getElementById('onboardingOverlay');
        if (overlay) {
            overlay.classList.remove('hidden');
            const prereqRes = await safeFetch('/api/prerequisites');
            if (prereqRes.ok) {
                const prereqs = await prereqRes.json();
                renderOnboardingPrereqs(prereqs);
            }
        }
    } catch (e) {
        console.error('checkFirstRun error:', e);
    }
}

function renderOnboardingPrereqs(prereqs) {
    const container = document.getElementById('onboardingPrereqs');
    if (!container) return;
    const items = [
        { label: 'Claude CLI', ok: prereqs.claude_cli?.installed, hint: 'Required for AI features. Install: npm install -g @anthropic-ai/claude-code' },
        { label: 'Git', ok: prereqs.git?.installed, hint: 'Optional. Enables auto-sync and version history.' },
    ];
    container.innerHTML = items.map(i => `
        <div class="onboarding-prereq ${i.ok ? 'prereq-ok' : 'prereq-warn'}">
            <span>${i.ok ? '&#10003;' : '&#9888;'}</span>
            <div>
                <strong>${i.label}</strong>
                <p>${i.ok ? 'Installed' : esc(i.hint)}</p>
            </div>
        </div>
    `).join('');
}

function dismissOnboarding() {
    document.getElementById('onboardingOverlay')?.classList.add('hidden');
}

function onboardingCreateProject() {
    dismissOnboarding();
    showNewProjectForm();
}

// --- Log Viewer ---

async function openLogViewer() {
    const modal = document.getElementById('logViewerModal');
    if (!modal) return;
    modal.classList.remove('hidden');
    trapFocus(modal);

    const res = await safeFetch('/api/logs');
    const logs = await res.json();
    const list = document.getElementById('logFileList');
    if (!logs.length) {
        list.innerHTML = '<p class="hint-text">No log files found.</p>';
        return;
    }
    list.innerHTML = logs.map(l => `
        <div class="log-file-item" onclick="viewLogFile('${escAttr(l.filename)}')">
            <strong>${esc(l.filename)}</strong>
            <span>${l.size_kb} KB &middot; ${new Date(l.modified_at).toLocaleString()}</span>
        </div>
    `).join('');
}

function closeLogViewer() {
    document.getElementById('logViewerModal')?.classList.add('hidden');
}

async function viewLogFile(filename) {
    const res = await safeFetch(`/api/logs/${encodeURIComponent(filename)}`);
    const data = await res.json();
    const content = document.getElementById('logContent');
    if (content) {
        content.textContent = data.content || 'Empty log file';
        content.scrollTop = content.scrollHeight;
    }
}

// --- About Dialog ---

function openAboutDialog() {
    const version = document.getElementById('aboutVersion');
    if (version) {
        safeFetch('/api/prerequisites').then(r => r.json()).then(d => {
            version.textContent = `v${d.app_version || '?'}`;
        });
    }
    document.getElementById('aboutModal')?.classList.remove('hidden');
}

function closeAboutDialog() {
    document.getElementById('aboutModal')?.classList.add('hidden');
}

// --- JS Error Logging ---

window.addEventListener('error', (e) => {
    console.error('Uncaught error:', e.message, e.filename, e.lineno);
});

window.addEventListener('unhandledrejection', (e) => {
    console.error('Unhandled promise rejection:', e.reason);
});
