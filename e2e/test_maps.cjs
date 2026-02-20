/**
 * Map Tab Test Script — Tests Market Map, Auto-Layout, Geographic Map, and Heatmap.
 * Run: node e2e/test_maps.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const results = [];

function report(name, pass, detail) {
    const status = pass ? 'PASS' : 'FAIL';
    results.push({ name, status, detail });
    console.log(`   [${status}] ${name}${detail ? ' — ' + detail : ''}`);
}

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    const consoleLogs = [];
    page.on('console', msg => consoleLogs.push(msg.type() + ': ' + msg.text()));

    // ——————————————————————————————————————
    // SETUP
    // ——————————————————————————————————————
    console.log('1. Loading homepage...');
    await page.goto('http://127.0.0.1:5001/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    console.log('2. Dismissing onboarding tour...');
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Get CSRF token
    console.log('3. Getting CSRF token...');
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
    if (!csrf) {
        console.log('   WARNING: No CSRF token found');
    } else {
        console.log('   CSRF token obtained');
    }

    // Create test project
    console.log('4. Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Map Test ' + Date.now(),
                purpose: 'Test',
                seed_categories: 'Digital Health\nInsurTech'
            })
        });
        return r.json();
    }, csrf);
    console.log('   Project response:', JSON.stringify(projResp));

    let pid = projResp.id || projResp.project_id;
    if (!pid) {
        console.log('   Project creation returned no ID, listing existing...');
        const projects = await page.evaluate(async (token) => {
            const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
            return r.json();
        }, csrf);
        if (projects && projects.length > 0) {
            pid = projects[0].id;
            console.log('   Using existing project:', pid, projects[0].name);
        } else {
            console.log('   ERROR: No projects available');
            await browser.close();
            process.exit(1);
        }
    }

    // Add 6 test companies with diverse geographies
    console.log('5. Adding 6 test companies...');
    const companies = [
        { name: 'Oscar Health', url: 'https://oscar-map.com', hq_city: 'New York', hq_country: 'US', geography: 'United States' },
        { name: 'Babylon', url: 'https://babylon-map.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom' },
        { name: 'Ada Health', url: 'https://ada-map.com', hq_city: 'Berlin', hq_country: 'Germany', geography: 'Germany' },
        { name: 'Doctolib', url: 'https://doctolib-map.com', hq_city: 'Paris', hq_country: 'France', geography: 'France' },
        { name: 'Niva Bupa', url: 'https://nivabupa-map.com', hq_city: 'Mumbai', hq_country: 'India', geography: 'India' },
        { name: 'Ping An', url: 'https://pingan-map.com', hq_city: 'Shanghai', hq_country: 'China', geography: 'China' },
    ];

    for (const c of companies) {
        const resp = await page.evaluate(async (args) => {
            const r = await fetch('/api/companies/add', {
                method: 'POST',
                headers: { 'X-CSRF-Token': args.token, 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: args.pid, ...args.company })
            });
            return { status: r.status, ok: r.ok };
        }, { token: csrf, pid, company: c });
        console.log(`   Added ${c.name} (${c.hq_city}, ${c.hq_country}): ${resp.ok ? 'OK' : 'FAILED ' + resp.status}`);
    }

    // Select project
    console.log('6. Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);

    // Dismiss tour again (selectProject may trigger it)
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // ——————————————————————————————————————
    // TEST A: Market Map
    // ——————————————————————————————————————
    console.log('\n=== TEST A: Market Map ===');
    await page.evaluate(() => showTab('map'));
    await page.waitForTimeout(2000);

    // Dismiss tour
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    await page.evaluate(() => switchMapView('market'));
    await page.waitForTimeout(3000);

    await page.screenshot({ path: DIR + '/feature_map_market.png' });
    console.log('   Saved: feature_map_market.png');

    const marketInfo = await page.evaluate(() => {
        const el = document.getElementById('marketMap');
        if (!el) return { exists: false };
        const html = el.innerHTML;
        const columns = el.querySelectorAll('.map-column').length;
        const tiles = el.querySelectorAll('.map-tile').length;
        const svgs = el.querySelectorAll('svg').length;
        const canvases = el.querySelectorAll('canvas').length;
        return {
            exists: true,
            hidden: el.classList.contains('hidden'),
            contentLength: html.length,
            columns,
            tiles,
            svgs,
            canvases,
            width: el.offsetWidth,
            height: el.offsetHeight,
        };
    });
    console.log('   Market Map info:', JSON.stringify(marketInfo));

    report('Market Map container exists', marketInfo.exists);
    report('Market Map not hidden', marketInfo.exists && !marketInfo.hidden);
    report('Market Map has content', marketInfo.contentLength > 0, `innerHTML length: ${marketInfo.contentLength}`);
    report('Market Map has columns', marketInfo.columns > 0, `${marketInfo.columns} columns`);
    report('Market Map has company tiles', marketInfo.tiles > 0, `${marketInfo.tiles} tiles`);

    // ——————————————————————————————————————
    // TEST B: Auto-Layout
    // ——————————————————————————————————————
    console.log('\n=== TEST B: Auto-Layout ===');
    await page.evaluate(() => switchMapView('auto'));
    await page.waitForTimeout(3000);

    await page.screenshot({ path: DIR + '/feature_map_autolayout.png' });
    console.log('   Saved: feature_map_autolayout.png');

    const autoInfo = await page.evaluate(() => {
        const el = document.getElementById('autoLayoutMap');
        if (!el) return { exists: false };
        const html = el.innerHTML;
        const canvases = el.querySelectorAll('canvas').length;
        return {
            exists: true,
            hidden: el.classList.contains('hidden'),
            contentLength: html.length,
            canvases,
            width: el.offsetWidth,
            height: el.offsetHeight,
        };
    });
    console.log('   Auto-Layout info:', JSON.stringify(autoInfo));

    report('Auto-Layout container exists', autoInfo.exists);
    report('Auto-Layout not hidden', autoInfo.exists && !autoInfo.hidden);
    report('Auto-Layout has content', autoInfo.contentLength > 0, `innerHTML length: ${autoInfo.contentLength}`);
    report('Auto-Layout has canvas (Cytoscape)', autoInfo.canvases > 0, `${autoInfo.canvases} canvas elements`);

    // ——————————————————————————————————————
    // TEST C: Geographic Map
    // ——————————————————————————————————————
    console.log('\n=== TEST C: Geographic Map ===');
    await page.evaluate(() => switchMapView('geo'));
    // Wait longer for Leaflet CDN + tile loading
    await page.waitForTimeout(8000);

    await page.screenshot({ path: DIR + '/feature_map_geo.png' });
    console.log('   Saved: feature_map_geo.png');

    const geoInfo = await page.evaluate(() => {
        const el = document.getElementById('geoMap');
        if (!el) return { exists: false };
        const tiles = document.querySelectorAll('.leaflet-tile').length;
        const markerIcons = document.querySelectorAll('.leaflet-marker-icon').length;
        const geoSquares = document.querySelectorAll('.geo-marker-square').length;
        const clusters = document.querySelectorAll('.marker-cluster').length;
        const markerPane = document.querySelector('.leaflet-marker-pane');
        const markerPaneChildren = markerPane ? markerPane.children.length : 0;
        const zoomIn = document.querySelector('.leaflet-control-zoom-in');
        const zoomOut = document.querySelector('.leaflet-control-zoom-out');
        const attribution = document.querySelector('.leaflet-control-attribution');
        return {
            exists: true,
            hidden: el.classList.contains('hidden'),
            width: el.offsetWidth,
            height: el.offsetHeight,
            tiles,
            markerIcons,
            geoSquares,
            clusters,
            markerPaneChildren,
            hasZoomIn: !!zoomIn,
            hasZoomOut: !!zoomOut,
            hasAttribution: !!attribution,
            attributionText: attribution ? attribution.textContent.substring(0, 60) : '',
        };
    });
    console.log('   Geographic Map info:', JSON.stringify(geoInfo));
    console.log(`   Tiles: ${geoInfo.tiles}`);
    console.log(`   Marker icons (.leaflet-marker-icon): ${geoInfo.markerIcons}`);
    console.log(`   Geo squares (.geo-marker-square): ${geoInfo.geoSquares}`);
    console.log(`   Clusters (.marker-cluster): ${geoInfo.clusters}`);
    console.log(`   Marker pane children: ${geoInfo.markerPaneChildren}`);

    report('Geographic Map container exists', geoInfo.exists);
    report('Geographic Map not hidden', geoInfo.exists && !geoInfo.hidden);
    report('Leaflet tiles loaded', geoInfo.tiles > 0, `${geoInfo.tiles} tiles`);
    report('Leaflet marker icons present', geoInfo.markerIcons > 0, `${geoInfo.markerIcons} markers`);
    report('Geo marker squares present', geoInfo.geoSquares > 0, `${geoInfo.geoSquares} squares`);
    report('Marker clusters present', geoInfo.clusters > 0, `${geoInfo.clusters} clusters`);
    report('Marker pane has children', geoInfo.markerPaneChildren > 0, `${geoInfo.markerPaneChildren} children`);
    report('Zoom controls exist', geoInfo.hasZoomIn && geoInfo.hasZoomOut);
    report('Leaflet attribution exists', geoInfo.hasAttribution, geoInfo.attributionText);

    // ——————————————————————————————————————
    // TEST D: Heatmap Toggle
    // ——————————————————————————————————————
    console.log('\n=== TEST D: Heatmap Toggle ===');

    const heatmapBtnExists = await page.evaluate(() => {
        const btn = document.getElementById('heatmapToggleBtn');
        return !!btn;
    });
    console.log('   Heatmap button exists:', heatmapBtnExists);

    if (heatmapBtnExists) {
        // Click the heatmap toggle button
        await page.evaluate(() => {
            const btn = document.getElementById('heatmapToggleBtn');
            if (btn) btn.click();
        });
        await page.waitForTimeout(3000);

        await page.screenshot({ path: DIR + '/feature_map_heatmap.png' });
        console.log('   Saved: feature_map_heatmap.png');

        const heatInfo = await page.evaluate(() => {
            const btn = document.getElementById('heatmapToggleBtn');
            const isActive = btn ? btn.classList.contains('active') : false;
            // Heatmap layer renders as a canvas in the leaflet overlay pane
            const overlayPane = document.querySelector('.leaflet-overlay-pane');
            const overlayCanvases = overlayPane ? overlayPane.querySelectorAll('canvas').length : 0;
            // Check if marker cluster is hidden (heatmap removes it)
            const markerIcons = document.querySelectorAll('.leaflet-marker-icon').length;
            return {
                btnActive: isActive,
                overlayCanvases,
                markerIconsVisible: markerIcons,
            };
        });
        console.log('   Heatmap info:', JSON.stringify(heatInfo));

        report('Heatmap button activated', heatInfo.btnActive);
        report('Heatmap overlay canvas present', heatInfo.overlayCanvases > 0, `${heatInfo.overlayCanvases} overlay canvases`);
        report('Markers hidden during heatmap', heatInfo.markerIconsVisible === 0, `${heatInfo.markerIconsVisible} markers still visible`);
    } else {
        // Try calling toggleGeoHeatmap directly
        console.log('   Heatmap button not found, trying toggleGeoHeatmap()...');
        const toggleResult = await page.evaluate(() => {
            if (typeof toggleGeoHeatmap === 'function') {
                toggleGeoHeatmap();
                return 'called';
            }
            return 'function not found';
        });
        console.log('   toggleGeoHeatmap():', toggleResult);
        await page.waitForTimeout(3000);

        await page.screenshot({ path: DIR + '/feature_map_heatmap.png' });
        console.log('   Saved: feature_map_heatmap.png');

        const heatInfo = await page.evaluate(() => {
            const overlayPane = document.querySelector('.leaflet-overlay-pane');
            const overlayCanvases = overlayPane ? overlayPane.querySelectorAll('canvas').length : 0;
            return { overlayCanvases };
        });
        report('Heatmap toggle function exists', toggleResult === 'called');
        report('Heatmap overlay canvas present', heatInfo.overlayCanvases > 0, `${heatInfo.overlayCanvases} overlay canvases`);
    }

    // ——————————————————————————————————————
    // SUMMARY
    // ——————————————————————————————————————
    console.log('\n' + '='.repeat(50));
    console.log('TEST SUMMARY');
    console.log('='.repeat(50));

    const passed = results.filter(r => r.status === 'PASS').length;
    const failed = results.filter(r => r.status === 'FAIL').length;
    const total = results.length;

    results.forEach(r => {
        console.log(`  [${r.status}] ${r.name}${r.detail ? ' — ' + r.detail : ''}`);
    });

    console.log('');
    console.log(`  Total: ${total} | Passed: ${passed} | Failed: ${failed}`);
    console.log('='.repeat(50));

    // Print console errors
    const errors = consoleLogs.filter(l => l.startsWith('error:'));
    if (errors.length > 0) {
        console.log(`\n  Console errors (${errors.length}):`);
        errors.slice(0, 10).forEach(e => console.log('    ' + e));
    }

    console.log('\nScreenshots saved to ' + DIR + '/');
    await browser.close();
    process.exit(failed > 0 ? 1 : 0);
})().catch(e => {
    console.error('FATAL:', e.message);
    process.exit(1);
});
