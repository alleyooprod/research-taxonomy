/**
 * Canvas diagnostic v3 — investigate why mouse events don't reach Fabric.js
 * Run: node e2e/canvas_debug3.cjs
 */
const { chromium } = require('playwright');
const DIR = 'test-evidence';

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    const consoleLogs = [];
    page.on('console', msg => consoleLogs.push(msg.type() + ': ' + msg.text()));
    page.on('pageerror', err => consoleLogs.push('PAGE_ERROR: ' + err.message));

    await page.goto('http://127.0.0.1:5001/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });

    const csrf = await page.evaluate(() => document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '');
    const projects = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
        return r.json();
    }, csrf);
    await page.evaluate((id) => selectProject(id), projects[0].id);
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });

    // Switch to canvas
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });

    // Create canvas
    page.once('dialog', async d => { await d.accept('Debug v3'); });
    await page.evaluate(() => createNewCanvas());
    await page.waitForTimeout(5000);

    // 1. Inspect the DOM structure around the canvas
    const domStructure = await page.evaluate(() => {
        const wrapper = document.getElementById('canvasWrapper');
        if (!wrapper) return 'No canvasWrapper';

        function describeEl(el, depth = 0) {
            const indent = '  '.repeat(depth);
            const tag = el.tagName?.toLowerCase() || '?';
            const id = el.id ? `#${el.id}` : '';
            const cls = el.className ? `.${String(el.className).split(' ').join('.')}` : '';
            const styles = window.getComputedStyle(el);
            const pos = styles.position;
            const zIndex = styles.zIndex;
            const pointerEvents = styles.pointerEvents;
            const display = styles.display;
            const overflow = styles.overflow;
            const dims = `${el.offsetWidth}x${el.offsetHeight}`;
            const rect = el.getBoundingClientRect();
            const bounds = `(${Math.round(rect.x)},${Math.round(rect.y)})`;

            let desc = `${indent}${tag}${id}${cls} [${dims}] pos=${pos} z=${zIndex} pe=${pointerEvents} d=${display} ${bounds}`;

            const children = [];
            for (const child of el.children) {
                children.push(describeEl(child, depth + 1));
            }
            return desc + (children.length ? '\n' + children.join('\n') : '');
        }

        return describeEl(wrapper);
    });
    console.log('DOM structure:\n' + domStructure);

    // 2. Check what element is at the center of the canvas (hit test)
    const hitTest = await page.evaluate(() => {
        const wrapper = document.getElementById('canvasWrapper');
        const rect = wrapper.getBoundingClientRect();
        const cx = rect.x + rect.width / 2;
        const cy = rect.y + rect.height / 2;
        const el = document.elementFromPoint(cx, cy);
        if (!el) return { found: false, x: cx, y: cy };
        return {
            found: true,
            x: cx, y: cy,
            tagName: el.tagName,
            id: el.id,
            className: String(el.className),
            pointerEvents: window.getComputedStyle(el).pointerEvents,
            zIndex: window.getComputedStyle(el).zIndex,
        };
    });
    console.log('\nHit test at canvas center:', JSON.stringify(hitTest, null, 2));

    // 3. Add a native DOM click listener to see if clicks reach the canvas elements
    const nativeEventTest = await page.evaluate(() => {
        return new Promise(resolve => {
            const results = { upperCanvasClicks: 0, lowerCanvasClicks: 0, wrapperClicks: 0, containerClicks: 0 };

            const upper = document.querySelector('.upper-canvas');
            const lower = document.querySelector('.lower-canvas');
            const wrapper = document.getElementById('canvasWrapper');
            const container = document.querySelector('.canvas-container');

            if (upper) upper.addEventListener('mousedown', () => { results.upperCanvasClicks++; }, true);
            if (lower) lower.addEventListener('mousedown', () => { results.lowerCanvasClicks++; }, true);
            if (wrapper) wrapper.addEventListener('mousedown', () => { results.wrapperClicks++; }, true);
            if (container) container.addEventListener('mousedown', () => { results.containerClicks++; }, true);

            // Also test if Fabric.js event system works
            const fc = window._fabricCanvas;
            if (fc) {
                let fabricEventCount = 0;
                fc.on('mouse:down', () => { fabricEventCount++; });
                results._fabricEventListener = 'bound';
                // Store reference for later check
                window._testFabricEventCount = () => fabricEventCount;
            }

            window._testNativeResults = results;
            resolve({
                upperExists: !!upper,
                lowerExists: !!lower,
                containerExists: !!container,
                upperPointerEvents: upper ? window.getComputedStyle(upper).pointerEvents : 'N/A',
                upperPosition: upper ? window.getComputedStyle(upper).position : 'N/A',
                upperZIndex: upper ? window.getComputedStyle(upper).zIndex : 'N/A',
                upperDisplay: upper ? window.getComputedStyle(upper).display : 'N/A',
                upperDims: upper ? `${upper.offsetWidth}x${upper.offsetHeight}` : 'N/A',
            });
        });
    });
    console.log('\nNative event setup:', JSON.stringify(nativeEventTest, null, 2));

    // 4. Now do actual mouse clicks and check what fires
    const wrapperBox = await page.evaluate(() => {
        const w = document.getElementById('canvasWrapper');
        const r = w?.getBoundingClientRect();
        return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
    });

    if (wrapperBox) {
        const cx = wrapperBox.x + wrapperBox.w / 2;
        const cy = wrapperBox.y + wrapperBox.h / 2;

        console.log(`\nClicking at (${cx}, ${cy})...`);
        await page.mouse.click(cx, cy);
        await page.waitForTimeout(500);
        await page.mouse.click(cx + 50, cy + 50);
        await page.waitForTimeout(500);
        await page.mouse.click(cx - 50, cy - 50);
        await page.waitForTimeout(500);

        const clickResults = await page.evaluate(() => {
            const r = window._testNativeResults || {};
            const fabricEvents = typeof window._testFabricEventCount === 'function' ? window._testFabricEventCount() : 'N/A';
            return { ...r, fabricEvents };
        });
        console.log('Click results:', JSON.stringify(clickResults, null, 2));
    }

    // 5. Check Fabric.js 6 internal event handler count
    const fabricInternals = await page.evaluate(() => {
        const fc = window._fabricCanvas;
        if (!fc) return 'no canvas';
        return {
            // Check if there are event handlers registered
            hasEvents: !!fc.__eventListeners,
            eventTypes: fc.__eventListeners ? Object.keys(fc.__eventListeners) : [],
            mouseDownHandlers: fc.__eventListeners?.['mouse:down']?.length || 0,
            mouseMoveHandlers: fc.__eventListeners?.['mouse:move']?.length || 0,
            mouseUpHandlers: fc.__eventListeners?.['mouse:up']?.length || 0,
        };
    });
    console.log('\nFabric.js internals:', JSON.stringify(fabricInternals, null, 2));

    // Print canvas-specific logs
    const canvasLogs = consoleLogs.filter(l => l.includes('[Canvas]'));
    console.log('\n=== Canvas Logs ===');
    canvasLogs.forEach(l => console.log('  ', l));

    // Cleanup
    await page.evaluate(async (token) => {
        const id = document.getElementById('canvasSelect')?.value;
        if (id) await fetch(`/api/canvases/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': token } });
    }, csrf);

    await browser.close();
    console.log('\nDone.');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
