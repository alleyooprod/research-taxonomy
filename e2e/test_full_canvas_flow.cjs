/**
 * Full canvas flow test against RUNNING app:
 * 1. Select project → Canvas tab
 * 2. Create new canvas via prompt dialog
 * 3. Verify Excalidraw loads
 * 4. Drop a company onto canvas
 * 5. Take evidence screenshots
 *
 * Uses WebKit engine to match pywebview behavior.
 */
const { webkit } = require('playwright');
const PORT = process.argv[2] || 5001;

(async () => {
    const browser = await webkit.launch({ headless: false });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

    const errors = [];
    page.on('console', msg => {
        const t = msg.text();
        if (t.includes('clearbit') || t.includes('ERR_NAME') || t.includes('preloaded')) return;
        if (msg.type() === 'error' && t.includes('404')) return;
        console.log(`[${msg.type()}] ${t}`);
    });
    page.on('pageerror', err => {
        console.log('[pageerror] ' + err.message);
        errors.push(err.message);
    });

    console.log(`Testing full canvas flow on port ${PORT} (WebKit)...\n`);
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle', timeout: 20000 });

    // Dismiss driver.js
    await page.evaluate(() => {
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        if (window.driverObj) { try { window.driverObj.destroy(); } catch(e) {} }
        document.body.classList.remove('driver-active');
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // 1. Select "Olly Market Taxonomy" project (id=1)
    await page.evaluate(() => selectProject(1, 'Olly Market Taxonomy'));
    await page.waitForTimeout(2000);
    console.log('1. Selected project: Olly Market Taxonomy');

    // 2. Switch to Canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);
    console.log('2. Canvas tab active');

    // 3. Click "New Canvas" button (actual button click, not programmatic)
    console.log('3. Clicking NEW CANVAS button...');
    await page.click('button:has-text("New Canvas")');
    await page.waitForTimeout(1500);

    // Check if prompt dialog appeared
    const dialogState = await page.evaluate(() => ({
        promptDisplay: document.getElementById('promptSheet')?.style?.display,
        promptVisible: document.getElementById('promptSheet')?.classList?.contains('visible'),
        promptTitle: document.getElementById('promptSheetTitle')?.textContent,
    }));
    console.log('   Dialog state:', JSON.stringify(dialogState));
    await page.screenshot({ path: 'test-evidence/canvas-flow-1-dialog.png' });

    if (!dialogState.promptVisible) {
        console.log('FAIL: Dialog did not appear!');
        await browser.close();
        process.exit(1);
    }
    console.log('   Dialog appeared correctly');

    // 4. Type canvas name and submit
    await page.fill('#promptSheetInput', 'My First Canvas');
    await page.click('#promptSheetConfirm');
    console.log('4. Submitted canvas name: "My First Canvas"');

    // 5. Wait for Excalidraw to load
    let excalidrawLoaded = false;
    for (let i = 0; i < 20; i++) {
        await page.waitForTimeout(1000);
        excalidrawLoaded = await page.evaluate(() => {
            const root = document.getElementById('excalidrawRoot');
            return !!(root && root.querySelector('.excalidraw'));
        });
        if (excalidrawLoaded) {
            console.log(`5. Excalidraw loaded after ${i + 1}s`);
            break;
        }
    }
    if (!excalidrawLoaded) {
        console.log('5. FAIL: Excalidraw did not load (timeout)');
        await page.screenshot({ path: 'test-evidence/canvas-flow-2-timeout.png' });
        await browser.close();
        process.exit(1);
    }

    await page.screenshot({ path: 'test-evidence/canvas-flow-2-excalidraw.png' });

    // 6. Test company drag-drop
    console.log('6. Testing company drag-drop...');
    const companyDropped = await page.evaluate(() => {
        // Simulate dropping a company by calling the function directly
        const companies = _canvasCompanies || [];
        if (companies.length === 0) return { error: 'no companies loaded' };

        const company = companies[0];
        // Create a mock drop event data
        const wrapper = document.getElementById('excalidrawRoot');
        if (!wrapper || !window._excalidrawAPI) return { error: 'excalidraw not ready' };

        // Use the internal function to create company elements
        if (typeof _createCompanyElements === 'function') {
            const elements = _createCompanyElements(company, 200, 200);
            if (elements && elements.length > 0) {
                const existing = window._excalidrawAPI.getSceneElements();
                window._excalidrawAPI.updateScene({ elements: [...existing, ...elements] });
                return { success: true, company: company.name, elementCount: elements.length };
            }
        }
        return { error: '_createCompanyElements not available' };
    });
    console.log('   Company drop result:', JSON.stringify(companyDropped));

    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'test-evidence/canvas-flow-3-company.png' });

    // 7. Verify canvas select shows the new canvas
    const selectState = await page.evaluate(() => ({
        value: document.getElementById('canvasSelect')?.value,
        text: document.getElementById('canvasSelect')?.selectedOptions?.[0]?.text,
    }));
    console.log('7. Canvas select:', JSON.stringify(selectState));

    // 8. Check Excalidraw API and toolbar
    const excalidrawState = await page.evaluate(() => ({
        apiAvailable: !!window._excalidrawAPI,
        hasToolbar: document.querySelector('.excalidraw') !== null,
        elementCount: window._excalidrawAPI ? window._excalidrawAPI.getSceneElements().length : 0,
    }));
    console.log('8. Excalidraw state:', JSON.stringify(excalidrawState));

    // Summary
    console.log('\n=== RESULTS ===');
    const allPass = dialogState.promptVisible && excalidrawLoaded &&
                    excalidrawState.apiAvailable && excalidrawState.hasToolbar;
    console.log(allPass ? 'ALL CHECKS PASSED' : 'SOME CHECKS FAILED');

    if (errors.length) {
        console.log('\nPage errors:');
        errors.slice(0, 5).forEach(e => console.log('  - ' + e.substring(0, 200)));
    }

    // Clean up: delete the test canvas
    const canvasId = selectState.value;
    if (canvasId) {
        await page.evaluate(async (id) => {
            await safeFetch(`/api/canvases/${id}`, { method: 'DELETE' });
        }, parseInt(canvasId));
        console.log('\nCleaned up test canvas id:', canvasId);
    }

    await browser.close();
    process.exit(allPass ? 0 : 1);
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
