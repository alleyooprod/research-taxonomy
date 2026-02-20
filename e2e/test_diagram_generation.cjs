/**
 * End-to-end test: AI Diagram generation
 * 1. Create canvas
 * 2. Open AI Diagram panel
 * 3. Use Market Landscape template
 * 4. Select 2 categories (small for speed)
 * 5. Generate diagram
 * 6. Verify diagram elements appear on canvas
 */
const { chromium } = require('playwright');
const PORT = process.argv[2] || 5001;

(async () => {
    const browser = await chromium.launch({ headless: false });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

    page.on('pageerror', err => console.log('[pageerror]', err.message));
    page.on('console', msg => {
        if (msg.type() === 'error' && !msg.text().includes('404') && !msg.text().includes('ERR_NAME'))
            console.log(`[console.error] ${msg.text().substring(0, 200)}`);
    });

    console.log(`Testing diagram generation on port ${PORT}...\n`);
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle', timeout: 20000 });

    // Dismiss driver.js
    await page.evaluate(() => {
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        if (window.driverObj) { try { window.driverObj.destroy(); } catch(e) {} }
        document.body.classList.remove('driver-active');
    });
    await page.waitForTimeout(500);

    // Select project
    await page.evaluate(() => selectProject(1, 'Olly Market Taxonomy'));
    await page.waitForTimeout(2000);
    console.log('1. Project selected');

    // Canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);

    // Create canvas
    const canvasId = await page.evaluate(async () => {
        const res = await safeFetch('/api/canvases', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: 1, title: 'Diagram Test Canvas' }),
        });
        const data = await res.json();
        if (data.id) {
            await loadCanvasList();
            document.getElementById('canvasSelect').value = data.id;
            loadCanvasFromSelect();
        }
        return data.id;
    });
    console.log('2. Canvas created:', canvasId);

    // Wait for Excalidraw
    for (let i = 0; i < 15; i++) {
        await page.waitForTimeout(1000);
        const ready = await page.evaluate(() => !!(document.querySelector('.excalidraw') && window._excalidrawAPI));
        if (ready) { console.log(`3. Excalidraw ready after ${i+1}s`); break; }
    }

    // Open diagram panel
    await page.evaluate(() => openDiagramPanel());
    await page.waitForTimeout(500);

    // Use Market Landscape template
    await page.evaluate(() => useDiagramTemplate('market_landscape'));
    console.log('4. Market Landscape template loaded');

    // Select only first 2 categories (faster generation)
    await page.evaluate(() => {
        toggleAllDiagramCategories(false);
        const checkboxes = document.querySelectorAll('#diagramCategoryList input[type="checkbox"]');
        if (checkboxes.length >= 1) checkboxes[0].checked = true;
        if (checkboxes.length >= 2) checkboxes[1].checked = true;
    });

    const selectedCats = await page.evaluate(() => {
        const checked = document.querySelectorAll('#diagramCategoryList input[type="checkbox"]:checked');
        return Array.from(checked).map(cb => cb.parentElement.textContent.trim());
    });
    console.log('5. Selected categories:', selectedCats);

    // Take pre-generation screenshot
    await page.screenshot({ path: 'test-evidence/diagram-pre-generate.png' });

    // Start generation
    console.log('6. Starting diagram generation...');
    const startTime = Date.now();
    await page.evaluate(() => startDiagramGeneration());

    // Poll for completion (up to 3 minutes)
    let diagramDone = false;
    let diagramError = null;
    for (let i = 0; i < 60; i++) {
        await page.waitForTimeout(3000);
        const elapsed = Math.round((Date.now() - startTime) / 1000);

        const state = await page.evaluate(() => ({
            statusHidden: document.getElementById('diagramStatus').classList.contains('hidden'),
            errorHidden: document.getElementById('diagramError').classList.contains('hidden'),
            errorText: document.getElementById('diagramError').textContent,
            postActionsHidden: document.getElementById('diagramPostActions').classList.contains('hidden'),
            elementCount: window._excalidrawAPI ? window._excalidrawAPI.getSceneElements().length : 0,
        }));

        if (!state.errorHidden) {
            diagramError = state.errorText;
            console.log(`   Error after ${elapsed}s: ${diagramError}`);
            break;
        }

        if (!state.postActionsHidden || state.elementCount > 0) {
            diagramDone = true;
            console.log(`   Diagram generated after ${elapsed}s — ${state.elementCount} elements`);
            break;
        }

        if (i % 5 === 0) {
            console.log(`   Waiting... ${elapsed}s`);
        }
    }

    await page.waitForTimeout(1000);
    await page.screenshot({ path: 'test-evidence/diagram-post-generate.png' });
    console.log('7. Screenshot saved');

    // Check element details
    if (diagramDone) {
        const elements = await page.evaluate(() => {
            const els = window._excalidrawAPI.getSceneElements();
            const types = {};
            els.forEach(e => { types[e.type] = (types[e.type] || 0) + 1; });
            return { total: els.length, types };
        });
        console.log('8. Elements:', JSON.stringify(elements));
    }

    // Summary
    console.log('\n=== RESULTS ===');
    if (diagramDone) {
        console.log('DIAGRAM GENERATION SUCCEEDED');
    } else if (diagramError) {
        console.log('DIAGRAM GENERATION FAILED:', diagramError);
    } else {
        console.log('DIAGRAM GENERATION TIMED OUT');
    }

    // Cleanup
    if (canvasId) {
        await page.evaluate(async (id) => {
            await safeFetch(`/api/canvases/${id}`, { method: 'DELETE' });
        }, canvasId);
        console.log('Cleaned up test canvas');
    }

    await browser.close();
    process.exit(diagramDone ? 0 : 1);
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
