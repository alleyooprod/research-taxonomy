/**
 * Company list, detail panel, edit modal, star, sort.
 */

let currentSort = { by: 'name', dir: 'asc' };
let currentCompanyView = 'table';
let _lastCompanies = [];

// --- Bulk Selection ---
let bulkSelection = new Set();
let _lastCheckedIdx = null;

function toggleBulkSelect(companyId, checkbox, event) {
    event.stopPropagation();
    const rows = Array.from(document.querySelectorAll('#companyBody tr[data-company-id]'));
    const currentIdx = rows.findIndex(r => r.dataset.companyId == companyId);

    if (event.shiftKey && _lastCheckedIdx !== null && currentIdx !== _lastCheckedIdx) {
        const start = Math.min(_lastCheckedIdx, currentIdx);
        const end = Math.max(_lastCheckedIdx, currentIdx);
        const shouldCheck = checkbox.checked;
        for (let i = start; i <= end; i++) {
            const id = parseInt(rows[i].dataset.companyId);
            const cb = rows[i].querySelector('.bulk-checkbox');
            if (cb) cb.checked = shouldCheck;
            if (shouldCheck) bulkSelection.add(id); else bulkSelection.delete(id);
        }
    } else {
        if (checkbox.checked) bulkSelection.add(companyId); else bulkSelection.delete(companyId);
    }
    _lastCheckedIdx = currentIdx;
    updateBulkBar();
}

function toggleSelectAll(masterCheckbox) {
    const checkboxes = document.querySelectorAll('.bulk-checkbox');
    checkboxes.forEach(cb => {
        cb.checked = masterCheckbox.checked;
        const id = parseInt(cb.dataset.companyId);
        if (masterCheckbox.checked) bulkSelection.add(id); else bulkSelection.delete(id);
    });
    updateBulkBar();
}

function clearBulkSelection() {
    bulkSelection.clear();
    _lastCheckedIdx = null;
    document.querySelectorAll('.bulk-checkbox').forEach(cb => cb.checked = false);
    const master = document.getElementById('selectAllCheckbox');
    if (master) master.checked = false;
    updateBulkBar();
}

function updateBulkBar() {
    const bar = document.getElementById('bulkActionBar');
    if (!bar) return;
    if (bulkSelection.size > 0) {
        bar.classList.remove('hidden');
        document.getElementById('bulkCount').textContent = `${bulkSelection.size} selected`;
    } else {
        bar.classList.add('hidden');
    }
}

async function bulkAction(action) {
    if (!bulkSelection.size) return;
    const ids = Array.from(bulkSelection);
    let params = {};

    if (action === 'assign_category') {
        const catId = prompt('Enter category ID to assign:');
        if (!catId) return;
        params.category_id = parseInt(catId);
    } else if (action === 'add_tags') {
        const tags = prompt('Enter tags (comma-separated):');
        if (!tags) return;
        params.tags = tags.split(',').map(t => t.trim()).filter(Boolean);
    } else if (action === 'set_relationship') {
        const status = prompt('Enter relationship status (watching, to_reach_out, in_conversation, met, partner, not_relevant):');
        if (!status) return;
        params.status = status;
    } else if (action === 'delete') {
        if (!confirm(`Delete ${ids.length} companies?`)) return;
    }

    const res = await safeFetch('/api/companies/bulk', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, company_ids: ids, params }),
    });
    const data = await res.json();

    if (action === 'delete') {
        showUndoToast(`Deleted ${data.updated} companies`, async () => {
            for (const id of ids) {
                await safeFetch(`/api/companies/${id}/restore`, { method: 'POST' });
            }
            loadCompanies();
            loadStats();
        });
    } else {
        showToast(`Updated ${data.updated} companies`);
    }

    clearBulkSelection();
    loadCompanies();
    loadStats();
}

function debounceSearch() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(loadCompanies, 300);
}

async function loadCompanies() {
    const search = document.getElementById('searchInput').value;
    const starred = document.getElementById('starredFilter').checked;
    const needsEnrichment = document.getElementById('enrichmentFilter').checked;
    let url = `/api/companies?project_id=${currentProjectId}&`;
    if (search) url += `search=${encodeURIComponent(search)}&`;
    if (activeFilters.category_id) url += `category_id=${activeFilters.category_id}&`;
    if (starred) url += `starred=1&`;
    if (needsEnrichment) url += `needs_enrichment=1&`;
    if (activeFilters.tags.length) url += `tags=${encodeURIComponent(activeFilters.tags.join(','))}&`;
    if (activeFilters.geography) url += `geography=${encodeURIComponent(activeFilters.geography)}&`;
    if (activeFilters.funding_stage) url += `funding_stage=${encodeURIComponent(activeFilters.funding_stage)}&`;
    if (activeFilters.founded_from) url += `founded_from=${activeFilters.founded_from}&`;
    if (activeFilters.founded_to) url += `founded_to=${activeFilters.founded_to}&`;
    const relFilter = document.getElementById('relationshipFilter').value;
    if (relFilter) url += `relationship_status=${encodeURIComponent(relFilter)}&`;
    url += `sort_by=${currentSort.by}&sort_dir=${currentSort.dir}&`;

    const res = await safeFetch(url);
    let companies = await res.json();
    // Client-side founded year range filter (in case backend doesn't support it)
    if (activeFilters.founded_from && activeFilters.founded_to) {
        companies = companies.filter(c => {
            if (!c.founded_year) return false;
            const y = parseInt(c.founded_year);
            return y >= activeFilters.founded_from && y <= activeFilters.founded_to;
        });
    }
    _lastCompanies = companies;

    // If not in table view, render the alternate view
    if (currentCompanyView !== 'table') {
        renderAlternateView(companies);
        return;
    }

    document.querySelectorAll('.sort-header').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === currentSort.by) {
            th.classList.add(currentSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
        }
    });

    const tbody = document.getElementById('companyBody');
    if (!companies.length) {
        const search = document.getElementById('searchInput').value;
        const hasFilters = search || activeFilters.category_id || activeFilters.tags.length
            || activeFilters.geography || activeFilters.funding_stage;
        tbody.innerHTML = `<tr><td colspan="10" class="empty-state">
            <div class="empty-state-content">
                <span class="empty-state-icon"><span class="material-symbols-outlined">search</span></span>
                <p class="empty-state-title">${hasFilters ? 'No companies match your filters' : 'No companies yet'}</p>
                <p class="empty-state-desc">${hasFilters
                    ? 'Try adjusting your search or <button class="empty-state-link" onclick="clearAllFilters()">clearing all filters</button>'
                    : 'Go to the <button class="empty-state-link" onclick="showTab(\'process\')">Process tab</button> to add companies'}</p>
            </div>
        </td></tr>`;
    } else {
        tbody.innerHTML = companies.map(c => {
            const compClass = c.completeness >= 0.7 ? 'comp-high' : c.completeness >= 0.4 ? 'comp-mid' : 'comp-low';
            const compPct = Math.round(c.completeness * 100);
            return `
            <tr onclick="showDetail(${c.id})" style="cursor:pointer" data-company-id="${c.id}">
                <td class="bulk-cell" onclick="event.stopPropagation()"><input type="checkbox" class="bulk-checkbox" data-company-id="${c.id}" ${bulkSelection.has(c.id) ? 'checked' : ''} onchange="toggleBulkSelect(${c.id}, this, event)"></td>
                <td><span class="star-btn ${c.is_starred ? 'starred' : ''}" onclick="event.stopPropagation();toggleStar(${c.id},this)" title="Star"><span class="material-symbols-outlined">${c.is_starred ? 'star' : 'star_outline'}</span></span></td>
                <td>
                    <div class="company-name-cell">
                        <img class="company-logo" src="${c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`}" alt="" onerror="this.style.display='none'">
                        <strong>${esc(c.name)}</strong>
                        <span class="completeness-dot ${compClass}" title="${compPct}% complete"></span>
                        ${c.relationship_status ? `<span class="relationship-dot rel-${c.relationship_status}" title="${relationshipLabel(c.relationship_status)}"></span>` : ''}
                    </div>
                </td>
                <td>${c.category_id ? `<a class="cat-link" onclick="event.stopPropagation();navigateTo('category',${c.category_id},'${escAttr(c.category_name)}')"><span class="cat-color-dot" style="background:${getCategoryColor(c.category_id) || 'transparent'}"></span> ${esc(c.category_name)}</a>` : 'N/A'}</td>
                <td><div class="cell-clamp">${esc(c.what || '')}</div></td>
                <td><div class="cell-clamp">${esc(c.target || '')}</div></td>
                <td><div class="cell-clamp">${esc(c.geography || '')}</div></td>
                <td><span class="source-count">${c.source_count || 0} links</span></td>
                <td>${(c.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join(' ')}</td>
                <td>${c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : '-'}</td>
            </tr>`;
        }).join('');
    }
}

async function toggleStar(id, el) {
    const res = await safeFetch(`/api/companies/${id}/star`, { method: 'POST' });
    const data = await res.json();
    el.innerHTML = `<span class="material-symbols-outlined">${data.is_starred ? 'star' : 'star_outline'}</span>`;
    el.classList.toggle('starred', !!data.is_starred);
}

async function saveRelationship(id) {
    const status = document.getElementById(`relStatus-${id}`).value;
    const note = document.getElementById(`relNote-${id}`).value;
    await safeFetch(`/api/companies/${id}/relationship`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ status: status || null, note })
    });
    loadCompanies();
}

async function showDetail(id) {
    const res = await safeFetch(`/api/companies/${id}`);
    const c = await res.json();

    let sourcesHtml = '';
    if (c.sources && c.sources.length) {
        sourcesHtml = `<div class="detail-field">
            <label>Sources (${c.sources.length})</label>
            <div class="sources-list">
                ${c.sources.map(s => `
                    <div class="source-item">
                        <span class="source-type-badge source-type-${s.source_type}">${esc(s.source_type)}</span>
                        <a href="${esc(s.url)}" target="_blank">${esc(s.url)}</a>
                        <span class="source-date">${new Date(s.added_at).toLocaleDateString()}</span>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }

    const logoUrl = c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`;
    const fundingAmt = c.total_funding_usd ? (typeof formatCurrency === 'function' ? formatCurrency(c.total_funding_usd) : '$' + Number(c.total_funding_usd).toLocaleString()) : null;

    document.getElementById('detailName').textContent = c.name;
    document.getElementById('detailContent').innerHTML = `
        <div class="detail-logo-row">
            <img class="detail-logo" src="${logoUrl}" alt="" onerror="this.style.display='none'">
            <a href="${esc(c.url)}" target="_blank">${esc(c.url)}</a>
            ${c.linkedin_url ? `<a href="${esc(c.linkedin_url)}" target="_blank" class="linkedin-link" title="LinkedIn">in</a>` : ''}
            ${c.url && typeof generateQrCode === 'function' ? `<button class="btn" style="padding:2px 6px;font-size:11px" onclick="event.stopPropagation();showCompanyQr('${escAttr(c.url)}','${escAttr(c.name)}')" title="Show QR code">QR</button>` : ''}
        </div>
        <div class="detail-field"><label>What</label><p>${esc(c.what || 'N/A')}</p></div>
        <div class="detail-field"><label>Target</label><p>${esc(c.target || 'N/A')}</p></div>
        <div class="detail-field"><label>Products</label><p>${esc(c.products || 'N/A')}</p></div>
        <div class="detail-firmographics">
            <div class="detail-field"><label>Funding</label><p>${esc(c.funding || 'N/A')}</p></div>
            <div class="detail-field"><label>Stage</label><p>${esc(c.funding_stage || 'N/A')}</p></div>
            <div class="detail-field"><label>Total Raised</label><p>${fundingAmt || 'N/A'}</p></div>
            <div class="detail-field"><label>Founded</label><p>${c.founded_year || 'N/A'}</p></div>
            <div class="detail-field"><label>Employees</label><p>${esc(c.employee_range || 'N/A')}</p></div>
            <div class="detail-field"><label>HQ</label><p>${esc(c.hq_city || '')}${c.hq_city && c.hq_country ? ', ' : ''}${esc(c.hq_country || 'N/A')}</p></div>
        </div>
        <div class="detail-field"><label>Geography</label><p>${esc(c.geography || 'N/A')}</p></div>
        <div class="detail-field"><label>TAM</label><p>${esc(c.tam || 'N/A')}</p></div>
        <div class="detail-field"><label>Category</label><p>${c.category_id ? `<a class="cat-link" onclick="navigateTo('category',${c.category_id},'${escAttr(c.category_name)}')">${esc(c.category_name)}</a>` : 'N/A'} / ${esc(c.subcategory_name || 'N/A')}</p></div>
        <div class="detail-field"><label>Tags</label><p>${(c.tags || []).join(', ') || 'None'}</p></div>
        <div class="detail-field"><label>Confidence</label><p>${c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : 'N/A'}</p></div>
        <div class="detail-field"><label>Processed</label><p>${c.processed_at || 'N/A'}</p></div>
        ${sourcesHtml}
        ${c.status && c.status !== 'active' ? `<div class="lifecycle-badge lifecycle-${c.status}">${esc(c.status)}</div>` : ''}
        ${c.business_model || c.company_stage || c.primary_focus ? `
        <div class="detail-facets">
            ${c.business_model ? `<span class="facet-badge facet-model">${esc(c.business_model)}</span>` : ''}
            ${c.company_stage ? `<span class="facet-badge facet-stage">${esc(c.company_stage)}</span>` : ''}
            ${c.primary_focus ? `<span class="facet-badge facet-focus">${esc(c.primary_focus)}</span>` : ''}
        </div>` : ''}
        <div class="detail-actions">
            <button class="btn" onclick="openEditModal(${c.id})">Edit</button>
            <button class="btn" onclick="openReResearch(${c.id})">Re-research</button>
            <button class="btn" onclick="startEnrichment(${c.id})">Enrich</button>
            <button class="btn" onclick="startCompanyResearch(${c.id}, '${escAttr(c.name)}')">Deep Dive</button>
            <button class="btn" onclick="findSimilar(${c.id})">Find Similar</button>
            <button class="btn" onclick="showVersionHistory(${c.id})">History</button>
            <button class="danger-btn" onclick="deleteCompany(${c.id})">Delete</button>
        </div>
        <div id="similarResults-${c.id}" class="hidden similar-results"></div>

        <!-- Relationship Section -->
        <div class="relationship-section">
            <label>Relationship</label>
            <div class="relationship-controls">
                <select id="relStatus-${c.id}" class="relationship-select" onchange="saveRelationship(${c.id})">
                    <option value="">-- None --</option>
                    <option value="watching" ${c.relationship_status === 'watching' ? 'selected' : ''}>Watching</option>
                    <option value="to_reach_out" ${c.relationship_status === 'to_reach_out' ? 'selected' : ''}>To Reach Out</option>
                    <option value="in_conversation" ${c.relationship_status === 'in_conversation' ? 'selected' : ''}>In Conversation</option>
                    <option value="met" ${c.relationship_status === 'met' ? 'selected' : ''}>Met</option>
                    <option value="partner" ${c.relationship_status === 'partner' ? 'selected' : ''}>Partner</option>
                    <option value="not_relevant" ${c.relationship_status === 'not_relevant' ? 'selected' : ''}>Not Relevant</option>
                </select>
                ${c.relationship_status ? `<span class="relationship-dot rel-${c.relationship_status}" style="width:10px;height:10px"></span>` : ''}
            </div>
            <textarea id="relNote-${c.id}" class="relationship-note" rows="2" placeholder="Notes about this relationship..."
                onblur="saveRelationship(${c.id})">${esc(c.relationship_note || '')}</textarea>
        </div>

        <!-- Notes Section -->
        <div class="detail-notes">
            <div class="detail-notes-header">
                <label>Notes</label>
                <button class="filter-action-btn" onclick="showAddNote(${c.id})">+ Add note</button>
            </div>
            <div id="addNoteForm-${c.id}" class="hidden" style="margin-bottom:8px">
                <textarea id="newNoteText-${c.id}" rows="2" placeholder="Add a note..."></textarea>
                <div style="display:flex;gap:6px;margin-top:4px">
                    <button class="primary-btn" onclick="addNote(${c.id})">Save</button>
                    <button class="btn" onclick="document.getElementById('addNoteForm-${c.id}').classList.add('hidden')">Cancel</button>
                </div>
            </div>
            <div id="notesList-${c.id}">
                ${(c.notes || []).map(n => `
                    <div class="note-item ${n.is_pinned ? 'note-pinned' : ''}">
                        <div class="note-content">${esc(n.content)}</div>
                        <div class="note-meta">
                            <span>${new Date(n.created_at).toLocaleDateString()}</span>
                            <span class="note-action" onclick="togglePinNote(${n.id},${c.id})">${n.is_pinned ? 'Unpin' : 'Pin'}</span>
                            <span class="note-action note-delete" onclick="deleteNote(${n.id},${c.id})">Delete</span>
                        </div>
                    </div>
                `).join('') || '<p style="font-size:12px;color:var(--text-muted)">No notes yet.</p>'}
            </div>
        </div>

        <!-- Events Section -->
        <div class="detail-events">
            <div class="detail-notes-header">
                <label>Events</label>
                <button class="filter-action-btn" onclick="showAddEvent(${c.id})">+ Add event</button>
            </div>
            <div id="addEventForm-${c.id}" class="hidden" style="margin-bottom:8px">
                <div style="display:flex;gap:6px;flex-wrap:wrap">
                    <select id="newEventType-${c.id}">
                        <option value="funding_round">Funding Round</option>
                        <option value="acquired">Acquired</option>
                        <option value="shut_down">Shut Down</option>
                        <option value="launched">Product Launch</option>
                        <option value="pivot">Pivot</option>
                        <option value="partnership">Partnership</option>
                    </select>
                    <input type="date" id="newEventDate-${c.id}">
                </div>
                <textarea id="newEventDesc-${c.id}" rows="1" placeholder="Description..." style="margin-top:4px"></textarea>
                <div style="display:flex;gap:6px;margin-top:4px">
                    <button class="primary-btn" onclick="addEvent(${c.id})">Save</button>
                    <button class="btn" onclick="document.getElementById('addEventForm-${c.id}').classList.add('hidden')">Cancel</button>
                </div>
            </div>
            <div id="eventsList-${c.id}">
                ${(c.events || []).map(ev => `
                    <div class="event-item">
                        <span class="event-type-badge">${esc(ev.event_type)}</span>
                        <span>${esc(ev.description || '')}</span>
                        <span class="event-date">${ev.event_date || ''}</span>
                        <span class="note-action note-delete" onclick="deleteEvent(${ev.id},${c.id})">Delete</span>
                    </div>
                `).join('') || '<p style="font-size:12px;color:var(--text-muted)">No events yet.</p>'}
            </div>
        </div>

        <div id="reResearchForm-${c.id}" class="re-research-form hidden">
            <label>Additional source URLs (one per line):</label>
            <textarea id="reResearchUrls-${c.id}" rows="3" placeholder="https://example.com/about&#10;https://crunchbase.com/organization/..."></textarea>
            <div class="re-research-actions">
                <button class="primary-btn" onclick="startReResearch(${c.id})">Run Re-research</button>
                <button class="btn" onclick="closeReResearch(${c.id})">Cancel</button>
            </div>
            <div id="reResearchStatus-${c.id}" class="hidden"></div>
        </div>
    `;
    document.getElementById('detailPanel').classList.remove('hidden');
}

function closeDetail() {
    document.getElementById('detailPanel').classList.add('hidden');
}

async function deleteCompany(id) {
    if (!confirm('Delete this company?')) return;
    await safeFetch(`/api/companies/${id}`, { method: 'DELETE' });
    closeDetail();
    loadCompanies();
    loadStats();
}

// --- Re-Research ---
function openReResearch(id) {
    document.getElementById(`reResearchForm-${id}`).classList.remove('hidden');
}

function closeReResearch(id) {
    document.getElementById(`reResearchForm-${id}`).classList.add('hidden');
}

async function startReResearch(companyId) {
    const urlsText = document.getElementById(`reResearchUrls-${companyId}`).value;
    const urls = urlsText.split('\n').map(u => u.trim()).filter(Boolean);
    if (!urls.length) { showToast('Enter at least one URL'); return; }

    const statusDiv = document.getElementById(`reResearchStatus-${companyId}`);
    statusDiv.classList.remove('hidden');
    statusDiv.innerHTML = '<div class="progress-bar"><div class="progress-fill" style="width:30%;animation:pulse 2s infinite"></div></div><p>Re-researching with additional sources...</p>';

    const res = await safeFetch(`/api/companies/${companyId}/re-research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls, model: document.getElementById('modelSelect').value }),
    });
    const data = await res.json();
    pollReResearch(companyId, data.research_id);
}

let _reResearchPollCount = 0;
const _MAX_RERESEARCH_RETRIES = 60;

async function pollReResearch(companyId, researchId) {
    const res = await safeFetch(`/api/re-research/${researchId}`);
    const data = await res.json();

    if (data.status === 'pending') {
        if (++_reResearchPollCount > _MAX_RERESEARCH_RETRIES) {
            data.status = 'error';
            data.error = 'Re-research timed out. Please try again.';
        } else {
            setTimeout(() => pollReResearch(companyId, researchId), 3000);
            return;
        }
    }
    _reResearchPollCount = 0;

    const statusDiv = document.getElementById(`reResearchStatus-${companyId}`);
    if (data.status === 'error') {
        statusDiv.innerHTML = `<p class="re-research-error">${esc(data.error)}</p>`;
    } else {
        statusDiv.innerHTML = '<p class="re-research-success">Research updated successfully!</p>';
        setTimeout(() => {
            showDetail(companyId);
            loadCompanies();
            loadStats();
        }, 1000);
    }
}

// --- Edit Modal ---
async function openEditModal(id) {
    const res = await safeFetch(`/api/companies/${id}`);
    const c = await res.json();

    const taxRes = await safeFetch(`/api/taxonomy?project_id=${currentProjectId}`);
    allCategories = await taxRes.json();

    const topLevel = allCategories.filter(c => !c.parent_id);
    const catSelect = document.getElementById('editCategory');
    catSelect.innerHTML = '<option value="">-- Select --</option>' +
        topLevel.map(cat => `<option value="${cat.id}">${esc(cat.name)}</option>`).join('');

    document.getElementById('editId').value = c.id;
    document.getElementById('editName').value = c.name || '';
    document.getElementById('editUrl').value = c.url || '';
    document.getElementById('editWhat').value = c.what || '';
    document.getElementById('editTarget').value = c.target || '';
    document.getElementById('editProducts').value = c.products || '';
    document.getElementById('editFunding').value = c.funding || '';
    document.getElementById('editGeography').value = c.geography || '';
    document.getElementById('editTam').value = c.tam || '';
    document.getElementById('editTags').value = (c.tags || []).join(', ');
    document.getElementById('editEmployeeRange').value = c.employee_range || '';
    document.getElementById('editFoundedYear').value = c.founded_year || '';
    document.getElementById('editFundingStage').value = c.funding_stage || '';
    document.getElementById('editTotalFunding').value = c.total_funding_usd || '';
    document.getElementById('editHqCity').value = c.hq_city || '';
    document.getElementById('editHqCountry').value = c.hq_country || '';
    document.getElementById('editLinkedin').value = c.linkedin_url || '';
    document.getElementById('editBusinessModel').value = c.business_model || '';
    document.getElementById('editCompanyStage').value = c.company_stage || '';
    document.getElementById('editPrimaryFocus').value = c.primary_focus || '';

    catSelect.value = c.category_id || '';
    loadSubcategories();
    document.getElementById('editSubcategory').value = c.subcategory_id || '';

    document.getElementById('editModal').classList.remove('hidden');
    window._editModalFocusTrap = trapFocus(document.getElementById('editModal'));
}

function loadSubcategories() {
    const parentId = parseInt(document.getElementById('editCategory').value);
    const subSelect = document.getElementById('editSubcategory');
    const subs = allCategories.filter(c => c.parent_id === parentId);
    subSelect.innerHTML = '<option value="">-- Select --</option>' +
        subs.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
}

function closeEditModal() {
    if (window._editModalFocusTrap) { window._editModalFocusTrap(); window._editModalFocusTrap = null; }
    document.getElementById('editModal').classList.add('hidden');
}

async function saveEdit(event) {
    event.preventDefault();
    const id = document.getElementById('editId').value;
    const tagsStr = document.getElementById('editTags').value;
    const tags = tagsStr ? tagsStr.split(',').map(t => t.trim()).filter(Boolean) : [];

    const prevRes = await safeFetch(`/api/companies/${id}`);
    const prevData = await prevRes.json();

    const fields = {
        name: document.getElementById('editName').value,
        url: document.getElementById('editUrl').value,
        what: document.getElementById('editWhat').value,
        target: document.getElementById('editTarget').value,
        products: document.getElementById('editProducts').value,
        funding: document.getElementById('editFunding').value,
        geography: document.getElementById('editGeography').value,
        tam: document.getElementById('editTam').value,
        category_id: document.getElementById('editCategory').value || null,
        subcategory_id: document.getElementById('editSubcategory').value || null,
        tags: tags,
        project_id: currentProjectId,
        employee_range: document.getElementById('editEmployeeRange').value || null,
        founded_year: document.getElementById('editFoundedYear').value ? parseInt(document.getElementById('editFoundedYear').value) : null,
        funding_stage: document.getElementById('editFundingStage').value || null,
        total_funding_usd: document.getElementById('editTotalFunding').value ? parseFloat(document.getElementById('editTotalFunding').value) : null,
        hq_city: document.getElementById('editHqCity').value || null,
        hq_country: document.getElementById('editHqCountry').value || null,
        linkedin_url: document.getElementById('editLinkedin').value || null,
        business_model: document.getElementById('editBusinessModel').value || null,
        company_stage: document.getElementById('editCompanyStage').value || null,
        primary_focus: document.getElementById('editPrimaryFocus').value || null,
    };

    await safeFetch(`/api/companies/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(fields),
    });

    closeEditModal();
    closeDetail();
    loadCompanies();
    loadStats();

    showUndoToast(`Updated ${fields.name}`, async () => {
        const undoFields = {
            name: prevData.name, url: prevData.url, what: prevData.what,
            target: prevData.target, products: prevData.products, funding: prevData.funding,
            geography: prevData.geography, tam: prevData.tam,
            category_id: prevData.category_id, subcategory_id: prevData.subcategory_id,
            tags: prevData.tags || [], project_id: currentProjectId,
            employee_range: prevData.employee_range, founded_year: prevData.founded_year,
            funding_stage: prevData.funding_stage, total_funding_usd: prevData.total_funding_usd,
            hq_city: prevData.hq_city, hq_country: prevData.hq_country,
            linkedin_url: prevData.linkedin_url,
            business_model: prevData.business_model, company_stage: prevData.company_stage,
            primary_focus: prevData.primary_focus,
        };
        await safeFetch(`/api/companies/${id}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(undoFields),
        });
        loadCompanies();
        loadStats();
    });
}

// --- Notes ---
function showAddNote(companyId) {
    document.getElementById(`addNoteForm-${companyId}`).classList.remove('hidden');
}

async function addNote(companyId) {
    const content = document.getElementById(`newNoteText-${companyId}`).value.trim();
    if (!content) return;
    await safeFetch(`/api/companies/${companyId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
    });
    showDetail(companyId);
}

async function deleteNote(noteId, companyId) {
    await safeFetch(`/api/notes/${noteId}`, { method: 'DELETE' });
    showDetail(companyId);
}

async function togglePinNote(noteId, companyId) {
    await safeFetch(`/api/notes/${noteId}/pin`, { method: 'POST' });
    showDetail(companyId);
}

// --- Events ---
function showAddEvent(companyId) {
    document.getElementById(`addEventForm-${companyId}`).classList.remove('hidden');
}

async function addEvent(companyId) {
    const event_type = document.getElementById(`newEventType-${companyId}`).value;
    const description = document.getElementById(`newEventDesc-${companyId}`).value.trim();
    const event_date = document.getElementById(`newEventDate-${companyId}`).value || null;
    await safeFetch(`/api/companies/${companyId}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_type, description, event_date }),
    });
    showDetail(companyId);
}

async function deleteEvent(eventId, companyId) {
    await safeFetch(`/api/events/${eventId}`, { method: 'DELETE' });
    showDetail(companyId);
}

// --- Version History ---
async function showVersionHistory(companyId) {
    const res = await safeFetch(`/api/companies/${companyId}/versions`);
    const versions = await res.json();

    let html = '<div class="version-history"><h3>Version History</h3>';
    if (!versions.length) {
        html += '<p style="font-size:13px;color:var(--text-muted)">No version history yet. Versions are created automatically when you edit a company.</p>';
    } else {
        html += versions.map((v, i) => `
            <div class="version-item">
                <div class="version-meta">
                    <span class="version-desc">${esc(v.change_description || 'Edit')}</span>
                    <span class="version-date">${new Date(v.created_at).toLocaleString()}</span>
                </div>
                <div style="display:flex;gap:4px">
                    ${i < versions.length - 1 ? `<button class="filter-action-btn" onclick="showVersionDiff(${companyId},${v.id},${versions[i+1].id})">Diff</button>` : ''}
                    <button class="filter-action-btn" onclick="restoreVersion(${v.id},${companyId})">Restore</button>
                </div>
            </div>
        `).join('');
    }
    html += '<button class="btn" onclick="showDetail(' + companyId + ')" style="margin-top:10px">Back</button></div>';
    document.getElementById('detailContent').innerHTML = html;
}

async function showVersionDiff(companyId, newVersionId, oldVersionId) {
    const [newRes, oldRes] = await Promise.all([
        safeFetch(`/api/versions/${newVersionId}`),
        safeFetch(`/api/versions/${oldVersionId}`),
    ]);
    const newV = await newRes.json();
    const oldV = await oldRes.json();
    const fields = ['name','what','target','products','geography','funding','funding_stage','total_funding_usd','employee_range','founded_year','hq_city','hq_country','tam','business_model'];

    if (window.Diff2Html) {
        // Build unified diff string
        let diffStr = '';
        fields.forEach(f => {
            const oldVal = String((oldV.data && oldV.data[f]) || '');
            const newVal = String((newV.data && newV.data[f]) || '');
            if (oldVal !== newVal) {
                diffStr += `--- a/${f}\n+++ b/${f}\n@@ -1 +1 @@\n-${oldVal}\n+${newVal}\n`;
            }
        });
        if (!diffStr) diffStr = '--- a/no-changes\n+++ b/no-changes\n@@ -0,0 +0,0 @@\n No differences found\n';
        const diffHtml = Diff2Html.html(diffStr, { drawFileList: false, outputFormat: 'side-by-side', matching: 'lines' });
        document.getElementById('detailContent').innerHTML = `
            <div class="version-history"><h3>Version Diff</h3>
            ${diffHtml}
            <button class="btn" onclick="showVersionHistory(${companyId})" style="margin-top:10px">Back to History</button></div>`;
    } else {
        // Fallback: simple text diff
        let html = '<div class="version-history"><h3>Version Diff</h3><table class="compare-table"><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>';
        fields.forEach(f => {
            const oldVal = (oldV.data && oldV.data[f]) || '';
            const newVal = (newV.data && newV.data[f]) || '';
            if (oldVal !== newVal) {
                html += `<tr><td><strong>${esc(f)}</strong></td><td style="color:var(--accent-danger)">${esc(String(oldVal))}</td><td style="color:var(--accent-green)">${esc(String(newVal))}</td></tr>`;
            }
        });
        html += '</tbody></table><button class="btn" onclick="showVersionHistory(' + companyId + ')" style="margin-top:10px">Back to History</button></div>';
        document.getElementById('detailContent').innerHTML = html;
    }
}

async function restoreVersion(versionId, companyId) {
    if (!confirm('Restore this version? Current state will be saved as a version first.')) return;
    await safeFetch(`/api/versions/${versionId}/restore`, { method: 'POST' });
    showDetail(companyId);
    loadCompanies();
}

function showCompanyQr(url, name) {
    const qrHtml = typeof generateQrCode === 'function' ? generateQrCode(url, 6) : null;
    if (!qrHtml) { showToast('QR code library not loaded'); return; }
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    modal.innerHTML = `<div class="modal" style="max-width:320px;text-align:center;padding:24px">
        <h3 style="margin:0 0 12px">${esc(name)}</h3>
        <div style="display:inline-block;padding:12px;background:#fff;border-radius:8px">${qrHtml}</div>
        <p style="margin:8px 0 0;font-size:12px;color:var(--text-muted)">${esc(url)}</p>
        <button class="btn" onclick="this.closest('.modal-overlay').remove()" style="margin-top:12px">Close</button>
    </div>`;
    document.body.appendChild(modal);
}

// --- Escape to clear bulk selection ---
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && bulkSelection.size > 0) {
        clearBulkSelection();
    }
});

// --- Enrichment ---
async function startEnrichment(companyId) {
    showToast('Starting enrichment...');
    const res = await safeFetch(`/api/companies/${companyId}/enrich`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: document.getElementById('modelSelect')?.value || 'sonnet' }),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error); return; }
    pollEnrichment(data.job_id, companyId);
}

let _enrichPollCount = 0;
const _MAX_ENRICH_RETRIES = 120;

async function pollEnrichment(jobId, companyId) {
    const res = await safeFetch(`/api/enrich/${jobId}`);
    const data = await res.json();
    if (data.status === 'pending') {
        if (++_enrichPollCount > _MAX_ENRICH_RETRIES) {
            showToast('Enrichment timed out');
            return;
        }
        setTimeout(() => pollEnrichment(jobId, companyId), 3000);
        return;
    }
    _enrichPollCount = 0;
    if (data.status === 'error') {
        showToast('Enrichment failed: ' + (data.error || ''));
    } else {
        const fields = data.enriched_fields || [];
        showToast(`Enriched ${fields.length} fields (${data.steps_run} steps)`);
        if (companyId) showDetail(companyId);
        loadCompanies();
    }
}

async function startBatchEnrichment() {
    const ids = bulkSelection.size > 0 ? Array.from(bulkSelection) : null;
    showToast('Starting batch enrichment...');
    const res = await safeFetch('/api/companies/enrich-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            company_ids: ids,
            model: document.getElementById('modelSelect')?.value || 'sonnet',
        }),
    });
    const data = await res.json();
    if (data.error) { showToast(data.error); return; }
    showToast(`Enriching ${data.count} companies...`);
    _enrichPollCount = 0;
    pollEnrichment(data.job_id, null);
}

// --- Company View Switching ---
function switchCompanyView(view) {
    currentCompanyView = view;
    const table = document.getElementById('companyTable');
    const container = document.getElementById('companyViewContainer');
    document.querySelectorAll('.company-view-toggle .view-toggle-btn').forEach(b => b.classList.remove('active'));

    if (view === 'table') {
        table.classList.remove('hidden');
        container.classList.add('hidden');
        document.getElementById('viewTableBtn').classList.add('active');
        loadCompanies();
    } else {
        table.classList.add('hidden');
        container.classList.remove('hidden');
        document.getElementById(`view${view.charAt(0).toUpperCase() + view.slice(1)}Btn`).classList.add('active');
        renderAlternateView(_lastCompanies);
    }
}

function renderAlternateView(companies) {
    const container = document.getElementById('companyViewContainer');
    if (currentCompanyView === 'gallery') renderGalleryView(companies, container);
    else if (currentCompanyView === 'timeline') renderTimelineView(companies, container);
    else if (currentCompanyView === 'matrix') renderMatrixView(companies, container);
}

function renderGalleryView(companies, container) {
    if (!companies.length) {
        container.innerHTML = '<p class="hint-text" style="padding:20px">No companies to display.</p>';
        return;
    }
    container.innerHTML = `<div class="gallery-grid">${companies.map(c => {
        const color = getCategoryColor(c.category_id) || 'var(--border-default)';
        const logoUrl = c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`;
        return `<div class="gallery-card" onclick="showDetail(${c.id})" style="border-top:3px solid ${color}">
            <div class="gallery-card-header">
                <img class="gallery-logo" src="${logoUrl}" alt="" onerror="this.style.display='none'">
                <div>
                    <strong>${esc(c.name)}</strong>
                    ${c.category_name ? `<div class="gallery-cat"><span class="cat-color-dot" style="background:${color}"></span> ${esc(c.category_name)}</div>` : ''}
                </div>
                ${c.is_starred ? '<span class="material-symbols-outlined" style="color:var(--wheat);font-size:16px;margin-left:auto">star</span>' : ''}
            </div>
            <p class="gallery-desc">${esc((c.what || '').substring(0, 120))}</p>
            <div class="gallery-meta">
                ${c.geography ? `<span>${esc(c.geography)}</span>` : ''}
                ${c.funding_stage ? `<span>${esc(c.funding_stage)}</span>` : ''}
                ${c.founded_year ? `<span>${c.founded_year}</span>` : ''}
            </div>
            <div class="gallery-tags">${(c.tags || []).slice(0, 3).map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
        </div>`;
    }).join('')}</div>`;
}

function renderTimelineView(companies, container) {
    const withYear = companies.filter(c => c.founded_year);
    if (!withYear.length) {
        container.innerHTML = '<p class="hint-text" style="padding:20px">No companies with founding year data for timeline view.</p>';
        return;
    }
    const byYear = {};
    withYear.forEach(c => {
        const y = c.founded_year;
        if (!byYear[y]) byYear[y] = [];
        byYear[y].push(c);
    });
    const years = Object.keys(byYear).sort((a, b) => a - b);

    container.innerHTML = `<div class="timeline-container">
        <div class="timeline-track">
            ${years.map(y => `<div class="timeline-year">
                <div class="timeline-year-label">${y}</div>
                <div class="timeline-year-dots">
                    ${byYear[y].map(c => {
                        const color = getCategoryColor(c.category_id) || '#888';
                        return `<div class="timeline-dot" style="background:${color}" onclick="showDetail(${c.id})" title="${esc(c.name)} — ${esc(c.category_name || '')}"></div>`;
                    }).join('')}
                </div>
            </div>`).join('')}
        </div>
    </div>`;
}

function renderMatrixView(companies, container) {
    if (!companies.length) {
        container.innerHTML = '<p class="hint-text" style="padding:20px">No companies for matrix view.</p>';
        return;
    }
    // Rows: categories, Columns: geographies
    const cats = {};
    const geos = new Set();
    companies.forEach(c => {
        const catName = c.category_name || 'Uncategorized';
        const geo = c.geography || 'Unknown';
        if (!cats[catName]) cats[catName] = {};
        const geoKey = geo.split(',')[0].trim(); // use first geo segment
        geos.add(geoKey);
        if (!cats[catName][geoKey]) cats[catName][geoKey] = [];
        cats[catName][geoKey].push(c);
    });
    const geoList = Array.from(geos).sort();
    const catNames = Object.keys(cats).sort();

    container.innerHTML = `<div class="matrix-wrapper"><table class="matrix-table">
        <thead><tr><th>Category</th>${geoList.map(g => `<th>${esc(g)}</th>`).join('')}<th>Total</th></tr></thead>
        <tbody>${catNames.map(cat => {
            const total = geoList.reduce((s, g) => s + (cats[cat][g] ? cats[cat][g].length : 0), 0);
            return `<tr><td><strong>${esc(cat)}</strong></td>
                ${geoList.map(g => {
                    const count = cats[cat][g] ? cats[cat][g].length : 0;
                    return `<td class="matrix-cell ${count ? 'matrix-filled' : ''}" ${count ? `onclick="showMatrixDetail('${escAttr(cat)}','${escAttr(g)}')" style="cursor:pointer"` : ''}>${count || ''}</td>`;
                }).join('')}
                <td><strong>${total}</strong></td>
            </tr>`;
        }).join('')}</tbody>
        <tfoot><tr><td><strong>Total</strong></td>${geoList.map(g => {
            const total = catNames.reduce((s, cat) => s + (cats[cat][g] ? cats[cat][g].length : 0), 0);
            return `<td><strong>${total}</strong></td>`;
        }).join('')}<td><strong>${companies.length}</strong></td></tr></tfoot>
    </table></div>`;
}

function showMatrixDetail(catName, geoKey) {
    const matches = _lastCompanies.filter(c =>
        (c.category_name || 'Uncategorized') === catName &&
        (c.geography || 'Unknown').split(',')[0].trim() === geoKey
    );
    const panel = document.getElementById('detailPanel');
    document.getElementById('detailName').textContent = `${catName} × ${geoKey}`;
    document.getElementById('detailContent').innerHTML = `
        <p>${matches.length} companies</p>
        <div class="category-company-list">
            ${matches.map(c => `
                <div class="cat-company-item" onclick="showDetail(${c.id})">
                    <strong>${esc(c.name)}</strong>
                    <span class="text-muted" style="font-size:11px;margin-left:auto">${esc(c.what || '').substring(0, 60)}</span>
                </div>
            `).join('')}
        </div>
        <button class="btn" onclick="closeDetail()" style="margin-top:12px">Close</button>
    `;
    panel.classList.remove('hidden');
}

// --- Sort Headers ---
document.addEventListener('click', (e) => {
    const th = e.target.closest('.sort-header');
    if (!th) return;
    const sortKey = th.dataset.sort;
    if (currentSort.by === sortKey) {
        currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
    } else {
        currentSort.by = sortKey;
        currentSort.dir = 'asc';
    }
    loadCompanies();
});
