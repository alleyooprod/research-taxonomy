/**
 * AI Discovery / Process tab end-to-end test script.
 * Tests discovery UI, input, URL processing, recent batches, discovery tab, and find similar.
 * Run: node e2e/test_ai_discovery.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const BASE = 'http://127.0.0.1:5001/';

const results = [];
function report(name, pass, detail) {
    results.push({ name, pass, detail });
    console.log(`  ${pass ? 'PASS' : 'FAIL'}: ${name} — ${detail}`);
}

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    const consoleLogs = [];
    const consoleErrors = [];
    page.on('console', msg => {
        const line = msg.type() + ': ' + msg.text();
        consoleLogs.push(line);
        if (msg.type() === 'error') consoleErrors.push(line);
    });

    // ── Step 1: Load page ──
    console.log('\n1. Loading homepage...');
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // ── Step 2: Dismiss driver.js tour ──
    console.log('2. Dismissing onboarding tour...');
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // ── Step 3: Get CSRF token ──
    console.log('3. Getting CSRF token...');
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
    console.log('   CSRF token:', csrf ? csrf.substring(0, 16) + '...' : 'MISSING');
    if (!csrf) {
        console.log('FATAL: No CSRF token found');
        await browser.close();
        process.exit(1);
    }

    // ── Step 4: Create test project ──
    console.log('4. Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'AI Discovery Test ' + Date.now(),
                purpose: 'E2E test for AI Discovery tab',
                seed_categories: 'Digital Health\nInsurTech'
            })
        });
        return r.json();
    }, csrf);

    let pid = projResp.id || projResp.project_id;
    if (!pid) {
        console.log('   Project creation failed, using existing...');
        const projects = await page.evaluate(async (token) => {
            const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
            return r.json();
        }, csrf);
        if (projects && projects.length > 0) {
            pid = projects[0].id;
            console.log('   Using existing project:', pid, projects[0].name);
        } else {
            console.log('FATAL: No projects available');
            await browser.close();
            process.exit(1);
        }
    } else {
        console.log('   Created project:', pid);
    }

    // ── Step 5: Add 2 companies with unique URLs ──
    console.log('5. Adding test companies...');
    const companies = [
        { name: 'TestCo Alpha', url: 'https://testco-alpha-' + Date.now() + '.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'Digital Health' },
        { name: 'TestCo Beta', url: 'https://testco-beta-' + Date.now() + '.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom', category_name: 'InsurTech' },
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
        console.log('   Added:', c.name, '— status:', resp.status);
    }

    // ── Step 6: Select project and dismiss tour ──
    console.log('6. Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    // ════════════════════════════════════════════════════════
    // TEST A — Discovery Tab UI
    // ════════════════════════════════════════════════════════
    console.log('\n═══ TEST A: Discovery Tab UI ═══');
    await page.evaluate(() => showTab('process'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    await page.screenshot({ path: DIR + '/feature_discovery_tab.png', fullPage: false });
    console.log('   Screenshot: feature_discovery_tab.png');

    const testA = await page.evaluate(() => {
        const query = document.getElementById('discoveryQuery');
        const btn = document.getElementById('discoveryBtn');
        const modelSelect = document.getElementById('discoveryModelSelect');
        const tabProcess = document.getElementById('tab-process');
        return {
            queryExists: !!query,
            queryVisible: query ? (query.offsetWidth > 0 && query.offsetHeight > 0) : false,
            btnExists: !!btn,
            btnVisible: btn ? (btn.offsetWidth > 0 && btn.offsetHeight > 0) : false,
            btnText: btn ? btn.textContent.trim() : '',
            modelSelectExists: !!modelSelect,
            modelSelectVisible: modelSelect ? (modelSelect.offsetWidth > 0) : false,
            tabVisible: tabProcess ? !tabProcess.classList.contains('hidden') : false,
        };
    });

    report('A1 - #discoveryQuery exists', testA.queryExists, testA.queryExists ? 'Input found' : 'Input NOT found');
    report('A2 - #discoveryQuery visible', testA.queryVisible, testA.queryVisible ? 'Input is visible' : 'Input is NOT visible');
    report('A3 - #discoveryBtn exists', testA.btnExists, testA.btnExists ? `Button found: "${testA.btnText}"` : 'Button NOT found');
    report('A4 - #discoveryBtn visible', testA.btnVisible, testA.btnVisible ? 'Button is visible' : 'Button is NOT visible');
    report('A5 - Model selector exists', testA.modelSelectExists, testA.modelSelectExists ? 'Dropdown found' : 'Dropdown NOT found');
    report('A6 - Process tab visible', testA.tabVisible, testA.tabVisible ? 'Tab content is showing' : 'Tab content hidden');

    // ════════════════════════════════════════════════════════
    // TEST B — Discovery Input
    // ════════════════════════════════════════════════════════
    console.log('\n═══ TEST B: Discovery Input ═══');
    const queryText = 'Digital health insurance companies';
    await page.fill('#discoveryQuery', queryText);
    await page.waitForTimeout(500);

    await page.screenshot({ path: DIR + '/feature_discovery_input.png', fullPage: false });
    console.log('   Screenshot: feature_discovery_input.png');

    const testB = await page.evaluate(() => {
        const query = document.getElementById('discoveryQuery');
        return {
            value: query ? query.value : '',
        };
    });

    report('B1 - Query input has value', testB.value === queryText,
        testB.value === queryText ? `Value matches: "${testB.value}"` : `Expected "${queryText}", got "${testB.value}"`);

    // ════════════════════════════════════════════════════════
    // TEST C — URL Processing Section
    // ════════════════════════════════════════════════════════
    console.log('\n═══ TEST C: URL Processing Section ═══');

    // Scroll down to reveal URL processing section
    await page.evaluate(() => {
        const tabProcess = document.getElementById('tab-process');
        if (tabProcess) tabProcess.scrollTop = tabProcess.scrollHeight;
    });
    await page.waitForTimeout(500);

    const testC = await page.evaluate(() => {
        const urlInput = document.getElementById('urlInput');
        const processHeading = [...document.querySelectorAll('#tab-process h3')].find(h => h.textContent.includes('Submit URLs'));
        return {
            urlInputExists: !!urlInput,
            urlInputVisible: urlInput ? (urlInput.offsetWidth > 0 && urlInput.offsetHeight > 0) : false,
            urlInputTag: urlInput ? urlInput.tagName : '',
            urlInputRows: urlInput ? urlInput.rows : 0,
            urlInputPlaceholder: urlInput ? urlInput.placeholder.substring(0, 60) : '',
            headingExists: !!processHeading,
            headingText: processHeading ? processHeading.textContent.trim() : '',
        };
    });

    await page.screenshot({ path: DIR + '/feature_discovery_urls.png', fullPage: false });
    console.log('   Screenshot: feature_discovery_urls.png');

    report('C1 - URL textarea (#urlInput) exists', testC.urlInputExists,
        testC.urlInputExists ? `Found <${testC.urlInputTag}> with ${testC.urlInputRows} rows` : 'Textarea NOT found');
    report('C2 - URL textarea visible', testC.urlInputVisible,
        testC.urlInputVisible ? 'Textarea is visible' : 'Textarea is NOT visible');
    report('C3 - URL section heading', testC.headingExists,
        testC.headingExists ? `Heading: "${testC.headingText}"` : 'Heading NOT found');
    report('C4 - URL textarea has placeholder', testC.urlInputPlaceholder.length > 0,
        testC.urlInputPlaceholder.length > 0 ? `Placeholder: "${testC.urlInputPlaceholder}..."` : 'No placeholder');

    // ════════════════════════════════════════════════════════
    // TEST D — Recent Batches
    // ════════════════════════════════════════════════════════
    console.log('\n═══ TEST D: Recent Batches ═══');

    const testD = await page.evaluate(() => {
        const batchList = document.getElementById('batchList');
        const batchHeading = [...document.querySelectorAll('#tab-process h3')].find(h => h.textContent.includes('Recent Batches'));
        const batchDetailView = document.getElementById('batchDetailView');
        return {
            batchListExists: !!batchList,
            batchListVisible: batchList ? (batchList.offsetWidth > 0) : false,
            batchListHTML: batchList ? batchList.innerHTML.substring(0, 200) : '',
            batchListChildCount: batchList ? batchList.children.length : 0,
            headingExists: !!batchHeading,
            headingText: batchHeading ? batchHeading.textContent.trim() : '',
            detailViewExists: !!batchDetailView,
        };
    });

    // Scroll to bottom to capture batch section
    await page.evaluate(() => {
        const tabProcess = document.getElementById('tab-process');
        if (tabProcess) tabProcess.scrollTop = tabProcess.scrollHeight;
    });
    await page.waitForTimeout(500);
    await page.screenshot({ path: DIR + '/feature_discovery_batches.png', fullPage: false });
    console.log('   Screenshot: feature_discovery_batches.png');

    report('D1 - #batchList exists', testD.batchListExists,
        testD.batchListExists ? 'Batch list container found' : 'Batch list NOT found');
    report('D2 - #batchList visible', testD.batchListVisible,
        testD.batchListVisible ? 'Batch list is visible' : 'Batch list NOT visible (may be empty but present)');
    report('D3 - Recent Batches heading', testD.headingExists,
        testD.headingExists ? `Heading: "${testD.headingText}"` : 'Heading NOT found');
    report('D4 - Batch detail view exists', testD.detailViewExists,
        testD.detailViewExists ? 'Detail view container found' : 'Detail view NOT found');
    if (testD.batchListChildCount > 0) {
        report('D5 - Batch list has items', true, `${testD.batchListChildCount} batch item(s) found`);
    } else {
        report('D5 - Batch list is empty (expected for new project)', true, 'No batches yet (expected)');
    }

    // ════════════════════════════════════════════════════════
    // TEST E — Discovery Tab (alternative name)
    // ════════════════════════════════════════════════════════
    console.log('\n═══ TEST E: Discovery Tab (alternative name) ═══');

    await page.evaluate(() => {
        try { showTab('discovery'); } catch(e) { /* may not exist */ }
    });
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    await page.screenshot({ path: DIR + '/feature_discovery_alt.png', fullPage: false });
    console.log('   Screenshot: feature_discovery_alt.png');

    const testE = await page.evaluate(() => {
        const tabDiscovery = document.getElementById('tab-discovery');
        const header = tabDiscovery ? tabDiscovery.querySelector('.discovery-header') : null;
        const contextSection = document.getElementById('discoveryContexts');
        const dimensionsSection = document.getElementById('discoveryDimensions');
        const landscapeSection = document.getElementById('discoveryLandscape');
        const gapSection = document.getElementById('discoveryGap');
        const historySection = document.getElementById('discoveryHistory');
        const tabBtn = document.getElementById('discoveryTabBtn');

        return {
            tabExists: !!tabDiscovery,
            tabVisible: tabDiscovery ? (!tabDiscovery.classList.contains('hidden') && tabDiscovery.offsetHeight > 0) : false,
            headerText: header ? header.textContent.trim().substring(0, 80) : '',
            contextSectionExists: !!contextSection,
            dimensionsSectionExists: !!dimensionsSection,
            landscapeSectionExists: !!landscapeSection,
            gapSectionExists: !!gapSection,
            historySectionExists: !!historySection,
            tabBtnExists: !!tabBtn,
            tabBtnHidden: tabBtn ? tabBtn.classList.contains('hidden') : 'N/A',
        };
    });

    report('E1 - #tab-discovery exists', testE.tabExists,
        testE.tabExists ? 'Discovery tab section found' : 'Discovery tab NOT found');
    report('E2 - Discovery tab visible', testE.tabVisible,
        testE.tabVisible ? 'Tab content is showing' : 'Tab content NOT visible (may be hidden)');
    report('E3 - Discovery header', testE.headerText.length > 0,
        testE.headerText.length > 0 ? `Header: "${testE.headerText}"` : 'No header found');
    report('E4 - Context Files section', testE.contextSectionExists,
        testE.contextSectionExists ? 'Found' : 'NOT found');
    report('E5 - Research Dimensions section', testE.dimensionsSectionExists,
        testE.dimensionsSectionExists ? 'Found' : 'NOT found');
    report('E6 - Feature Landscape section', testE.landscapeSectionExists,
        testE.landscapeSectionExists ? 'Found' : 'NOT found');
    report('E7 - Gap Analysis section', testE.gapSectionExists,
        testE.gapSectionExists ? 'Found' : 'NOT found');
    report('E8 - Analysis History section', testE.historySectionExists,
        testE.historySectionExists ? 'Found' : 'NOT found');

    // ════════════════════════════════════════════════════════
    // TEST F — Find Similar Companies
    // ════════════════════════════════════════════════════════
    console.log('\n═══ TEST F: Find Similar Companies ═══');

    // Switch to companies tab to look for the Find Similar button
    await page.evaluate(() => showTab('companies'));
    await page.waitForTimeout(2000);
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(500);

    const testF = await page.evaluate(() => {
        // Check if findSimilar function exists
        const funcExists = typeof findSimilar === 'function';

        // Look for "Find Similar" buttons in the companies list
        const findSimilarBtns = document.querySelectorAll('button');
        let findSimilarBtn = null;
        let findSimilarBtnText = '';
        for (const btn of findSimilarBtns) {
            if (btn.textContent.trim().includes('Find Similar') || 
                btn.getAttribute('onclick')?.includes('findSimilar')) {
                findSimilarBtn = btn;
                findSimilarBtnText = btn.textContent.trim();
                break;
            }
        }

        // Also check for similar results containers
        const similarContainers = document.querySelectorAll('[id^="similarResults-"]');

        return {
            funcExists,
            btnFound: !!findSimilarBtn,
            btnText: findSimilarBtnText,
            btnVisible: findSimilarBtn ? (findSimilarBtn.offsetWidth > 0) : false,
            similarContainersCount: similarContainers.length,
        };
    });

    await page.screenshot({ path: DIR + '/feature_discovery_similar.png', fullPage: false });
    console.log('   Screenshot: feature_discovery_similar.png');

    report('F1 - findSimilar() function exists', testF.funcExists,
        testF.funcExists ? 'Function is defined' : 'Function NOT found');
    report('F2 - Find Similar button in UI', testF.btnFound,
        testF.btnFound ? `Button found: "${testF.btnText}"` : 'Button not currently visible (may appear in company detail)');
    if (testF.btnFound) {
        report('F3 - Find Similar button visible', testF.btnVisible,
            testF.btnVisible ? 'Button is visible' : 'Button exists but not visible');
    } else {
        // Try expanding a company row to find the button
        const expandResult = await page.evaluate(() => {
            // Click on first company row to expand it
            const companyRow = document.querySelector('.company-row, .company-item, tr[onclick], [onclick*="toggleCompany"], [onclick*="expandCompany"]');
            if (companyRow) {
                companyRow.click();
                return { clicked: true, selector: companyRow.className || companyRow.tagName };
            }
            return { clicked: false };
        });

        if (expandResult.clicked) {
            await page.waitForTimeout(1000);

            const retryF = await page.evaluate(() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    if (btn.textContent.trim().includes('Find Similar') ||
                        btn.getAttribute('onclick')?.includes('findSimilar')) {
                        return { found: true, text: btn.textContent.trim(), visible: btn.offsetWidth > 0 };
                    }
                }
                return { found: false };
            });

            await page.screenshot({ path: DIR + '/feature_discovery_similar.png', fullPage: false });

            report('F3 - Find Similar button after expanding company', retryF.found,
                retryF.found ? `Button found: "${retryF.text}", visible: ${retryF.visible}` : 'Button still not visible');
        } else {
            report('F3 - Could not expand company row', false, 'No expandable company row found');
        }
    }

    // ════════════════════════════════════════════════════════
    // SUMMARY
    // ════════════════════════════════════════════════════════
    console.log('\n════════════════════════════════════════');
    console.log('RESULTS SUMMARY');
    console.log('════════════════════════════════════════');

    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass).length;
    const total = results.length;

    for (const r of results) {
        console.log(`  ${r.pass ? 'PASS' : 'FAIL'}: ${r.name}`);
    }

    console.log(`\nTotal: ${total} | Passed: ${passed} | Failed: ${failed}`);

    // Console errors
    console.log('\n═══ JS Console Errors (' + consoleErrors.length + ') ═══');
    if (consoleErrors.length > 0) {
        for (const e of consoleErrors) {
            console.log('  ', e);
        }
    } else {
        console.log('   None detected');
    }

    console.log('\nScreenshots saved to ' + DIR + '/');
    await browser.close();

    process.exit(failed > 0 ? 1 : 0);
})().catch(e => {
    console.error('FATAL:', e.message);
    console.error(e.stack);
    process.exit(1);
});
