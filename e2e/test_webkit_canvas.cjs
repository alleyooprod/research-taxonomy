/**
 * Test canvas creation using WebKit engine (same as pywebview on macOS)
 * against the RUNNING app on port 5001
 */
const { webkit } = require('playwright');
const PORT = process.argv[2] || 5001;

(async () => {
    const browser = await webkit.launch({ headless: false });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

    const errors = [];
    page.on('console', msg => {
        const t = msg.text();
        if (t.includes('clearbit') || t.includes('ERR_NAME')) return;
        console.log(`[${msg.type()}] ${t}`);
    });
    page.on('pageerror', err => {
        console.log('[pageerror] ' + err.message);
        errors.push(err.message);
    });

    console.log(`Connecting to running app on port ${PORT} using WEBKIT...`);
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle', timeout: 20000 });

    // Dismiss driver.js
    await page.evaluate(() => {
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        if (window.driverObj) { try { window.driverObj.destroy(); } catch(e) {} }
        document.body.classList.remove('driver-active');
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Select first project
    const projSelected = await page.evaluate(() => {
        const cards = document.querySelectorAll('.project-card:not(.new-project-card)');
        if (cards.length === 0) return false;
        const onclick = cards[0].getAttribute('onclick') || '';
        const match = onclick.match(/selectProject\((\d+),\s*'([^']+)'\)/);
        if (match) { selectProject(parseInt(match[1]), match[2]); return match[2]; }
        return false;
    });
    console.log('Project selected:', projSelected);
    await page.waitForTimeout(2000);

    // Switch to canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);

    // Check the state before clicking New Canvas
    const preState = await page.evaluate(() => ({
        hasPromptSheet: !!document.getElementById('promptSheet'),
        promptSheetDisplay: document.getElementById('promptSheet')?.style?.display,
        typeofCreateNew: typeof createNewCanvas,
        typeofShowPrompt: typeof _showPrompt,
        currentProjectId: typeof currentProjectId !== 'undefined' ? currentProjectId : 'UNDEFINED',
    }));
    console.log('Pre-state:', JSON.stringify(preState, null, 2));

    // Call createNewCanvas — don't await, it opens a dialog
    console.log('\nCalling createNewCanvas()...');
    page.evaluate(() => createNewCanvas()).catch(e => console.log('createNewCanvas error:', e.message));

    await page.waitForTimeout(2000);

    // Check if prompt dialog appeared
    const afterState = await page.evaluate(() => ({
        promptDisplay: document.getElementById('promptSheet')?.style?.display,
        promptVisible: document.getElementById('promptSheet')?.classList?.contains('visible'),
        promptTitle: document.getElementById('promptSheetTitle')?.textContent,
        inputVisible: !!document.getElementById('promptSheetInput'),
    }));
    console.log('After createNewCanvas:', JSON.stringify(afterState, null, 2));

    await page.screenshot({ path: 'test-evidence/webkit-canvas-test.png' });
    console.log('Screenshot saved to test-evidence/webkit-canvas-test.png');

    if (afterState.promptVisible) {
        // Type a name and click Create
        console.log('\nDialog is visible! Typing name and submitting...');
        await page.fill('#promptSheetInput', 'WebKit Test Canvas');
        await page.click('#promptSheetConfirm');
        await page.waitForTimeout(5000);

        // Check if canvas was created
        const created = await page.evaluate(() => ({
            selectValue: document.getElementById('canvasSelect')?.value,
            selectOptions: document.getElementById('canvasSelect')?.options?.length,
            wrapperHidden: document.getElementById('canvasWrapper')?.classList?.contains('hidden'),
            hasExcalidraw: !!document.querySelector('.excalidraw'),
        }));
        console.log('After creation:', JSON.stringify(created, null, 2));
        await page.screenshot({ path: 'test-evidence/webkit-canvas-created.png' });
        console.log('Created screenshot saved');
    } else {
        console.log('\nDIALOG DID NOT APPEAR! Investigating...');
        // Check for errors
        const debugInfo = await page.evaluate(() => {
            try {
                const overlay = document.getElementById('promptSheet');
                return {
                    overlayExists: !!overlay,
                    overlayParent: overlay?.parentElement?.tagName,
                    overlayZIndex: overlay ? getComputedStyle(overlay).zIndex : null,
                    overlayPosition: overlay ? getComputedStyle(overlay).position : null,
                    bodyOverflow: getComputedStyle(document.body).overflow,
                    bodyPointerEvents: getComputedStyle(document.body).pointerEvents,
                };
            } catch(e) {
                return { error: e.message };
            }
        });
        console.log('Debug info:', JSON.stringify(debugInfo, null, 2));
    }

    if (errors.length) {
        console.log('\nPage errors:', errors);
    }

    await browser.close();
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
