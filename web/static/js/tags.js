/**
 * Tag management modal: rename, merge, delete tags.
 */

async function openTagManager() {
    document.getElementById('tagModal').classList.remove('hidden');
    hideTagForms();
    window._tagModalFocusTrap = trapFocus(document.getElementById('tagModal'));
    const res = await safeFetch(`/api/tags?project_id=${currentProjectId}`);
    const tags = await res.json();
    document.getElementById('tagList').innerHTML = tags.length
        ? tags.map(t => `<div class="tag-manager-item">
            <span class="tag">${esc(t.tag)}</span>
            <span class="tag-count">${t.count} companies</span>
            <button class="tag-delete-btn" data-action="delete-tag" data-tag="${escAttr(t.tag)}" title="Delete tag">&times;</button>
          </div>`).join('')
        : '<p style="color:var(--text-muted);font-size:13px">No tags yet.</p>';
}

function closeTagManager() {
    if (window._tagModalFocusTrap) { window._tagModalFocusTrap(); window._tagModalFocusTrap = null; }
    document.getElementById('tagModal').classList.add('hidden');
}

function showTagRenameForm() {
    hideTagForms();
    document.getElementById('tagRenameForm').classList.remove('hidden');
}

function showTagMergeForm() {
    hideTagForms();
    document.getElementById('tagMergeForm').classList.remove('hidden');
}

function hideTagForms() {
    document.getElementById('tagRenameForm').classList.add('hidden');
    document.getElementById('tagMergeForm').classList.add('hidden');
}

async function executeTagRename() {
    const old_tag = document.getElementById('tagRenameOld').value.trim();
    const new_tag = document.getElementById('tagRenameNew').value.trim();
    if (!old_tag || !new_tag) { showToast('Enter both tag names'); return; }
    const res = await safeFetch('/api/tags/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old_tag, new_tag, project_id: currentProjectId }),
    });
    const data = await res.json();
    showUndoToast(`Renamed "${old_tag}" to "${new_tag}" (${data.updated} companies)`, async () => {
        await safeFetch('/api/tags/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_tag: new_tag, new_tag: old_tag, project_id: currentProjectId }),
        });
        openTagManager();
        loadCompanies();
    });
    openTagManager();
    loadCompanies();
    loadFilterOptions();
}

async function executeTagMerge() {
    const source = document.getElementById('tagMergeSource').value.trim();
    const target = document.getElementById('tagMergeTarget').value.trim();
    if (!source || !target) { showToast('Enter both tag names'); return; }
    await safeFetch('/api/tags/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_tag: source, target_tag: target, project_id: currentProjectId }),
    });
    openTagManager();
    loadCompanies();
    loadFilterOptions();
}

async function deleteTag(tagName) {
    if (!confirm(`Remove tag "${tagName}" from all companies?`)) return;
    await safeFetch('/api/tags/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tag: tagName, project_id: currentProjectId }),
    });
    openTagManager();
    loadCompanies();
    loadFilterOptions();
}

// --- Action Delegation ---
registerActions({
    'delete-tag': (el) => deleteTag(el.dataset.tag),
    'open-tag-manager': () => openTagManager(),
    'close-tag-manager': () => closeTagManager(),
    'show-tag-rename-form': () => showTagRenameForm(),
    'show-tag-merge-form': () => showTagMergeForm(),
    'execute-tag-rename': () => executeTagRename(),
    'execute-tag-merge': () => executeTagMerge(),
    'hide-tag-forms': () => hideTagForms(),
});
