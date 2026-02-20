/**
 * Test diagram generation using WebKit (matches pywebview engine)
 * against the RUNNING desktop app on port 5001.
 */
const { webkit } = require('playwright');
const PORT = process.argv[2] || 5001;

(async () => {
    const browser = await webkit.launch({ headless: false });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

    page.on('pageerror', err => console.log('[pageerror]', err.message));

    console.log(`Testing diagram generation on RUNNING app (WebKit, port ${PORT})...\n`);
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle', timeout: 20000 });

    // Dismiss driver.js
    await page.evaluate(() => {
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        if (window.driverObj) { try { window.driverObj.destroy(); } catch(e) {} }
        document.body.classList.remove('driver-active');
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Select project
    await page.evaluate(() => selectProject(1, 'Olly Market Taxonomy'));
    await page.waitForTimeout(2000);
    console.log('1. Project: Olly Market Taxonomy');

    // Canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);

    // Create canvas via prompt dialog (testing the full user flow)
    console.log('2. Clicking NEW CANVAS button...');
    await page.click('button:has-text("New Canvas")');
    await page.waitForTimeout(1500);

    // Check dialog appeared
    const dialogUp = await page.evaluate(() =>
        document.getElementById('promptSheet')?.classList?.contains('visible'));
    console.log('   Prompt dialog visible:', dialogUp);

    if (!dialogUp) {
        console.log('FAIL: dialog did not appear');
        await page.screenshot({ path: 'test-evidence/webkit-diagram-fail.png' });
        await browser.close();
        process.exit(1);
    }

    // Type name and submit
    await page.fill('#promptSheetInput', 'Diagram Test');
    await page.click('#promptSheetConfirm');
    console.log('3. Created canvas "Diagram Test"');

    // Wait for Excalidraw
    for (let i = 0; i < 15; i++) {
        await page.waitForTimeout(1000);
        const ready = await page.evaluate(() =>
            !!(document.querySelector('.excalidraw') && window._excalidrawAPI));
        if (ready) { console.log(`4. Excalidraw loaded (${i+1}s)`); break; }
    }

    // Open diagram panel
    await page.evaluate(() => openDiagramPanel());
    await page.waitForTimeout(500);

    // Use Enterprise Tech Stack template
    await page.evaluate(() => useDiagramTemplate('tech_stack'));
    console.log('5. Applied "Enterprise Tech Stack" template');

    // Select 3 categories for a meaningful diagram
    await page.evaluate(() => {
        toggleAllDiagramCategories(false);
        const cbs = document.querySelectorAll('#diagramCategoryList input[type="checkbox"]');
        for (let i = 0; i < Math.min(3, cbs.length); i++) cbs[i].checked = true;
    });
    const cats = await page.evaluate(() => {
        const checked = document.querySelectorAll('#diagramCategoryList input:checked');
        return Array.from(checked).map(cb => cb.parentElement.textContent.trim());
    });
    console.log('6. Categories:', cats);

    // Screenshot before generation
    await page.screenshot({ path: 'test-evidence/webkit-diagram-before.png' });

    // Generate
    console.log('7. Generating diagram...');
    const t0 = Date.now();
    await page.evaluate(() => startDiagramGeneration());

    let done = false, error = null;
    for (let i = 0; i < 80; i++) {
        await page.waitForTimeout(3000);
        const elapsed = Math.round((Date.now() - t0) / 1000);

        const st = await page.evaluate(() => ({
            statusHidden: document.getElementById('diagramStatus').classList.contains('hidden'),
            errorHidden: document.getElementById('diagramError').classList.contains('hidden'),
            errorText: document.getElementById('diagramError').textContent,
            postHidden: document.getElementById('diagramPostActions').classList.contains('hidden'),
            elements: window._excalidrawAPI ? window._excalidrawAPI.getSceneElements().length : 0,
        }));

        if (!st.errorHidden) { error = st.errorText; console.log(`   ERROR at ${elapsed}s: ${error}`); break; }
        if (!st.postHidden || st.elements > 0) {
            done = true;
            console.log(`   Done in ${elapsed}s — ${st.elements} elements on canvas`);
            break;
        }
        if (i % 5 === 0) console.log(`   Waiting... ${elapsed}s`);
    }

    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'test-evidence/webkit-diagram-after.png' });
    console.log('8. Screenshot saved');

    if (done) {
        const els = await page.evaluate(() => {
            const all = window._excalidrawAPI.getSceneElements();
            const types = {};
            all.forEach(e => { types[e.type] = (types[e.type] || 0) + 1; });
            const texts = all.filter(e => e.type === 'text').map(e => e.text.substring(0, 60));
            return { total: all.length, types, sampleTexts: texts.slice(0, 8) };
        });
        console.log('9. Elements:', JSON.stringify(els.types));
        console.log('   Sample text:', els.sampleTexts);
    }

    // Cleanup
    const cid = await page.evaluate(() => _currentCanvasId);
    if (cid) {
        await page.evaluate(async (id) => {
            await safeFetch(`/api/canvases/${id}`, { method: 'DELETE' });
        }, cid);
        console.log('\nCleaned up canvas');
    }

    console.log('\n=== RESULT ===');
    console.log(done ? 'DIAGRAM GENERATION SUCCEEDED (WebKit)' : `FAILED: ${error || 'timeout'}`);

    await browser.close();
    process.exit(done ? 0 : 1);
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
