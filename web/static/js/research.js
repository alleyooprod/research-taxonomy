/**
 * Deep Dive research: scope-based research with web search, templates, saved library.
 */

let _currentResearchMode = 'report';
let _researchPollCount = 0;
const _MAX_RESEARCH_POLL = 240; // 12 min at 3s (must exceed backend timeout of 10 min)
let _selectedResearchCompanyId = null;
let _researchStartTime = null;

// --- Mode switching ---
function switchResearchMode(mode) {
    _currentResearchMode = mode;
    document.getElementById('researchModeReport').classList.toggle('hidden', mode !== 'report');
    document.getElementById('researchModeDeepDive').classList.toggle('hidden', mode !== 'deepdive');
    document.getElementById('researchModeSetup').classList.toggle('hidden', mode !== 'setup');
    document.getElementById('quickReportModeBtn').classList.toggle('active', mode === 'report');
    document.getElementById('deepDiveModeBtn').classList.toggle('active', mode === 'deepdive');
    document.getElementById('setupModeBtn').classList.toggle('active', mode === 'setup');

    if (mode === 'deepdive') {
        loadSavedResearch();
        loadResearchTemplates();
    }
    if (mode === 'setup') {
        loadProjectSetup();
    }
}

// --- Project Setup View ---
let _editCustomSchema = null;

async function loadProjectSetup() {
    if (!currentProjectId) return;
    const container = document.getElementById('setupContent');
    container.innerHTML = '<p class="hint-text">Loading project setup...</p>';

    try {
        const [projRes, dataRes] = await Promise.all([
            safeFetch(`/api/projects/${currentProjectId}`),
            safeFetch(`/api/projects/${currentProjectId}/has-data`),
        ]);
        const project = await projRes.json();
        const dataCheck = await dataRes.json();

        if (dataCheck.has_data) {
            _renderSetupViewMode(container, project, dataCheck);
        } else {
            _renderSetupEditMode(container, project);
        }
    } catch (e) {
        container.innerHTML = '<p class="hint-text">Failed to load project setup.</p>';
    }
}

function _parseJsonField(val) {
    if (!val) return [];
    if (Array.isArray(val)) return val;
    try { return JSON.parse(val); } catch { return []; }
}

function _renderSetupViewMode(container, project, dataCheck) {
    const schema = project.entity_schema
        ? (typeof project.entity_schema === 'string' ? JSON.parse(project.entity_schema) : project.entity_schema)
        : null;
    const categories = _parseJsonField(project.seed_categories);
    const links = _parseJsonField(project.example_links);
    const keywords = _parseJsonField(project.market_keywords);

    const dataSummary = [];
    if (dataCheck.entity_count > 0) dataSummary.push(`${dataCheck.entity_count} entities`);
    if (dataCheck.company_count > 0) dataSummary.push(`${dataCheck.company_count} companies`);

    let schemaHtml = '<em>Default schema</em>';
    if (schema && schema.entity_types && schema.entity_types.length > 0) {
        schemaHtml = _renderTypesListReadonly(schema.entity_types);
        if (schema.relationships && schema.relationships.length > 0) {
            schemaHtml += `<div class="setup-rels"><strong>Relationships:</strong> ${schema.relationships.map(r =>
                `<span class="template-type-tag">${esc(r.from_type || '')} &rarr; ${esc(r.to_type || '')} (${esc(r.name || '')})</span>`
            ).join(' ')}</div>`;
        }
    }

    container.innerHTML = `
        <div class="setup-readonly-notice">
            This project has ${dataSummary.join(' and ')}. Setup fields are read-only.
        </div>
        <div class="setup-fields">
            <div class="setup-field">
                <label class="setup-label">PROJECT NAME</label>
                <div class="setup-value">${esc(project.name)}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">PURPOSE</label>
                <div class="setup-value">${esc(project.purpose || '(not set)')}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">EXPECTED OUTCOME</label>
                <div class="setup-value">${esc(project.outcome || '(not set)')}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">ENTITY SCHEMA</label>
                <div class="setup-value setup-schema">${schemaHtml}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">STARTING CATEGORIES</label>
                <div class="setup-value">${categories.length ? categories.map(c => esc(c)).join('<br>') : '<em>None</em>'}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">EXAMPLE LINKS</label>
                <div class="setup-value">${links.length ? links.map(l => `<a href="${esc(l)}" target="_blank" rel="noopener">${esc(l)}</a>`).join('<br>') : '<em>None</em>'}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">MARKET KEYWORDS</label>
                <div class="setup-value">${keywords.length ? keywords.map(k => esc(k)).join(', ') : '<em>None</em>'}</div>
            </div>
            <div class="setup-field">
                <label class="setup-label">DESCRIPTION</label>
                <div class="setup-value">${esc(project.description || '(not set)')}</div>
            </div>
        </div>
        <div class="setup-danger-zone">
            <button class="btn btn-danger" data-action="confirm-delete-project">Delete Project</button>
        </div>
    `;
}

function _renderTypesListReadonly(types) {
    return `<div class="schema-types">${types.map(et => {
        const indent = et.parent_type ? 'schema-type-child' : '';
        const attrs = et.attributes || [];
        const attrLabel = attrs.length > 0
            ? `<span class="schema-attr-count">${attrs.length} attrs</span>` : '';
        const parentLabel = et.parent_type
            ? `<span class="schema-parent-label">&larr; ${esc(et.parent_type)}</span>` : '';
        const attrList = attrs.length > 0
            ? `<div class="schema-attr-list">${attrs.map(a =>
                `<span class="schema-attr-tag">${esc(a.name || a.slug)} <span class="schema-attr-type">${esc(a.type || 'text')}</span></span>`
            ).join(' ')}</div>` : '';
        return `<div class="schema-type-row ${indent}">
            <span class="template-type-tag">${esc(et.name)}</span>
            ${parentLabel}${attrLabel}
            ${attrList}
        </div>`;
    }).join('')}</div>`;
}

function _renderSetupEditMode(container, project) {
    const schema = project.entity_schema
        ? (typeof project.entity_schema === 'string' ? JSON.parse(project.entity_schema) : project.entity_schema)
        : null;
    const categories = _parseJsonField(project.seed_categories);
    const links = _parseJsonField(project.example_links);
    const keywords = _parseJsonField(project.market_keywords);
    _editCustomSchema = schema;

    let schemaPreviewHtml = '';
    if (schema && schema.entity_types) {
        schemaPreviewHtml = _renderTypesListReadonly(schema.entity_types);
    }

    container.innerHTML = `
        <div class="setup-editable-notice">
            No entities or companies added yet. All fields are editable.
        </div>
        <div class="setup-form">
            <div class="form-group full-width">
                <label for="epName">Project Name *</label>
                <input type="text" id="epName" value="${escAttr(project.name)}" required>
            </div>
            <div class="form-group full-width">
                <label for="epPurpose">Purpose *</label>
                <textarea id="epPurpose" rows="3">${esc(project.purpose || '')}</textarea>
            </div>
            <div class="form-group full-width">
                <label for="epOutcome">Expected Outcome</label>
                <textarea id="epOutcome" rows="2">${esc(project.outcome || '')}</textarea>
            </div>

            <div class="form-group full-width">
                <label class="setup-label">ENTITY SCHEMA</label>
                <div class="setup-schema-preview">${schemaPreviewHtml || '<em>Default schema</em>'}</div>
                <p class="form-hint">To change the schema, switch to the Process tab and use the entity browser's schema tools.</p>
            </div>

            <div class="form-group full-width">
                <label for="epCategories">Starting Categories</label>
                <textarea id="epCategories" rows="3" placeholder="One per line">${categories.join('\n')}</textarea>
            </div>
            <div class="form-group full-width">
                <label for="epLinks">Example Links</label>
                <textarea id="epLinks" rows="3" placeholder="One URL per line">${links.join('\n')}</textarea>
            </div>
            <div class="form-group full-width">
                <label for="epKeywords">Market Keywords</label>
                <input type="text" id="epKeywords" value="${escAttr(keywords.join(', '))}" placeholder="Comma-separated">
            </div>
            <div class="form-group full-width">
                <label for="epDescription">Description</label>
                <textarea id="epDescription" rows="3">${esc(project.description || '')}</textarea>
            </div>
            <div class="form-actions">
                <button class="primary-btn" data-action="save-project-setup">Save Changes</button>
            </div>
        </div>
        <div class="setup-danger-zone">
            <button class="btn btn-danger" data-action="confirm-delete-project">Delete Project</button>
        </div>
    `;
}

async function saveProjectSetup() {
    const name = document.getElementById('epName')?.value?.trim();
    if (!name) { showToast('Project name is required'); return; }

    const categories = (document.getElementById('epCategories')?.value || '')
        .split('\n').filter(s => s.trim());
    const links = (document.getElementById('epLinks')?.value || '')
        .split('\n').filter(s => s.trim());
    const keywords = (document.getElementById('epKeywords')?.value || '')
        .split(',').map(s => s.trim()).filter(Boolean);

    const data = {
        name,
        purpose: document.getElementById('epPurpose')?.value || '',
        outcome: document.getElementById('epOutcome')?.value || '',
        seed_categories: JSON.stringify(categories),
        example_links: JSON.stringify(links),
        market_keywords: JSON.stringify(keywords),
        description: document.getElementById('epDescription')?.value || '',
    };

    const res = await safeFetch(`/api/projects/${currentProjectId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    const result = await res.json();
    if (result.error) { showToast(result.error); return; }

    showToast('Project setup saved');
    document.getElementById('projectTitle').textContent = name;
}

async function confirmDeleteProject() {
    const confirmed = await showNativeConfirm({
        title: 'Delete Project',
        message: 'This will permanently delete this project and ALL its data (entities, evidence, reports, everything). This cannot be undone.',
        confirmText: 'Delete Forever',
        cancelText: 'Cancel',
        type: 'danger',
    });
    if (!confirmed) return;

    const res = await safeFetch(`/api/projects/${currentProjectId}`, { method: 'DELETE' });
    const result = await res.json();
    if (result.error) { showToast(result.error); return; }

    showToast('Project deleted');
    switchProject();
}

// --- Scope selector ---
function onResearchScopeChange() {
    const scopeType = document.getElementById('researchScopeType').value;
    const scopeSelect = document.getElementById('researchScopeId');
    const companySearch = document.getElementById('researchCompanySearch');
    const companyResults = document.getElementById('researchCompanyResults');

    scopeSelect.classList.add('hidden');
    companySearch.classList.add('hidden');
    companyResults.classList.add('hidden');
    _selectedResearchCompanyId = null;

    if (scopeType === 'category') {
        scopeSelect.classList.remove('hidden');
        loadResearchCategories();
    } else if (scopeType === 'company') {
        companySearch.classList.remove('hidden');
        companySearch.value = '';
    }
}

async function loadResearchCategories() {
    const res = await safeFetch(`/api/taxonomy?project_id=${currentProjectId}`);
    const cats = await res.json();
    const topLevel = cats.filter(c => !c.parent_id);
    const sel = document.getElementById('researchScopeId');
    sel.innerHTML = '<option value="">Select category...</option>' +
        topLevel.map(c => `<option value="${c.id}">${esc(c.name)} (${c.company_count})</option>`).join('');
}

let _companySearchTimeout = null;
function searchResearchCompany() {
    clearTimeout(_companySearchTimeout);
    const q = document.getElementById('researchCompanySearch').value.trim();
    if (q.length < 2) {
        document.getElementById('researchCompanyResults').classList.add('hidden');
        return;
    }
    _companySearchTimeout = setTimeout(async () => {
        const res = await safeFetch(`/api/companies?project_id=${currentProjectId}&search=${encodeURIComponent(q)}&limit=8`);
        const companies = await res.json();
        const container = document.getElementById('researchCompanyResults');
        if (!companies.length) {
            container.classList.add('hidden');
            return;
        }
        container.classList.remove('hidden');
        container.innerHTML = companies.map(c => `
            <div class="research-company-option" data-action="select-research-company" data-id="${c.id}" data-value="${escAttr(c.name)}">
                <strong>${esc(c.name)}</strong>
                <span class="hint-text">${esc(c.category_name || '')}</span>
            </div>
        `).join('');
    }, 300);
}

function selectResearchCompany(id, name) {
    _selectedResearchCompanyId = id;
    document.getElementById('researchCompanySearch').value = name;
    document.getElementById('researchCompanyResults').classList.add('hidden');
}

// --- Templates (DB-backed) ---
let _researchTemplates = [];

async function loadResearchTemplates() {
    const res = await safeFetch(`/api/research/templates?project_id=${currentProjectId}`);
    _researchTemplates = await res.json();
    renderTemplateButtons();
}

function renderTemplateButtons() {
    const container = document.getElementById('researchTemplateButtons');
    if (!container) return;
    container.innerHTML = _researchTemplates.map(t =>
        `<button class="research-template-btn" data-action="apply-research-template" data-id="${t.id}">${esc(t.name)}</button>`
    ).join('') +
    `<button class="research-template-btn research-template-manage" data-action="open-template-manager" title="Manage templates">
        <span class="material-symbols-outlined" style="font-size:14px">settings</span>
    </button>`;
}

function _getScopeLabel() {
    const scopeType = document.getElementById('researchScopeType').value;
    if (scopeType === 'category') {
        const sel = document.getElementById('researchScopeId');
        const opt = sel.options[sel.selectedIndex];
        if (opt && opt.value) return opt.text.replace(/\s*\(\d+\)$/, '');
    } else if (scopeType === 'company') {
        const name = document.getElementById('researchCompanySearch').value.trim();
        if (name) return name;
    }
    return 'this market';
}

function applyResearchTemplate(idOrKey) {
    const scopeLabel = _getScopeLabel();
    // Support both old string keys (for backward compat) and new numeric IDs
    let template;
    if (typeof idOrKey === 'number') {
        template = _researchTemplates.find(t => t.id === idOrKey);
    }
    if (!template) return;
    const prompt = (template.prompt_template || '').replace(/\{scope\}/g, scopeLabel)
        .replace(/\{company_name\}/g, scopeLabel)
        .replace(/\{category_name\}/g, scopeLabel)
        .replace(/\{project_name\}/g, 'the project');
    document.getElementById('researchPrompt').value = prompt;
    document.getElementById('researchPrompt').focus();
}

// --- Template Manager ---
function openTemplateManager() {
    const modal = document.getElementById('templateManagerModal');
    modal.classList.remove('hidden');
    renderTemplateManagerList();
    trapFocus(modal);
}

function closeTemplateManager() {
    document.getElementById('templateManagerModal').classList.add('hidden');
}

function renderTemplateManagerList() {
    const list = document.getElementById('templateManagerList');
    list.innerHTML = _researchTemplates.map(t => `
        <div class="template-item">
            <div class="template-item-header">
                <strong>${esc(t.name)}</strong>
                ${t.is_default ? '<span class="hint-text">(default)</span>' : ''}
            </div>
            <div class="template-item-body hint-text">${esc((t.prompt_template || '').substring(0, 120))}...</div>
            <div class="template-item-actions">
                <button class="btn btn-sm" data-action="edit-template" data-id="${t.id}">Edit</button>
                <button class="btn btn-sm" style="color:var(--accent-danger)" data-action="delete-template" data-id="${t.id}">Delete</button>
            </div>
        </div>
    `).join('');
}

function showAddTemplateForm() {
    document.getElementById('templateFormTitle').textContent = 'New Template';
    document.getElementById('templateFormId').value = '';
    document.getElementById('templateFormName').value = '';
    document.getElementById('templateFormPrompt').value = '';
    document.getElementById('templateFormSection').classList.remove('hidden');
}

function editTemplate(id) {
    const t = _researchTemplates.find(x => x.id === id);
    if (!t) return;
    document.getElementById('templateFormTitle').textContent = 'Edit Template';
    document.getElementById('templateFormId').value = id;
    document.getElementById('templateFormName').value = t.name;
    document.getElementById('templateFormPrompt').value = t.prompt_template;
    document.getElementById('templateFormSection').classList.remove('hidden');
}

async function saveTemplate() {
    const id = document.getElementById('templateFormId').value;
    const name = document.getElementById('templateFormName').value.trim();
    const prompt_template = document.getElementById('templateFormPrompt').value.trim();
    if (!name || !prompt_template) { showToast('Name and prompt required'); return; }

    if (id) {
        await safeFetch(`/api/research/templates/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, prompt_template }),
        });
    } else {
        await safeFetch('/api/research/templates', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProjectId, name, prompt_template }),
        });
    }
    document.getElementById('templateFormSection').classList.add('hidden');
    await loadResearchTemplates();
    renderTemplateManagerList();
    showToast('Template saved');
}

async function deleteTemplate(id) {
    const confirmed = await showNativeConfirm({
        title: 'Delete Template',
        message: 'This will permanently remove this research template.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;
    await safeFetch(`/api/research/templates/${id}`, { method: 'DELETE' });
    await loadResearchTemplates();
    renderTemplateManagerList();
    showToast('Template deleted');
}

// --- Start Deep Dive ---
async function startDeepDive() {
    const prompt = document.getElementById('researchPrompt').value.trim();
    if (!prompt) { showToast('Enter a research question'); return; }

    const scopeType = document.getElementById('researchScopeType').value;
    let scopeId = null;
    if (scopeType === 'category') {
        scopeId = document.getElementById('researchScopeId').value || null;
    } else if (scopeType === 'company') {
        scopeId = _selectedResearchCompanyId;
        if (!scopeId) { showToast('Select a company first'); return; }
    }

    let title = document.getElementById('researchTitle').value.trim();
    if (!title) {
        title = prompt.length > 60 ? prompt.substring(0, 57) + '...' : prompt;
    }

    const model = document.getElementById('researchModelSelect').value;
    const btn = document.getElementById('researchBtn');
    btn.disabled = true;

    document.getElementById('researchStatus').classList.remove('hidden');
    document.getElementById('researchResult').classList.add('hidden');

    const res = await safeFetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            title: title,
            scope_type: scopeType,
            scope_id: scopeId ? parseInt(scopeId) : null,
            prompt: prompt,
            model: model,
        }),
    });
    const data = await res.json();
    if (data.error) {
        showToast(data.error);
        btn.disabled = false;
        document.getElementById('researchStatus').classList.add('hidden');
        return;
    }

    _researchPollCount = 0;
    _researchStartTime = Date.now();
    pollResearch(data.research_id);
}

async function pollResearch(researchId) {
    const res = await safeFetch(`/api/research/${researchId}/poll`);
    const data = await res.json();

    if (data.status === 'pending' || data.status === 'running') {
        // Update elapsed time display
        if (_researchStartTime) {
            const elapsed = Math.round((Date.now() - _researchStartTime) / 1000);
            const min = Math.floor(elapsed / 60);
            const sec = elapsed % 60;
            const timeStr = min > 0 ? `${min}m ${sec}s` : `${sec}s`;
            const statusText = document.getElementById('researchStatusText');
            if (statusText) statusText.textContent = `Researching... ${timeStr} elapsed. AI is searching the web and analyzing data.`;
        }
        if (++_researchPollCount > _MAX_RESEARCH_POLL) {
            showResearchError('Research timed out. Please try again with a more focused question.');
            return;
        }
        setTimeout(() => pollResearch(researchId), 3000);
        return;
    }

    _researchPollCount = 0;
    _researchStartTime = null;
    document.getElementById('researchBtn').disabled = false;
    document.getElementById('researchStatus').classList.add('hidden');

    if (data.status === 'failed' || data.status === 'error') {
        loadResearchDetail(researchId);
        return;
    }

    loadResearchDetail(researchId);
    loadSavedResearch();
}

function showResearchError(msg) {
    _researchStartTime = null;
    document.getElementById('researchBtn').disabled = false;
    document.getElementById('researchStatus').classList.add('hidden');
    const content = document.getElementById('researchResult');
    content.classList.remove('hidden');
    content.innerHTML = `<div class="re-research-error">
        <p>${esc(msg)}</p>
        <button class="btn" data-action="start-deep-dive" style="margin-top:8px">
            <span class="material-symbols-outlined" style="font-size:16px;vertical-align:middle">refresh</span> Retry
        </button>
    </div>`;
}

function cancelResearchPoll() {
    _researchPollCount = _MAX_RESEARCH_POLL + 1;
    _researchStartTime = null;
    document.getElementById('researchBtn').disabled = false;
    document.getElementById('researchStatus').classList.add('hidden');
    showToast('Research polling cancelled. The research may still complete on the server.');
}

// --- View research result ---
async function loadResearchDetail(researchId) {
    const res = await safeFetch(`/api/research/${researchId}`);
    const data = await res.json();
    if (!data || data.error) return;

    const content = document.getElementById('researchResult');
    content.classList.remove('hidden');

    if (data.status === 'failed') {
        content.innerHTML = `<div class="re-research-error">
            <p>${esc(data.result || 'Research failed')}</p>
            <button class="btn" data-action="start-deep-dive" style="margin-top:8px">
                <span class="material-symbols-outlined" style="font-size:16px;vertical-align:middle">refresh</span> Retry
            </button>
        </div>`;
        return;
    }

    let html;
    if (window.marked) {
        const renderer = new marked.Renderer();
        const defaultCode = renderer.code.bind(renderer);
        renderer.code = function(args) {
            if (args.lang === 'mermaid') {
                return `<div class="mermaid">${args.text}</div>`;
            }
            if (window.hljs && args.lang && hljs.getLanguage(args.lang)) {
                const highlighted = hljs.highlight(args.text, { language: args.lang }).value;
                return `<pre><code class="hljs language-${esc(args.lang)}">${highlighted}</code></pre>`;
            }
            return defaultCode(args);
        };
        marked.use({ renderer, breaks: true, gfm: true });
        html = sanitize(marked.parse(data.result || ''));
    } else {
        html = esc(data.result || '').replace(/\n/g, '<br>');
    }

    const durationStr = data.duration_ms ? `${(data.duration_ms / 1000).toFixed(0)}s` : '';
    const costStr = data.cost_usd ? `$${data.cost_usd.toFixed(3)}` : '';
    const metaParts = [data.model, durationStr, costStr].filter(Boolean).join(' · ');

    content.innerHTML = `
        <div class="report-header">
            <h3>${esc(data.title)}</h3>
            <div style="display:flex;gap:8px;align-items:center">
                <span class="hint-text">${metaParts}</span>
                <button class="btn" data-action="export-research-md" data-id="${researchId}">Export .md</button>
                <button class="btn" data-action="export-research-pdf">Export PDF</button>
                <button class="btn" data-action="start-presentation" data-value="report"><span class="material-symbols-outlined" style="font-size:14px;vertical-align:middle">slideshow</span> Present</button>
            </div>
        </div>
        <div class="report-body">${html}</div>
    `;

    if (window.mermaid) {
        try { mermaid.run({ nodes: content.querySelectorAll('.mermaid') }); } catch (e) {}
    }
    if (window.hljs) content.querySelectorAll('pre code:not(.hljs)').forEach(el => hljs.highlightElement(el));

    content.scrollIntoView({ behavior: 'smooth' });
}

// --- Export ---
function exportResearchMd(researchId) {
    safeFetch(`/api/research/${researchId}`).then(r => r.json()).then(data => {
        if (!data.result) return;
        const blob = new Blob([`# ${data.title}\n\n${data.result}`], { type: 'text/markdown' });
        if (window.saveAs) saveAs(blob, `research-${researchId}.md`);
    });
}

function exportResearchPdf() {
    const body = document.querySelector('#researchResult .report-body');
    if (!body) return;
    const printWin = window.open('', '_blank');
    printWin.document.write(`<!DOCTYPE html><html><head>
        <title>Research</title>
        <style>
            body { font-family: 'Noto Sans', sans-serif; font-size: 13px; line-height: 1.7; color: #333; max-width: 800px; margin: 0 auto; padding: 40px; }
            h1, h2, h3, h4 { color: #3D4035; }
            table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 12px; }
            th, td { padding: 8px 10px; border: 1px solid #ddd; text-align: left; }
            th { background: #f5f2eb; font-weight: 600; }
            blockquote { margin: 12px 0; padding: 10px 16px; border-left: 3px solid #BC6C5A; background: #fff5f0; }
            a { color: #BC6C5A; }
            .mermaid { display: none; }
        </style>
    </head><body>${body.innerHTML}</body></html>`);
    printWin.document.close();
    printWin.onload = () => { printWin.print(); };
}

// --- Saved research library ---
async function loadSavedResearch() {
    const container = document.getElementById('savedResearchList');
    if (!container) return;

    const res = await safeFetch(`/api/research?project_id=${currentProjectId}`);
    const items = await res.json();

    if (!items.length) {
        container.innerHTML = '<p class="hint-text">No saved research yet. Start a deep dive above.</p>';
        return;
    }

    container.innerHTML = items.map(r => {
        const scopeLabel = r.scope_type === 'project' ? 'Project' :
            r.scope_type === 'custom' ? 'Custom' :
            r.scope_type.charAt(0).toUpperCase() + r.scope_type.slice(1);
        const statusIcon = r.status === 'completed' ? 'check_circle' :
            r.status === 'running' ? 'hourglass_top' :
            r.status === 'failed' ? 'error' : 'schedule';
        const statusClass = r.status === 'completed' ? 'research-status-done' :
            r.status === 'failed' ? 'research-status-failed' : 'research-status-pending';

        return `
        <div class="saved-report-item">
            <div class="saved-report-info">
                <strong>${esc(r.title)}</strong>
                <span class="hint-text">
                    <span class="material-symbols-outlined ${statusClass}" style="font-size:14px;vertical-align:middle">${statusIcon}</span>
                    ${scopeLabel} · ${r.model || ''} · ${new Date(r.created_at).toLocaleDateString()}
                </span>
            </div>
            <div class="saved-report-actions">
                ${r.status === 'completed'
                    ? `<button class="btn" data-action="view-saved-research" data-id="${r.id}">View</button>
                       <button class="btn" data-action="export-research-md" data-id="${r.id}">MD</button>`
                    : r.status === 'running'
                    ? '<span class="hint-text">Running...</span>'
                    : `<span class="re-research-error" style="font-size:12px">Failed</span>`
                }
                <button class="btn" style="color:var(--accent-danger)" data-action="delete-research" data-id="${r.id}">Delete</button>
            </div>
        </div>`;
    }).join('');
}

async function viewSavedResearch(researchId) {
    await loadResearchDetail(researchId);
}

async function deleteResearch(researchId) {
    const confirmed = await showNativeConfirm({
        title: 'Delete Research',
        message: 'This will permanently remove this saved research.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;
    await safeFetch(`/api/research/${researchId}`, { method: 'DELETE' });
    loadSavedResearch();
    showToast('Research deleted');
}

// --- Company detail panel "Research" button support ---
function startCompanyResearch(companyId, companyName) {
    showTab('reports');
    switchResearchMode('deepdive');
    document.getElementById('researchScopeType').value = 'company';
    onResearchScopeChange();
    document.getElementById('researchCompanySearch').value = companyName;
    _selectedResearchCompanyId = companyId;
    document.getElementById('researchPrompt').focus();
}

// ── Action Delegation ─────────────────────────────────────────

registerActions({
    'confirm-delete-project':    () => confirmDeleteProject(),
    'save-project-setup':        () => saveProjectSetup(),
    'select-research-company':   (el) => selectResearchCompany(Number(el.dataset.id), el.dataset.value),
    'apply-research-template':   (el) => applyResearchTemplate(Number(el.dataset.id)),
    'open-template-manager':     () => openTemplateManager(),
    'edit-template':             (el) => editTemplate(Number(el.dataset.id)),
    'delete-template':           (el) => deleteTemplate(Number(el.dataset.id)),
    'start-deep-dive':           () => startDeepDive(),
    'export-research-md':        (el) => exportResearchMd(Number(el.dataset.id)),
    'export-research-pdf':       () => exportResearchPdf(),
    'start-presentation':        (el) => startPresentation(el.dataset.value),
    'view-saved-research':       (el) => viewSavedResearch(Number(el.dataset.id)),
    'delete-research':           (el) => deleteResearch(Number(el.dataset.id)),
    'switch-research-mode':      (el) => switchResearchMode(el.dataset.value),
    'research-scope-change':     () => onResearchScopeChange(),
    'search-research-company':   () => searchResearchCompany(),
    'cancel-research-poll':      () => cancelResearchPoll(),
    'close-template-manager':    () => closeTemplateManager(),
    'save-template':             () => saveTemplate(),
    'show-add-template-form':    () => showAddTemplateForm(),
    'cancel-template-form':      () => document.getElementById('templateFormSection').classList.add('hidden'),
});

// ── Global Exposure (cross-module calls only) ─────────────────

window.switchResearchMode    = switchResearchMode;
window.startCompanyResearch  = startCompanyResearch;
window.startDeepDive         = startDeepDive;
