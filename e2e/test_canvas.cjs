/**
 * Canvas Tab — comprehensive Playwright test script.
 * Tests: tab load, canvas creation, drawing tools, canvas list, export buttons.
 * Run: node e2e/test_canvas.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const BASE = 'http://127.0.0.1:5001/';

const results = [];
function record(test, pass, detail) {
    results.push({ test, pass, detail });
    console.log(`  ${pass ? 'PASS' : 'FAIL'}: ${test} — ${detail}`);
}

async function dismissTour(page) {
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(300);
}

/**
 * Wait until all local JS scripts have defined their key functions.
 * This guards against the CDN defer / local script race condition.
 */
async function waitForScriptsReady(page, timeout = 15000) {
    await page.waitForFunction(() => {
        return typeof selectProject === 'function'
            && typeof renderFilterChips === 'function'
            && typeof loadFilterOptions === 'function'
            && typeof loadCompanies === 'function'
            && typeof showTab === 'function'
            && typeof loadCanvasList === 'function'
            && typeof createNewCanvas === 'function'
            && typeof initFabricCanvas === 'function'
            && typeof fabric !== 'undefined';
    }, { timeout });
}

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    const consoleLogs = [];
    page.on('console', msg => consoleLogs.push(msg.type() + ': ' + msg.text()));

    // ——— Setup: load page, dismiss tour, create project & companies ———
    console.log('\n=== SETUP ===');
    console.log('Loading homepage...');
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    console.log('Waiting for all scripts to be ready...');
    await waitForScriptsReady(page);
    console.log('All scripts ready.');

    await dismissTour(page);

    // Get CSRF token
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
    console.log('CSRF token obtained:', csrf ? 'yes' : 'NO — tests may fail');

    // Create test project
    console.log('Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Canvas Test ' + Date.now(),
                purpose: 'Canvas tab testing',
                seed_categories: 'Digital Health\nInsurTech'
            })
        });
        return r.json();
    }, csrf);

    let pid = projResp.id || projResp.project_id;
    if (!pid) {
        console.log('Project creation returned no ID, listing existing...');
        const projects = await page.evaluate(async (token) => {
            const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
            return r.json();
        }, csrf);
        if (projects && projects.length > 0) {
            pid = projects[0].id;
            console.log('Using existing project:', pid, projects[0].name);
        } else {
            console.log('ERROR: No projects available. Aborting.');
            await browser.close();
            process.exit(1);
        }
    } else {
        console.log('Project created, id:', pid);
    }

    // Add 2 companies
    console.log('Adding test companies...');
    const companies = [
        { name: 'TestCo Alpha', url: 'https://testco-alpha-' + Date.now() + '.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'Digital Health' },
        { name: 'TestCo Beta', url: 'https://testco-beta-' + Date.now() + '.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom', category_name: 'InsurTech' },
    ];
    for (const c of companies) {
        const resp = await page.evaluate(async (args) => {
            const r = await fetch('/api/companies/add', {
                method: 'POST',
                headers: { 'X-CSRF-Token': args.token, 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: args.pid, ...args.company })
            });
            return { status: r.status, ok: r.ok };
        }, { token: csrf, pid, company: c });
        console.log(`  Added ${c.name}: status ${resp.status}`);
    }

    // Select project via selectProject() — all scripts are guaranteed loaded
    console.log('Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);
    await dismissTour(page);

    // ==========================================
    // TEST A — Canvas Tab Load
    // ==========================================
    console.log('\n=== TEST A: Canvas Tab Load ===');
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(4000);
    await dismissTour(page);

    await page.screenshot({ path: DIR + '/feature_canvas_tab.png', fullPage: false });
    console.log('  Screenshot saved: feature_canvas_tab.png');

    const testA = await page.evaluate(() => {
        return {
            loadCanvasList: typeof loadCanvasList,
            createNewCanvas: typeof createNewCanvas,
            initFabricCanvas: typeof initFabricCanvas,
            fabricLoaded: typeof fabric !== 'undefined',
            fabricType: typeof fabric,
            sidebarExists: !!document.getElementById('canvasSidebar'),
            sidebarVisible: (() => {
                const el = document.getElementById('canvasSidebar');
                return el ? el.offsetWidth > 0 : false;
            })(),
            tabVisible: (() => {
                const el = document.getElementById('tab-canvas');
                return el ? !el.classList.contains('hidden') && el.offsetWidth > 0 : false;
            })(),
        };
    });
    console.log('  Results:', JSON.stringify(testA, null, 2));

    record('A1: loadCanvasList exists', testA.loadCanvasList === 'function', `typeof = ${testA.loadCanvasList}`);
    record('A2: createNewCanvas exists', testA.createNewCanvas === 'function', `typeof = ${testA.createNewCanvas}`);
    record('A3: initFabricCanvas exists', testA.initFabricCanvas === 'function', `typeof = ${testA.initFabricCanvas}`);
    record('A4: fabric.js loaded', testA.fabricLoaded, `typeof fabric = ${testA.fabricType}`);
    record('A5: sidebar exists', testA.sidebarExists, `canvasSidebar found = ${testA.sidebarExists}`);
    record('A6: canvas tab visible', testA.tabVisible, `tab-canvas visible = ${testA.tabVisible}`);

    // ==========================================
    // TEST B — Create New Canvas
    // ==========================================
    console.log('\n=== TEST B: Create New Canvas ===');

    // Register dialog handler BEFORE triggering the action
    let dialogHandled = false;
    page.once('dialog', async dialog => {
        console.log(`  Dialog appeared: type=${dialog.type()}, message="${dialog.message()}"`);
        await dialog.accept('Test Canvas 1');
        dialogHandled = true;
    });

    await page.evaluate(() => {
        const btn = document.querySelector('button[onclick*="createNewCanvas"]');
        if (btn) btn.click();
        else if (typeof createNewCanvas === 'function') createNewCanvas();
    });
    await page.waitForTimeout(4000);
    await dismissTour(page);

    await page.screenshot({ path: DIR + '/feature_canvas_created.png', fullPage: false });
    console.log('  Screenshot saved: feature_canvas_created.png');

    const testB = await page.evaluate(() => {
        const el = document.getElementById('fabricCanvas');
        const wrapper = document.getElementById('canvasWrapper');
        const drawToolbar = document.getElementById('canvasDrawToolbar');
        return {
            canvasExists: !!el,
            canvasWidth: el ? el.width : 0,
            canvasHeight: el ? el.height : 0,
            wrapperVisible: wrapper ? !wrapper.classList.contains('hidden') : false,
            toolbarVisible: drawToolbar ? !drawToolbar.classList.contains('hidden') : false,
            emptyStateHidden: (() => {
                const es = document.getElementById('canvasEmptyState');
                return es ? es.classList.contains('hidden') || es.style.display === 'none' : true;
            })(),
        };
    });
    console.log('  Results:', JSON.stringify(testB, null, 2));

    record('B1: dialog handled', dialogHandled, `dialog accepted = ${dialogHandled}`);
    record('B2: fabricCanvas exists', testB.canvasExists, `element found = ${testB.canvasExists}`);
    record('B3: canvas has size', testB.canvasWidth > 0 && testB.canvasHeight > 0, `${testB.canvasWidth}x${testB.canvasHeight}`);
    record('B4: canvas wrapper visible', testB.wrapperVisible, `canvasWrapper visible = ${testB.wrapperVisible}`);
    record('B5: drawing toolbar visible', testB.toolbarVisible, `canvasDrawToolbar visible = ${testB.toolbarVisible}`);
    record('B6: empty state hidden', testB.emptyStateHidden, `empty state hidden = ${testB.emptyStateHidden}`);

    // ==========================================
    // TEST C — Canvas Drawing Tools
    // ==========================================
    console.log('\n=== TEST C: Canvas Drawing Tools ===');

    const testC = await page.evaluate(() => {
        const tools = {
            toolSelect: !!document.getElementById('toolSelect'),
            toolPen: !!document.getElementById('toolPen'),
            toolLine: !!document.getElementById('toolLine'),
            toolRect: !!document.getElementById('toolRect'),
            toolCircle: !!document.getElementById('toolCircle'),
            toolDiamond: !!document.getElementById('toolDiamond'),
            toolText: !!document.getElementById('toolText'),
            toolNote: !!document.getElementById('toolNote'),
            toolPan: !!document.getElementById('toolPan'),
            toolGrid: !!document.getElementById('toolGrid'),
        };

        // Sketch mode toggle — it is a button with id="toolHandDrawn"
        const sketchToggle = document.getElementById('toolHandDrawn');
        tools.sketchToggleExists = !!sketchToggle;
        tools.sketchLabelText = sketchToggle ? sketchToggle.textContent.trim() : '';

        // Color pickers
        const fillColor = document.getElementById('canvasFillColor');
        const strokeColor = document.getElementById('canvasStrokeColor');
        tools.fillColorExists = !!fillColor;
        tools.fillColorType = fillColor ? fillColor.type : '';
        tools.strokeColorExists = !!strokeColor;
        tools.strokeColorType = strokeColor ? strokeColor.type : '';

        // Stroke width / font size controls
        const strokeWidth = document.getElementById('canvasStrokeWidth');
        const fontSize = document.getElementById('canvasFontSize');
        tools.strokeWidthExists = !!strokeWidth;
        tools.fontSizeExists = !!fontSize;

        // Undo/redo/delete buttons
        tools.deleteBtn = !!document.querySelector('button[onclick*="deleteSelectedCanvasElements"]');
        tools.undoBtn = !!document.querySelector('button[onclick*="canvasUndo"]');
        tools.redoBtn = !!document.querySelector('button[onclick*="canvasRedo"]');

        // Zoom controls
        tools.zoomInBtn = !!document.querySelector('button[onclick*="canvasZoom(1.2)"]');
        tools.zoomOutBtn = !!document.querySelector('button[onclick*="canvasZoom(0.8)"]');
        tools.fitViewBtn = !!document.querySelector('button[onclick*="canvasFitView"]');

        return tools;
    });
    console.log('  Results:', JSON.stringify(testC, null, 2));

    await page.screenshot({ path: DIR + '/feature_canvas_tools.png', fullPage: false });
    console.log('  Screenshot saved: feature_canvas_tools.png');

    record('C1: pen/draw tool exists', testC.toolPen, `toolPen = ${testC.toolPen}`);
    record('C2: shape tools exist (rect/circle/diamond)', testC.toolRect && testC.toolCircle && testC.toolDiamond, `rect=${testC.toolRect}, circle=${testC.toolCircle}, diamond=${testC.toolDiamond}`);
    record('C3: text tool exists', testC.toolText, `toolText = ${testC.toolText}`);
    record('C4: line tool exists', testC.toolLine, `toolLine = ${testC.toolLine}`);
    record('C5: sketch mode toggle exists', testC.sketchToggleExists, `toolHandDrawn = ${testC.sketchToggleExists}, label = "${testC.sketchLabelText}"`);
    record('C6: fill color picker exists', testC.fillColorExists, `type = ${testC.fillColorType}`);
    record('C7: stroke color picker exists', testC.strokeColorExists, `type = ${testC.strokeColorType}`);
    record('C8: stroke width control exists', testC.strokeWidthExists, `canvasStrokeWidth = ${testC.strokeWidthExists}`);
    record('C9: font size control exists', testC.fontSizeExists, `canvasFontSize = ${testC.fontSizeExists}`);
    record('C10: undo/redo buttons exist', testC.undoBtn && testC.redoBtn, `undo=${testC.undoBtn}, redo=${testC.redoBtn}`);
    record('C11: zoom controls exist', testC.zoomInBtn && testC.zoomOutBtn && testC.fitViewBtn, `zoomIn=${testC.zoomInBtn}, zoomOut=${testC.zoomOutBtn}, fitView=${testC.fitViewBtn}`);
    record('C12: select tool exists', testC.toolSelect, `toolSelect = ${testC.toolSelect}`);

    // ==========================================
    // TEST D — Canvas List (create second canvas)
    // ==========================================
    console.log('\n=== TEST D: Canvas List ===');

    // Register new dialog handler for second canvas
    page.once('dialog', async dialog => {
        console.log(`  Dialog appeared: type=${dialog.type()}, message="${dialog.message()}"`);
        await dialog.accept('Test Canvas 2');
    });

    await page.evaluate(() => {
        const btn = document.querySelector('button[onclick*="createNewCanvas"]');
        if (btn) btn.click();
        else if (typeof createNewCanvas === 'function') createNewCanvas();
    });
    await page.waitForTimeout(3000);
    await dismissTour(page);

    await page.screenshot({ path: DIR + '/feature_canvas_list.png', fullPage: false });
    console.log('  Screenshot saved: feature_canvas_list.png');

    const testD = await page.evaluate(() => {
        const select = document.getElementById('canvasSelect');
        const options = select ? Array.from(select.options) : [];
        // Filter out the placeholder "Select canvas..." option
        const canvasOptions = options.filter(o => o.value && o.value !== '');
        return {
            selectExists: !!select,
            totalOptions: options.length,
            canvasCount: canvasOptions.length,
            canvasNames: canvasOptions.map(o => o.textContent.trim()),
            selectedValue: select ? select.value : '',
        };
    });
    console.log('  Results:', JSON.stringify(testD, null, 2));

    record('D1: canvas select dropdown exists', testD.selectExists, `canvasSelect found = ${testD.selectExists}`);
    record('D2: 2+ canvases in list', testD.canvasCount >= 2, `canvas count = ${testD.canvasCount}, names = [${testD.canvasNames.join(', ')}]`);
    record('D3: canvas names visible', testD.canvasNames.length >= 2, `names: ${JSON.stringify(testD.canvasNames)}`);

    // ==========================================
    // TEST E — Canvas Export Buttons
    // ==========================================
    console.log('\n=== TEST E: Canvas Export Buttons ===');

    const testE = await page.evaluate(() => {
        const pngBtn = document.getElementById('canvasExportPngBtn');
        const svgBtn = document.getElementById('canvasExportSvgBtn');
        const pdfBtn = document.getElementById('canvasExportPdfBtn');
        return {
            pngBtnExists: !!pngBtn,
            pngBtnText: pngBtn ? pngBtn.textContent.trim() : '',
            pngOnclick: pngBtn ? pngBtn.getAttribute('onclick') : '',
            svgBtnExists: !!svgBtn,
            svgBtnText: svgBtn ? svgBtn.textContent.trim() : '',
            svgOnclick: svgBtn ? svgBtn.getAttribute('onclick') : '',
            pdfBtnExists: !!pdfBtn,
            pdfBtnText: pdfBtn ? pdfBtn.textContent.trim() : '',
            pdfOnclick: pdfBtn ? pdfBtn.getAttribute('onclick') : '',
            diagramBtnExists: !!document.getElementById('canvasGenDiagramBtn'),
        };
    });
    console.log('  Results:', JSON.stringify(testE, null, 2));

    await page.screenshot({ path: DIR + '/feature_canvas_export.png', fullPage: false });
    console.log('  Screenshot saved: feature_canvas_export.png');

    record('E1: PNG export button exists', testE.pngBtnExists, `canvasExportPngBtn found, onclick="${testE.pngOnclick}"`);
    record('E2: SVG export button exists', testE.svgBtnExists, `canvasExportSvgBtn found, onclick="${testE.svgOnclick}"`);
    record('E3: PDF export button exists', testE.pdfBtnExists, `canvasExportPdfBtn found, onclick="${testE.pdfOnclick}"`);

    // ==========================================
    // SUMMARY
    // ==========================================
    console.log('\n========================================');
    console.log('           TEST SUMMARY');
    console.log('========================================');

    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass).length;
    const total = results.length;

    for (const r of results) {
        const icon = r.pass ? 'PASS' : 'FAIL';
        console.log(`  [${icon}] ${r.test}`);
        if (!r.pass) {
            console.log(`         Detail: ${r.detail}`);
        }
    }

    console.log('----------------------------------------');
    console.log(`  Total: ${total} | Passed: ${passed} | Failed: ${failed}`);
    console.log('----------------------------------------');

    // Console errors
    const errors = consoleLogs.filter(l => l.startsWith('error:'));
    if (errors.length > 0) {
        console.log(`\n  Console errors (${errors.length}):`);
        errors.forEach(e => console.log('    ' + e));
    }

    console.log('\n  Screenshots saved to ' + DIR + '/');
    console.log('    - feature_canvas_tab.png');
    console.log('    - feature_canvas_created.png');
    console.log('    - feature_canvas_tools.png');
    console.log('    - feature_canvas_list.png');
    console.log('    - feature_canvas_export.png');

    await browser.close();
    process.exit(failed > 0 ? 1 : 0);

})().catch(e => {
    console.error('FATAL:', e.message);
    console.error(e.stack);
    process.exit(1);
});
