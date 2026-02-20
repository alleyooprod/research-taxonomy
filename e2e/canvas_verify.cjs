/**
 * Canvas verification — tests drawing after driver.js cleanup fix
 * Run: node e2e/canvas_verify.cjs
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

    const csrf = await page.evaluate(() => document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '');
    const projects = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
        return r.json();
    }, csrf);
    await page.evaluate((id) => selectProject(id), projects[0].id);
    await page.waitForTimeout(3000);

    // Check body classes before cleanup
    const bodyClassesBefore = await page.evaluate(() => document.body.className);
    console.log('Body classes before tab switch:', bodyClassesBefore);

    // Switch to canvas (the showTab function now calls _cleanupDriverJs)
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(3000);

    // Check body classes after cleanup
    const bodyClassesAfter = await page.evaluate(() => document.body.className);
    console.log('Body classes after tab switch:', bodyClassesAfter);

    // Create canvas
    page.once('dialog', async d => { await d.accept('Verify Canvas'); });
    await page.evaluate(() => createNewCanvas());
    await page.waitForTimeout(5000);

    // Check pointer-events on canvas elements
    const peCheck = await page.evaluate(() => {
        const wrapper = document.getElementById('canvasWrapper');
        const upper = document.querySelector('.upper-canvas');
        const container = document.querySelector('.canvas-container');
        const getpe = el => el ? window.getComputedStyle(el).pointerEvents : 'N/A';
        return {
            body: getpe(document.body),
            wrapper: getpe(wrapper),
            container: getpe(container),
            upperCanvas: getpe(upper),
        };
    });
    console.log('Pointer events:', JSON.stringify(peCheck));

    // Hit test at canvas center
    const hitTest = await page.evaluate(() => {
        const wrapper = document.getElementById('canvasWrapper');
        const rect = wrapper.getBoundingClientRect();
        const cx = rect.x + rect.width / 2;
        const cy = rect.y + rect.height / 2;
        const el = document.elementFromPoint(cx, cy);
        return el ? { tag: el.tagName, class: String(el.className).substring(0, 50) } : null;
    });
    console.log('Hit test at canvas center:', JSON.stringify(hitTest));

    // Check if Fabric canvas exists
    const fabricExists = await page.evaluate(() => !!window._fabricCanvas);
    console.log('Fabric canvas exists:', fabricExists);

    if (fabricExists) {
        // Set rect tool and draw via mouse
        console.log('\n--- Drawing test ---');
        await page.evaluate(() => setCanvasTool('rect'));
        await page.waitForTimeout(300);

        const wrapperBox = await page.evaluate(() => {
            const w = document.getElementById('canvasWrapper');
            const r = w?.getBoundingClientRect();
            return r ? { x: r.x, y: r.y, w: r.width, h: r.height } : null;
        });

        if (wrapperBox) {
            const startX = wrapperBox.x + 200;
            const startY = wrapperBox.y + 150;

            // Draw rectangle
            await page.mouse.move(startX, startY);
            await page.mouse.down();
            await page.mouse.move(startX + 200, startY + 120, { steps: 10 });
            await page.mouse.up();
            await page.waitForTimeout(1000);

            const afterRect = await page.evaluate(() => ({
                objects: window._fabricCanvas?.getObjects().length,
                tool: typeof _canvasTool !== 'undefined' ? _canvasTool : 'inaccessible',
            }));
            console.log('After rect draw:', JSON.stringify(afterRect));

            // Draw a circle
            await page.evaluate(() => setCanvasTool('circle'));
            await page.waitForTimeout(300);
            await page.mouse.move(startX + 300, startY + 50);
            await page.mouse.down();
            await page.mouse.move(startX + 450, startY + 180, { steps: 10 });
            await page.mouse.up();
            await page.waitForTimeout(1000);

            const afterCircle = await page.evaluate(() => ({
                objects: window._fabricCanvas?.getObjects().length,
            }));
            console.log('After circle draw:', JSON.stringify(afterCircle));

            // Add text
            await page.evaluate(() => setCanvasTool('text'));
            await page.waitForTimeout(300);
            await page.mouse.click(startX + 100, startY + 200);
            await page.waitForTimeout(500);

            const afterText = await page.evaluate(() => ({
                objects: window._fabricCanvas?.getObjects().length,
            }));
            console.log('After text:', JSON.stringify(afterText));

            // Drag a company from sidebar
            console.log('\n--- Company drag test ---');
            const companyItem = await page.locator('.canvas-sidebar-item').first();
            if (await companyItem.count() > 0) {
                const box = await companyItem.boundingBox();
                if (box) {
                    const targetX = wrapperBox.x + wrapperBox.w / 2;
                    const targetY = wrapperBox.y + wrapperBox.h / 2;
                    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
                    await page.mouse.down();
                    await page.mouse.move(targetX, targetY, { steps: 10 });
                    await page.mouse.up();
                    await page.waitForTimeout(1000);

                    const afterDrag = await page.evaluate(() => ({
                        objects: window._fabricCanvas?.getObjects().length,
                    }));
                    console.log('After company drag:', JSON.stringify(afterDrag));
                }
            }

            await page.screenshot({ path: DIR + '/canvas_verify_drawn.png' });
            console.log('\nSaved: canvas_verify_drawn.png');
        }
    }

    // Print canvas logs
    const canvasLogs = consoleLogs.filter(l => l.includes('[Canvas]'));
    console.log('\n=== Canvas Logs ===');
    canvasLogs.forEach(l => console.log('  ', l));

    const nonNetErrors = consoleLogs.filter(l => l.startsWith('error') && !l.includes('net::ERR'));
    console.log('\n=== Non-network Errors (' + nonNetErrors.length + ') ===');
    nonNetErrors.forEach(e => console.log('  ', e));

    // Cleanup
    await page.evaluate(async (token) => {
        const id = document.getElementById('canvasSelect')?.value;
        if (id) await fetch(`/api/canvases/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': token } });
    }, csrf);

    await browser.close();
    console.log('\nDone.');
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
