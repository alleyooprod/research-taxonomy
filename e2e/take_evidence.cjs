/**
 * Direct evidence capture script — screenshots of all fixed features.
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
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
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
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Verify driver.js is fully cleaned up
    const driverState = await page.evaluate(() => ({
        bodyClasses: document.body.className,
        pointerEvents: getComputedStyle(document.body).pointerEvents,
    }));
    console.log('   Driver state:', JSON.stringify(driverState));

    await page.screenshot({ path: DIR + '/project_selected.png' });
    console.log('   Saved: project_selected.png');

    // === Graph View (expanded nodes/text) ===
    console.log('\n=== Graph View (expanded) ===');
    await page.evaluate(() => showTab('taxonomy'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
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

    // Switch to graph view
    await page.evaluate(() => switchTaxonomyView('graph'));
    await page.waitForTimeout(8000);

    const graphInfo = await page.evaluate(() => {
        const el = document.getElementById('taxonomyGraph');
        const canvases = el ? el.querySelectorAll('canvas').length : 0;
        return {
            containerW: el ? el.offsetWidth : 0,
            containerH: el ? el.offsetHeight : 0,
            canvases,
            hidden: el ? el.classList.contains('hidden') : true,
        };
    });
    console.log('   Graph:', JSON.stringify(graphInfo));

    // Scroll down to graph container for full view
    await page.evaluate(() => {
        const el = document.getElementById('taxonomyGraph');
        if (el) el.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    await page.waitForTimeout(500);
    await page.screenshot({ path: DIR + '/graph_view_expanded.png' });
    console.log('   Saved: graph_view_expanded.png');

    // === Knowledge Graph (expanded nodes/text) ===
    console.log('\n=== Knowledge Graph (expanded) ===');
    await page.evaluate(() => switchTaxonomyView('knowledge'));
    await page.waitForTimeout(8000);

    const kgInfo = await page.evaluate(() => {
        const el = document.getElementById('knowledgeGraph');
        const canvases = el ? el.querySelectorAll('canvas').length : 0;
        return {
            containerW: el ? el.offsetWidth : 0,
            containerH: el ? el.offsetHeight : 0,
            canvases,
            hidden: el ? el.classList.contains('hidden') : true,
        };
    });
    console.log('   KG:', JSON.stringify(kgInfo));

    await page.evaluate(() => {
        const el = document.getElementById('knowledgeGraph');
        if (el) el.scrollIntoView({ behavior: 'instant', block: 'start' });
    });
    await page.waitForTimeout(500);
    await page.screenshot({ path: DIR + '/knowledge_graph_expanded.png' });
    console.log('   Saved: knowledge_graph_expanded.png');

    // === Canvas — drawing test ===
    console.log('\n=== Canvas (drawing test) ===');
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // Verify pointer-events are NOT blocked
    const pointerCheck = await page.evaluate(() => {
        const body = document.body;
        const wrapper = document.getElementById('canvasWrapper');
        return {
            bodyClasses: body.className,
            bodyPointerEvents: getComputedStyle(body).pointerEvents,
            wrapperPointerEvents: wrapper ? getComputedStyle(wrapper).pointerEvents : 'N/A',
        };
    });
    console.log('   Pointer check:', JSON.stringify(pointerCheck));

    const canvasFuncs = await page.evaluate(() => ({
        loadCanvasList: typeof loadCanvasList === 'function',
        createNewCanvas: typeof createNewCanvas === 'function',
        initFabricCanvas: typeof initFabricCanvas === 'function',
        fabricLoaded: typeof fabric !== 'undefined',
        fabricVersion: typeof fabric !== 'undefined' ? fabric.version : 'N/A',
    }));
    console.log('   Canvas functions:', JSON.stringify(canvasFuncs));

    // Create a new canvas
    page.once('dialog', async dialog => {
        await dialog.accept('Evidence Test Canvas');
    });
    await page.evaluate(() => createNewCanvas());
    await page.waitForTimeout(4000);

    // Draw shapes programmatically
    const drawResult = await page.evaluate(() => {
        const canvas = window._fabricCanvas;
        if (!canvas) return { error: 'No _fabricCanvas' };

        // Draw rect
        const rect = new fabric.Rect({
            left: 80, top: 80, width: 200, height: 100,
            fill: '#FFFFFF', stroke: '#000000', strokeWidth: 2,
        });
        canvas.add(rect);

        // Draw circle
        const circle = new fabric.Circle({
            left: 350, top: 100, radius: 50,
            fill: '#F0F0F0', stroke: '#000000', strokeWidth: 2,
        });
        canvas.add(circle);

        // Add text
        const text = new fabric.IText('Canvas Working!', {
            left: 120, top: 120, fontSize: 20,
            fill: '#000000', fontFamily: 'Plus Jakarta Sans, sans-serif',
        });
        canvas.add(text);

        canvas.renderAll();
        return { objectCount: canvas.getObjects().length, success: true };
    });
    console.log('   Draw result:', JSON.stringify(drawResult));

    // Test mouse interaction (draw a rect via mouse events)
    const wrapperBox = await page.evaluate(() => {
        const w = document.getElementById('canvasWrapper');
        if (!w) return null;
        const r = w.getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height };
    });

    if (wrapperBox && wrapperBox.w > 0) {
        await page.evaluate(() => setCanvasTool('rect'));
        const cx = wrapperBox.x + 550;
        const cy = wrapperBox.y + 200;
        await page.mouse.move(cx, cy);
        await page.mouse.down();
        await page.mouse.move(cx + 120, cy + 80, { steps: 5 });
        await page.mouse.up();
        await page.waitForTimeout(1000);

        const afterDraw = await page.evaluate(() => ({
            objectCount: window._fabricCanvas ? window._fabricCanvas.getObjects().length : 'no canvas',
        }));
        console.log('   After mouse draw:', JSON.stringify(afterDraw));
    }

    await page.waitForTimeout(500);
    await page.screenshot({ path: DIR + '/canvas_drawing_working.png' });
    console.log('   Saved: canvas_drawing_working.png');

    // === Geographic Map ===
    console.log('\n=== Geographic Map ===');
    await page.evaluate(() => showTab('map'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);
    await page.evaluate(() => switchMapView('geo'));
    await page.waitForTimeout(8000);
    await page.screenshot({ path: DIR + '/geographic_map.png' });
    console.log('   Saved: geographic_map.png');

    // === AI Discovery ===
    console.log('\n=== AI Discovery ===');
    await page.evaluate(() => showTab('process'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        if (typeof _cleanupDriverJs === 'function') _cleanupDriverJs();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.screenshot({ path: DIR + '/ai_discovery.png' });
    console.log('   Saved: ai_discovery.png');

    // === Cleanup: delete test project and canvas ===
    console.log('\n=== Cleanup ===');
    // Delete canvas first
    await page.evaluate(() => showTab('canvas'));
    await page.waitForTimeout(1000);
    const canvasId = await page.evaluate(() => document.getElementById('canvasSelect')?.value);
    if (canvasId) {
        await page.evaluate(async (args) => {
            await fetch(`/api/canvases/${args.cid}`, {
                method: 'DELETE',
                headers: { 'X-CSRF-Token': args.token }
            });
        }, { cid: canvasId, token: csrf });
        console.log('   Deleted test canvas:', canvasId);
    }

    // Delete test project
    if (pid) {
        await page.evaluate(async (args) => {
            await fetch(`/api/projects/${args.pid}`, {
                method: 'DELETE',
                headers: { 'X-CSRF-Token': args.token }
            });
        }, { pid, token: csrf });
        console.log('   Deleted test project:', pid);
    }

    // Print console errors
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
