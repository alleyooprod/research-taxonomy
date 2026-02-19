/**
 * Keyboard shortcuts and row selection.
 */

let selectedRowIndex = -1;
let shortcutOverlayVisible = false;

function showShortcutHelp() {
    if (shortcutOverlayVisible) { hideShortcutHelp(); return; }
    const overlay = document.createElement('div');
    overlay.className = 'shortcut-overlay';
    overlay.id = 'shortcutOverlay';
    overlay.onclick = (e) => { if (e.target === overlay) hideShortcutHelp(); };
    overlay.innerHTML = `
        <div class="shortcut-modal">
            <h2>Keyboard Shortcuts</h2>
            <div class="shortcut-row"><span>Navigate rows</span><span><span class="shortcut-key">j</span> <span class="shortcut-key">k</span></span></div>
            <div class="shortcut-row"><span>Open selected</span><span class="shortcut-key">Enter</span></div>
            <div class="shortcut-row"><span>Close panel / modal</span><span class="shortcut-key">Esc</span></div>
            <div class="shortcut-row"><span>Companies tab</span><span class="shortcut-key">1</span></div>
            <div class="shortcut-row"><span>Taxonomy tab</span><span class="shortcut-key">2</span></div>
            <div class="shortcut-row"><span>Process tab</span><span class="shortcut-key">3</span></div>
            <div class="shortcut-row"><span>Export tab</span><span class="shortcut-key">4</span></div>
            <div class="shortcut-row"><span>Focus search</span><span class="shortcut-key">/</span></div>
            <div class="shortcut-row"><span>Toggle dark mode</span><span class="shortcut-key">D</span></div>
            <div class="shortcut-row"><span>Star selected</span><span class="shortcut-key">S</span></div>
            <div class="shortcut-row"><span>Undo</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">Z</span></span></div>
            <div class="shortcut-row"><span>Redo</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">\u21e7</span><span class="shortcut-key">Z</span></span></div>
            <div class="shortcut-row"><span>Command palette</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">K</span></span></div>
            <div class="shortcut-row"><span>Find</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">F</span></span></div>
            <div class="shortcut-row"><span>Print</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">P</span></span></div>
            <div class="shortcut-row"><span>Settings</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">,</span></span></div>
            <div class="shortcut-row"><span>New project</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">N</span></span></div>
            <div class="shortcut-row"><span>Share</span><span><span class="shortcut-key">\u2318</span><span class="shortcut-key">\u21e7</span><span class="shortcut-key">S</span></span></div>
            <div class="shortcut-row"><span>This help</span><span class="shortcut-key">?</span></div>
        </div>
    `;
    document.body.appendChild(overlay);
    shortcutOverlayVisible = true;
}

function hideShortcutHelp() {
    const overlay = document.getElementById('shortcutOverlay');
    if (overlay) overlay.remove();
    shortcutOverlayVisible = false;
}

function selectRow(index) {
    const rows = document.querySelectorAll('#companyBody tr');
    if (!rows.length) return;

    if (index < 0) index = 0;
    if (index >= rows.length) index = rows.length - 1;

    rows.forEach(r => r.classList.remove('row-selected'));

    selectedRowIndex = index;
    rows[index].classList.add('row-selected');
    rows[index].scrollIntoView({ block: 'nearest' });
}

document.addEventListener('keydown', (e) => {
    // --- Cmd+K: Open ninja-keys command palette ---
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const ninja = document.querySelector('ninja-keys');
        if (ninja) ninja.open();
        return;
    }

    // --- macOS Native Shortcuts (checked first, regardless of focus) ---

    // Cmd+Z - Undo (when NOT in canvas tab or text input)
    if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
        const activeEl = document.activeElement;
        const isTextInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable);
        const isCanvasTab = document.querySelector('.tab.active')?.textContent?.trim()?.toLowerCase() === 'canvas';

        if (!isTextInput && !isCanvasTab) {
            e.preventDefault();
            performUndo();
            return;
        }
    }

    // Cmd+Shift+Z - Redo
    if ((e.metaKey || e.ctrlKey) && e.key === 'z' && e.shiftKey) {
        const activeEl = document.activeElement;
        const isTextInput = activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA' || activeEl.isContentEditable);
        const isCanvasTab = document.querySelector('.tab.active')?.textContent?.trim()?.toLowerCase() === 'canvas';

        if (!isTextInput && !isCanvasTab) {
            e.preventDefault();
            performRedo();
            return;
        }
    }

    // Cmd+F - Focus app search instead of browser find
    if ((e.metaKey || e.ctrlKey) && e.key === 'f') {
        e.preventDefault();
        const searchInput = document.getElementById('searchInput') || document.querySelector('input[type="search"]');
        if (searchInput) {
            searchInput.focus();
            searchInput.select();
        }
        return;
    }

    // Cmd+P - Print current view
    if ((e.metaKey || e.ctrlKey) && e.key === 'p') {
        e.preventDefault();
        window.print();
        return;
    }

    // Cmd+, - Open settings tab
    if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        const tabs = document.querySelectorAll('.tab');
        const settingsIdx = Array.from(tabs).findIndex(t => t.textContent.trim().toLowerCase() === 'settings');
        if (settingsIdx >= 0 && typeof showTab === 'function') showTab(settingsIdx);
        return;
    }

    // Cmd+N - New project (if on project selection screen)
    if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        const newProjectBtn = document.getElementById('newProjectBtn') || document.querySelector('[onclick*="showNewProject"]');
        if (newProjectBtn) {
            e.preventDefault();
            newProjectBtn.click();
        }
        return;
    }

    // Cmd+Shift+S - Share current view
    if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 's') {
        e.preventDefault();
        // Share the current company if detail panel is open, otherwise share project
        const detailPanel = document.getElementById('detailPanel');
        const isDetailOpen = detailPanel && !detailPanel.classList.contains('hidden');
        if (isDetailOpen && window._currentCompanyId) {
            shareCompany(window._currentCompanyId);
        } else {
            shareProject();
        }
        return;
    }

    // --- Standard Shortcuts ---
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
        if (e.key === 'Escape') { e.target.blur(); }
        return;
    }

    const editModal = document.getElementById('editModal');
    const editModalOpen = editModal && !editModal.classList.contains('hidden');

    if (e.key === 'Escape') {
        e.preventDefault();
        if (shortcutOverlayVisible) { hideShortcutHelp(); return; }
        if (editModalOpen) { closeEditModal(); return; }
        if (!document.getElementById('detailPanel').classList.contains('hidden')) { closeDetail(); return; }
        return;
    }

    if (editModalOpen || shortcutOverlayVisible) return;

    const mainApp = document.getElementById('mainApp');
    if (!mainApp || mainApp.classList.contains('hidden')) {
        if (e.key === 'd' || e.key === 'D') { toggleTheme(); return; }
        if (e.key === '?') { showShortcutHelp(); return; }
        return;
    }

    const tabNames = ['companies', 'taxonomy', 'map', 'process', 'export'];

    switch (e.key) {
        case 'j':
            e.preventDefault();
            selectRow(selectedRowIndex + 1);
            break;
        case 'k':
            e.preventDefault();
            selectRow(selectedRowIndex - 1);
            break;
        case 'Enter':
            if (selectedRowIndex >= 0) {
                const rows = document.querySelectorAll('#companyBody tr');
                if (rows[selectedRowIndex]) {
                    const id = rows[selectedRowIndex].getAttribute('data-company-id');
                    if (id) showDetail(parseInt(id));
                }
            }
            break;
        case '1': case '2': case '3': case '4': case '5':
            e.preventDefault();
            const tabIdx = parseInt(e.key) - 1;
            const tabs = document.querySelectorAll('.tab');
            if (tabs[tabIdx]) {
                document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                tabs.forEach(el => el.classList.remove('active'));
                document.getElementById('tab-' + tabNames[tabIdx]).classList.add('active');
                tabs[tabIdx].classList.add('active');
                if (tabNames[tabIdx] === 'companies') loadCompanies();
                if (tabNames[tabIdx] === 'taxonomy') loadTaxonomy();
                if (tabNames[tabIdx] === 'process') loadBatches();
            }
            break;
        case '/':
            e.preventDefault();
            document.getElementById('searchInput').focus();
            break;
        case 'd':
        case 'D':
            toggleTheme();
            break;
        case 's':
        case 'S':
            if (selectedRowIndex >= 0) {
                const rows = document.querySelectorAll('#companyBody tr');
                if (rows[selectedRowIndex]) {
                    const starBtn = rows[selectedRowIndex].querySelector('.star-btn');
                    const id = rows[selectedRowIndex].getAttribute('data-company-id');
                    if (id && starBtn) toggleStar(parseInt(id), starBtn);
                }
            }
            break;
        case '?':
            e.preventDefault();
            showShortcutHelp();
            break;
    }
});
