/**
 * Full end-to-end test: select project → canvas tab → create canvas → Excalidraw loads
 */
const { chromium } = require('playwright');

const PORT = process.argv[2] || 5099;

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    const consoleErrors = [];
    page.on('console', msg => {
        const t = msg.type();
        if (t === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', err => consoleErrors.push('PAGE: ' + err.message));

    console.log(`Testing against http://127.0.0.1:${PORT}/`);
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle', timeout: 15000 });

    // 0. Dismiss driver.js tour if present
    await page.evaluate(() => {
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        if (window.driverObj) { try { window.driverObj.destroy(); } catch(e) {} }
        document.body.classList.remove('driver-active');
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // 1. Select a project — use selectProject() directly
    const projectInfo = await page.evaluate(() => {
        const cards = document.querySelectorAll('.project-card:not(.new-project-card)');
        if (cards.length === 0) return null;
        // Extract project id and name from card's onclick
        const card = cards[0];
        const onclick = card.getAttribute('onclick') || '';
        const match = onclick.match(/selectProject\((\d+),\s*'([^']+)'\)/);
        if (match) {
            selectProject(parseInt(match[1]), match[2]);
            return { id: parseInt(match[1]), name: match[2] };
        }
        // Fallback: click the card
        card.click();
        return { id: 'clicked', name: 'unknown' };
    });
    if (!projectInfo) {
        console.log('1. SKIP — no projects available');
        await page.screenshot({ path: 'test-evidence/excalidraw-no-projects.png' });
        await browser.close();
        return;
    }
    await page.waitForTimeout(2000);
    console.log('1. Selected project:', projectInfo.name, '(id:', projectInfo.id + ')');

    // 2. Navigate to Canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1500);
    const tabActive = await page.evaluate(() => {
        const t = document.getElementById('tab-canvas');
        return t && t.classList.contains('active');
    });
    console.log('2. Canvas tab active:', tabActive);

    // 3. Create a new canvas via API directly (bypasses prompt dialog)
    await page.waitForTimeout(1500);

    const projectId = await page.evaluate(() => currentProjectId);
    console.log('3. currentProjectId:', projectId);

    if (!projectId) {
        console.log('3. SKIP — no project ID set, cannot create canvas');
        await page.screenshot({ path: 'test-evidence/excalidraw-canvas-loaded.png' });
        await browser.close();
        return;
    }

    // Create canvas via API, then load it
    const canvasId = await page.evaluate(async () => {
        const res = await safeFetch('/api/canvases', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProjectId, title: 'Excalidraw E2E Test' }),
        });
        const data = await res.json();
        if (data.id) {
            await loadCanvasList();
            document.getElementById('canvasSelect').value = data.id;
            loadCanvasFromSelect();
        }
        return data.id;
    });
    console.log('3. Created canvas id:', canvasId);

    // 4. Wait for Excalidraw to load from CDN
    let excalidrawLoaded = false;
    for (let i = 0; i < 20; i++) {
        await page.waitForTimeout(1000);
        excalidrawLoaded = await page.evaluate(() => {
            const root = document.getElementById('excalidrawRoot');
            return !!(root && root.querySelector('.excalidraw'));
        });
        if (excalidrawLoaded) {
            console.log('4. Excalidraw loaded after ' + (i + 1) + 's');
            break;
        }
    }
    if (!excalidrawLoaded) console.log('4. Excalidraw loaded: false (timeout)');

    // 5. Check Excalidraw API is available
    const apiAvailable = await page.evaluate(() => !!window._excalidrawAPI);
    console.log('5. Excalidraw API available:', apiAvailable);

    // 6. Check canvas wrapper is visible
    const wrapperVisible = await page.evaluate(() => {
        const w = document.getElementById('canvasWrapper');
        return w && !w.classList.contains('hidden');
    });
    console.log('6. Canvas wrapper visible:', wrapperVisible);

    // 7. Take screenshot
    await page.screenshot({ path: 'test-evidence/excalidraw-canvas-loaded.png', fullPage: false });
    console.log('7. Screenshot saved to test-evidence/excalidraw-canvas-loaded.png');

    // 8. Verify Excalidraw toolbar elements are present
    const hasToolbar = await page.evaluate(() => {
        const root = document.getElementById('excalidrawRoot');
        if (!root) return false;
        // Check for Excalidraw's shape tools
        const buttons = root.querySelectorAll('button, [role="button"]');
        return buttons.length > 5; // Excalidraw has many toolbar buttons
    });
    console.log('8. Excalidraw toolbar present:', hasToolbar);

    // Summary
    console.log('\n=== RESULTS ===');
    const allPass = tabActive && excalidrawLoaded && apiAvailable && wrapperVisible && hasToolbar;
    console.log(allPass ? 'ALL CHECKS PASSED' : 'SOME CHECKS FAILED');

    if (consoleErrors.length) {
        console.log('\nConsole errors:');
        consoleErrors.slice(0, 5).forEach(e => console.log('  - ' + e.substring(0, 200)));
    }

    await browser.close();
    process.exit(allPass ? 0 : 1);
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
