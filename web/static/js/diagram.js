/**
 * AI Diagram Generator: LLM-powered enterprise architecture diagrams.
 * Uses structured output from Claude/Gemini to create editable Fabric.js layouts.
 * Integrates dagre (flow layout), elkjs (enterprise stacks), and rough.js (sketch style).
 */

let _diagramPollTimer = null;
let _diagramPollCount = 0;
const _DIAGRAM_MAX_POLL = 60;   // 3 min at 3s intervals
let _diagramStartTime = 0;
let _lastDiagramLayout = null;  // cached for auto-arrange

// ─── Panel Management ───────────────────────────────────────────

function openDiagramPanel() {
    if (!_fabricCanvas || !_currentCanvasId) {
        showToast('Create or select a canvas first');
        return;
    }
    document.getElementById('canvasSidebar').classList.add('hidden');
    document.getElementById('diagramPanel').classList.remove('hidden');
    loadDiagramCategories();
}

function closeDiagramPanel() {
    document.getElementById('diagramPanel').classList.add('hidden');
    document.getElementById('canvasSidebar').classList.remove('hidden');
    cancelDiagramGeneration();
}

async function loadDiagramCategories() {
    const container = document.getElementById('diagramCategoryList');
    if (!container) return;
    container.innerHTML = '<span class="hint-text">Loading...</span>';

    const res = await safeFetch(`/api/taxonomy?project_id=${currentProjectId}`);
    const categories = await res.json();

    // Build hierarchy: top-level then children
    const topLevel = categories.filter(c => !c.parent_id);
    const children = categories.filter(c => c.parent_id);
    const childMap = {};
    children.forEach(c => {
        if (!childMap[c.parent_id]) childMap[c.parent_id] = [];
        childMap[c.parent_id].push(c);
    });

    let html = '';
    for (const cat of topLevel) {
        const color = cat.color || '#888';
        const count = cat.company_count || 0;
        html += `<label title="${esc(cat.name)} (${count} companies)">
            <input type="checkbox" value="${cat.id}" checked>
            <span class="cat-color-dot" style="background:${color}"></span>
            ${esc(cat.name)} <span class="hint-text">(${count})</span>
        </label>`;
        // Sub-categories
        if (childMap[cat.id]) {
            for (const sub of childMap[cat.id]) {
                const subCount = sub.company_count || 0;
                const subColor = sub.color || color;
                html += `<label title="${esc(sub.name)} (${subCount} companies)" style="padding-left:22px">
                    <input type="checkbox" value="${sub.id}" checked>
                    <span class="cat-color-dot" style="background:${subColor}"></span>
                    ${esc(sub.name)} <span class="hint-text">(${subCount})</span>
                </label>`;
            }
        }
    }
    container.innerHTML = html;
}

function toggleAllDiagramCategories(state) {
    document.querySelectorAll('#diagramCategoryList input[type="checkbox"]')
        .forEach(cb => { cb.checked = state; });
}

// ─── Generation Flow ────────────────────────────────────────────

function startDiagramGeneration() {
    // Validate
    const prompt = document.getElementById('diagramPrompt').value.trim();
    if (!prompt) {
        showToast('Enter a description of the diagram you want');
        return;
    }

    const categoryIds = [];
    document.querySelectorAll('#diagramCategoryList input[type="checkbox"]:checked')
        .forEach(cb => categoryIds.push(parseInt(cb.value)));
    if (!categoryIds.length) {
        showToast('Select at least one category');
        return;
    }

    const fields = ['name'];
    document.querySelectorAll('#diagramFieldList input[type="checkbox"]:checked:not([disabled])')
        .forEach(cb => fields.push(cb.value));

    const model = document.getElementById('diagramModelSelect').value;
    const layoutStyle = document.getElementById('diagramLayoutStyle').value;

    // UI state
    document.getElementById('diagramGenBtn').disabled = true;
    document.getElementById('diagramStatus').classList.remove('hidden');
    document.getElementById('diagramError').classList.add('hidden');
    document.getElementById('diagramPostActions').classList.add('hidden');
    document.getElementById('diagramStatusText').textContent = 'Generating diagram layout...';
    _diagramStartTime = Date.now();

    // POST request
    safeFetch('/api/canvases/generate-diagram', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: currentProjectId,
            category_ids: categoryIds,
            fields,
            prompt,
            model,
            layout_style: layoutStyle,
        }),
    }).then(res => res.json()).then(data => {
        if (data.error) {
            _showDiagramError(data.error);
            return;
        }
        _diagramPollCount = 0;
        _pollDiagramResult(data.job_id);
    }).catch(err => {
        _showDiagramError('Failed to start diagram generation');
    });
}

function _pollDiagramResult(jobId) {
    _diagramPollTimer = setTimeout(async () => {
        _diagramPollCount++;
        const elapsed = Math.round((Date.now() - _diagramStartTime) / 1000);
        const elapsedStr = elapsed >= 60
            ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`
            : `${elapsed}s`;
        document.getElementById('diagramStatusText').textContent =
            `Generating diagram layout... ${elapsedStr} elapsed`;

        if (_diagramPollCount > _DIAGRAM_MAX_POLL) {
            _showDiagramError('Diagram generation timed out. Try a simpler prompt or fewer categories.');
            return;
        }

        try {
            const res = await safeFetch(`/api/canvases/generate-diagram/${jobId}`);
            const data = await res.json();

            if (data.status === 'complete') {
                _onDiagramComplete(data);
            } else if (data.status === 'error') {
                _showDiagramError(data.error || 'Diagram generation failed');
            } else {
                // Still pending
                _pollDiagramResult(jobId);
            }
        } catch (err) {
            _pollDiagramResult(jobId);
        }
    }, 3000);
}

function cancelDiagramGeneration() {
    if (_diagramPollTimer) {
        clearTimeout(_diagramPollTimer);
        _diagramPollTimer = null;
    }
    document.getElementById('diagramStatus').classList.add('hidden');
    document.getElementById('diagramGenBtn').disabled = false;
}

function _showDiagramError(message) {
    cancelDiagramGeneration();
    const el = document.getElementById('diagramError');
    el.textContent = message;
    el.classList.remove('hidden');
    document.getElementById('diagramGenBtn').disabled = false;
}

function _onDiagramComplete(data) {
    cancelDiagramGeneration();
    _lastDiagramLayout = data.layout;

    const costStr = data.cost_usd ? ` ($${data.cost_usd.toFixed(4)})` : '';
    const durationStr = data.duration_ms
        ? ` in ${(data.duration_ms / 1000).toFixed(1)}s`
        : '';
    showToast(`Diagram generated${durationStr}${costStr}`);

    // Clear canvas if checkbox checked
    if (document.getElementById('diagramClearCanvas').checked && _fabricCanvas) {
        _fabricCanvas.clear();
        _fabricCanvas.backgroundColor = _isDark() ? '#1a1a18' : '#faf8f5';
    }

    renderDiagramLayout(data.layout);

    // Show post-generation actions
    document.getElementById('diagramPostActions').classList.remove('hidden');
    document.getElementById('diagramGenBtn').disabled = false;
}

// ─── Core Renderer ──────────────────────────────────────────────

const _GRID_W = 300;
const _GRID_H = 200;
const _DIAGRAM_PAD = 20;
const _COMPANY_ROW_H = 22;
const _DIAGRAM_MARGIN = 40;

function renderDiagramLayout(layout) {
    if (!_fabricCanvas || !layout) return;

    const isDark = _isDark();
    let titleOffset = 0;

    // 1. Title
    if (layout.title) {
        const titleText = new fabric.IText(layout.title, {
            left: _DIAGRAM_MARGIN,
            top: _DIAGRAM_MARGIN,
            fontSize: 24,
            fontWeight: 'bold',
            fill: isDark ? '#e0ddd5' : '#3D4035',
            fontFamily: 'Noto Sans, sans-serif',
        });
        titleText._customType = 'diagramTitle';
        _fabricCanvas.add(titleText);
        titleOffset = 50;
    }

    // 2. Category blocks
    const blockPositions = {};  // category_id → {cx, cy}

    for (const block of (layout.category_blocks || [])) {
        const x = _DIAGRAM_MARGIN + block.col * _GRID_W;
        const y = _DIAGRAM_MARGIN + titleOffset + block.row * _GRID_H;
        const w = block.width_units * _GRID_W - _DIAGRAM_PAD;
        // Dynamic height: header + companies, clamped to height_units
        const minH = block.height_units * _GRID_H - _DIAGRAM_PAD;
        const contentH = 36 + (block.companies || []).length * _COMPANY_ROW_H + 10;
        const h = Math.max(minH, contentH);
        const color = block.color || '#5a7c5a';

        const objects = [];

        // Background rect
        objects.push(new fabric.Rect({
            width: w,
            height: h,
            fill: (isDark ? color + '20' : color + '12'),
            stroke: color,
            strokeWidth: 2,
            rx: 12,
            ry: 12,
            originX: 'left',
            originY: 'top',
            left: 0,
            top: 0,
        }));

        // Category label
        objects.push(new fabric.Text(block.label || block.category_name, {
            fontSize: 14,
            fontWeight: 'bold',
            fill: color,
            fontFamily: 'Noto Sans, sans-serif',
            left: 12,
            top: 10,
        }));

        // Company count badge
        const countText = `${(block.companies || []).length} companies`;
        objects.push(new fabric.Text(countText, {
            fontSize: 10,
            fill: color + '99',
            fontFamily: 'Noto Sans, sans-serif',
            left: w - 10,
            top: 12,
            originX: 'right',
        }));

        // Company rows
        (block.companies || []).forEach((company, i) => {
            const fieldParts = [];
            if (company.fields) {
                for (const [key, value] of Object.entries(company.fields)) {
                    if (value && value !== '' && value !== 'None') {
                        fieldParts.push(value);
                    }
                }
            }
            let displayText = company.name;
            if (fieldParts.length) {
                displayText += '  —  ' + fieldParts.join(' · ');
            }
            if (displayText.length > 70) {
                displayText = displayText.substring(0, 68) + '...';
            }

            objects.push(new fabric.Text(displayText, {
                fontSize: 11,
                fill: isDark ? '#c8c5bd' : '#555',
                fontFamily: 'Noto Sans, sans-serif',
                left: 16,
                top: 34 + i * _COMPANY_ROW_H,
            }));
        });

        const group = new fabric.Group(objects, {
            left: x,
            top: y,
        });
        group._customType = 'categoryBlock';
        group._categoryId = block.category_id;
        _fabricCanvas.add(group);

        // Track center positions for connectors
        blockPositions[block.category_id] = {
            cx: x + w / 2,
            cy: y + h / 2,
        };
    }

    // 3. Connectors
    if (layout.connectors) {
        for (const conn of layout.connectors) {
            const from = blockPositions[conn.from_category_id];
            const to = blockPositions[conn.to_category_id];
            if (from && to) {
                _addDiagramArrow(from.cx, from.cy, to.cx, to.cy,
                                 conn.label || '');
            }
        }
    }

    // 4. Annotations
    if (layout.annotations) {
        const isDark = _isDark();
        for (const ann of layout.annotations) {
            const ax = _DIAGRAM_MARGIN + (ann.col || 0) * _GRID_W;
            const ay = _DIAGRAM_MARGIN + titleOffset + (ann.row || 0) * _GRID_H;
            const fontSize = ann.style === 'heading' ? 18
                : ann.style === 'subheading' ? 14 : 12;
            const text = new fabric.IText(ann.text, {
                left: ax,
                top: ay,
                fontSize,
                fill: isDark ? '#e0ddd5' : '#3D4035',
                fontFamily: 'Noto Sans, sans-serif',
                fontWeight: ann.style === 'heading' ? 'bold' : 'normal',
                fontStyle: ann.style === 'note' ? 'italic' : 'normal',
            });
            text._customType = 'diagramAnnotation';
            _fabricCanvas.add(text);
        }
    }

    // 5. Optional layout engine pass
    const layoutStyle = document.getElementById('diagramLayoutStyle')?.value;
    if (layoutStyle === 'flow' && window.dagre) {
        _applyDagreLayout(layout);
    } else if (layoutStyle === 'enterprise_stack' && window.ELK) {
        _applyElkLayout(layout);
    }

    // 6. Optional sketch style
    const visualStyle = document.querySelector(
        'input[name="diagramVisualStyle"]:checked')?.value;
    if (visualStyle === 'sketch') {
        _applySketchStyle();
    }

    // 7. Finalize
    _fabricCanvas.renderAll();
    _pushUndoState();
    scheduleCanvasSave();
    setTimeout(() => canvasFitView(), 100);
}

function _addDiagramArrow(x1, y1, x2, y2, label) {
    const strokeColor = _isDark() ? '#888' : '#666';
    const line = new fabric.Line([x1, y1, x2, y2], {
        stroke: strokeColor,
        strokeWidth: 1.5,
        strokeDashArray: [6, 4],
    });
    const angle = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
    const arrow = new fabric.Triangle({
        width: 10,
        height: 10,
        fill: strokeColor,
        left: x2,
        top: y2,
        angle: angle + 90,
        originX: 'center',
        originY: 'center',
    });

    const items = [line, arrow];

    if (label) {
        const midX = (x1 + x2) / 2;
        const midY = (y1 + y2) / 2;
        items.push(new fabric.Text(label, {
            left: midX,
            top: midY - 10,
            fontSize: 10,
            fill: strokeColor,
            fontFamily: 'Noto Sans, sans-serif',
            fontStyle: 'italic',
            originX: 'center',
        }));
    }

    const group = new fabric.Group(items);
    group._customType = 'diagramConnector';
    _fabricCanvas.add(group);
}

// ─── Layout Engines ─────────────────────────────────────────────

function _applyDagreLayout(layout) {
    if (!window.dagre) return;

    const g = new dagre.graphlib.Graph();
    g.setGraph({
        rankdir: 'TB',
        nodesep: 40,
        ranksep: 60,
        marginx: _DIAGRAM_MARGIN,
        marginy: _DIAGRAM_MARGIN,
    });
    g.setDefaultEdgeLabel(() => ({}));

    // Map Fabric objects by category ID
    const fabricBlocks = {};
    _fabricCanvas.getObjects().forEach(obj => {
        if (obj._customType === 'categoryBlock' && obj._categoryId) {
            fabricBlocks[obj._categoryId] = obj;
        }
    });

    // Add nodes
    for (const block of (layout.category_blocks || [])) {
        const obj = fabricBlocks[block.category_id];
        if (!obj) continue;
        const bound = obj.getBoundingRect();
        g.setNode(String(block.category_id), {
            width: bound.width,
            height: bound.height,
        });
    }

    // Add edges from connectors
    for (const conn of (layout.connectors || [])) {
        g.setEdge(String(conn.from_category_id), String(conn.to_category_id));
    }

    dagre.layout(g);

    // Apply positions
    g.nodes().forEach(nodeId => {
        const node = g.node(nodeId);
        const obj = fabricBlocks[parseInt(nodeId)];
        if (obj && node) {
            const bound = obj.getBoundingRect();
            obj.set({
                left: node.x - bound.width / 2,
                top: node.y - bound.height / 2,
            });
            obj.setCoords();
        }
    });

    // Update connector arrows
    _fabricCanvas.getObjects()
        .filter(o => o._customType === 'diagramConnector')
        .forEach(o => _fabricCanvas.remove(o));

    for (const conn of (layout.connectors || [])) {
        const fromObj = fabricBlocks[conn.from_category_id];
        const toObj = fabricBlocks[conn.to_category_id];
        if (fromObj && toObj) {
            const fb = fromObj.getBoundingRect();
            const tb = toObj.getBoundingRect();
            _addDiagramArrow(
                fb.left + fb.width / 2, fb.top + fb.height,
                tb.left + tb.width / 2, tb.top,
                conn.label || '',
            );
        }
    }

    _fabricCanvas.renderAll();
}

async function _applyElkLayout(layout) {
    if (!window.ELK) return;

    const elk = new ELK();
    const graph = {
        id: 'root',
        layoutOptions: {
            'elk.algorithm': 'layered',
            'elk.direction': 'DOWN',
            'elk.spacing.nodeNode': '40',
            'elk.layered.spacing.nodeNodeBetweenLayers': '60',
        },
        children: [],
        edges: [],
    };

    const fabricBlocks = {};
    _fabricCanvas.getObjects().forEach(obj => {
        if (obj._customType === 'categoryBlock' && obj._categoryId) {
            fabricBlocks[obj._categoryId] = obj;
        }
    });

    for (const block of (layout.category_blocks || [])) {
        const obj = fabricBlocks[block.category_id];
        if (!obj) continue;
        const bound = obj.getBoundingRect();
        graph.children.push({
            id: String(block.category_id),
            width: bound.width,
            height: bound.height,
        });
    }

    for (const conn of (layout.connectors || [])) {
        graph.edges.push({
            id: `e_${conn.from_category_id}_${conn.to_category_id}`,
            sources: [String(conn.from_category_id)],
            targets: [String(conn.to_category_id)],
        });
    }

    try {
        const result = await elk.layout(graph);
        for (const child of (result.children || [])) {
            const obj = fabricBlocks[parseInt(child.id)];
            if (obj) {
                obj.set({
                    left: (child.x || 0) + _DIAGRAM_MARGIN,
                    top: (child.y || 0) + _DIAGRAM_MARGIN,
                });
                obj.setCoords();
            }
        }

        // Rebuild connectors
        _fabricCanvas.getObjects()
            .filter(o => o._customType === 'diagramConnector')
            .forEach(o => _fabricCanvas.remove(o));

        for (const conn of (layout.connectors || [])) {
            const fromObj = fabricBlocks[conn.from_category_id];
            const toObj = fabricBlocks[conn.to_category_id];
            if (fromObj && toObj) {
                const fb = fromObj.getBoundingRect();
                const tb = toObj.getBoundingRect();
                _addDiagramArrow(
                    fb.left + fb.width / 2, fb.top + fb.height,
                    tb.left + tb.width / 2, tb.top,
                    conn.label || '',
                );
            }
        }

        _fabricCanvas.renderAll();
    } catch (e) {
        console.warn('ELK layout failed:', e);
    }
}

function autoArrangeDiagram() {
    if (!_lastDiagramLayout || !_fabricCanvas) {
        showToast('No diagram to re-arrange');
        return;
    }
    const layoutStyle = document.getElementById('diagramLayoutStyle')?.value;
    if (layoutStyle === 'flow' && window.dagre) {
        _applyDagreLayout(_lastDiagramLayout);
    } else if (layoutStyle === 'enterprise_stack' && window.ELK) {
        _applyElkLayout(_lastDiagramLayout);
    } else {
        showToast('Auto-arrange is available for Flow and Enterprise Stack layouts');
    }
    canvasFitView();
    scheduleCanvasSave();
}

// ─── Sketch Style (rough.js) ───────────────────────────────────

function _applySketchStyle() {
    if (!window.roughjs && !window.rough) return;
    const RoughCanvas = (window.rough || window.roughjs).canvas;
    if (!RoughCanvas) return;

    // Get the underlying HTML canvas
    const canvasEl = _fabricCanvas.lowerCanvasEl || _fabricCanvas.getElement();
    const rc = RoughCanvas(canvasEl);

    // Walk all category blocks and redraw their background rects with rough.js
    _fabricCanvas.getObjects().forEach(obj => {
        if (obj._customType !== 'categoryBlock') return;
        const objs = obj.getObjects ? obj.getObjects() : [];
        const bgRect = objs.find(o => o.type === 'rect');
        if (!bgRect) return;

        // Store original values and make the clean rect transparent
        bgRect._origFill = bgRect.fill;
        bgRect._origStroke = bgRect.stroke;
        bgRect._origStrokeWidth = bgRect.strokeWidth;
        bgRect.set({
            fill: 'transparent',
            stroke: 'transparent',
            strokeWidth: 0,
        });
    });

    // Re-render with rough overlays
    _fabricCanvas.renderAll();

    // Draw rough shapes over the clean canvas
    _fabricCanvas.getObjects().forEach(obj => {
        if (obj._customType !== 'categoryBlock') return;
        const bound = obj.getBoundingRect();
        const objs = obj.getObjects ? obj.getObjects() : [];
        const bgRect = objs.find(o => o.type === 'rect');
        if (!bgRect || !bgRect._origStroke) return;

        rc.rectangle(bound.left, bound.top, bound.width, bound.height, {
            stroke: bgRect._origStroke,
            strokeWidth: 2,
            fill: bgRect._origFill,
            fillStyle: 'cross-hatch',
            roughness: 1.5,
            bowing: 1,
        });
    });
}

// ─── PDF Export (vector via pdfmake) ────────────────────────────

function exportCanvasPdf() {
    if (!_fabricCanvas) return;
    if (!window.pdfMake) {
        showToast('PDF library not loaded');
        return;
    }

    // Temporarily hide grid
    const wasGrid = _canvasGridVisible;
    if (wasGrid) {
        _canvasGridLines.forEach(l => l.set({ visible: false }));
        _fabricCanvas.renderAll();
    }

    const svg = _fabricCanvas.toSVG();

    if (wasGrid) {
        _canvasGridLines.forEach(l => l.set({ visible: true }));
        _fabricCanvas.renderAll();
    }

    // Calculate canvas dimensions
    const objects = _fabricCanvas.getObjects().filter(o => !o._isGridLine);
    let canvasW = 800, canvasH = 600;
    if (objects.length) {
        let maxX = 0, maxY = 0;
        objects.forEach(o => {
            const b = o.getBoundingRect();
            maxX = Math.max(maxX, b.left + b.width);
            maxY = Math.max(maxY, b.top + b.height);
        });
        canvasW = maxX + 40;
        canvasH = maxY + 40;
    }

    // Use landscape if wider than tall
    const pageOrientation = canvasW > canvasH ? 'landscape' : 'portrait';

    const docDefinition = {
        pageSize: 'A4',
        pageOrientation,
        pageMargins: [20, 20, 20, 20],
        content: [
            {
                svg: svg,
                width: pageOrientation === 'landscape' ? 770 : 555,
            },
        ],
    };

    pdfMake.createPdf(docDefinition).download('canvas-diagram.pdf');
}

// ─── _isDark helper (reuse from canvas.js scope) ────────────────

function _diagramIsDark() {
    return document.documentElement.getAttribute('data-theme') === 'dark';
}
