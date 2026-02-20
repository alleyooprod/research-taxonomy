/**
 * E2E Test: Project Creation and Setup Flow
 * Tests: page load, new project form, template selection, project creation,
 *        project list, project selection, main UI tabs.
 * Run: node e2e/test_project_setup.cjs
 */
const { chromium } = require('playwright');
const path = require('path');

const DIR = path.join(__dirname, '..', 'test-evidence');
const BASE = 'http://127.0.0.1:5001';

const results = [];
function record(name, pass, detail) {
    results.push({ name, pass, detail });
    console.log(`  ${pass ? 'PASS' : 'FAIL'}: ${name}${detail ? ' -- ' + detail : ''}`);
}

async function dismissTour(page) {
    await page.evaluate(() => {
        if (window.driverObj && typeof driverObj.destroy === 'function') driverObj.destroy();
        document.querySelectorAll('.driver-overlay, .driver-popover').forEach(el => el.remove());
        document.body.classList.remove('driver-active');
    });
    await page.waitForTimeout(300);
}

async function getCSRF(page) {
    return page.evaluate(() => {
        const m = document.querySelector('meta[name="csrf-token"]');
        return m ? m.getAttribute('content') : '';
    });
}

async function waitForAppReady(page) {
    await page.waitForFunction(
        () => typeof selectProject === 'function'
           && typeof loadTaxonomy === 'function'
           && typeof showTab === 'function'
           && typeof showNewProjectForm === 'function',
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
        // Grid may be empty if DB has no projects -- acceptable
    });
    await page.waitForTimeout(500);
    await dismissTour(page);
    await page.waitForTimeout(300);
}

(async () => {
    console.log('=== Project Setup E2E Test ===\n');

    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const page = await ctx.newPage();

    // Collect console errors
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    // =========================================================================
    // TEST A -- Page Load and Initial UI
    // =========================================================================
    console.log('--- TEST A: Page Load and Initial UI ---');
    try {
        await page.goto(BASE + '/', { waitUntil: 'networkidle', timeout: 20000 });
        await waitForAppReady(page);

        await page.screenshot({ path: path.join(DIR, 'setup_page_load.png') });
        console.log('  Screenshot: setup_page_load.png');

        const loadInfo = await page.evaluate(() => {
            const projectSelection = document.getElementById('projectSelection');
            const projectGrid = document.getElementById('projectGrid');
            const mainApp = document.getElementById('mainApp');
            const newProjectForm = document.getElementById('newProjectForm');
            const title = document.querySelector('h1');

            return {
                projectSelectionVisible: projectSelection ? !projectSelection.classList.contains('hidden') && projectSelection.offsetHeight > 0 : false,
                projectGridExists: !!projectGrid,
                mainAppHidden: mainApp ? mainApp.classList.contains('hidden') : true,
                newProjectFormHidden: newProjectForm ? newProjectForm.classList.contains('hidden') : true,
                pageTitle: title ? title.textContent.trim() : '',
                hasNewProjectCard: !!document.querySelector('.project-card-new, .new-project-card'),
            };
        });

        record('A1: Page loads successfully', loadInfo.projectSelectionVisible,
            `projectSelection visible=${loadInfo.projectSelectionVisible}`);
        record('A2: Project grid exists', loadInfo.projectGridExists);
        record('A3: Main app hidden on initial load', loadInfo.mainAppHidden);
        record('A4: New project form hidden initially', loadInfo.newProjectFormHidden);
        record('A5: New Project card present', loadInfo.hasNewProjectCard,
            `found .project-card-new=${loadInfo.hasNewProjectCard}`);
    } catch (err) {
        record('A: Page load', false, err.message);
    }

    // Get CSRF token
    const csrf = await getCSRF(page);
    if (!csrf) {
        console.log('  FATAL: No CSRF token found');
        await browser.close();
        process.exit(1);
    }
    console.log('  CSRF token acquired\n');

    // =========================================================================
    // TEST B -- New Project Form Opens
    // =========================================================================
    console.log('--- TEST B: New Project Form ---');
    try {
        // Click the "New Project" card to show the form
        await page.evaluate(() => showNewProjectForm());
        await page.waitForTimeout(2000);

        await page.screenshot({ path: path.join(DIR, 'setup_new_project_form.png') });
        console.log('  Screenshot: setup_new_project_form.png');

        const formInfo = await page.evaluate(() => {
            const form = document.getElementById('newProjectForm');
            const npName = document.getElementById('npName');
            const npPurpose = document.getElementById('npPurpose');
            const npCategories = document.getElementById('npCategories');
            const npTemplate = document.getElementById('npTemplate');
            const templatePicker = document.getElementById('templatePicker');
            const projectSelection = document.getElementById('projectSelection');

            return {
                formVisible: form ? !form.classList.contains('hidden') && form.offsetHeight > 0 : false,
                projectSelectionHidden: projectSelection ? projectSelection.classList.contains('hidden') : true,
                hasNameField: !!npName,
                hasPurposeField: !!npPurpose,
                hasCategoriesField: !!npCategories,
                hasTemplateInput: !!npTemplate,
                templateValue: npTemplate ? npTemplate.value : '',
                hasTemplatePicker: !!templatePicker,
                templatePickerHTML: templatePicker ? templatePicker.innerHTML.substring(0, 500) : '',
            };
        });

        record('B1: New project form visible', formInfo.formVisible);
        record('B2: Project selection hidden when form shows', formInfo.projectSelectionHidden);
        record('B3: Name field exists', formInfo.hasNameField);
        record('B4: Purpose field exists', formInfo.hasPurposeField);
        record('B5: Categories field exists', formInfo.hasCategoriesField);
        record('B6: Template hidden input exists', formInfo.hasTemplateInput,
            `value="${formInfo.templateValue}"`);
        record('B7: Template picker rendered', formInfo.hasTemplatePicker && formInfo.templatePickerHTML.length > 0,
            `picker HTML length=${formInfo.templatePickerHTML.length}`);
    } catch (err) {
        record('B: New project form', false, err.message);
    }

    // =========================================================================
    // TEST C -- Template Picker
    // =========================================================================
    console.log('\n--- TEST C: Template Picker ---');
    try {
        const templateInfo = await page.evaluate(() => {
            const cards = document.querySelectorAll('.template-card');
            const templateKeys = Array.from(cards).map(c => c.dataset.template);
            const selectedCards = document.querySelectorAll('.template-card-selected');
            const selectedKey = selectedCards.length > 0 ? selectedCards[0].dataset.template : '';

            return {
                cardCount: cards.length,
                templateKeys,
                selectedKey,
                hasBlank: templateKeys.includes('blank'),
                hasMarketAnalysis: templateKeys.includes('market_analysis'),
                hasProductAnalysis: templateKeys.includes('product_analysis'),
                hasDesignResearch: templateKeys.includes('design_research'),
            };
        });

        record('C1: Template cards rendered', templateInfo.cardCount >= 4,
            `found ${templateInfo.cardCount} cards: ${templateInfo.templateKeys.join(', ')}`);
        record('C2: Blank template available', templateInfo.hasBlank);
        record('C3: Market Analysis template available', templateInfo.hasMarketAnalysis);
        record('C4: Product Analysis template available', templateInfo.hasProductAnalysis);
        record('C5: Design Research template available', templateInfo.hasDesignResearch);
        record('C6: Default template selected', templateInfo.selectedKey === 'blank',
            `selected="${templateInfo.selectedKey}"`);

        // Select the market_analysis template
        await page.evaluate(() => _selectTemplate('market_analysis'));
        await page.waitForTimeout(500);

        const afterSelect = await page.evaluate(() => {
            const selected = document.querySelector('.template-card-selected');
            const npTemplate = document.getElementById('npTemplate');
            const schemaPreview = document.getElementById('schemaPreview');
            return {
                selectedTemplate: selected ? selected.dataset.template : '',
                hiddenInputValue: npTemplate ? npTemplate.value : '',
                schemaPreviewVisible: schemaPreview ? !schemaPreview.classList.contains('hidden') : false,
            };
        });

        record('C7: Template selection updates visual', afterSelect.selectedTemplate === 'market_analysis',
            `selected="${afterSelect.selectedTemplate}"`);
        record('C8: Hidden input updated', afterSelect.hiddenInputValue === 'market_analysis',
            `value="${afterSelect.hiddenInputValue}"`);
        record('C9: Schema preview shown after template select', afterSelect.schemaPreviewVisible);

        await page.screenshot({ path: path.join(DIR, 'setup_template_selected.png') });
        console.log('  Screenshot: setup_template_selected.png');
    } catch (err) {
        record('C: Template picker', false, err.message);
    }

    // =========================================================================
    // TEST D -- Fill Form and Create Project (market_analysis template)
    // =========================================================================
    console.log('\n--- TEST D: Create Project with Template ---');
    const testProjectName = 'E2E Setup Test ' + Date.now();
    let createdProjectId = null;
    try {
        // Fill form fields
        await page.fill('#npName', testProjectName);
        await page.fill('#npPurpose', 'E2E test for project setup flow');
        await page.fill('#npCategories', 'Category Alpha\nCategory Beta\nCategory Gamma');

        // Ensure market_analysis template is selected
        await page.evaluate(() => _selectTemplate('market_analysis'));
        await page.waitForTimeout(300);

        await page.screenshot({ path: path.join(DIR, 'setup_form_filled.png') });
        console.log('  Screenshot: setup_form_filled.png');

        // Submit the form by calling createProject via the form's submit event
        createdProjectId = await page.evaluate(async () => {
            const data = {
                name: document.getElementById('npName').value,
                purpose: document.getElementById('npPurpose').value,
                outcome: document.getElementById('npOutcome')?.value || '',
                seed_categories: document.getElementById('npCategories').value,
                template: 'market_analysis',
            };

            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const res = await fetch('/api/projects', {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            const result = await res.json();
            return result.id || result.project_id || null;
        });

        record('D1: Project created successfully', !!createdProjectId,
            `id=${createdProjectId}`);

        // Refresh project list and verify the new project appears
        await page.evaluate(() => {
            if (typeof loadProjects === 'function') loadProjects();
        });
        // Navigate back to project selection if we are on new project form
        await page.evaluate(() => {
            if (typeof showProjectSelection === 'function') showProjectSelection();
        });
        await page.waitForTimeout(2000);

        const listInfo = await page.evaluate((name) => {
            const grid = document.getElementById('projectGrid');
            const gridText = grid ? grid.innerText : '';
            const cards = grid ? grid.querySelectorAll('.project-card:not(.project-card-new)') : [];
            return {
                cardCount: cards.length,
                containsNewProject: gridText.includes(name),
            };
        }, testProjectName);

        record('D2: Project appears in project list', listInfo.containsNewProject,
            `searched for "${testProjectName}", cards=${listInfo.cardCount}`);

        await page.screenshot({ path: path.join(DIR, 'setup_project_in_list.png') });
        console.log('  Screenshot: setup_project_in_list.png');
    } catch (err) {
        record('D: Create project', false, err.message);
    }

    // =========================================================================
    // TEST E -- Select Project and Verify Main UI
    // =========================================================================
    console.log('\n--- TEST E: Select Project and Main UI ---');
    try {
        if (!createdProjectId) {
            record('E: Select project (skipped)', false, 'No project ID from creation step');
        } else {
            await page.evaluate(
                (args) => selectProject(args.id, args.name),
                { id: createdProjectId, name: testProjectName }
            );
            await page.waitForTimeout(3000);
            await dismissTour(page);
            await page.waitForTimeout(500);

            await page.screenshot({ path: path.join(DIR, 'setup_project_selected.png') });
            console.log('  Screenshot: setup_project_selected.png');

            const mainUIInfo = await page.evaluate(() => {
                const mainApp = document.getElementById('mainApp');
                const projectSelection = document.getElementById('projectSelection');
                const projectTitle = document.getElementById('projectTitle');
                const statCompanies = document.getElementById('statCompanies');
                const statCategories = document.getElementById('statCategories');

                // Tabs
                const tabButtons = document.querySelectorAll('[data-tab]');
                const tabLabels = Array.from(tabButtons).map(b => ({
                    label: b.textContent.trim(),
                    tab: b.dataset.tab,
                }));

                // Check entity browser activation (market_analysis has multi-type schema)
                const entityBrowser = document.getElementById('entityBrowser');
                const entityTypeBar = document.getElementById('entityTypeBar');

                return {
                    mainAppVisible: mainApp ? !mainApp.classList.contains('hidden') && mainApp.offsetHeight > 0 : false,
                    projectSelectionHidden: projectSelection ? projectSelection.classList.contains('hidden') : true,
                    titleText: projectTitle ? projectTitle.textContent.trim() : '',
                    companyStat: statCompanies ? statCompanies.textContent.trim() : '',
                    categoryStat: statCategories ? statCategories.textContent.trim() : '',
                    tabCount: tabButtons.length,
                    tabLabels,
                    entityBrowserVisible: entityBrowser ? !entityBrowser.classList.contains('hidden') : false,
                    entityTypeBarExists: !!entityTypeBar,
                    entityTypeBarHTML: entityTypeBar ? entityTypeBar.innerHTML.substring(0, 300) : '',
                };
            });

            record('E1: Main app visible', mainUIInfo.mainAppVisible);
            record('E2: Project selection hidden', mainUIInfo.projectSelectionHidden);
            record('E3: Header shows project title', mainUIInfo.titleText.length > 0,
                `title="${mainUIInfo.titleText}"`);
            record('E4: Stats bar shows company count', mainUIInfo.companyStat.length > 0,
                `stat="${mainUIInfo.companyStat}"`);
            record('E5: Stats bar shows category count', mainUIInfo.categoryStat.length > 0,
                `stat="${mainUIInfo.categoryStat}"`);
            record('E6: Tab buttons present', mainUIInfo.tabCount > 0,
                `count=${mainUIInfo.tabCount}, tabs=[${mainUIInfo.tabLabels.map(t => t.tab).join(', ')}]`);

            // Verify key tabs exist
            const tabNames = mainUIInfo.tabLabels.map(t => t.tab);
            record('E7: Companies tab exists', tabNames.includes('companies'));
            record('E8: Taxonomy tab exists', tabNames.includes('taxonomy'));
        }
    } catch (err) {
        record('E: Select project', false, err.message);
    }

    // =========================================================================
    // TEST F -- Tab Navigation
    // =========================================================================
    console.log('\n--- TEST F: Tab Navigation ---');
    try {
        if (!createdProjectId) {
            record('F: Tab navigation (skipped)', false, 'No project ID');
        } else {
            // Switch to taxonomy tab
            await page.evaluate(() => showTab('taxonomy'));
            await page.waitForTimeout(1500);
            await dismissTour(page);

            const taxonomyTab = await page.evaluate(() => {
                const el = document.getElementById('tab-taxonomy');
                return {
                    visible: el ? !el.classList.contains('hidden') && el.offsetHeight > 0 : false,
                    text: el ? el.innerText.substring(0, 200) : '',
                };
            });
            record('F1: Taxonomy tab activates', taxonomyTab.visible);

            // Check seed categories appear
            const catCheck = await page.evaluate(() => {
                const text = document.body.innerText;
                return {
                    hasAlpha: text.includes('Category Alpha'),
                    hasBeta: text.includes('Category Beta'),
                    hasGamma: text.includes('Category Gamma'),
                };
            });
            record('F2: Seed categories visible', catCheck.hasAlpha && catCheck.hasBeta && catCheck.hasGamma,
                `Alpha=${catCheck.hasAlpha}, Beta=${catCheck.hasBeta}, Gamma=${catCheck.hasGamma}`);

            await page.screenshot({ path: path.join(DIR, 'setup_taxonomy_tab.png') });
            console.log('  Screenshot: setup_taxonomy_tab.png');

            // Switch to companies tab
            await page.evaluate(() => showTab('companies'));
            await page.waitForTimeout(1500);
            await dismissTour(page);

            const companiesTab = await page.evaluate(() => {
                const el = document.getElementById('tab-companies');
                return {
                    visible: el ? !el.classList.contains('hidden') && el.offsetHeight > 0 : false,
                };
            });
            record('F3: Companies tab activates', companiesTab.visible);

            await page.screenshot({ path: path.join(DIR, 'setup_companies_tab.png') });
            console.log('  Screenshot: setup_companies_tab.png');

            // Switch to canvas tab
            await page.evaluate(() => showTab('canvas'));
            await page.waitForTimeout(1500);
            await dismissTour(page);

            const canvasTab = await page.evaluate(() => {
                const el = document.getElementById('tab-canvas');
                return {
                    visible: el ? !el.classList.contains('hidden') && el.offsetHeight > 0 : false,
                };
            });
            record('F4: Canvas tab activates', canvasTab.visible);

            await page.screenshot({ path: path.join(DIR, 'setup_canvas_tab.png') });
            console.log('  Screenshot: setup_canvas_tab.png');
        }
    } catch (err) {
        record('F: Tab navigation', false, err.message);
    }

    // =========================================================================
    // TEST G -- Back to Project Selection
    // =========================================================================
    console.log('\n--- TEST G: Back to Project Selection ---');
    try {
        if (!createdProjectId) {
            record('G: Back navigation (skipped)', false, 'No project ID');
        } else {
            await page.evaluate(() => {
                if (typeof switchProject === 'function') switchProject();
            });
            await page.waitForTimeout(2000);
            await dismissTour(page);

            const afterBack = await page.evaluate(() => {
                const projectSelection = document.getElementById('projectSelection');
                const mainApp = document.getElementById('mainApp');
                return {
                    projectSelectionVisible: projectSelection ? !projectSelection.classList.contains('hidden') : false,
                    mainAppHidden: mainApp ? mainApp.classList.contains('hidden') : true,
                };
            });

            record('G1: Project selection visible after back', afterBack.projectSelectionVisible);
            record('G2: Main app hidden after back', afterBack.mainAppHidden);

            await page.screenshot({ path: path.join(DIR, 'setup_back_to_selection.png') });
            console.log('  Screenshot: setup_back_to_selection.png');
        }
    } catch (err) {
        record('G: Back navigation', false, err.message);
    }

    // =========================================================================
    // TEST H -- Create Project with Blank Template (for comparison)
    // =========================================================================
    console.log('\n--- TEST H: Create Project with Blank Template ---');
    let blankProjectId = null;
    const blankProjectName = 'E2E Blank Test ' + Date.now();
    try {
        blankProjectId = await page.evaluate(async (name) => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const r = await fetch('/api/projects', {
                method: 'POST',
                headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    purpose: 'E2E blank template test',
                    seed_categories: 'Cat1\nCat2',
                    template: 'blank',
                })
            });
            const result = await r.json();
            return result.id || result.project_id || null;
        }, blankProjectName);

        record('H1: Blank template project created', !!blankProjectId, `id=${blankProjectId}`);

        if (blankProjectId) {
            // Select it and verify the company view (not entity browser) is shown
            await page.evaluate(
                (args) => selectProject(args.id, args.name),
                { id: blankProjectId, name: blankProjectName }
            );
            await page.waitForTimeout(3000);
            await dismissTour(page);

            await page.evaluate(() => showTab('companies'));
            await page.waitForTimeout(1500);
            await dismissTour(page);

            const blankViewInfo = await page.evaluate(() => {
                const entityBrowser = document.getElementById('entityBrowser');
                const companyView = document.getElementById('companyViewWrapper');
                return {
                    entityBrowserHidden: entityBrowser ? entityBrowser.classList.contains('hidden') : true,
                    companyViewVisible: companyView ? !companyView.classList.contains('hidden') : false,
                };
            });

            record('H2: Blank template shows company view (not entity browser)',
                blankViewInfo.entityBrowserHidden && blankViewInfo.companyViewVisible,
                `entityBrowserHidden=${blankViewInfo.entityBrowserHidden}, companyViewVisible=${blankViewInfo.companyViewVisible}`);

            await page.screenshot({ path: path.join(DIR, 'setup_blank_template.png') });
            console.log('  Screenshot: setup_blank_template.png');
        }
    } catch (err) {
        record('H: Blank template project', false, err.message);
    }

    // =========================================================================
    // CLEANUP -- Delete test projects
    // =========================================================================
    console.log('\n--- Cleanup ---');
    const cleanupCsrf = await getCSRF(page);
    for (const pid of [createdProjectId, blankProjectId]) {
        if (pid) {
            const delResp = await page.evaluate(async (args) => {
                const r = await fetch('/api/projects/' + args.pid, {
                    method: 'DELETE',
                    headers: { 'X-CSRF-Token': args.token },
                });
                return r.status;
            }, { token: cleanupCsrf, pid });
            console.log(`  Deleted project ${pid}: status=${delResp}`);
        }
    }

    // =========================================================================
    // SUMMARY
    // =========================================================================
    console.log('\n' + '='.repeat(60));
    console.log('          PROJECT SETUP TEST RESULTS');
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
        console.log('\nConsole errors during test (' + consoleErrors.length + '):');
        consoleErrors.filter(e =>
            !e.includes('favicon') && !e.includes('clearbit') &&
            !e.includes('MIME type') && !e.includes('Content Security Policy') &&
            !e.includes('Failed to load resource')
        ).slice(0, 10).forEach(e => console.log('  ', e.substring(0, 150)));
    }

    await browser.close();
    console.log('\nDone. Screenshots saved to ' + DIR + '/');
    process.exit(failed > 0 ? 1 : 0);
})().catch(e => {
    console.error('FATAL:', e.message);
    process.exit(1);
});
