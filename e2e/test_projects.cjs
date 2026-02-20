/**
 * E2E Test: Project Management Features
 * Run: node e2e/test_projects.cjs
 */
const { chromium } = require('playwright');

const DIR = 'test-evidence';
const BASE = 'http://127.0.0.1:5001';

const results = [];
function report(name, pass, detail) {
    results.push({ name, pass, detail });
    console.log(`  ${pass ? 'PASS' : 'FAIL'}: ${name}${detail ? ' — ' + detail : ''}`);
}

async function dismissTour(page) {
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') {
            driverObj.destroy();
        }
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
    });
}

async function getCSRF(page) {
    return page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
}

/** Wait for the app to fully initialize (all scripts loaded + loadProjects done) */
async function waitForAppReady(page) {
    // Wait for window.onload to have fired (init.js runs loadProjects there)
    await page.waitForFunction(
        () => typeof selectProject === 'function'
           && typeof loadTaxonomy === 'function'
           && typeof loadCompanies === 'function'
           && typeof showTab === 'function',
        { timeout: 15000 }
    );
    // Wait for project grid to be populated (async loadProjects)
    await page.waitForFunction(
        () => {
            const grid = document.getElementById('projectGrid');
            return grid && grid.children.length > 0;
        },
        { timeout: 10000 }
    ).catch(() => {
        // Grid may be empty if DB has no projects — that is acceptable
    });
    await page.waitForTimeout(500);
    await dismissTour(page);
    await page.waitForTimeout(300);
}

(async () => {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    // Collect console errors
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    console.log('Loading homepage...');
    await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 20000 });
    await waitForAppReady(page);

    const csrf = await getCSRF(page);
    if (!csrf) {
        console.log('FATAL: No CSRF token found');
        await browser.close();
        process.exit(1);
    }
    console.log('App ready. CSRF obtained.');

    // =========================================================================
    // TEST A — Homepage / Landing
    // =========================================================================
    console.log('\n=== TEST A: Homepage / Landing ===');
    await page.screenshot({ path: DIR + '/feature_home_landing.png' });
    console.log('  Screenshot: feature_home_landing.png');

    const landingInfo = await page.evaluate(() => {
        const projectSelection = document.getElementById('projectSelection');
        const projectGrid = document.getElementById('projectGrid');
        const mainApp = document.getElementById('mainApp');
        const newProjectForm = document.getElementById('newProjectForm');
        const bodyText = document.body.innerText;

        return {
            projectSelectionVisible: projectSelection ? !projectSelection.classList.contains('hidden') && projectSelection.offsetHeight > 0 : false,
            projectGridVisible: projectGrid ? !projectGrid.classList.contains('hidden') && projectGrid.offsetHeight > 0 : false,
            mainAppHidden: mainApp ? mainApp.classList.contains('hidden') : true,
            newProjectFormExists: !!newProjectForm,
            hasCreateButton: bodyText.includes('New Project') || bodyText.includes('Create') || !!document.querySelector('.project-card-new, .new-project-card'),
            hasWelcome: bodyText.includes('Welcome') || bodyText.includes('Research Taxonomy') || bodyText.includes('research') || bodyText.includes('Projects'),
        };
    });

    report('Project selection screen visible', landingInfo.projectSelectionVisible,
        `projectSelection=${landingInfo.projectSelectionVisible}, projectGrid=${landingInfo.projectGridVisible}`);
    report('Main app hidden on load', landingInfo.mainAppHidden);
    report('Create Project UI available', landingInfo.hasCreateButton || landingInfo.newProjectFormExists,
        `button=${landingInfo.hasCreateButton}, form=${landingInfo.newProjectFormExists}`);
    report('Welcome/onboarding content present', landingInfo.hasWelcome);

    // =========================================================================
    // TEST B — Create Project via API
    // =========================================================================
    console.log('\n=== TEST B: Create Project ===');
    const projectName1 = 'Project Mgmt Test ' + Date.now();
    const projResp = await page.evaluate(async (args) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': args.token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: args.name,
                purpose: 'Testing project management',
                seed_categories: 'Category A\nCategory B\nCategory C'
            })
        });
        return { status: r.status, body: await r.json() };
    }, { token: csrf, name: projectName1 });

    console.log('  API response:', JSON.stringify(projResp));

    const pid1 = projResp.body.id || projResp.body.project_id;
    report('Project created successfully', projResp.status === 200 || projResp.status === 201,
        `status=${projResp.status}`);
    report('Response contains project ID', !!pid1, `id=${pid1}`);

    // Refresh the project list so the new project appears
    await page.evaluate(() => { if (typeof loadProjects === 'function') loadProjects(); });
    await page.waitForTimeout(2000);
    await page.screenshot({ path: DIR + '/feature_project_created.png' });
    console.log('  Screenshot: feature_project_created.png');

    // =========================================================================
    // TEST C — Project List
    // =========================================================================
    console.log('\n=== TEST C: Project List ===');

    const listInfo = await page.evaluate((name) => {
        const grid = document.getElementById('projectGrid');
        const gridHTML = grid ? grid.innerHTML : '';
        const gridText = grid ? grid.innerText : '';
        const cards = grid ? grid.querySelectorAll('.project-card') : [];
        return {
            gridExists: !!grid,
            gridVisible: grid ? grid.offsetHeight > 0 : false,
            cardCount: cards.length,
            containsNewProject: gridText.includes(name) || gridHTML.includes(name),
            gridTextSnippet: gridText.substring(0, 500),
        };
    }, projectName1);

    report('Project grid visible', listInfo.gridVisible, `cards=${listInfo.cardCount}`);
    report('Newly created project in list', listInfo.containsNewProject,
        `searched for "${projectName1}"`);

    await page.screenshot({ path: DIR + '/feature_project_list.png' });
    console.log('  Screenshot: feature_project_list.png');

    // =========================================================================
    // TEST D — Select Project
    // =========================================================================
    console.log('\n=== TEST D: Select Project ===');

    if (pid1) {
        // Use selectProject with name argument as the real UI does
        await page.evaluate(
            (args) => selectProject(args.id, args.name),
            { id: pid1, name: projectName1 }
        );
        await page.waitForTimeout(3000);
        await dismissTour(page);
        await page.waitForTimeout(500);

        const selectedInfo = await page.evaluate(() => {
            const mainApp = document.getElementById('mainApp');
            const projectTitle = document.getElementById('projectTitle');
            const statCompanies = document.getElementById('statCompanies');
            const statCategories = document.getElementById('statCategories');
            const projectSelection = document.getElementById('projectSelection');

            // Check for tabs
            const tabButtons = document.querySelectorAll('.tab-btn, [data-tab], button[onclick*="showTab"]');
            const tabLabels = Array.from(tabButtons).map(b => b.innerText.trim()).filter(Boolean);

            return {
                mainAppVisible: mainApp ? !mainApp.classList.contains('hidden') && mainApp.offsetHeight > 0 : false,
                projectSelectionHidden: projectSelection ? projectSelection.classList.contains('hidden') : true,
                titleText: projectTitle ? projectTitle.innerText.trim() : '',
                companyStat: statCompanies ? statCompanies.innerText.trim() : '',
                categoryStat: statCategories ? statCategories.innerText.trim() : '',
                tabCount: tabButtons.length,
                tabLabels: tabLabels,
            };
        });

        report('Main app visible after selection', selectedInfo.mainAppVisible);
        report('Project selection hidden', selectedInfo.projectSelectionHidden);
        report('Header shows project title', selectedInfo.titleText.length > 0,
            `title="${selectedInfo.titleText}"`);
        report('Company stat shown', selectedInfo.companyStat.includes('compan'),
            `stat="${selectedInfo.companyStat}"`);
        report('Category stat shown', selectedInfo.categoryStat.includes('categor'),
            `stat="${selectedInfo.categoryStat}"`);
        report('Tabs visible', selectedInfo.tabCount > 0,
            `count=${selectedInfo.tabCount}, labels=[${selectedInfo.tabLabels.join(', ')}]`);

        await page.screenshot({ path: DIR + '/feature_project_selected.png' });
        console.log('  Screenshot: feature_project_selected.png');
    } else {
        report('Select project (skipped — no pid)', false, 'Project creation failed');
    }

    // =========================================================================
    // TEST E — Project Categories
    // =========================================================================
    console.log('\n=== TEST E: Project Categories ===');

    if (pid1) {
        await page.evaluate(() => showTab('taxonomy'));
        await page.waitForTimeout(2000);
        await dismissTour(page);
        await page.waitForTimeout(500);

        const catInfo = await page.evaluate(() => {
            const bodyText = document.body.innerText;
            const hasCatA = bodyText.includes('Category A');
            const hasCatB = bodyText.includes('Category B');
            const hasCatC = bodyText.includes('Category C');

            // Also check the taxonomy tab specifically
            const taxonomyTab = document.getElementById('taxonomyTab') || document.getElementById('taxonomy');
            const taxonomyText = taxonomyTab ? taxonomyTab.innerText : '';

            return {
                hasCatA,
                hasCatB,
                hasCatC,
                allPresent: hasCatA && hasCatB && hasCatC,
                taxonomyTabText: taxonomyText.substring(0, 500),
            };
        });

        report('Category A found', catInfo.hasCatA);
        report('Category B found', catInfo.hasCatB);
        report('Category C found', catInfo.hasCatC);
        report('All seed categories present', catInfo.allPresent,
            `A=${catInfo.hasCatA}, B=${catInfo.hasCatB}, C=${catInfo.hasCatC}`);

        await page.screenshot({ path: DIR + '/feature_project_categories.png' });
        console.log('  Screenshot: feature_project_categories.png');
    } else {
        report('Project categories (skipped)', false, 'No project ID');
    }

    // =========================================================================
    // TEST F — Back / Close Project
    // =========================================================================
    console.log('\n=== TEST F: Back / Close Project ===');

    if (pid1) {
        const backInfo = await page.evaluate(() => {
            const backBtn = document.querySelector('.back-btn, button[onclick*="switchProject"]');
            const hasSwitchProject = typeof switchProject === 'function';
            return {
                backBtnExists: !!backBtn,
                backBtnText: backBtn ? backBtn.innerText.trim() : '',
                hasSwitchProjectFn: hasSwitchProject,
            };
        });

        report('Back button exists', backInfo.backBtnExists,
            `text="${backInfo.backBtnText}", switchProject fn=${backInfo.hasSwitchProjectFn}`);

        await page.evaluate(() => {
            if (typeof switchProject === 'function') {
                switchProject();
            } else {
                const btn = document.querySelector('.back-btn, button[onclick*="switchProject"]');
                if (btn) btn.click();
            }
        });
        await page.waitForTimeout(2000);
        await dismissTour(page);
        await page.waitForTimeout(500);

        const afterBack = await page.evaluate(() => {
            const projectSelection = document.getElementById('projectSelection');
            const mainApp = document.getElementById('mainApp');
            return {
                projectSelectionVisible: projectSelection ? !projectSelection.classList.contains('hidden') : false,
                mainAppHidden: mainApp ? mainApp.classList.contains('hidden') : true,
            };
        });

        report('Returned to project selection', afterBack.projectSelectionVisible);
        report('Main app hidden after back', afterBack.mainAppHidden);

        await page.screenshot({ path: DIR + '/feature_project_back.png' });
        console.log('  Screenshot: feature_project_back.png');
    } else {
        report('Back/close project (skipped)', false, 'No project ID');
    }

    // =========================================================================
    // TEST G — Create Second Project & Multi-Project List
    // =========================================================================
    console.log('\n=== TEST G: Create Second Project ===');

    const csrf2 = await getCSRF(page);

    const projectName2 = 'Second Project ' + Date.now();
    const projResp2 = await page.evaluate(async (args) => {
        const r = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'X-CSRF-Token': args.token, 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: args.name,
                purpose: 'Second project for multi-project test',
                seed_categories: 'Alpha\nBeta'
            })
        });
        return { status: r.status, body: await r.json() };
    }, { token: csrf2, name: projectName2 });

    const pid2 = projResp2.body.id || projResp2.body.project_id;
    report('Second project created', !!pid2, `id=${pid2}, status=${projResp2.status}`);

    // Refresh project list
    await page.evaluate(() => { if (typeof loadProjects === 'function') loadProjects(); });
    await page.waitForTimeout(2000);

    const multiInfo = await page.evaluate((args) => {
        const grid = document.getElementById('projectGrid');
        const gridText = grid ? grid.innerText : '';
        const cards = grid ? grid.querySelectorAll('.project-card') : [];
        return {
            cardCount: cards.length,
            hasProject1: gridText.includes(args.name1),
            hasProject2: gridText.includes(args.name2),
            bothPresent: gridText.includes(args.name1) && gridText.includes(args.name2),
        };
    }, { name1: projectName1, name2: projectName2 });

    report('Multiple projects in list', multiInfo.cardCount >= 2,
        `cards=${multiInfo.cardCount}`);
    report('First project visible', multiInfo.hasProject1);
    report('Second project visible', multiInfo.hasProject2);
    report('Both projects present', multiInfo.bothPresent);

    await page.screenshot({ path: DIR + '/feature_project_multi.png' });
    console.log('  Screenshot: feature_project_multi.png');

    // =========================================================================
    // CLEANUP — Delete test projects
    // =========================================================================
    console.log('\n=== Cleanup ===');
    const csrf3 = await getCSRF(page);
    for (const pid of [pid1, pid2]) {
        if (pid) {
            const delResp = await page.evaluate(async (args) => {
                const r = await fetch('/api/projects/' + args.pid, {
                    method: 'DELETE',
                    headers: { 'X-CSRF-Token': args.token },
                });
                return r.status;
            }, { token: csrf3, pid });
            console.log(`  Deleted project ${pid}: status=${delResp}`);
        }
    }

    // =========================================================================
    // SUMMARY
    // =========================================================================
    console.log('\n' + '='.repeat(60));
    console.log('TEST RESULTS SUMMARY');
    console.log('='.repeat(60));
    const passed = results.filter(r => r.pass).length;
    const failed = results.filter(r => !r.pass).length;
    results.forEach(r => {
        console.log(`  ${r.pass ? 'PASS' : 'FAIL'}: ${r.name}`);
    });
    console.log('-'.repeat(60));
    console.log(`  Total: ${results.length} | Passed: ${passed} | Failed: ${failed}`);
    console.log('='.repeat(60));

    if (consoleErrors.length > 0) {
        console.log('\nConsole errors detected (' + consoleErrors.length + '):');
        consoleErrors.slice(0, 10).forEach(e => console.log('  ', e));
    }

    await browser.close();
    console.log('\nDone. Screenshots saved to ' + DIR + '/');
    process.exit(failed > 0 ? 1 : 0);
})().catch(e => {
    console.error('FATAL:', e.message);
    process.exit(1);
});
