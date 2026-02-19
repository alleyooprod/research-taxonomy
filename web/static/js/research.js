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
    document.getElementById('quickReportModeBtn').classList.toggle('active', mode === 'report');
    document.getElementById('deepDiveModeBtn').classList.toggle('active', mode === 'deepdive');

    if (mode === 'deepdive') {
        loadSavedResearch();
        loadResearchTemplates();
    }
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
            <div class="research-company-option" onclick="selectResearchCompany(${c.id}, '${escAttr(c.name)}')">
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
        `<button class="research-template-btn" onclick="applyResearchTemplate(${t.id})">${esc(t.name)}</button>`
    ).join('') +
    `<button class="research-template-btn research-template-manage" onclick="openTemplateManager()" title="Manage templates">
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
                <button class="btn btn-sm" onclick="editTemplate(${t.id})">Edit</button>
                <button class="btn btn-sm" style="color:var(--accent-danger)" onclick="deleteTemplate(${t.id})">Delete</button>
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
        <button class="btn" onclick="startDeepDive()" style="margin-top:8px">
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
            <button class="btn" onclick="startDeepDive()" style="margin-top:8px">
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
                <button class="btn" onclick="exportResearchMd(${researchId})">Export .md</button>
                <button class="btn" onclick="exportResearchPdf()">Export PDF</button>
                <button class="btn" onclick="startPresentation('report')"><span class="material-symbols-outlined" style="font-size:14px;vertical-align:middle">slideshow</span> Present</button>
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
                    ? `<button class="btn" onclick="viewSavedResearch(${r.id})">View</button>
                       <button class="btn" onclick="exportResearchMd(${r.id})">MD</button>`
                    : r.status === 'running'
                    ? '<span class="hint-text">Running...</span>'
                    : `<span class="re-research-error" style="font-size:12px">Failed</span>`
                }
                <button class="btn" style="color:var(--accent-danger)" onclick="deleteResearch(${r.id})">Delete</button>
            </div>
        </div>`;
    }).join('');
}

async function viewSavedResearch(researchId) {
    await loadResearchDetail(researchId);
}

async function deleteResearch(researchId) {
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
