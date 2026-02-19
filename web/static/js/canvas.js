/**
 * Canvas: full-featured visual workspace powered by Fabric.js.
 * Supports freehand drawing, shapes, text, sticky notes, lines/arrows,
 * company drag-drop, undo/redo, grid, export (PNG/SVG/PDF).
 */

let _fabricCanvas = null;
let _currentCanvasId = null;
let _canvasSaveTimeout = null;
let _canvasCompanies = [];
let _canvasTool = 'select';
let _canvasUndoStack = [];
let _canvasRedoStack = [];
const _MAX_UNDO = 50;
let _isUndoRedo = false;       // flag to prevent saving undo state during undo/redo
let _lineDrawStart = null;     // temp: line tool start point
let _shapeDrawStart = null;    // temp: shape tool drag start
let _shapeDrawObj = null;      // temp: shape being drawn
let _canvasGridLines = [];
let _canvasGridVisible = false;
let _isPanning = false;
let _panStart = null;

// --- Canvas list ---
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
    _canvasCompanies = await res.json();
    renderCanvasSidebar(_canvasCompanies);
}

function renderCanvasSidebar(companies) {
    const container = document.getElementById('canvasCompanyList');
    if (!container) return;
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

// --- Canvas CRUD ---
async function createNewCanvas() {
    const title = prompt('Canvas name:');
    if (!title || !title.trim()) return;
    const res = await safeFetch('/api/canvases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProjectId, title: title.trim() }),
    });
    const data = await res.json();
    if (data.id) {
        await loadCanvasList();
        document.getElementById('canvasSelect').value = data.id;
        loadCanvasFromSelect();
    }
}

function loadCanvasFromSelect() {
    const id = document.getElementById('canvasSelect').value;
    if (id) {
        loadCanvas(parseInt(id));
    } else {
        _currentCanvasId = null;
        if (_fabricCanvas) { _fabricCanvas.dispose(); _fabricCanvas = null; }
        document.getElementById('canvasWrapper').classList.add('hidden');
        document.getElementById('canvasEmptyState').classList.remove('hidden');
        document.getElementById('canvasDrawToolbar').classList.add('hidden');
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
    document.getElementById('canvasDrawToolbar').classList.remove('hidden');
    setCanvasButtonsEnabled(true);

    // Defer init until after browser reflow (wrapper just became visible)
    requestAnimationFrame(() => initFabricCanvas(canvasData.data || {}));
}

function setCanvasButtonsEnabled(enabled) {
    ['renameCanvasBtn', 'deleteCanvasBtn', 'canvasExportPngBtn', 'canvasExportSvgBtn', 'canvasExportPdfBtn', 'canvasGenDiagramBtn'].forEach(id => {
        const btn = document.getElementById(id);
        if (btn) btn.disabled = !enabled;
    });
}

async function renameCurrentCanvas() {
    if (!_currentCanvasId) return;
    const title = prompt('New canvas name:');
    if (!title || !title.trim()) return;
    await safeFetch(`/api/canvases/${_currentCanvasId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim() }),
    });
    loadCanvasList();
    showToast('Canvas renamed');
}

async function deleteCurrentCanvas() {
    if (!_currentCanvasId) return;
    if (!confirm('Delete this canvas?')) return;
    await safeFetch(`/api/canvases/${_currentCanvasId}`, { method: 'DELETE' });
    _currentCanvasId = null;
    if (_fabricCanvas) { _fabricCanvas.dispose(); _fabricCanvas = null; }
    document.getElementById('canvasWrapper').classList.add('hidden');
    document.getElementById('canvasEmptyState').classList.remove('hidden');
    document.getElementById('canvasDrawToolbar').classList.add('hidden');
    setCanvasButtonsEnabled(false);
    loadCanvasList();
    showToast('Canvas deleted');
}

// === Fabric.js Initialization ===

function initFabricCanvas(data) {
    const wrapper = document.getElementById('canvasWrapper');
    const canvasEl = document.getElementById('fabricCanvas');

    // Dispose previous instance
    if (_fabricCanvas) { _fabricCanvas.dispose(); _fabricCanvas = null; }

    // Size canvas to fill wrapper
    const rect = wrapper.getBoundingClientRect();

    // Guard: if wrapper has no dimensions yet (pre-reflow), retry next frame
    if (rect.width < 1 || rect.height < 1) {
        requestAnimationFrame(() => initFabricCanvas(data));
        return;
    }

    canvasEl.width = rect.width;
    canvasEl.height = rect.height;

    _fabricCanvas = new fabric.Canvas('fabricCanvas', {
        width: rect.width,
        height: rect.height,
        backgroundColor: _isDark() ? '#1a1a18' : '#faf8f5',
        selection: true,
        preserveObjectStacking: true,
    });

    // Reset state
    _canvasUndoStack = [];
    _canvasRedoStack = [];
    _canvasGridLines = [];
    _canvasGridVisible = false;
    _lineDrawStart = null;
    _shapeDrawStart = null;
    _shapeDrawObj = null;

    // Load data — detect old Cytoscape format vs new Fabric format
    if (data.elements && !data.objects) {
        _convertCytoscapeData(data.elements);
    } else if (data.objects) {
        _fabricCanvas.loadFromJSON(data, () => {
            _fabricCanvas.renderAll();
            _pushUndoState();
        });
        return;
    }

    // Setup event handlers
    _setupFabricEvents();
    _fabricCanvas.renderAll();

    // Drop zone for companies
    wrapper.addEventListener('dragover', (e) => e.preventDefault());
    wrapper.addEventListener('drop', onCanvasDrop);

    // Initial undo state
    _pushUndoState();

    // Set default tool
    setCanvasTool('select');
}

function _isDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark';
}

// --- Convert old Cytoscape canvas data to Fabric objects ---
function _convertCytoscapeData(elements) {
    if (!_fabricCanvas || !Array.isArray(elements)) return;

    // elements can be {nodes:[...], edges:[...]} or flat array
    const nodes = Array.isArray(elements) ? elements.filter(e => e.group === 'nodes' || (!e.group && e.data && !e.data.source)) :
        (elements.nodes || []);
    const edges = Array.isArray(elements) ? elements.filter(e => e.group === 'edges' || (e.data && e.data.source)) :
        (elements.edges || []);

    // Build node position map
    const posMap = {};
    nodes.forEach(n => {
        const d = n.data || {};
        const pos = n.position || { x: 200 + Math.random() * 400, y: 200 + Math.random() * 400 };
        posMap[d.id] = pos;

        if (d.type === 'company') {
            _addCompanyNode(pos.x, pos.y, d.companyId || d.id, d.label || '', d.color || '#5a7c5a');
        } else if (d.type === 'note') {
            _addStickyNote(pos.x, pos.y, d.label || 'Note');
        }
    });

    // Convert edges to lines
    edges.forEach(e => {
        const d = e.data || {};
        const srcPos = posMap[d.source];
        const tgtPos = posMap[d.target];
        if (srcPos && tgtPos) {
            _addArrowLine(srcPos.x, srcPos.y, tgtPos.x, tgtPos.y);
        }
    });

    _fabricCanvas.renderAll();
    _setupFabricEvents();
}

// === Event Handlers ===

function _setupFabricEvents() {
    if (!_fabricCanvas) return;

    // Track modifications for undo and auto-save
    _fabricCanvas.on('object:modified', () => { if (!_isUndoRedo) { _pushUndoState(); scheduleCanvasSave(); } });
    _fabricCanvas.on('object:added', () => { if (!_isUndoRedo) { _pushUndoState(); scheduleCanvasSave(); } });
    _fabricCanvas.on('object:removed', () => { if (!_isUndoRedo) { _pushUndoState(); scheduleCanvasSave(); } });

    // Mouse events for drawing tools
    _fabricCanvas.on('mouse:down', _onMouseDown);
    _fabricCanvas.on('mouse:move', _onMouseMove);
    _fabricCanvas.on('mouse:up', _onMouseUp);
    _fabricCanvas.on('mouse:dblclick', _onDoubleClick);

    // Right-click context menu
    _fabricCanvas.on('mouse:down', (opt) => {
        if (opt.e.button === 2) {
            opt.e.preventDefault();
            opt.e.stopPropagation();
            const target = _fabricCanvas.findTarget(opt.e);
            if (target) {
                showCanvasContextMenu(opt.e.clientX, opt.e.clientY, target);
            }
        }
    });

    // Prevent browser context menu on canvas
    _fabricCanvas.upperCanvasEl.addEventListener('contextmenu', (e) => e.preventDefault());

    // Mouse wheel zoom
    _fabricCanvas.on('mouse:wheel', (opt) => {
        const delta = opt.e.deltaY;
        let zoom = _fabricCanvas.getZoom();
        zoom *= 0.999 ** delta;
        zoom = Math.min(Math.max(zoom, 0.1), 10);
        _fabricCanvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
        opt.e.preventDefault();
        opt.e.stopPropagation();
    });

    // Keyboard shortcuts
    document.removeEventListener('keydown', _canvasKeyHandler);
    document.addEventListener('keydown', _canvasKeyHandler);
}

function _onMouseDown(opt) {
    if (opt.e.button === 2) return; // ignore right-click
    const pointer = _fabricCanvas.getViewportPoint(opt.e);
    const scenePoint = _fabricCanvas.restorePointerVpt(pointer);

    if (_canvasTool === 'pan') {
        _isPanning = true;
        _panStart = { x: opt.e.clientX, y: opt.e.clientY };
        _fabricCanvas.selection = false;
        _fabricCanvas.setCursor('grabbing');
        return;
    }

    if (_canvasTool === 'line') {
        _lineDrawStart = scenePoint;
        return;
    }

    if (['rect', 'circle', 'diamond'].includes(_canvasTool) && !opt.target) {
        _shapeDrawStart = scenePoint;
        const color = document.getElementById('canvasFillColor').value;
        const strokeColor = document.getElementById('canvasStrokeColor').value;
        const strokeWidth = +(document.getElementById('canvasStrokeWidth').value);

        if (_canvasTool === 'rect') {
            _shapeDrawObj = new fabric.Rect({
                left: scenePoint.x, top: scenePoint.y, width: 1, height: 1,
                fill: color + '30', stroke: strokeColor, strokeWidth,
                rx: 6, ry: 6,
            });
        } else if (_canvasTool === 'circle') {
            _shapeDrawObj = new fabric.Ellipse({
                left: scenePoint.x, top: scenePoint.y, rx: 1, ry: 1,
                fill: color + '30', stroke: strokeColor, strokeWidth,
            });
        } else if (_canvasTool === 'diamond') {
            _shapeDrawObj = new fabric.Rect({
                left: scenePoint.x, top: scenePoint.y, width: 1, height: 1,
                fill: color + '30', stroke: strokeColor, strokeWidth,
                angle: 45, originX: 'center', originY: 'center',
            });
        }
        if (_shapeDrawObj) {
            _shapeDrawObj.set({ selectable: false, evented: false });
            _fabricCanvas.add(_shapeDrawObj);
        }
        return;
    }

    // Click on empty canvas in shape/text tools = place at click
    if (!opt.target) {
        if (_canvasTool === 'text') {
            _addText(scenePoint.x, scenePoint.y);
            setCanvasTool('select');
            return;
        }
        if (_canvasTool === 'note') {
            const text = prompt('Sticky note text:');
            if (text && text.trim()) {
                _addStickyNote(scenePoint.x, scenePoint.y, text.trim());
                setCanvasTool('select');
            }
            return;
        }
    }
}

function _onMouseMove(opt) {
    if (_isPanning && _panStart) {
        const vpt = _fabricCanvas.viewportTransform;
        vpt[4] += opt.e.clientX - _panStart.x;
        vpt[5] += opt.e.clientY - _panStart.y;
        _panStart = { x: opt.e.clientX, y: opt.e.clientY };
        _fabricCanvas.requestRenderAll();
        return;
    }

    if (_shapeDrawStart && _shapeDrawObj) {
        const pointer = _fabricCanvas.getViewportPoint(opt.e);
        const p = _fabricCanvas.restorePointerVpt(pointer);

        if (_canvasTool === 'rect' || _canvasTool === 'diamond') {
            const w = Math.abs(p.x - _shapeDrawStart.x);
            const h = Math.abs(p.y - _shapeDrawStart.y);
            if (_canvasTool === 'diamond') {
                _shapeDrawObj.set({ width: w, height: h });
            } else {
                _shapeDrawObj.set({
                    left: Math.min(p.x, _shapeDrawStart.x),
                    top: Math.min(p.y, _shapeDrawStart.y),
                    width: w, height: h,
                });
            }
        } else if (_canvasTool === 'circle') {
            _shapeDrawObj.set({
                left: Math.min(p.x, _shapeDrawStart.x),
                top: Math.min(p.y, _shapeDrawStart.y),
                rx: Math.abs(p.x - _shapeDrawStart.x) / 2,
                ry: Math.abs(p.y - _shapeDrawStart.y) / 2,
            });
        }
        _fabricCanvas.renderAll();
    }
}

function _onMouseUp(opt) {
    if (_isPanning) {
        _isPanning = false;
        _panStart = null;
        _fabricCanvas.setCursor('grab');
        return;
    }

    const pointer = _fabricCanvas.getViewportPoint(opt.e);
    const scenePoint = _fabricCanvas.restorePointerVpt(pointer);

    // Line tool — draw on second click
    if (_canvasTool === 'line' && _lineDrawStart) {
        const dist = Math.hypot(scenePoint.x - _lineDrawStart.x, scenePoint.y - _lineDrawStart.y);
        if (dist > 5) {
            _addArrowLine(_lineDrawStart.x, _lineDrawStart.y, scenePoint.x, scenePoint.y);
        }
        _lineDrawStart = null;
        return;
    }

    // Finish shape drag-draw
    if (_shapeDrawStart && _shapeDrawObj) {
        _shapeDrawObj.set({ selectable: true, evented: true });
        // If shape too small, set min size
        if ((_shapeDrawObj.width || 0) < 10 && (_shapeDrawObj.height || 0) < 10) {
            if (_canvasTool === 'rect' || _canvasTool === 'diamond') {
                _shapeDrawObj.set({ width: 120, height: 80 });
            } else if (_canvasTool === 'circle') {
                _shapeDrawObj.set({ rx: 50, ry: 40 });
            }
        }
        _fabricCanvas.setActiveObject(_shapeDrawObj);
        _fabricCanvas.renderAll();
        _shapeDrawStart = null;
        _shapeDrawObj = null;
        setCanvasTool('select');
        return;
    }
}

function _onDoubleClick(opt) {
    const target = opt.target;
    if (target && target._customType === 'stickyNote') {
        // Edit sticky note text
        const textObj = target.getObjects().find(o => o.type === 'textbox' || o.type === 'i-text' || o.type === 'text');
        if (textObj) {
            const newText = prompt('Edit note:', textObj.text);
            if (newText !== null) {
                textObj.set({ text: newText });
                _fabricCanvas.renderAll();
                scheduleCanvasSave();
            }
        }
    } else if (target && (target.type === 'i-text' || target.type === 'textbox')) {
        // Enter editing mode
        target.enterEditing();
    }
}

// === Tool Mode ===

function setCanvasTool(tool) {
    _canvasTool = tool;
    document.querySelectorAll('#canvasDrawToolbar .draw-tool').forEach(b => b.classList.remove('active'));
    const btnMap = {
        select: 'toolSelect', pan: 'toolPan', pen: 'toolPen', line: 'toolLine',
        rect: 'toolRect', circle: 'toolCircle', diamond: 'toolDiamond',
        text: 'toolText', note: 'toolNote',
    };
    const btn = document.getElementById(btnMap[tool]);
    if (btn) btn.classList.add('active');

    if (!_fabricCanvas) return;

    // Reset drawing mode
    _fabricCanvas.isDrawingMode = false;
    _fabricCanvas.selection = true;
    _fabricCanvas.defaultCursor = 'default';
    _fabricCanvas.hoverCursor = 'move';
    _lineDrawStart = null;
    _shapeDrawStart = null;
    _shapeDrawObj = null;

    // Enable/disable object selectability based on tool
    _fabricCanvas.forEachObject(obj => {
        obj.selectable = (tool === 'select');
        obj.evented = (tool === 'select');
    });

    if (tool === 'pen') {
        _fabricCanvas.isDrawingMode = true;
        _fabricCanvas.freeDrawingBrush = new fabric.PencilBrush(_fabricCanvas);
        _fabricCanvas.freeDrawingBrush.color = document.getElementById('canvasStrokeColor').value;
        _fabricCanvas.freeDrawingBrush.width = +(document.getElementById('canvasStrokeWidth').value);
    } else if (tool === 'pan') {
        _fabricCanvas.selection = false;
        _fabricCanvas.defaultCursor = 'grab';
        _fabricCanvas.hoverCursor = 'grab';
    } else if (['line', 'rect', 'circle', 'diamond', 'text', 'note'].includes(tool)) {
        _fabricCanvas.selection = false;
        _fabricCanvas.defaultCursor = 'crosshair';
        _fabricCanvas.hoverCursor = 'crosshair';
    }
}

// === Shape Creation Helpers ===

function _addCompanyNode(x, y, companyId, name, color) {
    const circle = new fabric.Circle({
        radius: 25, fill: color + '30', stroke: color, strokeWidth: 2,
        originX: 'center', originY: 'center',
    });
    const label = new fabric.Text(name.length > 12 ? name.substring(0, 11) + '...' : name, {
        fontSize: 11, fill: _isDark() ? '#e0ddd5' : '#3D4035',
        originX: 'center', originY: 'top', top: 28,
        fontFamily: 'Noto Sans, sans-serif',
    });
    const group = new fabric.Group([circle, label], {
        left: x - 25, top: y - 25,
    });
    group._customType = 'company';
    group._companyId = companyId;
    group._companyName = name;
    _fabricCanvas.add(group);
    return group;
}

function _addStickyNote(x, y, text) {
    const bg = new fabric.Rect({
        width: 160, height: 80,
        fill: _isDark() ? '#4a4636' : '#FFF8E1',
        stroke: _isDark() ? '#6b6550' : '#FFE082',
        strokeWidth: 1, rx: 8, ry: 8,
        originX: 'center', originY: 'center',
    });
    const textObj = new fabric.Textbox(text, {
        width: 140, fontSize: 12,
        fill: _isDark() ? '#e0ddd5' : '#3D4035',
        fontFamily: 'Noto Sans, sans-serif',
        textAlign: 'center',
        originX: 'center', originY: 'center',
    });
    const group = new fabric.Group([bg, textObj], {
        left: x - 80, top: y - 40,
    });
    group._customType = 'stickyNote';
    _fabricCanvas.add(group);
    return group;
}

function _addText(x, y) {
    const fontSize = +(document.getElementById('canvasFontSize').value) || 14;
    const color = document.getElementById('canvasStrokeColor').value;
    const text = new fabric.IText('Text', {
        left: x, top: y, fontSize,
        fill: color,
        fontFamily: 'Noto Sans, sans-serif',
    });
    _fabricCanvas.add(text);
    _fabricCanvas.setActiveObject(text);
    text.enterEditing();
    text.selectAll();
}

function _addArrowLine(x1, y1, x2, y2) {
    const strokeColor = document.getElementById('canvasStrokeColor').value;
    const strokeWidth = +(document.getElementById('canvasStrokeWidth').value);

    const line = new fabric.Line([x1, y1, x2, y2], {
        stroke: strokeColor, strokeWidth,
        selectable: true, evented: true,
    });

    // Arrowhead triangle
    const angle = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
    const headSize = strokeWidth * 4 + 6;
    const arrow = new fabric.Triangle({
        width: headSize, height: headSize,
        fill: strokeColor,
        left: x2, top: y2,
        angle: angle + 90,
        originX: 'center', originY: 'center',
    });

    const group = new fabric.Group([line, arrow], { selectable: true, evented: true });
    group._customType = 'arrow';
    _fabricCanvas.add(group);
    return group;
}

// === Drag & Drop from sidebar ===

function onCanvasDragStart(event, companyId, name, categoryName, color) {
    event.dataTransfer.setData('application/json', JSON.stringify({
        companyId, name, categoryName, color,
    }));
}

function onCanvasDrop(event) {
    event.preventDefault();
    if (!_fabricCanvas) return;

    let dragData;
    try {
        dragData = JSON.parse(event.dataTransfer.getData('application/json'));
    } catch { return; }

    // Check if company already on canvas
    const existing = _fabricCanvas.getObjects().find(o => o._companyId === dragData.companyId);
    if (existing) {
        showToast(`${dragData.name} is already on the canvas`);
        return;
    }

    // Convert screen coords to canvas coords
    const wrapperRect = document.getElementById('canvasWrapper').getBoundingClientRect();
    const vpt = _fabricCanvas.viewportTransform;
    const zoom = _fabricCanvas.getZoom();
    const x = (event.clientX - wrapperRect.left - vpt[4]) / zoom;
    const y = (event.clientY - wrapperRect.top - vpt[5]) / zoom;

    _addCompanyNode(x, y, dragData.companyId, dragData.name, dragData.color || '#999');
    _fabricCanvas.renderAll();
}

// === Context Menu ===

function showCanvasContextMenu(clientX, clientY, target) {
    hideCanvasContextMenu();
    const menu = document.getElementById('canvasCtxMenu');
    menu.innerHTML = '';

    const items = [];
    if (target._customType === 'company') {
        items.push({ label: 'Open Detail', icon: 'open_in_new', action: () => { showTab('companies'); showDetail(target._companyId); } });
        items.push({ label: 'Start Research', icon: 'science', action: () => startCompanyResearch(target._companyId, target._companyName) });
    }
    if (target._customType === 'stickyNote') {
        items.push({ label: 'Edit Note', icon: 'edit', action: () => {
            const textObj = target.getObjects().find(o => o.type === 'textbox' || o.type === 'text');
            if (textObj) {
                const newText = prompt('Edit note:', textObj.text);
                if (newText !== null) { textObj.set({ text: newText }); _fabricCanvas.renderAll(); scheduleCanvasSave(); }
            }
        }});
    }
    items.push({ label: 'Duplicate', icon: 'content_copy', action: () => {
        target.clone((cloned) => {
            cloned.set({ left: (cloned.left || 0) + 20, top: (cloned.top || 0) + 20 });
            cloned._customType = target._customType;
            cloned._companyId = target._companyId;
            cloned._companyName = target._companyName;
            _fabricCanvas.add(cloned);
            _fabricCanvas.setActiveObject(cloned);
        });
    }});
    items.push({ label: 'Bring to Front', icon: 'flip_to_front', action: () => { _fabricCanvas.bringObjectToFront(target); } });
    items.push({ label: 'Send to Back', icon: 'flip_to_back', action: () => { _fabricCanvas.sendObjectToBack(target); } });
    items.push({ label: 'Delete', icon: 'delete', action: () => { _fabricCanvas.remove(target); } });

    menu.innerHTML = items.map(item =>
        `<div class="canvas-ctx-item" onclick="event.stopPropagation()">
            <span class="material-symbols-outlined" style="font-size:16px">${item.icon}</span>
            ${esc(item.label)}
        </div>`
    ).join('');

    const menuItems = menu.querySelectorAll('.canvas-ctx-item');
    items.forEach((item, i) => {
        menuItems[i].addEventListener('click', () => { hideCanvasContextMenu(); item.action(); });
    });

    // Position menu near cursor
    const tabCanvas = document.getElementById('tab-canvas');
    const tabRect = tabCanvas.getBoundingClientRect();
    menu.style.left = (clientX - tabRect.left) + 'px';
    menu.style.top = (clientY - tabRect.top) + 'px';
    menu.classList.remove('hidden');

    setTimeout(() => {
        document.addEventListener('click', hideCanvasContextMenu, { once: true });
    }, 0);
}

function hideCanvasContextMenu() {
    const menu = document.getElementById('canvasCtxMenu');
    if (menu) menu.classList.add('hidden');
}

// === Undo / Redo ===

function _pushUndoState() {
    if (!_fabricCanvas || _isUndoRedo) return;
    const json = JSON.stringify(_fabricCanvas.toJSON(['_customType', '_companyId', '_companyName', '_categoryId']));
    _canvasUndoStack.push(json);
    if (_canvasUndoStack.length > _MAX_UNDO) _canvasUndoStack.shift();
    _canvasRedoStack = [];
}

function canvasUndo() {
    if (!_fabricCanvas || _canvasUndoStack.length <= 1) return;
    _isUndoRedo = true;
    _canvasRedoStack.push(_canvasUndoStack.pop());
    const json = _canvasUndoStack[_canvasUndoStack.length - 1];
    _fabricCanvas.loadFromJSON(json, () => {
        _fabricCanvas.renderAll();
        _isUndoRedo = false;
        scheduleCanvasSave();
    });
}

function canvasRedo() {
    if (!_fabricCanvas || !_canvasRedoStack.length) return;
    _isUndoRedo = true;
    const json = _canvasRedoStack.pop();
    _canvasUndoStack.push(json);
    _fabricCanvas.loadFromJSON(json, () => {
        _fabricCanvas.renderAll();
        _isUndoRedo = false;
        scheduleCanvasSave();
    });
}

// === Delete, Color, Font ===

function deleteSelectedCanvasElements() {
    if (!_fabricCanvas) return;
    const active = _fabricCanvas.getActiveObjects();
    if (!active.length) return;
    active.forEach(obj => _fabricCanvas.remove(obj));
    _fabricCanvas.discardActiveObject();
    _fabricCanvas.renderAll();
}

function applyFillToSelected(color) {
    if (!_fabricCanvas) return;
    const active = _fabricCanvas.getActiveObjects();
    active.forEach(obj => {
        if (obj.type === 'group') {
            obj.getObjects().forEach(child => {
                if (child.type !== 'text' && child.type !== 'i-text' && child.type !== 'textbox') {
                    child.set({ fill: color + '30' });
                }
            });
        } else if (obj.type !== 'i-text' && obj.type !== 'textbox' && obj.type !== 'text') {
            obj.set({ fill: color + '30' });
        }
    });
    _fabricCanvas.renderAll();
    if (active.length) scheduleCanvasSave();
}

function applyStrokeToSelected(color) {
    if (!_fabricCanvas) return;
    const active = _fabricCanvas.getActiveObjects();
    active.forEach(obj => {
        if (obj.type === 'group') {
            obj.getObjects().forEach(child => child.set({ stroke: color }));
        } else {
            obj.set({ stroke: color });
        }
    });
    _fabricCanvas.renderAll();
    if (active.length) scheduleCanvasSave();
}

function applyStrokeWidthToSelected(width) {
    if (!_fabricCanvas) return;
    const active = _fabricCanvas.getActiveObjects();
    active.forEach(obj => obj.set({ strokeWidth: width }));
    _fabricCanvas.renderAll();
    if (active.length) scheduleCanvasSave();
}

function applyFontSizeToSelected(size) {
    if (!_fabricCanvas) return;
    const active = _fabricCanvas.getActiveObjects();
    active.forEach(obj => {
        if (obj.type === 'i-text' || obj.type === 'textbox' || obj.type === 'text') {
            obj.set({ fontSize: size });
        }
    });
    _fabricCanvas.renderAll();
    if (active.length) scheduleCanvasSave();
}

// === Zoom & Grid ===

function canvasZoom(factor) {
    if (!_fabricCanvas) return;
    let zoom = _fabricCanvas.getZoom() * factor;
    zoom = Math.min(Math.max(zoom, 0.1), 10);
    const center = _fabricCanvas.getCenterPoint();
    _fabricCanvas.zoomToPoint(center, zoom);
}

function canvasFitView() {
    if (!_fabricCanvas) return;
    _fabricCanvas.setViewportTransform([1, 0, 0, 1, 0, 0]);
    const objects = _fabricCanvas.getObjects().filter(o => !o._isGridLine);
    if (objects.length) {
        // Calculate bounding box
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        objects.forEach(o => {
            const bound = o.getBoundingRect();
            minX = Math.min(minX, bound.left);
            minY = Math.min(minY, bound.top);
            maxX = Math.max(maxX, bound.left + bound.width);
            maxY = Math.max(maxY, bound.top + bound.height);
        });
        const padding = 60;
        const bw = maxX - minX + padding * 2;
        const bh = maxY - minY + padding * 2;
        const zoom = Math.min(_fabricCanvas.width / bw, _fabricCanvas.height / bh, 2);
        _fabricCanvas.setViewportTransform([zoom, 0, 0, zoom,
            -minX * zoom + padding * zoom + (_fabricCanvas.width - bw * zoom) / 2,
            -minY * zoom + padding * zoom + (_fabricCanvas.height - bh * zoom) / 2,
        ]);
    }
}

function toggleCanvasGrid() {
    if (!_fabricCanvas) return;
    _canvasGridVisible = !_canvasGridVisible;
    const gridBtn = document.getElementById('toolGrid');
    if (gridBtn) gridBtn.classList.toggle('active', _canvasGridVisible);

    // Remove existing grid lines
    _canvasGridLines.forEach(l => _fabricCanvas.remove(l));
    _canvasGridLines = [];

    if (_canvasGridVisible) {
        const gridSize = 40;
        const gridColor = _isDark() ? '#333' : '#e0e0e0';
        for (let x = 0; x < 4000; x += gridSize) {
            const line = new fabric.Line([x, 0, x, 4000], {
                stroke: gridColor, strokeWidth: 0.5, selectable: false, evented: false,
                excludeFromExport: true,
            });
            line._isGridLine = true;
            _canvasGridLines.push(line);
            _fabricCanvas.add(line);
            _fabricCanvas.sendObjectToBack(line);
        }
        for (let y = 0; y < 4000; y += gridSize) {
            const line = new fabric.Line([0, y, 4000, y], {
                stroke: gridColor, strokeWidth: 0.5, selectable: false, evented: false,
                excludeFromExport: true,
            });
            line._isGridLine = true;
            _canvasGridLines.push(line);
            _fabricCanvas.add(line);
            _fabricCanvas.sendObjectToBack(line);
        }
    }
    _fabricCanvas.renderAll();
}

// === Keyboard Shortcuts ===

function _canvasKeyHandler(e) {
    if (!document.getElementById('tab-canvas')?.classList.contains('active')) return;
    if (!_fabricCanvas) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
    // Don't intercept when editing text in Fabric
    if (_fabricCanvas.getActiveObject()?.isEditing) return;

    const meta = e.metaKey || e.ctrlKey;

    if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteSelectedCanvasElements();
    } else if (meta && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        canvasUndo();
    } else if (meta && e.key === 'z' && e.shiftKey) {
        e.preventDefault();
        canvasRedo();
    } else if (meta && e.key === 'g' && !e.shiftKey) {
        e.preventDefault();
        groupSelected();
    } else if (meta && e.key === 'g' && e.shiftKey) {
        e.preventDefault();
        ungroupSelected();
    } else if (meta && e.key === 'a') {
        e.preventDefault();
        _fabricCanvas.discardActiveObject();
        const sel = new fabric.ActiveSelection(_fabricCanvas.getObjects().filter(o => !o._isGridLine), { canvas: _fabricCanvas });
        _fabricCanvas.setActiveObject(sel);
        _fabricCanvas.requestRenderAll();
    } else if (e.key === 'Escape') {
        _fabricCanvas.discardActiveObject();
        setCanvasTool('select');
        _fabricCanvas.renderAll();
    } else if (!meta) {
        // Tool shortcuts (single key, no modifier)
        const keyMap = { v: 'select', h: 'pan', p: 'pen', l: 'line', r: 'rect', o: 'circle', d: 'diamond', t: 'text', n: 'note', g: null };
        if (e.key in keyMap && keyMap[e.key]) setCanvasTool(keyMap[e.key]);
        if (e.key === 'g' && !meta) toggleCanvasGrid();
    }
}

// === Group / Ungroup ===

function groupSelected() {
    if (!_fabricCanvas) return;
    const activeObj = _fabricCanvas.getActiveObject();
    if (!activeObj || activeObj.type !== 'activeselection') return;
    activeObj.toGroup();
    _fabricCanvas.requestRenderAll();
}

function ungroupSelected() {
    if (!_fabricCanvas) return;
    const activeObj = _fabricCanvas.getActiveObject();
    if (!activeObj || activeObj.type !== 'group') return;
    activeObj.toActiveSelection();
    _fabricCanvas.requestRenderAll();
}

// === Auto-save ===

function scheduleCanvasSave() {
    clearTimeout(_canvasSaveTimeout);
    _canvasSaveTimeout = setTimeout(saveCanvas, 2000);
}

async function saveCanvas() {
    if (!_fabricCanvas || !_currentCanvasId) return;
    const json = _fabricCanvas.toJSON(['_customType', '_companyId', '_companyName', '_categoryId']);
    // Remove grid lines from saved data
    json.objects = (json.objects || []).filter(o => !o._isGridLine);
    await safeFetch(`/api/canvases/${_currentCanvasId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: json }),
    });
}

// === Export ===

function exportCanvasPng() {
    if (!_fabricCanvas) return;
    // Temporarily hide grid
    const wasGrid = _canvasGridVisible;
    if (wasGrid) { _canvasGridLines.forEach(l => l.set({ visible: false })); _fabricCanvas.renderAll(); }
    const dataUrl = _fabricCanvas.toDataURL({
        format: 'png', multiplier: 2,
        quality: 1,
    });
    if (wasGrid) { _canvasGridLines.forEach(l => l.set({ visible: true })); _fabricCanvas.renderAll(); }
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = 'canvas.png';
    link.click();
}

function exportCanvasSvg() {
    if (!_fabricCanvas) return;
    const wasGrid = _canvasGridVisible;
    if (wasGrid) { _canvasGridLines.forEach(l => l.set({ visible: false })); _fabricCanvas.renderAll(); }
    const svg = _fabricCanvas.toSVG();
    if (wasGrid) { _canvasGridLines.forEach(l => l.set({ visible: true })); _fabricCanvas.renderAll(); }
    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'canvas.svg';
    link.click();
}

// === Window Resize ===
window.addEventListener('resize', () => {
    if (!_fabricCanvas) return;
    const wrapper = document.getElementById('canvasWrapper');
    if (!wrapper || wrapper.classList.contains('hidden')) return;
    const rect = wrapper.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    _fabricCanvas.setDimensions({ width: rect.width, height: rect.height });
    _fabricCanvas.renderAll();
});
