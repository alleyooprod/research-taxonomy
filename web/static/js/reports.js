/**
 * AI market report generation, viewing, and export.
 */

async function generateMarketReport() {
    const categoryName = document.getElementById('reportCategorySelect').value;
    if (!categoryName) { showToast('Select a category'); return; }

    if (!acquireAiLock('report generation')) {
        showToast(`Another AI task is running (${aiLock}). Please wait for it to finish.`);
        return;
    }

    const btn = document.getElementById('reportBtn');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    document.getElementById('reportStatus').classList.remove('hidden');
    document.getElementById('reportContent').classList.add('hidden');

    const res = await safeFetch('/api/ai/market-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_name: categoryName, project_id: currentProjectId, model: document.getElementById('reportModelSelect').value }),
    });
    const data = await res.json();
    localStorage.setItem('activeReportId', data.report_id);
    localStorage.setItem('activeReportCategory', categoryName);
    pollReport(data.report_id);
}

function resumeActiveReport() {
    const reportId = localStorage.getItem('activeReportId');
    if (reportId) {
        document.getElementById('reportStatus').classList.remove('hidden');
        document.getElementById('reportContent').classList.add('hidden');
        const btn = document.getElementById('reportBtn');
        btn.disabled = true;
        btn.textContent = 'Generating...';
        pollReport(reportId);
    }
}

let _reportPollCount = 0;
const _MAX_POLL_RETRIES = 120; // 6 minutes at 3s intervals

async function pollReport(reportId) {
    const res = await safeFetch(`/api/ai/market-report/${reportId}`);
    const data = await res.json();

    if (data.status === 'pending') {
        if (++_reportPollCount > _MAX_POLL_RETRIES) {
            data.status = 'error';
            data.error = 'Report generation timed out. Please try again.';
        } else {
            setTimeout(() => pollReport(reportId), 3000);
            return;
        }
    }
    _reportPollCount = 0;

    localStorage.removeItem('activeReportId');
    localStorage.removeItem('activeReportCategory');
    releaseAiLock();

    const btn = document.getElementById('reportBtn');
    btn.disabled = false;
    btn.textContent = 'Generate Report';
    document.getElementById('reportStatus').classList.add('hidden');

    const content = document.getElementById('reportContent');
    content.classList.remove('hidden');

    if (data.status === 'error') {
        content.innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
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
        html = sanitize(marked.parse(data.report || ''));
    } else {
        html = esc(data.report || '')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/^### (.+)$/gm, '<h4>$1</h4>')
            .replace(/^## (.+)$/gm, '<h3>$1</h3>')
            .replace(/^# (.+)$/gm, '<h2>$1</h2>')
            .replace(/^- (.+)$/gm, '<li>$1</li>')
            .replace(/\n/g, '<br>');
    }

    const currentReportId = reportId;
    content.innerHTML = `
        <div class="report-header">
            <h3>Market Report: ${esc(data.category || '')}</h3>
            <div style="display:flex;gap:8px;align-items:center">
                <span class="hint-text">${data.company_count || 0} companies analyzed</span>
                <button class="btn" onclick="exportReportMd('${esc(currentReportId)}')">Export .md</button>
                <button class="btn" onclick="exportReportPdf()">Export PDF</button>
            </div>
        </div>
        <div class="report-body">${html}</div>
    `;

    if (window.mermaid) {
        try {
            mermaid.run({ nodes: content.querySelectorAll('.mermaid') });
        } catch (e) {
            console.warn('Mermaid rendering failed:', e);
        }
    }
    if (window.hljs) content.querySelectorAll('pre code:not(.hljs)').forEach(el => hljs.highlightElement(el));

    loadSavedReports();
}

function exportReportMd(reportId) {
    window.location.href = `/api/reports/${reportId}/export/md`;
}

function exportReportPdf() {
    const reportBody = document.querySelector('#reportContent .report-body');
    if (!reportBody) return;
    const printWin = window.open('', '_blank');
    printWin.document.write(`<!DOCTYPE html><html><head>
        <title>Market Report</title>
        <style>
            body { font-family: 'Noto Sans', sans-serif; font-size: 13px; line-height: 1.7; color: #333; max-width: 800px; margin: 0 auto; padding: 40px; }
            h1, h2, h3, h4 { color: #3D4035; }
            table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 12px; }
            th, td { padding: 8px 10px; border: 1px solid #ddd; text-align: left; word-wrap: break-word; }
            th { background: #f5f2eb; font-weight: 600; }
            blockquote { margin: 12px 0; padding: 10px 16px; border-left: 3px solid #BC6C5A; background: #fff5f0; }
            ul, ol { margin: 8px 0; padding-left: 24px; }
            li { margin-bottom: 4px; }
            a { color: #BC6C5A; }
            .mermaid { display: none; }
        </style>
    </head><body>${reportBody.innerHTML}</body></html>`);
    printWin.document.close();
    printWin.onload = () => { printWin.print(); };
}

async function loadSavedReports() {
    const reportSel = document.getElementById('reportCategorySelect');
    if (reportSel && reportSel.options.length <= 1) {
        const taxRes = await safeFetch(`/api/taxonomy?project_id=${currentProjectId}`);
        const cats = await taxRes.json();
        const topLevel = cats.filter(c => !c.parent_id);
        reportSel.innerHTML = '<option value="">Select a category...</option>' +
            topLevel.map(c => `<option value="${esc(c.name)}">${esc(c.name)} (${c.company_count})</option>`).join('');
    }
    const container = document.getElementById('savedReportsList');
    if (!container) return;
    const res = await safeFetch(`/api/reports?project_id=${currentProjectId}`);
    const reports = await res.json();
    if (!reports.length) {
        container.innerHTML = '<p class="hint-text">No saved reports yet. Generate one above.</p>';
        return;
    }
    container.innerHTML = reports.map(r => `
        <div class="saved-report-item">
            <div class="saved-report-info">
                <strong>${esc(r.category_name)}</strong>
                <span class="hint-text">${r.company_count} companies &middot; ${r.model || ''} &middot; ${new Date(r.created_at).toLocaleDateString()}</span>
            </div>
            <div class="saved-report-actions">
                ${r.status === 'complete'
                    ? `<button class="btn" onclick="viewSavedReport('${esc(r.report_id)}')">View</button>
                       <button class="btn" onclick="exportReportMd('${esc(r.report_id)}')">MD</button>`
                    : `<span class="re-research-error" style="font-size:12px">${esc(r.error_message || 'Error')}</span>`
                }
                <button class="btn" style="color:var(--accent-danger)" onclick="deleteSavedReport('${esc(r.report_id)}')">Delete</button>
            </div>
        </div>
    `).join('');
}

async function viewSavedReport(reportId) {
    const res = await safeFetch(`/api/reports/${reportId}`);
    const data = await res.json();
    if (!data.markdown_content) return;

    const content = document.getElementById('reportContent');
    content.classList.remove('hidden');

    let html;
    if (window.marked) {
        const renderer = new marked.Renderer();
        const defaultCode = renderer.code.bind(renderer);
        renderer.code = function(args) {
            if (args.lang === 'mermaid') {
                return `<div class="mermaid">${args.text}</div>`;
            }
            return defaultCode(args);
        };
        marked.use({ renderer, breaks: true, gfm: true });
        html = sanitize(marked.parse(data.markdown_content || ''));
    } else {
        html = esc(data.markdown_content).replace(/\n/g, '<br>');
    }

    content.innerHTML = `
        <div class="report-header">
            <h3>Market Report: ${esc(data.category_name)}</h3>
            <div style="display:flex;gap:8px;align-items:center">
                <span class="hint-text">${data.company_count || 0} companies &middot; ${new Date(data.created_at).toLocaleDateString()}</span>
                <button class="btn" onclick="exportReportMd('${esc(reportId)}')">Export .md</button>
                <button class="btn" onclick="exportReportPdf()">Export PDF</button>
            </div>
        </div>
        <div class="report-body">${html}</div>
    `;

    if (window.mermaid) {
        try { mermaid.run({ nodes: content.querySelectorAll('.mermaid') }); } catch (e) {}
    }

    content.scrollIntoView({ behavior: 'smooth' });
}

async function deleteSavedReport(reportId) {
    if (!confirm('Delete this report?')) return;
    await safeFetch(`/api/reports/${reportId}`, { method: 'DELETE' });
    loadSavedReports();
}
