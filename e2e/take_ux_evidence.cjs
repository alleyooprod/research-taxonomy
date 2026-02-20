/**
 * UX update evidence capture — header, tab indicator, tooltips, settings, taxonomy.
 */
const { chromium } = require('playwright');
const DIR = 'test-evidence';

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
    await page.goto('http://127.0.0.1:5001/', { waitUntil: 'networkidle', timeout: 15000 });
    await page.waitForTimeout(2000);

    // Dismiss tour
    await page.evaluate(() => {
        if (window.driverObj) driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Screenshot homepage
    await page.screenshot({ path: DIR + '/ux-final-homepage.png' });
    console.log('Saved: ux-final-homepage.png');

    // Select first project
    const hasProjects = await page.evaluate(() => {
        const cards = document.querySelectorAll('.project-card:not(.project-card-new)');
        return cards.length;
    });
    if (hasProjects === 0) { console.log('No projects'); await browser.close(); return; }

    await page.evaluate(() => {
        const cards = document.querySelectorAll('.project-card:not(.project-card-new)');
        if (cards.length > 0) cards[0].click();
    });
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj) driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Verify tab indicator
    const indicator = await page.evaluate(() => {
        const ind = document.querySelector('.tab-indicator');
        return ind ? { left: ind.style.left, width: ind.style.width } : null;
    });
    console.log('Tab indicator (Companies):', JSON.stringify(indicator));

    // Verify tooltips
    const tooltips = await page.evaluate(() => {
        let count = 0;
        document.querySelectorAll('button[aria-label]').forEach(b => { if (b._tippy) count++; });
        return count;
    });
    console.log('Tippy instances:', tooltips);

    // Screenshot: Companies tab with header, indicator, tooltips
    await page.screenshot({ path: DIR + '/ux-final-companies.png' });
    console.log('Saved: ux-final-companies.png');

    // Hover over notification bell to show tooltip
    const bellBtn = await page.$('button.notification-bell[aria-label]');
    if (bellBtn) {
        try {
            await bellBtn.hover({ timeout: 3000 });
            await page.waitForTimeout(500);
            await page.screenshot({ path: DIR + '/ux-final-tooltip.png' });
            console.log('Saved: ux-final-tooltip.png');
        } catch(e) { console.log('Tooltip hover skipped (button not visible)'); }
    }

    // Switch to Taxonomy tab — verify indicator moves
    await page.evaluate(() => showTab('taxonomy'));
    await page.waitForTimeout(1500);
    const ind2 = await page.evaluate(() => {
        const ind = document.querySelector('.tab-indicator');
        return ind ? { left: ind.style.left, width: ind.style.width } : null;
    });
    console.log('Tab indicator (Taxonomy):', JSON.stringify(ind2));
    await page.screenshot({ path: DIR + '/ux-final-taxonomy.png' });
    console.log('Saved: ux-final-taxonomy.png');

    // Switch to Settings tab
    await page.evaluate(() => showTab('settings'));
    await page.waitForTimeout(1000);
    await page.screenshot({ path: DIR + '/ux-final-settings.png' });
    console.log('Saved: ux-final-settings.png');

    // Switch to Map tab
    await page.evaluate(() => showTab('map'));
    await page.waitForTimeout(1000);
    await page.evaluate(() => switchMapView('geo'));
    await page.waitForTimeout(5000);
    await page.screenshot({ path: DIR + '/ux-final-map.png' });
    console.log('Saved: ux-final-map.png');

    // Check for console errors
    const errors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });

    console.log('\nAll evidence captured.');
    await browser.close();
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
