/**
 * Playwright E2E test: Companies Tab
 * Tests: empty state, adding companies, list view, detail panel, search/filter, header count
 * Run: node e2e/test_companies.cjs
 */
const { chromium } = require('playwright');
const path = require('path');

const DIR = path.join(__dirname, '..', 'test-evidence');
const BASE_URL = 'http://127.0.0.1:5001';

const results = [];
function record(name, pass, detail) {
    results.push({ name, pass, detail });
    console.log(`  ${pass ? 'PASS' : 'FAIL'}: ${name}${detail ? ' — ' + detail : ''}`);
}

async function dismissTour(page) {
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
    await page.waitForTimeout(300);
}

/** Always get fresh CSRF token from the current page meta tag. */
async function getCSRF(page) {
    return page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
}

/** Wait until a global function is defined (scripts fully loaded). */
async function waitForGlobal(page, fnName, timeoutMs = 15000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        const ready = await page.evaluate((n) => typeof window[n] === 'function', fnName);
        if (ready) return true;
        await page.waitForTimeout(200);
    }
    return false;
}

(async () => {
    console.log('=== Companies Tab E2E Test ===\n');

    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    // Collect console errors
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    // ---- Setup: Load page, create project, select it ----
    console.log('--- Setup ---');
    console.log('  Loading page...');
    await page.goto(BASE_URL + '/', { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);
    await dismissTour(page);

    // Wait for key functions to be available (scripts fully loaded)
    console.log('  Waiting for app scripts to load...');
    await waitForGlobal(page, 'selectProject');
    await waitForGlobal(page, 'showTab');
    await waitForGlobal(page, 'loadCompanies');
    console.log('  All app functions ready');

    // Get fresh CSRF token
    let token = await getCSRF(page);
    if (!token) {
        console.log('  FATAL: No CSRF token found');
        await browser.close();
        process.exit(1);
    }
    console.log('  CSRF token acquired');

    // Create test project — use page.evaluate with inline CSRF read for freshness
    const projName = 'Companies Test ' + Date.now();
    console.log(`  Creating project: ${projName}`);
    const projResp = await page.evaluate(async (name) => {
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                purpose: 'E2E test for companies tab',
                seed_categories: 'Digital Health\nInsurTech'
            })
        });
        return { status: r.status, body: await r.json() };
    }, projName);
    console.log(`  Project response: ${projResp.status} ${JSON.stringify(projResp.body)}`);

    let pid = projResp.body.id || projResp.body.project_id;
    if (!pid) {
        console.log('  Project creation failed, trying existing projects...');
        const projects = await page.evaluate(async () => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': csrf } });
            return r.json();
        });
        if (projects && projects.length > 0) {
            pid = projects[0].id;
            console.log(`  Using existing project: ${pid} (${projects[0].name})`);
        } else {
            console.log('  FATAL: No projects available');
            await browser.close();
            process.exit(1);
        }
    } else {
        console.log(`  Project created with ID: ${pid}`);
    }

    // Select project — wait for renderFilterChips first
    await waitForGlobal(page, 'renderFilterChips', 5000);
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);
    await dismissTour(page);
    console.log('  Project selected\n');

    // ============================================================
    // TEST A: Companies Tab Empty State
    // ============================================================
    console.log('--- TEST A: Companies Tab Empty State ---');
    try {
        await page.evaluate(() => showTab('companies'));
        await page.waitForTimeout(2000);
        await dismissTour(page);

        await page.screenshot({ path: path.join(DIR, 'feature_companies_empty.png') });
        console.log('  Screenshot: feature_companies_empty.png');

        // Check the tab loaded (tab-companies is visible)
        const tabVisible = await page.evaluate(() => {
            const el = document.getElementById('tab-companies');
            return el && !el.classList.contains('hidden') && el.offsetWidth > 0;
        });
        record('A1: Companies tab loads', tabVisible, tabVisible ? 'tab-companies is visible' : 'tab not visible');

        // Check for empty state or table structure
        const emptyState = await page.evaluate(() => {
            const tbody = document.getElementById('companyBody');
            const emptyEl = tbody ? tbody.querySelector('.empty-state') : null;
            const rowCount = tbody ? tbody.querySelectorAll('tr[data-company-id]').length : 0;
            return { hasEmptyState: !!emptyEl, rowCount };
        });
        record('A2: Empty state shown (0 companies)', emptyState.hasEmptyState || emptyState.rowCount === 0,
            `emptyState=${emptyState.hasEmptyState}, rows=${emptyState.rowCount}`);

        // Check for Add Company mechanism (Process tab link in empty state, or any add button)
        const hasAddMechanism = await page.evaluate(() => {
            const emptyLink = document.querySelector('.empty-state-link');
            const addBtn = document.querySelector('button[onclick*="addCompany"], button[onclick*="add_company"], #addCompanyBtn');
            return { emptyLink: !!emptyLink, addBtn: !!addBtn, emptyLinkText: emptyLink?.textContent || '' };
        });
        record('A3: Add company mechanism exists', hasAddMechanism.emptyLink || hasAddMechanism.addBtn,
            `emptyLink=${hasAddMechanism.emptyLink} ("${hasAddMechanism.emptyLinkText}"), addBtn=${hasAddMechanism.addBtn}`);

        // Check search input exists
        const hasSearch = await page.evaluate(() => {
            const el = document.getElementById('searchInput');
            return !!el;
        });
        record('A4: Search input exists', hasSearch, hasSearch ? 'searchInput found' : 'searchInput not found');

        // Check no JS errors on tab load (filter known benign CDN/CSP issues)
        const errorsBeforeAdd = consoleErrors.filter(e =>
            !e.includes('favicon') && !e.includes('clearbit') &&
            !e.includes('MIME type') && !e.includes('Content Security Policy') &&
            !e.includes('layoutBase') && !e.includes('import statement') &&
            !e.includes('ninja-ke') && !e.includes('docx@') &&
            !e.includes('Failed to load resource'));
        record('A5: No critical JS errors', errorsBeforeAdd.length === 0,
            errorsBeforeAdd.length > 0 ? `${errorsBeforeAdd.length} errors: ${errorsBeforeAdd[0]}` : 'clean console (CDN/CSP warnings filtered)');
    } catch (err) {
        record('A: Companies empty state', false, err.message);
    }

    // ============================================================
    // TEST B: Add Companies via API and verify list
    // ============================================================
    console.log('\n--- TEST B: Add Companies via API ---');
    try {
        const companies = [
            { name: 'Oscar Health', url: 'https://oscar-co.com', hq_city: 'New York', hq_country: 'US', geography: 'US', description: 'Digital health insurance' },
            { name: 'Babylon Health', url: 'https://babylon-co.com', hq_city: 'London', hq_country: 'UK', geography: 'UK', description: 'AI-powered healthcare' },
            { name: 'Lemonade Inc', url: 'https://lemonade-co.com', hq_city: 'New York', hq_country: 'US', geography: 'US', description: 'AI insurance' },
            { name: 'Ada Health', url: 'https://ada-co.com', hq_city: 'Berlin', hq_country: 'DE', geography: 'Germany', description: 'Health assessment' },
            { name: 'Doctolib', url: 'https://doctolib-co.com', hq_city: 'Paris', hq_country: 'FR', geography: 'France', description: 'Online booking' },
        ];

        const addResults = [];
        for (const c of companies) {
            const resp = await page.evaluate(async (args) => {
                const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
                const r = await fetch('/api/companies/add', {
                    method: 'POST',
                    headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: args.pid, ...args.company })
                });
                return { status: r.status, body: await r.json() };
            }, { pid, company: c });
            addResults.push(resp);
        }

        const allAdded = addResults.every(r => r.status === 200 && r.body.id);
        record('B1: All 5 companies added via API', allAdded,
            `responses: ${addResults.map(r => r.status + ':' + (r.body.id || r.body.error || 'no-id')).join(', ')}`);

        // Reload companies tab
        await page.evaluate(() => showTab('companies'));
        await page.waitForTimeout(3000);
        await dismissTour(page);

        await page.screenshot({ path: path.join(DIR, 'feature_companies_list.png') });
        console.log('  Screenshot: feature_companies_list.png');

        // Count visible company rows
        const listInfo = await page.evaluate(() => {
            const rows = document.querySelectorAll('#companyBody tr[data-company-id]');
            const names = Array.from(rows).map(r => {
                const strong = r.querySelector('strong');
                return strong ? strong.textContent.trim() : '';
            });
            return { count: rows.length, names };
        });
        record('B2: Company list shows 5 items', listInfo.count === 5,
            `found ${listInfo.count} rows: ${listInfo.names.join(', ')}`);

        // Verify each company name appears
        const pageHTML = await page.evaluate(() => document.body.innerHTML);
        const namesFound = companies.map(c => ({
            name: c.name,
            found: pageHTML.includes(c.name)
        }));
        const allNamesFound = namesFound.every(n => n.found);
        record('B3: All company names in page', allNamesFound,
            namesFound.map(n => `${n.name}:${n.found ? 'yes' : 'NO'}`).join(', '));
    } catch (err) {
        record('B: Add companies', false, err.message);
    }

    // ============================================================
    // TEST C: Company Details
    // ============================================================
    console.log('\n--- TEST C: Company Details ---');
    try {
        // Click first company row to open detail panel
        const firstCompanyId = await page.evaluate(() => {
            const row = document.querySelector('#companyBody tr[data-company-id]');
            return row ? parseInt(row.dataset.companyId) : null;
        });

        if (firstCompanyId) {
            await page.evaluate((id) => showDetail(id), firstCompanyId);
            await page.waitForTimeout(2000);

            await page.screenshot({ path: path.join(DIR, 'feature_companies_detail.png') });
            console.log('  Screenshot: feature_companies_detail.png');

            // Check detail panel is visible
            const detailVisible = await page.evaluate(() => {
                const panel = document.getElementById('detailPanel');
                return panel && !panel.classList.contains('hidden');
            });
            record('C1: Detail panel opens', detailVisible, detailVisible ? 'detailPanel visible' : 'detailPanel hidden');

            // Check detail fields
            const detailFields = await page.evaluate(() => {
                const content = document.getElementById('detailContent');
                if (!content) return { found: false };
                const html = content.innerHTML;
                const name = document.getElementById('detailName')?.textContent || '';
                return {
                    found: true,
                    name,
                    hasWhat: html.includes('What'),
                    hasTarget: html.includes('Target'),
                    hasGeography: html.includes('Geography'),
                    hasHQ: html.includes('HQ'),
                    hasCategory: html.includes('Category'),
                    hasTags: html.includes('Tags'),
                    hasUrl: html.includes('oscar-co.com') || html.includes('babylon-co.com') || html.includes('lemonade-co.com') || html.includes('ada-co.com') || html.includes('doctolib-co.com'),
                    hasEditBtn: html.includes('Edit'),
                    hasDeleteBtn: html.includes('Delete'),
                };
            });
            record('C2: Detail shows company name', detailFields.name.length > 0,
                `name="${detailFields.name}"`);
            record('C3: Detail has standard fields', detailFields.hasWhat && detailFields.hasGeography && detailFields.hasHQ,
                `What=${detailFields.hasWhat}, Geography=${detailFields.hasGeography}, HQ=${detailFields.hasHQ}`);
            record('C4: Detail has URL link', detailFields.hasUrl, 'company URL displayed');
            record('C5: Detail has action buttons', detailFields.hasEditBtn && detailFields.hasDeleteBtn,
                `Edit=${detailFields.hasEditBtn}, Delete=${detailFields.hasDeleteBtn}`);
        } else {
            record('C1: Detail panel opens', false, 'No company found to click');
        }

        // Close detail panel
        await page.evaluate(() => {
            if (typeof closeDetail === 'function') closeDetail();
        });
        await page.waitForTimeout(500);
    } catch (err) {
        record('C: Company details', false, err.message);
    }

    // ============================================================
    // TEST D: Company Search/Filter
    // ============================================================
    console.log('\n--- TEST D: Company Search/Filter ---');
    try {
        const searchInput = await page.$('#searchInput');
        if (searchInput) {
            // Clear and type a search term
            await searchInput.fill('');
            await page.waitForTimeout(500);
            await searchInput.fill('Oscar');
            await page.waitForTimeout(1500); // debounce + API

            await page.screenshot({ path: path.join(DIR, 'feature_companies_search.png') });
            console.log('  Screenshot: feature_companies_search.png');

            const searchResults = await page.evaluate(() => {
                const rows = document.querySelectorAll('#companyBody tr[data-company-id]');
                const names = Array.from(rows).map(r => {
                    const strong = r.querySelector('strong');
                    return strong ? strong.textContent.trim() : '';
                });
                return { count: rows.length, names };
            });

            record('D1: Search filters results', searchResults.count > 0 && searchResults.count < 5,
                `${searchResults.count} results for "Oscar": ${searchResults.names.join(', ')}`);

            const hasOscar = searchResults.names.some(n => n.toLowerCase().includes('oscar'));
            record('D2: Search result contains "Oscar"', hasOscar,
                hasOscar ? 'Oscar Health found' : `got: ${searchResults.names.join(', ')}`);

            // Now search for something that should match none
            await searchInput.fill('XYZNONEXISTENT');
            await page.waitForTimeout(1500);

            const noResults = await page.evaluate(() => {
                const rows = document.querySelectorAll('#companyBody tr[data-company-id]');
                const emptyState = document.querySelector('#companyBody .empty-state');
                return { count: rows.length, hasEmptyState: !!emptyState };
            });
            record('D3: No-match search shows 0 results', noResults.count === 0,
                `${noResults.count} rows, emptyState=${noResults.hasEmptyState}`);

            // Clear search to restore all
            await searchInput.fill('');
            await page.waitForTimeout(1500);

            const allBack = await page.evaluate(() => {
                return document.querySelectorAll('#companyBody tr[data-company-id]').length;
            });
            record('D4: Clearing search restores all companies', allBack === 5,
                `${allBack} rows after clear`);
        } else {
            record('D1: Search input found', false, 'searchInput element not found');
        }
    } catch (err) {
        record('D: Search/Filter', false, err.message);
    }

    // ============================================================
    // TEST E: Header Company Count
    // ============================================================
    console.log('\n--- TEST E: Header Company Count ---');
    try {
        // Trigger stats reload
        await page.evaluate(() => {
            if (typeof loadStats === 'function') loadStats();
        });
        await page.waitForTimeout(2000);

        await page.screenshot({ path: path.join(DIR, 'feature_companies_header.png') });
        console.log('  Screenshot: feature_companies_header.png');

        const headerCount = await page.evaluate(() => {
            const el = document.getElementById('statCompanies');
            return el ? el.textContent.trim() : '';
        });
        record('E1: Header shows company count', headerCount.includes('5'),
            `statCompanies text: "${headerCount}"`);

        const countNum = parseInt(headerCount);
        record('E2: Count is exactly 5', countNum === 5,
            `parsed count: ${countNum}`);
    } catch (err) {
        record('E: Header count', false, err.message);
    }

    // ============================================================
    // Summary
    // ============================================================
    console.log('\n========================================');
    console.log('          TEST SUMMARY');
    console.log('========================================');
    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass).length;
    console.log(`  Total:  ${results.length}`);
    console.log(`  Passed: ${passed}`);
    console.log(`  Failed: ${failed}`);
    console.log('');
    if (failed > 0) {
        console.log('  Failed tests:');
        results.filter(r => !r.pass).forEach(r => {
            console.log(`    - ${r.name}: ${r.detail}`);
        });
    }
    console.log('');
    console.log(`  Screenshots saved to: ${DIR}/`);
    console.log(`  Console errors during test: ${consoleErrors.length}`);
    if (consoleErrors.length > 0) {
        consoleErrors.slice(0, 5).forEach(e => console.log(`    ${e.substring(0, 120)}`));
    }
    console.log('========================================');
    console.log(`  Result: ${failed === 0 ? 'ALL PASSED' : `${failed} FAILED`}`);
    console.log('========================================\n');

    await browser.close();
    process.exit(failed > 0 ? 1 : 0);
})().catch(err => {
    console.error('FATAL ERROR:', err.message);
    process.exit(1);
});
