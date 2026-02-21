/**
 * Project selection and creation.
 * Includes schema template picker and AI schema suggestion.
 */

// State for project setup
let _selectedTemplate = 'blank';
let _customSchema = null;  // Set when AI suggests or user provides custom schema
let _schemaTemplates = [];

async function loadProjects() {
    const newProjectCard = `
        <div class="project-card project-card-new" onclick="showNewProjectForm()">
            <div class="project-card-plus">+</div>
            <h3>New Project</h3>
            <p class="project-purpose">Create a new research project</p>
        </div>
    `;

    try {
        const res = await safeFetch('/api/projects');
        if (!res.ok) {
            console.error('Failed to load projects:', res.status);
            document.getElementById('projectGrid').innerHTML = newProjectCard;
            return;
        }
        const projects = await res.json();
        if (!Array.isArray(projects)) {
            console.error('Expected array of projects, got:', typeof projects, projects);
            document.getElementById('projectGrid').innerHTML = newProjectCard;
            return;
        }

        let html = projects.map(p => {
            const entitySchema = p.entity_schema ? JSON.parse(p.entity_schema) : null;
            const typeCount = entitySchema ? entitySchema.entity_types?.length || 0 : 0;
            const metaLabel = typeCount > 1 ? `${typeCount} entity types` : `${p.company_count} companies`;
            return `
            <div class="project-card" onclick="selectProject(${p.id}, '${escAttr(p.name)}')">
                <button class="project-card-delete" onclick="event.stopPropagation(); confirmDeleteProjectFromGrid(${p.id}, '${escAttr(p.name)}')"
                        aria-label="Delete project" title="Delete project">
                    <span class="material-symbols-outlined icon-16">delete</span>
                </button>
                <h3>${esc(p.name)}</h3>
                <p class="project-purpose">${esc(p.purpose || '')}</p>
                <div class="project-meta">
                    <span>${metaLabel}</span>
                    <span>${new Date(p.created_at).toLocaleDateString()}</span>
                </div>
            </div>
        `}).join('');

        html += newProjectCard;
        document.getElementById('projectGrid').innerHTML = html;
    } catch (e) {
        console.error('Error loading projects:', e);
        document.getElementById('projectGrid').innerHTML = newProjectCard;
    }
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

    // Load entity schema for this project
    _loadProjectSchema(id);

    // Update tab indicator now that #mainApp is visible and tabs have layout
    requestAnimationFrame(() => {
        if (typeof updateTabIndicator === 'function') updateTabIndicator();
        if (typeof initTooltips === 'function') initTooltips();
    });
}

async function _loadProjectSchema(projectId) {
    try {
        const res = await safeFetch(`/api/projects/${projectId}`);
        const project = await res.json();
        if (project.entity_schema) {
            window._currentProjectSchema = typeof project.entity_schema === 'string'
                ? JSON.parse(project.entity_schema)
                : project.entity_schema;
        } else {
            window._currentProjectSchema = null;
        }
    } catch (e) {
        window._currentProjectSchema = null;
    }

    // Initialize entity browser if schema has multiple types
    if (typeof initEntityBrowser === 'function') {
        initEntityBrowser();
    }
}

function switchProject() {
    currentProjectId = null;
    window._currentProjectSchema = null;
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

async function showNewProjectForm() {
    document.getElementById('projectSelection').classList.add('hidden');
    document.getElementById('newProjectForm').classList.remove('hidden');
    document.getElementById('npName').value = '';
    document.getElementById('npPurpose').value = '';
    document.getElementById('npOutcome').value = '';
    document.getElementById('npCategories').value = '';
    document.getElementById('npLinks').value = '';
    document.getElementById('npKeywords').value = '';
    document.getElementById('npDescription').value = '';
    document.getElementById('npAiDescription').value = '';
    document.getElementById('npTemplate').value = 'blank';
    _selectedTemplate = 'blank';
    _customSchema = null;

    // Load templates and render picker
    await _loadSchemaTemplates();
    _renderTemplatePicker();
    _renderSchemaPreview();
}

async function _loadSchemaTemplates() {
    if (_schemaTemplates.length > 0) return;
    try {
        const res = await safeFetch('/api/schema/templates');
        _schemaTemplates = await res.json();
    } catch (e) {
        _schemaTemplates = [];
    }
}

function _renderTemplatePicker() {
    const picker = document.getElementById('templatePicker');
    if (!picker || _schemaTemplates.length === 0) return;

    const icons = {
        blank: '&#9634;',           // empty square
        market_analysis: '&#9635;', // filled square
        product_analysis: '&#9881;', // gear
        design_research: '&#9830;', // diamond
    };

    picker.innerHTML = _schemaTemplates.map(t => `
        <div class="template-card ${t.key === _selectedTemplate ? 'template-card-selected' : ''}"
             onclick="_selectTemplate('${escAttr(t.key)}')" data-template="${escAttr(t.key)}">
            <div class="template-icon">${icons[t.key] || '&#9679;'}</div>
            <div class="template-info">
                <strong>${esc(t.name)}</strong>
                <span>${esc(t.description)}</span>
            </div>
            <div class="template-types">${t.entity_types.map(et =>
                `<span class="template-type-tag">${esc(et.name)}</span>`
            ).join(' ')}</div>
        </div>
    `).join('');
}

function _selectTemplate(key) {
    _selectedTemplate = key;
    _customSchema = null;
    document.getElementById('npTemplate').value = key;

    // Update visual selection
    document.querySelectorAll('.template-card').forEach(c => {
        c.classList.toggle('template-card-selected', c.dataset.template === key);
    });

    _renderSchemaPreview();
}

function _renderSchemaPreview() {
    const preview = document.getElementById('schemaPreview');
    const content = document.getElementById('schemaPreviewContent');
    if (!preview || !content) return;

    // Determine which schema to show
    let schema = _customSchema;
    if (!schema) {
        const tmpl = _schemaTemplates.find(t => t.key === _selectedTemplate);
        if (!tmpl) {
            preview.classList.add('hidden');
            return;
        }
        // Build a light preview from template data
        content.innerHTML = _renderTypesList(tmpl.entity_types);
        preview.classList.remove('hidden');
        return;
    }

    // Full schema preview (from AI suggestion or custom)
    const types = schema.entity_types || [];
    const rels = schema.relationships || [];

    let html = _renderTypesList(types.map(et => ({
        name: et.name,
        slug: et.slug,
        parent_type: et.parent_type,
        attributes: et.attributes,
    })));

    if (rels.length > 0) {
        html += `<div class="schema-rels"><strong>Relationships:</strong> ${rels.map(r =>
            `<span class="template-type-tag">${esc(r.from_type)} &rarr; ${esc(r.to_type)} (${esc(r.name)})</span>`
        ).join(' ')}</div>`;
    }

    content.innerHTML = html;
    preview.classList.remove('hidden');
}

function _renderTypesList(types) {
    return `<div class="schema-types">${types.map(et => {
        const indent = et.parent_type ? 'schema-type-child' : '';
        const attrCount = et.attributes ? et.attributes.length : 0;
        const attrLabel = attrCount > 0 ? `<span class="schema-attr-count">${attrCount} attrs</span>` : '';
        const parentLabel = et.parent_type ? `<span class="schema-parent-label">&larr; ${esc(et.parent_type)}</span>` : '';
        return `<div class="schema-type-row ${indent}">
            <span class="template-type-tag">${esc(et.name)}</span>
            ${parentLabel}${attrLabel}
        </div>`;
    }).join('')}</div>`;
}

async function suggestSchema() {
    const description = document.getElementById('npAiDescription')?.value?.trim();
    if (!description) {
        showToast('Describe your research first');
        return;
    }

    const btn = document.getElementById('aiSuggestBtn');
    const status = document.getElementById('aiSuggestStatus');
    btn.disabled = true;
    btn.textContent = 'Thinking...';
    status.classList.remove('hidden');
    status.textContent = 'AI is designing a schema for your research...';

    try {
        const res = await safeFetch('/api/schema/suggest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                description,
                template: _selectedTemplate,
            }),
        });
        const result = await res.json();

        if (result.error) {
            status.textContent = `Error: ${result.error}`;
            return;
        }

        _customSchema = result.schema;
        status.innerHTML = `<strong>AI suggestion:</strong> ${esc(result.explanation || '')}`;

        // Deselect template cards — custom schema overrides
        document.querySelectorAll('.template-card').forEach(c => c.classList.remove('template-card-selected'));
        document.getElementById('npTemplate').value = 'custom';

        _renderSchemaPreview();
        showToast('Schema suggested — review the preview below');

    } catch (e) {
        status.textContent = 'Failed to get suggestion. Try again.';
    } finally {
        btn.disabled = false;
        btn.textContent = 'Suggest Schema';
    }
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

    // Include schema: custom schema takes priority, then template
    if (_customSchema) {
        data.entity_schema = _customSchema;
    } else {
        data.template = _selectedTemplate || 'blank';
    }

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

async function confirmDeleteProjectFromGrid(projectId, projectName) {
    const confirmed = await showNativeConfirm({
        title: `Delete "${projectName}"?`,
        message: 'This will permanently delete this project and ALL its data. This cannot be undone.',
        confirmText: 'Delete Forever',
        cancelText: 'Cancel',
        type: 'danger',
    });
    if (!confirmed) return;

    const res = await safeFetch(`/api/projects/${projectId}`, { method: 'DELETE' });
    const result = await res.json();
    if (result.error) { showToast(result.error); return; }

    showToast(`"${projectName}" deleted`);
    loadProjects();
}
