const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();

    const consoleErrors = [];
    page.on('console', msg => {
        const t = msg.type();
        if (t === 'error' || t === 'warning') consoleErrors.push(t + ': ' + msg.text());
    });
    page.on('pageerror', err => consoleErrors.push('PAGE: ' + err.message));

    await page.goto('http://127.0.0.1:5099/', { waitUntil: 'networkidle', timeout: 15000 });

    // Navigate to canvas tab
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);

    // Check that excalidrawRoot exists
    const rootExists = await page.evaluate(() => { return !!document.getElementById('excalidrawRoot'); });
    console.log('ExcalidrawRoot exists:', rootExists);

    // Check that the old drawing toolbar is gone
    const drawToolbar = await page.evaluate(() => { return !!document.getElementById('canvasDrawToolbar'); });
    console.log('Old drawing toolbar removed:', !drawToolbar);

    // Check that the fabricCanvas element is gone
    const fabricCanvas = await page.evaluate(() => { return !!document.getElementById('fabricCanvas'); });
    console.log('Old fabricCanvas removed:', !fabricCanvas);

    // Check that import map loaded
    const importMapOk = await page.evaluate(() => {
        return document.querySelectorAll('script[type="importmap"]').length > 0;
    });
    console.log('Import map present:', importMapOk);

    // Try to dynamically import React via the import map
    const reactLoadable = await page.evaluate(async () => {
        try {
            const React = await import('react');
            return !!React.default;
        } catch (e) {
            return 'ERROR: ' + e.message;
        }
    });
    console.log('React loadable via import map:', reactLoadable);

    // Try loading Excalidraw
    const excalidrawLoadable = await page.evaluate(async () => {
        try {
            const mod = await import('https://esm.sh/@excalidraw/excalidraw@0.18.0/dist/dev/index.js?external=react,react-dom');
            return !!mod.Excalidraw;
        } catch (e) {
            return 'ERROR: ' + e.message;
        }
    });
    console.log('Excalidraw loadable:', excalidrawLoadable);

    // Take screenshot
    await page.screenshot({ path: 'test-evidence/excalidraw-canvas-tab.png', fullPage: false });
    console.log('Screenshot saved to test-evidence/excalidraw-canvas-tab.png');

    if (consoleErrors.length) {
        console.log('\nConsole issues:');
        consoleErrors.slice(0, 10).forEach(e => console.log('  ' + e.substring(0, 200)));
    }

    await browser.close();
})().catch(err => { console.error('Test failed:', err.message); process.exit(1); });
