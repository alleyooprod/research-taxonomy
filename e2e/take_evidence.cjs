/**
 * Direct evidence capture script — bypasses Playwright test framework overhead.
 * Run: node e2e/take_evidence.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    const consoleLogs = [];
    page.on('console', msg => consoleLogs.push(msg.type() + ': ' + msg.text()));

    console.log('1. Loading homepage...');
    await page.goto('http://127.0.0.1:5001/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // Dismiss driver.js onboarding tour if present
    console.log('2. Dismissing onboarding tour...');
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') {
            driverObj.destroy();
        }
        // Remove overlay elements
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Verify CDN libs loaded
    const libs = await page.evaluate(() => ({
        cytoscape: typeof cytoscape,
        fabric: typeof fabric,
        L: typeof L,
        selectProject: typeof selectProject,
        showTab: typeof showTab,
    }));
    console.log('3. CDN libraries loaded:', JSON.stringify(libs));

    // Get CSRF
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });

    // Create a test project
    console.log('4. Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Evidence Test ' + Date.now(),
                purpose: 'Screenshot evidence',
                seed_categories: 'Digital Health\nInsurTech\nHealthcare AI\nTelemedicine'
            })
        });
        return r.json();
    }, csrf);
    console.log('   Project response:', JSON.stringify(projResp));

    let pid = projResp.id || projResp.project_id;

    // If project creation failed, use an existing project
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
            return;
        }
    }

    // Add test companies
    console.log('5. Adding test companies...');
    const companies = [
        { name: 'Oscar Health', url: 'https://oscar.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'Digital Health' },
        { name: 'Babylon Health', url: 'https://babylon.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom', category_name: 'Telemedicine' },
        { name: 'Lemonade', url: 'https://lemonade.com', hq_city: 'New York', hq_country: 'US', geography: 'US', category_name: 'InsurTech' },
        { name: 'Veeva Systems', url: 'https://veeva.com', hq_city: 'San Francisco', hq_country: 'US', geography: 'USA', category_name: 'Healthcare AI' },
        { name: 'Ada Health', url: 'https://ada.com', hq_city: 'Berlin', hq_country: 'Germany', geography: 'Germany', category_name: 'Healthcare AI' },
        { name: 'Doctolib', url: 'https://doctolib.com', hq_city: 'Paris', hq_country: 'France', geography: 'France', category_name: 'Telemedicine' },
        { name: 'Niva Bupa', url: 'https://nivabupa.com', hq_city: 'Mumbai', hq_country: 'India', geography: 'India', category_name: 'InsurTech' },
        { name: 'Ping An Health', url: 'https://pingan.com', hq_city: 'Shanghai', hq_country: 'China', geography: 'China', category_name: 'Digital Health' },
    ];

    for (const c of companies) {
        await page.evaluate(async (args) => {
            await fetch('/api/companies/add', {
                method: 'POST',
                headers: { 'X-CSRF-Token': args.token, 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: args.pid, ...args.company })
            });
        }, { token: csrf, pid, company: c });
    }
    console.log('   Added', companies.length, 'companies');

    // Select the project
    console.log('6. Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);

    // Dismiss tour again (selectProject may trigger it)
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    await page.screenshot({ path: DIR + '/project_selected.png' });
    console.log('   Saved: project_selected.png');

    // === BUG #1: Graph View ===
    console.log('\n=== BUG #1: Graph View ===');
    await page.evaluate(() => showTab('taxonomy'));
    await page.waitForTimeout(2000);
    // Dismiss tour again
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Collapse the Analytics Dashboard so graph views are visible below
    await page.evaluate(() => {
        const body = document.getElementById('analyticsSection');
        if (body && !body.classList.contains('collapsed')) {
            toggleSection('analyticsSection');
        }
    });
    await page.waitForTimeout(500);

    // Call switchTaxonomyView directly (more reliable than button click through overlays)
    const graphDebug = await page.evaluate(() => {
        const hasFunc = typeof switchTaxonomyView === 'function';
        const hasCytoscape = typeof cytoscape === 'function';
        const pid = typeof currentProjectId !== 'undefined' ? currentProjectId : 'UNDEFINED';
        const container = document.getElementById('taxonomyGraph');
        if (hasFunc) switchTaxonomyView('graph');
        return { hasFunc, hasCytoscape, pid, containerExists: !!container };
    });
    console.log('   Debug:', JSON.stringify(graphDebug));
    // Wait for cytoscape to render (CDN load + API fetch + layout)
    await page.waitForTimeout(8000);
    await page.screenshot({ path: DIR + '/bug1_graph_view.png' });
    const graphCanvases = await page.locator('#taxonomyGraph canvas').count();
    const graphVisible = await page.evaluate(() => {
        const el = document.getElementById('taxonomyGraph');
        return el ? { hidden: el.classList.contains('hidden'), w: el.offsetWidth, h: el.offsetHeight } : null;
    });
    console.log('   Canvas elements in graph:', graphCanvases);
    console.log('   Graph container:', JSON.stringify(graphVisible));
    console.log('   Saved: bug1_graph_view.png');

    // === BUG #2: Knowledge Graph ===
    console.log('\n=== BUG #2: Knowledge Graph ===');
    // Call switchTaxonomyView directly
    await page.evaluate(() => switchTaxonomyView('knowledge'));
    // Wait for cytoscape to render (API fetch + layout)
    await page.waitForTimeout(8000);
    await page.screenshot({ path: DIR + '/bug2_knowledge_graph.png' });
    const kgCanvases = await page.locator('#knowledgeGraph canvas').count();
    const kgVisible = await page.evaluate(() => {
        const kgEl = document.getElementById('knowledgeGraph');
        const kgCanvas = document.getElementById('kgCanvas');
        return {
            kgHidden: kgEl ? kgEl.classList.contains('hidden') : 'missing',
            kgW: kgEl ? kgEl.offsetWidth : 0,
            kgH: kgEl ? kgEl.offsetHeight : 0,
            canvasW: kgCanvas ? kgCanvas.offsetWidth : 0,
            canvasH: kgCanvas ? kgCanvas.offsetHeight : 0,
        };
    });
    console.log('   Canvas elements in KG:', kgCanvases);
    console.log('   KG container:', JSON.stringify(kgVisible));
    console.log('   Saved: bug2_knowledge_graph.png');

    // === BUG #3: Geographic Map ===
    console.log('\n=== BUG #3: Geographic Map ===');
    await page.evaluate(() => showTab('map'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);
    // Call switchMapView directly
    const mapDebug = await page.evaluate(() => {
        const hasFunc = typeof switchMapView === 'function';
        const hasLeaflet = typeof L === 'object';
        if (hasFunc) switchMapView('geo');
        return { hasFunc, hasLeaflet };
    });
    console.log('   Debug:', JSON.stringify(mapDebug));
    // Wait for Leaflet to render tiles + markers
    await page.waitForTimeout(8000);
    await page.screenshot({ path: DIR + '/bug3_geographic_map.png' });
    const tiles = await page.locator('.leaflet-tile').count();
    // Check multiple marker selectors (marker-cluster, divIcon, standard markers)
    const markerInfo = await page.evaluate(() => {
        const squares = document.querySelectorAll('.geo-marker-square').length;
        const divIcons = document.querySelectorAll('.leaflet-marker-icon').length;
        const clusters = document.querySelectorAll('.marker-cluster').length;
        const svgMarkers = document.querySelectorAll('.leaflet-marker-pane *').length;
        return { squares, divIcons, clusters, svgMarkers };
    });
    console.log('   Tiles:', tiles, '| Markers:', JSON.stringify(markerInfo));
    console.log('   Saved: bug3_geographic_map.png');

    // === BUG #4: Canvas ===
    console.log('\n=== BUG #4: Canvas ===');
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(4000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.screenshot({ path: DIR + '/bug4_canvas_tab.png' });
    const canvasFuncs = await page.evaluate(() => ({
        loadCanvasList: typeof loadCanvasList === 'function',
        createNewCanvas: typeof createNewCanvas === 'function',
        initFabricCanvas: typeof initFabricCanvas === 'function',
        fabricLoaded: typeof fabric !== 'undefined',
    }));
    console.log('   Canvas functions:', JSON.stringify(canvasFuncs));
    console.log('   Saved: bug4_canvas_tab.png');

    // Create a new canvas
    page.on('dialog', async dialog => {
        await dialog.accept('Evidence Test Canvas');
    });
    await page.evaluate(() => {
        const btn = document.querySelector('button[onclick*="createNewCanvas"]');
        if (btn) btn.click();
        else if (typeof createNewCanvas === 'function') createNewCanvas();
    });
    await page.waitForTimeout(4000);
    await page.screenshot({ path: DIR + '/bug4_canvas_created.png' });
    const fabricVisible = await page.evaluate(() => {
        const el = document.getElementById('fabricCanvas');
        return el ? (el.offsetWidth > 0) : false;
    });
    console.log('   Fabric canvas visible:', fabricVisible);
    console.log('   Saved: bug4_canvas_created.png');

    // === BUG #5: AI Discovery ===
    console.log('\n=== BUG #5: AI Discovery ===');
    await page.evaluate(() => showTab('process'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.screenshot({ path: DIR + '/bug5_ai_discovery.png' });
    const discoveryUI = await page.evaluate(() => {
        const query = document.getElementById('discoveryQuery');
        const btn = document.getElementById('discoveryBtn');
        return {
            queryInput: !!query,
            discoverBtn: !!btn,
            queryVisible: query ? query.offsetWidth > 0 : false,
            btnVisible: btn ? btn.offsetWidth > 0 : false,
        };
    });
    console.log('   Discovery UI:', JSON.stringify(discoveryUI));
    console.log('   Saved: bug5_ai_discovery.png');

    // === Overview screenshots of all tabs ===
    console.log('\n=== Overview Screenshots ===');
    const tabs = ['companies', 'taxonomy', 'map', 'canvas', 'process', 'settings'];
    for (const tab of tabs) {
        await page.evaluate((t) => showTab(t), tab);
        await page.waitForTimeout(1500);
        await page.evaluate(() => {
            if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
            document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
        });
        await page.screenshot({ path: DIR + '/overview_' + tab + '.png' });
        console.log('   Saved: overview_' + tab + '.png');
    }

    // Print any console errors
    const errors = consoleLogs.filter(l => l.startsWith('error:'));
    console.log('\n=== Console Errors (' + errors.length + ') ===');
    if (errors.length > 0) {
        errors.forEach(e => console.log('  ', e));
    } else {
        console.log('   None detected');
    }

    await browser.close();
    console.log('\nEvidence capture complete. Screenshots saved to ' + DIR + '/');
})().catch(e => {
    console.error('FATAL:', e.message);
    process.exit(1);
});
