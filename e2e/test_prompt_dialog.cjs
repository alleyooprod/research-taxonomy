/**
 * Diagnose: does the prompt sheet dialog appear when clicking NEW CANVAS?
 */
const { chromium } = require('playwright');
const PORT = process.argv[2] || 5001;

(async () => {
    const browser = await chromium.launch({ headless: false });
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

    page.on('console', msg => {
        const t = msg.text();
        if (t.includes('clearbit') || t.includes('ERR_NAME')) return;
        console.log(`[${msg.type()}] ${t}`);
    });
    page.on('pageerror', err => console.log('[pageerror]', err.message));

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
    await page.evaluate(() => {
        const cards = document.querySelectorAll('.project-card:not(.new-project-card)');
        if (cards.length) {
            const onclick = cards[0].getAttribute('onclick') || '';
            const match = onclick.match(/selectProject\((\d+),\s*'([^']+)'\)/);
            if (match) selectProject(parseInt(match[1]), match[2]);
        }
    });
    await page.waitForTimeout(2000);

    // Canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);

    // Check if elements exist
    const diag = await page.evaluate(() => ({
        hasPromptSheet: !!document.getElementById('promptSheet'),
        hasConfirmSheet: !!document.getElementById('confirmSheet'),
        promptSheetDisplay: document.getElementById('promptSheet')?.style?.display,
        promptHTML: document.getElementById('promptSheet')?.outerHTML?.substring(0, 300) || 'NOT FOUND',
        typeofShowPrompt: typeof _showPrompt,
        typeofCreateNewCanvas: typeof createNewCanvas,
    }));
    console.log('\nDiagnostic:', JSON.stringify(diag, null, 2));

    // Call createNewCanvas and observe
    console.log('\n--- Calling createNewCanvas() ---');
    // Don't await — it blocks waiting for user input on the prompt dialog
    page.evaluate(() => createNewCanvas());

    await page.waitForTimeout(1500);

    // Check if prompt sheet is now visible
    const afterState = await page.evaluate(() => ({
        promptDisplay: document.getElementById('promptSheet')?.style?.display,
        promptVisible: document.getElementById('promptSheet')?.classList?.contains('visible'),
        promptInputValue: document.getElementById('promptSheetInput')?.value,
    }));
    console.log('After createNewCanvas:', JSON.stringify(afterState, null, 2));

    await page.screenshot({ path: 'test-evidence/prompt-dialog-test.png' });
    console.log('Screenshot saved');

    await browser.close();
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
