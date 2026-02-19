/**
 * Trash, CSV import, duplicates, merge, XLSX export, PDF export,
 * ExcelJS styled export, Word (.docx) export, ZIP bundle export,
 * Markdown rendering utility.
 */

// Fallback if showNativeConfirm hasn't been loaded yet
const _confirmExport = window.showNativeConfirm || (async (opts) => confirm(opts.message || opts.title));

// --- Trash ---
async function loadTrash() {
    const container = document.getElementById('trashList');
    container.classList.remove('hidden');
    const res = await safeFetch(`/api/trash?project_id=${currentProjectId}`);
    const items = await res.json();

    if (!items.length) {
        container.innerHTML = '<p style="padding:12px;color:var(--text-muted)">Trash is empty.</p>';
        return;
    }

    container.innerHTML = items.map(c => `
        <div class="trash-item">
            <div>
                <strong>${esc(c.name)}</strong>
                <span style="color:var(--text-muted);font-size:12px;margin-left:8px">Deleted ${new Date(c.deleted_at).toLocaleDateString()}</span>
            </div>
            <div style="display:flex;gap:6px">
                <button class="btn" onclick="restoreFromTrash(${c.id})">Restore</button>
                <button class="danger-btn" onclick="permanentDelete(${c.id})">Delete forever</button>
            </div>
        </div>
    `).join('');
}

async function restoreFromTrash(id) {
    await safeFetch(`/api/companies/${id}/restore`, { method: 'POST' });
    loadTrash();
    loadCompanies();
    loadStats();
}

async function permanentDelete(id) {
    const confirmed = await _confirmExport({
        title: 'Permanently Delete?',
        message: 'This cannot be undone. The data will be completely removed.',
        confirmText: 'Delete Permanently',
        type: 'danger'
    });
    if (!confirmed) return;
    await safeFetch(`/api/companies/${id}/permanent-delete`, { method: 'DELETE' });
    loadTrash();
}

// --- CSV Import ---
async function importCsv(event) {
    event.preventDefault();
    const file = document.getElementById('csvFile').files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('project_id', currentProjectId);

    const res = await safeFetch('/api/import/csv', { method: 'POST', body: formData });
    const data = await res.json();

    const resultDiv = document.getElementById('importResult');
    resultDiv.classList.remove('hidden');
    if (data.error) {
        resultDiv.innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
    } else {
        resultDiv.innerHTML = `<p class="re-research-success">Imported ${data.imported} of ${data.total_rows} rows.</p>`;
        loadCompanies();
        loadStats();
    }
}

// --- Duplicates ---
async function findDuplicates() {
    const container = document.getElementById('duplicatesList');
    container.classList.remove('hidden');
    container.innerHTML = '<p>Scanning...</p>';
    const res = await safeFetch(`/api/duplicates?project_id=${currentProjectId}`);
    const dupes = await res.json();

    if (!dupes.length) {
        container.innerHTML = '<p style="padding:12px;color:var(--text-muted)">No duplicates found.</p>';
        return;
    }

    container.innerHTML = dupes.map(d => `
        <div class="duplicate-group">
            <div class="duplicate-header">URL match: ${esc(d.key)}</div>
            ${d.companies.map(c => `
                <div class="duplicate-item">
                    <span>${esc(c.name)}</span>
                    <a href="${esc(c.url)}" target="_blank" style="font-size:12px">${esc(c.url)}</a>
                </div>
            `).join('')}
            ${d.companies.length === 2 ? `
                <button class="filter-action-btn" onclick="mergeCompanies(${d.companies[0].id},${d.companies[1].id})">
                    Merge "${esc(d.companies[1].name)}" into "${esc(d.companies[0].name)}"
                </button>
            ` : ''}
        </div>
    `).join('');
}

async function mergeCompanies(targetId, sourceId) {
    const confirmed = await _confirmExport({
        title: 'Merge Companies?',
        message: 'This will combine these companies into one record. The source will be moved to trash. This cannot be undone.',
        confirmText: 'Merge',
        type: 'warning'
    });
    if (!confirmed) return;
    await safeFetch('/api/companies/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_id: targetId, source_id: sourceId }),
    });
    findDuplicates();
    loadCompanies();
    loadStats();
}

// --- SheetJS (Excel Export) ---
async function exportXlsx() {
    if (!window.XLSX) { showToast('Excel library still loading...'); return; }

    const [compRes, taxRes] = await Promise.all([
        safeFetch(`/api/companies?project_id=${currentProjectId}`),
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();
    const topCats = categories.filter(c => !c.parent_id);

    const wb = XLSX.utils.book_new();

    const allData = companies.map(c => ({
        Name: c.name,
        URL: c.url,
        Category: c.category_name || '',
        What: c.what || '',
        Target: c.target || '',
        Products: c.products || '',
        Geography: c.geography || '',
        'HQ City': c.hq_city || '',
        'HQ Country': c.hq_country || '',
        'Funding Stage': c.funding_stage || '',
        'Total Funding': c.total_funding_usd || '',
        'Business Model': c.business_model || '',
        Employees: c.employee_range || '',
        'Founded Year': c.founded_year || '',
        Confidence: c.confidence_score ? Math.round(c.confidence_score * 100) + '%' : '',
        Tags: (c.tags || []).join(', '),
        Starred: c.is_starred ? 'Yes' : '',
    }));
    const wsAll = XLSX.utils.json_to_sheet(allData);
    wsAll['!cols'] = [
        {wch:25},{wch:35},{wch:20},{wch:40},{wch:20},{wch:30},
        {wch:15},{wch:15},{wch:15},{wch:12},{wch:15},{wch:10},
        {wch:10},{wch:10},{wch:10},{wch:20},{wch:6},
    ];
    XLSX.utils.book_append_sheet(wb, wsAll, 'All Companies');

    topCats.forEach(cat => {
        const catCompanies = companies.filter(c => c.category_name === cat.name);
        if (!catCompanies.length) return;
        const data = catCompanies.map(c => ({
            Name: c.name, URL: c.url, What: c.what || '',
            Target: c.target || '', Geography: c.geography || '',
            Stage: c.funding_stage || '', Confidence: c.confidence_score ? Math.round(c.confidence_score*100)+'%' : '',
        }));
        const ws = XLSX.utils.json_to_sheet(data);
        const sheetName = cat.name.substring(0, 31);
        XLSX.utils.book_append_sheet(wb, ws, sheetName);
    });

    XLSX.writeFile(wb, `taxonomy-${formatDate(new Date().toISOString()).replace(/\s/g,'-')}.xlsx`);
    if (notyf) notyf.success('Excel workbook exported!');
}

// --- pdfmake (PDF Export) ---
function exportReportPdfPdfmake() {
    if (!window.pdfMake) {
        exportReportPdf();
        return;
    }
    const reportBody = document.querySelector('#reportContent .report-body');
    if (!reportBody) return;

    const title = document.querySelector('#reportContent .report-header h3')?.textContent || 'Market Report';
    const text = reportBody.innerText;
    const lines = text.split('\n').filter(l => l.trim());

    const content = [
        { text: title, style: 'header', margin: [0, 0, 0, 12] },
        { text: `Generated ${formatDate(new Date().toISOString())}`, style: 'subheader', margin: [0, 0, 0, 20] },
    ];

    lines.forEach(line => {
        if (line.startsWith('##')) {
            content.push({ text: line.replace(/^#+\s*/, ''), style: 'sectionHeader', margin: [0, 12, 0, 6] });
        } else if (line.startsWith('- ') || line.startsWith('* ')) {
            content.push({ text: line, margin: [10, 2, 0, 2], fontSize: 10 });
        } else {
            content.push({ text: line, margin: [0, 2, 0, 2], fontSize: 10 });
        }
    });

    pdfMake.createPdf({
        content,
        defaultStyle: { font: 'Roboto', fontSize: 10, lineHeight: 1.4 },
        styles: {
            header: { fontSize: 18, bold: true, color: '#3D4035' },
            subheader: { fontSize: 11, color: '#888' },
            sectionHeader: { fontSize: 14, bold: true, color: '#bc6c5a' },
        },
    }).download(`${title.replace(/[^a-zA-Z0-9]/g, '_')}.pdf`);
}

// Full project PDF export
async function exportFullPdf() {
    if (!window.pdfMake) { showToast('PDF library still loading...'); return; }

    const [compRes, taxRes] = await Promise.all([
        safeFetch(`/api/companies?project_id=${currentProjectId}`),
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();
    const topCats = categories.filter(c => !c.parent_id);

    const content = [
        { text: document.getElementById('projectTitle').textContent, style: 'header' },
        { text: `${companies.length} companies across ${topCats.length} categories`, style: 'subheader', margin: [0, 0, 0, 20] },
    ];

    const tableBody = [['Name', 'Category', 'What', 'Geography', 'Stage']];
    companies.forEach(c => {
        tableBody.push([
            c.name || '',
            c.category_name || '',
            (c.what || '').substring(0, 80),
            c.geography || '',
            c.funding_stage || '',
        ]);
    });

    content.push({
        table: { headerRows: 1, widths: ['auto', 'auto', '*', 'auto', 'auto'], body: tableBody },
        layout: 'lightHorizontalLines',
        fontSize: 8,
    });

    pdfMake.createPdf({
        content,
        defaultStyle: { font: 'Roboto', fontSize: 9 },
        styles: {
            header: { fontSize: 20, bold: true },
            subheader: { fontSize: 12, color: '#666' },
        },
        pageOrientation: 'landscape',
    }).download('taxonomy-export.pdf');

    if (notyf) notyf.success('PDF exported!');
}

// ============================================================
// Helper: safe file download (uses FileSaver.js saveAs if available)
// ============================================================
function _safeSaveAs(blob, filename) {
    if (window.saveAs) {
        saveAs(blob, filename);
    } else {
        // Manual fallback
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
    }
}

// Helper: sanitize project name for file names
function _safeFilename(name) {
    return (name || 'export').replace(/[^a-zA-Z0-9_\-]/g, '-').replace(/-+/g, '-');
}

// Helper: fetch project data (companies + categories) for export functions
async function _fetchExportData() {
    const [compRes, taxRes] = await Promise.all([
        safeFetch(`/api/companies?project_id=${currentProjectId}`),
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();
    const projectName = document.getElementById('projectTitle')?.textContent || 'Taxonomy Project';
    return { project: { name: projectName }, companies, categories };
}

// Helper: convert companies array to CSV string
function _convertToCSV(companies) {
    if (!companies.length) return '';
    const headers = ['name', 'url', 'category_name', 'what', 'target', 'products',
        'geography', 'hq_city', 'hq_country', 'funding_stage', 'total_funding_usd',
        'business_model', 'employee_range', 'founded_year', 'confidence_score', 'tags'];
    const escape = v => {
        const s = String(v == null ? '' : v);
        return s.includes(',') || s.includes('"') || s.includes('\n') ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const rows = [headers.join(',')];
    companies.forEach(c => {
        rows.push(headers.map(h => {
            let val = c[h];
            if (h === 'tags' && Array.isArray(val)) val = val.join('; ');
            if (h === 'confidence_score' && val) val = Math.round(val * 100) + '%';
            return escape(val);
        }).join(','));
    });
    return rows.join('\n');
}

// ============================================================
// TASK 1: Professional PDF Report (pdfmake)
// ============================================================
function buildCategorySection(categories, companies) {
    const topCats = categories.filter(c => !c.parent_id);
    const content = [];
    topCats.forEach(cat => {
        const subs = categories.filter(c => c.parent_id === cat.id);
        const catCompanies = companies.filter(c => c.category_name === cat.name);

        content.push({ text: cat.name, fontSize: 14, bold: true, margin: [0, 12, 0, 4] });
        if (cat.description) {
            content.push({ text: cat.description, fontSize: 10, color: '#444444', margin: [0, 0, 0, 4] });
        }
        content.push({ text: `${catCompanies.length} companies`, fontSize: 9, color: '#999999', margin: [0, 0, 0, 4] });

        if (subs.length) {
            const subItems = subs.map(s => {
                const subCount = companies.filter(c => c.subcategory_id === s.id || c.category_name === s.name).length;
                return { text: `  - ${s.name}` + (subCount ? ` (${subCount})` : ''), fontSize: 10, margin: [8, 1, 0, 1] };
            });
            content.push(...subItems);
        }

        // Light separator
        content.push({ canvas: [{ type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 0.5, lineColor: '#E5E5E5' }], margin: [0, 8, 0, 4] });
    });
    return content;
}

function buildCompaniesTable(companies) {
    return {
        table: {
            headerRows: 1,
            widths: ['*', 'auto', 'auto', 'auto', 'auto'],
            body: [
                [
                    { text: 'Company', bold: true },
                    { text: 'Category', bold: true },
                    { text: 'Funding', bold: true },
                    { text: 'Employees', bold: true },
                    { text: 'Geography', bold: true }
                ],
                ...companies.map(c => [
                    c.name || '',
                    c.category_name || '',
                    c.funding_stage || '',
                    c.employee_range || '',
                    c.geography || ''
                ])
            ]
        },
        layout: {
            hLineWidth: () => 0.5,
            vLineWidth: () => 0,
            hLineColor: () => '#E5E5E5',
            paddingLeft: () => 4,
            paddingRight: () => 4,
            paddingTop: () => 6,
            paddingBottom: () => 6
        }
    };
}

function exportProjectPdf(project, companies, categories) {
    if (!window.pdfMake) { showToast('PDF library not loaded', 'error'); return; }

    const docDef = {
        defaultStyle: { font: 'Roboto', fontSize: 11, color: '#000000' },
        pageMargins: [40, 60, 40, 60],
        header: { text: project.name + ' -- Market Taxonomy Report', margin: [40, 20], fontSize: 9, color: '#999999' },
        footer: function(currentPage, pageCount) {
            return { text: currentPage + ' / ' + pageCount, alignment: 'right', margin: [0, 20, 40, 0], fontSize: 9, color: '#999999' };
        },
        content: [
            { text: project.name, fontSize: 32, bold: true, margin: [0, 0, 0, 8] },
            { text: 'Market Taxonomy Report', fontSize: 15, color: '#666666', margin: [0, 0, 0, 4] },
            { text: 'Generated ' + new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }), fontSize: 11, color: '#999999', margin: [0, 0, 0, 24] },
            { canvas: [{ type: 'line', x1: 0, y1: 0, x2: 515, y2: 0, lineWidth: 1, lineColor: '#000000' }], margin: [0, 0, 0, 24] },
            { text: 'Categories', fontSize: 18, bold: true, margin: [0, 0, 0, 12] },
            ...buildCategorySection(categories, companies),
            { text: '', pageBreak: 'before' },
            { text: 'Companies', fontSize: 18, bold: true, margin: [0, 0, 0, 12] },
            buildCompaniesTable(companies),
        ]
    };
    pdfMake.createPdf(docDef).download(_safeFilename(project.name) + '-report.pdf');
    if (notyf) notyf.success('PDF report exported!');
}

// Tab wrapper: fetches data then calls exportProjectPdf
async function exportProjectPdfFromTab() {
    const { project, companies, categories } = await _fetchExportData();
    exportProjectPdf(project, companies, categories);
}

// ============================================================
// TASK 2: Styled Excel Export (ExcelJS)
// ============================================================
async function exportProjectExcel(project, companies) {
    if (!window.ExcelJS) { showToast('Excel library not loaded', 'error'); return; }
    const wb = new ExcelJS.Workbook();
    wb.creator = 'Research Taxonomy Library';
    wb.created = new Date();
    const ws = wb.addWorksheet('Companies');

    ws.columns = [
        { header: 'Name', key: 'name', width: 30 },
        { header: 'URL', key: 'url', width: 35 },
        { header: 'Category', key: 'category_name', width: 20 },
        { header: 'What', key: 'what', width: 40 },
        { header: 'Funding', key: 'funding_stage', width: 15 },
        { header: 'Employees', key: 'employee_range', width: 15 },
        { header: 'Geography', key: 'geography', width: 15 },
        { header: 'Business Model', key: 'business_model', width: 15 },
        { header: 'Confidence', key: 'confidence_score', width: 12 },
    ];

    // Header style: black background, white text
    ws.getRow(1).eachCell(cell => {
        cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, name: 'Arial', size: 10 };
        cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF000000' } };
        cell.border = { bottom: { style: 'thin', color: { argb: 'FF000000' } } };
    });

    companies.forEach(c => {
        ws.addRow({
            name: c.name || '',
            url: c.url || '',
            category_name: c.category_name || '',
            what: c.what || '',
            funding_stage: c.funding_stage || '',
            employee_range: c.employee_range || '',
            geography: c.geography || '',
            business_model: c.business_model || '',
            confidence_score: c.confidence_score ? Math.round(c.confidence_score * 100) + '%' : '',
        });
    });

    // Alternating row shading for readability
    ws.eachRow((row, rowNumber) => {
        if (rowNumber > 1 && rowNumber % 2 === 0) {
            row.eachCell(cell => {
                cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFF5F5F5' } };
            });
        }
    });

    const buffer = await wb.xlsx.writeBuffer();
    _safeSaveAs(
        new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }),
        _safeFilename(project.name) + '.xlsx'
    );
    if (notyf) notyf.success('Styled Excel exported!');
}

// Tab wrapper
async function exportProjectExcelFromTab() {
    const { project, companies } = await _fetchExportData();
    await exportProjectExcel(project, companies);
}

// ============================================================
// TASK 3: Word Document Export (docx)
// ============================================================
async function exportProjectWord(project, companies, categories) {
    if (!window.docx) { showToast('Word library not loaded', 'error'); return; }
    const { Document, Packer, Paragraph, Table, TableRow, TableCell, TextRun, HeadingLevel, WidthType, BorderStyle, AlignmentType } = docx;

    const topCats = categories.filter(c => !c.parent_id);

    // Build category paragraphs
    const categoryChildren = [];
    topCats.forEach(cat => {
        const catCompanies = companies.filter(c => c.category_name === cat.name);
        categoryChildren.push(
            new Paragraph({ text: cat.name, heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 120 } })
        );
        if (cat.description) {
            categoryChildren.push(
                new Paragraph({ children: [new TextRun({ text: cat.description, color: '444444', size: 20 })], spacing: { after: 80 } })
            );
        }
        categoryChildren.push(
            new Paragraph({ children: [new TextRun({ text: `${catCompanies.length} companies`, color: '999999', size: 18, italics: true })], spacing: { after: 120 } })
        );

        const subs = categories.filter(c => c.parent_id === cat.id);
        subs.forEach(s => {
            categoryChildren.push(
                new Paragraph({ children: [new TextRun({ text: s.name, size: 20 })], bullet: { level: 0 }, spacing: { after: 40 } })
            );
        });
    });

    // Build companies table
    const headerCells = ['Company', 'Category', 'Funding', 'Employees', 'Geography'].map(h =>
        new TableCell({
            children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, size: 18, color: 'FFFFFF' })], alignment: AlignmentType.LEFT })],
            shading: { fill: '000000' },
            width: { size: 20, type: WidthType.PERCENTAGE },
        })
    );

    const dataRows = companies.map(c =>
        new TableRow({
            children: [c.name || '', c.category_name || '', c.funding_stage || '', c.employee_range || '', c.geography || ''].map(val =>
                new TableCell({
                    children: [new Paragraph({ children: [new TextRun({ text: val, size: 18 })], spacing: { before: 40, after: 40 } })],
                    width: { size: 20, type: WidthType.PERCENTAGE },
                })
            )
        })
    );

    const companiesTable = new Table({
        rows: [new TableRow({ children: headerCells, tableHeader: true }), ...dataRows],
        width: { size: 100, type: WidthType.PERCENTAGE },
    });

    const doc = new Document({
        creator: 'Research Taxonomy Library',
        title: project.name + ' - Market Taxonomy Report',
        sections: [{
            properties: {},
            children: [
                new Paragraph({ text: project.name, heading: HeadingLevel.TITLE, spacing: { after: 100 } }),
                new Paragraph({
                    children: [new TextRun({ text: 'Market Taxonomy Report', color: '666666', size: 26 })],
                    spacing: { after: 80 }
                }),
                new Paragraph({
                    children: [new TextRun({
                        text: 'Generated ' + new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }),
                        color: '999999', size: 20
                    })],
                    spacing: { after: 300 }
                }),
                new Paragraph({ text: 'Categories', heading: HeadingLevel.HEADING_1, spacing: { before: 240, after: 120 } }),
                ...categoryChildren,
                new Paragraph({ text: 'Companies', heading: HeadingLevel.HEADING_1, spacing: { before: 480, after: 120 } }),
                companiesTable,
            ]
        }]
    });

    const blob = await Packer.toBlob(doc);
    _safeSaveAs(blob, _safeFilename(project.name) + '.docx');
    if (notyf) notyf.success('Word document exported!');
}

// Tab wrapper
async function exportProjectWordFromTab() {
    const { project, companies, categories } = await _fetchExportData();
    await exportProjectWord(project, companies, categories);
}

// ============================================================
// TASK 4: ZIP Bundle Export (JSZip)
// ============================================================
async function exportProjectZip(project, companies, categories) {
    if (!window.JSZip) { showToast('ZIP library not loaded', 'error'); return; }
    const zip = new JSZip();

    // JSON
    zip.file('taxonomy.json', JSON.stringify({ project, categories, companies }, null, 2));

    // CSV
    zip.file('companies.csv', _convertToCSV(companies));

    // Markdown summary
    const md = _buildMarkdownSummary(project, companies, categories);
    zip.file('taxonomy-summary.md', md);

    const blob = await zip.generateAsync({ type: 'blob' });
    _safeSaveAs(blob, _safeFilename(project.name) + '-export.zip');
    if (notyf) notyf.success('ZIP bundle exported!');
}

function _buildMarkdownSummary(project, companies, categories) {
    const topCats = categories.filter(c => !c.parent_id);
    let md = `# ${project.name}\n\n`;
    md += `**Market Taxonomy Report** -- Generated ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}\n\n`;
    md += `${companies.length} companies across ${topCats.length} categories.\n\n`;
    md += `## Categories\n\n`;
    topCats.forEach(cat => {
        const count = companies.filter(c => c.category_name === cat.name).length;
        md += `### ${cat.name} (${count})\n`;
        if (cat.description) md += `${cat.description}\n`;
        const subs = categories.filter(c => c.parent_id === cat.id);
        subs.forEach(s => { md += `- ${s.name}\n`; });
        md += '\n';
    });
    md += `## Companies\n\n`;
    md += `| Name | Category | Funding | Geography |\n`;
    md += `|------|----------|---------|----------|\n`;
    companies.forEach(c => {
        md += `| ${c.name || ''} | ${c.category_name || ''} | ${c.funding_stage || ''} | ${c.geography || ''} |\n`;
    });
    return md;
}

// Tab wrapper
async function exportProjectZipFromTab() {
    const { project, companies, categories } = await _fetchExportData();
    await exportProjectZip(project, companies, categories);
}

// ============================================================
// TASK 5: Markdown Rendering Utility
// ============================================================
function renderMarkdown(text) {
    if (!text) return '';
    if (window.marked) {
        const html = marked.parse(text);
        // Sanitize with DOMPurify if available
        if (window.DOMPurify) return DOMPurify.sanitize(html);
        return html;
    }
    // Fallback: return plain text (escaped)
    return esc(text);
}
