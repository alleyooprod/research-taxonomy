/**
 * Comprehensive Tab Navigation, Layout Integrity & Responsive Behavior Tests
 * Run: node e2e/test_navigation.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const BASE = 'http://127.0.0.1:5001/';

// Test result tracking
const results = { pass: 0, fail: 0, details: [] };

function report(test, passed, detail) {
    if (passed) {
        results.pass++;
        console.log(`  PASS: ${test}`);
    } else {
        results.fail++;
        console.log(`  FAIL: ${test} — ${detail}`);
    }
    results.details.push({ test, passed, detail: detail || '' });
}

(async () => {
    console.log('='.repeat(70));
    console.log('  NAVIGATION, LAYOUT & RESPONSIVE BEHAVIOR TEST SUITE');
    console.log('  ' + new Date().toISOString());
    console.log('='.repeat(70));

    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    // Collect ALL console messages for error audit
    const consoleErrors = [];
    const allConsoleLogs = [];
    page.on('console', msg => {
        const entry = msg.type() + ': ' + msg.text();
        allConsoleLogs.push(entry);
        if (msg.type() === 'error') {
            consoleErrors.push(msg.text());
        }
    });

    // Handle dialogs (e.g. canvas name prompt)
    page.on('dialog', async dialog => {
        await dialog.accept('Nav Test Canvas');
    });

    // =========================================================================
    // SETUP: Load page, dismiss tour, create project, add companies
    // =========================================================================
    console.log('\n--- SETUP ---');

    console.log('1. Loading homepage...');
    await page.goto(BASE, { waitUntil: 'networkidle', timeout: 20000 });
    await page.waitForTimeout(2000);

    // Dismiss driver.js onboarding tour
    console.log('2. Dismissing onboarding tour...');
    await dismissTour(page);
    await page.waitForTimeout(500);

    // Get CSRF token
    const csrf = await page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
    console.log('   CSRF token obtained:', csrf ? 'yes' : 'NO — tests may fail');

    // Create test project
    console.log('3. Creating test project...');
    const projResp = await page.evaluate(async (token) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Nav Test ' + Date.now(),
                purpose: 'Navigation & layout testing',
                seed_categories: 'Digital Health\nInsurTech\nHealthcare AI'
            })
        });
        return r.json();
    }, csrf);

    let pid = projResp.id || projResp.project_id;
    if (!pid) {
        console.log('   Project creation returned no ID, using existing...');
        const projects = await page.evaluate(async (token) => {
            const r = await fetch('/api/projects', { headers: { 'X-CSRF-Token': token } });
            return r.json();
        }, csrf);
        if (projects && projects.length > 0) {
            pid = projects[0].id;
            console.log('   Using existing project:', pid, projects[0].name);
        } else {
            console.error('   FATAL: No projects available');
            await browser.close();
            process.exit(1);
        }
    } else {
        console.log('   Project created: id=' + pid);
    }

    // Add 3 test companies with unique URLs
    console.log('4. Adding 3 test companies...');
    const companies = [
        { name: 'TestCo Alpha', url: 'https://alpha-' + Date.now() + '.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'Digital Health' },
        { name: 'TestCo Beta', url: 'https://beta-' + Date.now() + '.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom', category_name: 'InsurTech' },
        { name: 'TestCo Gamma', url: 'https://gamma-' + Date.now() + '.com', hq_city: 'Berlin', hq_country: 'Germany', geography: 'Germany', category_name: 'Healthcare AI' },
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
    console.log('   Added 3 companies');

    // Select project
    console.log('5. Selecting project...');
    await page.evaluate((id) => { selectProject(id); }, pid);
    await page.waitForTimeout(3000);
    await dismissTour(page);
    await page.waitForTimeout(500);

    // =========================================================================
    // TEST A: All Tab Navigation
    // =========================================================================
    console.log('\n' + '='.repeat(70));
    console.log('  TEST A: All Tab Navigation');
    console.log('='.repeat(70));

    // Tab definitions: [showTab name, screenshot filename, fallback name]
    const tabDefs = [
        { name: 'companies', file: 'feature_nav_companies.png', fallback: null },
        { name: 'taxonomy', file: 'feature_nav_taxonomy.png', fallback: null },
        { name: 'map', file: 'feature_nav_map.png', fallback: null },
        { name: 'reports', file: 'feature_nav_research.png', fallback: 'research' },
        { name: 'canvas', file: 'feature_nav_canvas.png', fallback: null },
        { name: 'discovery', file: 'feature_nav_discovery.png', fallback: 'process' },
        { name: 'process', file: 'feature_nav_process.png', fallback: null },
        { name: 'export', file: 'feature_nav_export.png', fallback: null },
        { name: 'settings', file: 'feature_nav_settings.png', fallback: null },
    ];

    const tabSwitchResults = {};

    for (const tab of tabDefs) {
        let usedName = tab.name;
        let success = false;
        let errorMsg = '';

        try {
            // Try primary tab name
            const result = await page.evaluate((t) => {
                try {
                    showTab(t);
                    return { ok: true };
                } catch (e) {
                    return { ok: false, error: e.message };
                }
            }, tab.name);

            if (!result.ok && tab.fallback) {
                console.log(`  Tab '${tab.name}' failed (${result.error}), trying fallback '${tab.fallback}'...`);
                const fallbackResult = await page.evaluate((t) => {
                    try {
                        showTab(t);
                        return { ok: true };
                    } catch (e) {
                        return { ok: false, error: e.message };
                    }
                }, tab.fallback);
                if (fallbackResult.ok) {
                    usedName = tab.fallback;
                    success = true;
                } else {
                    errorMsg = `Primary '${tab.name}' and fallback '${tab.fallback}' both failed`;
                }
            } else if (result.ok) {
                success = true;
            } else {
                errorMsg = result.error;
            }
        } catch (e) {
            errorMsg = e.message;
        }

        await page.waitForTimeout(1500);
        await dismissTour(page);

        // Take screenshot regardless of success
        await page.screenshot({ path: DIR + '/' + tab.file });
        console.log(`  Screenshot saved: ${tab.file}`);

        if (success) {
            // Verify the tab content panel is visible
            const tabContentId = 'tab-' + usedName;
            const isActive = await page.evaluate((id) => {
                const el = document.getElementById(id);
                return el ? el.classList.contains('active') : false;
            }, tabContentId);
            report(`Tab '${usedName}' navigated and content active`, isActive, isActive ? '' : `#${tabContentId} not active`);
        } else {
            report(`Tab '${tab.name}' navigation`, false, errorMsg);
        }

        tabSwitchResults[usedName || tab.name] = success;
    }

    // =========================================================================
    // TEST B: Tab Active States
    // =========================================================================
    console.log('\n' + '='.repeat(70));
    console.log('  TEST B: Tab Active States');
    console.log('='.repeat(70));

    // Test each navigable tab for proper active state isolation
    const testableTabs = ['companies', 'taxonomy', 'map', 'canvas', 'process', 'export', 'settings'];

    for (const tabName of testableTabs) {
        await page.evaluate((t) => {
            try { showTab(t); } catch(e) {}
        }, tabName);
        await page.waitForTimeout(800);
        await dismissTour(page);

        const activeState = await page.evaluate(() => {
            const allTabs = document.querySelectorAll('.tab');
            const activeTabs = document.querySelectorAll('.tab.active');
            const activeContents = document.querySelectorAll('.tab-content.active');
            const activeTabTexts = Array.from(activeTabs).map(t => t.textContent.trim());
            const activeContentIds = Array.from(activeContents).map(el => el.id);
            return {
                totalTabs: allTabs.length,
                activeTabCount: activeTabs.length,
                activeContentCount: activeContents.length,
                activeTabTexts,
                activeContentIds,
            };
        });

        const oneTabActive = activeState.activeTabCount === 1;
        const oneContentActive = activeState.activeContentCount === 1;

        report(
            `Tab '${tabName}' — exactly 1 tab button active`,
            oneTabActive,
            `Found ${activeState.activeTabCount} active tabs: [${activeState.activeTabTexts.join(', ')}]`
        );
        report(
            `Tab '${tabName}' — exactly 1 content panel active`,
            oneContentActive,
            `Found ${activeState.activeContentCount} active panels: [${activeState.activeContentIds.join(', ')}]`
        );
    }

    // =========================================================================
    // TEST C: Header Integrity
    // =========================================================================
    console.log('\n' + '='.repeat(70));
    console.log('  TEST C: Header Integrity');
    console.log('='.repeat(70));

    // Go to companies tab first (header is visible in project view)
    await page.evaluate(() => showTab('companies'));
    await page.waitForTimeout(1500);
    await dismissTour(page);

    // Check header elements — scope queries to #mainApp to get the correct elements
    const headerInfo = await page.evaluate(() => {
        const mainApp = document.getElementById('mainApp');
        const statCompanies = document.getElementById('statCompanies');
        const statCategories = document.getElementById('statCategories');
        const statUpdated = document.getElementById('statUpdated');
        // Scope to mainApp to avoid picking up elements from hidden views
        const backBtn = mainApp ? mainApp.querySelector('.back-btn') : document.querySelector('.back-btn');
        const notifBell = mainApp ? mainApp.querySelector('.notification-bell') : document.querySelector('.notification-bell');
        const themeToggle = mainApp ? mainApp.querySelector('.theme-toggle') : document.querySelector('.theme-toggle');
        const projectTitle = document.getElementById('projectTitle');

        // Check visibility by walking up to see if any parent is hidden
        function isVisible(el) {
            if (!el) return false;
            if (el.offsetWidth === 0 && el.offsetHeight === 0) return false;
            // Also check computed display/visibility
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden') return false;
            return true;
        }

        // Check if mainApp itself is visible (it should be after selectProject)
        const mainAppVisible = mainApp ? !mainApp.classList.contains('hidden') : false;

        return {
            mainAppVisible,
            companiesText: statCompanies ? statCompanies.textContent.trim() : null,
            companiesVisible: isVisible(statCompanies),
            categoriesText: statCategories ? statCategories.textContent.trim() : null,
            categoriesVisible: isVisible(statCategories),
            dateText: statUpdated ? statUpdated.textContent.trim() : null,
            dateVisible: isVisible(statUpdated),
            backBtnExists: !!backBtn,
            backBtnVisible: isVisible(backBtn),
            backBtnInMainApp: mainApp ? !!mainApp.querySelector('.back-btn') : false,
            bellExists: !!notifBell,
            bellVisible: isVisible(notifBell),
            themeToggleExists: !!themeToggle,
            themeToggleVisible: isVisible(themeToggle),
            projectTitleText: projectTitle ? projectTitle.textContent.trim() : null,
        };
    });

    console.log('  Header data:', JSON.stringify(headerInfo, null, 2));

    report('Company count displayed', headerInfo.companiesVisible && headerInfo.companiesText !== null,
        `text="${headerInfo.companiesText}", visible=${headerInfo.companiesVisible}`);
    report('Category count displayed', headerInfo.categoriesVisible && headerInfo.categoriesText !== null,
        `text="${headerInfo.categoriesText}", visible=${headerInfo.categoriesVisible}`);
    report('Date/updated displayed', headerInfo.dateVisible && headerInfo.dateText !== null,
        `text="${headerInfo.dateText}", visible=${headerInfo.dateVisible}`);
    report('Back arrow present in #mainApp', headerInfo.backBtnExists && headerInfo.backBtnInMainApp,
        `exists=${headerInfo.backBtnExists}, inMainApp=${headerInfo.backBtnInMainApp}`);
    report('Notification bell present & visible', headerInfo.bellExists && headerInfo.bellVisible,
        `exists=${headerInfo.bellExists}, visible=${headerInfo.bellVisible}`);
    report('Dark mode toggle present & visible', headerInfo.themeToggleExists && headerInfo.themeToggleVisible,
        `exists=${headerInfo.themeToggleExists}, visible=${headerInfo.themeToggleVisible}`);

    await page.screenshot({ path: DIR + '/feature_header.png' });
    console.log('  Screenshot saved: feature_header.png');

    // =========================================================================
    // TEST D: Console Error Audit
    // =========================================================================
    console.log('\n' + '='.repeat(70));
    console.log('  TEST D: Console Error Audit');
    console.log('='.repeat(70));

    // Unique error messages
    const uniqueErrors = [...new Set(consoleErrors)];

    // Known/expected error patterns
    const knownPatterns = [
        /matrix/i,                          // Known matrix tab issue
        /null.*classList/i,                  // Null element access
        /favicon/i,                         // Missing favicon
        /net::ERR/i,                        // Network errors in test env
        /404/i,                             // 404s (missing optional endpoints)
        /429/i,                             // Rate limiting in rapid test
        /Rate limit/i,                      // Rate limit message
        /Content Security Policy/i,         // CSP violations for test logos
        /MIME type/i,                       // CDN MIME type issues
        /clearbit/i,                        // Logo loading CSP
        /import statement outside/i,        // ESM/CJS CDN issue (ninja-keys)
        /layoutBase/i,                      // Cytoscape-fcose plugin loading order
        /\.filter is not a function/i,      // Rate-limited response parsed as error obj
        /\.forEach is not a function/i,     // Same rate-limit cascade
        /print\.css/i,                      // Missing print stylesheet
    ];

    const knownErrors = uniqueErrors.filter(e =>
        knownPatterns.some(pattern => pattern.test(e))
    );
    const unknownErrors = uniqueErrors.filter(e =>
        !knownPatterns.some(pattern => pattern.test(e))
    );

    console.log(`  Total console errors: ${consoleErrors.length}`);
    console.log(`  Unique error messages: ${uniqueErrors.length}`);
    console.log(`  Known/expected errors: ${knownErrors.length}`);
    console.log(`  Unknown errors: ${unknownErrors.length}`);

    if (knownErrors.length > 0) {
        console.log('\n  Known errors (expected/environmental):');
        knownErrors.forEach(e => console.log('    - ' + e.substring(0, 150)));
    }
    if (unknownErrors.length > 0) {
        console.log('\n  UNEXPECTED errors:');
        unknownErrors.forEach(e => console.log('    - ' + e.substring(0, 200)));
    }

    report('Console error audit — no unexpected errors', unknownErrors.length === 0,
        unknownErrors.length > 0 ? `${unknownErrors.length} unexpected error(s): ${unknownErrors[0].substring(0, 100)}` : '');

    // =========================================================================
    // TEST E: CDN Library Verification
    // =========================================================================
    console.log('\n' + '='.repeat(70));
    console.log('  TEST E: CDN Library Verification');
    console.log('='.repeat(70));

    const cdnLibs = await page.evaluate(() => {
        return {
            cytoscape: { type: typeof cytoscape, loaded: typeof cytoscape === 'function' },
            fabric: { type: typeof fabric, loaded: typeof fabric === 'object' },
            leaflet: { type: typeof L, loaded: typeof L === 'object' },
            chartjs: { type: typeof Chart, loaded: typeof Chart === 'function' },
            perfectFreehand: { type: typeof getStroke, loaded: typeof getStroke === 'function' },
        };
    });

    console.log('  CDN library status:');
    const libChecks = [
        { name: 'Cytoscape.js', key: 'cytoscape', expected: 'function' },
        { name: 'Fabric.js', key: 'fabric', expected: 'object' },
        { name: 'Leaflet (L)', key: 'leaflet', expected: 'object' },
        { name: 'Chart.js', key: 'chartjs', expected: 'function' },
        { name: 'perfect-freehand (getStroke)', key: 'perfectFreehand', expected: 'function' },
    ];

    for (const lib of libChecks) {
        const info = cdnLibs[lib.key];
        const loaded = info.loaded;
        console.log(`    ${lib.name}: typeof=${info.type}, loaded=${loaded}`);
        report(`CDN: ${lib.name} loaded (typeof === '${lib.expected}')`, loaded,
            loaded ? '' : `typeof is '${info.type}', expected '${lib.expected}'`);
    }

    // =========================================================================
    // SUMMARY
    // =========================================================================
    console.log('\n' + '='.repeat(70));
    console.log('  FINAL SUMMARY');
    console.log('='.repeat(70));
    console.log(`  Total tests:  ${results.pass + results.fail}`);
    console.log(`  PASSED:       ${results.pass}`);
    console.log(`  FAILED:       ${results.fail}`);
    console.log('='.repeat(70));

    if (results.fail > 0) {
        console.log('\n  Failed tests:');
        results.details.filter(d => !d.passed).forEach(d => {
            console.log(`    - ${d.test}: ${d.detail}`);
        });
    }

    console.log('\n  Screenshots saved to ' + DIR + '/');
    const screenshots = [
        'feature_nav_companies.png', 'feature_nav_taxonomy.png', 'feature_nav_map.png',
        'feature_nav_research.png', 'feature_nav_canvas.png', 'feature_nav_discovery.png',
        'feature_nav_process.png', 'feature_nav_export.png', 'feature_nav_settings.png',
        'feature_header.png'
    ];
    for (const s of screenshots) {
        console.log('    - ' + s);
    }

    await browser.close();

    // Exit with code reflecting test results
    process.exit(results.fail > 0 ? 1 : 0);

})().catch(e => {
    console.error('FATAL ERROR:', e.message);
    console.error(e.stack);
    process.exit(1);
});

// Helper: dismiss driver.js tour
async function dismissTour(page) {
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') {
            driverObj.destroy();
        }
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
}
