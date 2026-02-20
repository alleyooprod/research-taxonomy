/**
 * Canvas diagnostic script — captures console errors and tests canvas functionality.
 * Run: node e2e/canvas_debug.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    const consoleLogs = [];
    const pageErrors = [];
    page.on('console', msg => consoleLogs.push(msg.type() + ': ' + msg.text()));
    page.on('pageerror', err => pageErrors.push(err.message));

    console.log('1. Loading homepage...');
    await page.goto('http://127.0.0.1:5001/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // Dismiss driver.js
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Get CSRF
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });

    // Use existing project (Olly Market Taxonomy, id=1)
    console.log('2. Selecting project...');
    const projects = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
        return r.json();
    }, csrf);

    let pid = projects && projects.length > 0 ? projects[0].id : null;
    if (!pid) {
        console.log('ERROR: No projects available');
        await browser.close();
        return;
    }
    console.log('   Using project:', pid, projects[0].name);

    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);

    // Dismiss tour again
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Switch to canvas tab
    console.log('\n3. Switching to Canvas tab...');
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(3000);

    // Dismiss tour
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Check canvas state BEFORE creating canvas
    const preState = await page.evaluate(() => ({
        fabricLoaded: typeof fabric !== 'undefined',
        fabricVersion: typeof fabric !== 'undefined' ? fabric.version : 'N/A',
        canvasFuncsAvailable: {
            loadCanvasList: typeof loadCanvasList === 'function',
            createNewCanvas: typeof createNewCanvas === 'function',
            initFabricCanvas: typeof initFabricCanvas === 'function',
            setCanvasTool: typeof setCanvasTool === 'function',
            loadCanvas: typeof loadCanvas === 'function',
        },
        canvasSelectOptions: document.getElementById('canvasSelect')?.options?.length || 0,
        emptyStateVisible: !document.getElementById('canvasEmptyState')?.classList.contains('hidden'),
        wrapperVisible: !document.getElementById('canvasWrapper')?.classList.contains('hidden'),
        drawToolbarVisible: !document.getElementById('canvasDrawToolbar')?.classList.contains('hidden'),
    }));
    console.log('   Pre-create state:', JSON.stringify(preState, null, 2));

    await page.screenshot({ path: DIR + '/canvas_debug_1_pretab.png' });

    // Create a new canvas
    console.log('\n4. Creating new canvas...');
    page.once('dialog', async dialog => {
        console.log('   Dialog appeared:', dialog.message());
        await dialog.accept('Debug Test Canvas');
    });

    // Clear console logs before creating canvas to isolate errors
    const preCreateErrorCount = consoleLogs.filter(l => l.startsWith('error')).length;
    const preCreateWarningCount = consoleLogs.filter(l => l.startsWith('warning')).length;

    await page.evaluate(() => createNewCanvas());
    await page.waitForTimeout(5000);

    await page.screenshot({ path: DIR + '/canvas_debug_2_created.png' });

    // Check state AFTER creating canvas
    const postState = await page.evaluate(() => {
        const wrapper = document.getElementById('canvasWrapper');
        const fabricEl = document.getElementById('fabricCanvas');
        const fabricCanvas = window._fabricCanvas;

        return {
            wrapperVisible: wrapper ? !wrapper.classList.contains('hidden') : false,
            wrapperDims: wrapper ? { w: wrapper.offsetWidth, h: wrapper.offsetHeight } : null,
            fabricElDims: fabricEl ? { w: fabricEl.width, h: fabricEl.height } : null,
            fabricCanvasExists: !!fabricCanvas,
            fabricCanvasWidth: fabricCanvas ? fabricCanvas.width : null,
            fabricCanvasHeight: fabricCanvas ? fabricCanvas.height : null,
            drawToolbarVisible: !document.getElementById('canvasDrawToolbar')?.classList.contains('hidden'),
            canvasSelectValue: document.getElementById('canvasSelect')?.value,
            emptyStateHidden: document.getElementById('canvasEmptyState')?.classList.contains('hidden'),
            // Check for Fabric.js internal canvas container
            fabricContainerExists: !!document.querySelector('.canvas-container'),
            fabricUpperCanvas: !!document.querySelector('.upper-canvas'),
        };
    });
    console.log('   Post-create state:', JSON.stringify(postState, null, 2));

    // Try drawing operations
    console.log('\n5. Testing drawing tools...');

    // Test select tool
    const toolTest = await page.evaluate(() => {
        const results = {};
        try {
            setCanvasTool('select');
            results.selectTool = 'OK';
        } catch (e) { results.selectTool = 'ERROR: ' + e.message; }

        try {
            setCanvasTool('rect');
            results.rectTool = 'OK';
        } catch (e) { results.rectTool = 'ERROR: ' + e.message; }

        try {
            setCanvasTool('pen');
            results.penTool = 'OK';
        } catch (e) { results.penTool = 'ERROR: ' + e.message; }

        try {
            setCanvasTool('text');
            results.textTool = 'OK';
        } catch (e) { results.textTool = 'ERROR: ' + e.message; }

        try {
            setCanvasTool('note');
            results.noteTool = 'OK';
        } catch (e) { results.noteTool = 'ERROR: ' + e.message; }

        try {
            setCanvasTool('line');
            results.lineTool = 'OK';
        } catch (e) { results.lineTool = 'ERROR: ' + e.message; }

        return results;
    });
    console.log('   Tool tests:', JSON.stringify(toolTest, null, 2));

    // Try to add a shape programmatically
    console.log('\n6. Testing shape creation...');
    const shapeTest = await page.evaluate(() => {
        const results = {};
        const canvas = window._fabricCanvas;
        if (!canvas) { results.error = 'No _fabricCanvas'; return results; }

        try {
            const rect = new fabric.Rect({
                left: 100, top: 100, width: 200, height: 100,
                fill: '#FFFFFF', stroke: '#000000', strokeWidth: 2,
            });
            canvas.add(rect);
            results.rectAdded = true;
            results.objectCount = canvas.getObjects().length;
        } catch (e) { results.rectError = e.message; }

        try {
            const text = new fabric.IText('Hello Canvas', {
                left: 150, top: 150, fontSize: 18,
                fill: '#000000', fontFamily: 'Plus Jakarta Sans, sans-serif',
            });
            canvas.add(text);
            results.textAdded = true;
            results.objectCount = canvas.getObjects().length;
        } catch (e) { results.textError = e.message; }

        try {
            canvas.renderAll();
            results.rendered = true;
        } catch (e) { results.renderError = e.message; }

        return results;
    });
    console.log('   Shape test:', JSON.stringify(shapeTest, null, 2));

    await page.waitForTimeout(1000);
    await page.screenshot({ path: DIR + '/canvas_debug_3_shapes.png' });
    console.log('   Saved: canvas_debug_3_shapes.png');

    // Test mouse interaction by simulating clicks on the canvas
    console.log('\n7. Testing mouse interaction...');
    const wrapperBox = await page.evaluate(() => {
        const w = document.getElementById('canvasWrapper');
        if (!w) return null;
        const r = w.getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height };
    });
    console.log('   Wrapper bounds:', JSON.stringify(wrapperBox));

    if (wrapperBox && wrapperBox.w > 0) {
        // Select rect tool and try to draw
        await page.evaluate(() => setCanvasTool('rect'));

        const cx = wrapperBox.x + 300;
        const cy = wrapperBox.y + 200;

        await page.mouse.move(cx, cy);
        await page.mouse.down();
        await page.mouse.move(cx + 150, cy + 100, { steps: 5 });
        await page.mouse.up();
        await page.waitForTimeout(500);

        const afterDraw = await page.evaluate(() => ({
            objectCount: window._fabricCanvas ? window._fabricCanvas.getObjects().length : 'no canvas',
            currentTool: window._canvasTool,
        }));
        console.log('   After mouse draw:', JSON.stringify(afterDraw));

        await page.screenshot({ path: DIR + '/canvas_debug_4_drawn.png' });
        console.log('   Saved: canvas_debug_4_drawn.png');
    }

    // Check AI Diagram functions
    console.log('\n8. Testing AI Diagram...');
    const diagramFuncs = await page.evaluate(() => ({
        openDiagramPanel: typeof openDiagramPanel === 'function',
        startDiagramGeneration: typeof startDiagramGeneration === 'function',
        closeDiagramPanel: typeof closeDiagramPanel === 'function',
        autoArrangeDiagram: typeof autoArrangeDiagram === 'function',
    }));
    console.log('   Diagram functions:', JSON.stringify(diagramFuncs));

    // Try opening the diagram panel
    const diagramState = await page.evaluate(() => {
        try {
            if (typeof openDiagramPanel === 'function') {
                openDiagramPanel();
                return { opened: true };
            }
            return { opened: false, reason: 'function not found' };
        } catch (e) {
            return { opened: false, error: e.message };
        }
    });
    console.log('   Diagram panel:', JSON.stringify(diagramState));
    await page.waitForTimeout(1000);
    await page.screenshot({ path: DIR + '/canvas_debug_5_diagram.png' });
    console.log('   Saved: canvas_debug_5_diagram.png');

    // Print all console errors
    const newErrors = consoleLogs.filter(l => l.startsWith('error'));
    const newWarnings = consoleLogs.filter(l => l.startsWith('warning'));

    console.log('\n=== Console Errors (' + newErrors.length + ') ===');
    newErrors.forEach(e => console.log('  ', e));

    console.log('\n=== Console Warnings (' + newWarnings.length + ') ===');
    newWarnings.slice(0, 10).forEach(w => console.log('  ', w));

    console.log('\n=== Page Errors (' + pageErrors.length + ') ===');
    pageErrors.forEach(e => console.log('  ', e));

    // Cleanup: delete the test canvas
    console.log('\n9. Cleaning up test canvas...');
    await page.evaluate(async (token) => {
        const canvasId = document.getElementById('canvasSelect')?.value;
        if (canvasId) {
            await fetch(`/api/canvases/${canvasId}`, {
                method: 'DELETE',
                headers: { 'X-CSRF-Token': token }
            });
        }
    }, csrf);

    await browser.close();
    console.log('\nCanvas diagnostic complete. Screenshots saved to ' + DIR + '/');
})().catch(e => {
    console.error('FATAL:', e.message);
    process.exit(1);
});
