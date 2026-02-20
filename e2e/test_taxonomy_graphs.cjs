/**
 * Taxonomy Graph Views test script
 * Tests: Tree View, Graph View, Knowledge Graph, Analytics Dashboard
 * Run: node e2e/test_taxonomy_graphs.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const BASE = 'http://127.0.0.1:5001';

const results = [];

function record(name, pass, details) {
    results.push({ name, pass, details });
    const tag = pass ? 'PASS' : 'FAIL';
    console.log(`  [${tag}] ${name}: ${details}`);
}

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    // Collect console errors
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') {
            consoleErrors.push(msg.text());
        }
    });

    // ── Step 1: Load homepage ──────────────────────────────────
    console.log('1. Loading homepage...');
    await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // ── Step 2: Dismiss driver.js tour ─────────────────────────
    console.log('2. Dismissing onboarding tour...');
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') {
            driverObj.destroy();
        }
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // ── Step 3: Get CSRF token ─────────────────────────────────
    console.log('3. Getting CSRF token...');
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
    if (!csrf) {
        console.log('   ERROR: No CSRF token found. Aborting.');
        await browser.close();
        process.exit(1);
    }
    console.log('   CSRF token obtained:', csrf.substring(0, 20) + '...');

    // ── Step 4: Create test project ────────────────────────────
    console.log('4. Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Taxonomy Test ' + Date.now(),
                purpose: 'Test',
                seed_categories: 'Digital Health\nInsurTech\nHealthcare AI'
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
            console.log('   ERROR: No projects available. Aborting.');
            await browser.close();
            process.exit(1);
        }
    }
    console.log('   Project ID:', pid);

    // ── Step 5: Add 5 test companies ───────────────────────────
    console.log('5. Adding 5 test companies...');
    const companies = [
        { name: 'Oscar Health', url: 'https://oscar-test.com', hq_city: 'New York', hq_country: 'US', geography: 'US' },
        { name: 'Babylon', url: 'https://babylon-test.com', hq_city: 'London', hq_country: 'UK', geography: 'UK' },
        { name: 'Ada Health', url: 'https://ada-test.com', hq_city: 'Berlin', hq_country: 'DE', geography: 'Germany' },
        { name: 'Doctolib', url: 'https://doctolib-test.com', hq_city: 'Paris', hq_country: 'FR', geography: 'France' },
        { name: 'Veeva', url: 'https://veeva-test.com', hq_city: 'San Francisco', hq_country: 'US', geography: 'US' },
    ];

    for (const c of companies) {
        const resp = await page.evaluate(async (args) => {
            const r = await fetch('/api/companies/add', {
                method: 'POST',
                headers: { 'X-CSRF-Token': args.token, 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: args.pid, ...args.company })
            });
            return { status: r.status, body: await r.json().catch(() => null) };
        }, { token: csrf, pid, company: c });
        console.log(`   Added ${c.name}: status=${resp.status}`);
    }

    // ── Step 6: Select project ─────────────────────────────────
    console.log('6. Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);

    // ── Step 7: Dismiss tour again ─────────────────────────────
    console.log('7. Dismissing tour again...');
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // ── Step 8: Switch to taxonomy tab ─────────────────────────
    console.log('8. Switching to taxonomy tab...');
    await page.evaluate(() => showTab('taxonomy'));
    await page.waitForTimeout(2000);

    // Dismiss tour again
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // ── Step 9: Collapse Analytics Dashboard ───────────────────
    console.log('9. Collapsing analytics dashboard...');
    await page.evaluate(() => {
        const body = document.getElementById('analyticsSection');
        if (body && !body.classList.contains('collapsed')) {
            toggleSection('analyticsSection');
        }
    });
    await page.waitForTimeout(500);

    // ════════════════════════════════════════════════════════════
    // TEST A — Tree View
    // ════════════════════════════════════════════════════════════
    console.log('\n=== TEST A: Tree View ===');
    await page.evaluate(() => switchTaxonomyView('tree'));
    await page.waitForTimeout(2000);

    await page.screenshot({ path: DIR + '/feature_taxonomy_tree.png', fullPage: false });
    console.log('   Screenshot saved: feature_taxonomy_tree.png');

    const treeInfo = await page.evaluate(() => {
        const tree = document.getElementById('taxonomyTree');
        if (!tree) return { exists: false };
        return {
            exists: true,
            htmlLength: tree.innerHTML.length,
            childCount: tree.children.length,
            textSnippet: tree.innerText.substring(0, 200),
            visible: tree.offsetWidth > 0 && tree.offsetHeight > 0,
            width: tree.offsetWidth,
            height: tree.offsetHeight,
        };
    });
    console.log('   Tree info:', JSON.stringify(treeInfo));

    if (treeInfo.exists && treeInfo.htmlLength > 50 && treeInfo.visible) {
        record('TEST A: Tree View', true,
            `Tree rendered with ${treeInfo.htmlLength} chars HTML, ${treeInfo.childCount} children, ${treeInfo.width}x${treeInfo.height}px`);
    } else {
        record('TEST A: Tree View', false,
            `Tree exists=${treeInfo.exists}, htmlLength=${treeInfo.htmlLength}, visible=${treeInfo.visible}`);
    }

    // ════════════════════════════════════════════════════════════
    // TEST B — Graph View
    // ════════════════════════════════════════════════════════════
    console.log('\n=== TEST B: Graph View ===');
    consoleErrors.length = 0; // reset to capture graph-specific errors

    await page.evaluate(() => switchTaxonomyView('graph'));
    await page.waitForTimeout(8000);

    await page.screenshot({ path: DIR + '/feature_taxonomy_graph.png', fullPage: false });
    console.log('   Screenshot saved: feature_taxonomy_graph.png');

    const graphCanvases = await page.locator('#taxonomyGraph canvas').count();
    const graphInfo = await page.evaluate(() => {
        const el = document.getElementById('taxonomyGraph');
        if (!el) return { exists: false };
        return {
            exists: true,
            hidden: el.classList.contains('hidden'),
            display: getComputedStyle(el).display,
            width: el.offsetWidth,
            height: el.offsetHeight,
            canvasCount: el.querySelectorAll('canvas').length,
            childCount: el.children.length,
            htmlLength: el.innerHTML.length,
        };
    });
    console.log('   Graph container:', JSON.stringify(graphInfo));
    console.log('   Canvas elements:', graphCanvases);

    if (consoleErrors.length > 0) {
        console.log('   Console errors during graph render:');
        consoleErrors.forEach(e => console.log('     - ' + e));
    } else {
        console.log('   No console errors during graph render.');
    }

    if (graphInfo.exists && graphCanvases > 0 && graphInfo.width > 100 && graphInfo.height > 100) {
        record('TEST B: Graph View', true,
            `${graphCanvases} canvas(es), container ${graphInfo.width}x${graphInfo.height}px, ${consoleErrors.length} errors`);
    } else {
        record('TEST B: Graph View', false,
            `canvases=${graphCanvases}, exists=${graphInfo.exists}, w=${graphInfo.width}, h=${graphInfo.height}, errors=${consoleErrors.length}`);
    }

    // ════════════════════════════════════════════════════════════
    // TEST C — Knowledge Graph
    // ════════════════════════════════════════════════════════════
    console.log('\n=== TEST C: Knowledge Graph ===');
    consoleErrors.length = 0;

    await page.evaluate(() => switchTaxonomyView('knowledge'));
    await page.waitForTimeout(8000);

    await page.screenshot({ path: DIR + '/feature_taxonomy_kg.png', fullPage: false });
    console.log('   Screenshot saved: feature_taxonomy_kg.png');

    const kgCanvases = await page.locator('#knowledgeGraph canvas').count();
    const kgInfo = await page.evaluate(() => {
        const kgEl = document.getElementById('knowledgeGraph');
        const kgCanvas = document.getElementById('kgCanvas');
        const filters = document.querySelectorAll('#knowledgeGraph input[type="checkbox"], #kgFilters input[type="checkbox"], .kg-filter input[type="checkbox"]');

        return {
            containerExists: !!kgEl,
            containerHidden: kgEl ? kgEl.classList.contains('hidden') : 'N/A',
            containerWidth: kgEl ? kgEl.offsetWidth : 0,
            containerHeight: kgEl ? kgEl.offsetHeight : 0,
            canvasExists: !!kgCanvas,
            canvasWidth: kgCanvas ? kgCanvas.offsetWidth : 0,
            canvasHeight: kgCanvas ? kgCanvas.offsetHeight : 0,
            canvasCount: kgEl ? kgEl.querySelectorAll('canvas').length : 0,
            filterCheckboxCount: filters.length,
            htmlLength: kgEl ? kgEl.innerHTML.length : 0,
        };
    });
    console.log('   KG container:', JSON.stringify(kgInfo));
    console.log('   Canvas elements:', kgCanvases);

    if (consoleErrors.length > 0) {
        console.log('   Console errors during KG render:');
        consoleErrors.forEach(e => console.log('     - ' + e));
    } else {
        console.log('   No console errors during KG render.');
    }

    if (kgInfo.containerExists && kgCanvases > 0 && kgInfo.containerWidth > 100 && kgInfo.containerHeight > 100) {
        record('TEST C: Knowledge Graph', true,
            `${kgCanvases} canvas(es), container ${kgInfo.containerWidth}x${kgInfo.containerHeight}px, ` +
            `kgCanvas ${kgInfo.canvasWidth}x${kgInfo.canvasHeight}px, ${kgInfo.filterCheckboxCount} filter checkboxes`);
    } else {
        record('TEST C: Knowledge Graph', false,
            `canvases=${kgCanvases}, exists=${kgInfo.containerExists}, ` +
            `w=${kgInfo.containerWidth}, h=${kgInfo.containerHeight}, errors=${consoleErrors.length}`);
    }

    // ════════════════════════════════════════════════════════════
    // TEST D — Analytics Dashboard
    // ════════════════════════════════════════════════════════════
    console.log('\n=== TEST D: Analytics Dashboard ===');
    consoleErrors.length = 0;

    // Switch back to tree view first
    await page.evaluate(() => switchTaxonomyView('tree'));
    await page.waitForTimeout(1000);

    // Un-collapse analytics section
    await page.evaluate(() => {
        const body = document.getElementById('analyticsSection');
        if (body && body.classList.contains('collapsed')) {
            toggleSection('analyticsSection');
        }
    });
    await page.waitForTimeout(2000);

    await page.screenshot({ path: DIR + '/feature_taxonomy_dashboard.png', fullPage: false });
    console.log('   Screenshot saved: feature_taxonomy_dashboard.png');

    const dashInfo = await page.evaluate(() => {
        const matrix = document.getElementById('matrixContainer');
        const fundingChart = document.getElementById('chartFundingStage');
        const confChart = document.getElementById('chartConfidence');
        const analyticsSection = document.getElementById('analyticsSection');

        return {
            sectionExists: !!analyticsSection,
            sectionCollapsed: analyticsSection ? analyticsSection.classList.contains('collapsed') : 'N/A',
            matrixExists: !!matrix,
            matrixHasContent: matrix ? matrix.innerHTML.length > 20 : false,
            matrixContentLength: matrix ? matrix.innerHTML.length : 0,
            matrixWidth: matrix ? matrix.offsetWidth : 0,
            matrixHeight: matrix ? matrix.offsetHeight : 0,
            fundingChartExists: !!fundingChart,
            fundingChartTag: fundingChart ? fundingChart.tagName : 'N/A',
            fundingChartWidth: fundingChart ? fundingChart.offsetWidth : 0,
            confChartExists: !!confChart,
            confChartTag: confChart ? confChart.tagName : 'N/A',
            confChartWidth: confChart ? confChart.offsetWidth : 0,
        };
    });
    console.log('   Dashboard info:', JSON.stringify(dashInfo));

    const dashPass = dashInfo.sectionExists &&
                     !dashInfo.sectionCollapsed &&
                     dashInfo.matrixExists &&
                     dashInfo.matrixHasContent &&
                     dashInfo.fundingChartExists &&
                     dashInfo.confChartExists;

    if (dashPass) {
        record('TEST D: Analytics Dashboard', true,
            `Matrix ${dashInfo.matrixWidth}x${dashInfo.matrixHeight}px (${dashInfo.matrixContentLength} chars), ` +
            `fundingChart=${dashInfo.fundingChartExists} (${dashInfo.fundingChartWidth}px), ` +
            `confChart=${dashInfo.confChartExists} (${dashInfo.confChartWidth}px)`);
    } else {
        record('TEST D: Analytics Dashboard', false,
            `section=${dashInfo.sectionExists}, collapsed=${dashInfo.sectionCollapsed}, ` +
            `matrix=${dashInfo.matrixExists} (content=${dashInfo.matrixHasContent}), ` +
            `funding=${dashInfo.fundingChartExists}, conf=${dashInfo.confChartExists}`);
    }

    // ════════════════════════════════════════════════════════════
    // Summary
    // ════════════════════════════════════════════════════════════
    console.log('\n' + '='.repeat(60));
    console.log('RESULTS SUMMARY');
    console.log('='.repeat(60));
    let passed = 0;
    let failed = 0;
    for (const r of results) {
        const tag = r.pass ? 'PASS' : 'FAIL';
        if (r.pass) passed++; else failed++;
        console.log(`  [${tag}] ${r.name}`);
        console.log(`         ${r.details}`);
    }
    console.log('='.repeat(60));
    console.log(`Total: ${passed} passed, ${failed} failed out of ${results.length} tests`);
    console.log('='.repeat(60));

    console.log('\nScreenshots saved to test-evidence/:');
    console.log('  - feature_taxonomy_tree.png');
    console.log('  - feature_taxonomy_graph.png');
    console.log('  - feature_taxonomy_kg.png');
    console.log('  - feature_taxonomy_dashboard.png');

    await browser.close();
    process.exit(failed > 0 ? 1 : 0);
})();
