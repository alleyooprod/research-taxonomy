/**
 * AI Diagram Generator: LLM-powered enterprise architecture diagrams.
 * Uses structured output from Claude/Gemini to create Excalidraw elements.
 */

let _diagramPollTimer = null;
let _diagramPollCount = 0;
const _DIAGRAM_MAX_POLL = 120;  // 6 min at 3s intervals
let _diagramStartTime = 0;

// ─── Diagram Templates ─────────────────────────────────────────

const _DIAGRAM_TEMPLATES = {
    market_landscape: {
        prompt: 'Create a market landscape overview. Arrange each category as a labeled block in a grid layout. Show all companies within their category blocks. Group related categories near each other.',
        layout: 'grid',
        fields: ['name'],
    },
    tech_stack: {
        prompt: 'Create an enterprise technology stack diagram. Stack categories vertically as layers — infrastructure/data at the bottom, platforms in the middle, and consumer-facing/applications at the top. Show companies within each layer. Add connectors between layers to show data flow.',
        layout: 'stacked_vertical',
        fields: ['name', 'what'],
    },
    value_chain: {
        prompt: 'Create a value chain diagram showing how these categories connect in a left-to-right flow. Start with upstream/input categories on the left and progress to downstream/consumer-facing categories on the right. Add labeled connectors showing the relationships between stages.',
        layout: 'flow',
        fields: ['name'],
    },
    competitive: {
        prompt: 'Create a competitive landscape diagram. Arrange companies in a grid grouped by category. For each company, prominently display their funding and employee count to show relative scale. Place larger/more-funded companies more prominently.',
        layout: 'grid',
        fields: ['name', 'total_funding_usd', 'employee_range', 'funding_stage'],
    },
    customer_journey: {
        prompt: 'Map these categories to stages of a customer/patient health journey — from awareness and prevention, through diagnosis and treatment, to ongoing management and outcomes. Arrange left-to-right as a flow. Show which companies serve each stage.',
        layout: 'flow',
        fields: ['name', 'what'],
    },
};

function useDiagramTemplate(templateKey) {
    const tmpl = _DIAGRAM_TEMPLATES[templateKey];
    if (!tmpl) return;

    document.getElementById('diagramPrompt').value = tmpl.prompt;

    // Set layout style
    const layoutSelect = document.getElementById('diagramLayoutStyle');
    if (layoutSelect) layoutSelect.value = tmpl.layout;

    // Select all categories by default
    toggleAllDiagramCategories(true);

    // Set the right fields
    document.querySelectorAll('#diagramFieldList input[type="checkbox"]:not([disabled])').forEach(cb => {
        cb.checked = tmpl.fields.includes(cb.value);
    });

    // Open the details sections if closed
    document.querySelectorAll('#diagramPanel details').forEach(d => {
        if (tmpl.fields.length > 1) d.open = true;
    });
}

// ─── Panel Management ───────────────────────────────────────────

function openDiagramPanel() {
    if (!_excalidrawAPI || !_currentCanvasId) {
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

    const costStr = data.cost_usd ? ` ($${data.cost_usd.toFixed(4)})` : '';
    const durationStr = data.duration_ms
        ? ` in ${(data.duration_ms / 1000).toFixed(1)}s`
        : '';
    showToast(`Diagram generated${durationStr}${costStr}`);

    // Clear canvas if checkbox checked
    if (document.getElementById('diagramClearCanvas').checked && _excalidrawAPI) {
        _excalidrawAPI.resetScene();
    }

    renderDiagramLayout(data.layout);

    document.getElementById('diagramPostActions').classList.remove('hidden');
    document.getElementById('diagramGenBtn').disabled = false;
}

// ─── Core Renderer: LLM layout → Excalidraw elements ────────────

const _GRID_W = 300;
const _GRID_H = 200;
const _DIAGRAM_PAD = 20;
const _COMPANY_ROW_H = 22;
const _DIAGRAM_MARGIN = 40;

function renderDiagramLayout(layout) {
    if (!_excalidrawAPI || !layout) return;

    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const newElements = [];
    let titleOffset = 0;

    // 1. Title
    if (layout.title) {
        newElements.push(_makeElement('text', {
            x: _DIAGRAM_MARGIN,
            y: _DIAGRAM_MARGIN,
            text: layout.title,
            fontSize: 28,
            strokeColor: isDark ? '#e0ddd5' : '#1a1a1a',
            fontFamily: 2,
        }));
        titleOffset = 50;
    }

    // 2. Category blocks
    const blockCenters = {}; // category_id → {cx, cy}

    for (const block of (layout.category_blocks || [])) {
        const x = _DIAGRAM_MARGIN + block.col * _GRID_W;
        const y = _DIAGRAM_MARGIN + titleOffset + block.row * _GRID_H;
        const w = block.width_units * _GRID_W - _DIAGRAM_PAD;
        const minH = block.height_units * _GRID_H - _DIAGRAM_PAD;
        const contentH = 44 + (block.companies || []).length * _COMPANY_ROW_H + 10;
        const h = Math.max(minH, contentH);
        const color = block.color || '#5a7c5a';

        const blockId = _randomId();

        // Background rectangle
        newElements.push(_makeElement('rectangle', {
            id: blockId,
            x, y, width: w, height: h,
            strokeColor: color,
            backgroundColor: _hexToRgba(color, 0.08),
            fillStyle: 'solid',
            strokeWidth: 1,
            roughness: 0,
            roundness: null,
            customData: { categoryId: block.category_id, type: 'categoryBlock' },
        }));

        // Category label
        newElements.push(_makeElement('text', {
            x: x + 14, y: y + 10,
            text: block.label || block.category_name,
            fontSize: 16,
            strokeColor: color,
            fontFamily: 2,
        }));

        // Company count
        newElements.push(_makeElement('text', {
            x: x + w - 14, y: y + 12,
            text: `${(block.companies || []).length} companies`,
            fontSize: 11,
            strokeColor: _hexToRgba(color, 0.5),
            fontFamily: 2,
            textAlign: 'right',
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
                displayText += '  \u2014  ' + fieldParts.join(' \u00b7 ');
            }
            if (displayText.length > 70) {
                displayText = displayText.substring(0, 68) + '...';
            }

            newElements.push(_makeElement('text', {
                x: x + 18,
                y: y + 40 + i * _COMPANY_ROW_H,
                text: displayText,
                fontSize: 12,
                strokeColor: isDark ? '#c8c5bd' : '#555555',
                fontFamily: 2,
            }));
        });

        // Track center for connectors
        blockCenters[block.category_id] = {
            cx: x + w / 2,
            cy: y + h / 2,
            id: blockId,
            bottom: y + h,
            top: y,
        };
    }

    // 3. Connectors (arrows)
    if (layout.connectors) {
        for (const conn of layout.connectors) {
            const from = blockCenters[conn.from_category_id];
            const to = blockCenters[conn.to_category_id];
            if (!from || !to) continue;

            const arrowId = _randomId();
            // Arrow from bottom of source to top of target
            const x1 = from.cx;
            const y1 = from.bottom;
            const x2 = to.cx;
            const y2 = to.top;

            newElements.push(_makeElement('arrow', {
                id: arrowId,
                x: x1, y: y1,
                points: [[0, 0], [x2 - x1, y2 - y1]],
                strokeColor: isDark ? '#888888' : '#666666',
                strokeWidth: 1.5,
                strokeStyle: 'dashed',
                roughness: 1,
                endArrowhead: 'arrow',
            }));

            // Connector label
            if (conn.label) {
                const midX = (x1 + x2) / 2;
                const midY = (y1 + y2) / 2;
                newElements.push(_makeElement('text', {
                    x: midX, y: midY - 12,
                    text: conn.label,
                    fontSize: 11,
                    strokeColor: isDark ? '#888888' : '#666666',
                    fontFamily: 2,
                    textAlign: 'center',
                }));
            }
        }
    }

    // 4. Annotations
    if (layout.annotations) {
        for (const ann of layout.annotations) {
            const ax = _DIAGRAM_MARGIN + (ann.col || 0) * _GRID_W;
            const ay = _DIAGRAM_MARGIN + titleOffset + (ann.row || 0) * _GRID_H;
            const fontSize = ann.style === 'heading' ? 20
                : ann.style === 'subheading' ? 15 : 12;

            newElements.push(_makeElement('text', {
                x: ax, y: ay,
                text: ann.text,
                fontSize,
                strokeColor: isDark ? '#e0ddd5' : '#1a1a1a',
                fontFamily: 2,
            }));
        }
    }

    // 5. Add to canvas
    const current = _excalidrawAPI.getSceneElements();
    _excalidrawAPI.updateScene({ elements: [...current, ...newElements] });

    // 6. Scroll to fit
    setTimeout(() => {
        if (_excalidrawAPI && _excalidrawAPI.scrollToContent) {
            _excalidrawAPI.scrollToContent(newElements, { fitToViewport: true, viewportZoomFactor: 0.9 });
        }
    }, 200);

    scheduleCanvasSave();
}

// --- Action Delegation ---
registerActions({
    'open-diagram-panel': () => openDiagramPanel(),
    'close-diagram-panel': () => closeDiagramPanel(),
    'start-diagram-generation': () => startDiagramGeneration(),
    'cancel-diagram-generation': () => cancelDiagramGeneration(),
    'use-diagram-template': (el) => useDiagramTemplate(el.dataset.template),
    'toggle-all-diagram-categories': (el) => toggleAllDiagramCategories(el.dataset.state === 'true'),
});
