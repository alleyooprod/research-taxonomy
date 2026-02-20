/**
 * Canvas diagnostic v2 — uses window._fabricCanvas exposure
 * Run: node e2e/canvas_debug2.cjs
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

    await page.goto('http://127.0.0.1:5001/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // Dismiss tour
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    const csrf = await page.evaluate(() => document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '');

    // Use existing project
    const projects = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
        return r.json();
    }, csrf);
    const pid = projects?.[0]?.id;
    if (!pid) { console.log('No projects'); await browser.close(); return; }
    console.log('Using project:', pid, projects[0].name);

    await page.evaluate((id) => selectProject(id), pid);
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });

    // Switch to canvas
    console.log('\n--- Canvas Tab ---');
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });

    // Create canvas
    page.once('dialog', async d => { await d.accept('Debug v2 Canvas'); });
    await page.evaluate(() => createNewCanvas());
    await page.waitForTimeout(5000);

    // Check window._fabricCanvas
    const fabricState = await page.evaluate(() => {
        const fc = window._fabricCanvas;
        if (!fc) return { exists: false };
        return {
            exists: true,
            width: fc.width,
            height: fc.height,
            objectCount: fc.getObjects().length,
            isDrawingMode: fc.isDrawingMode,
            selection: fc.selection,
            backgroundColor: fc.backgroundColor,
            upperCanvasEl: !!fc.upperCanvasEl,
            lowerCanvasEl: !!fc.lowerCanvasEl,
            wrapperEl: !!fc.wrapperEl,
        };
    });
    console.log('Fabric canvas state:', JSON.stringify(fabricState, null, 2));

    if (fabricState.exists) {
        // Test adding objects programmatically
        const addResult = await page.evaluate(() => {
            const fc = window._fabricCanvas;
            try {
                const rect = new fabric.Rect({
                    left: 100, top: 100, width: 200, height: 120,
                    fill: '#f0f0f0', stroke: '#000000', strokeWidth: 2,
                });
                fc.add(rect);

                const text = new fabric.IText('Test Text', {
                    left: 130, top: 140, fontSize: 20,
                    fill: '#000000', fontFamily: 'Plus Jakarta Sans, sans-serif',
                });
                fc.add(text);

                const circle = new fabric.Circle({
                    left: 400, top: 200, radius: 50,
                    fill: '#e0e0e0', stroke: '#333333', strokeWidth: 1,
                });
                fc.add(circle);

                fc.renderAll();

                return {
                    success: true,
                    objectCount: fc.getObjects().length,
                    canvasDataURL: fc.toDataURL({ format: 'png' }).substring(0, 100),
                };
            } catch (e) {
                return { success: false, error: e.message, stack: e.stack?.substring(0, 300) };
            }
        });
        console.log('Add objects result:', JSON.stringify(addResult, null, 2));

        await page.waitForTimeout(1000);
        await page.screenshot({ path: DIR + '/canvas_debug2_objects.png' });
        console.log('Saved: canvas_debug2_objects.png');

        // Test mouse drawing
        console.log('\n--- Mouse Drawing Test ---');
        await page.evaluate(() => setCanvasTool('rect'));
        await page.waitForTimeout(300);

        const wrapperBox = await page.evaluate(() => {
            const w = document.getElementById('canvasWrapper');
            const r = w?.getBoundingClientRect();
            return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
        });
        console.log('Wrapper box:', JSON.stringify(wrapperBox));

        if (wrapperBox) {
            const cx = wrapperBox.x + 500;
            const cy = wrapperBox.y + 300;
            await page.mouse.move(cx, cy);
            await page.mouse.down();
            await page.mouse.move(cx + 200, cy + 100, { steps: 10 });
            await page.mouse.up();
            await page.waitForTimeout(1000);

            const afterDraw = await page.evaluate(() => ({
                objectCount: window._fabricCanvas?.getObjects().length,
                tool: window._canvasTool,
            }));
            console.log('After mouse draw:', JSON.stringify(afterDraw));

            await page.screenshot({ path: DIR + '/canvas_debug2_drawn.png' });
            console.log('Saved: canvas_debug2_drawn.png');
        }

        // Test undo
        console.log('\n--- Undo Test ---');
        const undoResult = await page.evaluate(() => {
            try {
                const before = window._fabricCanvas?.getObjects().length;
                canvasUndo();
                return { before, after: 'pending (async)' };
            } catch (e) {
                return { error: e.message };
            }
        });
        console.log('Undo result:', JSON.stringify(undoResult));
        await page.waitForTimeout(1000);
    }

    // Print canvas-specific console logs
    const canvasLogs = consoleLogs.filter(l => l.includes('[Canvas]'));
    console.log('\n=== Canvas Logs (' + canvasLogs.length + ') ===');
    canvasLogs.forEach(l => console.log('  ', l));

    const errors = consoleLogs.filter(l => l.startsWith('error') && !l.includes('net::ERR'));
    console.log('\n=== Non-network Errors (' + errors.length + ') ===');
    errors.forEach(e => console.log('  ', e));

    console.log('\n=== Page Errors (' + pageErrors.length + ') ===');
    pageErrors.forEach(e => console.log('  ', e));

    // Cleanup
    await page.evaluate(async (token) => {
        const id = document.getElementById('canvasSelect')?.value;
        if (id) await fetch(`/api/canvases/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': token } });
    }, csrf);

    await browser.close();
    console.log('\nDone.');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
