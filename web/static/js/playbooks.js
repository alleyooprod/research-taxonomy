/**
 * Research Playbooks -- Intelligence tab sub-view.
 *
 * Provides a guided research workflow system. Users can create playbooks
 * (sequences of steps), run them against projects, and track progress.
 * Built-in templates can be seeded for common research patterns.
 *
 * Lives inside #tab-intelligence alongside Monitoring, Insights, and Hypotheses.
 * Sub-nav switching is handled by insights.js -- this file only manages the
 * Playbooks dashboard content.
 *
 * API prefix: /api/playbooks/...
 */

// ── State ──────────────────────────────────────────────────────
let _playbooksLoaded = false;
let _playbooksList = [];
let _activeRunsList = [];
let _currentPlaybookView = 'library'; // 'library' | 'runs' | 'run-detail'
let _currentRunId = null;

// ── Public API ─────────────────────────────────────────────────

window.initPlaybooks = initPlaybooks;
window._ensurePlaybooksDashboard = _ensurePlaybooksDashboard;

/**
 * Entry point -- called when the Playbooks sub-view is shown.
 * Ensures the dashboard container exists, then loads data.
 */
function initPlaybooks() {
    if (!currentProjectId) return;

    _ensurePlaybooksDashboard();

    // Show the dashboard
    const el = document.getElementById('playbooksDashboard');
    if (el) el.classList.remove('hidden');

    // Load the current view
    if (_currentPlaybookView === 'library') {
        _loadPlaybooks();
    } else if (_currentPlaybookView === 'runs') {
        _loadActiveRuns();
    } else if (_currentPlaybookView === 'run-detail' && _currentRunId) {
        _viewRunDetail(_currentRunId);
    }
}

// ── Dashboard Container ────────────────────────────────────────

/**
 * Create the playbooks dashboard container dynamically if it does
 * not already exist. Appended to #tab-intelligence.
 */
function _ensurePlaybooksDashboard() {
    const tab = document.getElementById('tab-intelligence');
    if (!tab) return;

    // Already injected?
    if (document.getElementById('playbooksDashboard')) return;

    const container = document.createElement('div');
    container.id = 'playbooksDashboard';
    container.className = 'pb-dashboard hidden';
    container.innerHTML = `
        <div class="pb-header">
            <h2>Research Playbooks</h2>
            <div class="pb-header-actions">
                <button class="ins-btn ins-btn-ghost" onclick="_seedTemplates()" id="pbSeedBtn">Seed Templates</button>
                <button class="ins-btn" onclick="_createPlaybook()">+ New Playbook</button>
            </div>
        </div>

        <div class="pb-inner-nav">
            <button class="pb-inner-btn pb-inner-btn--active" data-pb-view="library"
                    onclick="_switchPlaybookView('library')">Library</button>
            <button class="pb-inner-btn" data-pb-view="runs"
                    onclick="_switchPlaybookView('runs')">Active Runs</button>
        </div>

        <div id="pbLibrary" class="pb-library"></div>
        <div id="pbLibraryEmpty" class="pb-empty hidden">
            <div class="pb-empty__title">No playbooks yet</div>
            <div class="pb-empty__desc">Create a playbook or seed the built-in templates to get started.</div>
            <div class="pb-empty__actions">
                <button class="ins-btn" onclick="_seedTemplates()">Seed Templates</button>
                <button class="ins-btn ins-btn-ghost" onclick="_createPlaybook()">+ New Playbook</button>
            </div>
        </div>

        <div id="pbRuns" class="pb-runs hidden"></div>
        <div id="pbRunsEmpty" class="pb-empty hidden">
            <div class="pb-empty__title">No active runs</div>
            <div class="pb-empty__desc">Start a playbook run from the library to begin tracking progress.</div>
        </div>

        <div id="pbRunDetail" class="pb-run-detail hidden"></div>

        <div id="pbSuggestions" class="pb-suggestions hidden"></div>
    `;
    tab.appendChild(container);
}

// ── Inner Sub-Navigation ───────────────────────────────────────

/**
 * Switch between library and active runs views within the Playbooks
 * dashboard. Also hides run-detail when switching away.
 */
function _switchPlaybookView(view) {
    _currentPlaybookView = view;
    _currentRunId = null;

    // Update inner nav active state
    document.querySelectorAll('.pb-inner-btn').forEach(btn => {
        btn.classList.toggle('pb-inner-btn--active', btn.dataset.pbView === view);
    });

    // Toggle containers
    const libraryEl = document.getElementById('pbLibrary');
    const libraryEmptyEl = document.getElementById('pbLibraryEmpty');
    const runsEl = document.getElementById('pbRuns');
    const runsEmptyEl = document.getElementById('pbRunsEmpty');
    const runDetailEl = document.getElementById('pbRunDetail');
    const suggestionsEl = document.getElementById('pbSuggestions');

    if (libraryEl) libraryEl.classList.toggle('hidden', view !== 'library');
    if (libraryEmptyEl) libraryEmptyEl.classList.add('hidden');
    if (runsEl) runsEl.classList.toggle('hidden', view !== 'runs');
    if (runsEmptyEl) runsEmptyEl.classList.add('hidden');
    if (runDetailEl) runDetailEl.classList.add('hidden');
    if (suggestionsEl) suggestionsEl.classList.add('hidden');

    // Load data for the selected view
    if (view === 'library') {
        _loadPlaybooks();
    } else if (view === 'runs') {
        _loadActiveRuns();
    }
}

// ── Playbook Library ───────────────────────────────────────────

/**
 * Fetch all playbooks and render the library grid.
 */
async function _loadPlaybooks() {
    if (!currentProjectId) return;

    try {
        const resp = await safeFetch('/api/playbooks');
        if (!resp.ok) return;
        const data = await resp.json();
        _playbooksList = data.playbooks || data || [];
        _renderPlaybookCards(_playbooksList);
    } catch (e) {
        console.warn('Failed to load playbooks:', e);
    }
}

/**
 * Render playbook cards in a grid layout.
 */
function _renderPlaybookCards(playbooks) {
    const container = document.getElementById('pbLibrary');
    const emptyEl = document.getElementById('pbLibraryEmpty');
    if (!container) return;

    if (!playbooks || playbooks.length === 0) {
        container.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    // Sort: templates first, then by name
    const sorted = [...playbooks].sort((a, b) => {
        if (a.is_template && !b.is_template) return -1;
        if (!a.is_template && b.is_template) return 1;
        return (a.name || '').localeCompare(b.name || '');
    });

    container.innerHTML = `
        <div class="pb-grid">
            ${sorted.map((pb, idx) => _renderPlaybookCard(pb, idx)).join('')}
        </div>
    `;
}

/**
 * Render a single playbook card.
 */
function _renderPlaybookCard(pb, idx) {
    const stepCount = pb.steps ? pb.steps.length : (pb.step_count || 0);
    const category = pb.category || '';
    const isTemplate = pb.is_template;
    const runCount = pb.run_stats?.total_runs || pb.run_count || 0;
    const description = pb.description || '';
    const truncatedDesc = description.length > 120
        ? description.substring(0, 120) + '...'
        : description;

    return `
        <div class="pb-card" data-playbook-id="${pb.id}" style="--i:${idx}">
            <div class="pb-card__top">
                <div class="pb-card__badges">
                    ${isTemplate ? '<span class="pb-template-badge">TEMPLATE</span>' : ''}
                    ${category ? `<span class="pb-category-badge">${esc(category)}</span>` : ''}
                </div>
                <div class="pb-card__name">${esc(pb.name || 'Untitled')}</div>
                ${truncatedDesc ? `<div class="pb-card__desc">${esc(truncatedDesc)}</div>` : ''}
            </div>
            <div class="pb-card__bottom">
                <div class="pb-card__meta">
                    <span class="pb-card__meta-item">${stepCount} step${stepCount !== 1 ? 's' : ''}</span>
                    <span class="pb-card__sep">&middot;</span>
                    <span class="pb-card__meta-item">${runCount} run${runCount !== 1 ? 's' : ''}</span>
                </div>
                <div class="pb-card__actions">
                    <button class="ins-btn ins-btn-sm" onclick="event.stopPropagation(); _startRun(${pb.id})"
                            title="Start Run">Run</button>
                    <button class="ins-btn ins-btn-sm ins-btn-ghost" onclick="event.stopPropagation(); _duplicatePlaybook(${pb.id})"
                            title="Duplicate">Duplicate</button>
                    ${!isTemplate ? `
                        <button class="ins-btn ins-btn-sm ins-btn-ghost" onclick="event.stopPropagation(); _editPlaybook(${pb.id})"
                                title="Edit">Edit</button>
                        <button class="ins-btn ins-btn-sm ins-btn-danger" onclick="event.stopPropagation(); _deletePlaybook(${pb.id})"
                                title="Delete">Delete</button>
                    ` : ''}
                    <button class="ins-btn ins-btn-sm ins-btn-ghost" onclick="event.stopPropagation(); _improvePlaybook(${pb.id})"
                            title="AI Suggestions">Improve</button>
                </div>
            </div>
        </div>
    `;
}

// ── Active Runs ────────────────────────────────────────────────

/**
 * Fetch active runs for the current project and render the list.
 */
async function _loadActiveRuns() {
    if (!currentProjectId) return;

    try {
        const resp = await safeFetch(`/api/playbooks/runs?project_id=${currentProjectId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        _activeRunsList = data.runs || data || [];
        _renderRunsList(_activeRunsList);
    } catch (e) {
        console.warn('Failed to load active runs:', e);
    }
}

/**
 * Render the list of runs with status and progress.
 */
function _renderRunsList(runs) {
    const container = document.getElementById('pbRuns');
    const emptyEl = document.getElementById('pbRunsEmpty');
    if (!container) return;

    if (!runs || runs.length === 0) {
        container.innerHTML = '';
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }
    if (emptyEl) emptyEl.classList.add('hidden');

    // Sort: in_progress first, then by started_at desc
    const sorted = [...runs].sort((a, b) => {
        if (a.status === 'in_progress' && b.status !== 'in_progress') return -1;
        if (a.status !== 'in_progress' && b.status === 'in_progress') return 1;
        return (b.started_at || '').localeCompare(a.started_at || '');
    });

    container.innerHTML = sorted.map((run, idx) => _renderRunItem(run, idx)).join('');
}

/**
 * Render a single run row with progress bar.
 */
function _renderRunItem(run, idx) {
    const status = (run.status || 'in_progress').toLowerCase();
    const playbookName = run.playbook_name || run.playbook?.name || 'Playbook';
    const totalSteps = run.total_steps || 0;
    const completedSteps = run.completed_steps || 0;
    const progressPct = totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0;
    const startedAt = run.started_at ? _pbRelativeTime(run.started_at) : '';
    const completedAt = run.completed_at ? _pbRelativeTime(run.completed_at) : '';

    return `
        <div class="pb-run-item" data-run-id="${run.id}" style="--i:${idx}"
             onclick="_viewRunDetail(${run.id})">
            <div class="pb-run-item__left">
                <span class="pb-status-badge pb-status--${esc(status)}">${esc(_formatRunStatus(status))}</span>
                <div class="pb-run-item__content">
                    <div class="pb-run-item__name">${esc(playbookName)}</div>
                    <div class="pb-run-item__meta">
                        <span class="pb-run-item__time">Started ${esc(startedAt)}</span>
                        ${completedAt ? `<span class="pb-run-item__sep">&middot;</span><span class="pb-run-item__time">Completed ${esc(completedAt)}</span>` : ''}
                    </div>
                </div>
            </div>
            <div class="pb-run-item__right">
                <div class="pb-run-item__progress-info">
                    <span class="pb-run-item__progress-text">${completedSteps}/${totalSteps}</span>
                    <span class="pb-run-item__progress-pct">${progressPct}%</span>
                </div>
                <div class="pb-progress-bar">
                    <div class="pb-progress-fill pb-progress--${esc(status)}" style="width: ${progressPct}%"></div>
                </div>
            </div>
        </div>
    `;
}

// ── Run Detail View ────────────────────────────────────────────

/**
 * Fetch a run with its merged steps and render the detail view.
 */
async function _viewRunDetail(runId) {
    _currentPlaybookView = 'run-detail';
    _currentRunId = runId;

    // Hide other views, show detail
    const libraryEl = document.getElementById('pbLibrary');
    const libraryEmptyEl = document.getElementById('pbLibraryEmpty');
    const runsEl = document.getElementById('pbRuns');
    const runsEmptyEl = document.getElementById('pbRunsEmpty');
    const detailEl = document.getElementById('pbRunDetail');
    const suggestionsEl = document.getElementById('pbSuggestions');

    if (libraryEl) libraryEl.classList.add('hidden');
    if (libraryEmptyEl) libraryEmptyEl.classList.add('hidden');
    if (runsEl) runsEl.classList.add('hidden');
    if (runsEmptyEl) runsEmptyEl.classList.add('hidden');
    if (suggestionsEl) suggestionsEl.classList.add('hidden');
    if (detailEl) {
        detailEl.classList.remove('hidden');
        detailEl.innerHTML = '<div class="pb-loading">Loading run...</div>';
    }

    try {
        const resp = await safeFetch(`/api/playbooks/runs/${runId}`);
        if (!resp.ok) {
            if (detailEl) detailEl.innerHTML = '<div class="pb-loading">Failed to load run</div>';
            return;
        }

        const run = await resp.json();
        _renderRunDetail(run);
    } catch (e) {
        console.warn('Failed to load run detail:', e);
        if (detailEl) detailEl.innerHTML = '<div class="pb-loading">Failed to load run</div>';
    }
}

/**
 * Render the full run detail view with step tracker.
 */
function _renderRunDetail(run) {
    const detailEl = document.getElementById('pbRunDetail');
    if (!detailEl) return;

    const status = (run.status || 'in_progress').toLowerCase();
    const playbookName = run.playbook_name || run.playbook?.name || 'Playbook';
    const steps = run.steps || [];
    const totalSteps = steps.length || run.total_steps || 0;
    const completedSteps = steps.filter(s => s.completed).length;
    const progressPct = totalSteps > 0 ? Math.round((completedSteps / totalSteps) * 100) : 0;
    const startedAt = run.started_at ? _pbRelativeTime(run.started_at) : '';

    detailEl.innerHTML = `
        <div class="pb-run-detail__header">
            <button class="ins-btn ins-btn-ghost" onclick="_backToRunsList()">Back</button>
            <div class="pb-run-detail__header-right">
                ${status === 'in_progress' ? `
                    <button class="ins-btn ins-btn-sm ins-btn-danger" onclick="_updateRunStatus(${run.id}, 'abandoned')">Abandon</button>
                    <button class="ins-btn ins-btn-sm" onclick="_updateRunStatus(${run.id}, 'completed')">Complete</button>
                ` : ''}
            </div>
        </div>

        <div class="pb-run-detail__summary">
            <div class="pb-run-detail__title-row">
                <span class="pb-run-detail__name">${esc(playbookName)}</span>
                <span class="pb-status-badge pb-status--${esc(status)}">${esc(_formatRunStatus(status))}</span>
            </div>
            <div class="pb-run-detail__meta">
                <span>Started ${esc(startedAt)}</span>
            </div>
            <div class="pb-run-detail__progress-row">
                <div class="pb-progress-bar pb-progress-bar--lg">
                    <div class="pb-progress-fill pb-progress--${esc(status)}" style="width: ${progressPct}%"></div>
                </div>
                <span class="pb-run-detail__progress-label">${completedSteps}/${totalSteps} (${progressPct}%)</span>
            </div>
        </div>

        <div class="pb-run-detail__steps">
            ${steps.map((step, idx) => _renderStepItem(run.id, step, idx, status)).join('')}
        </div>
    `;
}

/**
 * Render a single step item within the run detail view.
 */
function _renderStepItem(runId, step, idx, runStatus) {
    const completed = step.completed || false;
    const stepType = step.type || 'task';
    const title = step.title || `Step ${idx + 1}`;
    const description = step.description || '';
    const guidance = step.guidance || '';
    const notes = step.notes || '';
    const stepClasses = ['pb-step'];
    if (completed) stepClasses.push('pb-step--completed');

    const isEditable = runStatus === 'in_progress';
    const guidanceId = `pbGuidance_${runId}_${idx}`;
    const notesId = `pbNotes_${runId}_${idx}`;

    return `
        <div class="${stepClasses.join(' ')}" data-step-index="${idx}">
            <div class="pb-step__header">
                <label class="pb-step__checkbox-label">
                    <input type="checkbox" class="pb-step__checkbox"
                           ${completed ? 'checked' : ''}
                           ${!isEditable ? 'disabled' : ''}
                           onchange="_onStepCheckChange(${runId}, ${idx}, this.checked)">
                    <span class="pb-step__index">${idx + 1}</span>
                </label>
                <div class="pb-step__title-area">
                    <div class="pb-step__title-row">
                        <span class="pb-step__title">${esc(title)}</span>
                        <span class="pb-step__type-badge">${esc(stepType)}</span>
                    </div>
                    ${description ? `<div class="pb-step__description">${esc(description)}</div>` : ''}
                </div>
            </div>

            ${guidance ? `
                <div class="pb-step__guidance-section">
                    <button class="pb-step__guidance-toggle ins-btn ins-btn-sm ins-btn-ghost"
                            onclick="_toggleGuidance('${guidanceId}', this)">Show Guidance</button>
                    <div id="${guidanceId}" class="pb-step__guidance hidden">${esc(guidance)}</div>
                </div>
            ` : ''}

            ${isEditable ? `
                <div class="pb-step__notes-section">
                    <textarea id="${notesId}" class="pb-step__notes"
                              placeholder="Add notes for this step..."
                              onblur="_saveStepNotes(${runId}, ${idx}, this.value)">${esc(notes)}</textarea>
                </div>
            ` : (notes ? `
                <div class="pb-step__notes-section">
                    <div class="pb-step__notes-readonly">${esc(notes)}</div>
                </div>
            ` : '')}
        </div>
    `;
}

/**
 * Toggle guidance visibility for a step.
 */
function _toggleGuidance(guidanceId, btnEl) {
    const el = document.getElementById(guidanceId);
    if (!el) return;

    const isHidden = el.classList.contains('hidden');
    el.classList.toggle('hidden');
    if (btnEl) {
        btnEl.textContent = isHidden ? 'Hide Guidance' : 'Show Guidance';
    }
}

/**
 * Handle step checkbox change -- calls the complete step API.
 */
function _onStepCheckChange(runId, stepIndex, checked) {
    const notesEl = document.getElementById(`pbNotes_${runId}_${stepIndex}`);
    const notes = notesEl ? notesEl.value : '';
    _completeStep(runId, stepIndex, checked, notes);
}

/**
 * Save step notes on blur -- only sends if the step is already completed
 * or if there are actual notes to save.
 */
function _saveStepNotes(runId, stepIndex, notes) {
    const stepEl = document.querySelector(`[data-step-index="${stepIndex}"]`);
    if (!stepEl) return;

    const checkbox = stepEl.querySelector('.pb-step__checkbox');
    const completed = checkbox ? checkbox.checked : false;

    // Only save if step has been interacted with
    if (notes.trim() || completed) {
        _completeStep(runId, stepIndex, completed, notes);
    }
}

// ── Step & Run Status Operations ───────────────────────────────

/**
 * Mark a step as completed or uncompleted with optional notes.
 */
async function _completeStep(runId, stepIndex, completed, notes) {
    try {
        const body = { completed: completed };
        if (notes !== undefined && notes !== null) body.notes = notes;

        const resp = await safeFetch(`/api/playbooks/runs/${runId}/step/${stepIndex}`, {
            method: 'PUT',
            headers: csrfHeaders(),
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to update step', 'error');
            return;
        }

        // Refresh the run detail to get updated progress
        await _viewRunDetail(runId);
    } catch (e) {
        console.warn('Failed to complete step:', e);
        showToast('Failed to update step', 'error');
    }
}

/**
 * Update the overall status of a run (e.g. abandon or complete).
 */
async function _updateRunStatus(runId, status) {
    if (status === 'abandoned') {
        const confirmed = await window.showNativeConfirm({
            title: 'Abandon Run',
            message: 'This will mark the run as abandoned. You can still view its progress but cannot make further changes.',
            confirmText: 'Abandon',
            type: 'danger',
        });
        if (!confirmed) return;
    }

    if (status === 'completed') {
        const confirmed = await window.showNativeConfirm({
            title: 'Complete Run',
            message: 'Mark this run as completed? Any remaining unchecked steps will stay as-is.',
            confirmText: 'Complete',
            type: 'warning',
        });
        if (!confirmed) return;
    }

    try {
        const resp = await safeFetch(`/api/playbooks/runs/${runId}/status`, {
            method: 'PUT',
            headers: csrfHeaders(),
            body: JSON.stringify({ status: status }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to update run status', 'error');
            return;
        }

        showToast(`Run ${status === 'completed' ? 'completed' : 'abandoned'}`);
        await _viewRunDetail(runId);
    } catch (e) {
        console.warn('Failed to update run status:', e);
        showToast('Failed to update run status', 'error');
    }
}

/**
 * Navigate back from run detail to the runs list.
 */
function _backToRunsList() {
    _switchPlaybookView('runs');
}

// ── Playbook CRUD ──────────────────────────────────────────────

/**
 * Start a new run for a playbook.
 */
async function _startRun(playbookId) {
    if (!currentProjectId) {
        showToast('No project selected', 'error');
        return;
    }

    try {
        const resp = await safeFetch(`/api/playbooks/${playbookId}/run`, {
            method: 'POST',
            headers: csrfHeaders(),
            body: JSON.stringify({ project_id: currentProjectId }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to start run', 'error');
            return;
        }

        const data = await resp.json();
        const runId = data.run_id || data.id;
        showToast('Run started');

        // Navigate to the run detail view
        if (runId) {
            _viewRunDetail(runId);
        } else {
            _switchPlaybookView('runs');
        }
    } catch (e) {
        console.warn('Failed to start run:', e);
        showToast('Failed to start run', 'error');
    }
}

/**
 * Show the create/edit playbook modal.
 */
function _createPlaybook() {
    _ensurePlaybookFormModal();
    const overlay = document.getElementById('pbFormModal');
    const titleEl = document.getElementById('pbFormTitle');
    const nameInput = document.getElementById('pbFormName');
    const descInput = document.getElementById('pbFormDescription');
    const catInput = document.getElementById('pbFormCategory');
    const stepsContainer = document.getElementById('pbFormSteps');
    const submitBtn = document.getElementById('pbFormSubmit');

    titleEl.textContent = 'New Playbook';
    nameInput.value = '';
    descInput.value = '';
    catInput.value = '';
    stepsContainer.innerHTML = _renderStepFormRow(0);
    submitBtn.textContent = 'Create';
    submitBtn.dataset.mode = 'create';
    submitBtn.dataset.pbId = '';

    overlay.style.display = 'flex';
    requestAnimationFrame(() => {
        overlay.classList.add('visible');
        nameInput.focus();
    });
}

/**
 * Show the edit playbook modal pre-filled with existing data.
 */
async function _editPlaybook(playbookId) {
    const pb = _playbooksList.find(p => p.id === playbookId);
    if (!pb) return;

    // If we don't have full step data, fetch the playbook detail
    let playbook = pb;
    if (!pb.steps || pb.steps.length === 0) {
        try {
            const resp = await safeFetch(`/api/playbooks/${playbookId}`);
            if (resp.ok) {
                playbook = await resp.json();
            }
        } catch (e) {
            console.warn('Failed to fetch playbook detail:', e);
        }
    }

    _ensurePlaybookFormModal();
    const overlay = document.getElementById('pbFormModal');
    const titleEl = document.getElementById('pbFormTitle');
    const nameInput = document.getElementById('pbFormName');
    const descInput = document.getElementById('pbFormDescription');
    const catInput = document.getElementById('pbFormCategory');
    const stepsContainer = document.getElementById('pbFormSteps');
    const submitBtn = document.getElementById('pbFormSubmit');

    titleEl.textContent = 'Edit Playbook';
    nameInput.value = playbook.name || '';
    descInput.value = playbook.description || '';
    catInput.value = playbook.category || '';

    const steps = playbook.steps || [];
    if (steps.length > 0) {
        stepsContainer.innerHTML = steps.map((s, i) => _renderStepFormRow(i, s)).join('');
    } else {
        stepsContainer.innerHTML = _renderStepFormRow(0);
    }

    submitBtn.textContent = 'Save';
    submitBtn.dataset.mode = 'edit';
    submitBtn.dataset.pbId = String(playbookId);

    overlay.style.display = 'flex';
    requestAnimationFrame(() => {
        overlay.classList.add('visible');
        nameInput.focus();
    });
}

/**
 * Render a single step row in the create/edit form.
 */
function _renderStepFormRow(index, step) {
    const title = step ? (step.title || '') : '';
    const description = step ? (step.description || '') : '';
    const type = step ? (step.type || 'task') : 'task';

    return `
        <div class="pb-form-step" data-step-form-index="${index}">
            <div class="pb-form-step__header">
                <span class="pb-form-step__num">${index + 1}</span>
                <button type="button" class="ins-btn ins-btn-sm ins-btn-danger"
                        onclick="_removeStepFormRow(this)" title="Remove step">Remove</button>
            </div>
            <div class="pb-form-step__fields">
                <input type="text" class="ins-form-input pb-form-step__title"
                       placeholder="Step title" value="${esc(title)}">
                <input type="text" class="ins-form-input pb-form-step__desc"
                       placeholder="Description (optional)" value="${esc(description)}">
                <select class="ins-form-select pb-form-step__type">
                    <option value="task" ${type === 'task' ? 'selected' : ''}>Task</option>
                    <option value="research" ${type === 'research' ? 'selected' : ''}>Research</option>
                    <option value="analysis" ${type === 'analysis' ? 'selected' : ''}>Analysis</option>
                    <option value="review" ${type === 'review' ? 'selected' : ''}>Review</option>
                    <option value="capture" ${type === 'capture' ? 'selected' : ''}>Capture</option>
                    <option value="compare" ${type === 'compare' ? 'selected' : ''}>Compare</option>
                </select>
            </div>
        </div>
    `;
}

/**
 * Add a new step row to the create/edit form.
 */
function _addStepFormRow() {
    const container = document.getElementById('pbFormSteps');
    if (!container) return;

    const currentRows = container.querySelectorAll('.pb-form-step');
    const newIndex = currentRows.length;
    container.insertAdjacentHTML('beforeend', _renderStepFormRow(newIndex));
}

/**
 * Remove a step row from the create/edit form.
 */
function _removeStepFormRow(btnEl) {
    const row = btnEl.closest('.pb-form-step');
    if (!row) return;

    const container = document.getElementById('pbFormSteps');
    const rows = container.querySelectorAll('.pb-form-step');
    if (rows.length <= 1) {
        showToast('Playbook must have at least one step');
        return;
    }

    row.remove();
    // Re-number remaining steps
    _renumberStepRows();
}

/**
 * Re-number step rows after adding/removing.
 */
function _renumberStepRows() {
    const container = document.getElementById('pbFormSteps');
    if (!container) return;

    const rows = container.querySelectorAll('.pb-form-step');
    rows.forEach((row, idx) => {
        row.dataset.stepFormIndex = String(idx);
        const numEl = row.querySelector('.pb-form-step__num');
        if (numEl) numEl.textContent = String(idx + 1);
    });
}

/**
 * Submit the create/edit playbook form.
 */
async function _submitPlaybookForm() {
    const submitBtn = document.getElementById('pbFormSubmit');
    const nameInput = document.getElementById('pbFormName');
    const descInput = document.getElementById('pbFormDescription');
    const catInput = document.getElementById('pbFormCategory');

    const name = (nameInput?.value || '').trim();
    if (!name) {
        showToast('Name is required');
        return;
    }

    // Collect steps from form
    const stepRows = document.querySelectorAll('#pbFormSteps .pb-form-step');
    const steps = [];
    for (const row of stepRows) {
        const titleEl = row.querySelector('.pb-form-step__title');
        const descEl = row.querySelector('.pb-form-step__desc');
        const typeEl = row.querySelector('.pb-form-step__type');

        const stepTitle = (titleEl?.value || '').trim();
        if (!stepTitle) continue; // skip empty steps

        const step = { title: stepTitle };
        const stepDesc = (descEl?.value || '').trim();
        if (stepDesc) step.description = stepDesc;
        const stepType = typeEl?.value || 'task';
        if (stepType !== 'task') step.type = stepType;

        steps.push(step);
    }

    if (steps.length === 0) {
        showToast('At least one step with a title is required');
        return;
    }

    const mode = submitBtn.dataset.mode;
    const pbId = submitBtn.dataset.pbId;
    submitBtn.disabled = true;

    try {
        const body = {
            name: name,
            steps: steps,
        };
        const desc = (descInput?.value || '').trim();
        if (desc) body.description = desc;
        const cat = (catInput?.value || '').trim();
        if (cat) body.category = cat;

        if (mode === 'create') {
            const resp = await safeFetch('/api/playbooks', {
                method: 'POST',
                headers: csrfHeaders(),
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showToast(err.error || 'Failed to create playbook', 'error');
                return;
            }
            showToast('Playbook created');
        } else {
            const resp = await safeFetch(`/api/playbooks/${pbId}`, {
                method: 'PUT',
                headers: csrfHeaders(),
                body: JSON.stringify(body),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showToast(err.error || 'Failed to update playbook', 'error');
                return;
            }
            showToast('Playbook updated');
        }

        _closePlaybookForm();
        await _loadPlaybooks();
    } catch (e) {
        console.error('Playbook form submit failed:', e);
        showToast('Operation failed', 'error');
    } finally {
        submitBtn.disabled = false;
    }
}

/**
 * Close the create/edit playbook modal.
 */
function _closePlaybookForm() {
    const overlay = document.getElementById('pbFormModal');
    if (!overlay) return;
    overlay.classList.remove('visible');
    setTimeout(() => { overlay.style.display = 'none'; }, 200);
}

/**
 * Seed the default built-in templates.
 */
async function _seedTemplates() {
    const btn = document.getElementById('pbSeedBtn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Seeding...';
    }

    try {
        const resp = await safeFetch('/api/playbooks/templates/seed', {
            method: 'POST',
            headers: csrfHeaders(),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to seed templates', 'error');
            return;
        }

        const data = await resp.json();
        const count = data.seeded || data.count || 0;
        showToast(`Seeded ${count} template${count !== 1 ? 's' : ''}`);
        await _loadPlaybooks();
    } catch (e) {
        console.warn('Failed to seed templates:', e);
        showToast('Failed to seed templates', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'Seed Templates';
        }
    }
}

/**
 * Duplicate a playbook (creates a copy).
 */
async function _duplicatePlaybook(playbookId) {
    try {
        const resp = await safeFetch(`/api/playbooks/${playbookId}/duplicate`, {
            method: 'POST',
            headers: csrfHeaders(),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to duplicate playbook', 'error');
            return;
        }

        showToast('Playbook duplicated');
        await _loadPlaybooks();
    } catch (e) {
        console.warn('Failed to duplicate playbook:', e);
        showToast('Failed to duplicate playbook', 'error');
    }
}

/**
 * Delete a playbook (with confirmation). Templates cannot be deleted.
 */
async function _deletePlaybook(playbookId) {
    const confirmed = await window.showNativeConfirm({
        title: 'Delete Playbook',
        message: 'This will permanently remove this playbook and all its data.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await safeFetch(`/api/playbooks/${playbookId}`, {
            method: 'DELETE',
            headers: csrfHeaders(),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast(err.error || 'Failed to delete playbook', 'error');
            return;
        }

        // Animate card out
        const card = document.querySelector(`[data-playbook-id="${playbookId}"]`);
        if (card) {
            card.style.opacity = '0';
            card.style.transform = 'translateY(10px)';
            setTimeout(() => {
                _playbooksList = _playbooksList.filter(p => p.id !== playbookId);
                _renderPlaybookCards(_playbooksList);
            }, 200);
        } else {
            _playbooksList = _playbooksList.filter(p => p.id !== playbookId);
            _renderPlaybookCards(_playbooksList);
        }

        showToast('Playbook deleted');
    } catch (e) {
        console.warn('Failed to delete playbook:', e);
        showToast('Failed to delete playbook', 'error');
    }
}

/**
 * Request AI-generated improvement suggestions for a playbook.
 */
async function _improvePlaybook(playbookId) {
    const suggestionsEl = document.getElementById('pbSuggestions');
    if (!suggestionsEl) return;

    suggestionsEl.classList.remove('hidden');
    suggestionsEl.innerHTML = '<div class="pb-loading">Generating suggestions...</div>';

    try {
        const resp = await safeFetch(`/api/playbooks/${playbookId}/improve`, {
            method: 'POST',
            headers: csrfHeaders(),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            suggestionsEl.innerHTML = `<div class="pb-suggestions__error">${esc(err.error || 'Failed to generate suggestions')}</div>`;
            return;
        }

        const data = await resp.json();
        _renderSuggestions(playbookId, data);
    } catch (e) {
        console.warn('Failed to improve playbook:', e);
        suggestionsEl.innerHTML = '<div class="pb-suggestions__error">Failed to generate suggestions</div>';
    }
}

/**
 * Render AI improvement suggestions.
 */
function _renderSuggestions(playbookId, data) {
    const suggestionsEl = document.getElementById('pbSuggestions');
    if (!suggestionsEl) return;

    const suggestions = data.suggestions || data.improvements || [];
    const summary = data.summary || data.analysis || '';

    if (!suggestions.length && !summary) {
        suggestionsEl.innerHTML = `
            <div class="pb-suggestions__header">
                <span class="pb-suggestions__title">AI Suggestions</span>
                <button class="ins-btn ins-btn-sm ins-btn-ghost" onclick="_closeSuggestions()">Close</button>
            </div>
            <div class="pb-suggestions__empty">No suggestions available for this playbook.</div>
        `;
        return;
    }

    suggestionsEl.innerHTML = `
        <div class="pb-suggestions__header">
            <span class="pb-suggestions__title">AI Suggestions</span>
            <button class="ins-btn ins-btn-sm ins-btn-ghost" onclick="_closeSuggestions()">Close</button>
        </div>
        ${summary ? `<div class="pb-suggestions__summary">${esc(summary)}</div>` : ''}
        ${suggestions.length > 0 ? `
            <div class="pb-suggestions__list">
                ${suggestions.map(s => `
                    <div class="pb-suggestions__item">
                        <div class="pb-suggestions__item-text">${esc(typeof s === 'string' ? s : (s.suggestion || s.text || ''))}</div>
                    </div>
                `).join('')}
            </div>
        ` : ''}
    `;
}

/**
 * Close the suggestions panel.
 */
function _closeSuggestions() {
    const el = document.getElementById('pbSuggestions');
    if (el) el.classList.add('hidden');
}

// ── Modal Builders ─────────────────────────────────────────────

/**
 * Create the playbook create/edit modal if it does not already exist.
 */
function _ensurePlaybookFormModal() {
    if (document.getElementById('pbFormModal')) return;

    const html = `
        <div id="pbFormModal" class="confirm-sheet-overlay" style="display:none;">
            <div class="confirm-sheet pb-modal">
                <div id="pbFormTitle" class="confirm-sheet-title ins-modal-title">New Playbook</div>
                <div class="pb-modal-form">
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="pbFormName">Name</label>
                        <input id="pbFormName" type="text" class="ins-form-input"
                               placeholder="e.g. Market Entry Assessment">
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="pbFormDescription">Description (optional)</label>
                        <textarea id="pbFormDescription" class="ins-form-textarea"
                                  placeholder="What does this playbook help achieve?" rows="2"></textarea>
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label" for="pbFormCategory">Category (optional)</label>
                        <input id="pbFormCategory" type="text" class="ins-form-input"
                               placeholder="e.g. market, product, competitive">
                    </div>
                    <div class="ins-form-field">
                        <label class="ins-form-label">Steps</label>
                        <div id="pbFormSteps" class="pb-form-steps"></div>
                        <button type="button" class="ins-btn ins-btn-sm ins-btn-ghost"
                                onclick="_addStepFormRow()" style="margin-top:var(--space-2);">+ Add Step</button>
                    </div>
                </div>
                <div class="confirm-sheet-actions" style="margin-top:var(--space-4);">
                    <button id="pbFormSubmit" class="confirm-btn-primary" style="border-radius:0;"
                            onclick="_submitPlaybookForm()">Create</button>
                    <button class="confirm-btn-cancel" style="border-radius:0;"
                            onclick="_closePlaybookForm()">Cancel</button>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', html);
}

// ── Helpers ────────────────────────────────────────────────────

/**
 * Format an ISO date string as a human-readable relative time.
 */
function _pbRelativeTime(isoString) {
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
 * Format a run status string for display.
 */
function _formatRunStatus(status) {
    const labels = {
        in_progress: 'In Progress',
        completed: 'Completed',
        abandoned: 'Abandoned',
    };
    return labels[status] || (status || '').replace(/_/g, ' ');
}

// ── Expose on window ──────────────────────────────────────────

window._switchPlaybookView = _switchPlaybookView;
window._loadPlaybooks = _loadPlaybooks;
window._loadActiveRuns = _loadActiveRuns;
window._viewRunDetail = _viewRunDetail;
window._backToRunsList = _backToRunsList;
window._completeStep = _completeStep;
window._onStepCheckChange = _onStepCheckChange;
window._saveStepNotes = _saveStepNotes;
window._updateRunStatus = _updateRunStatus;
window._startRun = _startRun;
window._createPlaybook = _createPlaybook;
window._editPlaybook = _editPlaybook;
window._submitPlaybookForm = _submitPlaybookForm;
window._closePlaybookForm = _closePlaybookForm;
window._seedTemplates = _seedTemplates;
window._duplicatePlaybook = _duplicatePlaybook;
window._deletePlaybook = _deletePlaybook;
window._improvePlaybook = _improvePlaybook;
window._closeSuggestions = _closeSuggestions;
window._toggleGuidance = _toggleGuidance;
window._addStepFormRow = _addStepFormRow;
window._removeStepFormRow = _removeStepFormRow;
