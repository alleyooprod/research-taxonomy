/**
 * Canvas: visual workspace powered by Excalidraw.
 * Replaces the old Fabric.js implementation with a battle-tested whiteboard.
 * Lazy-loads React + Excalidraw via dynamic import() on first use.
 */

// Fallback if showNativeConfirm hasn't been loaded yet
const _confirmCanvas = window.showNativeConfirm || (async (opts) => confirm(opts.message || opts.title));

let _currentCanvasId = null;
let _canvasSaveTimeout = null;
let _canvasCompanies = [];
let _excalidrawAPI = null;          // Excalidraw imperative API ref
let _excalidrawReact = null;        // cached React module
let _excalidrawCreateRoot = null;   // cached ReactDOM.createRoot
let _excalidrawLib = null;          // cached Excalidraw module
let _excalidrawRoot = null;         // React root
let _excalidrawLoading = false;     // prevent double-init

// --- Excalidraw Lazy Loader ---

async function _loadExcalidraw() {
    if (_excalidrawLib) return { React: _excalidrawReact, Lib: _excalidrawLib };
    if (_excalidrawLoading) {
        // Wait for in-flight load
        while (_excalidrawLoading) await new Promise(r => setTimeout(r, 100));
        return { React: _excalidrawReact, Lib: _excalidrawLib };
    }
    _excalidrawLoading = true;
    try {
        _excalidrawReact = await import("react");
        const ReactDOM = await import("react-dom/client");
        _excalidrawLib = await import(
            "https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/dev/index.js?external=react,react-dom"
        );
        _excalidrawCreateRoot = ReactDOM.createRoot;
        console.log("Excalidraw loaded successfully");
        return { React: _excalidrawReact, Lib: _excalidrawLib };
    } catch (err) {
        console.error("Failed to load Excalidraw:", err);
        showToast("Failed to load canvas library. Check your internet connection.");
        throw err;
    } finally {
        _excalidrawLoading = false;
    }
}

// --- Canvas Reset (called when switching projects) ---

function resetCanvasState() {
    _currentCanvasId = null;
    _unmountExcalidraw();
    const sel = document.getElementById('canvasSelect');
    if (sel) sel.innerHTML = '<option value="">Select canvas...</option>';
    const wrapper = document.getElementById('canvasWrapper');
    if (wrapper) wrapper.classList.add('hidden');
    const empty = document.getElementById('canvasEmptyState');
    if (empty) empty.classList.remove('hidden');
    setCanvasButtonsEnabled(false);
}

// --- Canvas List ---

async function loadCanvasList() {
    const res = await safeFetch(`/api/canvases?project_id=${currentProjectId}`);
    const items = await res.json();
    const sel = document.getElementById('canvasSelect');
    const currentVal = sel.value;
    sel.innerHTML = '<option value="">Select canvas...</option>' +
        items.map(c => `<option value="${c.id}">${esc(c.title)}</option>`).join('');
    if (currentVal) sel.value = currentVal;
    loadCanvasSidebarCompanies();
}

async function loadCanvasSidebarCompanies() {
    const res = await safeFetch(`/api/companies?project_id=${currentProjectId}&limit=500`);
    const data = await res.json();
    _canvasCompanies = Array.isArray(data) ? data : [];
    renderCanvasSidebar(_canvasCompanies);
}

function renderCanvasSidebar(companies) {
    const container = document.getElementById('canvasCompanyList');
    if (!container || !Array.isArray(companies)) return;
    container.innerHTML = companies.map(c => {
        const color = typeof getCategoryColor === 'function' ? getCategoryColor(c.category_id) : '#999';
        return `<div class="canvas-sidebar-item" draggable="true"
            ondragstart="onCanvasDragStart(event, ${c.id}, '${escAttr(c.name)}', '${escAttr(c.category_name || '')}', '${color}')"
            title="${esc(c.name)}">
            <span class="cat-color-dot" style="background:${color}"></span>
            <span class="canvas-sidebar-name">${esc(c.name)}</span>
        </div>`;
    }).join('');
}

function filterCanvasCompanies() {
    const q = document.getElementById('canvasCompanySearch').value.toLowerCase();
    const filtered = q ? _canvasCompanies.filter(c =>
        c.name.toLowerCase().includes(q) || (c.category_name || '').toLowerCase().includes(q)
    ) : _canvasCompanies;
    renderCanvasSidebar(filtered);
}

// --- Custom prompt (pywebview blocks native prompt()) ---

function _ensurePromptSheet() {
    if (document.getElementById('promptSheet')) return;
    const html = `<div id="promptSheet" class="confirm-sheet-overlay" style="display:none;">
      <div class="confirm-sheet">
        <div id="promptSheetTitle" class="confirm-sheet-title">Enter a name</div>
        <input id="promptSheetInput" type="text" class="prompt-sheet-input" autocomplete="off" />
        <div class="confirm-sheet-actions confirm-sheet-actions-mt">
          <button id="promptSheetConfirm" class="confirm-btn-primary">Create</button>
          <button id="promptSheetCancel" class="confirm-btn-cancel">Cancel</button>
        </div>
      </div>
    </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
}

function _showPrompt(title, placeholder, confirmText) {
    return new Promise((resolve) => {
        _ensurePromptSheet();
        const overlay = document.getElementById('promptSheet');

        document.getElementById('promptSheetTitle').textContent = title || 'Enter a name';
        const input = document.getElementById('promptSheetInput');
        const confirmBtn = document.getElementById('promptSheetConfirm');
        const cancelBtn = document.getElementById('promptSheetCancel');
        input.value = '';
        input.placeholder = placeholder || '';
        confirmBtn.textContent = confirmText || 'Create';

        overlay.style.display = 'flex';
        requestAnimationFrame(() => { overlay.classList.add('visible'); input.focus(); });

        function cleanup() {
            overlay.classList.remove('visible');
            setTimeout(() => { overlay.style.display = 'none'; }, 200);
            confirmBtn.removeEventListener('click', onConfirm);
            cancelBtn.removeEventListener('click', onCancel);
            input.removeEventListener('keydown', onKey);
        }
        function onConfirm() { const v = input.value.trim(); cleanup(); resolve(v || null); }
        function onCancel() { cleanup(); resolve(null); }
        function onKey(e) {
            if (e.key === 'Enter') { onConfirm(); }
            else if (e.key === 'Escape') { onCancel(); }
        }
        confirmBtn.addEventListener('click', onConfirm);
        cancelBtn.addEventListener('click', onCancel);
        input.addEventListener('keydown', onKey);
    });
}

// --- Canvas CRUD ---

async function createNewCanvas() {
    const title = await _showPrompt('Canvas name', 'My canvas...', 'Create');
    if (!title) return;
    const res = await safeFetch('/api/canvases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, title }),
    });
    if (!res.ok) { showToast('Failed to create canvas'); return; }
    const data = await res.json();
    if (data.id) {
        await loadCanvasList();
        document.getElementById('canvasSelect').value = data.id;
        loadCanvasFromSelect();
    } else {
        showToast('Canvas creation failed');
    }
}

function loadCanvasFromSelect() {
    const id = document.getElementById('canvasSelect').value;
    if (id) {
        loadCanvas(parseInt(id));
    } else {
        _currentCanvasId = null;
        _unmountExcalidraw();
        document.getElementById('canvasWrapper').classList.add('hidden');
        document.getElementById('canvasEmptyState').classList.remove('hidden');
        setCanvasButtonsEnabled(false);
    }
}

async function loadCanvas(canvasId) {
    _currentCanvasId = canvasId;
    const res = await safeFetch(`/api/canvases/${canvasId}`);
    const canvasData = await res.json();
    if (canvasData.error) { showToast('Canvas not found'); return; }

    document.getElementById('canvasEmptyState').classList.add('hidden');
    document.getElementById('canvasWrapper').classList.remove('hidden');
    setCanvasButtonsEnabled(true);

    const data = canvasData.data || {};

    // Detect old Fabric.js format
    if (data.objects && !data.elements) {
        showToast('This canvas used the old editor. Starting fresh.');
        initExcalidrawCanvas([]);
        return;
    }

    initExcalidrawCanvas(data.elements || [], data.appState || {});
}

function setCanvasButtonsEnabled(enabled) {
    ['renameCanvasBtn', 'deleteCanvasBtn', 'canvasExportPngBtn', 'canvasExportSvgBtn', 'canvasExportPdfBtn', 'canvasGenDiagramBtn'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = !enabled;
    });
}

async function renameCurrentCanvas() {
    if (!_currentCanvasId) return;
    const title = await _showPrompt('Rename canvas', 'New name...', 'Rename');
    if (!title) return;
    await safeFetch(`/api/canvases/${_currentCanvasId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
    });
    loadCanvasList();
    showToast('Canvas renamed');
}

async function deleteCurrentCanvas() {
    if (!_currentCanvasId) return;
    const confirmed = await _confirmCanvas({
        title: 'Delete Canvas?',
        message: 'This canvas and all its contents will be permanently deleted.',
        confirmText: 'Delete Canvas',
        type: 'danger'
    });
    if (!confirmed) return;
    await safeFetch(`/api/canvases/${_currentCanvasId}`, { method: 'DELETE' });
    _currentCanvasId = null;
    _unmountExcalidraw();
    document.getElementById('canvasWrapper').classList.add('hidden');
    document.getElementById('canvasEmptyState').classList.remove('hidden');
    setCanvasButtonsEnabled(false);
    loadCanvasList();
    showToast('Canvas deleted');
}

// --- Excalidraw Initialization ---

async function initExcalidrawCanvas(elements, appState) {
    const container = document.getElementById('excalidrawRoot');
    if (!container) return;

    // Show loading
    container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:13px">Loading canvas...</div>';

    try {
        const { React, Lib } = await _loadExcalidraw();
        const { Excalidraw } = Lib;

        // Unmount previous
        _unmountExcalidraw();

        const dark = document.documentElement.getAttribute('data-theme') === 'dark';

        const initialData = {
            elements: elements || [],
            appState: {
                viewBackgroundColor: dark ? '#1a1a1a' : '#ffffff',
                theme: dark ? 'dark' : 'light',
                currentItemFontFamily: 2,          // Helvetica, not Virgil
                currentItemStrokeColor: dark ? '#e0e0e0' : '#1a1a1a',
                currentItemRoughness: 0,            // Clean lines, not sketchy
                currentItemFontSize: 16,
                ...(appState || {}),
            },
        };

        function App() {
            return React.default.createElement(
                "div",
                { style: { width: "100%", height: "100%" } },
                React.default.createElement(Excalidraw, {
                    initialData: initialData,
                    excalidrawAPI: (api) => { _excalidrawAPI = api; window._excalidrawAPI = api; },
                    UIOptions: {
                        canvasActions: {
                            saveToActiveFile: false,
                            loadScene: false,
                            export: false,
                            toggleTheme: true,
                        },
                    },
                    onChange: (els, state) => {
                        scheduleCanvasSave();
                    },
                })
            );
        }

        _excalidrawRoot = _excalidrawCreateRoot(container);
        _excalidrawRoot.render(React.default.createElement(App));

        // Setup drop zone for companies
        const wrapper = document.getElementById('canvasWrapper');
        wrapper.removeEventListener('dragover', _canvasDragOverHandler);
        wrapper.removeEventListener('drop', onCanvasDrop);
        wrapper.addEventListener('dragover', _canvasDragOverHandler);
        wrapper.addEventListener('drop', onCanvasDrop);

    } catch (err) {
        container.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--accent-danger);font-size:13px;padding:20px;text-align:center">
            Failed to load Excalidraw.<br>Check console for details.
        </div>`;
    }
}

function _unmountExcalidraw() {
    if (_excalidrawRoot) {
        _excalidrawRoot.unmount();
        _excalidrawRoot = null;
    }
    _excalidrawAPI = null;
    window._excalidrawAPI = null;
    const container = document.getElementById('excalidrawRoot');
    if (container) container.innerHTML = '';
}

// --- Drag & Drop from sidebar ---

function _canvasDragOverHandler(e) { e.preventDefault(); }

function onCanvasDragStart(event, companyId, name, categoryName, color) {
    event.dataTransfer.setData('application/json', JSON.stringify({
        companyId, name, categoryName, color,
    }));
}

function onCanvasDrop(event) {
    event.preventDefault();
    if (!_excalidrawAPI) return;

    let dragData;
    try {
        dragData = JSON.parse(event.dataTransfer.getData('application/json'));
    } catch { return; }

    // Get drop position relative to canvas
    const wrapperRect = document.getElementById('canvasWrapper').getBoundingClientRect();
    const x = event.clientX - wrapperRect.left;
    const y = event.clientY - wrapperRect.top;

    // Check if company already on canvas
    const existing = _excalidrawAPI.getSceneElements().find(
        el => el.customData && el.customData.companyId === dragData.companyId
    );
    if (existing) {
        showToast(`${dragData.name} is already on the canvas`);
        return;
    }

    // Create Excalidraw elements for the company card
    const elements = _createCompanyElements(x, y, dragData);
    const current = _excalidrawAPI.getSceneElements();
    _excalidrawAPI.updateScene({ elements: [...current, ...elements] });
}

function _hexToRgba(hex, alpha) {
    // Convert 3- or 6-digit hex to rgba string
    let h = hex.replace('#', '');
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    const r = parseInt(h.substring(0, 2), 16);
    const g = parseInt(h.substring(2, 4), 16);
    const b = parseInt(h.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function _createCompanyElements(x, y, data) {
    const rectId = _randomId();
    const textId = _randomId();
    const color = data.color || '#888888';
    const name = data.name || 'Company';
    const category = data.categoryName || '';
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    const displayText = category ? `${name}\n${category}` : name;
    const lines = displayText.split('\n');
    const longestLine = lines.reduce((a, b) => a.length > b.length ? a : b, '');
    const width = Math.max(180, longestLine.length * 8.5 + 40);
    const lineHeight = 1.25;
    const fontSize = 14;
    const textH = lines.length * fontSize * lineHeight;
    const height = Math.max(52, textH + 28);

    return [
        _makeElement('rectangle', {
            id: rectId,
            x: x - width / 2, y: y - height / 2,
            width, height,
            strokeColor: color,
            backgroundColor: _hexToRgba(color, 0.08),
            fillStyle: 'solid',
            strokeWidth: 1.5,
            roughness: 0,
            roundness: null,
            boundElements: [{ type: 'text', id: textId }],
            customData: { companyId: data.companyId, companyName: name, type: 'company' },
        }),
        _makeElement('text', {
            id: textId,
            x: x - width / 2, y: y - height / 2,
            width: width,
            height: height,
            text: displayText,
            fontSize: fontSize,
            fontFamily: 2,
            lineHeight: lineHeight,
            strokeColor: isDark ? '#e0e0e0' : '#1a1a1a',
            textAlign: 'center',
            verticalAlign: 'middle',
            containerId: rectId,
            autoResize: true,
        }),
    ];
}

// --- Auto-save ---

function scheduleCanvasSave() {
    clearTimeout(_canvasSaveTimeout);
    _canvasSaveTimeout = setTimeout(saveCanvas, 2000);
}

async function saveCanvas() {
    if (!_excalidrawAPI || !_currentCanvasId) return;
    const elements = _excalidrawAPI.getSceneElements();
    const appState = _excalidrawAPI.getAppState();
    const data = {
        elements: elements,
        appState: {
            viewBackgroundColor: appState.viewBackgroundColor,
            theme: appState.theme,
        },
    };
    await safeFetch(`/api/canvases/${_currentCanvasId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data }),
    });
}

// --- Export ---

async function exportCanvasPng() {
    if (!_excalidrawAPI || !_excalidrawLib) return;
    try {
        const elements = _excalidrawAPI.getSceneElements().filter(e => !e.isDeleted);
        if (!elements.length) { showToast('Nothing to export'); return; }
        const blob = await _excalidrawLib.exportToBlob({
            elements,
            appState: _excalidrawAPI.getAppState(),
            files: _excalidrawAPI.getFiles(),
            mimeType: 'image/png',
            exportPadding: 20,
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = 'canvas.png';
        link.click();
        URL.revokeObjectURL(url);
    } catch (err) {
        console.error('PNG export failed:', err);
        showToast('Export failed');
    }
}

async function exportCanvasSvg() {
    if (!_excalidrawAPI || !_excalidrawLib) return;
    try {
        const elements = _excalidrawAPI.getSceneElements().filter(e => !e.isDeleted);
        if (!elements.length) { showToast('Nothing to export'); return; }
        const svg = await _excalidrawLib.exportToSvg({
            elements,
            appState: _excalidrawAPI.getAppState(),
            files: _excalidrawAPI.getFiles(),
            exportPadding: 20,
        });
        const svgString = new XMLSerializer().serializeToString(svg);
        const blob = new Blob([svgString], { type: 'image/svg+xml' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'canvas.svg';
        link.click();
    } catch (err) {
        console.error('SVG export failed:', err);
        showToast('Export failed');
    }
}

function exportCanvasPdf() {
    if (!_excalidrawAPI || !_excalidrawLib) return;
    // Export SVG then print
    exportCanvasSvg(); // For now, SVG export — PDF via print dialog
    showToast('Use SVG export, then print to PDF from your browser');
}

// --- Excalidraw Element Helpers ---

function _randomId() {
    return Math.random().toString(36).substring(2, 10) + Math.random().toString(36).substring(2, 6);
}

function _randomSeed() {
    return Math.floor(Math.random() * 2147483647);
}

function _measureText(text, fontSize) {
    // Approximate text dimensions using character metrics
    const lines = (text || '').split('\n');
    const charW = fontSize * 0.6;
    const longest = lines.reduce((a, b) => a.length > b.length ? a : b, '');
    const w = Math.ceil(longest.length * charW) + 4;
    const h = Math.ceil(lines.length * fontSize * 1.25) + 4;
    return { w, h };
}

function _makeElement(type, overrides) {
    const base = {
        id: _randomId(),
        type: type,
        x: 0,
        y: 0,
        width: 100,
        height: 40,
        angle: 0,
        strokeColor: '#1a1a1a',
        backgroundColor: 'transparent',
        fillStyle: 'solid',
        strokeWidth: 1,
        strokeStyle: 'solid',
        roughness: 0,
        opacity: 100,
        seed: _randomSeed(),
        version: 1,
        versionNonce: _randomSeed(),
        isDeleted: false,
        boundElements: null,
        updated: Date.now(),
        link: null,
        locked: false,
        groupIds: [],
        frameId: null,
        roundness: null,
    };

    if (type === 'text') {
        const text = overrides.text || '';
        const fontSize = overrides.fontSize || 16;
        const measured = _measureText(text, fontSize);
        // If text is bound to a container, width/height come from container
        const isBound = overrides.containerId != null;
        Object.assign(base, {
            text: text,
            fontSize: fontSize,
            fontFamily: 2,
            textAlign: 'left',
            verticalAlign: 'top',
            containerId: null,
            originalText: text,
            autoResize: true,
            lineHeight: 1.25,
            width: isBound ? (overrides.width || measured.w) : measured.w,
            height: isBound ? (overrides.height || measured.h) : measured.h,
            strokeWidth: 1,
            backgroundColor: 'transparent',
        });
    } else if (type === 'arrow') {
        Object.assign(base, {
            points: [[0, 0], [100, 0]],
            startBinding: null,
            endBinding: null,
            startArrowhead: null,
            endArrowhead: 'arrow',
            roundness: { type: 2 },
        });
    }

    // Apply overrides
    Object.assign(base, overrides);

    // Ensure originalText matches text
    if (type === 'text' && base.text) {
        base.originalText = base.text;
    }

    return base;
}

// --- Load Canvas from Report Export ---

/**
 * Load an Excalidraw scene from a report canvas export.
 * If Excalidraw is already mounted, updates the scene.
 * Otherwise, initializes Excalidraw with the provided elements.
 *
 * @param {Object} data - Excalidraw-compatible JSON with elements and appState
 */
async function loadCanvasFromReport(data) {
    if (!data || !data.elements) {
        if (typeof showToast === 'function') showToast('No canvas data to load');
        return;
    }

    const elements = data.elements || [];
    const appState = data.appState || {};

    // Show the canvas workspace UI
    const wrapper = document.getElementById('canvasWrapper');
    const empty = document.getElementById('canvasEmptyState');
    if (wrapper) wrapper.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');

    if (_excalidrawAPI) {
        // Excalidraw already mounted — update scene directly
        _excalidrawAPI.updateScene({
            elements: elements,
            appState: appState,
        });
        _excalidrawAPI.scrollToContent();
    } else {
        // Excalidraw not yet mounted — initialize with these elements
        await initExcalidrawCanvas(elements, appState);
    }
}

window.loadCanvasFromReport = loadCanvasFromReport;

// Expose key functions globally for cross-module access
window._excalidrawAPI = null;
window._currentCanvasId = null;
Object.defineProperty(window, '_currentCanvasId', {
    get: () => _currentCanvasId,
    set: (v) => { _currentCanvasId = v; },
});
