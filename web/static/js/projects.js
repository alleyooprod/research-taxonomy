/**
 * Project selection and creation.
 */

async function loadProjects() {
    const res = await safeFetch('/api/projects');
    const projects = await res.json();

    let html = projects.map(p => `
        <div class="project-card" onclick="selectProject(${p.id}, '${escAttr(p.name)}')">
            <h3>${esc(p.name)}</h3>
            <p class="project-purpose">${esc(p.purpose || '')}</p>
            <div class="project-meta">
                <span>${p.company_count} companies</span>
                <span>${new Date(p.created_at).toLocaleDateString()}</span>
            </div>
        </div>
    `).join('');

    html += `
        <div class="project-card project-card-new" onclick="showNewProjectForm()">
            <div class="project-card-plus">+</div>
            <h3>New Project</h3>
            <p class="project-purpose">Create a new research taxonomy</p>
        </div>
    `;

    document.getElementById('projectGrid').innerHTML = html;
}

function selectProject(id, name) {
    currentProjectId = id;
    document.getElementById('projectTitle').textContent = name;

    document.getElementById('exportJson').href = `/api/export/json?project_id=${id}`;
    document.getElementById('exportMd').href = `/api/export/md?project_id=${id}`;
    document.getElementById('exportCsv').href = `/api/export/csv?project_id=${id}`;

    document.getElementById('projectSelection').classList.add('hidden');
    document.getElementById('newProjectForm').classList.add('hidden');
    document.getElementById('mainApp').classList.remove('hidden');

    activeFilters = { category_id: null, category_name: null, tags: [], geography: null, funding_stage: null, founded_from: null, founded_to: null };
    renderFilterChips();

    loadStats();
    loadCompanies();
    loadTaxonomy();
    loadFilterOptions();
    loadSavedViews();
    if (typeof resetCanvasState === 'function') resetCanvasState();
    document.getElementById('chatToggle').classList.remove('hidden');
    document.getElementById('tourBtn')?.classList.remove('hidden');
    connectSSE();
    requestNotificationPermission();

    // Update tab indicator now that #mainApp is visible and tabs have layout
    requestAnimationFrame(() => {
        if (typeof updateTabIndicator === 'function') updateTabIndicator();
        if (typeof initTooltips === 'function') initTooltips();
    });
}

function switchProject() {
    currentProjectId = null;
    document.getElementById('mainApp').classList.add('hidden');
    document.getElementById('projectSelection').classList.remove('hidden');
    document.getElementById('chatToggle').classList.add('hidden');
    closeChat();
    if (eventSource) { eventSource.close(); eventSource = null; }
    loadProjects();
}

function showProjectSelection() {
    document.getElementById('newProjectForm').classList.add('hidden');
    document.getElementById('projectSelection').classList.remove('hidden');
}

function showNewProjectForm() {
    document.getElementById('projectSelection').classList.add('hidden');
    document.getElementById('newProjectForm').classList.remove('hidden');
    document.getElementById('npName').value = '';
    document.getElementById('npPurpose').value = '';
    document.getElementById('npOutcome').value = '';
    document.getElementById('npCategories').value = '';
    document.getElementById('npLinks').value = '';
    document.getElementById('npKeywords').value = '';
    document.getElementById('npDescription').value = '';
}

async function createProject(event) {
    event.preventDefault();
    const data = {
        name: document.getElementById('npName').value,
        purpose: document.getElementById('npPurpose').value,
        outcome: document.getElementById('npOutcome').value,
        seed_categories: document.getElementById('npCategories').value,
        example_links: document.getElementById('npLinks').value,
        market_keywords: document.getElementById('npKeywords').value,
        description: document.getElementById('npDescription').value,
    };

    const res = await safeFetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    const result = await res.json();

    if (result.error) {
        showToast(result.error || 'An error occurred');
        return;
    }

    selectProject(result.id, data.name);
}
