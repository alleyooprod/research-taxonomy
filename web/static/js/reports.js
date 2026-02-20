/**
 * Reports — generate, view, and export structured reports from project data.
 * Phase 4 of the Research Workbench.
 *
 * Provides:
 * - Template selection with availability checks
 * - Report generation (rule-based and AI-assisted)
 * - Report viewer with sections, evidence references, data tables
 * - Report list management (rename, delete)
 * - Export to HTML, Markdown, JSON
 */

// ── Reports State ────────────────────────────────────────────

let _reportsData = [];              // List of reports from API
let _activeReportId = null;         // Currently viewed report
let _reportTemplate = null;         // Selected template slug for generation

// ── Init ─────────────────────────────────────────────────────

/**
 * Initialize the Reports section — called when the Export tab
 * shows the reports sub-section.
 */
async function initReports() {
    if (!currentProjectId) return;
    _activeReportId = null;
    _reportTemplate = null;
    await Promise.all([
        _loadReportTemplates(),
        _loadReportList(),
    ]);
}

// ── Template Loading ─────────────────────────────────────────

async function _loadReportTemplates() {
    const container = document.getElementById('reportTemplates');
    if (!container) return;
    container.innerHTML = '<div class="report-loading">Loading templates&hellip;</div>';

    try {
        const resp = await fetch(`/api/synthesis/templates?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            container.innerHTML = _reportEmptyState('Templates Unavailable', 'Could not load report templates.');
            return;
        }
        const templates = await resp.json();
        _renderTemplateCards(templates);
    } catch (e) {
        console.warn('Failed to load report templates:', e);
        container.innerHTML = _reportEmptyState('Connection Error', 'Unable to reach templates endpoint.');
    }
}

// ── Template Cards ───────────────────────────────────────────

/**
 * Render horizontal template cards. Available templates are clickable
 * with a Generate button; unavailable ones are greyed out with a hint.
 */
function _renderTemplateCards(templates) {
    const container = document.getElementById('reportTemplates');
    if (!container) return;

    if (!templates || templates.length === 0) {
        container.innerHTML = _reportEmptyState(
            'No Templates',
            'No report templates are available for this project type.'
        );
        return;
    }

    container.innerHTML = `
        <div class="report-template-row">
            ${templates.map(tpl => {
                const available = tpl.available !== false;
                const hint = tpl.hint || 'Requires more data';
                const desc = tpl.description || '';

                return `
                    <div class="report-template-card ${available ? 'report-template-available' : 'report-template-unavailable'} ${_reportTemplate === tpl.slug ? 'report-template-selected' : ''}"
                         ${available ? `onclick="_selectTemplate('${esc(tpl.slug)}')"` : ''}
                         title="${available ? escAttr(desc) : escAttr(hint)}">
                        <div class="report-template-name">${esc(tpl.name || tpl.slug)}</div>
                        <div class="report-template-desc">
                            ${available
                                ? esc(_truncateReportLabel(desc, 60))
                                : `<span class="report-template-hint">${esc(hint)}</span>`
                            }
                        </div>
                        ${available
                            ? `<button class="btn btn-sm report-template-gen-btn" onclick="event.stopPropagation(); _selectTemplate('${esc(tpl.slug)}')">Generate</button>`
                            : ''
                        }
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

// ── Template Selection ───────────────────────────────────────

/**
 * Select a template and show generation options (entity filter,
 * audience, AI toggle).
 */
function _selectTemplate(slug) {
    _reportTemplate = slug;

    // Update card selection state
    const cards = document.querySelectorAll('.report-template-card');
    cards.forEach(card => card.classList.remove('report-template-selected'));
    const selected = document.querySelector(`.report-template-available[onclick*="'${slug}'"]`);
    if (selected) selected.classList.add('report-template-selected');

    const formArea = document.getElementById('reportGenForm');
    if (!formArea) return;

    formArea.innerHTML = `
        <div class="report-gen-form">
            <div class="report-gen-heading">Generate Report: ${esc(slug)}</div>
            <div class="report-gen-fields">
                <div class="report-gen-field">
                    <label class="report-gen-label" for="reportEntityFilter">Entity Filter</label>
                    <select class="report-gen-select" id="reportEntityFilter">
                        <option value="">All entities</option>
                    </select>
                </div>
                <div class="report-gen-field">
                    <label class="report-gen-label" for="reportAudience">Audience</label>
                    <input class="report-gen-input" id="reportAudience" type="text"
                           placeholder="e.g. executive, technical, investor" />
                </div>
                <div class="report-gen-field">
                    <label class="report-gen-label" for="reportQuestions">Key Questions</label>
                    <textarea class="report-gen-textarea" id="reportQuestions" rows="3"
                              placeholder="Optional: specific questions the report should address"></textarea>
                </div>
                <div class="report-gen-field report-gen-toggle-row">
                    <label class="report-gen-label" for="reportUseAi">AI-Assisted</label>
                    <input type="checkbox" id="reportUseAi" class="report-gen-checkbox" />
                    <span class="report-gen-toggle-hint">Uses LLM to synthesise insights and write narratives</span>
                </div>
            </div>
            <div class="report-gen-actions">
                <button class="btn btn-sm" onclick="_runGeneration()">Generate Report</button>
                <button class="btn btn-sm report-gen-cancel" onclick="_cancelGeneration()">Cancel</button>
            </div>
        </div>
    `;

    _populateGenEntityFilter();
}

async function _populateGenEntityFilter() {
    try {
        const resp = await fetch(`/api/entities?project_id=${currentProjectId}&limit=200`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) return;
        const data = await resp.json();
        const entities = Array.isArray(data) ? data : (data.entities || data.items || []);

        const sel = document.getElementById('reportEntityFilter');
        if (!sel) return;
        entities.forEach(e => {
            const opt = document.createElement('option');
            opt.value = e.id;
            opt.textContent = e.name || e.company_name || `Entity ${e.id}`;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.warn('Could not load entity list for report filter:', e);
    }
}

function _cancelGeneration() {
    _reportTemplate = null;
    const formArea = document.getElementById('reportGenForm');
    if (formArea) formArea.innerHTML = '';

    // Remove selection highlight
    const cards = document.querySelectorAll('.report-template-card');
    cards.forEach(card => card.classList.remove('report-template-selected'));
}

// ── Report Generation ────────────────────────────────────────

async function _runGeneration() {
    if (!_reportTemplate) return;

    const entityFilterEl = document.getElementById('reportEntityFilter');
    const audienceEl = document.getElementById('reportAudience');
    const questionsEl = document.getElementById('reportQuestions');
    const useAiEl = document.getElementById('reportUseAi');

    const options = {
        entity_id: entityFilterEl ? (entityFilterEl.value || null) : null,
        audience: audienceEl ? audienceEl.value.trim() : '',
        questions: questionsEl ? questionsEl.value.trim() : '',
        use_ai: useAiEl ? useAiEl.checked : false,
    };

    await _generateReport(_reportTemplate, options);
}

/**
 * Generate a report by calling the backend.
 * Uses /generate-ai if AI is toggled on, otherwise /generate.
 */
async function _generateReport(template, options) {
    const formArea = document.getElementById('reportGenForm');
    if (formArea) {
        formArea.innerHTML = `
            <div class="report-loading">
                <div class="report-loading-text">Generating report&hellip;</div>
                <div class="report-loading-hint">This may take a moment${options.use_ai ? ' (AI synthesis in progress)' : ''}.</div>
            </div>
        `;
    }

    const endpoint = options.use_ai
        ? '/api/synthesis/generate-ai'
        : '/api/synthesis/generate';

    const body = {
        project_id: currentProjectId,
        template: template,
        entity_id: options.entity_id || null,
        audience: options.audience || null,
        questions: options.questions || null,
    };

    try {
        const resp = await fetch(endpoint, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify(body),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            const msg = err.error || 'Report generation failed.';
            if (formArea) formArea.innerHTML = _reportEmptyState('Generation Failed', msg);
            if (window.notyf) window.notyf.error(msg);
            return;
        }

        const report = await resp.json();

        // Clear form, refresh list, and show the new report
        if (formArea) formArea.innerHTML = '';
        _reportTemplate = null;
        const cards = document.querySelectorAll('.report-template-card');
        cards.forEach(card => card.classList.remove('report-template-selected'));

        _activeReportId = report.id;
        await _loadReportList();
        _renderReportView(report);

        if (window.notyf) window.notyf.success('Report generated');
    } catch (e) {
        console.error('Report generation failed:', e);
        if (formArea) formArea.innerHTML = _reportEmptyState('Generation Failed', 'An unexpected error occurred.');
        if (window.notyf) window.notyf.error('Report generation failed');
    }
}

// ── Report Viewer ────────────────────────────────────────────

/**
 * Load a single report by ID and render it.
 */
async function _loadReport(reportId) {
    const viewer = document.getElementById('reportViewer');
    if (!viewer) return;
    viewer.innerHTML = '<div class="report-loading">Loading report&hellip;</div>';

    try {
        const resp = await fetch(`/api/synthesis/${reportId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            viewer.innerHTML = _reportEmptyState('Report Not Found', 'Could not load the requested report.');
            return;
        }
        const report = await resp.json();
        _activeReportId = reportId;
        _renderReportView(report);

        // Update active state in the list
        _highlightActiveReport(reportId);
    } catch (e) {
        console.warn('Failed to load report:', e);
        viewer.innerHTML = _reportEmptyState('Load Failed', 'Could not load report.');
    }
}

/**
 * Render the full report view with title bar, sections, evidence
 * references, data tables, AI badge, and timestamp footer.
 */
function _renderReportView(report) {
    const viewer = document.getElementById('reportViewer');
    if (!viewer) return;

    const sections = report.sections || [];
    const createdAt = report.created_at
        ? new Date(report.created_at).toLocaleString()
        : '';
    const updatedAt = report.updated_at
        ? new Date(report.updated_at).toLocaleString()
        : '';
    const isAi = report.ai_generated || report.use_ai || false;

    const sectionsHtml = sections.map((section, idx) => {
        const contentHtml = _renderSectionContent(section);
        const evidenceHtml = _renderSectionEvidence(section.evidence_refs);
        const tableHtml = _renderSectionTable(section.table);

        return `
            <div class="report-section" data-section-index="${idx}">
                <div class="report-section-heading">${esc(section.heading || section.title || 'Section ' + (idx + 1))}</div>
                <div class="report-section-content">${contentHtml}</div>
                ${tableHtml}
                ${evidenceHtml}
            </div>
        `;
    }).join('');

    viewer.innerHTML = `
        <div class="report-viewer">
            <div class="report-title-bar">
                <div class="report-title-text">
                    <span class="report-title">${esc(report.title || 'Untitled Report')}</span>
                    ${isAi ? '<span class="report-ai-badge">AI Generated</span>' : ''}
                </div>
                <div class="report-title-actions">
                    <button class="btn btn-sm" onclick="_editReportTitle(${report.id})" title="Rename report">Rename</button>
                    <button class="btn btn-sm" onclick="_showExportBar(${report.id})" title="Export report">Export</button>
                    <button class="btn btn-sm report-btn-delete" onclick="_deleteReport(${report.id})" title="Delete report">Delete</button>
                </div>
            </div>
            ${report.template ? '<div class="report-template-label">Template: ' + esc(report.template) + '</div>' : ''}
            ${report.audience ? '<div class="report-audience-label">Audience: ' + esc(report.audience) + '</div>' : ''}
            <div class="report-sections">
                ${sectionsHtml || _reportEmptyState('Empty Report', 'This report has no content sections.')}
            </div>
            <div class="report-export-bar hidden" id="reportExportBar_${report.id}">
                <span class="report-export-label">Export as:</span>
                <button class="btn btn-sm" onclick="_exportReport(${report.id}, 'html')">HTML</button>
                <button class="btn btn-sm" onclick="_exportReport(${report.id}, 'markdown')">Markdown</button>
                <button class="btn btn-sm" onclick="_exportReport(${report.id}, 'json')">JSON</button>
                <button class="btn btn-sm" onclick="_exportReport(${report.id}, 'pdf')">PDF</button>
                <button class="btn btn-sm" onclick="_exportReportToCanvas(${report.id})">Canvas</button>
            </div>
            <div class="report-footer">
                ${createdAt ? '<span class="report-footer-item">Created: ' + esc(createdAt) + '</span>' : ''}
                ${updatedAt ? '<span class="report-footer-item">Updated: ' + esc(updatedAt) + '</span>' : ''}
                ${report.entity_count != null ? '<span class="report-footer-item">' + report.entity_count + ' entities</span>' : ''}
            </div>
        </div>
    `;
}

/**
 * Render section content as markdown-safe HTML.
 * Handles paragraphs separated by double newlines, preserves
 * single newlines as line breaks.
 */
function _renderSectionContent(section) {
    const content = section.content || section.body || '';
    if (!content) return '<p class="report-section-empty">No content.</p>';

    // Split on double newlines for paragraphs, escape HTML, preserve single newlines
    const paragraphs = content.split(/\n\n+/);
    return paragraphs.map(function(para) {
        const escaped = esc(para.trim());
        const withBreaks = escaped.replace(/\n/g, '<br>');
        return '<p class="report-paragraph">' + withBreaks + '</p>';
    }).join('');
}

/**
 * Render evidence references as inline badge-style links.
 */
function _renderSectionEvidence(refs) {
    if (!refs || refs.length === 0) return '';

    const badges = refs.map(function(ref) {
        const label = ref.label || ref.filename || ref.evidence_id || 'Evidence';
        const href = ref.url || ref.serve_url || '#';
        const title = ref.description || ref.source || '';

        return '<a class="report-evidence-ref" href="' + escAttr(href) + '" target="_blank" rel="noopener"' +
               ' title="' + escAttr(title) + '">' + esc(_truncateReportLabel(String(label), 30)) + '</a>';
    }).join('');

    return `
        <div class="report-evidence-row">
            <span class="report-evidence-label">Evidence:</span>
            ${badges}
        </div>
    `;
}

/**
 * Render a data table within a section if provided.
 */
function _renderSectionTable(table) {
    if (!table) return '';

    const headers = table.headers || [];
    const rows = table.rows || [];

    if (!headers.length && !rows.length) return '';

    const headerHtml = headers.length
        ? '<thead><tr>' + headers.map(function(h) {
            return '<th class="report-table-head">' + esc(String(h)) + '</th>';
          }).join('') + '</tr></thead>'
        : '';

    const rowsHtml = rows.map(function(row, rowIdx) {
        const cells = (Array.isArray(row) ? row : [row]).map(function(cell) {
            return '<td class="report-table-cell">' + esc(String(cell != null ? cell : '')) + '</td>';
        }).join('');
        return '<tr class="' + (rowIdx % 2 === 0 ? 'report-table-row-even' : 'report-table-row-odd') + '">' + cells + '</tr>';
    }).join('');

    return `
        <div class="report-table-wrap">
            <table class="report-table">
                ${headerHtml}
                <tbody>${rowsHtml}</tbody>
            </table>
        </div>
    `;
}

function _showExportBar(reportId) {
    const bar = document.getElementById('reportExportBar_' + reportId);
    if (!bar) return;
    bar.classList.toggle('hidden');
}

// ── Report List ──────────────────────────────────────────────

/**
 * Load the list of saved reports for the current project.
 */
async function _loadReportList() {
    const container = document.getElementById('reportList');
    if (!container) return;

    try {
        const resp = await fetch(`/api/synthesis?project_id=${currentProjectId}`, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            _reportsData = [];
            _renderReportList([]);
            return;
        }
        _reportsData = await resp.json();
        _renderReportList(_reportsData);
    } catch (e) {
        console.warn('Failed to load report list:', e);
        _reportsData = [];
        _renderReportList([]);
    }
}

/**
 * Render the saved reports as a list/table with title, template,
 * date, and action buttons.
 */
function _renderReportList(reports) {
    const container = document.getElementById('reportList');
    if (!container) return;

    if (!reports || reports.length === 0) {
        container.innerHTML = `
            <div class="report-list-empty">
                <div class="report-list-empty-title">No Reports</div>
                <div class="report-list-empty-desc">Generate a report using the templates above.</div>
            </div>
        `;
        return;
    }

    const rows = reports.map(function(report) {
        const date = report.created_at
            ? new Date(report.created_at).toLocaleDateString()
            : '';
        const isAi = report.ai_generated || report.use_ai || false;
        const isActive = _activeReportId === report.id;

        return `
            <div class="report-list-row ${isActive ? 'report-list-row-active' : ''}" data-report-id="${report.id}">
                <div class="report-list-title" onclick="_loadReport(${report.id})">
                    ${esc(report.title || 'Untitled Report')}
                    ${isAi ? '<span class="report-ai-badge report-ai-badge-sm">AI</span>' : ''}
                </div>
                <div class="report-list-template">${esc(report.template || '')}</div>
                <div class="report-list-date">${esc(date)}</div>
                <div class="report-list-actions">
                    <button class="btn btn-sm" onclick="_loadReport(${report.id})" title="View report">View</button>
                    <button class="btn btn-sm" onclick="_exportReport(${report.id}, 'html')" title="Export as HTML">Export</button>
                    <button class="btn btn-sm report-btn-delete" onclick="_deleteReport(${report.id})" title="Delete report">Del</button>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = `
        <div class="report-list-header">
            <span class="report-list-header-title">Title</span>
            <span class="report-list-header-template">Template</span>
            <span class="report-list-header-date">Date</span>
            <span class="report-list-header-actions">Actions</span>
        </div>
        <div class="report-list-body">
            ${rows}
        </div>
    `;
}

function _highlightActiveReport(reportId) {
    const rows = document.querySelectorAll('.report-list-row');
    rows.forEach(function(row) {
        const rid = parseInt(row.getAttribute('data-report-id'), 10);
        row.classList.toggle('report-list-row-active', rid === reportId);
    });
}

// ── Export ────────────────────────────────────────────────────

/**
 * Export a report in the given format (html, markdown, json).
 * HTML opens in a new tab; markdown/json download as file.
 */
async function _exportReport(reportId, format) {
    const url = '/api/synthesis/' + reportId + '/export?format=' + encodeURIComponent(format);

    try {
        const resp = await fetch(url, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            const err = await resp.json().catch(function() { return {}; });
            if (window.notyf) window.notyf.error(err.error || 'Export failed');
            return;
        }

        if (format === 'pdf') {
            const blob = await resp.blob();
            _downloadBlob(blob, 'report-' + reportId + '.pdf');
        } else if (format === 'html') {
            const html = await resp.text();
            const win = window.open('', '_blank');
            if (win) {
                win.document.write(html);
                win.document.close();
            } else {
                _downloadBlob(new Blob([html], { type: 'text/html' }), 'report-' + reportId + '.html');
            }
        } else if (format === 'json') {
            const json = await resp.text();
            _downloadBlob(new Blob([json], { type: 'application/json' }), 'report-' + reportId + '.json');
        } else {
            // markdown or other text formats
            const text = await resp.text();
            const mimeType = format === 'markdown' ? 'text/markdown' : 'text/plain';
            const ext = format === 'markdown' ? 'md' : 'txt';
            _downloadBlob(new Blob([text], { type: mimeType }), 'report-' + reportId + '.' + ext);
        }

        if (window.notyf) window.notyf.success('Exported as ' + format);
    } catch (e) {
        console.error('Export failed:', e);
        if (window.notyf) window.notyf.error('Export failed');
    }
}

function _downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function() {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }, 100);
}

// ── Report Editing ───────────────────────────────────────────

/**
 * Rename a report title via prompt dialog.
 */
async function _editReportTitle(reportId) {
    const current = _reportsData.find(function(r) { return r.id === reportId; });
    const currentTitle = current ? (current.title || '') : '';

    const result = await showPromptDialog(
        'Rename Report',
        'Enter a new title for this report:',
        currentTitle,
    );
    if (result === null || result === undefined || result.trim() === '') return;

    try {
        const resp = await fetch('/api/synthesis/' + reportId, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN,
            },
            body: JSON.stringify({ title: result.trim() }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(function() { return {}; });
            if (window.notyf) window.notyf.error(err.error || 'Rename failed');
            return;
        }

        if (window.notyf) window.notyf.success('Report renamed');

        // Refresh list and re-render viewer if this is the active report
        await _loadReportList();
        if (_activeReportId === reportId) {
            await _loadReport(reportId);
        }
    } catch (e) {
        console.error('Rename failed:', e);
        if (window.notyf) window.notyf.error('Rename failed');
    }
}

/**
 * Delete a report with confirmation.
 */
async function _deleteReport(reportId) {
    const report = _reportsData.find(function(r) { return r.id === reportId; });
    const title = report ? (report.title || 'Untitled Report') : 'this report';

    const confirmed = await window.showNativeConfirm({
        title: 'Delete Report',
        message: 'Delete "' + title + '"? This cannot be undone.',
        confirmText: 'Delete',
        type: 'danger',
    });
    if (!confirmed) return;

    try {
        const resp = await fetch('/api/synthesis/' + reportId, {
            method: 'DELETE',
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            const err = await resp.json().catch(function() { return {}; });
            if (window.notyf) window.notyf.error(err.error || 'Delete failed');
            return;
        }

        if (window.notyf) window.notyf.success('Report deleted');

        // Clear viewer if this was the active report
        if (_activeReportId === reportId) {
            _activeReportId = null;
            const viewer = document.getElementById('reportViewer');
            if (viewer) viewer.innerHTML = '';
        }

        await _loadReportList();
    } catch (e) {
        console.error('Delete failed:', e);
        if (window.notyf) window.notyf.error('Delete failed');
    }
}

// ── Utilities ─────────────────────────────────────────────────

function _reportEmptyState(title, desc) {
    return `
        <div class="report-empty-state">
            <div class="report-empty-title">${esc(title)}</div>
            <div class="report-empty-desc">${esc(desc)}</div>
        </div>
    `;
}

function _truncateReportLabel(str, maxLen) {
    if (!str) return '';
    return str.length <= maxLen ? str : str.substring(0, maxLen - 1) + '\u2026';
}

// ── Canvas Export ─────────────────────────────────────────────

/**
 * Export a report as an Excalidraw canvas composition.
 * Fetches the canvas JSON from the backend, switches to the Canvas tab,
 * and loads the data into Excalidraw.
 */
async function _exportReportToCanvas(reportId) {
    const url = '/api/synthesis/' + reportId + '/export?format=canvas';

    try {
        const resp = await fetch(url, {
            headers: { 'X-CSRFToken': CSRF_TOKEN },
        });
        if (!resp.ok) {
            const err = await resp.json().catch(function() { return {}; });
            if (window.notyf) window.notyf.error(err.error || 'Canvas export failed');
            return;
        }

        const canvasData = await resp.json();

        // Switch to the Canvas tab
        if (typeof showTab === 'function') {
            showTab('canvas');
        }

        // Load the canvas data into Excalidraw
        if (typeof window.loadCanvasFromReport === 'function') {
            window.loadCanvasFromReport(canvasData);
        } else {
            console.warn('loadCanvasFromReport not available — canvas module may not be loaded');
            if (window.notyf) window.notyf.error('Canvas module not available');
            return;
        }

        if (window.notyf) window.notyf.success('Report loaded into Canvas');
    } catch (e) {
        console.error('Canvas export failed:', e);
        if (window.notyf) window.notyf.error('Canvas export failed');
    }
}

// ── Global Exposure ───────────────────────────────────────────

window.initReports             = initReports;
window._selectTemplate         = _selectTemplate;
window._generateReport         = _generateReport;
window._loadReport             = _loadReport;
window._exportReport           = _exportReport;
window._exportReportToCanvas   = _exportReportToCanvas;
window._editReportTitle        = _editReportTitle;
window._deleteReport           = _deleteReport;
window._showExportBar          = _showExportBar;
window._runGeneration          = _runGeneration;
window._cancelGeneration       = _cancelGeneration;
